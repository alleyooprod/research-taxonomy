"""Check execution — trigger individual or batch monitor checks."""
import json

from flask import request, jsonify, current_app
from loguru import logger

from . import monitoring_bp
from ._shared import (
    _require_project_id, _now_iso, _ensure_tables,
    _row_to_monitor, _execute_check, _row_to_check,
)

# ═════════════════════════════════════════════════════════════
# 5. Trigger Single Check
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors/<int:monitor_id>/check", methods=["POST"])
def trigger_check(monitor_id):
    """Trigger an immediate check for a single monitor.

    Fetches current content, computes hash, compares with previous check,
    generates change summary, and optionally creates a change feed entry.

    Returns:
        Check result dict with changes if any.
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Monitor {monitor_id} not found"}), 404

        monitor = dict(row)
        result = _execute_check(monitor, conn)

    status_code = 200 if result["status"] != "error" else 422
    return jsonify(result), status_code


# ═════════════════════════════════════════════════════════════
# 6. Check All Due Monitors
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/check-all", methods=["POST"])
def check_all_monitors():
    """Check all monitors that are due for a check.

    Finds active monitors where last_checked_at is NULL or older than
    check_interval_hours, runs checks sequentially.

    Query params:
        project_id (required): Project ID

    Returns:
        Summary of checks performed and changes found.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Find due monitors: never checked or interval elapsed
        rows = conn.execute(
            """SELECT * FROM monitors
               WHERE project_id = ? AND is_active = 1
               AND (
                   last_checked_at IS NULL
                   OR datetime(last_checked_at, '+' || check_interval_hours || ' hours')
                       <= datetime('now')
               )
               ORDER BY last_checked_at ASC NULLS FIRST""",
            (project_id,),
        ).fetchall()

        total = len(rows)
        checked = 0
        changes_found = 0
        errors = 0
        results = []

        for row in rows:
            monitor = dict(row)
            try:
                check_result = _execute_check(monitor, conn)
                checked += 1
                if check_result.get("changes_detected"):
                    changes_found += 1
                if check_result.get("status") == "error":
                    errors += 1
                results.append({
                    "monitor_id": monitor["id"],
                    "target_url": monitor["target_url"],
                    "status": check_result["status"],
                    "changes_detected": check_result.get("changes_detected", False),
                    "change_summary": check_result.get("change_summary"),
                    "error": check_result.get("error"),
                })
            except Exception as e:
                checked += 1
                errors += 1
                results.append({
                    "monitor_id": monitor["id"],
                    "target_url": monitor["target_url"],
                    "status": "error",
                    "changes_detected": False,
                    "error": str(e)[:300],
                })
                logger.exception(
                    "Check-all failed for monitor %d (%s)",
                    monitor["id"], monitor["target_url"],
                )

    logger.info(
        "Check-all for project %d: %d/%d checked, %d changes, %d errors",
        project_id, checked, total, changes_found, errors,
    )

    return jsonify({
        "project_id": project_id,
        "total_due": total,
        "checked": checked,
        "changes_found": changes_found,
        "errors": errors,
        "results": results,
    })


