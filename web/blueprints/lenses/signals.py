"""Signals Lens endpoints."""
import json
from datetime import datetime, timedelta

from flask import request, jsonify, current_app
from loguru import logger

from . import lenses_bp
from ._shared import _require_project_id

@lenses_bp.route("/api/lenses/signals/timeline")
def signals_timeline():
    """Chronological event timeline combining change feed, attribute updates,
    and evidence captures.

    Query: ?project_id=N&entity_id=N (optional)&limit=50&offset=0

    Returns:
        {
            events: [{type, entity_id, entity_name, title, description,
                      severity, timestamp, metadata}],
            total, limit, offset
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_id = request.args.get("entity_id", type=int)
    limit = request.args.get("limit", 50, type=int)
    offset = max(0, request.args.get("offset", 0, type=int))

    # Clamp limit to a reasonable maximum
    limit = min(limit, 200)

    db = current_app.db
    events = []

    with db._get_conn() as conn:
        entity_filter = ""
        params_base = [project_id]
        if entity_id:
            entity_filter = " AND e.id = ?"
            params_base = [project_id, entity_id]

        # 1) Change feed entries (from monitoring)
        try:
            cf_rows = conn.execute(
                f"""
                SELECT cf.id, cf.monitor_id, cf.change_type, cf.title,
                       cf.description, cf.created_at,
                       cf.severity, cf.details_json, cf.source_url,
                       e.id as entity_id, e.name as entity_name
                FROM change_feed cf
                JOIN entities e ON e.id = cf.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0{entity_filter}
                ORDER BY cf.created_at DESC
                """,
                params_base,
            ).fetchall()

            for row in cf_rows:
                metadata = {}
                if row["details_json"]:
                    try:
                        metadata = json.loads(row["details_json"]) if isinstance(row["details_json"], str) else row["details_json"]
                    except (json.JSONDecodeError, TypeError):
                        pass
                events.append({
                    "type": "change_detected",
                    "entity_id": row["entity_id"],
                    "entity_name": row["entity_name"],
                    "title": f"{row['change_type']}: {row['title']}",
                    "description": row["description"] or "",
                    "severity": row["severity"] or "info",
                    "timestamp": row["created_at"],
                    "metadata": metadata,
                })
        except Exception:
            logger.debug("change_feed table not available for signals timeline")

        # 2) Entity attribute changes
        try:
            ea_rows = conn.execute(
                f"""
                SELECT ea.id, ea.attr_slug, ea.value, ea.source,
                       ea.captured_at, ea.entity_id,
                       e.name as entity_name
                FROM entity_attributes ea
                JOIN entities e ON e.id = ea.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0{entity_filter}
                ORDER BY ea.captured_at DESC
                """,
                params_base,
            ).fetchall()

            for row in ea_rows:
                events.append({
                    "type": "attribute_updated",
                    "entity_id": row["entity_id"],
                    "entity_name": row["entity_name"],
                    "title": f"Attribute: {row['attr_slug']}",
                    "description": f"Set to '{row['value'] or ''}'",
                    "severity": "info",
                    "timestamp": row["captured_at"],
                    "metadata": {"source": row["source"], "attr_slug": row["attr_slug"]},
                })
        except Exception:
            logger.debug("entity_attributes table not available for signals timeline")

        # 3) Evidence captures
        try:
            ev_rows = conn.execute(
                f"""
                SELECT ev.id, ev.evidence_type, ev.source_url, ev.source_name,
                       ev.captured_at, ev.entity_id,
                       e.name as entity_name
                FROM evidence ev
                JOIN entities e ON e.id = ev.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0{entity_filter}
                ORDER BY ev.captured_at DESC
                """,
                params_base,
            ).fetchall()

            for row in ev_rows:
                events.append({
                    "type": "evidence_captured",
                    "entity_id": row["entity_id"],
                    "entity_name": row["entity_name"],
                    "title": f"Evidence: {row['evidence_type']}",
                    "description": row["source_name"] or row["source_url"] or "",
                    "severity": "info",
                    "timestamp": row["captured_at"],
                    "metadata": {
                        "evidence_type": row["evidence_type"],
                        "source_url": row["source_url"],
                    },
                })
        except Exception:
            logger.debug("evidence table not available for signals timeline")

    # Sort all events by timestamp descending
    events.sort(key=lambda e: e["timestamp"] or "", reverse=True)

    total = len(events)
    paged = events[offset:offset + limit]

    logger.info("Signals timeline: {} total events (returning {}) for project {}",
                total, len(paged), project_id)

    return jsonify({
        "events": paged,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@lenses_bp.route("/api/lenses/signals/activity")
def signals_activity():
    """Per-entity activity summary.

    Query: ?project_id=N

    Returns:
        {
            entities: [{entity_id, entity_name, change_count, last_change,
                        monitor_count, evidence_count, attribute_updates}]
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        # Base entities
        entity_rows = conn.execute(
            """SELECT id, name FROM entities
               WHERE project_id = ? AND is_deleted = 0
               ORDER BY name COLLATE NOCASE""",
            (project_id,),
        ).fetchall()

        if not entity_rows:
            return jsonify({"entities": []})

        entity_ids = [r["id"] for r in entity_rows]
        placeholders = ",".join("?" * len(entity_ids))

        # Change feed counts per entity
        change_counts = {}
        last_changes = {}
        try:
            cf_rows = conn.execute(
                f"""
                SELECT cf.entity_id,
                       COUNT(*) as cnt,
                       MAX(cf.created_at) as last_change
                FROM change_feed cf
                WHERE cf.entity_id IN ({placeholders})
                GROUP BY cf.entity_id
                """,
                entity_ids,
            ).fetchall()
            for row in cf_rows:
                change_counts[row["entity_id"]] = row["cnt"]
                last_changes[row["entity_id"]] = row["last_change"]
        except Exception:
            logger.debug("change_feed table not available for signals activity")

        # Monitor counts per entity
        monitor_counts = {}
        try:
            m_rows = conn.execute(
                f"""
                SELECT entity_id, COUNT(*) as cnt
                FROM monitors
                WHERE entity_id IN ({placeholders})
                GROUP BY entity_id
                """,
                entity_ids,
            ).fetchall()
            for row in m_rows:
                monitor_counts[row["entity_id"]] = row["cnt"]
        except Exception:
            logger.debug("monitors table not available for signals activity")

        # Evidence counts per entity
        evidence_counts = {}
        try:
            ev_rows = conn.execute(
                f"""
                SELECT entity_id, COUNT(*) as cnt
                FROM evidence
                WHERE entity_id IN ({placeholders})
                GROUP BY entity_id
                """,
                entity_ids,
            ).fetchall()
            for row in ev_rows:
                evidence_counts[row["entity_id"]] = row["cnt"]
        except Exception:
            logger.debug("evidence table not available for signals activity")

        # Attribute update counts per entity
        attr_counts = {}
        try:
            ea_rows = conn.execute(
                f"""
                SELECT entity_id, COUNT(*) as cnt
                FROM entity_attributes
                WHERE entity_id IN ({placeholders})
                GROUP BY entity_id
                """,
                entity_ids,
            ).fetchall()
            for row in ea_rows:
                attr_counts[row["entity_id"]] = row["cnt"]
        except Exception:
            logger.debug("entity_attributes table not available for signals activity")

    results = []
    for row in entity_rows:
        eid = row["id"]
        results.append({
            "entity_id": eid,
            "entity_name": row["name"],
            "change_count": change_counts.get(eid, 0),
            "last_change": last_changes.get(eid),
            "monitor_count": monitor_counts.get(eid, 0),
            "evidence_count": evidence_counts.get(eid, 0),
            "attribute_updates": attr_counts.get(eid, 0),
        })

    return jsonify({"entities": results})


@lenses_bp.route("/api/lenses/signals/trends")
def signals_trends():
    """Event counts grouped by time period (week buckets).

    Query: ?project_id=N&period=week (default)&entity_id=N (optional)

    Returns:
        {
            periods: [{period_start, period_end, change_count,
                       attribute_count, evidence_count, total}],
            entity_id (if filtered)
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_id = request.args.get("entity_id", type=int)
    # period param accepted but currently only 'week' is implemented
    # Future: day, month
    _period = request.args.get("period", "week")

    db = current_app.db

    # SQLite: strftime('%Y-%W', date) gives year-week
    # We'll use date(timestamp, 'weekday 0', '-6 days') to get Monday of each week

    with db._get_conn() as conn:
        entity_filter = ""
        params_base = [project_id]
        if entity_id:
            entity_filter = " AND e.id = ?"
            params_base = [project_id, entity_id]

        # Collect all timestamped events with their week bucket
        week_data = {}  # week_start → {change_count, attribute_count, evidence_count}

        # 1) Change feed events by week
        try:
            cf_rows = conn.execute(
                f"""
                SELECT date(cf.created_at, 'weekday 0', '-6 days') as week_start,
                       COUNT(*) as cnt
                FROM change_feed cf
                JOIN entities e ON e.id = cf.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0{entity_filter}
                  AND cf.created_at IS NOT NULL
                GROUP BY week_start
                ORDER BY week_start
                """,
                params_base,
            ).fetchall()
            for row in cf_rows:
                ws = row["week_start"]
                if ws:
                    week_data.setdefault(ws, {"change_count": 0, "attribute_count": 0, "evidence_count": 0})
                    week_data[ws]["change_count"] = row["cnt"]
        except Exception:
            logger.debug("change_feed table not available for signals trends")

        # 2) Attribute updates by week
        try:
            ea_rows = conn.execute(
                f"""
                SELECT date(ea.captured_at, 'weekday 0', '-6 days') as week_start,
                       COUNT(*) as cnt
                FROM entity_attributes ea
                JOIN entities e ON e.id = ea.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0{entity_filter}
                  AND ea.captured_at IS NOT NULL
                GROUP BY week_start
                ORDER BY week_start
                """,
                params_base,
            ).fetchall()
            for row in ea_rows:
                ws = row["week_start"]
                if ws:
                    week_data.setdefault(ws, {"change_count": 0, "attribute_count": 0, "evidence_count": 0})
                    week_data[ws]["attribute_count"] = row["cnt"]
        except Exception:
            logger.debug("entity_attributes table not available for signals trends")

        # 3) Evidence captures by week
        try:
            ev_rows = conn.execute(
                f"""
                SELECT date(ev.captured_at, 'weekday 0', '-6 days') as week_start,
                       COUNT(*) as cnt
                FROM evidence ev
                JOIN entities e ON e.id = ev.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0{entity_filter}
                  AND ev.captured_at IS NOT NULL
                GROUP BY week_start
                ORDER BY week_start
                """,
                params_base,
            ).fetchall()
            for row in ev_rows:
                ws = row["week_start"]
                if ws:
                    week_data.setdefault(ws, {"change_count": 0, "attribute_count": 0, "evidence_count": 0})
                    week_data[ws]["evidence_count"] = row["cnt"]
        except Exception:
            logger.debug("evidence table not available for signals trends")

    # Build sorted period list
    periods = []
    for week_start in sorted(week_data.keys()):
        counts = week_data[week_start]
        total = counts["change_count"] + counts["attribute_count"] + counts["evidence_count"]
        periods.append({
            "period_start": week_start,
            "period_end": week_start[:10],  # same format; end = start + 6 days
            "change_count": counts["change_count"],
            "attribute_count": counts["attribute_count"],
            "evidence_count": counts["evidence_count"],
            "total": total,
        })

    # Compute proper period_end (start + 6 days)
    for p in periods:
        try:
            start_dt = datetime.strptime(p["period_start"], "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=6)
            p["period_end"] = end_dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    result = {"periods": periods}
    if entity_id:
        result["entity_id"] = entity_id

    return jsonify(result)


@lenses_bp.route("/api/lenses/signals/heatmap")
def signals_heatmap():
    """Entity x event-type heatmap matrix.

    Query: ?project_id=N

    Returns:
        {
            entities: [name],
            event_types: [str],
            matrix: [[count]],
            raw: [{entity_id, entity_name, event_type, count}]
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        # Base entities
        entity_rows = conn.execute(
            """SELECT id, name FROM entities
               WHERE project_id = ? AND is_deleted = 0
               ORDER BY name COLLATE NOCASE""",
            (project_id,),
        ).fetchall()

        if not entity_rows:
            return jsonify({
                "entities": [],
                "event_types": [],
                "matrix": [],
                "raw": [],
            })

        entity_ids = [r["id"] for r in entity_rows]
        placeholders = ",".join("?" * len(entity_ids))

        # Collect counts per entity per event type
        raw_data = {}  # (entity_id, event_type) → count

        # 1) Change feed events
        try:
            cf_rows = conn.execute(
                f"""
                SELECT cf.entity_id, COUNT(*) as cnt
                FROM change_feed cf
                WHERE cf.entity_id IN ({placeholders})
                GROUP BY cf.entity_id
                """,
                entity_ids,
            ).fetchall()
            for row in cf_rows:
                raw_data[(row["entity_id"], "change_detected")] = row["cnt"]
        except Exception:
            logger.debug("change_feed table not available for signals heatmap")

        # 2) Attribute updates
        try:
            ea_rows = conn.execute(
                f"""
                SELECT entity_id, COUNT(*) as cnt
                FROM entity_attributes
                WHERE entity_id IN ({placeholders})
                GROUP BY entity_id
                """,
                entity_ids,
            ).fetchall()
            for row in ea_rows:
                raw_data[(row["entity_id"], "attribute_updated")] = row["cnt"]
        except Exception:
            logger.debug("entity_attributes table not available for signals heatmap")

        # 3) Evidence captures
        try:
            ev_rows = conn.execute(
                f"""
                SELECT entity_id, COUNT(*) as cnt
                FROM evidence
                WHERE entity_id IN ({placeholders})
                GROUP BY entity_id
                """,
                entity_ids,
            ).fetchall()
            for row in ev_rows:
                raw_data[(row["entity_id"], "evidence_captured")] = row["cnt"]
        except Exception:
            logger.debug("evidence table not available for signals heatmap")

    # Build matrix
    entity_names = [r["name"] for r in entity_rows]
    event_types = ["change_detected", "attribute_updated", "evidence_captured"]

    eid_to_idx = {r["id"]: i for i, r in enumerate(entity_rows)}
    matrix = [[0] * len(event_types) for _ in range(len(entity_rows))]

    raw_list = []
    for (eid, etype), count in raw_data.items():
        idx = eid_to_idx.get(eid)
        if idx is not None:
            col = event_types.index(etype)
            matrix[idx][col] = count
            raw_list.append({
                "entity_id": eid,
                "entity_name": entity_names[idx],
                "event_type": etype,
                "count": count,
            })

    # Sort raw list by entity name then event type
    raw_list.sort(key=lambda r: (r["entity_name"].lower(), r["event_type"]))

    return jsonify({
        "entities": entity_names,
        "event_types": event_types,
        "matrix": matrix,
        "raw": raw_list,
    })


@lenses_bp.route("/api/lenses/signals/summary")
def signals_summary():
    """Market-level change summary: what shifted across all entities.

    Aggregates changes by field, calculates most active entities,
    identifies recently changed attributes, and finds common change patterns.

    Query: ?project_id=N&days=30

    Returns:
        {
            period_days, entity_count, total_events,
            most_active_entities: [{entity_id, entity_name, event_count}],
            top_changed_fields: [{field_name, change_count, entities_affected}],
            recent_highlights: [{entity_name, change_type, field_name, description, timestamp}],
            source_breakdown: {change_detected, attribute_updated, evidence_captured},
            severity_breakdown: {critical, high, medium, low, info}
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    days = request.args.get("days", 30, type=int)
    days = min(max(days, 1), 365)

    db = current_app.db

    with db._get_conn() as conn:
        # 1. Entity activity counts
        entity_rows = conn.execute(
            """SELECT id, name FROM entities
               WHERE project_id = ? AND is_deleted = 0
               ORDER BY name COLLATE NOCASE""",
            (project_id,),
        ).fetchall()

        if not entity_rows:
            return jsonify({
                "period_days": days,
                "entity_count": 0,
                "total_events": 0,
                "most_active_entities": [],
                "top_changed_fields": [],
                "recent_highlights": [],
                "source_breakdown": {"change_detected": 0, "attribute_updated": 0, "evidence_captured": 0},
                "severity_breakdown": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            })

        entity_ids = [r["id"] for r in entity_rows]
        entity_map = {r["id"]: r["name"] for r in entity_rows}
        placeholders = ",".join("?" * len(entity_ids))

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        # 2. Change feed analysis
        change_counts = {}  # entity_id -> count
        field_changes = {}  # field_name -> {count, entity_ids}
        severity_breakdown = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        recent_highlights = []

        try:
            cf_rows = conn.execute(
                f"""SELECT cf.change_type, cf.title, cf.description,
                           cf.created_at, cf.severity, cf.details_json,
                           cf.source_url, cf.entity_id
                    FROM change_feed cf
                    WHERE cf.entity_id IN ({placeholders})
                      AND cf.created_at >= ?
                    ORDER BY cf.created_at DESC""",
                entity_ids + [cutoff],
            ).fetchall()

            for row in cf_rows:
                eid = row["entity_id"]
                change_counts[eid] = change_counts.get(eid, 0) + 1

                fname = row["title"] or "unknown"
                if fname not in field_changes:
                    field_changes[fname] = {"count": 0, "entity_ids": set()}
                field_changes[fname]["count"] += 1
                field_changes[fname]["entity_ids"].add(eid)

                sev = row["severity"] or "info"
                if sev in severity_breakdown:
                    severity_breakdown[sev] += 1

                if len(recent_highlights) < 10:
                    recent_highlights.append({
                        "entity_name": entity_map.get(eid, ""),
                        "change_type": row["change_type"],
                        "field_name": fname,
                        "description": row["description"] or "",
                        "timestamp": row["created_at"],
                    })
        except Exception:
            logger.debug("change_feed not available for signals summary")

        # 3. Attribute update counts
        attr_counts = {}  # entity_id -> count
        try:
            ea_rows = conn.execute(
                f"""SELECT entity_id, COUNT(*) as cnt
                    FROM entity_attributes
                    WHERE entity_id IN ({placeholders})
                      AND captured_at >= ?
                    GROUP BY entity_id""",
                entity_ids + [cutoff],
            ).fetchall()
            for row in ea_rows:
                attr_counts[row["entity_id"]] = row["cnt"]
        except Exception:
            logger.debug("entity_attributes not available for signals summary")

        # 4. Evidence capture counts
        evidence_counts = {}  # entity_id -> count
        try:
            ev_rows = conn.execute(
                f"""SELECT entity_id, COUNT(*) as cnt
                    FROM evidence
                    WHERE entity_id IN ({placeholders})
                      AND captured_at >= ?
                    GROUP BY entity_id""",
                entity_ids + [cutoff],
            ).fetchall()
            for row in ev_rows:
                evidence_counts[row["entity_id"]] = row["cnt"]
        except Exception:
            logger.debug("evidence not available for signals summary")

    # Build results
    total_changes = sum(change_counts.values())
    total_attrs = sum(attr_counts.values())
    total_evidence = sum(evidence_counts.values())
    total_events = total_changes + total_attrs + total_evidence

    # Most active entities (by total events, top 10)
    entity_activity = []
    for eid in entity_ids:
        total = change_counts.get(eid, 0) + attr_counts.get(eid, 0) + evidence_counts.get(eid, 0)
        if total > 0:
            entity_activity.append({
                "entity_id": eid,
                "entity_name": entity_map.get(eid, ""),
                "event_count": total,
            })
    entity_activity.sort(key=lambda e: e["event_count"], reverse=True)
    most_active = entity_activity[:10]

    # Top changed fields (from change feed)
    top_fields = []
    for fname, data in sorted(field_changes.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
        top_fields.append({
            "field_name": fname,
            "change_count": data["count"],
            "entities_affected": len(data["entity_ids"]),
        })

    return jsonify({
        "period_days": days,
        "entity_count": len(entity_rows),
        "total_events": total_events,
        "most_active_entities": most_active,
        "top_changed_fields": top_fields,
        "recent_highlights": recent_highlights,
        "source_breakdown": {
            "change_detected": total_changes,
            "attribute_updated": total_attrs,
            "evidence_captured": total_evidence,
        },
        "severity_breakdown": severity_breakdown,
    })
