"""Dashboard stats, auto-setup, check history, bulk operations."""
import json

from flask import request, jsonify, current_app
from loguru import logger

from . import monitoring_bp
from ._shared import (
    _require_project_id, _now_iso, _is_safe_url,
    _ensure_tables, _row_to_monitor, _row_to_check, _row_to_feed_item,
    _detect_monitor_type_from_url, _URL_ATTR_SLUGS,
)

# ═════════════════════════════════════════════════════════════
# 11. Dashboard Stats
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/stats")
def monitoring_stats():
    """Get monitoring dashboard statistics for a project.

    Query params:
        project_id (required): Project ID

    Returns:
        {
            total_monitors, active_monitors, inactive_monitors,
            monitors_with_errors,
            changes_this_week, changes_total,
            unread_count,
            by_type: {website: N, appstore: N, ...},
            by_severity: {info: N, minor: N, ...},
            recent_changes: [{title, severity, created_at, entity_name}, ...]
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Monitor counts
        total_monitors = conn.execute(
            "SELECT COUNT(*) FROM monitors WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]

        active_monitors = conn.execute(
            "SELECT COUNT(*) FROM monitors WHERE project_id = ? AND is_active = 1",
            (project_id,),
        ).fetchone()[0]

        monitors_with_errors = conn.execute(
            "SELECT COUNT(*) FROM monitors WHERE project_id = ? AND consecutive_errors > 0",
            (project_id,),
        ).fetchone()[0]

        # By monitor type
        type_rows = conn.execute(
            """SELECT monitor_type, COUNT(*) as count
               FROM monitors WHERE project_id = ?
               GROUP BY monitor_type""",
            (project_id,),
        ).fetchall()
        by_type = {row["monitor_type"]: row["count"] for row in type_rows}

        # Change feed stats
        changes_total = conn.execute(
            "SELECT COUNT(*) FROM change_feed WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]

        changes_this_week = conn.execute(
            """SELECT COUNT(*) FROM change_feed
               WHERE project_id = ?
               AND created_at >= datetime('now', '-7 days')""",
            (project_id,),
        ).fetchone()[0]

        unread_count = conn.execute(
            """SELECT COUNT(*) FROM change_feed
               WHERE project_id = ? AND is_read = 0 AND is_dismissed = 0""",
            (project_id,),
        ).fetchone()[0]

        # By severity
        severity_rows = conn.execute(
            """SELECT severity, COUNT(*) as count
               FROM change_feed WHERE project_id = ?
               GROUP BY severity""",
            (project_id,),
        ).fetchall()
        by_severity = {row["severity"]: row["count"] for row in severity_rows}

        # Recent changes (last 5)
        recent_rows = conn.execute(
            """SELECT cf.title, cf.severity, cf.change_type,
                      cf.created_at, e.name as entity_name
               FROM change_feed cf
               JOIN entities e ON e.id = cf.entity_id
               WHERE cf.project_id = ? AND cf.is_dismissed = 0
               ORDER BY cf.created_at DESC
               LIMIT 5""",
            (project_id,),
        ).fetchall()

        recent_changes = [
            {
                "title": row["title"],
                "severity": row["severity"],
                "change_type": row["change_type"],
                "created_at": row["created_at"],
                "entity_name": row["entity_name"],
            }
            for row in recent_rows
        ]

    return jsonify({
        "total_monitors": total_monitors,
        "active_monitors": active_monitors,
        "inactive_monitors": total_monitors - active_monitors,
        "monitors_with_errors": monitors_with_errors,
        "changes_this_week": changes_this_week,
        "changes_total": changes_total,
        "unread_count": unread_count,
        "by_type": by_type,
        "by_severity": by_severity,
        "recent_changes": recent_changes,
    })


# ═════════════════════════════════════════════════════════════
# 12. Auto-Setup Monitors
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/auto-setup", methods=["POST"])
def auto_setup_monitors():
    """Auto-create monitors from entity URL attributes.

    Scans all entities in a project for URL-type attributes (website, url,
    homepage, store_url, etc.), detects the monitor type from the URL,
    and creates monitors for any that don't already exist.

    Query params:
        project_id (required): Project ID

    Request JSON (optional):
        check_interval_hours: int — interval for created monitors (default: 24)
        monitor_types: list — restrict to specific types (default: all)

    Returns:
        {created: N, skipped: N, monitors: [{id, entity_name, target_url, monitor_type}]}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    data = request.json or {}
    check_interval = data.get("check_interval_hours", 24)
    allowed_types = data.get("monitor_types")

    if allowed_types and not isinstance(allowed_types, list):
        return jsonify({"error": "monitor_types must be a list"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Get all entities for this project
        entity_rows = conn.execute(
            """SELECT id, name FROM entities
               WHERE project_id = ? AND is_deleted = 0""",
            (project_id,),
        ).fetchall()

        entity_ids = [r["id"] for r in entity_rows]
        entity_names = {r["id"]: r["name"] for r in entity_rows}

        if not entity_ids:
            return jsonify({"created": 0, "skipped": 0, "monitors": []})

        # Find URL attributes for these entities
        placeholders = ",".join("?" * len(entity_ids))
        slug_placeholders = ",".join("?" * len(_URL_ATTR_SLUGS))

        attr_rows = conn.execute(
            f"""SELECT ea.entity_id, ea.attr_slug, ea.value
                FROM entity_attributes ea
                WHERE ea.entity_id IN ({placeholders})
                AND LOWER(ea.attr_slug) IN ({slug_placeholders})
                AND ea.id IN (
                    SELECT MAX(id) FROM entity_attributes
                    WHERE entity_id IN ({placeholders})
                    GROUP BY entity_id, attr_slug
                )""",
            list(entity_ids) + list(_URL_ATTR_SLUGS) + list(entity_ids),
        ).fetchall()

        # Also check for source URLs stored in entity source field
        source_rows = conn.execute(
            f"""SELECT id, source FROM entities
                WHERE id IN ({placeholders})
                AND source IS NOT NULL
                AND source LIKE 'http%'""",
            entity_ids,
        ).fetchall()

        # Collect candidate URLs
        candidates = []  # list of (entity_id, url)
        for row in attr_rows:
            val = (row["value"] or "").strip()
            if val and (val.startswith("http://") or val.startswith("https://")):
                candidates.append((row["entity_id"], val))

        for row in source_rows:
            source = (row["source"] or "").strip()
            if source:
                candidates.append((row["id"], source))

        # Get existing monitors for dedup (keyed by entity + url + type)
        existing_monitors = conn.execute(
            "SELECT entity_id, target_url, monitor_type FROM monitors WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        existing_set = {
            (row["entity_id"], row["target_url"]) for row in existing_monitors
        }
        existing_typed_set = {
            (row["entity_id"], row["target_url"], row["monitor_type"])
            for row in existing_monitors
        }

        created = 0
        skipped = 0
        created_monitors = []

        # --- URL-based monitors (website, appstore, playstore, rss) ---
        for entity_id, url in candidates:
            if (entity_id, url) in existing_set:
                skipped += 1
                continue

            monitor_type = _detect_monitor_type_from_url(url)
            if allowed_types and monitor_type not in allowed_types:
                skipped += 1
                continue

            cursor = conn.execute(
                """INSERT INTO monitors
                   (project_id, entity_id, monitor_type, target_url,
                    check_interval_hours, is_active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (project_id, entity_id, monitor_type, url, check_interval),
            )
            monitor_id = cursor.lastrowid
            existing_set.add((entity_id, url))
            existing_typed_set.add((entity_id, url, monitor_type))
            created += 1
            created_monitors.append({
                "id": monitor_id,
                "entity_id": entity_id,
                "entity_name": entity_names.get(entity_id, ""),
                "target_url": url,
                "monitor_type": monitor_type,
            })

        # --- Entity-name-based monitors (hackernews, news_search, patent) ---
        for entity_id, entity_name in entity_names.items():
            # Hacker News monitor for every entity
            if (not allowed_types or "hackernews" in allowed_types) and \
               (entity_id, entity_name, "hackernews") not in existing_typed_set:
                cursor = conn.execute(
                    """INSERT INTO monitors
                       (project_id, entity_id, monitor_type, target_url,
                        check_interval_hours, is_active)
                       VALUES (?, ?, 'hackernews', ?, ?, 1)""",
                    (project_id, entity_id, entity_name, check_interval),
                )
                existing_typed_set.add((entity_id, entity_name, "hackernews"))
                created += 1
                created_monitors.append({
                    "id": cursor.lastrowid,
                    "entity_id": entity_id,
                    "entity_name": entity_name,
                    "target_url": entity_name,
                    "monitor_type": "hackernews",
                })

            # News search monitor for every entity
            if (not allowed_types or "news_search" in allowed_types) and \
               (entity_id, entity_name, "news_search") not in existing_typed_set:
                cursor = conn.execute(
                    """INSERT INTO monitors
                       (project_id, entity_id, monitor_type, target_url,
                        check_interval_hours, is_active)
                       VALUES (?, ?, 'news_search', ?, ?, 1)""",
                    (project_id, entity_id, entity_name, check_interval),
                )
                existing_typed_set.add((entity_id, entity_name, "news_search"))
                created += 1
                created_monitors.append({
                    "id": cursor.lastrowid,
                    "entity_id": entity_id,
                    "entity_name": entity_name,
                    "target_url": entity_name,
                    "monitor_type": "news_search",
                })

        # --- Traffic monitors (domain from URL attributes) ---
        if not allowed_types or "traffic" in allowed_types:
            for entity_id, url in candidates:
                # Extract domain from URL
                domain = None
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    domain = parsed.hostname
                except Exception:
                    pass
                if not domain:
                    continue

                if (entity_id, domain, "traffic") not in existing_typed_set:
                    cursor = conn.execute(
                        """INSERT INTO monitors
                           (project_id, entity_id, monitor_type, target_url,
                            check_interval_hours, is_active)
                           VALUES (?, ?, 'traffic', ?, ?, 1)""",
                        (project_id, entity_id, domain, check_interval),
                    )
                    existing_typed_set.add((entity_id, domain, "traffic"))
                    created += 1
                    created_monitors.append({
                        "id": cursor.lastrowid,
                        "entity_id": entity_id,
                        "entity_name": entity_names.get(entity_id, ""),
                        "target_url": domain,
                        "monitor_type": "traffic",
                    })

    logger.info(
        "Auto-setup for project %d: created %d monitors, skipped %d",
        project_id, created, skipped,
    )

    return jsonify({
        "created": created,
        "skipped": skipped,
        "monitors": created_monitors,
    })


# ═════════════════════════════════════════════════════════════
# Additional Endpoints
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors/<int:monitor_id>/checks")
def list_monitor_checks(monitor_id):
    """List recent checks for a specific monitor.

    Query params:
        limit (optional): Max results (default: 20)
        offset (optional): Pagination offset (default: 0)

    Returns:
        List of check result dicts, newest first.
    """
    limit = request.args.get("limit", 20, type=int)
    offset = max(0, request.args.get("offset", 0, type=int))
    limit = max(1, min(limit, 100))

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        monitor = conn.execute(
            "SELECT id FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

        if not monitor:
            return jsonify({"error": f"Monitor {monitor_id} not found"}), 404

        total = conn.execute(
            "SELECT COUNT(*) FROM monitor_checks WHERE monitor_id = ?",
            (monitor_id,),
        ).fetchone()[0]

        rows = conn.execute(
            """SELECT * FROM monitor_checks
               WHERE monitor_id = ?
               ORDER BY checked_at DESC
               LIMIT ? OFFSET ?""",
            (monitor_id, limit, offset),
        ).fetchall()

    checks = [_row_to_check(row) for row in rows]

    return jsonify({
        "monitor_id": monitor_id,
        "checks": checks,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@monitoring_bp.route("/api/monitoring/feed/unread-count")
def unread_count():
    """Get the count of unread, non-dismissed change feed items.

    Query params:
        project_id (required): Project ID

    Returns:
        {count: N}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        count = conn.execute(
            """SELECT COUNT(*) FROM change_feed
               WHERE project_id = ? AND is_read = 0 AND is_dismissed = 0""",
            (project_id,),
        ).fetchone()[0]

    return jsonify({"count": count})


def _bulk_update_feed(field, value):
    """Shared helper for bulk feed updates (read/dismiss)."""
    _ALLOWED_FIELDS = {"is_dismissed", "is_read"}
    if field not in _ALLOWED_FIELDS:
        raise ValueError(f"Invalid field: {field}")

    data = request.json or {}
    ids = data.get("ids", [])
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "ids must be a non-empty list"}), 400
    db = current_app.db
    with db._get_conn() as conn:
        _ensure_tables(conn)
        placeholders = ",".join("?" * len(ids))
        cursor = conn.execute(
            f"UPDATE change_feed SET {field} = ? WHERE id IN ({placeholders})",
            [value] + ids,
        )
    return jsonify({"updated": True, "count": cursor.rowcount})


@monitoring_bp.route("/api/monitoring/feed/bulk-dismiss", methods=["POST"])
def bulk_dismiss_feed():
    """Dismiss multiple feed items at once. Body: {ids: [int]}"""
    return _bulk_update_feed("is_dismissed", 1)


@monitoring_bp.route("/api/monitoring/feed/bulk-read", methods=["POST"])
def bulk_read_feed():
    """Mark multiple feed items as read at once. Body: {ids: [int]}"""
    return _bulk_update_feed("is_read", 1)


@monitoring_bp.route("/api/monitoring/entity/<int:entity_id>/summary")
def entity_monitoring_summary(entity_id):
    """Monitoring summary for a specific entity: monitors, recent changes, health."""
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db
    with db._get_conn() as conn:
        _ensure_tables(conn)

        entity = conn.execute(
            "SELECT id, name FROM entities WHERE id = ? AND project_id = ? AND is_deleted = 0",
            (entity_id, project_id),
        ).fetchone()
        if not entity:
            return jsonify({"error": f"Entity {entity_id} not found in project {project_id}"}), 404

        monitors = [_row_to_monitor(r) for r in conn.execute(
            "SELECT * FROM monitors WHERE entity_id = ? ORDER BY created_at DESC",
            (entity_id,),
        ).fetchall()]

        recent_changes = [_row_to_feed_item(r) for r in conn.execute(
            """SELECT cf.*, e.name as entity_name FROM change_feed cf
               JOIN entities e ON e.id = cf.entity_id
               WHERE cf.entity_id = ? AND cf.is_dismissed = 0
               ORDER BY cf.created_at DESC LIMIT 10""",
            (entity_id,),
        ).fetchall()]

    # Derive health status
    has_errors = any(m["consecutive_errors"] > 0 for m in monitors)
    last_check = max((m["last_checked_at"] for m in monitors if m["last_checked_at"]), default=None)
    if not monitors:
        health_status = "no_monitors"
    elif has_errors:
        health_status = "degraded"
    elif last_check is None:
        health_status = "pending"
    else:
        health_status = "healthy"

    return jsonify({
        "entity_id": entity_id, "entity_name": entity["name"],
        "monitors": monitors, "recent_changes": recent_changes,
        "health": {
            "status": health_status, "last_check": last_check,
            "monitor_count": len(monitors),
            "active_count": sum(1 for m in monitors if m["is_active"]),
            "error_count": sum(1 for m in monitors if m["consecutive_errors"] > 0),
        },
    })
