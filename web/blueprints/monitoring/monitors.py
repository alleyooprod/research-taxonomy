"""Monitor CRUD — list, create, update, delete."""
import json

from flask import request, jsonify, current_app
from loguru import logger

from . import monitoring_bp
from ._shared import (
    _require_project_id, _now_iso, _is_safe_url,
    _ensure_tables, _row_to_monitor, _validate_url,
    _detect_monitor_type_from_url, _VALID_MONITOR_TYPES,
)

# ═════════════════════════════════════════════════════════════
# 1. List Monitors
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors")
def list_monitors():
    """List all monitors for a project.

    Query params:
        project_id (required): Project ID
        entity_id (optional): Filter by entity
        monitor_type (optional): Filter by type (website|appstore|playstore|rss)
        is_active (optional): Filter by active status (1 or 0)

    Returns:
        List of monitor dicts with entity_name and last check info.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_id = request.args.get("entity_id", type=int)
    monitor_type = request.args.get("monitor_type")
    is_active = request.args.get("is_active", type=int)

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = """
            SELECT m.*, e.name as entity_name
            FROM monitors m
            JOIN entities e ON e.id = m.entity_id
            WHERE m.project_id = ?
        """
        params = [project_id]

        if entity_id is not None:
            query += " AND m.entity_id = ?"
            params.append(entity_id)
        if monitor_type:
            query += " AND m.monitor_type = ?"
            params.append(monitor_type)
        if is_active is not None:
            query += " AND m.is_active = ?"
            params.append(is_active)

        query += " ORDER BY m.created_at DESC"

        rows = conn.execute(query, params).fetchall()

    result = []
    for row in rows:
        monitor = _row_to_monitor(row)
        monitor["entity_name"] = row["entity_name"]
        result.append(monitor)

    return jsonify(result)


# ═════════════════════════════════════════════════════════════
# 2. Create Monitor
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors", methods=["POST"])
def create_monitor():
    """Create a new monitor for an entity.

    Request JSON:
        project_id (required): Project ID
        entity_id (required): Entity to monitor
        monitor_type (required): website | appstore | playstore | rss
        target_url (required): URL or identifier to monitor
        check_interval_hours (optional): Hours between checks (default: 24)

    Returns:
        Created monitor dict (201)
    """
    data = request.json or {}
    project_id = data.get("project_id")
    entity_id = data.get("entity_id")
    monitor_type = data.get("monitor_type")
    target_url = data.get("target_url", "").strip()
    check_interval = data.get("check_interval_hours", 24)

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not monitor_type:
        return jsonify({"error": "monitor_type is required"}), 400
    if monitor_type not in _VALID_MONITOR_TYPES:
        return jsonify({
            "error": f"Invalid monitor_type: {monitor_type}. "
                     f"Valid types: {sorted(_VALID_MONITOR_TYPES)}"
        }), 400

    target_url, url_err = _validate_url(target_url)
    if url_err:
        return jsonify({"error": url_err}), 400

    # SSRF protection: reject private/internal network URLs
    if target_url.startswith(("http://", "https://")) and not _is_safe_url(target_url):
        return jsonify({"error": "URL targets a private or internal network"}), 400

    if not isinstance(check_interval, int) or check_interval < 1:
        return jsonify({"error": "check_interval_hours must be a positive integer"}), 400

    db = current_app.db

    # Validate entity exists and belongs to project
    with db._get_conn() as conn:
        _ensure_tables(conn)

        entity = conn.execute(
            "SELECT id, name FROM entities WHERE id = ? AND project_id = ? AND is_deleted = 0",
            (entity_id, project_id),
        ).fetchone()

        if not entity:
            return jsonify({"error": f"Entity {entity_id} not found in project {project_id}"}), 404

        # Check for duplicate monitor (same entity + URL + type)
        existing = conn.execute(
            """SELECT id FROM monitors
               WHERE entity_id = ? AND target_url = ? AND monitor_type = ?""",
            (entity_id, target_url, monitor_type),
        ).fetchone()

        if existing:
            return jsonify({
                "error": "A monitor already exists for this entity, URL, and type",
                "existing_id": existing["id"],
            }), 409

        cursor = conn.execute(
            """INSERT INTO monitors
               (project_id, entity_id, monitor_type, target_url,
                check_interval_hours, is_active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (project_id, entity_id, monitor_type, target_url, check_interval),
        )
        monitor_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

    monitor = _row_to_monitor(row)
    monitor["entity_name"] = entity["name"]

    logger.info(
        "Created %s monitor #%d for entity %d (%s)",
        monitor_type, monitor_id, entity_id, target_url,
    )
    return jsonify(monitor), 201


# ═════════════════════════════════════════════════════════════
# 3. Delete Monitor
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors/<int:monitor_id>", methods=["DELETE"])
def delete_monitor(monitor_id):
    """Delete a monitor and all its associated checks.

    Cascade delete will remove monitor_checks rows.
    Change feed entries will have monitor_id set to NULL (ON DELETE SET NULL).

    Returns:
        {deleted: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Monitor {monitor_id} not found"}), 404

        conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))

    logger.info("Deleted monitor #%d", monitor_id)
    return jsonify({"deleted": True, "id": monitor_id})


# ═════════════════════════════════════════════════════════════
# 4. Update Monitor
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors/<int:monitor_id>", methods=["PUT"])
def update_monitor(monitor_id):
    """Update a monitor's settings.

    Request JSON (all optional):
        is_active: bool — enable or disable the monitor
        check_interval_hours: int — adjust check frequency
        target_url: str — change the monitored URL

    Returns:
        Updated monitor dict
    """
    data = request.json or {}
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Monitor {monitor_id} not found"}), 404

        updates = []
        params = []

        if "is_active" in data:
            updates.append("is_active = ?")
            params.append(1 if data["is_active"] else 0)

        if "check_interval_hours" in data:
            interval = data["check_interval_hours"]
            if not isinstance(interval, int) or interval < 1:
                return jsonify({"error": "check_interval_hours must be a positive integer"}), 400
            updates.append("check_interval_hours = ?")
            params.append(interval)

        if "target_url" in data:
            new_url, url_err = _validate_url(data["target_url"])
            if url_err:
                return jsonify({"error": url_err}), 400
            updates.append("target_url = ?")
            params.append(new_url)

        if not updates:
            return jsonify({"error": "No valid fields to update"}), 400

        params.append(monitor_id)
        conn.execute(
            f"UPDATE monitors SET {', '.join(updates)} WHERE id = ?",
            params,
        )

        updated_row = conn.execute(
            """SELECT m.*, e.name as entity_name
               FROM monitors m
               JOIN entities e ON e.id = m.entity_id
               WHERE m.id = ?""",
            (monitor_id,),
        ).fetchone()

    monitor = _row_to_monitor(updated_row)
    monitor["entity_name"] = updated_row["entity_name"]

    logger.info("Updated monitor #%d: %s", monitor_id, ", ".join(updates))
    return jsonify(monitor)


