"""Product discovery: context files and analyses."""
import json
from datetime import datetime


class DiscoveryMixin:

    def save_context(self, project_id, name, content, filename=None,
                     context_type='roadmap'):
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO project_contexts (project_id, name, filename, content, context_type)
                VALUES (?, ?, ?, ?, ?)""",
                (project_id, name, filename, content, context_type),
            )
            return cursor.lastrowid

    def get_contexts(self, project_id):
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT id, project_id, name, filename, context_type, created_at,
                    LENGTH(content) as content_length
                FROM project_contexts
                WHERE project_id = ?
                ORDER BY created_at DESC""",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_context(self, context_id):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM project_contexts WHERE id = ?", (context_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_context(self, context_id):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE discovery_analyses SET context_id = NULL WHERE context_id = ?",
                (context_id,),
            )
            conn.execute("DELETE FROM project_contexts WHERE id = ?", (context_id,))

    def save_analysis(self, project_id, analysis_type, title=None,
                      parameters=None, result=None, context_id=None,
                      status='pending'):
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO discovery_analyses
                    (project_id, analysis_type, title, parameters, result, context_id, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, analysis_type, title,
                 json.dumps(parameters) if parameters else None,
                 json.dumps(result) if result else None,
                 context_id, status, now, now),
            )
            return cursor.lastrowid

    def update_analysis(self, analysis_id, **kwargs):
        allowed = {"title", "result", "status", "error_message", "parameters"}
        updates = {}
        for k, v in kwargs.items():
            if k in allowed:
                if k in ("result", "parameters") and v is not None and not isinstance(v, str):
                    v = json.dumps(v)
                updates[k] = v
        if not updates:
            return
        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [analysis_id]
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE discovery_analyses SET {set_clause} WHERE id = ?", values
            )

    def get_analyses(self, project_id, analysis_type=None):
        with self._get_conn() as conn:
            query = """SELECT da.*, pc.name as context_name
                FROM discovery_analyses da
                LEFT JOIN project_contexts pc ON da.context_id = pc.id
                WHERE da.project_id = ?"""
            params = [project_id]
            if analysis_type:
                query += " AND da.analysis_type = ?"
                params.append(analysis_type)
            query += " ORDER BY da.created_at DESC"
            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("parameters") and isinstance(d["parameters"], str):
                    try:
                        d["parameters"] = json.loads(d["parameters"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                if d.get("result") and isinstance(d["result"], str):
                    try:
                        d["result"] = json.loads(d["result"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results

    def get_analysis(self, analysis_id):
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT da.*, pc.name as context_name
                FROM discovery_analyses da
                LEFT JOIN project_contexts pc ON da.context_id = pc.id
                WHERE da.id = ?""",
                (analysis_id,),
            ).fetchone()
            if row:
                d = dict(row)
                if d.get("parameters") and isinstance(d["parameters"], str):
                    try:
                        d["parameters"] = json.loads(d["parameters"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                if d.get("result") and isinstance(d["result"], str):
                    try:
                        d["result"] = json.loads(d["result"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                return d
            return None

    def delete_analysis(self, analysis_id):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM discovery_analyses WHERE id = ?", (analysis_id,))
