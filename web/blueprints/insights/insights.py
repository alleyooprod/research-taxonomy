"""Insight management endpoints — generate, list, CRUD."""
import json
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from loguru import logger

from . import insights_bp
from ._shared import (
    _require_project_id, _now_iso, _parse_json_field,
    _ensure_tables, _row_to_insight,
    _VALID_INSIGHT_TYPES, _VALID_SEVERITIES, _VALID_CATEGORIES,
    _INSIGHT_SCHEMA,
)
from .detectors import (
    _get_active_entities, _get_latest_attributes,
    _detect_feature_gaps, _detect_pricing_outliers,
    _detect_sparse_coverage, _detect_stale_entities,
    _detect_feature_clusters, _detect_duplicates,
    _detect_attribute_coverage,
)

# ═════════════════════════════════════════════════════════════
# 1. Generate Insights (Rule-Based)
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/generate", methods=["POST"])
def generate_insights():
    """Run the rule-based insight engine to detect patterns in project data.

    Scans entity attributes for:
    - Feature gaps (attributes most entities have but some are missing)
    - Pricing outliers (values significantly above/below the mean)
    - Sparse coverage (attributes with very low coverage)
    - Stale entities (not updated in 30+ days)
    - Feature clusters (entities with overlapping feature sets)
    - Potential duplicates (entities with similar names)
    - Attribute coverage summary

    Query: ?project_id=N

    Returns: {insights: [...], generated_count: N}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Verify project exists
        project = conn.execute(
            "SELECT id, name FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Run all detectors
        all_insights = []

        detectors = [
            ("feature_gaps", _detect_feature_gaps),
            ("pricing_outliers", _detect_pricing_outliers),
            ("sparse_coverage", _detect_sparse_coverage),
            ("stale_entities", _detect_stale_entities),
            ("feature_clusters", _detect_feature_clusters),
            ("duplicates", _detect_duplicates),
            ("attribute_coverage", _detect_attribute_coverage),
        ]

        for name, detector_fn in detectors:
            try:
                found = detector_fn(conn, project_id)
                all_insights.extend(found)
            except Exception as e:
                logger.warning("Insight detector '%s' failed: %s", name, e)

        # Insert into DB
        inserted = []
        for insight in all_insights:
            cursor = conn.execute(
                """INSERT INTO insights
                   (project_id, insight_type, title, description, evidence_refs,
                    severity, category, confidence, source, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    insight["project_id"],
                    insight["insight_type"],
                    insight["title"],
                    insight["description"],
                    insight.get("evidence_refs", "[]"),
                    insight.get("severity", "info"),
                    insight.get("category"),
                    insight.get("confidence", 0.5),
                    insight.get("source", "rule"),
                    insight.get("metadata_json", "{}"),
                ),
            )
            insight_id = cursor.lastrowid

            # Fetch the inserted row for consistent output
            row = conn.execute(
                "SELECT * FROM insights WHERE id = ?", (insight_id,)
            ).fetchone()
            inserted.append(_row_to_insight(row))

    logger.info(
        "Generated %d rule-based insights for project %d (%s)",
        len(inserted), project_id, project["name"],
    )

    return jsonify({
        "insights": inserted,
        "generated_count": len(inserted),
    }), 201


