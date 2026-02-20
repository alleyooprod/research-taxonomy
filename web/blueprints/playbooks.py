"""Research Playbooks API — reusable research methodology templates.

A "playbook" is a saved sequence of research steps that can be applied
to any project to guide the analyst through a structured workflow.
Playbooks act as checklist templates for research — define once, run many
times across different projects.

Two tables back this feature:

- **playbooks** — the template definitions (name, category, ordered steps).
- **playbook_runs** — instances of a playbook being executed against a
  specific project, tracking per-step progress.

Endpoints:

    Playbook CRUD:
        POST   /api/playbooks                    — Create playbook
        GET    /api/playbooks                    — List playbooks (filterable)
        GET    /api/playbooks/<id>               — Get single playbook
        PUT    /api/playbooks/<id>               — Update playbook
        DELETE /api/playbooks/<id>               — Delete playbook (non-template only)
        POST   /api/playbooks/<id>/duplicate     — Clone a playbook

    Playbook Runs:
        POST   /api/playbooks/<id>/run           — Start a run for a project
        GET    /api/playbooks/runs               — List runs for a project
        GET    /api/playbooks/runs/<run_id>      — Get run with progress
        PUT    /api/playbooks/runs/<run_id>/step/<step_index>  — Complete/update step
        PUT    /api/playbooks/runs/<run_id>/status — Update run status

    Templates:
        GET    /api/playbooks/templates          — List built-in templates
        POST   /api/playbooks/templates/seed     — Seed default templates
        POST   /api/playbooks/<id>/improve       — AI-suggest improvements (mocked)
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, current_app
from loguru import logger

playbooks_bp = Blueprint("playbooks", __name__)

# ── Constants ────────────────────────────────────────────────

_VALID_STEP_TYPES = {"discover", "capture", "extract", "analyse", "review", "custom"}
_VALID_RUN_STATUSES = {"in_progress", "completed", "abandoned"}
_VALID_CATEGORIES = {"market", "product", "design", "competitive", "custom"}

# ── Lazy Table Creation ──────────────────────────────────────

_PLAYBOOKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS playbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    steps TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT DEFAULT '{}',
    is_template INTEGER DEFAULT 0,
    usage_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
"""

_PLAYBOOK_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS playbook_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playbook_id INTEGER NOT NULL REFERENCES playbooks(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    status TEXT DEFAULT 'in_progress',
    progress TEXT DEFAULT '[]',
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
)
"""

_TABLE_ENSURED = False


def _ensure_tables(conn):
    """Create playbook tables if they don't exist yet."""
    global _TABLE_ENSURED
    if not _TABLE_ENSURED:
        conn.execute(_PLAYBOOKS_TABLE_SQL)
        conn.execute(_PLAYBOOK_RUNS_TABLE_SQL)
        _TABLE_ENSURED = True


# ── Shared Helpers ───────────────────────────────────────────

def _require_project_id():
    """Extract and validate project_id from query string or JSON body.

    Returns (project_id, None) on success or (None, error_response) on failure.
    """
    pid = request.args.get("project_id", type=int)
    if not pid:
        return None, (jsonify({"error": "project_id is required"}), 400)
    return pid, None


def _now_iso():
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_json_field(raw, default=None):
    """Safely parse a JSON text field from a DB row."""
    if default is None:
        default = {}
    if not raw:
        return default
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return default


