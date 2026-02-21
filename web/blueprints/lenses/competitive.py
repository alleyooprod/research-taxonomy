"""Competitive Lens endpoints."""
import json

from flask import request, jsonify, current_app
from loguru import logger

from . import lenses_bp
from ._shared import _require_project_id, _FINANCIAL_SLUGS

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
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = min(limit, 500)  # Cap at 500

    db = current_app.db

    with db._get_conn() as conn:
        # Count total entities for pagination metadata
        if entity_type:
            total_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM entities WHERE project_id = ? AND type_slug = ? AND is_deleted = 0",
                (project_id, entity_type),
            ).fetchone()["cnt"]
            entity_rows = conn.execute(
                """
                SELECT id, name FROM entities
                WHERE project_id = ? AND type_slug = ? AND is_deleted = 0
                ORDER BY name COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                (project_id, entity_type, limit, offset),
            ).fetchall()
        else:
            total_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM entities WHERE project_id = ? AND is_deleted = 0",
                (project_id,),
            ).fetchone()["cnt"]
            entity_rows = conn.execute(
                """
                SELECT id, name FROM entities
                WHERE project_id = ? AND is_deleted = 0
                ORDER BY name COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                (project_id, limit, offset),
            ).fetchall()

        entities = [{"id": r["id"], "name": r["name"]} for r in entity_rows]
        entity_ids = [e["id"] for e in entities]

        if not entity_ids:
            return jsonify({
                "entities": [], "features": [], "matrix": {},
                "pagination": {"limit": limit, "offset": offset, "total": total_count},
            })

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
        "pagination": {"limit": limit, "offset": offset, "total": total_count},
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


_FINANCIAL_SLUGS = {
    "annual_revenue", "revenue", "market_cap", "employee_count",
    "employees", "sec_cik", "company_number", "domain_rank",
    "hn_mention_count", "patent_count", "recent_news_count",
}


