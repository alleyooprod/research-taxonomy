"""Analysis Lenses API — data aggregation for the Research Workbench lens system.

Provides endpoints for:
- Lens availability detection (which lenses are populated for a project)
- Competitive Lens: feature matrix, gap analysis, positioning scatter
- Product Lens: pricing landscape aggregation
- Design Lens: screenshot gallery and journey-stage grouping
- Temporal Lens: attribute change timeline and snapshot comparison
- Signals Lens: event timeline, activity summary, trends, and heatmap
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, current_app
from loguru import logger

lenses_bp = Blueprint("lenses", __name__)

# ── Shared helpers ────────────────────────────────────────────

_PRICING_SLUGS = {"price", "plan", "tier", "cost", "pricing", "subscription", "fee"}
_LOCATION_SLUGS = {"hq_city", "hq_country", "geography", "location", "city", "country", "address"}

# Canonical journey stage order — used to sort design/journey endpoints
_STAGE_ORDER = {
    "landing": 0,
    "onboarding": 1,
    "login": 2,
    "dashboard": 3,
    "listing": 4,
    "detail": 5,
    "search": 6,
    "settings": 7,
    "checkout": 8,
    "pricing": 9,
    "profile": 10,
    "notification": 11,
    "help": 12,
    "error": 13,
    "empty": 14,
    "other": 99,
}


def _require_project_id():
    """Extract and validate project_id from query string.

    Returns (project_id, None) on success or (None, error_response) on failure.
    """
    pid = request.args.get("project_id", type=int)
    if not pid:
        return None, (jsonify({"error": "project_id is required"}), 400)
    return pid, None


def _has_pricing_attr(attr_slug):
    """Return True if attr_slug contains any pricing-related keyword."""
    slug_lower = attr_slug.lower()
    return any(kw in slug_lower for kw in _PRICING_SLUGS)


# ═══════════════════════════════════════════════════════════════
# 4.1  Lens Framework
# ═══════════════════════════════════════════════════════════════

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
                   JOIN monitors m ON m.id = cf.monitor_id
                   JOIN entities e ON e.id = m.entity_id
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


# ═══════════════════════════════════════════════════════════════
# 4.2  Competitive Lens
# ═══════════════════════════════════════════════════════════════

@lenses_bp.route("/api/lenses/competitive/matrix")
def competitive_matrix():
    """Feature comparison matrix.

    Query: ?project_id=N&entity_type=slug&attr_slug=features

    Returns:
        {
            entities: [{id, name}],
            features: [str],
            matrix: {feature_name: {entity_id: true/false/value, ...}, ...}
        }

    If canonical_features exist for the project+attr_slug, those define the
    feature vocabulary.  Otherwise the distinct extracted values are used.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_type = request.args.get("entity_type")
    attr_slug = request.args.get("attr_slug", "features")

    db = current_app.db

    with db._get_conn() as conn:
        # Fetch entities of the given type (or all if no type specified)
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

        entities = [{"id": r["id"], "name": r["name"]} for r in entity_rows]
        entity_ids = [e["id"] for e in entities]

        if not entity_ids:
            return jsonify({"entities": [], "features": [], "matrix": {}})

        # Fetch canonical features for this project+attr_slug (if any)
        canonical_rows = conn.execute(
            """
            SELECT cf.id, cf.canonical_name, cf.category,
                   GROUP_CONCAT(fm.raw_value, '|||') as raw_values
            FROM canonical_features cf
            LEFT JOIN feature_mappings fm ON fm.canonical_feature_id = cf.id
            WHERE cf.project_id = ? AND cf.attr_slug = ?
            GROUP BY cf.id
            ORDER BY cf.category NULLS LAST, cf.canonical_name COLLATE NOCASE
            """,
            (project_id, attr_slug),
        ).fetchall()

        use_canonical = len(canonical_rows) > 0

        # Build raw_value → canonical_name lookup
        raw_to_canonical = {}
        canonical_features = []
        for row in canonical_rows:
            cname = row["canonical_name"]
            canonical_features.append(cname)
            if row["raw_values"]:
                for raw in row["raw_values"].split("|||"):
                    raw_to_canonical[raw.strip().lower()] = cname

        # Fetch all attribute rows for these entities and this slug
        placeholders = ",".join("?" * len(entity_ids))
        attr_rows = conn.execute(
            f"""
            SELECT ea.entity_id, ea.value
            FROM entity_attributes ea
            WHERE ea.entity_id IN ({placeholders})
              AND ea.attr_slug = ?
              AND ea.id IN (
                  SELECT MAX(id) FROM entity_attributes
                  WHERE entity_id IN ({placeholders})
                    AND attr_slug = ?
                  GROUP BY entity_id
              )
            """,
            entity_ids + [attr_slug] + entity_ids + [attr_slug],
        ).fetchall()

        # Parse values — may be a JSON array or a comma-separated string
        entity_values = {}  # entity_id → list of feature strings
        all_raw_features = set()
        for row in attr_rows:
            val = row["value"]
            if not val:
                entity_values[row["entity_id"]] = []
                continue
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    items = [str(v).strip() for v in parsed if v]
                else:
                    items = [str(parsed).strip()]
            except (json.JSONDecodeError, TypeError):
                items = [v.strip() for v in val.split(",") if v.strip()]
            entity_values[row["entity_id"]] = items
            all_raw_features.update(i.lower() for i in items)

        # Determine feature vocabulary
        if use_canonical:
            feature_list = canonical_features
        else:
            # Sort by name
            feature_list = sorted(all_raw_features, key=str.casefold)

        # Build matrix: feature_name → {entity_id: bool}
        matrix = {}
        for feature in feature_list:
            feature_lower = feature.lower()
            row_data = {}
            for entity in entities:
                eid = entity["id"]
                ev_items = entity_values.get(eid, [])
                ev_lower = [v.lower() for v in ev_items]
                if use_canonical:
                    # Check if any raw value maps to this canonical name
                    has_feature = any(
                        raw_to_canonical.get(v, v) == feature for v in ev_lower
                    )
                else:
                    has_feature = feature_lower in ev_lower
                row_data[str(eid)] = has_feature
            matrix[feature] = row_data

    return jsonify({
        "entities": entities,
        "features": feature_list,
        "matrix": matrix,
        "attr_slug": attr_slug,
        "canonical": use_canonical,
    })