# ═════════════════════════════════════════════════════════════
# 2. Generate AI-Enhanced Insights
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/generate-ai", methods=["POST"])
def generate_ai_insights():
    """Generate AI-enhanced insights using LLM analysis.

    Gathers project data and sends it to an LLM with a prompt asking for
    high-level patterns, correlations, and recommendations that rule-based
    detection would miss.

    Body: {focus?: "pricing"|"features"|"competitive"|"gaps", model?}
    Query: ?project_id=N

    Returns: {insights: [...], generated_count: N, cost_usd, duration_ms}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    body = request.json or {}
    focus = body.get("focus")
    model = body.get("model", "claude-haiku-4-5-20251001")

    if focus and focus not in _VALID_CATEGORIES:
        return jsonify({
            "error": f"Invalid focus: {focus}. Valid: {sorted(_VALID_CATEGORIES)}"
        }), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Verify project exists
        project = conn.execute(
            "SELECT id, name, purpose, description FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Gather entity data
        entities = _get_active_entities(conn, project_id)
        if not entities:
            return jsonify({
                "error": "No entities in this project to analyse"
            }), 400

        eids = [e["id"] for e in entities]
        attrs = _get_latest_attributes(conn, eids)

        # Build summary for LLM
        entity_summaries = []
        for e in entities:
            entity_attrs = attrs.get(e["id"], {})
            summary = {
                "name": e["name"],
                "type": e["type_slug"],
                "attributes": entity_attrs,
            }
            entity_summaries.append(summary)

    # Build the LLM prompt
    focus_instruction = ""
    if focus:
        focus_instruction = f"\n\nFOCUS AREA: Pay special attention to {focus}-related patterns."

    prompt = f"""You are a research analyst examining structured data about entities
in a research project.

PROJECT: {project["name"]}
{f'PURPOSE: {project["purpose"]}' if project["purpose"] else ''}
{f'DESCRIPTION: {project["description"]}' if project["description"] else ''}
{focus_instruction}

ENTITY DATA ({len(entity_summaries)} entities):
{json.dumps(entity_summaries, separators=(',', ':'), default=str)}

TASK: Analyse this data and identify actionable insights. Look for:
1. Cross-entity patterns and correlations
2. Market positioning insights (who competes with whom, and how)
3. Missing data that would be valuable to collect
4. Anomalies or surprising attribute combinations
5. Strategic recommendations based on the data

For each insight, provide:
- type: one of "pattern", "trend", "gap", "outlier", "correlation", "recommendation"
- title: a concise title (under 100 characters)
- description: a detailed explanation with specific entity references
- severity: one of "info", "notable", "important", "critical"
- category: one of "pricing", "features", "design", "market", "competitive"
- confidence: a float 0.0 to 1.0

Return a JSON object with an "insights" key containing an array of insight objects.
Aim for 3-8 high-quality insights. Do not repeat obvious observations."""

    try:
        from core.llm import run_cli
        llm_result = run_cli(prompt, model=model, timeout=90, json_schema=_INSIGHT_SCHEMA)
    except Exception as e:
        logger.error("LLM call failed for AI insights: %s", e)
        return jsonify({"error": f"AI generation failed: {str(e)}"}), 500

    # Parse LLM response
    raw_text = llm_result.get("result", "")
    structured = llm_result.get("structured_output")
    cost_usd = llm_result.get("cost_usd", 0)
    duration_ms = llm_result.get("duration_ms", 0)

    raw_insights = []

    # json_schema should guarantee structured output as {insights: [...]}
    if structured and isinstance(structured, dict) and "insights" in structured:
        raw_insights = structured["insights"]
    elif structured and isinstance(structured, list):
        raw_insights = structured
    else:
        # Fallback: parse from raw text
        try:
            text = raw_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            parsed = json.loads(text.strip())
            if isinstance(parsed, list):
                raw_insights = parsed
            elif isinstance(parsed, dict) and "insights" in parsed:
                raw_insights = parsed["insights"]
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse AI insight response as JSON")
            if raw_text.strip():
                raw_insights = [{
                    "type": "recommendation",
                    "title": "AI Analysis Summary",
                    "description": raw_text.strip()[:2000],
                    "severity": "info",
                    "category": focus or "market",
                    "confidence": 0.5,
                }]

    # Validate and insert
    inserted = []

    with db._get_conn() as conn:
        _ensure_tables(conn)

        for raw in raw_insights:
            if not isinstance(raw, dict):
                continue

            insight_type = raw.get("type", "recommendation")
            if insight_type not in _VALID_INSIGHT_TYPES:
                insight_type = "recommendation"

            severity = raw.get("severity", "info")
            if severity not in _VALID_SEVERITIES:
                severity = "info"

            category = raw.get("category")
            if category and category not in _VALID_CATEGORIES:
                category = None

            title = raw.get("title", "AI Insight")[:200]
            description = raw.get("description", "")[:5000]
            confidence = raw.get("confidence", 0.5)
            if not isinstance(confidence, (int, float)):
                confidence = 0.5
            confidence = max(0.0, min(1.0, float(confidence)))

            evidence_refs = raw.get("evidence_refs", [])
            metadata = {
                "model": model,
                "focus": focus,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
            }

            cursor = conn.execute(
                """INSERT INTO insights
                   (project_id, insight_type, title, description, evidence_refs,
                    severity, category, confidence, source, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ai', ?)""",
                (
                    project_id, insight_type, title, description,
                    json.dumps(evidence_refs),
                    severity, category, confidence,
                    json.dumps(metadata),
                ),
            )
            insight_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM insights WHERE id = ?", (insight_id,)
            ).fetchone()
            inserted.append(_row_to_insight(row))

    logger.info(
        "Generated %d AI insights for project %d (model=%s, cost=$%.4f)",
        len(inserted), project_id, model, cost_usd,
    )

    return jsonify({
        "insights": inserted,
        "generated_count": len(inserted),
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
    }), 201