@lenses_bp.route("/api/lenses/competitive/enriched-matrix")
def competitive_enriched_matrix():
    """Extended feature matrix with optional financial columns.

    Reuses the standard competitive matrix logic and augments each entity
    with financial / MCP-sourced attribute data.

    Query: ?project_id=N&entity_type=slug&attr_slug=features

    Returns:
        {
            entities: [{id, name}],
            features: [str],
            matrix: {feature_name: {entity_id: true/false, ...}, ...},
            attr_slug, canonical,
            financial_columns: [slug, ...],
            financial_data: {entity_id: {slug: value, ...}, ...}
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_type = request.args.get("entity_type")
    attr_slug = request.args.get("attr_slug", "features")
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = min(limit, 500)  # Cap at 500

    db = current_app.db

    with db._get_conn() as conn:
        # ── Fetch entities (same logic as competitive_matrix) ──
        if entity_type:
            total_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM entities WHERE project_id = ? AND type_slug = ? AND is_deleted = 0",
                (project_id, entity_type),
            ).fetchone()["cnt"]
            entity_rows = conn.execute(
                """
                SELECT id, name FROM entities
                WHERE project_id = ? AND type_slug = ? AND is_deleted = 0
                ORDER BY name COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                (project_id, entity_type, limit, offset),
            ).fetchall()
        else:
            total_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM entities WHERE project_id = ? AND is_deleted = 0",
                (project_id,),
            ).fetchone()["cnt"]
            entity_rows = conn.execute(
                """
                SELECT id, name FROM entities
                WHERE project_id = ? AND is_deleted = 0
                ORDER BY name COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                (project_id, limit, offset),
            ).fetchall()

        entities = [{"id": r["id"], "name": r["name"]} for r in entity_rows]
        entity_ids = [e["id"] for e in entities]

        if not entity_ids:
            return jsonify({
                "entities": [], "features": [], "matrix": {},
                "attr_slug": attr_slug, "canonical": False,
                "financial_columns": [], "financial_data": {},
                "pagination": {"limit": limit, "offset": offset, "total": total_count},
            })

        # ── Feature matrix (duplicated from competitive_matrix) ──
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

        raw_to_canonical = {}
        canonical_features = []
        for row in canonical_rows:
            cname = row["canonical_name"]
            canonical_features.append(cname)
            if row["raw_values"]:
                for raw in row["raw_values"].split("|||"):
                    raw_to_canonical[raw.strip().lower()] = cname

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

        entity_values = {}
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

        if use_canonical:
            feature_list = canonical_features
        else:
            feature_list = sorted(all_raw_features, key=str.casefold)

        matrix = {}
        for feature in feature_list:
            feature_lower = feature.lower()
            row_data = {}
            for entity in entities:
                eid = entity["id"]
                ev_items = entity_values.get(eid, [])
                ev_lower = [v.lower() for v in ev_items]
                if use_canonical:
                    has_feature = any(
                        raw_to_canonical.get(v, v) == feature for v in ev_lower
                    )
                else:
                    has_feature = feature_lower in ev_lower
                row_data[str(eid)] = has_feature
            matrix[feature] = row_data

        # ── Financial data per entity (batch query) ──
        financial_data = {}
        all_financial_slugs_found = set()
        fin_slug_list = sorted(_FINANCIAL_SLUGS)

        if entity_ids and fin_slug_list:
            eid_placeholders = ",".join("?" * len(entity_ids))
            fin_placeholders = ",".join("?" * len(fin_slug_list))
            fin_rows = conn.execute(
                f"""
                SELECT ea.entity_id, ea.attr_slug, ea.value, ea.source, ea.confidence
                FROM entity_attributes ea
                INNER JOIN (
                    SELECT entity_id, attr_slug, MAX(id) as max_id
                    FROM entity_attributes
                    WHERE entity_id IN ({eid_placeholders}) AND attr_slug IN ({fin_placeholders})
                    GROUP BY entity_id, attr_slug
                ) latest ON ea.id = latest.max_id
                """,
                entity_ids + fin_slug_list,
            ).fetchall()

            # Group by entity_id
            fin_by_entity = {}
            for row in fin_rows:
                eid = row["entity_id"]
                if eid not in fin_by_entity:
                    fin_by_entity[eid] = {}
                fin_by_entity[eid][row["attr_slug"]] = row["value"]
                all_financial_slugs_found.add(row["attr_slug"])

            for eid in entity_ids:
                financial_data[str(eid)] = fin_by_entity.get(eid, {})

    return jsonify({
        "entities": entities,
        "features": feature_list,
        "matrix": matrix,
        "attr_slug": attr_slug,
        "canonical": use_canonical,
        "financial_columns": sorted(all_financial_slugs_found),
        "financial_data": financial_data,
        "pagination": {"limit": limit, "offset": offset, "total": total_count},
    })


@lenses_bp.route("/api/lenses/competitive/market-map")
def competitive_market_map():
    """Bubble chart: entities positioned by two attributes, sized by a metric.

    Query: ?project_id=N&x_attr=domain_rank&y_attr=hn_mention_count&size_attr=patent_count

    Returns:
        {
            entities: [{id, name, x_value, y_value, size_value}],
            x_label, y_label, size_label
        }

    Only entities with at least x and y values are included.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    x_attr = request.args.get("x_attr", "domain_rank")
    y_attr = request.args.get("y_attr", "hn_mention_count")
    size_attr = request.args.get("size_attr", "patent_count")
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = min(limit, 500)  # Cap at 500

    db = current_app.db

    with db._get_conn() as conn:
        entity_rows = conn.execute(
            """
            SELECT id, name FROM entities
            WHERE project_id = ? AND is_deleted = 0
            ORDER BY name COLLATE NOCASE
            """,
            (project_id,),
        ).fetchall()

        if not entity_rows:
            return jsonify({
                "entities": [],
                "x_label": x_attr.replace("_", " ").title(),
                "y_label": y_attr.replace("_", " ").title(),
                "size_label": size_attr.replace("_", " ").title(),
                "pagination": {"limit": limit, "offset": offset, "total": 0},
            })

        # Batch load all needed attributes for all entities
        attr_slugs = [s for s in [x_attr, y_attr, size_attr] if s]
        attr_lookup = {}  # {entity_id: {slug: value}}

        if attr_slugs:
            eid_list = [ent["id"] for ent in entity_rows]
            eid_ph = ",".join("?" * len(eid_list))
            slug_ph = ",".join("?" * len(attr_slugs))
            attr_rows = conn.execute(
                f"""
                SELECT ea.entity_id, ea.attr_slug, ea.value
                FROM entity_attributes ea
                INNER JOIN (
                    SELECT entity_id, attr_slug, MAX(id) as max_id
                    FROM entity_attributes
                    WHERE entity_id IN ({eid_ph}) AND attr_slug IN ({slug_ph})
                    GROUP BY entity_id, attr_slug
                ) latest ON ea.id = latest.max_id
                """,
                eid_list + attr_slugs,
            ).fetchall()

            for row in attr_rows:
                attr_lookup.setdefault(row["entity_id"], {})[row["attr_slug"]] = row["value"]

        result_entities = []
        for ent in entity_rows:
            ent_attrs = attr_lookup.get(ent["id"], {})
            attrs = {}
            for slug in [x_attr, y_attr, size_attr]:
                raw = ent_attrs.get(slug)
                if raw is not None:
                    try:
                        attrs[slug] = float(raw)
                    except (ValueError, TypeError):
                        attrs[slug] = None
                else:
                    attrs[slug] = None

            # Only include entities that have at least x and y values
            if attrs.get(x_attr) is not None and attrs.get(y_attr) is not None:
                result_entities.append({
                    "id": ent["id"],
                    "name": ent["name"],
                    "x_value": attrs.get(x_attr),
                    "y_value": attrs.get(y_attr),
                    "size_value": attrs.get(size_attr, 1),
                })

    total_count = len(result_entities)
    paginated_entities = result_entities[offset:offset + limit]

    return jsonify({
        "entities": paginated_entities,
        "x_label": x_attr.replace("_", " ").title(),
        "y_label": y_attr.replace("_", " ").title(),
        "size_label": size_attr.replace("_", " ").title(),
        "pagination": {"limit": limit, "offset": offset, "total": total_count},
    })


