"""Shared helpers, constants, and DB schema for the Insights package."""
import json
import math
import re
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from loguru import logger

from .._utils import (
    require_project_id as _require_project_id,
    now_iso as _now_iso,
    parse_json_field as _parse_json_field,
)

# ── Constants ────────────────────────────────────────────────

# ── JSON schema for structured LLM output ─────────────────────

_INSIGHT_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["pattern", "trend", "gap", "outlier", "correlation", "recommendation"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "notable", "important", "critical"]},
                    "category": {"type": "string", "enum": ["pricing", "features", "design", "market", "competitive"]},
                    "confidence": {"type": "number"}
                },
                "required": ["type", "title", "description", "severity", "category", "confidence"],
                "additionalProperties": False
            }
        }
    },
    "required": ["insights"],
    "additionalProperties": False
})

_VALID_INSIGHT_TYPES = {"pattern", "trend", "gap", "outlier", "correlation", "recommendation"}
_VALID_SEVERITIES = {"info", "notable", "important", "critical"}
_VALID_INSIGHT_SOURCES = {"rule", "ai"}
_VALID_HYPOTHESIS_STATUSES = {"open", "supported", "refuted", "inconclusive"}
_VALID_EVIDENCE_DIRECTIONS = {"supports", "contradicts", "neutral"}
_VALID_CATEGORIES = {"pricing", "features", "design", "market", "competitive"}

# Thresholds for rule-based detectors
_FEATURE_GAP_THRESHOLD = 0.5      # Attribute must be on >50% of entities to be a "gap"
_SPARSE_COVERAGE_THRESHOLD = 0.25  # <25% coverage = sparse
_PRICING_OUTLIER_STDEVS = 2.0     # >2 standard deviations = outlier
_STALE_DAYS = 30                  # Entities not updated in 30+ days = stale
_DUPLICATE_SIMILARITY = 0.8       # Name similarity threshold for duplicate detection
_CLUSTER_MIN_OVERLAP = 0.6        # 60% feature overlap to consider a cluster


# ── Lazy Table Creation ──────────────────────────────────────

_INSIGHTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    insight_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    evidence_refs TEXT DEFAULT '[]',
    severity TEXT DEFAULT 'info',
    category TEXT,
    confidence REAL DEFAULT 0.5,
    source TEXT DEFAULT 'rule',
    is_dismissed INTEGER DEFAULT 0,
    is_pinned INTEGER DEFAULT 0,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_HYPOTHESES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    statement TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    confidence REAL DEFAULT 0.5,
    category TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
"""

_HYPOTHESIS_EVIDENCE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hypothesis_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_id INTEGER NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    direction TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    description TEXT NOT NULL,
    entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    attr_slug TEXT,
    evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    source TEXT DEFAULT 'manual',
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_TABLE_ENSURED = False


def _ensure_tables(conn):
    """Create insight and hypothesis tables if they don't exist yet."""
    global _TABLE_ENSURED
    if not _TABLE_ENSURED:
        conn.execute(_INSIGHTS_TABLE_SQL)
        conn.execute(_HYPOTHESES_TABLE_SQL)
        conn.execute(_HYPOTHESIS_EVIDENCE_TABLE_SQL)
        _TABLE_ENSURED = True


# ── Shared Helpers ───────────────────────────────────────────


def _row_to_insight(row):
    """Convert a DB row to an insight dict."""
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "insight_type": row["insight_type"],
        "title": row["title"],
        "description": row["description"],
        "evidence_refs": _parse_json_field(row["evidence_refs"], []),
        "severity": row["severity"],
        "category": row["category"],
        "confidence": row["confidence"],
        "source": row["source"],
        "is_dismissed": bool(row["is_dismissed"]),
        "is_pinned": bool(row["is_pinned"]),
        "metadata": _parse_json_field(row["metadata_json"]),
        "created_at": row["created_at"],
    }


def _row_to_hypothesis(row):
    """Convert a DB row to a hypothesis dict."""
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "statement": row["statement"],
        "status": row["status"],
        "confidence": row["confidence"],
        "category": row["category"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_evidence(row):
    """Convert a DB row to a hypothesis evidence dict."""
    return {
        "id": row["id"],
        "hypothesis_id": row["hypothesis_id"],
        "direction": row["direction"],
        "weight": row["weight"],
        "description": row["description"],
        "entity_id": row["entity_id"],
        "attr_slug": row["attr_slug"],
        "evidence_id": row["evidence_id"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _compute_hypothesis_confidence(evidence_rows):
    """Compute a confidence score from hypothesis evidence rows.

    The algorithm:
    - Sum weighted supports and weighted contradicts separately
    - Neutrals contribute nothing to the score
    - Score = supports / (supports + contradicts) if any directional evidence
    - Score = 0.5 if no directional evidence (agnostic)
    - Clamped to [0.0, 1.0]

    Returns: (confidence_float, supports_total, contradicts_total, neutral_total)
    """
    supports_total = 0.0
    contradicts_total = 0.0
    neutral_total = 0.0

    for ev in evidence_rows:
        direction = ev["direction"]
        weight = ev["weight"] or 1.0

        if direction == "supports":
            supports_total += weight
        elif direction == "contradicts":
            contradicts_total += weight
        else:
            neutral_total += weight

    total_directional = supports_total + contradicts_total
    if total_directional == 0:
        confidence = 0.5
    else:
        confidence = supports_total / total_directional

    confidence = max(0.0, min(1.0, round(confidence, 4)))
    return confidence, supports_total, contradicts_total, neutral_total


