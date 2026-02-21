"""Hypothesis management endpoints — create, list, evidence, scoring."""
import json
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from loguru import logger

from . import insights_bp
from ._shared import (
    _require_project_id, _now_iso, _parse_json_field,
    _ensure_tables, _row_to_hypothesis, _row_to_evidence,
    _compute_hypothesis_confidence,
    _VALID_HYPOTHESIS_STATUSES, _VALID_EVIDENCE_DIRECTIONS, _VALID_CATEGORIES,
)

# ═════════════════════════════════════════════════════════════
# 9. Create Hypothesis
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/hypotheses", methods=["POST"])
def create_hypothesis():
    """Create a new hypothesis for a project.

    Body: {project_id, statement, category?}

    Returns: created hypothesis (201)
    """
    data = request.json or {}
    project_id = data.get("project_id")
    statement = data.get("statement", "").strip()
    category = data.get("category")

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    if not statement:
        return jsonify({"error": "statement is required"}), 400
    if category and category not in _VALID_CATEGORIES:
        return jsonify({
            "error": f"Invalid category: {category}. Valid: {sorted(_VALID_CATEGORIES)}"
        }), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Verify project exists
        project = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project:
            return jsonify({"error": "Project not found"}), 404

        now = _now_iso()
        cursor = conn.execute(
            """INSERT INTO hypotheses (project_id, statement, status, confidence, category, created_at, updated_at)
               VALUES (?, ?, 'open', 0.5, ?, ?, ?)""",
            (project_id, statement, category, now, now),
        )
        hyp_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM hypotheses WHERE id = ?", (hyp_id,)
        ).fetchone()

    logger.info("Created hypothesis #%d for project %d", hyp_id, project_id)
    return jsonify(_row_to_hypothesis(row)), 201


# ═════════════════════════════════════════════════════════════
# 10. List Hypotheses
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/hypotheses")
def list_hypotheses():
    """List hypotheses for a project with optional filters.

    Query params:
        project_id (required): Project ID
        status (optional): Filter by status (open|supported|refuted|inconclusive)
        category (optional): Filter by category

    Returns: list of hypothesis dicts with evidence counts and computed confidence
    """
    project_id, err = _require_project_id()
    if err:
        return err

    status = request.args.get("status")
    category = request.args.get("category")

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = "SELECT * FROM hypotheses WHERE project_id = ?"
        params = [project_id]

        if status:
            query += " AND status = ?"
            params.append(status)
        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY updated_at DESC"
        rows = conn.execute(query, params).fetchall()

        # Enrich with evidence counts and computed confidence
        result = []
        for row in rows:
            hyp = _row_to_hypothesis(row)

            evidence_rows = conn.execute(
                "SELECT direction, weight FROM hypothesis_evidence WHERE hypothesis_id = ?",
                (row["id"],),
            ).fetchall()

            confidence, supports, contradicts, neutral = _compute_hypothesis_confidence(evidence_rows)
            hyp["computed_confidence"] = confidence
            hyp["evidence_count"] = len(evidence_rows)
            hyp["supports_count"] = sum(1 for e in evidence_rows if e["direction"] == "supports")
            hyp["contradicts_count"] = sum(1 for e in evidence_rows if e["direction"] == "contradicts")
            hyp["neutral_count"] = sum(1 for e in evidence_rows if e["direction"] == "neutral")
            hyp["supports_weight"] = round(supports, 2)
            hyp["contradicts_weight"] = round(contradicts, 2)

            result.append(hyp)

    return jsonify(result)


