"""SQLite database operations for the taxonomy builder.

The Database class inherits domain-specific methods from mixin classes
in storage/repos/. This keeps db.py focused on init, migration, and
project CRUD while allowing each feature area to be edited independently.
"""
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from config import DB_PATH, SEED_CATEGORIES
from storage.repos import (
    CompanyMixin, TaxonomyMixin, JobsMixin, SocialMixin, SettingsMixin,
    ResearchMixin, CanvasMixin, TemplateMixin, DimensionsMixin, DiscoveryMixin,
    EntityMixin, ExtractionMixin,
)


class Database(CompanyMixin, TaxonomyMixin, JobsMixin, SocialMixin, SettingsMixin,
               ResearchMixin, CanvasMixin, TemplateMixin, DimensionsMixin, DiscoveryMixin,
               EntityMixin, ExtractionMixin):
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        """Initialize database, migrating existing data if needed."""
        conn = self._get_conn()
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            if "categories" in tables:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
                needs_migration = "project_id" not in cols
            else:
                needs_migration = False

            if needs_migration:
                conn.execute("DROP TABLE IF EXISTS company_sources")
                conn.execute("DROP TABLE IF EXISTS projects")
                self._migrate_to_projects(conn)

            if "categories" in tables:
                self._migrate_phase1(conn)
                self._migrate_phase4(conn)
                self._migrate_phase5(conn)
                self._migrate_phase6(conn)
                self._migrate_phase7_entities(conn)

            if "triage_results" in tables:
                triage_cols = {r[1] for r in conn.execute("PRAGMA table_info(triage_results)").fetchall()}
                if "user_comment" not in triage_cols:
                    conn.execute("ALTER TABLE triage_results ADD COLUMN user_comment TEXT")

            conn.commit()

            schema_path = Path(__file__).parent / "schema.sql"
            conn.executescript(schema_path.read_text())
        finally:
            conn.close()

    def _migrate_to_projects(self, conn):
        """Non-destructive migration: add project support to existing DB."""
        print("  Migrating database to multi-project schema...")

        # Disable FK checks for schema migration, re-enable in finally block
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("SAVEPOINT migrate_projects")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                slug TEXT NOT NULL UNIQUE,
                purpose TEXT,
                outcome TEXT,
                description TEXT,
                seed_categories TEXT,
                example_links TEXT,
                market_keywords TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                is_active INTEGER DEFAULT 1
            )
        """)

        conn.execute(
            """INSERT INTO projects (name, slug, purpose, seed_categories)
               VALUES (?, ?, ?, ?)""",
            (
                "Olly Market Taxonomy",
                "olly-market-taxonomy",
                "Market research for Olly — health, insurance, employee benefits, HR, wellness, wearables",
                json.dumps(SEED_CATEGORIES),
            ),
        )

        conn.execute("""
            CREATE TABLE categories_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
                name TEXT NOT NULL,
                parent_id INTEGER REFERENCES categories_new(id),
                description TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                is_active INTEGER DEFAULT 1,
                merged_into_id INTEGER REFERENCES categories_new(id),
                UNIQUE(project_id, name)
            )
        """)
        conn.execute("""
            INSERT INTO categories_new (id, project_id, name, parent_id, description,
                created_at, updated_at, is_active, merged_into_id)
            SELECT id, 1, name, parent_id, description,
                created_at, updated_at, is_active, merged_into_id
            FROM categories
        """)
        conn.execute("DROP TABLE categories")
        conn.execute("ALTER TABLE categories_new RENAME TO categories")

        conn.execute("""
            CREATE TABLE companies_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
                slug TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                what TEXT,
                target TEXT,
                products TEXT,
                funding TEXT,
                geography TEXT,
                tam TEXT,
                category_id INTEGER REFERENCES categories(id),
                subcategory_id INTEGER REFERENCES categories(id),
                tags TEXT,
                raw_research TEXT,
                source_url TEXT,
                processed_at TEXT,
                updated_at TEXT DEFAULT (datetime('now')),
                confidence_score REAL,
                UNIQUE(project_id, url)
            )
        """)
        conn.execute("""
            INSERT INTO companies_new (id, project_id, slug, name, url, what, target,
                products, funding, geography, tam, category_id, subcategory_id, tags,
                raw_research, source_url, processed_at, updated_at, confidence_score)
            SELECT id, 1, slug, name, url, what, target,
                products, funding, geography, tam, category_id, subcategory_id, tags,
                raw_research, source_url, processed_at, updated_at, confidence_score
            FROM companies
        """)
        conn.execute("DROP TABLE companies")
        conn.execute("ALTER TABLE companies_new RENAME TO companies")

        for table in ["jobs", "taxonomy_changes", "triage_results"]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN project_id INTEGER DEFAULT 1 REFERENCES projects(id)")
                conn.execute(f"UPDATE {table} SET project_id = 1")
            except sqlite3.OperationalError:
                pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                source_type TEXT DEFAULT 'research',
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)

        rows = conn.execute("SELECT id, url, source_url FROM companies").fetchall()
        for r in rows:
            conn.execute(
                "INSERT INTO company_sources (company_id, url, source_type) VALUES (?, ?, 'research')",
                (r["id"], r["url"]),
            )
            if r["source_url"] and r["source_url"] != r["url"]:
                conn.execute(
                    "INSERT INTO company_sources (company_id, url, source_type) VALUES (?, ?, 'research')",
                    (r["id"], r["source_url"]),
                )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_categories_project ON categories(project_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_url ON companies(url)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_category ON companies(category_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_project ON companies(project_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sources_company ON company_sources(company_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_triage_batch ON triage_results(batch_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_triage_project ON triage_results(project_id)")

        conn.execute("RELEASE SAVEPOINT migrate_projects")
        conn.execute("PRAGMA foreign_keys=ON")
        print("  Migration complete. All existing data assigned to 'Olly Market Taxonomy' project.")

    def _migrate_phase1(self, conn):
        """Add firmographic, starring, and category synonym columns if missing."""
        company_cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        new_company_cols = [
            ("logo_url", "TEXT"),
            ("employee_range", "TEXT"),
            ("founded_year", "INTEGER"),
            ("funding_stage", "TEXT"),
            ("total_funding_usd", "REAL"),
            ("hq_city", "TEXT"),
            ("hq_country", "TEXT"),
            ("linkedin_url", "TEXT"),
            ("last_verified_at", "TEXT"),
            ("is_starred", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_type in new_company_cols:
            if col_name not in company_cols:
                conn.execute(f"ALTER TABLE companies ADD COLUMN {col_name} {col_type}")

        cat_cols = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
        if "synonyms" not in cat_cols:
            conn.execute("ALTER TABLE categories ADD COLUMN synonyms TEXT")
        if "color" not in cat_cols:
            conn.execute("ALTER TABLE categories ADD COLUMN color TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_starred ON companies(is_starred)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(project_id, is_deleted, category_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_subcategory ON companies(subcategory_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_batch_status ON jobs(batch_id, status)")

    def _migrate_phase4(self, conn):
        """Add soft delete, status, faceted classification, and relationship columns if missing."""
        company_cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        new_cols = [
            ("is_deleted", "INTEGER DEFAULT 0"),
            ("deleted_at", "TEXT"),
            ("status", "TEXT DEFAULT 'active'"),
            ("business_model", "TEXT"),
            ("company_stage", "TEXT"),
            ("primary_focus", "TEXT"),
            ("relationship_status", "TEXT"),
            ("relationship_note", "TEXT"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in company_cols:
                conn.execute(f"ALTER TABLE companies ADD COLUMN {col_name} {col_type}")

    def _migrate_phase5(self, conn):
        """Add scope notes to categories and enrichment_status to companies."""
        cat_cols = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
        for col_name in ("scope_note", "inclusion_criteria", "exclusion_criteria"):
            if col_name not in cat_cols:
                conn.execute(f"ALTER TABLE categories ADD COLUMN {col_name} TEXT")

        company_cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "enrichment_status" not in company_cols:
            conn.execute("ALTER TABLE companies ADD COLUMN enrichment_status TEXT")

    def _migrate_phase6(self, conn):
        """Add pricing columns to companies, features column to projects."""
        company_cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        pricing_cols = [
            ("pricing_model", "TEXT"),
            ("pricing_b2c_low", "REAL"),
            ("pricing_b2c_high", "REAL"),
            ("pricing_b2b_low", "REAL"),
            ("pricing_b2b_high", "REAL"),
            ("has_free_tier", "INTEGER DEFAULT 0"),
            ("revenue_model", "TEXT"),
            ("pricing_tiers", "TEXT"),
            ("pricing_notes", "TEXT"),
        ]
        for col_name, col_type in pricing_cols:
            if col_name not in company_cols:
                conn.execute(f"ALTER TABLE companies ADD COLUMN {col_name} {col_type}")

        project_cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "features" not in project_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN features TEXT DEFAULT '{}'")

    def _migrate_phase7_entities(self, conn):
        """Add entity schema support to projects."""
        project_cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "entity_schema" not in project_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN entity_schema TEXT")

    # --- Projects ---

    def create_project(self, name, purpose="", outcome="", seed_categories=None,
                       example_links=None, market_keywords=None, description="",
                       entity_schema=None):
        slug = self._make_slug(name)
        cats = seed_categories or []
        schema_json = json.dumps(entity_schema) if entity_schema else None
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO projects (name, slug, purpose, outcome, description,
                   seed_categories, example_links, market_keywords, entity_schema)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name, slug, purpose, outcome, description,
                    json.dumps(cats),
                    json.dumps(example_links or []),
                    json.dumps(market_keywords or []),
                    schema_json,
                ),
            )
            project_id = cursor.lastrowid
            for cat_name in cats:
                conn.execute(
                    "INSERT OR IGNORE INTO categories (project_id, name) VALUES (?, ?)",
                    (project_id, cat_name),
                )

            # Sync entity type definitions if schema provided
            if entity_schema:
                self._sync_entity_types_with_conn(conn, project_id, entity_schema)

            return project_id

    def get_projects(self):
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT p.*, COUNT(co.id) as company_count
                FROM projects p
                LEFT JOIN companies co ON co.project_id = p.id
                WHERE p.is_active = 1
                GROUP BY p.id
                ORDER BY p.created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_project(self, project_id):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            return dict(row) if row else None

    _PROJECT_FIELDS = {
        "name", "purpose", "outcome", "description", "seed_categories",
        "example_links", "market_keywords", "updated_at", "features",
        "entity_schema",
    }

    def update_project(self, project_id, fields):
        fields["updated_at"] = datetime.now().isoformat()
        safe_fields = {k: v for k, v in fields.items() if k in self._PROJECT_FIELDS}
        if not safe_fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in safe_fields)
        values = list(safe_fields.values()) + [project_id]
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE projects SET {set_clause} WHERE id = ?", values
            )

    # --- Helpers ---

    @staticmethod
    def _make_slug(name):
        slug = name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        return slug.strip('-')