# ═════════════════════════════════════════════════════════════
# 3. List Insights
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights")
def list_insights():
    """List insights for a project with optional filters.

    Query params:
        project_id (required): Project ID
        insight_type (optional): Filter by type (pattern|trend|gap|outlier|correlation|recommendation)
        severity (optional): Filter by severity (info|notable|important|critical)
        category (optional): Filter by category
        source (optional): Filter by source (rule|ai)
        is_dismissed (optional): Filter by dismissed status (0|1), default 0
        limit (optional): Max results (default 50)
        offset (optional): Pagination offset (default 0)

    Returns: {insights: [...], total: N, limit: N, offset: N}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    insight_type = request.args.get("insight_type")
    severity = request.args.get("severity")
    category = request.args.get("category")
    source = request.args.get("source")
    is_dismissed = request.args.get("is_dismissed", "0", type=str)
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    limit = max(1, min(limit, 200))

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = "SELECT * FROM insights WHERE project_id = ?"
        params = [project_id]

        if is_dismissed != "all":
            query += " AND is_dismissed = ?"
            params.append(int(is_dismissed) if is_dismissed.isdigit() else 0)

        if insight_type:
            query += " AND insight_type = ?"
            params.append(insight_type)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if category:
            query += " AND category = ?"
            params.append(category)
        if source:
            query += " AND source = ?"
            params.append(source)

        # Count
        count_query = query.replace("SELECT *", "SELECT COUNT(*) as total")
        total = conn.execute(count_query, params).fetchone()["total"]

        # Order: pinned first, then by severity weight, then newest
        query += """
            ORDER BY is_pinned DESC,
                     CASE severity
                         WHEN 'critical' THEN 0
                         WHEN 'important' THEN 1
                         WHEN 'notable' THEN 2
                         WHEN 'info' THEN 3
                         ELSE 4
                     END,
                     created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

    insights = [_row_to_insight(row) for row in rows]

    return jsonify({
        "insights": insights,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


# ═════════════════════════════════════════════════════════════
# 4. Get Single Insight
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/<int:insight_id>")
def get_insight(insight_id):
    """Get a single insight by ID.

    Returns: insight dict
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)
        row = conn.execute(
            "SELECT * FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()

    if not row:
        return jsonify({"error": f"Insight {insight_id} not found"}), 404

    return jsonify(_row_to_insight(row))


# ═════════════════════════════════════════════════════════════
# 5. Dismiss Insight
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/<int:insight_id>/dismiss", methods=["PUT"])
def dismiss_insight(insight_id):
    """Dismiss an insight (hides from default listing).

    Returns: {updated: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": f"Insight {insight_id} not found"}), 404

        conn.execute(
            "UPDATE insights SET is_dismissed = 1 WHERE id = ?", (insight_id,)
        )

    return jsonify({"updated": True, "id": insight_id})


# ═════════════════════════════════════════════════════════════
# 6. Pin/Unpin Insight
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/<int:insight_id>/pin", methods=["PUT"])
def pin_insight(insight_id):
    """Toggle the pinned status of an insight.

    Pinned insights float to the top of listings.

    Returns: {updated: true, id: N, is_pinned: bool}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id, is_pinned FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": f"Insight {insight_id} not found"}), 404

        new_pinned = 0 if row["is_pinned"] else 1
        conn.execute(
            "UPDATE insights SET is_pinned = ? WHERE id = ?",
            (new_pinned, insight_id),
        )

    return jsonify({
        "updated": True,
        "id": insight_id,
        "is_pinned": bool(new_pinned),
    })


# ═════════════════════════════════════════════════════════════
# 7. Delete Insight
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/<int:insight_id>", methods=["DELETE"])
def delete_insight(insight_id):
    """Delete an insight permanently.

    Returns: {deleted: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": f"Insight {insight_id} not found"}), 404

        conn.execute("DELETE FROM insights WHERE id = ?", (insight_id,))

    logger.info("Deleted insight #%d", insight_id)
    return jsonify({"deleted": True, "id": insight_id})


# ═════════════════════════════════════════════════════════════
# 8. Insight Summary Stats
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/summary")
def insight_summary():
    """Quick summary statistics for a project's insights.

    Query: ?project_id=N

    Returns:
        {
            total, undismissed, pinned,
            by_type: {gap: N, outlier: N, ...},
            by_severity: {info: N, notable: N, ...},
            by_source: {rule: N, ai: N},
            by_category: {pricing: N, features: N, ...},
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        total = conn.execute(
            "SELECT COUNT(*) FROM insights WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]

        undismissed = conn.execute(
            "SELECT COUNT(*) FROM insights WHERE project_id = ? AND is_dismissed = 0",
            (project_id,),
        ).fetchone()[0]

        pinned = conn.execute(
            "SELECT COUNT(*) FROM insights WHERE project_id = ? AND is_pinned = 1",
            (project_id,),
        ).fetchone()[0]

        # By type
        type_rows = conn.execute(
            """SELECT insight_type, COUNT(*) as count
               FROM insights WHERE project_id = ?
               GROUP BY insight_type""",
            (project_id,),
        ).fetchall()
        by_type = {r["insight_type"]: r["count"] for r in type_rows}

        # By severity
        severity_rows = conn.execute(
            """SELECT severity, COUNT(*) as count
               FROM insights WHERE project_id = ?
               GROUP BY severity""",
            (project_id,),
        ).fetchall()
        by_severity = {r["severity"]: r["count"] for r in severity_rows}

        # By source
        source_rows = conn.execute(
            """SELECT source, COUNT(*) as count
               FROM insights WHERE project_id = ?
               GROUP BY source""",
            (project_id,),
        ).fetchall()
        by_source = {r["source"]: r["count"] for r in source_rows}

        # By category
        category_rows = conn.execute(
            """SELECT category, COUNT(*) as count
               FROM insights WHERE project_id = ? AND category IS NOT NULL
               GROUP BY category""",
            (project_id,),
        ).fetchall()
        by_category = {r["category"]: r["count"] for r in category_rows}

    return jsonify({
        "total": total,
        "undismissed": undismissed,
        "pinned": pinned,
        "by_type": by_type,
        "by_severity": by_severity,
        "by_source": by_source,
        "by_category": by_category,
    })


