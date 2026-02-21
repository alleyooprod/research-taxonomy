"""Change feed — unified feed of detected changes."""
import json

from flask import request, jsonify, current_app
from loguru import logger

from . import monitoring_bp
from ._shared import _require_project_id, _now_iso, _ensure_tables, _row_to_feed_item

# ═════════════════════════════════════════════════════════════
# 7. Change Feed
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/feed")
def get_feed():
    """Get the change feed for a project.

    Query params:
        project_id (required): Project ID
        entity_id (optional): Filter by entity
        change_type (optional): Filter by change type
        severity (optional): Filter by severity
        is_read (optional): Filter by read status (0 or 1)
        limit (optional): Max results (default: 50)
        offset (optional): Pagination offset (default: 0)

    Returns:
        List of change feed items, newest first.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_id = request.args.get("entity_id", type=int)
    change_type = request.args.get("change_type")
    severity = request.args.get("severity")
    is_read = request.args.get("is_read", type=int)
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    # Clamp limit
    limit = max(1, min(limit, 200))

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = """
            SELECT cf.*, e.name as entity_name
            FROM change_feed cf
            JOIN entities e ON e.id = cf.entity_id
            WHERE cf.project_id = ? AND cf.is_dismissed = 0
        """
        params = [project_id]

        if entity_id is not None:
            query += " AND cf.entity_id = ?"
            params.append(entity_id)
        if change_type:
            query += " AND cf.change_type = ?"
            params.append(change_type)
        if severity:
            query += " AND cf.severity = ?"
            params.append(severity)
        if is_read is not None:
            query += " AND cf.is_read = ?"
            params.append(is_read)

        # Get total count for pagination
        count_query = query.replace(
            "SELECT cf.*, e.name as entity_name",
            "SELECT COUNT(*) as total",
        )
        total = conn.execute(count_query, params).fetchone()["total"]

        query += " ORDER BY cf.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

    items = [_row_to_feed_item(row) for row in rows]

    return jsonify({
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


# ═════════════════════════════════════════════════════════════
# 8. Mark Feed Item as Read
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/feed/<int:feed_id>/read", methods=["PUT"])
def mark_feed_read(feed_id):
    """Mark a single change feed item as read.

    Returns:
        {updated: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM change_feed WHERE id = ?", (feed_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Feed item {feed_id} not found"}), 404

        conn.execute(
            "UPDATE change_feed SET is_read = 1 WHERE id = ?", (feed_id,)
        )

    return jsonify({"updated": True, "id": feed_id})


# ═════════════════════════════════════════════════════════════
# 9. Dismiss Feed Item
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/feed/<int:feed_id>/dismiss", methods=["PUT"])
def dismiss_feed_item(feed_id):
    """Dismiss a change feed item (hides from default feed view).

    Returns:
        {updated: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM change_feed WHERE id = ?", (feed_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Feed item {feed_id} not found"}), 404

        conn.execute(
            "UPDATE change_feed SET is_dismissed = 1 WHERE id = ?", (feed_id,)
        )

    return jsonify({"updated": True, "id": feed_id})


# ═════════════════════════════════════════════════════════════
# 10. Mark All Feed Items as Read
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/feed/mark-all-read", methods=["POST"])
def mark_all_feed_read():
    """Mark all unread change feed items as read for a project.

    Query params:
        project_id (required): Project ID

    Returns:
        {updated: true, count: N}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        cursor = conn.execute(
            "UPDATE change_feed SET is_read = 1 WHERE project_id = ? AND is_read = 0",
            (project_id,),
        )
        count = cursor.rowcount

    logger.info("Marked %d feed items as read for project %d", count, project_id)
    return jsonify({"updated": True, "count": count})


