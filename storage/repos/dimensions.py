"""Research dimensions: EAV schema for dynamic company attributes."""
import json
import re
from datetime import datetime


class DimensionsMixin:

    @staticmethod
    def _make_dimension_slug(name):
        slug = name.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '_', slug)
        return slug.strip('_')

    def create_dimension(self, project_id, name, description=None,
                         data_type='text', source='user_defined',
                         ai_prompt=None, enum_values=None):
        slug = self._make_dimension_slug(name)
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO research_dimensions
                    (project_id, name, slug, description, data_type, enum_values, source, ai_prompt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, name, slug, description, data_type,
                 json.dumps(enum_values) if enum_values else None,
                 source, ai_prompt),
            )
            return cursor.lastrowid

    def get_dimensions(self, project_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT d.*,
                    (SELECT COUNT(*) FROM company_dimensions cd WHERE cd.dimension_id = d.id) as value_count
                FROM research_dimensions d
                WHERE d.project_id = ?
                ORDER BY d.created_at""",
                (project_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("enum_values"):
                    d["enum_values"] = json.loads(d["enum_values"])
                results.append(d)
            return results

    def get_dimension(self, dimension_id):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM research_dimensions WHERE id = ?", (dimension_id,)
            ).fetchone()
            if row:
                d = dict(row)
                if d.get("enum_values"):
                    d["enum_values"] = json.loads(d["enum_values"])
                return d
            return None

    def delete_dimension(self, dimension_id):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM company_dimensions WHERE dimension_id = ?", (dimension_id,))
            conn.execute("DELETE FROM research_dimensions WHERE id = ?", (dimension_id,))

    def set_company_dimension(self, company_id, dimension_id, value,
                              confidence=None, source='manual'):
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO company_dimensions (company_id, dimension_id, value, confidence, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_id, dimension_id) DO UPDATE SET
                    value=excluded.value,
                    confidence=excluded.confidence,
                    source=excluded.source,
                    updated_at=excluded.updated_at""",
                (company_id, dimension_id, value, confidence, source, now),
            )

    def get_company_dimensions(self, company_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT cd.*, rd.name as dimension_name, rd.slug, rd.data_type
                FROM company_dimensions cd
                JOIN research_dimensions rd ON cd.dimension_id = rd.id
                WHERE cd.company_id = ?
                ORDER BY rd.name""",
                (company_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_dimension_values(self, dimension_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT cd.*, c.name as company_name, c.url as company_url
                FROM company_dimensions cd
                JOIN companies c ON cd.company_id = c.id
                WHERE cd.dimension_id = ? AND c.is_deleted = 0
                ORDER BY c.name""",
                (dimension_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def bulk_set_dimension(self, dimension_id, values_list):
        """Batch update dimension values. values_list: [{"company_id": int, "value": str, "confidence": float}]"""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            for item in values_list:
                conn.execute(
                    """INSERT INTO company_dimensions (company_id, dimension_id, value, confidence, source, updated_at)
                    VALUES (?, ?, ?, ?, 'ai', ?)
                    ON CONFLICT(company_id, dimension_id) DO UPDATE SET
                        value=excluded.value,
                        confidence=excluded.confidence,
                        source=excluded.source,
                        updated_at=excluded.updated_at""",
                    (item["company_id"], dimension_id, item["value"],
                     item.get("confidence"), now),
                )