# ═════════════════════════════════════════════════════════════
# 11. Get Single Hypothesis
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/hypotheses/<int:hyp_id>")
def get_hypothesis(hyp_id):
    """Get a hypothesis with all its evidence.

    Returns: hypothesis dict with evidence array and computed confidence
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM hypotheses WHERE id = ?", (hyp_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": f"Hypothesis {hyp_id} not found"}), 404

        hyp = _row_to_hypothesis(row)

        # Fetch evidence with entity names
        evidence_rows = conn.execute(
            """SELECT he.*, e.name as entity_name
               FROM hypothesis_evidence he
               LEFT JOIN entities e ON e.id = he.entity_id
               WHERE he.hypothesis_id = ?
               ORDER BY he.created_at DESC""",
            (hyp_id,),
        ).fetchall()

        evidence = []
        for er in evidence_rows:
            ev = _row_to_evidence(er)
            if "entity_name" in er.keys():
                ev["entity_name"] = er["entity_name"]
            evidence.append(ev)

        hyp["evidence"] = evidence

        # Compute confidence
        confidence, supports, contradicts, neutral = _compute_hypothesis_confidence(evidence_rows)
        hyp["computed_confidence"] = confidence
        hyp["evidence_count"] = len(evidence)
        hyp["supports_weight"] = round(supports, 2)
        hyp["contradicts_weight"] = round(contradicts, 2)
        hyp["neutral_weight"] = round(neutral, 2)

    return jsonify(hyp)


# ═════════════════════════════════════════════════════════════
# 12. Update Hypothesis
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/hypotheses/<int:hyp_id>", methods=["PUT"])
def update_hypothesis(hyp_id):
    """Update a hypothesis's statement, status, or category.

    Body: {statement?, status?, category?}

    Returns: updated hypothesis dict
    """
    data = request.json or {}
    statement = data.get("statement")
    status = data.get("status")
    category = data.get("category")

    if statement is None and status is None and category is None:
        return jsonify({"error": "Provide statement, status, or category to update"}), 400

    if status and status not in _VALID_HYPOTHESIS_STATUSES:
        return jsonify({
            "error": f"Invalid status: {status}. Valid: {sorted(_VALID_HYPOTHESIS_STATUSES)}"
        }), 400

    if category is not None and category != "" and category not in _VALID_CATEGORIES:
        return jsonify({
            "error": f"Invalid category: {category}. Valid: {sorted(_VALID_CATEGORIES)}"
        }), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM hypotheses WHERE id = ?", (hyp_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": f"Hypothesis {hyp_id} not found"}), 404

        updates = []
        params = []

        if statement is not None:
            stmt = statement.strip()
            if not stmt:
                return jsonify({"error": "statement cannot be empty"}), 400
            updates.append("statement = ?")
            params.append(stmt)

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if category is not None:
            updates.append("category = ?")
            params.append(category if category else None)

        updates.append("updated_at = ?")
        params.append(_now_iso())
        params.append(hyp_id)

        conn.execute(
            f"UPDATE hypotheses SET {', '.join(updates)} WHERE id = ?",
            params,
        )

        updated_row = conn.execute(
            "SELECT * FROM hypotheses WHERE id = ?", (hyp_id,)
        ).fetchone()

    logger.info("Updated hypothesis #%d", hyp_id)
    return jsonify(_row_to_hypothesis(updated_row))


# ═════════════════════════════════════════════════════════════
# 13. Delete Hypothesis
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/hypotheses/<int:hyp_id>", methods=["DELETE"])
def delete_hypothesis(hyp_id):
    """Delete a hypothesis and all its evidence (cascade).

    Returns: {deleted: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM hypotheses WHERE id = ?", (hyp_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": f"Hypothesis {hyp_id} not found"}), 404

        conn.execute("DELETE FROM hypotheses WHERE id = ?", (hyp_id,))

    logger.info("Deleted hypothesis #%d", hyp_id)
    return jsonify({"deleted": True, "id": hyp_id})


