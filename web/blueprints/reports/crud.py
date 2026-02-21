"""Report CRUD — list, get, update, delete."""
import json
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from loguru import logger

from . import reports_bp
from ._shared import _require_project_id, _now_iso, _ensure_table, _row_to_report

# ═══════════════════════════════════════════════════════════════
# Report CRUD
# ═══════════════════════════════════════════════════════════════

@reports_bp.route("/api/synthesis")
def list_reports():
    """List all reports for a project.

    Query: ?project_id=N

    Returns: [{id, project_id, template, title, generated_at, updated_at, is_ai_generated}]
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            """
            SELECT id, project_id, template, title, content_json,
                   generated_at, updated_at, is_ai_generated, metadata_json
            FROM workbench_reports
            WHERE project_id = ?
            ORDER BY generated_at DESC
            """,
            (project_id,),
        ).fetchall()

    # Return summary (without full content) for listing
    result = []
    for row in rows:
        metadata = {}
        if row["metadata_json"]:
            try:
                metadata = json.loads(row["metadata_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        # Count sections from content
        section_count = 0
        if row["content_json"]:
            try:
                content = json.loads(row["content_json"])
                section_count = len(content.get("sections", []))
            except (json.JSONDecodeError, TypeError):
                pass
        result.append({
            "id": row["id"],
            "project_id": row["project_id"],
            "template": row["template"],
            "title": row["title"],
            "generated_at": row["generated_at"],
            "updated_at": row["updated_at"],
            "is_ai_generated": bool(row["is_ai_generated"]),
            "section_count": section_count,
            "metadata": metadata,
        })

    return jsonify(result)


@reports_bp.route("/api/synthesis/<int:report_id>")
def get_report(report_id):
    """Get a single report with full content.

    Returns: full report object with sections.
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_table(conn)
        row = conn.execute(
            """
            SELECT id, project_id, template, title, content_json,
                   generated_at, updated_at, is_ai_generated, metadata_json
            FROM workbench_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()

    if not row:
        return jsonify({"error": f"Report {report_id} not found"}), 404

    return jsonify(_row_to_report(row))


@reports_bp.route("/api/synthesis/<int:report_id>", methods=["PUT"])
def update_report(report_id):
    """Update a report's title or content.

    Body: {title: optional, sections: optional}
    """
    data = request.json or {}
    new_title = data.get("title")
    new_sections = data.get("sections")

    if new_title is None and new_sections is None:
        return jsonify({"error": "Provide title and/or sections to update"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_table(conn)

        row = conn.execute(
            "SELECT id, content_json FROM workbench_reports WHERE id = ?",
            (report_id,),
        ).fetchone()

        if not row:
            return jsonify({"error": f"Report {report_id} not found"}), 404

        now = _now_iso()

        if new_sections is not None:
            # Preserve gathered_data, update sections
            existing_content = {}
            if row["content_json"]:
                try:
                    existing_content = json.loads(row["content_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            existing_content["sections"] = new_sections
            content_json = json.dumps(existing_content)
            conn.execute(
                "UPDATE workbench_reports SET content_json = ?, updated_at = ? WHERE id = ?",
                (content_json, now, report_id),
            )

        if new_title is not None:
            conn.execute(
                "UPDATE workbench_reports SET title = ?, updated_at = ? WHERE id = ?",
                (new_title, now, report_id),
            )

        # Fetch updated row
        updated_row = conn.execute(
            """
            SELECT id, project_id, template, title, content_json,
                   generated_at, updated_at, is_ai_generated, metadata_json
            FROM workbench_reports
            WHERE id = ?
            """,
            (report_id,),
        ).fetchone()

    logger.info("Updated report #%d", report_id)
    return jsonify(_row_to_report(updated_row))


@reports_bp.route("/api/synthesis/<int:report_id>", methods=["DELETE"])
def delete_report(report_id):
    """Delete a report."""
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_table(conn)

        row = conn.execute(
            "SELECT id FROM workbench_reports WHERE id = ?",
            (report_id,),
        ).fetchone()

        if not row:
            return jsonify({"error": f"Report {report_id} not found"}), 404

        conn.execute("DELETE FROM workbench_reports WHERE id = ?", (report_id,))

    logger.info("Deleted report #%d", report_id)
    return jsonify({"deleted": True, "id": report_id})


