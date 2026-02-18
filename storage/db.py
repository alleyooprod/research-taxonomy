"""SQLite database operations for the taxonomy builder."""
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from config import DB_PATH, SEED_CATEGORIES


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """Initialize database, migrating existing data if needed."""
        conn = self._get_conn()
        try:
            # Check if this is an existing pre-project database
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            if "categories" in tables:
                # Check if categories already has project_id (migration completed)
                cols = {r[1] for r in conn.execute("PRAGMA table_info(categories)").fetchall()}
                needs_migration = "project_id" not in cols
            else:
                needs_migration = False

            if needs_migration:
                # Drop partially-created tables from any failed prior migration
                conn.execute("DROP TABLE IF EXISTS company_sources")
                conn.execute("DROP TABLE IF EXISTS projects")
                self._migrate_to_projects(conn)

            # Phase 1+ migrations: add firmographic, soft-delete, faceted columns
            # Must run BEFORE schema.sql so indexes on new columns succeed
            if "categories" in tables:
                self._migrate_phase1(conn)
                self._migrate_phase4(conn)

            # Triage comment migration
            if "triage_results" in tables:
                triage_cols = {r[1] for r in conn.execute("PRAGMA table_info(triage_results)").fetchall()}
                if "user_comment" not in triage_cols:
                    conn.execute("ALTER TABLE triage_results ADD COLUMN user_comment TEXT")

            # Explicit commit so executescript() sees the new columns
            conn.commit()

            # Run schema (creates tables for fresh DBs, creates indexes)
            schema_path = Path(__file__).parent / "schema.sql"
            conn.executescript(schema_path.read_text())
        finally:
            conn.close()

    def _migrate_to_projects(self, conn):
        """Non-destructive migration: add project support to existing DB."""
        print("  Migrating database to multi-project schema...")

        # Temporarily disable FK enforcement for table recreation
        conn.execute("PRAGMA foreign_keys=OFF")

        # 1. Create projects table
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

        # 2. Create default project
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

        # 3. Migrate categories (recreate to change UNIQUE constraint)
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

        # 4. Migrate companies (recreate to change UNIQUE constraints)
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

        # 5. Add project_id to jobs, taxonomy_changes, triage_results (simple ALTER)
        for table in ["jobs", "taxonomy_changes", "triage_results"]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN project_id INTEGER DEFAULT 1 REFERENCES projects(id)")
                conn.execute(f"UPDATE {table} SET project_id = 1")
            except sqlite3.OperationalError:
                pass  # Column already exists

        # 6. Create company_sources table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                source_type TEXT DEFAULT 'research',
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # 7. Backfill company_sources from existing companies
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

        # 8. Recreate indexes
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

        # Re-enable FK enforcement
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

        # Ensure starred index exists
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

    # --- Projects ---

    def create_project(self, name, purpose="", outcome="", seed_categories=None,
                       example_links=None, market_keywords=None, description=""):
        slug = self._make_slug(name)
        cats = seed_categories or []
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO projects (name, slug, purpose, outcome, description,
                   seed_categories, example_links, market_keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name, slug, purpose, outcome, description,
                    json.dumps(cats),
                    json.dumps(example_links or []),
                    json.dumps(market_keywords or []),
                ),
            )
            project_id = cursor.lastrowid
            # Seed categories
            for cat_name in cats:
                conn.execute(
                    "INSERT OR IGNORE INTO categories (project_id, name) VALUES (?, ?)",
                    (project_id, cat_name),
                )
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
        "example_links", "market_keywords", "updated_at",
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

    # --- Categories ---

    def get_categories(self, project_id=None, active_only=True):
        with self._get_conn() as conn:
            query = "SELECT * FROM categories WHERE 1=1"
            params = []
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            if active_only:
                query += " AND is_active = 1"
            query += " ORDER BY name"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_category_by_name(self, name, project_id=None):
        with self._get_conn() as conn:
            if project_id:
                row = conn.execute(
                    "SELECT * FROM categories WHERE name = ? AND project_id = ? AND is_active = 1",
                    (name, project_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM categories WHERE name = ? AND is_active = 1", (name,)
                ).fetchone()
            return dict(row) if row else None

    def add_category(self, name, parent_id=None, description=None, project_id=None):
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO categories (project_id, name, parent_id, description) VALUES (?, ?, ?, ?)",
                (project_id or 1, name, parent_id, description),
            )
            return cursor.lastrowid

    def merge_categories(self, source_name, target_name, reason="", project_id=None):
        with self._get_conn() as conn:
            q = "SELECT id FROM categories WHERE name = ?"
            params = [source_name]
            if project_id:
                q += " AND project_id = ?"
                params.append(project_id)
            source = conn.execute(q, params).fetchone()

            q2 = "SELECT id FROM categories WHERE name = ?"
            params2 = [target_name]
            if project_id:
                q2 += " AND project_id = ?"
                params2.append(project_id)
            target = conn.execute(q2, params2).fetchone()

            if not source or not target:
                return False
            conn.execute(
                "UPDATE companies SET category_id = ? WHERE category_id = ?",
                (target["id"], source["id"]),
            )
            conn.execute(
                "UPDATE categories SET is_active = 0, merged_into_id = ? WHERE id = ?",
                (target["id"], source["id"]),
            )
            conn.execute(
                "INSERT INTO taxonomy_changes (project_id, change_type, details, reason, affected_category_ids) VALUES (?, ?, ?, ?, ?)",
                (
                    project_id or 1,
                    "merge",
                    json.dumps({"from": source_name, "into": target_name}),
                    reason,
                    json.dumps([source["id"], target["id"]]),
                ),
            )
            return True

    def rename_category(self, old_name, new_name, reason="", project_id=None):
        with self._get_conn() as conn:
            q = "SELECT id FROM categories WHERE name = ?"
            params = [old_name]
            if project_id:
                q += " AND project_id = ?"
                params.append(project_id)
            cat = conn.execute(q, params).fetchone()
            if not cat:
                return False
            conn.execute(
                "UPDATE categories SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, datetime.now().isoformat(), cat["id"]),
            )
            conn.execute(
                "INSERT INTO taxonomy_changes (project_id, change_type, details, reason, affected_category_ids) VALUES (?, ?, ?, ?, ?)",
                (
                    project_id or 1,
                    "rename",
                    json.dumps({"from": old_name, "to": new_name}),
                    reason,
                    json.dumps([cat["id"]]),
                ),
            )
            return True

    def get_category_stats(self, project_id=None):
        with self._get_conn() as conn:
            query = """
                SELECT c.id, c.name, c.parent_id,
                       COUNT(DISTINCT co.id) as company_count
                FROM categories c
                LEFT JOIN companies co
                    ON (co.category_id = c.id OR co.subcategory_id = c.id)
                    AND co.is_deleted = 0
                WHERE c.is_active = 1
            """
            params = []
            if project_id:
                query += " AND c.project_id = ?"
                params.append(project_id)
            query += " GROUP BY c.id ORDER BY c.name"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # --- Companies ---

    def get_company_by_url(self, url, project_id=None):
        with self._get_conn() as conn:
            if project_id:
                row = conn.execute(
                    "SELECT * FROM companies WHERE url = ? AND project_id = ?",
                    (url, project_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM companies WHERE url = ?", (url,)
                ).fetchone()
            return dict(row) if row else None

    def upsert_company(self, data):
        slug = self._make_slug(data["name"])
        tags_json = json.dumps(data.get("tags", []))
        now = datetime.now().isoformat()
        project_id = data.get("project_id", 1)

        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM companies WHERE url = ? AND project_id = ?",
                (data["url"], project_id),
            ).fetchone()

            # Extract logo URL from company domain
            logo_url = data.get("logo_url")
            if not logo_url and data.get("url"):
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(data["url"]).netloc.replace("www.", "")
                    if domain:
                        logo_url = f"https://logo.clearbit.com/{domain}"
                except Exception:
                    pass

            if existing:
                conn.execute(
                    """UPDATE companies SET
                        name=?, slug=?, what=?, target=?, products=?, funding=?,
                        geography=?, tam=?, category_id=?, subcategory_id=?, tags=?,
                        raw_research=?, confidence_score=?, updated_at=?,
                        logo_url=?, employee_range=?, founded_year=?, funding_stage=?,
                        total_funding_usd=?, hq_city=?, hq_country=?, linkedin_url=?,
                        last_verified_at=?
                    WHERE id=?""",
                    (
                        data["name"], slug, data.get("what"), data.get("target"),
                        data.get("products"), data.get("funding"), data.get("geography"),
                        data.get("tam"), data.get("category_id"), data.get("subcategory_id"),
                        tags_json, data.get("raw_research"), data.get("confidence_score"),
                        now, logo_url, data.get("employee_range"),
                        data.get("founded_year"), data.get("funding_stage"),
                        data.get("total_funding_usd"), data.get("hq_city"),
                        data.get("hq_country"), data.get("linkedin_url"), now,
                        existing["id"],
                    ),
                )
                return existing["id"]
            else:
                cursor = conn.execute(
                    """INSERT INTO companies
                        (project_id, slug, name, url, what, target, products, funding,
                         geography, tam, category_id, subcategory_id, tags, raw_research,
                         source_url, processed_at, confidence_score,
                         logo_url, employee_range, founded_year, funding_stage,
                         total_funding_usd, hq_city, hq_country, linkedin_url,
                         last_verified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id, slug, data["name"], data["url"], data.get("what"),
                        data.get("target"), data.get("products"), data.get("funding"),
                        data.get("geography"), data.get("tam"), data.get("category_id"),
                        data.get("subcategory_id"), tags_json, data.get("raw_research"),
                        data.get("source_url"), now, data.get("confidence_score"),
                        logo_url, data.get("employee_range"),
                        data.get("founded_year"), data.get("funding_stage"),
                        data.get("total_funding_usd"), data.get("hq_city"),
                        data.get("hq_country"), data.get("linkedin_url"), now,
                    ),
                )
                return cursor.lastrowid

    def get_companies(self, project_id=None, category_id=None, search=None,
                      starred_only=False, needs_enrichment=False,
                      sort_by="name", sort_dir="asc", limit=500,
                      tags=None, geography=None, funding_stage=None,
                      relationship_status=None):
        # Completeness fields used for scoring
        completeness_fields = [
            "what", "target", "products", "funding", "geography", "tam",
            "employee_range", "founded_year", "funding_stage", "hq_city",
            "hq_country", "linkedin_url",
        ]

        with self._get_conn() as conn:
            query = """
                SELECT co.*,
                    c.name as category_name,
                    sc.name as subcategory_name,
                    (SELECT COUNT(*) FROM company_sources cs WHERE cs.company_id = co.id) as source_count
                FROM companies co
                LEFT JOIN categories c ON co.category_id = c.id
                LEFT JOIN categories sc ON co.subcategory_id = sc.id
                WHERE co.is_deleted = 0
            """
            params = []
            if project_id:
                query += " AND co.project_id = ?"
                params.append(project_id)
            if category_id:
                query += " AND co.category_id = ?"
                params.append(category_id)
            if search:
                query += " AND (co.name LIKE ? OR co.what LIKE ? OR co.products LIKE ?)"
                term = f"%{search}%"
                params.extend([term, term, term])
            if starred_only:
                query += " AND co.is_starred = 1"
            if tags:
                # Filter by tags (AND logic: company must have ALL specified tags)
                for tag in tags:
                    query += " AND co.tags LIKE ?"
                    params.append(f'%"{tag}"%')
            if geography:
                query += " AND co.geography LIKE ?"
                params.append(f"%{geography}%")
            if funding_stage:
                query += " AND co.funding_stage = ?"
                params.append(funding_stage)
            if relationship_status:
                if relationship_status == "any":
                    query += " AND co.relationship_status IS NOT NULL"
                else:
                    query += " AND co.relationship_status = ?"
                    params.append(relationship_status)

            # Sorting
            allowed_sorts = {
                "name": "co.name",
                "category": "c.name",
                "confidence": "co.confidence_score",
                "geography": "co.geography",
                "founded_year": "co.founded_year",
                "updated_at": "co.updated_at",
                "starred": "co.is_starred",
            }
            sort_col = allowed_sorts.get(sort_by, "co.name")
            direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
            query += f" ORDER BY {sort_col} {direction} LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["tags"] = json.loads(d["tags"]) if d["tags"] else []
                # Compute completeness score
                filled = sum(1 for f in completeness_fields if d.get(f))
                d["completeness"] = round(filled / len(completeness_fields), 2)
                results.append(d)

            if needs_enrichment:
                results = [r for r in results if r["completeness"] < 0.5]

            return results

    def get_company(self, company_id):
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT co.*, c.name as category_name, sc.name as subcategory_name
                   FROM companies co
                   LEFT JOIN categories c ON co.category_id = c.id
                   LEFT JOIN categories sc ON co.subcategory_id = sc.id
                   WHERE co.id = ?""",
                (company_id,),
            ).fetchone()
            if row:
                d = dict(row)
                d["tags"] = json.loads(d["tags"]) if d["tags"] else []
                # Include sources
                sources = conn.execute(
                    "SELECT * FROM company_sources WHERE company_id = ? ORDER BY added_at",
                    (company_id,),
                ).fetchall()
                d["sources"] = [dict(s) for s in sources]
                return d
            return None

    _COMPANY_FIELDS = {
        "name", "slug", "what", "target", "products", "funding", "geography",
        "tam", "category_id", "subcategory_id", "tags", "raw_research",
        "confidence_score", "updated_at", "logo_url", "employee_range",
        "founded_year", "funding_stage", "total_funding_usd", "hq_city",
        "hq_country", "linkedin_url", "is_starred", "is_deleted", "deleted_at",
        "status", "url", "last_verified_at", "relationship_status",
        "relationship_note", "relationship_updated_at",
    }

    def update_company(self, company_id, fields, save_history=True):
        if save_history:
            self.save_version(company_id, "Edit")
        if "tags" in fields and isinstance(fields["tags"], list):
            fields["tags"] = json.dumps(fields["tags"])
        fields["updated_at"] = datetime.now().isoformat()
        # Whitelist fields to prevent SQL injection via dynamic column names
        safe_fields = {k: v for k, v in fields.items() if k in self._COMPANY_FIELDS}
        if not safe_fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in safe_fields)
        values = list(safe_fields.values()) + [company_id]
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE companies SET {set_clause} WHERE id = ?", values
            )

    def delete_company(self, company_id):
        """Soft delete: mark as deleted instead of removing."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE companies SET is_deleted = 1, deleted_at = ? WHERE id = ?",
                (datetime.now().isoformat(), company_id),
            )

    def restore_company(self, company_id):
        """Restore a soft-deleted company."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE companies SET is_deleted = 0, deleted_at = NULL WHERE id = ?",
                (company_id,),
            )

    def get_trash(self, project_id=None):
        """Get all soft-deleted companies."""
        with self._get_conn() as conn:
            query = """
                SELECT co.*, c.name as category_name
                FROM companies co
                LEFT JOIN categories c ON co.category_id = c.id
                WHERE co.is_deleted = 1
            """
            params = []
            if project_id:
                query += " AND co.project_id = ?"
                params.append(project_id)
            query += " ORDER BY co.deleted_at DESC"
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["tags"] = json.loads(d["tags"]) if d["tags"] else []
                results.append(d)
            return results

    def permanently_delete(self, company_id):
        """Permanently delete a company (from trash)."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))

    def toggle_star(self, company_id):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT is_starred FROM companies WHERE id = ?", (company_id,)
            ).fetchone()
            if not row:
                return None
            new_val = 0 if row["is_starred"] else 1
            conn.execute(
                "UPDATE companies SET is_starred = ? WHERE id = ?",
                (new_val, company_id),
            )
            return new_val

    def update_relationship(self, company_id, status, note=None):
        """Update relationship status and note for a company."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE companies SET relationship_status = ?, relationship_note = ?, updated_at = ? WHERE id = ?",
                (status or None, note, datetime.now().isoformat(), company_id),
            )
            return {"relationship_status": status, "relationship_note": note}

    def get_all_company_urls(self, project_id=None):
        with self._get_conn() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT url FROM companies WHERE project_id = ?", (project_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT url FROM companies").fetchall()
            return {r["url"] for r in rows}

    # --- Company Sources ---

    def add_company_source(self, company_id, url, source_type="research"):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO company_sources (company_id, url, source_type) VALUES (?, ?, ?)",
                (company_id, url, source_type),
            )

    def get_company_sources(self, company_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM company_sources WHERE company_id = ? ORDER BY added_at",
                (company_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Jobs ---

    def create_jobs(self, batch_id, urls, project_id=None):
        with self._get_conn() as conn:
            for source_url, resolved_url in urls:
                conn.execute(
                    "INSERT INTO jobs (project_id, batch_id, url, source_url) VALUES (?, ?, ?, ?)",
                    (project_id or 1, batch_id, resolved_url, source_url),
                )

    def get_pending_jobs(self, batch_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE batch_id = ? AND status NOT IN ('done', 'error') ORDER BY id",
                (batch_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_failed_jobs(self, batch_id=None):
        with self._get_conn() as conn:
            if batch_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE batch_id = ? AND status = 'error'",
                    (batch_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE status = 'error'"
                ).fetchall()
            return [dict(r) for r in rows]

    def update_job(self, job_id, status, error_message=None, company_id=None):
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE jobs SET status=?, error_message=?, company_id=?,
                   attempts = attempts + CASE WHEN ? = 'error' THEN 1 ELSE 0 END,
                   updated_at=?
                WHERE id=?""",
                (status, error_message, company_id, status, datetime.now().isoformat(), job_id),
            )

    def get_batch_companies(self, batch_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT co.* FROM companies co
                   JOIN jobs j ON j.company_id = co.id
                   WHERE j.batch_id = ? AND j.status = 'done'""",
                (batch_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_batch_summary(self, batch_id):
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                    SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
                    SUM(CASE WHEN status NOT IN ('done','error') THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status='error' AND error_message LIKE 'Timeout:%' THEN 1 ELSE 0 END) as timeouts
                FROM jobs WHERE batch_id = ?""",
                (batch_id,),
            ).fetchone()
            return dict(row)

    def get_recent_batches(self, project_id=None, limit=10):
        with self._get_conn() as conn:
            query = """SELECT batch_id, MIN(created_at) as started,
                COUNT(*) as total,
                SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
                SUM(CASE WHEN status='error' AND error_message LIKE 'Timeout:%' THEN 1 ELSE 0 END) as timeouts,
                SUM(CASE WHEN status NOT IN ('done','error') THEN 1 ELSE 0 END) as pending
                FROM jobs"""
            params = []
            if project_id:
                query += " WHERE project_id = ?"
                params.append(project_id)
            query += " GROUP BY batch_id ORDER BY started DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_batch_details(self, batch_id):
        """Get full details for a batch: jobs + triage results."""
        with self._get_conn() as conn:
            jobs = conn.execute(
                """SELECT j.*, co.name as company_name, co.category_id,
                          c.name as category_name
                   FROM jobs j
                   LEFT JOIN companies co ON j.company_id = co.id
                   LEFT JOIN categories c ON co.category_id = c.id
                   WHERE j.batch_id = ?
                   ORDER BY j.id""",
                (batch_id,),
            ).fetchall()
            triage = conn.execute(
                """SELECT * FROM triage_results WHERE batch_id = ?
                   ORDER BY id""",
                (batch_id,),
            ).fetchall()
            return {
                "jobs": [dict(r) for r in jobs],
                "triage": [dict(r) for r in triage],
            }

    # --- Taxonomy Changes ---

    def log_taxonomy_change(self, change_type, details, reason="", affected_ids=None, project_id=None):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO taxonomy_changes (project_id, change_type, details, reason, affected_category_ids) VALUES (?, ?, ?, ?, ?)",
                (project_id or 1, change_type, json.dumps(details), reason, json.dumps(affected_ids or [])),
            )

    def get_taxonomy_history(self, project_id=None, limit=50):
        with self._get_conn() as conn:
            query = "SELECT * FROM taxonomy_changes"
            params = []
            if project_id:
                query += " WHERE project_id = ?"
                params.append(project_id)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # --- Triage ---

    def save_triage_results(self, batch_id, results, project_id=None):
        """Save a list of TriageResult dicts to the triage_results table."""
        with self._get_conn() as conn:
            for r in results:
                conn.execute(
                    """INSERT INTO triage_results
                       (project_id, batch_id, original_url, resolved_url, status, reason,
                        title, meta_description, scraped_text_preview, is_accessible)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id or 1,
                        batch_id,
                        r["original_url"],
                        r["resolved_url"],
                        r["status"],
                        r["reason"],
                        r["title"],
                        r["meta_description"],
                        r["scraped_text_preview"],
                        1 if r["is_accessible"] else 0,
                    ),
                )

    def get_triage_results(self, batch_id):
        """Get all triage results for a batch."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM triage_results WHERE batch_id = ? ORDER BY id",
                (batch_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_triage_action(self, triage_id, action, replacement_url=None, user_comment=None):
        """Update user's action on a triage result."""
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE triage_results SET user_action = ?, replacement_url = ?,
                   user_comment = ?, updated_at = datetime('now') WHERE id = ?""",
                (action, replacement_url, user_comment, triage_id),
            )

    def get_confirmed_urls(self, batch_id):
        """Get URLs confirmed for processing after triage."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM triage_results WHERE batch_id = ?
                   ORDER BY id""",
                (batch_id,),
            ).fetchall()

        urls = []
        for row in rows:
            r = dict(row)
            if r["user_action"] == "skip":
                continue
            if r["user_action"] == "replace" and r.get("replacement_url"):
                urls.append((r["original_url"], r["replacement_url"]))
            elif r["status"] == "valid" or r["user_action"] == "include":
                urls.append((r["original_url"], r["resolved_url"]))
        return urls

    # --- Company Notes ---

    def get_notes(self, company_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM company_notes WHERE company_id = ? ORDER BY is_pinned DESC, created_at DESC",
                (company_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_note(self, company_id, content):
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO company_notes (company_id, content) VALUES (?, ?)",
                (company_id, content),
            )
            return cursor.lastrowid

    def update_note(self, note_id, content):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE company_notes SET content = ?, updated_at = ? WHERE id = ?",
                (content, datetime.now().isoformat(), note_id),
            )

    def delete_note(self, note_id):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM company_notes WHERE id = ?", (note_id,))

    def toggle_pin_note(self, note_id):
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_pinned FROM company_notes WHERE id = ?", (note_id,)).fetchone()
            if not row:
                return None
            new_val = 0 if row["is_pinned"] else 1
            conn.execute("UPDATE company_notes SET is_pinned = ? WHERE id = ?", (new_val, note_id))
            return new_val

    # --- Company Versions ---

    def save_version(self, company_id, description="Edit"):
        """Snapshot current company state before an edit."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
            if not row:
                return
            snapshot = dict(row)
            snapshot.pop("id", None)
            conn.execute(
                "INSERT INTO company_versions (company_id, snapshot, change_description) VALUES (?, ?, ?)",
                (company_id, json.dumps(snapshot, default=str), description),
            )

    def get_versions(self, company_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM company_versions WHERE company_id = ? ORDER BY created_at DESC",
                (company_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["snapshot"] = json.loads(d["snapshot"])
                result.append(d)
            return result

    def restore_version(self, version_id):
        """Restore a company to a previous version's snapshot."""
        with self._get_conn() as conn:
            ver = conn.execute(
                "SELECT * FROM company_versions WHERE id = ?", (version_id,)
            ).fetchone()
            if not ver:
                return None
            snapshot = json.loads(ver["snapshot"])
            company_id = ver["company_id"]

            # Save current state as a version before restoring
            self.save_version(company_id, f"Before restore to version {version_id}")

            # Apply snapshot
            update_fields = [
                "name", "url", "what", "target", "products", "funding", "geography",
                "tam", "tags", "category_id", "subcategory_id", "confidence_score",
                "employee_range", "founded_year", "funding_stage", "total_funding_usd",
                "hq_city", "hq_country", "linkedin_url", "status",
            ]
            sets = []
            vals = []
            for f in update_fields:
                if f in snapshot:
                    sets.append(f"{f} = ?")
                    vals.append(snapshot[f])
            sets.append("updated_at = ?")
            vals.append(datetime.now().isoformat())
            vals.append(company_id)
            conn.execute(f"UPDATE companies SET {', '.join(sets)} WHERE id = ?", vals)
            return company_id

    # --- Company Events (Lifecycle) ---

    def add_event(self, company_id, event_type, description="", event_date=None):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO company_events (company_id, event_type, description, event_date) VALUES (?, ?, ?, ?)",
                (company_id, event_type, description, event_date),
            )

    def get_events(self, company_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM company_events WHERE company_id = ? ORDER BY COALESCE(event_date, created_at) DESC",
                (company_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_event(self, event_id):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM company_events WHERE id = ?", (event_id,))

    # --- Duplicate Detection ---

    def find_duplicates(self, project_id=None):
        """Find potential duplicate companies by normalized URL or similar name."""
        with self._get_conn() as conn:
            query = "SELECT id, name, url FROM companies WHERE is_deleted = 0"
            params = []
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            rows = conn.execute(query, params).fetchall()

        # Group by normalized URL
        from urllib.parse import urlparse
        url_groups = {}
        for r in rows:
            try:
                parsed = urlparse(r["url"])
                norm = parsed.netloc.replace("www.", "").lower() + parsed.path.rstrip("/").lower()
            except Exception:
                norm = r["url"].lower()
            url_groups.setdefault(norm, []).append(dict(r))

        duplicates = []
        for norm_url, group in url_groups.items():
            if len(group) > 1:
                duplicates.append({"type": "url", "key": norm_url, "companies": group})

        return duplicates

    # --- Merge Companies ---

    def merge_companies(self, target_id, source_id):
        """Merge source company into target. Combines sources and notes; soft-deletes source."""
        with self._get_conn() as conn:
            # Move sources from source to target
            conn.execute(
                "UPDATE company_sources SET company_id = ? WHERE company_id = ?",
                (target_id, source_id),
            )
            # Move notes from source to target
            conn.execute(
                "UPDATE company_notes SET company_id = ? WHERE company_id = ?",
                (target_id, source_id),
            )
            # Soft-delete source
            conn.execute(
                "UPDATE companies SET is_deleted = 1, deleted_at = ?, status = 'merged' WHERE id = ?",
                (datetime.now().isoformat(), source_id),
            )
            return True

    # --- CSV Import ---

    def import_companies_from_rows(self, rows, project_id):
        """Import companies from a list of dicts (from CSV). Returns count of imported."""
        imported = 0
        for row in rows:
            url = row.get("url", "").strip()
            name = row.get("name", "").strip()
            if not url or not name:
                continue
            data = {
                "project_id": project_id,
                "name": name,
                "url": url,
                "what": row.get("what"),
                "target": row.get("target"),
                "products": row.get("products"),
                "funding": row.get("funding"),
                "geography": row.get("geography"),
                "tam": row.get("tam"),
                "tags": [t.strip() for t in row.get("tags", "").split(",") if t.strip()] if isinstance(row.get("tags"), str) else row.get("tags", []),
                "employee_range": row.get("employee_range"),
                "founded_year": int(row["founded_year"]) if row.get("founded_year") else None,
                "funding_stage": row.get("funding_stage"),
                "total_funding_usd": float(row["total_funding_usd"]) if row.get("total_funding_usd") else None,
                "hq_city": row.get("hq_city"),
                "hq_country": row.get("hq_country"),
                "linkedin_url": row.get("linkedin_url"),
            }
            self.upsert_company(data)
            imported += 1
        return imported

    # --- Tags ---

    def get_all_tags(self, project_id=None):
        """Get all tags with counts for a project."""
        with self._get_conn() as conn:
            query = "SELECT tags FROM companies WHERE tags IS NOT NULL AND tags != '[]'"
            params = []
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            rows = conn.execute(query, params).fetchall()

        tag_counts = {}
        for row in rows:
            try:
                tags = json.loads(row["tags"])
            except (json.JSONDecodeError, TypeError):
                continue
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return [{"tag": t, "count": c} for t, c in sorted(tag_counts.items(), key=lambda x: -x[1])]

    def rename_tag(self, old_tag, new_tag, project_id=None):
        """Rename a tag across all companies in a project."""
        with self._get_conn() as conn:
            query = "SELECT id, tags FROM companies WHERE tags LIKE ?"
            params = [f'%"{old_tag}"%']
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            rows = conn.execute(query, params).fetchall()

            updated = 0
            for row in rows:
                try:
                    tags = json.loads(row["tags"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if old_tag in tags:
                    tags = [new_tag if t == old_tag else t for t in tags]
                    conn.execute(
                        "UPDATE companies SET tags = ? WHERE id = ?",
                        (json.dumps(tags), row["id"]),
                    )
                    updated += 1
            return updated

    def merge_tags(self, source_tag, target_tag, project_id=None):
        """Merge source_tag into target_tag (replaces source with target, deduplicates)."""
        with self._get_conn() as conn:
            query = "SELECT id, tags FROM companies WHERE tags LIKE ?"
            params = [f'%"{source_tag}"%']
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            rows = conn.execute(query, params).fetchall()

            updated = 0
            for row in rows:
                try:
                    tags = json.loads(row["tags"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if source_tag in tags:
                    tags = [target_tag if t == source_tag else t for t in tags]
                    tags = list(dict.fromkeys(tags))  # deduplicate preserving order
                    conn.execute(
                        "UPDATE companies SET tags = ? WHERE id = ?",
                        (json.dumps(tags), row["id"]),
                    )
                    updated += 1
            return updated

    def delete_tag(self, tag_name, project_id=None):
        """Remove a tag from all companies in a project."""
        with self._get_conn() as conn:
            query = "SELECT id, tags FROM companies WHERE tags LIKE ?"
            params = [f'%"{tag_name}"%']
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            rows = conn.execute(query, params).fetchall()

            updated = 0
            for row in rows:
                try:
                    tags = json.loads(row["tags"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if tag_name in tags:
                    tags = [t for t in tags if t != tag_name]
                    conn.execute(
                        "UPDATE companies SET tags = ? WHERE id = ?",
                        (json.dumps(tags), row["id"]),
                    )
                    updated += 1
            return updated

    # --- Saved Views ---

    def get_saved_views(self, project_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_views WHERE project_id = ? ORDER BY name",
                (project_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["filters"] = json.loads(d["filters"])
                result.append(d)
            return result

    def save_view(self, project_id, name, filters):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO saved_views (project_id, name, filters)
                   VALUES (?, ?, ?)""",
                (project_id, name, json.dumps(filters)),
            )

    def delete_saved_view(self, view_id):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM saved_views WHERE id = ?", (view_id,))

    # --- Map Layouts ---

    def get_map_layouts(self, project_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM map_layouts WHERE project_id = ? ORDER BY name",
                (project_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["layout_data"] = json.loads(d["layout_data"])
                result.append(d)
            return result

    def save_map_layout(self, project_id, name, layout_data):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO map_layouts (project_id, name, layout_data, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (project_id, name, json.dumps(layout_data), datetime.now().isoformat()),
            )

    # --- Distinct Values (for filter dropdowns) ---

    def get_distinct_geographies(self, project_id=None):
        with self._get_conn() as conn:
            query = "SELECT DISTINCT geography FROM companies WHERE geography IS NOT NULL AND geography != ''"
            params = []
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            query += " ORDER BY geography"
            rows = conn.execute(query, params).fetchall()
            return [r["geography"] for r in rows]

    def get_distinct_funding_stages(self, project_id=None):
        with self._get_conn() as conn:
            query = "SELECT DISTINCT funding_stage FROM companies WHERE funding_stage IS NOT NULL AND funding_stage != ''"
            params = []
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            query += " ORDER BY funding_stage"
            rows = conn.execute(query, params).fetchall()
            return [r["funding_stage"] for r in rows]

    # --- Share Tokens ---

    def create_share_token(self, project_id, label="Shared link", expires_at=None):
        import secrets
        token = secrets.token_urlsafe(32)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO share_tokens (project_id, token, label, expires_at) VALUES (?, ?, ?, ?)",
                (project_id, token, label, expires_at),
            )
        return token

    def get_share_tokens(self, project_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM share_tokens WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def validate_share_token(self, token):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM share_tokens WHERE token = ? AND is_active = 1",
                (token,),
            ).fetchone()
            if not row:
                return None
            r = dict(row)
            if r.get("expires_at"):
                if datetime.fromisoformat(r["expires_at"]) < datetime.now():
                    return None
            return r

    def revoke_share_token(self, token_id):
        with self._get_conn() as conn:
            conn.execute("UPDATE share_tokens SET is_active = 0 WHERE id = ?", (token_id,))

    # --- Activity Log ---

    def log_activity(self, project_id, action, description="", entity_type=None, entity_id=None):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO activity_log (project_id, action, description, entity_type, entity_id)
                VALUES (?, ?, ?, ?, ?)""",
                (project_id, action, description, entity_type, entity_id),
            )

    def get_activity(self, project_id, limit=50, offset=0):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM activity_log WHERE project_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Notification Prefs ---

    def get_notification_prefs(self, project_id):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM notification_prefs WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return dict(row) if row else None

    def save_notification_prefs(self, project_id, slack_webhook_url=None,
                                notify_batch_complete=1, notify_taxonomy_change=1,
                                notify_new_company=0):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO notification_prefs (project_id, slack_webhook_url,
                   notify_batch_complete, notify_taxonomy_change, notify_new_company)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                   slack_webhook_url = excluded.slack_webhook_url,
                   notify_batch_complete = excluded.notify_batch_complete,
                   notify_taxonomy_change = excluded.notify_taxonomy_change,
                   notify_new_company = excluded.notify_new_company,
                   updated_at = datetime('now')""",
                (project_id, slack_webhook_url, notify_batch_complete,
                 notify_taxonomy_change, notify_new_company),
            )

    # --- Taxonomy Quality ---

    def get_taxonomy_quality(self, project_id):
        with self._get_conn() as conn:
            categories = conn.execute("""
                SELECT c.id, c.name, c.parent_id,
                       COUNT(co.id) as company_count,
                       AVG(co.confidence_score) as avg_confidence
                FROM categories c
                LEFT JOIN companies co ON co.category_id = c.id AND co.is_deleted = 0
                WHERE c.project_id = ? AND c.is_active = 1
                GROUP BY c.id
            """, (project_id,)).fetchall()

            empty = []
            overcrowded = []
            low_confidence = []
            total_companies = 0
            total_confidence = 0
            confidence_count = 0

            for cat in categories:
                c = dict(cat)
                if not c["parent_id"]:  # Only check top-level
                    if c["company_count"] == 0:
                        empty.append(c)
                    elif c["company_count"] > 15:
                        overcrowded.append(c)
                total_companies += c["company_count"]
                if c["avg_confidence"] is not None:
                    if c["avg_confidence"] < 0.5:
                        low_confidence.append(c)
                    total_confidence += c["avg_confidence"] * c["company_count"]
                    confidence_count += c["company_count"]

            avg_confidence = (total_confidence / confidence_count) if confidence_count > 0 else None

            return {
                "empty_categories": [{"id": c["id"], "name": c["name"]} for c in empty],
                "overcrowded_categories": [{"id": c["id"], "name": c["name"], "count": c["company_count"]} for c in overcrowded],
                "low_confidence_categories": [{"id": c["id"], "name": c["name"], "avg_confidence": round(c["avg_confidence"], 2)} for c in low_confidence],
                "avg_confidence": round(avg_confidence, 2) if avg_confidence else None,
                "total_companies": total_companies,
                "total_categories": len([c for c in categories if not dict(c).get("parent_id")]),
            }

    # --- Helpers ---

    @staticmethod
    def _make_slug(name):
        slug = name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        return slug.strip('-')

    # --- Reports ---

    def save_report(self, project_id, report_id, category_name, company_count,
                    model, markdown_content, status="complete", error_message=None):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO reports
                   (project_id, report_id, category_name, company_count, model,
                    markdown_content, status, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, report_id, category_name, company_count,
                 model, markdown_content, status, error_message),
            )

    def get_reports(self, project_id=None):
        with self._get_conn() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM reports WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reports ORDER BY created_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_report(self, report_id):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_report(self, report_id):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))

    def get_stats(self, project_id=None):
        with self._get_conn() as conn:
            if project_id:
                companies = conn.execute(
                    "SELECT COUNT(*) FROM companies WHERE project_id = ? AND is_deleted = 0", (project_id,)
                ).fetchone()[0]
                categories = conn.execute(
                    "SELECT COUNT(*) FROM categories WHERE is_active = 1 AND parent_id IS NULL AND project_id = ?",
                    (project_id,),
                ).fetchone()[0]
                latest = conn.execute(
                    "SELECT MAX(processed_at) FROM companies WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0]
            else:
                companies = conn.execute(
                    "SELECT COUNT(*) FROM companies WHERE is_deleted = 0"
                ).fetchone()[0]
                categories = conn.execute(
                    "SELECT COUNT(*) FROM categories WHERE is_active = 1 AND parent_id IS NULL"
                ).fetchone()[0]
                latest = conn.execute(
                    "SELECT MAX(processed_at) FROM companies"
                ).fetchone()[0]
            return {
                "total_companies": companies,
                "total_categories": categories,
                "last_updated": latest,
            }