@lenses_bp.route("/api/lenses/competitive/gaps")
def competitive_gaps():
    """Gap analysis — features sorted by coverage (lowest first).

    Query: ?project_id=N&entity_type=slug&attr_slug=features

    Returns:
        {
            total_entities: int,
            gaps: [
                {feature_name, entity_count, total_entities, coverage_pct,
                 entities: [name, ...]}
            ]
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_type = request.args.get("entity_type")
    attr_slug = request.args.get("attr_slug", "features")

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

        entities = [{"id": r["id"], "name": r["name"]} for r in entity_rows]
        entity_ids = [e["id"] for e in entities]
        total = len(entities)

        if total == 0:
            return jsonify({"total_entities": 0, "gaps": []})

        # Fetch canonical features
        canonical_rows = conn.execute(
            """
            SELECT cf.id, cf.canonical_name,
                   GROUP_CONCAT(fm.raw_value, '|||') as raw_values
            FROM canonical_features cf
            LEFT JOIN feature_mappings fm ON fm.canonical_feature_id = cf.id
            WHERE cf.project_id = ? AND cf.attr_slug = ?
            GROUP BY cf.id
            """,
            (project_id, attr_slug),
        ).fetchall()

        use_canonical = len(canonical_rows) > 0
        raw_to_canonical = {}
        for row in canonical_rows:
            if row["raw_values"]:
                for raw in row["raw_values"].split("|||"):
                    raw_to_canonical[raw.strip().lower()] = row["canonical_name"]

        # Fetch current attribute values for all entities
        placeholders = ",".join("?" * len(entity_ids))
        attr_rows = conn.execute(
            f"""
            SELECT ea.entity_id, ea.value
            FROM entity_attributes ea
            WHERE ea.entity_id IN ({placeholders})
              AND ea.attr_slug = ?
              AND ea.id IN (
                  SELECT MAX(id) FROM entity_attributes
                  WHERE entity_id IN ({placeholders})
                    AND attr_slug = ?
                  GROUP BY entity_id
              )
            """,
            entity_ids + [attr_slug] + entity_ids + [attr_slug],
        ).fetchall()

    # Parse entity values
    eid_to_name = {e["id"]: e["name"] for e in entities}
    entity_values = {}  # entity_id → set of normalised feature names
    for row in attr_rows:
        val = row["value"]
        if not val:
            entity_values[row["entity_id"]] = set()
            continue
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                items = [str(v).strip() for v in parsed if v]
            else:
                items = [str(parsed).strip()]
        except (json.JSONDecodeError, TypeError):
            items = [v.strip() for v in val.split(",") if v.strip()]

        normalised = set()
        for item in items:
            key = item.lower()
            if use_canonical:
                normalised.add(raw_to_canonical.get(key, item))
            else:
                normalised.add(item)
        entity_values[row["entity_id"]] = normalised

    # Aggregate: feature → {entity_names}
    feature_entities = {}  # feature_name → list of entity names
    for eid, features in entity_values.items():
        name = eid_to_name.get(eid, str(eid))
        for feat in features:
            feature_entities.setdefault(feat, []).append(name)

    gaps = []
    for feat, enames in feature_entities.items():
        count = len(enames)
        gaps.append({
            "feature_name": feat,
            "entity_count": count,
            "total_entities": total,
            "coverage_pct": round(count / total * 100, 1),
            "entities": sorted(enames),
        })

    # Sort: lowest coverage first, then alphabetically
    gaps.sort(key=lambda g: (g["coverage_pct"], g["feature_name"].lower()))

    return jsonify({"total_entities": total, "gaps": gaps, "attr_slug": attr_slug})


@lenses_bp.route("/api/lenses/competitive/positioning")
def competitive_positioning():
    """Positioning scatter plot data.

    Query: ?project_id=N&entity_type=slug&x_attr=attr1&y_attr=attr2

    Returns:
        {
            x_attr, y_attr,
            entities: [{id, name, x_value, y_value}]
        }

    Only entities that have both attributes are included.
    Values are returned as strings (callers should handle parsing).
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_type = request.args.get("entity_type")
    x_attr = request.args.get("x_attr")
    y_attr = request.args.get("y_attr")

    if not x_attr or not y_attr:
        return jsonify({"error": "x_attr and y_attr are required"}), 400

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
            return jsonify({"x_attr": x_attr, "y_attr": y_attr, "entities": []})

        placeholders = ",".join("?" * len(entity_ids))

        # Fetch x attribute values (most recent per entity)
        x_rows = conn.execute(
            f"""
            SELECT ea.entity_id, ea.value
            FROM entity_attributes ea
            WHERE ea.entity_id IN ({placeholders})
              AND ea.attr_slug = ?
              AND ea.id IN (
                  SELECT MAX(id) FROM entity_attributes
                  WHERE entity_id IN ({placeholders})
                    AND attr_slug = ?
                  GROUP BY entity_id
              )
            """,
            entity_ids + [x_attr] + entity_ids + [x_attr],
        ).fetchall()

        # Fetch y attribute values (most recent per entity)
        y_rows = conn.execute(
            f"""
            SELECT ea.entity_id, ea.value
            FROM entity_attributes ea
            WHERE ea.entity_id IN ({placeholders})
              AND ea.attr_slug = ?
              AND ea.id IN (
                  SELECT MAX(id) FROM entity_attributes
                  WHERE entity_id IN ({placeholders})
                    AND attr_slug = ?
                  GROUP BY entity_id
              )
            """,
            entity_ids + [y_attr] + entity_ids + [y_attr],
        ).fetchall()

    x_values = {r["entity_id"]: r["value"] for r in x_rows}
    y_values = {r["entity_id"]: r["value"] for r in y_rows}

    result = []
    for row in entity_rows:
        eid = row["id"]
        xv = x_values.get(eid)
        yv = y_values.get(eid)
        if xv is not None and yv is not None:
            result.append({
                "id": eid,
                "name": row["name"],
                "x_value": xv,
                "y_value": yv,
            })

    return jsonify({"x_attr": x_attr, "y_attr": y_attr, "entities": result})