def _row_to_playbook(row):
    """Convert a DB row to a playbook dict."""
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "steps": _parse_json_field(row["steps"], []),
        "metadata": _parse_json_field(row["metadata_json"]),
        "is_template": bool(row["is_template"]),
        "usage_count": row["usage_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_run(row):
    """Convert a DB row to a playbook run dict."""
    return {
        "id": row["id"],
        "playbook_id": row["playbook_id"],
        "project_id": row["project_id"],
        "status": row["status"],
        "progress": _parse_json_field(row["progress"], []),
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def _validate_steps(steps):
    """Validate a list of step objects.

    Each step must have at least a title. Type is validated against
    _VALID_STEP_TYPES if present.

    Returns (normalised_steps, None) on success or (None, error_string) on failure.
    """
    if not isinstance(steps, list):
        return None, "steps must be a JSON array"

    if len(steps) == 0:
        return None, "steps must contain at least one step"

    normalised = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return None, f"Step {i} must be an object"

        title = step.get("title", "").strip()
        if not title:
            return None, f"Step {i} is missing a title"

        step_type = step.get("type", "custom")
        if step_type not in _VALID_STEP_TYPES:
            return None, (
                f"Step {i} has invalid type '{step_type}'. "
                f"Valid: {sorted(_VALID_STEP_TYPES)}"
            )

        normalised.append({
            "title": title,
            "description": step.get("description", ""),
            "type": step_type,
            "estimated_minutes": step.get("estimated_minutes"),
            "tools": step.get("tools", []),
            "guidance": step.get("guidance", ""),
        })

    return normalised, None


def _initialise_progress(steps):
    """Create a blank progress array from a list of step definitions.

    Returns a JSON-ready list of progress entries, one per step.
    """
    return [
        {
            "step_index": i,
            "completed": False,
            "notes": "",
            "completed_at": None,
        }
        for i in range(len(steps))
    ]


# ── Default Template Definitions ─────────────────────────────

_DEFAULT_TEMPLATES = [
    {
        "name": "Market Mapping",
        "description": (
            "Systematic market mapping workflow: discover companies, capture "
            "evidence, extract key attributes, and analyse the competitive "
            "landscape. Ideal for building a comprehensive market overview."
        ),
        "category": "market",
        "steps": [
            {
                "title": "Identify scope",
                "description": "Define the market, geography, and entity types to include",
                "type": "discover",
                "estimated_minutes": 15,
                "tools": [],
                "guidance": (
                    "Start by defining the boundaries of your research: which "
                    "market segment, geography, and company types are in scope. "
                    "Document inclusion/exclusion criteria."
                ),
            },
            {
                "title": "AI discover companies",
                "description": "Use AI Discovery to find relevant companies and products",
                "type": "discover",
                "estimated_minutes": 30,
                "tools": ["ai_discovery"],
                "guidance": (
                    "Use AI Discovery with specific prompts for your market. "
                    "Try multiple angles: competitors, adjacent players, emerging "
                    "startups. Aim for 10-30 entities."
                ),
            },
            {
                "title": "Capture websites",
                "description": "Capture company websites and key pages as evidence",
                "type": "capture",
                "estimated_minutes": 45,
                "tools": ["web_capture"],
                "guidance": (
                    "For each discovered company, capture their homepage, about "
                    "page, and product pages. Focus on pages that reveal "
                    "positioning, features, and pricing."
                ),
            },
            {
                "title": "Extract key attributes",
                "description": "Run extraction on captured pages to populate entity attributes",
                "type": "extract",
                "estimated_minutes": 30,
                "tools": ["extraction"],
                "guidance": (
                    "Run the extraction pipeline on captured evidence. Focus on "
                    "attributes that enable comparison: pricing, features, "
                    "target market, founding year, team size."
                ),
            },
            {
                "title": "Review extractions",
                "description": "Review and approve/reject extracted data in the review queue",
                "type": "review",
                "estimated_minutes": 20,
                "tools": ["review_queue"],
                "guidance": (
                    "Go through the extraction review queue. Accept accurate "
                    "extractions, edit those that need correction, and reject "
                    "any that are clearly wrong."
                ),
            },
            {
                "title": "Analyse competitive landscape",
                "description": "Use lenses and insights to identify patterns across entities",
                "type": "analyse",
                "estimated_minutes": 30,
                "tools": ["lenses", "insights"],
                "guidance": (
                    "Apply analytical lenses to compare entities. Look for "
                    "clusters, gaps in the market, pricing patterns, and "
                    "feature differentiators. Pin important insights."
                ),
            },
            {
                "title": "Generate report",
                "description": "Generate a market overview or competitive landscape report",
                "type": "analyse",
                "estimated_minutes": 15,
                "tools": ["reports"],
                "guidance": (
                    "Generate a Market Overview report to summarise findings. "
                    "Optionally generate an AI-enhanced narrative for "
                    "presentation to stakeholders."
                ),
            },
        ],
    },
    {
        "name": "Product Teardown",
        "description": (
            "Deep-dive product analysis: capture product and pricing pages, "
            "extract features and pricing, and generate a teardown report. "
            "Best for understanding a specific product in detail."
        ),
        "category": "product",
        "steps": [
            {
                "title": "Select target products",
                "description": "Identify the products to analyse in depth",
                "type": "discover",
                "estimated_minutes": 10,
                "tools": [],
                "guidance": (
                    "Choose 1-5 products for detailed teardown. These should be "
                    "direct competitors or products you want to understand deeply. "
                    "Create entities for each if not already present."
                ),
            },
            {
                "title": "Capture product pages",
                "description": "Capture detailed product/feature pages for each target",
                "type": "capture",
                "estimated_minutes": 30,
                "tools": ["web_capture"],
                "guidance": (
                    "For each product, capture: product overview page, feature "
                    "detail pages, comparison pages, and any demo/tour pages. "
                    "Capture screenshots of key UI elements."
                ),
            },
            {
                "title": "Capture pricing pages",
                "description": "Capture pricing and plan information for each target",
                "type": "capture",
                "estimated_minutes": 20,
                "tools": ["web_capture"],
                "guidance": (
                    "Capture pricing pages, plan comparison tables, and any "
                    "enterprise/contact-us pages. Include screenshots of "
                    "pricing tables for visual reference."
                ),
            },
            {
                "title": "Extract product features",
                "description": "Extract features, capabilities, and technical details",
                "type": "extract",
                "estimated_minutes": 20,
                "tools": ["extraction"],
                "guidance": (
                    "Run extraction focused on product attributes: features, "
                    "integrations, supported platforms, API availability, "
                    "and technical specifications."
                ),
            },
            {
                "title": "Extract pricing",
                "description": "Extract pricing tiers, plan names, and feature limits",
                "type": "extract",
                "estimated_minutes": 15,
                "tools": ["extraction"],
                "guidance": (
                    "Run extraction on pricing pages to capture: plan names, "
                    "prices, billing periods, feature limits per plan, "
                    "and any free tier details."
                ),
            },
            {
                "title": "Review findings",
                "description": "Review all extractions and correct any errors",
                "type": "review",
                "estimated_minutes": 15,
                "tools": ["review_queue"],
                "guidance": (
                    "Carefully review extracted pricing and feature data. "
                    "Pricing extraction is often imprecise — verify numbers "
                    "against captured screenshots."
                ),
            },
            {
                "title": "Generate product teardown report",
                "description": "Generate a detailed product teardown report",
                "type": "analyse",
                "estimated_minutes": 10,
                "tools": ["reports"],
                "guidance": (
                    "Generate a Product Teardown report for each target entity. "
                    "Use the AI-enhanced option for narrative analysis of "
                    "strengths, weaknesses, and positioning."
                ),
            },
        ],
    },
    {
        "name": "Design Research",
        "description": (
            "Visual design analysis workflow: capture screenshots, classify "
            "them by journey stage, identify UI patterns, and generate a "
            "design patterns report for cross-product comparison."
        ),
        "category": "design",
        "steps": [
            {
                "title": "Define design scope",
                "description": "Identify which products and journeys to analyse visually",
                "type": "discover",
                "estimated_minutes": 10,
                "tools": [],
                "guidance": (
                    "Decide which products and user journeys to capture. "
                    "Common journeys: onboarding, pricing, checkout, "
                    "dashboard, settings. Aim for 3-5 products."
                ),
            },
            {
                "title": "Capture screenshots",
                "description": "Capture screenshots of key screens across target products",
                "type": "capture",
                "estimated_minutes": 60,
                "tools": ["web_capture", "app_store"],
                "guidance": (
                    "Systematically capture each journey step for each product. "
                    "Name files descriptively (e.g. 'acme_onboarding_step1.png'). "
                    "Include both desktop and mobile views where relevant."
                ),
            },
            {
                "title": "Classify screenshots",
                "description": "Auto-classify screenshots into journey stages and UI patterns",
                "type": "extract",
                "estimated_minutes": 10,
                "tools": ["screenshot_classifier"],
                "guidance": (
                    "Run the screenshot classifier on captured evidence. "
                    "It will auto-detect journey stages (landing, signup, "
                    "dashboard, etc.) and UI patterns (hero, cards, tables)."
                ),
            },
            {
                "title": "Group into journey sequences",
                "description": "Organise classified screenshots into coherent journey sequences",
                "type": "analyse",
                "estimated_minutes": 15,
                "tools": ["screenshot_classifier"],
                "guidance": (
                    "Review the auto-grouped journey sequences. Correct any "
                    "misclassifications. Ensure each product has a complete "
                    "journey from landing through to core product."
                ),
            },
            {
                "title": "Analyse design patterns",
                "description": "Compare visual patterns across products",
                "type": "analyse",
                "estimated_minutes": 20,
                "tools": ["lenses", "insights"],
                "guidance": (
                    "Look across products for common design patterns: "
                    "navigation styles, pricing table layouts, onboarding "
                    "flows, dashboard structures. Note standout designs."
                ),
            },
            {
                "title": "Generate design patterns report",
                "description": "Generate a design patterns report with visual comparisons",
                "type": "analyse",
                "estimated_minutes": 10,
                "tools": ["reports"],
                "guidance": (
                    "Generate a Design Patterns report. This groups screenshots "
                    "by journey stage across entities, making it easy to compare "
                    "how different products handle the same user need."
                ),
            },
        ],
    },
    {
        "name": "Competitive Intelligence",
        "description": (
            "Ongoing competitive monitoring workflow: define the competitive "
            "set, capture and extract data, set up monitoring, form hypotheses, "
            "and generate competitive analysis reports."
        ),
        "category": "competitive",
        "steps": [
            {
                "title": "Define competitive set",
                "description": "Identify direct and indirect competitors to monitor",
                "type": "discover",
                "estimated_minutes": 20,
                "tools": ["ai_discovery"],
                "guidance": (
                    "Define your competitive set: direct competitors (same "
                    "market, same solution), indirect competitors (same problem, "
                    "different approach), and potential entrants. Use AI Discovery "
                    "to fill gaps."
                ),
            },
            {
                "title": "Capture company websites",
                "description": "Capture key pages for each competitor",
                "type": "capture",
                "estimated_minutes": 45,
                "tools": ["web_capture"],
                "guidance": (
                    "Capture each competitor's homepage, product page, pricing "
                    "page, about page, and blog/news page. These form the "
                    "baseline for ongoing monitoring."
                ),
            },
            {
                "title": "Extract features and pricing",
                "description": "Extract comparable attributes across competitors",
                "type": "extract",
                "estimated_minutes": 30,
                "tools": ["extraction"],
                "guidance": (
                    "Run extraction to populate: key features, pricing tiers, "
                    "target market, company size, funding stage, and "
                    "differentiators for each competitor."
                ),
            },
            {
                "title": "Set up monitoring",
                "description": "Configure monitoring for competitor changes",
                "type": "custom",
                "estimated_minutes": 15,
                "tools": ["monitoring"],
                "guidance": (
                    "Set up monitoring watches for key competitor pages. "
                    "Focus on pricing pages and product feature pages where "
                    "changes are most strategically relevant."
                ),
            },
            {
                "title": "Create hypotheses",
                "description": "Form testable hypotheses about the competitive landscape",
                "type": "analyse",
                "estimated_minutes": 20,
                "tools": ["insights"],
                "guidance": (
                    "Based on initial data, create hypotheses about: market "
                    "direction, pricing trends, feature convergence, and "
                    "competitive positioning. Link evidence to each hypothesis."
                ),
            },
            {
                "title": "Analyse with lenses",
                "description": "Apply analytical lenses to compare competitors systematically",
                "type": "analyse",
                "estimated_minutes": 25,
                "tools": ["lenses", "insights"],
                "guidance": (
                    "Apply lenses for feature comparison, pricing analysis, "
                    "and market positioning. Generate insights to surface "
                    "patterns and outliers across the competitive set."
                ),
            },
            {
                "title": "Generate competitive landscape report",
                "description": "Produce a comprehensive competitive analysis",
                "type": "analyse",
                "estimated_minutes": 15,
                "tools": ["reports"],
                "guidance": (
                    "Generate a Competitive Landscape report. Use the AI-enhanced "
                    "option for strategic narrative. Share with stakeholders "
                    "and update periodically as monitoring detects changes."
                ),
            },
        ],
    },
]


def _seed_default_templates(conn):
    """Insert default playbook templates if they don't already exist.

    Checks by name + is_template=1 to avoid duplicate seeding.
    Returns the count of newly inserted templates.
    """
    inserted = 0

    for tpl in _DEFAULT_TEMPLATES:
        existing = conn.execute(
            "SELECT id FROM playbooks WHERE name = ? AND is_template = 1",
            (tpl["name"],),
        ).fetchone()

        if existing:
            continue

        now = _now_iso()
        conn.execute(
            """INSERT INTO playbooks
               (name, description, category, steps, metadata_json,
                is_template, usage_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, '{}', 1, 0, ?, ?)""",
            (
                tpl["name"],
                tpl["description"],
                tpl["category"],
                json.dumps(tpl["steps"]),
                now,
                now,
            ),
        )
        inserted += 1

    return inserted


# ═════════════════════════════════════════════════════════════
# 1. Create Playbook
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks", methods=["POST"])
def create_playbook():
    """Create a new playbook.

    Body: {name, description?, category?, steps: [{title, description?, type?, ...}]}

    Returns: created playbook (201)
    """
    data = request.json or {}
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    category = data.get("category")
    steps_raw = data.get("steps")

    if not name:
        return jsonify({"error": "name is required"}), 400

    if category and category not in _VALID_CATEGORIES:
        return jsonify({
            "error": f"Invalid category: {category}. Valid: {sorted(_VALID_CATEGORIES)}"
        }), 400

    if steps_raw is None:
        return jsonify({"error": "steps is required"}), 400

    steps, step_err = _validate_steps(steps_raw)
    if step_err:
        return jsonify({"error": step_err}), 400

    metadata = data.get("metadata", {})

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        now = _now_iso()
        cursor = conn.execute(
            """INSERT INTO playbooks
               (name, description, category, steps, metadata_json,
                is_template, usage_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)""",
            (
                name,
                description or None,
                category,
                json.dumps(steps),
                json.dumps(metadata),
                now,
                now,
            ),
        )
        playbook_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM playbooks WHERE id = ?", (playbook_id,)
        ).fetchone()

    logger.info("Created playbook #%d: %s", playbook_id, name)
    return jsonify(_row_to_playbook(row)), 201


# ═════════════════════════════════════════════════════════════
# 2. List Playbooks
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks")
def list_playbooks():
    """List all playbooks with optional filters.

    Query params:
        category (optional): Filter by category
        is_template (optional): Filter by template status (0|1)

    Returns: list of playbook dicts
    """
    category = request.args.get("category")
    is_template = request.args.get("is_template")

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = "SELECT * FROM playbooks WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if is_template is not None:
            query += " AND is_template = ?"
            params.append(int(is_template))

        query += " ORDER BY is_template DESC, usage_count DESC, name COLLATE NOCASE"
        rows = conn.execute(query, params).fetchall()

    playbooks = [_row_to_playbook(row) for row in rows]
    return jsonify(playbooks)


# ═════════════════════════════════════════════════════════════
# 3. Get Single Playbook
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/<int:playbook_id>")
def get_playbook(playbook_id):
    """Get a single playbook by ID with usage statistics.

    Returns: playbook dict with run stats
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM playbooks WHERE id = ?", (playbook_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Playbook {playbook_id} not found"}), 404

        playbook = _row_to_playbook(row)

        # Enrich with run stats
        run_stats = conn.execute(
            """SELECT
                   COUNT(*) as total_runs,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_runs,
                   SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as active_runs,
                   SUM(CASE WHEN status = 'abandoned' THEN 1 ELSE 0 END) as abandoned_runs
               FROM playbook_runs WHERE playbook_id = ?""",
            (playbook_id,),
        ).fetchone()

        playbook["run_stats"] = {
            "total_runs": run_stats["total_runs"],
            "completed_runs": run_stats["completed_runs"],
            "active_runs": run_stats["active_runs"],
            "abandoned_runs": run_stats["abandoned_runs"],
        }

    return jsonify(playbook)


# ═════════════════════════════════════════════════════════════
# 4. Update Playbook
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/<int:playbook_id>", methods=["PUT"])
def update_playbook(playbook_id):
    """Update a playbook's name, description, category, or steps.

    Body: {name?, description?, category?, steps?}

    Returns: updated playbook dict
    """
    data = request.json or {}
    name = data.get("name")
    description = data.get("description")
    category = data.get("category")
    steps_raw = data.get("steps")
    metadata = data.get("metadata")

    if all(v is None for v in [name, description, category, steps_raw, metadata]):
        return jsonify({"error": "Provide at least one field to update"}), 400

    if category is not None and category != "" and category not in _VALID_CATEGORIES:
        return jsonify({
            "error": f"Invalid category: {category}. Valid: {sorted(_VALID_CATEGORIES)}"
        }), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM playbooks WHERE id = ?", (playbook_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": f"Playbook {playbook_id} not found"}), 404

        updates = []
        params = []

        if name is not None:
            stripped = name.strip()
            if not stripped:
                return jsonify({"error": "name cannot be empty"}), 400
            updates.append("name = ?")
            params.append(stripped)

        if description is not None:
            updates.append("description = ?")
            params.append(description.strip() or None)

        if category is not None:
            updates.append("category = ?")
            params.append(category if category else None)

        if steps_raw is not None:
            steps, step_err = _validate_steps(steps_raw)
            if step_err:
                return jsonify({"error": step_err}), 400
            updates.append("steps = ?")
            params.append(json.dumps(steps))

        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(json.dumps(metadata))

        updates.append("updated_at = ?")
        params.append(_now_iso())
        params.append(playbook_id)

        conn.execute(
            f"UPDATE playbooks SET {', '.join(updates)} WHERE id = ?",
            params,
        )

        updated_row = conn.execute(
            "SELECT * FROM playbooks WHERE id = ?", (playbook_id,)
        ).fetchone()

    logger.info("Updated playbook #%d", playbook_id)
    return jsonify(_row_to_playbook(updated_row))


# ═════════════════════════════════════════════════════════════
# 5. Delete Playbook
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/<int:playbook_id>", methods=["DELETE"])
def delete_playbook(playbook_id):
    """Delete a playbook (non-template only). Cascades to runs.

    Returns: {deleted: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id, is_template, name FROM playbooks WHERE id = ?",
            (playbook_id,),
        ).fetchone()

        if not row:
            return jsonify({"error": f"Playbook {playbook_id} not found"}), 404

        if row["is_template"]:
            return jsonify({
                "error": "Cannot delete a built-in template. Duplicate it first to customise."
            }), 403

        # Delete associated runs first (for DBs without FK cascade support)
        conn.execute(
            "DELETE FROM playbook_runs WHERE playbook_id = ?", (playbook_id,)
        )
        conn.execute("DELETE FROM playbooks WHERE id = ?", (playbook_id,))

    logger.info("Deleted playbook #%d: %s", playbook_id, row["name"])
    return jsonify({"deleted": True, "id": playbook_id})


# ═════════════════════════════════════════════════════════════
# 6. Duplicate Playbook
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/<int:playbook_id>/duplicate", methods=["POST"])
def duplicate_playbook(playbook_id):
    """Clone a playbook for customisation.

    The clone is always a non-template with usage_count = 0.
    An optional body can override the name: {name?: str}

    Returns: the newly created playbook (201)
    """
    data = request.json or {}
    custom_name = data.get("name", "").strip()

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM playbooks WHERE id = ?", (playbook_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Playbook {playbook_id} not found"}), 404

        new_name = custom_name if custom_name else f"{row['name']} (copy)"
        now = _now_iso()

        cursor = conn.execute(
            """INSERT INTO playbooks
               (name, description, category, steps, metadata_json,
                is_template, usage_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)""",
            (
                new_name,
                row["description"],
                row["category"],
                row["steps"],
                row["metadata_json"],
                now,
                now,
            ),
        )
        new_id = cursor.lastrowid

        new_row = conn.execute(
            "SELECT * FROM playbooks WHERE id = ?", (new_id,)
        ).fetchone()

    logger.info(
        "Duplicated playbook #%d -> #%d: %s", playbook_id, new_id, new_name
    )
    return jsonify(_row_to_playbook(new_row)), 201


