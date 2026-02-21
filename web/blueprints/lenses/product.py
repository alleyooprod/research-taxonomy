"""Product Lens endpoints."""

from flask import request, jsonify, current_app
from loguru import logger

from . import lenses_bp
from ._shared import _require_project_id, _has_pricing_attr

@lenses_bp.route("/api/lenses/product/pricing")
def product_pricing():
    """Pricing landscape — all pricing-related attributes per entity.

    Query: ?project_id=N&entity_type=slug

    Returns:
        {
            entities: [
                {entity_name, entity_id, attributes: {slug: value, ...}}
            ],
            pricing_attrs: [slug, ...]   -- the distinct pricing attr slugs found
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_type = request.args.get("entity_type")

    db = current_app.db

    with db._get_conn() as conn:
        if entity_type:
            entity_rows = conn.execute(
                """
                SELECT id, name FROM entities
                WHERE project_id = ? AND type_slug = ? AND is_deleted = 0
                ORDER BY name COLLATE NOCASE
                """,
                (project_id, entity_type),
            ).fetchall()
        else:
            entity_rows = conn.execute(
                """
                SELECT id, name FROM entities
                WHERE project_id = ? AND is_deleted = 0
                ORDER BY name COLLATE NOCASE
                """,
                (project_id,),
            ).fetchall()

        entity_ids = [r["id"] for r in entity_rows]
        if not entity_ids:
            return jsonify({"entities": [], "pricing_attrs": []})

        placeholders = ",".join("?" * len(entity_ids))

        # Fetch all distinct attribute slugs for these entities
        all_slugs = conn.execute(
            f"""
            SELECT DISTINCT attr_slug
            FROM entity_attributes
            WHERE entity_id IN ({placeholders})
            """,
            entity_ids,
        ).fetchall()
        pricing_slugs = [
            r["attr_slug"] for r in all_slugs if _has_pricing_attr(r["attr_slug"])
        ]

        if not pricing_slugs:
            return jsonify({"entities": [], "pricing_attrs": []})

        # Fetch most-recent values for each entity × pricing slug
        slug_placeholders = ",".join("?" * len(pricing_slugs))
        attr_rows = conn.execute(
            f"""
            SELECT ea.entity_id, ea.attr_slug, ea.value
            FROM entity_attributes ea
            WHERE ea.entity_id IN ({placeholders})
              AND ea.attr_slug IN ({slug_placeholders})
              AND ea.id IN (
                  SELECT MAX(id) FROM entity_attributes
                  WHERE entity_id IN ({placeholders})
                    AND attr_slug IN ({slug_placeholders})
                  GROUP BY entity_id, attr_slug
              )
            """,
            entity_ids + pricing_slugs + entity_ids + pricing_slugs,
        ).fetchall()

    # Aggregate per entity
    entity_attrs = {}  # entity_id → {slug: value}
    for row in attr_rows:
        entity_attrs.setdefault(row["entity_id"], {})[row["attr_slug"]] = row["value"]

    results = []
    for row in entity_rows:
        eid = row["id"]
        attrs = entity_attrs.get(eid, {})
        if attrs:  # only include entities that have at least one pricing attr
            results.append({
                "entity_id": eid,
                "entity_name": row["name"],
                "attributes": attrs,
            })

    return jsonify({
        "entities": results,
        "pricing_attrs": sorted(pricing_slugs),
    })


