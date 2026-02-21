"""Availability Lens endpoints."""

from flask import request, jsonify, current_app
from loguru import logger

from . import lenses_bp
from ._shared import _require_project_id, _has_pricing_attr, _LOCATION_SLUGS

@lenses_bp.route("/api/lenses/available")
def lenses_available():
    """Return which lenses are available for a project, based on data presence.

    Query: ?project_id=N

    Each lens entry:
        {name, slug, available: bool, entity_count: int, hint: str}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        # Total entity count
        total_entities = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE project_id = ? AND is_deleted = 0",
            (project_id,),
        ).fetchone()[0]

        # Competitive: 2+ entities with any attribute data
        entities_with_attrs = conn.execute(
            """
            SELECT COUNT(DISTINCT e.id)
            FROM entities e
            JOIN entity_attributes ea ON ea.entity_id = e.id
            WHERE e.project_id = ? AND e.is_deleted = 0
            """,
            (project_id,),
        ).fetchone()[0]
        competitive_available = entities_with_attrs >= 2

        # Product: 2+ entities with pricing-related attributes
        all_pricing_attrs = conn.execute(
            """
            SELECT DISTINCT ea.entity_id, ea.attr_slug
            FROM entity_attributes ea
            JOIN entities e ON e.id = ea.entity_id
            WHERE e.project_id = ? AND e.is_deleted = 0
            """,
            (project_id,),
        ).fetchall()

        pricing_entity_ids = {
            row[0]
            for row in all_pricing_attrs
            if _has_pricing_attr(row[1])
        }
        product_available = len(pricing_entity_ids) >= 2

        # Design: any entity has screenshot evidence
        screenshot_entity_count = conn.execute(
            """
            SELECT COUNT(DISTINCT ev.entity_id)
            FROM evidence ev
            JOIN entities e ON e.id = ev.entity_id
            WHERE e.project_id = ? AND ev.evidence_type = 'screenshot'
            """,
            (project_id,),
        ).fetchone()[0]
        design_available = screenshot_entity_count > 0

        # Temporal: any entity has 2+ snapshot records (rows in entity_attributes
        # with distinct snapshot_ids)
        entities_with_snapshots = conn.execute(
            """
            SELECT COUNT(DISTINCT ea.entity_id)
            FROM entity_attributes ea
            JOIN entities e ON e.id = ea.entity_id
            WHERE e.project_id = ? AND ea.snapshot_id IS NOT NULL
            GROUP BY ea.entity_id
            HAVING COUNT(DISTINCT ea.snapshot_id) >= 2
            """,
            (project_id,),
        ).fetchone()
        # fetchone returns None if no rows match
        temporal_available = entities_with_snapshots is not None

        # Alternatively check entity_snapshots table directly
        if not temporal_available:
            snapshot_count = conn.execute(
                "SELECT COUNT(*) FROM entity_snapshots WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            temporal_available = snapshot_count >= 2

        # Relationship: always available if entities exist
        relationship_available = total_entities > 0

        # Geographic: entities with location-related attributes
        all_attr_slugs = conn.execute(
            """
            SELECT DISTINCT ea.attr_slug
            FROM entity_attributes ea
            JOIN entities e ON e.id = ea.entity_id
            WHERE e.project_id = ? AND e.is_deleted = 0
            """,
            (project_id,),
        ).fetchall()
        geo_available = any(
            row[0] in _LOCATION_SLUGS for row in all_attr_slugs
        )

        # Signals: any monitoring data exists (change_feed or configured monitors)
        try:
            change_feed_count = conn.execute(
                """SELECT COUNT(*) FROM change_feed cf
                   JOIN entities e ON e.id = cf.entity_id
                   WHERE e.project_id = ? AND e.is_deleted = 0""",
                (project_id,),
            ).fetchone()[0]
        except Exception:
            change_feed_count = 0

        try:
            monitors_count = conn.execute(
                """SELECT COUNT(*) FROM monitors m
                   JOIN entities e ON e.id = m.entity_id
                   WHERE e.project_id = ? AND e.is_deleted = 0""",
                (project_id,),
            ).fetchone()[0]
        except Exception:
            monitors_count = 0

        signals_available = change_feed_count > 0 or monitors_count > 0

    lenses = [
        {
            "name": "Competitive Analysis",
            "slug": "competitive",
            "available": competitive_available,
            "entity_count": entities_with_attrs,
            "hint": (
                "Compares entities across shared features and attributes."
                if competitive_available
                else "Add attributes to 2 or more entities to enable."
            ),
        },
        {
            "name": "Product Comparison",
            "slug": "product",
            "available": product_available,
            "entity_count": len(pricing_entity_ids),
            "hint": (
                "Side-by-side pricing and plan comparison."
                if product_available
                else "Add pricing, plan, or tier attributes to 2+ entities to enable."
            ),
        },
        {
            "name": "Design Review",
            "slug": "design",
            "available": design_available,
            "entity_count": screenshot_entity_count,
            "hint": (
                "Browse captured screenshots by journey stage."
                if design_available
                else "Capture screenshots for at least one entity to enable."
            ),
        },
        {
            "name": "Temporal Tracking",
            "slug": "temporal",
            "available": temporal_available,
            "entity_count": total_entities,
            "hint": (
                "View how attributes have changed over time."
                if temporal_available
                else "Capture the same entity at least twice to enable."
            ),
        },
        {
            "name": "Relationship Map",
            "slug": "relationship",
            "available": relationship_available,
            "entity_count": total_entities,
            "hint": (
                "Explore connections between entities."
                if relationship_available
                else "Add entities to this project to enable."
            ),
        },
        {
            "name": "Geographic View",
            "slug": "geographic",
            "available": geo_available,
            "entity_count": total_entities,
            "hint": (
                "Map entities by location attributes."
                if geo_available
                else "Add location attributes (city, country, etc.) to entities to enable."
            ),
        },
        {
            "name": "Market Signals",
            "slug": "signals",
            "available": signals_available,
            "entity_count": monitors_count,
            "hint": (
                "View event timeline and change signals."
                if signals_available
                else "Set up monitoring on entities to enable signals."
            ),
        },
    ]

    return jsonify(lenses)