# ═════════════════════════════════════════════════════════════
# 7. Start Playbook Run
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/<int:playbook_id>/run", methods=["POST"])
def start_run(playbook_id):
    """Start a playbook run for a project.

    Body: {project_id}

    Returns: created run dict (201)
    """
    data = request.json or {}
    project_id = data.get("project_id")

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Verify playbook exists
        playbook_row = conn.execute(
            "SELECT id, name, steps FROM playbooks WHERE id = ?",
            (playbook_id,),
        ).fetchone()
        if not playbook_row:
            return jsonify({"error": f"Playbook {playbook_id} not found"}), 404

        # Verify project exists
        project_row = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not project_row:
            return jsonify({"error": f"Project {project_id} not found"}), 404

        # Parse steps to build initial progress
        steps = _parse_json_field(playbook_row["steps"], [])
        progress = _initialise_progress(steps)
        now = _now_iso()

        cursor = conn.execute(
            """INSERT INTO playbook_runs
               (playbook_id, project_id, status, progress, started_at, completed_at)
               VALUES (?, ?, 'in_progress', ?, ?, NULL)""",
            (playbook_id, project_id, json.dumps(progress), now),
        )
        run_id = cursor.lastrowid

        # Increment playbook usage count
        conn.execute(
            "UPDATE playbooks SET usage_count = usage_count + 1, updated_at = ? WHERE id = ?",
            (now, playbook_id),
        )

        run_row = conn.execute(
            "SELECT * FROM playbook_runs WHERE id = ?", (run_id,)
        ).fetchone()

    result = _row_to_run(run_row)
    result["playbook_name"] = playbook_row["name"]

    logger.info(
        "Started playbook run #%d (playbook=%s, project=%d)",
        run_id, playbook_row["name"], project_id,
    )
    return jsonify(result), 201


