"""Temporal Lens endpoints."""

from flask import request, jsonify, current_app
from loguru import logger

from . import lenses_bp
from ._shared import _require_project_id

@lenses_bp.route("/api/lenses/temporal/timeline")
def temporal_timeline():
    """Attribute change timeline for an entity.

    Query: ?project_id=N&entity_id=N

    Returns all distinct attribute values ordered chronologically, with
    per-attribute diffs highlighted between consecutive captures.

    Returns:
        {
            entity_id, entity_name,
            snapshots: [
                {
                    snapshot_id,          -- null for ungrouped rows
                    captured_at,
                    description,
                    attributes: {slug: value},
                    changes: {slug: {old_value, new_value}}  -- vs previous snapshot
                }
            ]
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_id = request.args.get("entity_id", type=int)
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        entity_row = conn.execute(
            "SELECT id, name FROM entities WHERE id = ? AND project_id = ? AND is_deleted = 0",
            (entity_id, project_id),
        ).fetchone()

        if not entity_row:
            return jsonify({"error": f"Entity {entity_id} not found in project {project_id}"}), 404

        # All attribute rows for this entity, ordered chronologically
        attr_rows = conn.execute(
            """
            SELECT ea.id, ea.attr_slug, ea.value, ea.source, ea.confidence,
                   ea.captured_at, ea.snapshot_id,
                   es.description as snapshot_description
            FROM entity_attributes ea
            LEFT JOIN entity_snapshots es ON es.id = ea.snapshot_id
            WHERE ea.entity_id = ?
            ORDER BY ea.captured_at ASC, ea.id ASC
            """,
            (entity_id,),
        ).fetchall()

    # Group rows into "timeline points".  Rows sharing the same snapshot_id
    # form a single point.  Rows with snapshot_id=NULL are each their own point.
    points = {}  # key → {captured_at, snapshot_id, description, attrs: {slug: value}}
    for row in attr_rows:
        snap_id = row["snapshot_id"]
        key = f"snap_{snap_id}" if snap_id is not None else f"row_{row['id']}"
        if key not in points:
            points[key] = {
                "snapshot_id": snap_id,
                "captured_at": row["captured_at"],
                "description": row["snapshot_description"] or "",
                "attributes": {},
            }
        # Later rows within the same snapshot overwrite earlier (last-write-wins)
        points[key]["attributes"][row["attr_slug"]] = row["value"]

    # Sort timeline points by captured_at, then snapshot_id
    sorted_points = sorted(
        points.values(),
        key=lambda p: (p["captured_at"] or "", p["snapshot_id"] or 0),
    )

    # Compute diffs between consecutive points
    snapshots = []
    prev_attrs = {}
    for point in sorted_points:
        changes = {}
        for slug, value in point["attributes"].items():
            old = prev_attrs.get(slug)
            if old != value:
                changes[slug] = {"old_value": old, "new_value": value}
        snapshots.append({
            "snapshot_id": point["snapshot_id"],
            "captured_at": point["captured_at"],
            "description": point["description"],
            "attributes": point["attributes"],
            "changes": changes,
        })
        prev_attrs = {**prev_attrs, **point["attributes"]}

    return jsonify({
        "entity_id": entity_id,
        "entity_name": entity_row["name"],
        "snapshots": snapshots,
    })


@lenses_bp.route("/api/lenses/temporal/compare")
def temporal_compare():
    """Side-by-side comparison of two snapshots for an entity.

    Query: ?project_id=N&entity_id=N&snapshot_a=id&snapshot_b=id

    snapshot_a and snapshot_b are entity_snapshots.id values.
    Returns the attribute state at each snapshot and the diff between them.

    Returns:
        {
            entity_id, entity_name,
            snapshot_a: {id, description, captured_at, attributes: {slug: value}},
            snapshot_b: {id, description, captured_at, attributes: {slug: value}},
            diff: {
                slug: {a_value, b_value, changed: bool}
            }
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_id = request.args.get("entity_id", type=int)
    snapshot_a_id = request.args.get("snapshot_a", type=int)
    snapshot_b_id = request.args.get("snapshot_b", type=int)

    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not snapshot_a_id or not snapshot_b_id:
        return jsonify({"error": "snapshot_a and snapshot_b are required"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        entity_row = conn.execute(
            "SELECT id, name FROM entities WHERE id = ? AND project_id = ? AND is_deleted = 0",
            (entity_id, project_id),
        ).fetchone()

        if not entity_row:
            return jsonify({"error": f"Entity {entity_id} not found in project {project_id}"}), 404

        def _load_snapshot(snap_id):
            snap = conn.execute(
                "SELECT id, description, created_at FROM entity_snapshots WHERE id = ? AND project_id = ?",
                (snap_id, project_id),
            ).fetchone()
            if not snap:
                return None, f"Snapshot {snap_id} not found"

            rows = conn.execute(
                """
                SELECT attr_slug, value
                FROM entity_attributes
                WHERE entity_id = ? AND snapshot_id = ?
                """,
                (entity_id, snap_id),
            ).fetchall()

            # Last-write-wins for each slug within the snapshot
            attrs = {}
            for r in rows:
                attrs[r["attr_slug"]] = r["value"]

            return {
                "id": snap["id"],
                "description": snap["description"] or "",
                "captured_at": snap["created_at"],
                "attributes": attrs,
            }, None

        snap_a, err_a = _load_snapshot(snapshot_a_id)
        snap_b, err_b = _load_snapshot(snapshot_b_id)

    if err_a:
        return jsonify({"error": err_a}), 404
    if err_b:
        return jsonify({"error": err_b}), 404

    # Build diff across the union of all attribute slugs
    all_slugs = sorted(set(snap_a["attributes"]) | set(snap_b["attributes"]))
    diff = {}
    for slug in all_slugs:
        a_val = snap_a["attributes"].get(slug)
        b_val = snap_b["attributes"].get(slug)
        diff[slug] = {
            "a_value": a_val,
            "b_value": b_val,
            "changed": a_val != b_val,
        }

    return jsonify({
        "entity_id": entity_id,
        "entity_name": entity_row["name"],
        "snapshot_a": snap_a,
        "snapshot_b": snap_b,
        "diff": diff,
    })


