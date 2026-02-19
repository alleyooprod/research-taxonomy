"""Company CRUD, sources, star, relationship, trash, duplicates, merge, CSV import."""
import json
import logging
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class CompanyMixin:

    def get_company_by_url(self, url, project_id=None):
        with self._get_conn() as conn:
            if project_id:
                row = conn.execute(
                    "SELECT * FROM companies WHERE url = ? AND project_id = ? AND is_deleted = 0",
                    (url, project_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM companies WHERE url = ? AND is_deleted = 0", (url,)
                ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _derive_logo_url(url):
        try:
            domain = urlparse(url).netloc.replace("www.", "")
            return f"https://logo.clearbit.com/{domain}" if domain else None
        except Exception:
            return None

    def upsert_company(self, data):
        """Upsert a company using INSERT ... ON CONFLICT to avoid race conditions."""
        slug = self._make_slug(data["name"])
        tags_json = json.dumps(data.get("tags", []))
        now = datetime.now().isoformat()
        project_id = data.get("project_id", 1)
        logo_url = data.get("logo_url") or self._derive_logo_url(data.get("url", ""))
        pricing_tiers = data.get("pricing_tiers")
        if pricing_tiers and not isinstance(pricing_tiers, str):
            pricing_tiers = json.dumps(pricing_tiers)

        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO companies
                    (project_id, slug, name, url, what, target, products, funding,
                     geography, tam, category_id, subcategory_id, tags, raw_research,
                     source_url, processed_at, confidence_score,
                     logo_url, employee_range, founded_year, funding_stage,
                     total_funding_usd, hq_city, hq_country, linkedin_url,
                     last_verified_at,
                     pricing_model, pricing_b2c_low, pricing_b2c_high,
                     pricing_b2b_low, pricing_b2b_high, has_free_tier,
                     revenue_model, pricing_tiers, pricing_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, url) DO UPDATE SET
                    name=excluded.name, slug=excluded.slug,
                    what=COALESCE(excluded.what, companies.what),
                    target=COALESCE(excluded.target, companies.target),
                    products=COALESCE(excluded.products, companies.products),
                    funding=COALESCE(excluded.funding, companies.funding),
                    geography=COALESCE(excluded.geography, companies.geography),
                    tam=COALESCE(excluded.tam, companies.tam),
                    category_id=COALESCE(excluded.category_id, companies.category_id),
                    subcategory_id=COALESCE(excluded.subcategory_id, companies.subcategory_id),
                    tags=excluded.tags,
                    raw_research=COALESCE(excluded.raw_research, companies.raw_research),
                    confidence_score=COALESCE(excluded.confidence_score, companies.confidence_score),
                    updated_at=excluded.processed_at,
                    logo_url=COALESCE(excluded.logo_url, companies.logo_url),
                    employee_range=COALESCE(excluded.employee_range, companies.employee_range),
                    founded_year=COALESCE(excluded.founded_year, companies.founded_year),
                    funding_stage=COALESCE(excluded.funding_stage, companies.funding_stage),
                    total_funding_usd=COALESCE(excluded.total_funding_usd, companies.total_funding_usd),
                    hq_city=COALESCE(excluded.hq_city, companies.hq_city),
                    hq_country=COALESCE(excluded.hq_country, companies.hq_country),
                    linkedin_url=COALESCE(excluded.linkedin_url, companies.linkedin_url),
                    last_verified_at=excluded.last_verified_at,
                    pricing_model=COALESCE(excluded.pricing_model, companies.pricing_model),
                    pricing_b2c_low=COALESCE(excluded.pricing_b2c_low, companies.pricing_b2c_low),
                    pricing_b2c_high=COALESCE(excluded.pricing_b2c_high, companies.pricing_b2c_high),
                    pricing_b2b_low=COALESCE(excluded.pricing_b2b_low, companies.pricing_b2b_low),
                    pricing_b2b_high=COALESCE(excluded.pricing_b2b_high, companies.pricing_b2b_high),
                    has_free_tier=COALESCE(excluded.has_free_tier, companies.has_free_tier),
                    revenue_model=COALESCE(excluded.revenue_model, companies.revenue_model),
                    pricing_tiers=COALESCE(excluded.pricing_tiers, companies.pricing_tiers),
                    pricing_notes=COALESCE(excluded.pricing_notes, companies.pricing_notes)
                """,
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
                    data.get("pricing_model"), data.get("pricing_b2c_low"),
                    data.get("pricing_b2c_high"), data.get("pricing_b2b_low"),
                    data.get("pricing_b2b_high"),
                    1 if data.get("has_free_tier") else (0 if data.get("has_free_tier") is not None else None),
                    data.get("revenue_model"), pricing_tiers,
                    data.get("pricing_notes"),
                ),
            )
            return cursor.lastrowid or conn.execute(
                "SELECT id FROM companies WHERE url = ? AND project_id = ?",
                (data["url"], project_id),
            ).fetchone()["id"]

    def get_companies(self, project_id=None, category_id=None, search=None,
                      starred_only=False, needs_enrichment=False,
                      sort_by="name", sort_dir="asc", limit=500, offset=0,
                      tags=None, geography=None, funding_stage=None,
                      relationship_status=None):
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
            query += f" ORDER BY {sort_col} {direction} LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["tags"] = json.loads(d["tags"]) if d["tags"] else []
                filled = sum(1 for f in completeness_fields if d.get(f))
                d["completeness"] = round(filled / len(completeness_fields), 2)
                results.append(d)

            if needs_enrichment:
                results = [r for r in results if r["completeness"] < 0.5]

            return results

    def get_company(self, company_id, include_deleted=False):
        with self._get_conn() as conn:
            query = """SELECT co.*, c.name as category_name, sc.name as subcategory_name
                   FROM companies co
                   LEFT JOIN categories c ON co.category_id = c.id
                   LEFT JOIN categories sc ON co.subcategory_id = sc.id
                   WHERE co.id = ?"""
            if not include_deleted:
                query += " AND co.is_deleted = 0"
            row = conn.execute(query, (company_id,)).fetchone()
            if row:
                d = dict(row)
                d["tags"] = json.loads(d["tags"]) if d["tags"] else []
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
        "pricing_model", "pricing_b2c_low", "pricing_b2c_high",
        "pricing_b2b_low", "pricing_b2b_high", "has_free_tier",
        "revenue_model", "pricing_tiers", "pricing_notes",
    }

    def update_company(self, company_id, fields, save_history=True):
        if save_history:
            self.save_version(company_id, "Edit")
        if "tags" in fields and isinstance(fields["tags"], list):
            fields["tags"] = json.dumps(fields["tags"])
        fields["updated_at"] = datetime.now().isoformat()
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
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE companies SET is_deleted = 1, deleted_at = ? WHERE id = ?",
                (datetime.now().isoformat(), company_id),
            )

    def restore_company(self, company_id):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE companies SET is_deleted = 0, deleted_at = NULL WHERE id = ?",
                (company_id,),
            )

    def get_trash(self, project_id=None):
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

    # --- Duplicates ---

    def find_duplicates(self, project_id=None):
        with self._get_conn() as conn:
            query = "SELECT id, name, url FROM companies WHERE is_deleted = 0"
            params = []
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            rows = conn.execute(query, params).fetchall()

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

    # --- Merge ---

    def merge_companies(self, target_id, source_id):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE company_sources SET company_id = ? WHERE company_id = ?",
                (target_id, source_id),
            )
            conn.execute(
                "UPDATE company_notes SET company_id = ? WHERE company_id = ?",
                (target_id, source_id),
            )
            conn.execute(
                "UPDATE company_versions SET company_id = ? WHERE company_id = ?",
                (target_id, source_id),
            )
            conn.execute(
                "UPDATE company_events SET company_id = ? WHERE company_id = ?",
                (target_id, source_id),
            )
            conn.execute(
                "UPDATE companies SET is_deleted = 1, deleted_at = ?, status = 'merged' WHERE id = ?",
                (datetime.now().isoformat(), source_id),
            )
            return True

    # --- CSV Import ---

    @staticmethod
    def _safe_int(val):
        if not val:
            return None
        try:
            v = int(float(val))
            return v if -10000 < v < 100000 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(val):
        if not val:
            return None
        try:
            v = float(val)
            return v if v >= 0 and v < 1e12 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _validate_url(url):
        try:
            parsed = urlparse(url)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    def import_companies_from_rows(self, rows, project_id):
        imported = 0
        skipped = 0
        for row in rows:
            url = row.get("url", "").strip()[:2000]
            name = row.get("name", "").strip()[:500]
            if not url or not name:
                skipped += 1
                continue
            if not self._validate_url(url):
                logger.warning("CSV import: skipping invalid URL %s", url[:100])
                skipped += 1
                continue
            data = {
                "project_id": project_id,
                "name": name,
                "url": url,
                "what": (row.get("what") or "")[:2000] or None,
                "target": (row.get("target") or "")[:2000] or None,
                "products": (row.get("products") or "")[:2000] or None,
                "funding": (row.get("funding") or "")[:2000] or None,
                "geography": (row.get("geography") or "")[:500] or None,
                "tam": (row.get("tam") or "")[:2000] or None,
                "tags": [t.strip()[:100] for t in row.get("tags", "").split(",") if t.strip()][:20]
                    if isinstance(row.get("tags"), str) else (row.get("tags") or [])[:20],
                "employee_range": (row.get("employee_range") or "")[:100] or None,
                "founded_year": self._safe_int(row.get("founded_year")),
                "funding_stage": (row.get("funding_stage") or "")[:100] or None,
                "total_funding_usd": self._safe_float(row.get("total_funding_usd")),
                "hq_city": (row.get("hq_city") or "")[:200] or None,
                "hq_country": (row.get("hq_country") or "")[:200] or None,
                "linkedin_url": (row.get("linkedin_url") or "")[:500] or None,
            }
            try:
                self.upsert_company(data)
                imported += 1
            except Exception as e:
                logger.warning("CSV import: failed to upsert %s: %s", name[:50], e)
                skipped += 1
        if skipped:
            logger.info("CSV import: %d imported, %d skipped", imported, skipped)
        return imported