# ═════════════════════════════════════════════════════════════
# 8. List Runs for a Project
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/runs")
def list_runs():
    """List playbook runs for a project.

    Query: ?project_id=N

    Returns: list of run dicts with playbook name
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        rows = conn.execute(
            """SELECT pr.*, p.name as playbook_name, p.category as playbook_category
               FROM playbook_runs pr
               JOIN playbooks p ON p.id = pr.playbook_id
               WHERE pr.project_id = ?
               ORDER BY pr.started_at DESC""",
            (project_id,),
        ).fetchall()

    runs = []
    for row in rows:
        run = _row_to_run(row)
        run["playbook_name"] = row["playbook_name"]
        run["playbook_category"] = row["playbook_category"]

        # Compute step progress summary
        progress = run["progress"]
        total_steps = len(progress)
        completed_steps = sum(1 for p in progress if p.get("completed"))
        run["total_steps"] = total_steps
        run["completed_steps"] = completed_steps
        run["progress_pct"] = (
            round(completed_steps / total_steps * 100, 1)
            if total_steps > 0
            else 0
        )

        runs.append(run)

    return jsonify(runs)


# ═════════════════════════════════════════════════════════════
# 9. Get Single Run
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/runs/<int:run_id>")
def get_run(run_id):
    """Get a playbook run with full progress detail.

    Returns: run dict with playbook steps merged into progress
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            """SELECT pr.*, p.name as playbook_name, p.category as playbook_category,
                      p.steps as playbook_steps, p.description as playbook_description
               FROM playbook_runs pr
               JOIN playbooks p ON p.id = pr.playbook_id
               WHERE pr.id = ?""",
            (run_id,),
        ).fetchone()

    if not row:
        return jsonify({"error": f"Run {run_id} not found"}), 404

    run = _row_to_run(row)
    run["playbook_name"] = row["playbook_name"]
    run["playbook_category"] = row["playbook_category"]
    run["playbook_description"] = row["playbook_description"]

    # Merge playbook step definitions with progress
    steps = _parse_json_field(row["playbook_steps"], [])
    progress = run["progress"]

    merged_steps = []
    for i, step in enumerate(steps):
        step_progress = progress[i] if i < len(progress) else {
            "step_index": i,
            "completed": False,
            "notes": "",
            "completed_at": None,
        }
        merged_steps.append({
            **step,
            "step_index": i,
            "completed": step_progress.get("completed", False),
            "notes": step_progress.get("notes", ""),
            "completed_at": step_progress.get("completed_at"),
        })

    run["steps"] = merged_steps

    # Compute summary
    total_steps = len(merged_steps)
    completed_steps = sum(1 for s in merged_steps if s.get("completed"))
    run["total_steps"] = total_steps
    run["completed_steps"] = completed_steps
    run["progress_pct"] = (
        round(completed_steps / total_steps * 100, 1)
        if total_steps > 0
        else 0
    )

    return jsonify(run)


