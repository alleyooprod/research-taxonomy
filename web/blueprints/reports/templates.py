"""Template availability endpoint."""
from flask import jsonify, current_app

from . import reports_bp
from ._shared import _require_project_id, _ensure_table, _check_template_availability, _TEMPLATES


# ═══════════════════════════════════════════════════════════════
# Report Templates
# ═══════════════════════════════════════════════════════════════

@reports_bp.route("/api/synthesis/templates")
def report_templates():
    """Return available report templates with availability for this project.

    Query: ?project_id=N

    Returns: [{name, slug, description, available, required_data}]
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_table(conn)
        availability = _check_template_availability(conn, project_id)

    result = []
    for tpl in _TEMPLATES:
        result.append({
            **tpl,
            "available": availability.get(tpl["slug"], False),
        })

    return jsonify(result)


