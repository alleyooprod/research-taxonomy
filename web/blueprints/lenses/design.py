"""Design Lens endpoints."""
import json

from flask import request, jsonify, current_app
from loguru import logger

from . import lenses_bp
from ._shared import _require_project_id, _has_design_attr, _STAGE_ORDER, _UI_PATTERN_TO_CATEGORY, _PATTERN_CATEGORIES

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
            logger.exception("Screenshot classification failed for evidence {}", row["id"])
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


@lenses_bp.route("/api/lenses/design/patterns")
def design_patterns():
    """Pattern library — design patterns extracted from evidence and extraction results.

    Query: ?project_id=N

    Aggregates patterns from:
    1. Extraction results with design-related attr_slug values
    2. Screenshot evidence classified by the screenshot classifier (UI patterns)
    3. Entity attributes with design-related slugs

    Returns:
        {
            patterns: [{name, category, occurrences, entities, evidence_ids, description}],
            categories: [str],
            total_patterns: int,
            total_evidence: int
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    limit = request.args.get("limit", 100, type=int)
    offset = max(0, request.args.get("offset", 0, type=int))
    limit = min(limit, 500)  # Cap at 500

    db = current_app.db

    # Collect patterns from multiple sources
    # pattern_key → {name, category, entity_names: set, evidence_ids: set, description}
    pattern_map = {}

    def _add_pattern(name, category, entity_name=None, evidence_id=None, description=""):
        key = name.lower().strip()
        if not key:
            return
        if key not in pattern_map:
            pattern_map[key] = {
                "name": name.strip(),
                "category": category,
                "entity_names": set(),
                "evidence_ids": set(),
                "description": description,
            }
        if entity_name:
            pattern_map[key]["entity_names"].add(entity_name)
        if evidence_id:
            pattern_map[key]["evidence_ids"].add(evidence_id)
        # Prefer longer descriptions
        if description and len(description) > len(pattern_map[key]["description"]):
            pattern_map[key]["description"] = description

    total_evidence = 0

    with db._get_conn() as conn:
        # 1. Extraction results with design-related attr_slugs
        try:
            er_rows = conn.execute(
                """
                SELECT er.attr_slug, er.extracted_value, er.source_evidence_id,
                       er.reasoning, e.name as entity_name
                FROM extraction_results er
                JOIN extraction_jobs ej ON ej.id = er.job_id
                JOIN entities e ON e.id = er.entity_id
                WHERE ej.project_id = ? AND e.is_deleted = 0
                  AND er.status != 'rejected'
                """,
                (project_id,),
            ).fetchall()

            for row in er_rows:
                if _has_design_attr(row["attr_slug"]):
                    val = row["extracted_value"] or ""
                    # Determine category from slug
                    slug_lower = row["attr_slug"].lower()
                    category = "layout"  # default
                    for kw, cat in [
                        ("navigation", "navigation"), ("nav", "navigation"),
                        ("color", "color"), ("colour", "color"),
                        ("typography", "typography"), ("font", "typography"),
                        ("interaction", "interaction"), ("animation", "animation"),
                        ("form", "form"), ("input", "form"),
                        ("layout", "layout"), ("grid", "layout"),
                        ("data", "data_display"), ("table", "data_display"),
                        ("chart", "data_display"),
                    ]:
                        if kw in slug_lower:
                            category = cat
                            break

                    _add_pattern(
                        name=val,
                        category=category,
                        entity_name=row["entity_name"],
                        evidence_id=row["source_evidence_id"],
                        description=row["reasoning"] or "",
                    )
        except Exception:
            logger.debug("extraction_results not available for design patterns")

        # 2. Screenshot evidence — classify and extract UI patterns
        try:
            ev_rows = conn.execute(
                """
                SELECT ev.id, ev.file_path, ev.source_url, ev.source_name,
                       ev.metadata_json, e.name as entity_name
                FROM evidence ev
                JOIN entities e ON e.id = ev.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0
                  AND ev.evidence_type = 'screenshot'
                """,
                (project_id,),
            ).fetchall()

            total_evidence = len(ev_rows)

            from core.extractors.screenshot import classify_by_context

            for row in ev_rows:
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
                    for ui_pattern in (classification.ui_patterns or []):
                        category = _UI_PATTERN_TO_CATEGORY.get(ui_pattern, "layout")
                        _add_pattern(
                            name=ui_pattern,
                            category=category,
                            entity_name=row["entity_name"],
                            evidence_id=row["id"],
                            description=f"UI pattern detected in screenshot",
                        )
                except Exception:
                    logger.debug("Screenshot classification failed for evidence {}", row["id"])

        except Exception:
            logger.debug("evidence table not available for design patterns")

        # 3. Entity attributes with design-related slugs
        try:
            ea_rows = conn.execute(
                """
                SELECT ea.attr_slug, ea.value, e.name as entity_name
                FROM entity_attributes ea
                JOIN entities e ON e.id = ea.entity_id
                WHERE e.project_id = ? AND e.is_deleted = 0
                  AND ea.id IN (
                      SELECT MAX(id) FROM entity_attributes
                      WHERE entity_id = ea.entity_id
                        AND attr_slug = ea.attr_slug
                      GROUP BY entity_id, attr_slug
                  )
                """,
                (project_id,),
            ).fetchall()

            for row in ea_rows:
                if _has_design_attr(row["attr_slug"]):
                    val = row["value"] or ""
                    if not val:
                        continue
                    slug_lower = row["attr_slug"].lower()
                    category = "layout"
                    for kw, cat in [
                        ("navigation", "navigation"), ("nav", "navigation"),
                        ("color", "color"), ("colour", "color"),
                        ("typography", "typography"), ("font", "typography"),
                        ("interaction", "interaction"), ("animation", "animation"),
                        ("form", "form"), ("input", "form"),
                        ("layout", "layout"), ("grid", "layout"),
                        ("data", "data_display"), ("table", "data_display"),
                    ]:
                        if kw in slug_lower:
                            category = cat
                            break

                    _add_pattern(
                        name=val,
                        category=category,
                        entity_name=row["entity_name"],
                    )
        except Exception:
            logger.debug("entity_attributes not available for design patterns")

    # Build result
    all_patterns = []
    for key, data in sorted(pattern_map.items(), key=lambda x: len(x[1]["entity_names"]), reverse=True):
        all_patterns.append({
            "name": data["name"],
            "category": data["category"],
            "occurrences": len(data["entity_names"]) + len(data["evidence_ids"]),
            "entities": sorted(data["entity_names"]),
            "evidence_ids": sorted(data["evidence_ids"]),
            "description": data["description"],
        })

    total_count = len(all_patterns)

    # Collect unique categories from ALL found patterns (before pagination)
    found_categories = sorted({p["category"] for p in all_patterns})
    if not found_categories:
        found_categories = list(_PATTERN_CATEGORIES)

    # Apply pagination to pattern list
    patterns = all_patterns[offset:offset + limit]

    return jsonify({
        "patterns": patterns,
        "categories": found_categories,
        "total_patterns": total_count,
        "total_evidence": total_evidence,
        "pagination": {"limit": limit, "offset": offset, "total": total_count},
    })


@lenses_bp.route("/api/lenses/design/scoring")
def design_scoring():
    """UX scoring — compute UX completeness scores for entities with evidence.

    Query: ?project_id=N

    Scores each entity across 4 dimensions:
    - Journey coverage (% of 16 journey stages covered): weight 0.4
    - Evidence depth (number of evidence items, normalized): weight 0.2
    - Pattern diversity (number of distinct UI patterns found): weight 0.2
    - Attribute completeness (% of design-related attributes filled): weight 0.2

    Returns:
        {
            entities: [{entity_id, entity_name, overall_score,
                        journey_coverage, evidence_depth,
                        pattern_diversity, attribute_completeness,
                        journey_stages_covered, total_evidence, patterns_found}],
            max_evidence: int,
            average_score: float
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    limit = request.args.get("limit", 100, type=int)
    offset = max(0, request.args.get("offset", 0, type=int))
    limit = min(limit, 500)  # Cap at 500

    db = current_app.db

    with db._get_conn() as conn:
        # Get all entities for this project
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
                "max_evidence": 0,
                "average_score": 0,
            })

        entity_ids = [r["id"] for r in entity_rows]
        placeholders = ",".join("?" * len(entity_ids))

        # Fetch all evidence per entity
        evidence_counts = {}
        try:
            ev_count_rows = conn.execute(
                f"""
                SELECT entity_id, COUNT(*) as cnt
                FROM evidence
                WHERE entity_id IN ({placeholders})
                GROUP BY entity_id
                """,
                entity_ids,
            ).fetchall()
            for row in ev_count_rows:
                evidence_counts[row["entity_id"]] = row["cnt"]
        except Exception:
            logger.debug("evidence table not available for UX scoring")

        # Only include entities that have at least some evidence
        entities_with_evidence = [
            r for r in entity_rows if evidence_counts.get(r["id"], 0) > 0
        ]

        if not entities_with_evidence:
            return jsonify({
                "entities": [],
                "max_evidence": 0,
                "average_score": 0,
            })

        max_evidence = max(evidence_counts.values()) if evidence_counts else 1

        # Fetch all screenshot evidence for classification
        ev_entity_ids = [r["id"] for r in entities_with_evidence]
        ev_placeholders = ",".join("?" * len(ev_entity_ids))
        screenshot_rows = []
        try:
            screenshot_rows = conn.execute(
                f"""
                SELECT ev.id, ev.entity_id, ev.file_path, ev.source_url,
                       ev.source_name, ev.metadata_json
                FROM evidence ev
                WHERE ev.entity_id IN ({ev_placeholders})
                  AND ev.evidence_type = 'screenshot'
                """,
                ev_entity_ids,
            ).fetchall()
        except Exception:
            logger.debug("evidence table not available for screenshot classification")

        # Classify all screenshots
        from core.extractors.screenshot import classify_by_context, JOURNEY_STAGES

        total_journey_stages = len(JOURNEY_STAGES)

        entity_journey_stages = {}  # entity_id → set of stages
        entity_ui_patterns = {}     # entity_id → set of patterns

        for row in screenshot_rows:
            eid = row["entity_id"]
            if eid not in entity_journey_stages:
                entity_journey_stages[eid] = set()
                entity_ui_patterns[eid] = set()

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
                if classification.journey_stage and classification.journey_stage != "other":
                    entity_journey_stages[eid].add(classification.journey_stage)
                for pattern in (classification.ui_patterns or []):
                    entity_ui_patterns[eid].add(pattern)
            except Exception:
                logger.debug("Screenshot classification failed for evidence {}", row["id"])

        # Fetch design-related attributes per entity
        design_attr_counts = {}  # entity_id → count of filled design attrs
        total_design_attrs = 0   # count of distinct design attr slugs across project

        try:
            # Find all distinct design-related attr slugs in the project
            all_slug_rows = conn.execute(
                f"""
                SELECT DISTINCT attr_slug
                FROM entity_attributes
                WHERE entity_id IN ({ev_placeholders})
                """,
                ev_entity_ids,
            ).fetchall()

            design_slugs_found = [
                r["attr_slug"] for r in all_slug_rows
                if _has_design_attr(r["attr_slug"])
            ]
            total_design_attrs = len(design_slugs_found)

            if design_slugs_found:
                slug_ph = ",".join("?" * len(design_slugs_found))
                da_rows = conn.execute(
                    f"""
                    SELECT entity_id, COUNT(DISTINCT attr_slug) as cnt
                    FROM entity_attributes
                    WHERE entity_id IN ({ev_placeholders})
                      AND attr_slug IN ({slug_ph})
                      AND value IS NOT NULL AND value != ''
                    GROUP BY entity_id
                    """,
                    ev_entity_ids + design_slugs_found,
                ).fetchall()
                for row in da_rows:
                    design_attr_counts[row["entity_id"]] = row["cnt"]
        except Exception:
            logger.debug("entity_attributes not available for UX scoring")

    # Compute scores
    from core.extractors.screenshot import UI_PATTERNS
    total_ui_patterns = len(UI_PATTERNS)

    results = []
    score_sum = 0

    for entity in entities_with_evidence:
        eid = entity["id"]
        ev_count = evidence_counts.get(eid, 0)
        stages = entity_journey_stages.get(eid, set())
        patterns = entity_ui_patterns.get(eid, set())
        design_attrs_filled = design_attr_counts.get(eid, 0)

        # Sub-scores (0.0 to 1.0)
        journey_coverage = len(stages) / total_journey_stages if total_journey_stages > 0 else 0
        evidence_depth = ev_count / max_evidence if max_evidence > 0 else 0
        pattern_diversity = len(patterns) / total_ui_patterns if total_ui_patterns > 0 else 0
        attr_completeness = (
            design_attrs_filled / total_design_attrs
            if total_design_attrs > 0 else 0
        )

        # Weighted overall score
        overall = (
            journey_coverage * 0.4
            + evidence_depth * 0.2
            + pattern_diversity * 0.2
            + attr_completeness * 0.2
        )

        overall = round(overall, 3)
        journey_coverage = round(journey_coverage, 3)
        evidence_depth = round(evidence_depth, 3)
        pattern_diversity = round(pattern_diversity, 3)
        attr_completeness = round(attr_completeness, 3)

        score_sum += overall

        results.append({
            "entity_id": eid,
            "entity_name": entity["name"],
            "overall_score": overall,
            "journey_coverage": journey_coverage,
            "evidence_depth": evidence_depth,
            "pattern_diversity": pattern_diversity,
            "attribute_completeness": attr_completeness,
            "journey_stages_covered": sorted(stages),
            "total_evidence": ev_count,
            "patterns_found": sorted(patterns),
        })

    # Sort by overall score descending
    results.sort(key=lambda r: r["overall_score"], reverse=True)

    total_count = len(results)
    avg_score = round(score_sum / total_count, 3) if total_count else 0

    # Apply pagination to the scored results
    paginated_results = results[offset:offset + limit]

    return jsonify({
        "entities": paginated_results,
        "max_evidence": max_evidence,
        "average_score": avg_score,
        "pagination": {"limit": limit, "offset": offset, "total": total_count},
    })