# ═════════════════════════════════════════════════════════════
# 14. Add Evidence to Hypothesis
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/hypotheses/<int:hyp_id>/evidence", methods=["POST"])
def add_hypothesis_evidence(hyp_id):
    """Add a piece of evidence to a hypothesis.

    Body: {
        direction: "supports"|"contradicts"|"neutral",
        description: str,
        weight?: float (0.1 to 3.0, default 1.0),
        entity_id?: int,
        attr_slug?: str,
        evidence_id?: int,
        source?: "manual"|"ai"
    }

    Returns: created evidence dict (201)
    """
    data = request.json or {}
    direction = data.get("direction")
    description = data.get("description", "").strip()
    weight = data.get("weight", 1.0)
    entity_id = data.get("entity_id")
    attr_slug = data.get("attr_slug")
    evidence_id = data.get("evidence_id")
    source = data.get("source", "manual")

    if not direction:
        return jsonify({"error": "direction is required"}), 400
    if direction not in _VALID_EVIDENCE_DIRECTIONS:
        return jsonify({
            "error": f"Invalid direction: {direction}. Valid: {sorted(_VALID_EVIDENCE_DIRECTIONS)}"
        }), 400
    if not description:
        return jsonify({"error": "description is required"}), 400

    if not isinstance(weight, (int, float)):
        return jsonify({"error": "weight must be a number"}), 400
    weight = max(0.1, min(3.0, float(weight)))

    if source not in ("manual", "ai"):
        source = "manual"

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Verify hypothesis exists
        hyp = conn.execute(
            "SELECT id, project_id FROM hypotheses WHERE id = ?", (hyp_id,)
        ).fetchone()
        if not hyp:
            return jsonify({"error": f"Hypothesis {hyp_id} not found"}), 404

        # Verify entity if provided
        if entity_id:
            entity = conn.execute(
                "SELECT id FROM entities WHERE id = ? AND is_deleted = 0",
                (entity_id,),
            ).fetchone()
            if not entity:
                return jsonify({"error": f"Entity {entity_id} not found"}), 404

        # Verify evidence if provided
        if evidence_id:
            ev = conn.execute(
                "SELECT id FROM evidence WHERE id = ?", (evidence_id,)
            ).fetchone()
            if not ev:
                return jsonify({"error": f"Evidence {evidence_id} not found"}), 404

        now = _now_iso()
        cursor = conn.execute(
            """INSERT INTO hypothesis_evidence
               (hypothesis_id, direction, weight, description,
                entity_id, attr_slug, evidence_id, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (hyp_id, direction, weight, description,
             entity_id, attr_slug, evidence_id, source, now),
        )
        ev_id = cursor.lastrowid

        # Recompute confidence and update hypothesis
        all_evidence = conn.execute(
            "SELECT direction, weight FROM hypothesis_evidence WHERE hypothesis_id = ?",
            (hyp_id,),
        ).fetchall()
        new_confidence, _, _, _ = _compute_hypothesis_confidence(all_evidence)

        conn.execute(
            "UPDATE hypotheses SET confidence = ?, updated_at = ? WHERE id = ?",
            (new_confidence, now, hyp_id),
        )

        row = conn.execute(
            """SELECT he.*, e.name as entity_name
               FROM hypothesis_evidence he
               LEFT JOIN entities e ON e.id = he.entity_id
               WHERE he.id = ?""",
            (ev_id,),
        ).fetchone()

    result = _row_to_evidence(row)
    if "entity_name" in row.keys():
        result["entity_name"] = row["entity_name"]

    logger.info(
        "Added %s evidence #%d to hypothesis #%d (weight=%.1f)",
        direction, ev_id, hyp_id, weight,
    )
    return jsonify(result), 201


# ═════════════════════════════════════════════════════════════
# 15. Remove Evidence from Hypothesis
# ═════════════════════════════════════════════════════════════

@insights_bp.route(
    "/api/insights/hypotheses/<int:hyp_id>/evidence/<int:ev_id>",
    methods=["DELETE"],
)
def remove_hypothesis_evidence(hyp_id, ev_id):
    """Remove a piece of evidence from a hypothesis.

    Returns: {deleted: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Verify the evidence belongs to the hypothesis
        row = conn.execute(
            "SELECT id FROM hypothesis_evidence WHERE id = ? AND hypothesis_id = ?",
            (ev_id, hyp_id),
        ).fetchone()
        if not row:
            return jsonify({
                "error": f"Evidence {ev_id} not found on hypothesis {hyp_id}"
            }), 404

        conn.execute("DELETE FROM hypothesis_evidence WHERE id = ?", (ev_id,))

        # Recompute confidence
        now = _now_iso()
        remaining = conn.execute(
            "SELECT direction, weight FROM hypothesis_evidence WHERE hypothesis_id = ?",
            (hyp_id,),
        ).fetchall()
        new_confidence, _, _, _ = _compute_hypothesis_confidence(remaining)

        conn.execute(
            "UPDATE hypotheses SET confidence = ?, updated_at = ? WHERE id = ?",
            (new_confidence, now, hyp_id),
        )

    logger.info("Removed evidence #%d from hypothesis #%d", ev_id, hyp_id)
    return jsonify({"deleted": True, "id": ev_id})


# ═════════════════════════════════════════════════════════════
# 16. Compute Hypothesis Score
# ═════════════════════════════════════════════════════════════

@insights_bp.route("/api/insights/hypotheses/<int:hyp_id>/score")
def hypothesis_score(hyp_id):
    """Compute the current confidence score for a hypothesis.

    The score is derived from the weighted balance of supporting vs
    contradicting evidence. Neutral evidence does not affect the score.

    Returns:
        {
            hypothesis_id, confidence,
            supports_weight, contradicts_weight, neutral_weight,
            evidence_count, breakdown: {supports: N, contradicts: N, neutral: N}
        }
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        hyp = conn.execute(
            "SELECT id FROM hypotheses WHERE id = ?", (hyp_id,)
        ).fetchone()
        if not hyp:
            return jsonify({"error": f"Hypothesis {hyp_id} not found"}), 404

        evidence_rows = conn.execute(
            "SELECT direction, weight FROM hypothesis_evidence WHERE hypothesis_id = ?",
            (hyp_id,),
        ).fetchall()

    confidence, supports, contradicts, neutral = _compute_hypothesis_confidence(evidence_rows)

    supports_count = sum(1 for e in evidence_rows if e["direction"] == "supports")
    contradicts_count = sum(1 for e in evidence_rows if e["direction"] == "contradicts")
    neutral_count = sum(1 for e in evidence_rows if e["direction"] == "neutral")

    return jsonify({
        "hypothesis_id": hyp_id,
        "confidence": confidence,
        "supports_weight": round(supports, 2),
        "contradicts_weight": round(contradicts, 2),
        "neutral_weight": round(neutral, 2),
        "evidence_count": len(evidence_rows),
        "breakdown": {
            "supports": supports_count,
            "contradicts": contradicts_count,
            "neutral": neutral_count,
        },
    })