# ═════════════════════════════════════════════════════════════
# 10. Complete/Update a Step
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route(
    "/api/playbooks/runs/<int:run_id>/step/<int:step_index>",
    methods=["PUT"],
)
def update_step(run_id, step_index):
    """Complete or update a step in a playbook run.

    Body: {completed: bool, notes?: str}

    Returns: updated run dict
    """
    data = request.json or {}
    completed = data.get("completed")
    notes = data.get("notes")

    if completed is None and notes is None:
        return jsonify({"error": "Provide completed and/or notes to update"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM playbook_runs WHERE id = ?", (run_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Run {run_id} not found"}), 404

        if row["status"] != "in_progress":
            return jsonify({
                "error": f"Cannot update steps on a run with status '{row['status']}'"
            }), 400

        progress = _parse_json_field(row["progress"], [])

        if step_index < 0 or step_index >= len(progress):
            return jsonify({
                "error": f"Invalid step_index {step_index}. "
                         f"This run has {len(progress)} steps (0-{len(progress) - 1})."
            }), 400

        # Update the step
        if completed is not None:
            progress[step_index]["completed"] = bool(completed)
            if completed:
                progress[step_index]["completed_at"] = _now_iso()
            else:
                progress[step_index]["completed_at"] = None

        if notes is not None:
            progress[step_index]["notes"] = notes

        conn.execute(
            "UPDATE playbook_runs SET progress = ? WHERE id = ?",
            (json.dumps(progress), run_id),
        )

        # Auto-complete the run if all steps are done
        all_done = all(p.get("completed") for p in progress)
        if all_done:
            now = _now_iso()
            conn.execute(
                "UPDATE playbook_runs SET status = 'completed', completed_at = ? WHERE id = ?",
                (now, run_id),
            )

        updated_row = conn.execute(
            "SELECT * FROM playbook_runs WHERE id = ?", (run_id,)
        ).fetchone()

    result = _row_to_run(updated_row)

    # Add progress summary
    total_steps = len(result["progress"])
    completed_steps = sum(1 for p in result["progress"] if p.get("completed"))
    result["total_steps"] = total_steps
    result["completed_steps"] = completed_steps
    result["progress_pct"] = (
        round(completed_steps / total_steps * 100, 1)
        if total_steps > 0
        else 0
    )

    logger.info(
        "Updated step %d on run #%d (completed=%s, %d/%d steps done)",
        step_index, run_id, completed, completed_steps, total_steps,
    )
    return jsonify(result)


