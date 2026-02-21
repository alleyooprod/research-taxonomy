"""Shared helpers, constants, and DB schema for the Reports package."""
import json
import uuid
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from loguru import logger

from .._utils import require_project_id as _require_project_id, now_iso as _now_iso

_REPORT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS workbench_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    template TEXT NOT NULL,
    title TEXT NOT NULL,
    content_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    updated_at TEXT,
    is_ai_generated INTEGER DEFAULT 0,
    metadata_json TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id)
)
"""

_TABLE_ENSURED = False


def _ensure_table(conn):
    """Create the workbench_reports table if it doesn't exist yet."""
    global _TABLE_ENSURED
    if not _TABLE_ENSURED:
        conn.execute(_REPORT_TABLE_SQL)
        _TABLE_ENSURED = True

def _row_to_report(row):
    """Convert a DB row to a report dict."""
    content = {}
    if row["content_json"]:
        try:
            content = json.loads(row["content_json"])
        except (json.JSONDecodeError, TypeError):
            content = {}
    metadata = {}
    if row["metadata_json"]:
        try:
            metadata = json.loads(row["metadata_json"])
        except (json.JSONDecodeError, TypeError):
            metadata = {}
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "template": row["template"],
        "title": row["title"],
        "sections": content.get("sections", []),
        "generated_at": row["generated_at"],
        "updated_at": row["updated_at"],
        "is_ai_generated": bool(row["is_ai_generated"]),
        "metadata": metadata,
    }


# ── Template definitions ─────────────────────────────────────

# ── JSON schemas for structured LLM output ───────────────────

_REPORT_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["heading", "content"],
                "additionalProperties": False
            }
        }
    },
    "required": ["title", "sections"],
    "additionalProperties": False
})

_TEMPLATES = [
    {
        "slug": "market_overview",
        "name": "Market Overview",
        "description": (
            "High-level summary of the market landscape: entity counts by type, "
            "category distribution, top attributes, and key statistics."
        ),
        "required_data": "3+ entities in the project",
    },
    {
        "slug": "competitive_landscape",
        "name": "Competitive Landscape",
        "description": (
            "Feature comparison matrix, gap analysis, and competitive positioning "
            "across entities with shared attributes."
        ),
        "required_data": "2+ entities with comparable attributes",
    },
    {
        "slug": "product_teardown",
        "name": "Product Teardown",
        "description": (
            "Deep-dive analysis of a single entity: all attributes, evidence catalogue, "
            "extraction results, and data completeness assessment."
        ),
        "required_data": "At least one entity with 5+ attributes",
    },
    {
        "slug": "design_patterns",
        "name": "Design Patterns",
        "description": (
            "Visual design audit: screenshot evidence grouped by journey stage, "
            "UI pattern identification, and cross-entity comparisons."
        ),
        "required_data": "Screenshot evidence attached to at least one entity",
    },
    {
        "slug": "change_report",
        "name": "Change Report",
        "description": (
            "Temporal analysis: what has changed across entity snapshots, "
            "attribute diffs, and trend identification over time."
        ),
        "required_data": "Entity snapshots captured at different times",
    },
]


def _check_template_availability(conn, project_id):
    """Return a dict of template_slug -> available (bool) for a project."""

    # Entity count
    total_entities = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE project_id = ? AND is_deleted = 0",
        (project_id,),
    ).fetchone()[0]

    # Entities with 2+ comparable attributes (at least 2 entities sharing an attr_slug)
    comparable_count = conn.execute(
        """
        SELECT COUNT(DISTINCT ea.entity_id)
        FROM entity_attributes ea
        JOIN entities e ON e.id = ea.entity_id
        WHERE e.project_id = ? AND e.is_deleted = 0
        AND ea.attr_slug IN (
            SELECT attr_slug FROM entity_attributes ea2
            JOIN entities e2 ON e2.id = ea2.entity_id
            WHERE e2.project_id = ? AND e2.is_deleted = 0
            GROUP BY ea2.attr_slug
            HAVING COUNT(DISTINCT ea2.entity_id) >= 2
        )
        """,
        (project_id, project_id),
    ).fetchone()[0]

    # Any entity with 5+ distinct attribute slugs
    rich_entity = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT ea.entity_id, COUNT(DISTINCT ea.attr_slug) as attr_count
            FROM entity_attributes ea
            JOIN entities e ON e.id = ea.entity_id
            WHERE e.project_id = ? AND e.is_deleted = 0
            GROUP BY ea.entity_id
            HAVING attr_count >= 5
        )
        """,
        (project_id,),
    ).fetchone()[0]

    # Any entity with screenshot evidence
    screenshot_count = conn.execute(
        """
        SELECT COUNT(DISTINCT ev.entity_id)
        FROM evidence ev
        JOIN entities e ON e.id = ev.entity_id
        WHERE e.project_id = ? AND ev.evidence_type = 'screenshot'
        """,
        (project_id,),
    ).fetchone()[0]

    # Any entity_snapshots exist
    snapshot_count = conn.execute(
        "SELECT COUNT(*) FROM entity_snapshots WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]

    return {
        "market_overview": total_entities >= 3,
        "competitive_landscape": comparable_count >= 2,
        "product_teardown": rich_entity > 0,
        "design_patterns": screenshot_count > 0,
        "change_report": snapshot_count > 0,
    }
