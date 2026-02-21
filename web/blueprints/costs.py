"""Cost tracking API — unified LLM cost logging, summaries, and budgets.

Provides endpoints for:
- Cost summary by model and operation
- Daily cost trends
- Project budget management (get/set)
"""
from flask import Blueprint, request, jsonify, current_app
from loguru import logger

from ._utils import require_project_id as _require_project_id, now_iso as _now_iso

costs_bp = Blueprint("costs", __name__)

# ── Lazy table creation ──────────────────────────────────────

_LLM_CALLS_SQL = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    operation TEXT,
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_BUDGETS_SQL = """
CREATE TABLE IF NOT EXISTS project_budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE,
    budget_usd REAL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
)
"""

_TABLE_ENSURED = False


def _ensure_tables(conn):
    """Create cost-tracking tables if they don't exist yet."""
    global _TABLE_ENSURED
    if not _TABLE_ENSURED:
        conn.execute(_LLM_CALLS_SQL)
        conn.execute(_BUDGETS_SQL)
        _TABLE_ENSURED = True


# ── GET /api/costs/summary ───────────────────────────────────

@costs_bp.route("/api/costs/summary")
def cost_summary():
    """Return cost summary for a project (or all projects if no project_id)."""
    project_id = request.args.get("project_id", type=int)

    with current_app.db._get_conn() as conn:
        _ensure_tables(conn)

        # Build WHERE clause
        where = ""
        params = ()
        if project_id:
            where = "WHERE project_id = ?"
            params = (project_id,)

        # Total cost and calls
        row = conn.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0) AS total_cost, "
            f"COUNT(*) AS total_calls "
            f"FROM llm_calls {where}",
            params,
        ).fetchone()
        total_cost = row[0]
        total_calls = row[1]

        # By model
        by_model = {}
        for r in conn.execute(
            f"SELECT model, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost "
            f"FROM llm_calls {where} GROUP BY model ORDER BY cost DESC",
            params,
        ).fetchall():
            by_model[r[0] or "unknown"] = {"calls": r[1], "cost_usd": round(r[2], 4)}

        # By operation
        by_operation = {}
        for r in conn.execute(
            f"SELECT operation, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost "
            f"FROM llm_calls {where} GROUP BY operation ORDER BY cost DESC",
            params,
        ).fetchall():
            by_operation[r[0] or "unknown"] = {"calls": r[1], "cost_usd": round(r[2], 4)}

    return jsonify({
        "total_cost_usd": round(total_cost, 4),
        "total_calls": total_calls,
        "by_model": by_model,
        "by_operation": by_operation,
    })


# ── GET /api/costs/daily ─────────────────────────────────────

@costs_bp.route("/api/costs/daily")
def cost_daily():
    """Return daily cost breakdown for the last N days."""
    project_id = request.args.get("project_id", type=int)
    days = request.args.get("days", 30, type=int)
    if days < 1:
        days = 1
    if days > 365:
        days = 365

    with current_app.db._get_conn() as conn:
        _ensure_tables(conn)

        where_parts = [f"created_at >= datetime('now', '-{days} days')"]
        params = ()
        if project_id:
            where_parts.append("project_id = ?")
            params = (project_id,)

        where = "WHERE " + " AND ".join(where_parts)

        rows = conn.execute(
            f"SELECT date(created_at) AS day, "
            f"COALESCE(SUM(cost_usd), 0) AS cost, "
            f"COUNT(*) AS calls "
            f"FROM llm_calls {where} "
            f"GROUP BY day ORDER BY day",
            params,
        ).fetchall()

    return jsonify([
        {"date": r[0], "cost_usd": round(r[1], 4), "calls": r[2]}
        for r in rows
    ])


# ── GET /api/costs/budget ────────────────────────────────────

@costs_bp.route("/api/costs/budget")
def get_budget():
    """Return the budget and spend for a project."""
    pid, err = _require_project_id()
    if err:
        return err

    with current_app.db._get_conn() as conn:
        _ensure_tables(conn)

        # Get budget
        row = conn.execute(
            "SELECT budget_usd FROM project_budgets WHERE project_id = ?",
            (pid,),
        ).fetchone()
        budget_usd = row[0] if row else 0.0

        # Get spend
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE project_id = ?",
            (pid,),
        ).fetchone()
        spent_usd = row[0]

    remaining = max(0.0, budget_usd - spent_usd)
    pct = (spent_usd / budget_usd * 100) if budget_usd > 0 else 0.0

    return jsonify({
        "budget_usd": round(budget_usd, 4),
        "spent_usd": round(spent_usd, 4),
        "remaining_usd": round(remaining, 4),
        "percentage_used": round(pct, 1),
    })


# ── PUT /api/costs/budget ────────────────────────────────────

@costs_bp.route("/api/costs/budget", methods=["PUT"])
def set_budget():
    """Set or update the budget for a project."""
    pid, err = _require_project_id()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    budget_usd = data.get("budget_usd")
    if budget_usd is None:
        return jsonify({"error": "budget_usd is required"}), 400

    try:
        budget_usd = float(budget_usd)
    except (TypeError, ValueError):
        return jsonify({"error": "budget_usd must be a number"}), 400

    if budget_usd < 0:
        return jsonify({"error": "budget_usd must be non-negative"}), 400

    with current_app.db._get_conn() as conn:
        _ensure_tables(conn)
        now = _now_iso()
        conn.execute(
            "INSERT INTO project_budgets (project_id, budget_usd, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(project_id) DO UPDATE SET budget_usd = ?, updated_at = ?",
            (pid, budget_usd, now, budget_usd, now),
        )

    logger.info("Budget set for project {}: ${}", pid, budget_usd)
    return jsonify({"status": "ok", "project_id": pid, "budget_usd": budget_usd})