# ═════════════════════════════════════════════════════════════
# 11. Update Run Status
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route(
    "/api/playbooks/runs/<int:run_id>/status",
    methods=["PUT"],
)
def update_run_status(run_id):
    """Update a run's overall status.

    Body: {status: "completed"|"abandoned"}

    Returns: updated run dict
    """
    data = request.json or {}
    new_status = data.get("status")

    if not new_status:
        return jsonify({"error": "status is required"}), 400

    if new_status not in _VALID_RUN_STATUSES:
        return jsonify({
            "error": f"Invalid status: {new_status}. Valid: {sorted(_VALID_RUN_STATUSES)}"
        }), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM playbook_runs WHERE id = ?", (run_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Run {run_id} not found"}), 404

        now = _now_iso()
        completed_at = now if new_status in ("completed", "abandoned") else None

        conn.execute(
            "UPDATE playbook_runs SET status = ?, completed_at = ? WHERE id = ?",
            (new_status, completed_at, run_id),
        )

        updated_row = conn.execute(
            "SELECT * FROM playbook_runs WHERE id = ?", (run_id,)
        ).fetchone()

    logger.info("Updated run #%d status to '%s'", run_id, new_status)
    return jsonify(_row_to_run(updated_row))


# ═════════════════════════════════════════════════════════════
# 12. List Built-in Templates
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/templates")
def list_templates():
    """List built-in playbook templates only.

    Returns: list of template playbook dicts
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        rows = conn.execute(
            "SELECT * FROM playbooks WHERE is_template = 1 ORDER BY name COLLATE NOCASE"
        ).fetchall()

    templates = [_row_to_playbook(row) for row in rows]
    return jsonify(templates)


# ═════════════════════════════════════════════════════════════
# 13. Seed Default Templates
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/templates/seed", methods=["POST"])
def seed_templates():
    """Seed the 4 default playbook templates if not already present.

    Returns: {seeded: N, message: str}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)
        count = _seed_default_templates(conn)

    if count > 0:
        logger.info("Seeded %d default playbook templates", count)

    return jsonify({
        "seeded": count,
        "message": (
            f"Seeded {count} new template(s)."
            if count > 0
            else "All default templates already exist."
        ),
    }), 201 if count > 0 else 200