# ═══════════════════════════════════════════════════════════════
# 4.3  Product Lens
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# 4.4  Design Lens
# ═══════════════════════════════════════════════════════════════

@lenses_bp.route("/api/lenses/design/gallery")
def design_gallery():
    """All screenshot evidence for an entity, grouped by evidence_type.

    Query: ?project_id=N&entity_id=N

    Returns:
        {
            entity_id, entity_name,
            groups: {evidence_type: [{id, file_path, source_url, source_name,
                                      metadata, created_at}]}
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

        evidence_rows = conn.execute(
            """
            SELECT id, evidence_type, file_path, source_url, source_name,
                   metadata_json, captured_at
            FROM evidence
            WHERE entity_id = ?
            ORDER BY evidence_type, captured_at DESC
            """,
            (entity_id,),
        ).fetchall()

    groups = {}
    for row in evidence_rows:
        ev_type = row["evidence_type"]
        metadata = {}
        if row["metadata_json"]:
            try:
                metadata = json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else row["metadata_json"]
            except (json.JSONDecodeError, TypeError):
                pass
        entry = {
            "id": row["id"],
            "file_path": row["file_path"],
            "source_url": row["source_url"],
            "source_name": row["source_name"],
            "metadata": metadata,
            "created_at": row["captured_at"],
        }
        groups.setdefault(ev_type, []).append(entry)

    return jsonify({
        "entity_id": entity_id,
        "entity_name": entity_row["name"],
        "groups": groups,
    })


@lenses_bp.route("/api/lenses/design/journey")
def design_journey():
    """Screenshots classified into journey stages, ordered by typical UX flow.

    Query: ?project_id=N&entity_id=N

    Classifies screenshots on the fly using heuristic metadata analysis
    (URL path, filename, source name) — no LLM call.

    Returns:
        {
            entity_id, entity_name,
            stages: [
                {
                    stage: str,
                    order: int,
                    screenshots: [{id, file_path, source_url, source_name,
                                   metadata, created_at, journey_confidence,
                                   ui_patterns}]
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

        evidence_rows = conn.execute(
            """
            SELECT id, file_path, source_url, source_name, metadata_json, captured_at
            FROM evidence
            WHERE entity_id = ? AND evidence_type = 'screenshot'
            ORDER BY captured_at ASC
            """,
            (entity_id,),
        ).fetchall()

    from core.extractors.screenshot import classify_by_context

    stage_map = {}  # stage → list of screenshot dicts
    for row in evidence_rows:
        metadata = {}
        if row["metadata_json"]:
            try:
                metadata = json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else row["metadata_json"]
            except (json.JSONDecodeError, TypeError):
                pass

        filename = None
        if row["file_path"]:
            filename = row["file_path"].split("/")[-1]

        try:
            classification = classify_by_context(
                source_url=row["source_url"],
                filename=filename,
                source_name=row["source_name"],
                evidence_metadata=metadata,
            )
            stage = classification.journey_stage
            confidence = classification.journey_confidence
            ui_patterns = classification.ui_patterns
        except Exception:
            logger.exception("Screenshot classification failed for evidence %s", row["id"])
            stage = "other"
            confidence = 0.0
            ui_patterns = []

        entry = {
            "id": row["id"],
            "file_path": row["file_path"],
            "source_url": row["source_url"],
            "source_name": row["source_name"],
            "metadata": metadata,
            "created_at": row["captured_at"],
            "journey_confidence": confidence,
            "ui_patterns": ui_patterns,
        }
        stage_map.setdefault(stage, []).append(entry)

    # Sort stages by canonical UX order
    stages = []
    for stage, screenshots in stage_map.items():
        stages.append({
            "stage": stage,
            "order": _STAGE_ORDER.get(stage, 99),
            "screenshots": screenshots,
        })
    stages.sort(key=lambda s: s["order"])

    return jsonify({
        "entity_id": entity_id,
        "entity_name": entity_row["name"],
        "stages": stages,
    })


# ═══════════════════════════════════════════════════════════════
# 4.5  Temporal Lens
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# 4.7  Signals Lens
# ═══════════════════════════════════════════════════════════════

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
    offset = request.args.get("offset", 0, type=int)

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
                SELECT cf.id, cf.monitor_id, cf.change_type, cf.field_name,
                       cf.old_value, cf.new_value, cf.detected_at,
                       cf.severity, cf.metadata_json,
                       e.id as entity_id, e.name as entity_name
                FROM change_feed cf
                JOIN monitors m ON m.id = cf.monitor_id
                JOIN entities e ON e.id = m.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0{entity_filter}
                ORDER BY cf.detected_at DESC
                """,
                params_base,
            ).fetchall()

            for row in cf_rows:
                metadata = {}
                if row["metadata_json"]:
                    try:
                        metadata = json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else row["metadata_json"]
                    except (json.JSONDecodeError, TypeError):
                        pass
                events.append({
                    "type": "change_detected",
                    "entity_id": row["entity_id"],
                    "entity_name": row["entity_name"],
                    "title": f"{row['change_type']}: {row['field_name'] or 'unknown'}",
                    "description": f"Changed from '{row['old_value'] or ''}' to '{row['new_value'] or ''}'",
                    "severity": row["severity"] or "info",
                    "timestamp": row["detected_at"],
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

    logger.info("Signals timeline: %d total events (returning %d) for project %d",
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
                SELECT m.entity_id,
                       COUNT(*) as cnt,
                       MAX(cf.detected_at) as last_change
                FROM change_feed cf
                JOIN monitors m ON m.id = cf.monitor_id
                WHERE m.entity_id IN ({placeholders})
                GROUP BY m.entity_id
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
                SELECT date(cf.detected_at, 'weekday 0', '-6 days') as week_start,
                       COUNT(*) as cnt
                FROM change_feed cf
                JOIN monitors m ON m.id = cf.monitor_id
                JOIN entities e ON e.id = m.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0{entity_filter}
                  AND cf.detected_at IS NOT NULL
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
                SELECT m.entity_id, COUNT(*) as cnt
                FROM change_feed cf
                JOIN monitors m ON m.id = cf.monitor_id
                WHERE m.entity_id IN ({placeholders})
                GROUP BY m.entity_id
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
            recent_highlights: [{entity_name, change_type, field_name, old_value, new_value, timestamp}],
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
                f"""SELECT cf.change_type, cf.field_name, cf.old_value, cf.new_value,
                           cf.detected_at, cf.severity,
                           m.entity_id
                    FROM change_feed cf
                    JOIN monitors m ON m.id = cf.monitor_id
                    WHERE m.entity_id IN ({placeholders})
                      AND cf.detected_at >= ?
                    ORDER BY cf.detected_at DESC""",
                entity_ids + [cutoff],
            ).fetchall()

            for row in cf_rows:
                eid = row["entity_id"]
                change_counts[eid] = change_counts.get(eid, 0) + 1

                fname = row["field_name"] or "unknown"
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
                        "old_value": row["old_value"],
                        "new_value": row["new_value"],
                        "timestamp": row["detected_at"],
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