# ═════════════════════════════════════════════════════════════
# 14. AI Improve Playbook (Mocked)
# ═════════════════════════════════════════════════════════════

@playbooks_bp.route("/api/playbooks/<int:playbook_id>/improve", methods=["POST"])
def improve_playbook(playbook_id):
    """AI-suggest improvements to a playbook based on past run data.

    Currently returns mocked suggestions. In a future version this will
    use LLM analysis of completed runs to suggest step additions,
    reorderings, or time estimate adjustments.

    Returns: {suggestions: [...], playbook_id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM playbooks WHERE id = ?", (playbook_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Playbook {playbook_id} not found"}), 404

        playbook = _row_to_playbook(row)

        # Gather run data for analysis context
        runs = conn.execute(
            """SELECT pr.*, p.name as playbook_name
               FROM playbook_runs pr
               JOIN playbooks p ON p.id = pr.playbook_id
               WHERE pr.playbook_id = ?
               ORDER BY pr.started_at DESC
               LIMIT 20""",
            (playbook_id,),
        ).fetchall()

        completed_runs = [r for r in runs if r["status"] == "completed"]
        abandoned_runs = [r for r in runs if r["status"] == "abandoned"]

    # Mocked suggestions based on run data patterns
    suggestions = []
    steps = playbook["steps"]
    total_runs = len(runs)
    completed_count = len(completed_runs)
    abandoned_count = len(abandoned_runs)

    if total_runs == 0:
        suggestions.append({
            "type": "info",
            "title": "No run data yet",
            "description": (
                "This playbook has not been run yet. Complete a few runs "
                "to get data-driven improvement suggestions."
            ),
        })
    else:
        # Completion rate suggestion
        if total_runs >= 3 and abandoned_count > completed_count:
            suggestions.append({
                "type": "warning",
                "title": "High abandonment rate",
                "description": (
                    f"{abandoned_count}/{total_runs} runs were abandoned. "
                    f"Consider simplifying the playbook by removing or "
                    f"combining steps, or adding clearer guidance."
                ),
            })

        # Step count suggestion
        if len(steps) > 8:
            suggestions.append({
                "type": "optimisation",
                "title": "Consider fewer steps",
                "description": (
                    f"This playbook has {len(steps)} steps. Playbooks with "
                    f"5-7 steps tend to have higher completion rates. "
                    f"Consider combining related steps."
                ),
            })

        # Time estimate suggestion
        total_minutes = sum(
            s.get("estimated_minutes", 0) for s in steps if s.get("estimated_minutes")
        )
        if total_minutes > 180:
            suggestions.append({
                "type": "optimisation",
                "title": "Consider splitting into phases",
                "description": (
                    f"Total estimated time is {total_minutes} minutes "
                    f"({total_minutes / 60:.1f} hours). Consider splitting "
                    f"into two playbooks — one for data collection and "
                    f"one for analysis."
                ),
            })

        # Guidance suggestion
        steps_without_guidance = [
            s["title"] for s in steps if not s.get("guidance")
        ]
        if steps_without_guidance:
            suggestions.append({
                "type": "improvement",
                "title": "Add guidance to steps",
                "description": (
                    f"{len(steps_without_guidance)} step(s) lack guidance: "
                    f"{', '.join(steps_without_guidance[:3])}. "
                    f"Adding guidance helps analysts follow the methodology "
                    f"consistently."
                ),
            })

    if not suggestions:
        suggestions.append({
            "type": "info",
            "title": "Playbook looks good",
            "description": (
                "No specific improvements suggested based on current run data. "
                "Keep running the playbook to accumulate more data for analysis."
            ),
        })

    return jsonify({
        "playbook_id": playbook_id,
        "suggestions": suggestions,
        "run_data": {
            "total_runs": total_runs,
            "completed": completed_count,
            "abandoned": abandoned_count,
        },
    })
