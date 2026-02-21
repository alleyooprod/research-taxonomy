"""Cross-Project Intelligence API — detecting overlapping entities across
projects, carrying forward entity data, and cross-project pattern analysis.

When the same company, product, or entity appears in multiple research
projects, this module detects the overlap, lets users link and sync
data between them, and surfaces analytical insights about divergence,
coverage gaps, and trends spanning the entire workspace.

Endpoints:

    Entity Overlap Detection:
        POST /api/cross-project/scan                    — Scan all projects for overlapping entities
        GET  /api/cross-project/overlaps                — List detected entity links
        POST /api/cross-project/link                    — Manually link two entities
        DELETE /api/cross-project/link/<id>              — Remove a link

    Entity Data Carry-Forward:
        GET  /api/cross-project/entity/<id>/linked       — Get all entities linked to this one
        POST /api/cross-project/sync                     — Sync attributes between linked entities
        GET  /api/cross-project/entity/<id>/diff         — Compare attributes of two linked entities

    Cross-Project Analysis:
        POST /api/cross-project/analyse                  — Run cross-project pattern analysis
        GET  /api/cross-project/insights                 — List cross-project insights
        PUT  /api/cross-project/insights/<id>/dismiss    — Dismiss a cross-project insight
        DELETE /api/cross-project/insights/<id>          — Delete a cross-project insight
        GET  /api/cross-project/stats                    — Summary stats
"""
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, current_app
from loguru import logger

from ._utils import (
    now_iso as _now_iso,
    parse_json_field as _parse_json_field,
)

crossproject_bp = Blueprint("crossproject", __name__)

# ── Constants ────────────────────────────────────────────────

_VALID_LINK_TYPES = {"same_entity", "related", "parent_child"}
_VALID_LINK_SOURCES = {"manual", "auto", "ai"}
_VALID_INSIGHT_TYPES = {"overlap", "divergence", "trend", "coverage_gap"}
_VALID_SEVERITIES = {"info", "notable", "important", "critical"}

_DICE_THRESHOLD = 0.8  # Name similarity threshold for auto-detection


# ── Lazy Table Creation ──────────────────────────────────────

_ENTITY_LINKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS entity_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    link_type TEXT DEFAULT 'same_entity',
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT 'manual',
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_entity_id, target_entity_id)
)
"""

_CROSS_PROJECT_INSIGHTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cross_project_insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    project_ids TEXT NOT NULL DEFAULT '[]',
    entity_ids TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT DEFAULT '{}',
    severity TEXT DEFAULT 'info',
    is_dismissed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_TABLE_ENSURED = False


def _ensure_tables(conn):
    """Create entity_links and cross_project_insights tables if needed."""
    global _TABLE_ENSURED
    if not _TABLE_ENSURED:
        conn.execute(_ENTITY_LINKS_TABLE_SQL)
        conn.execute(_CROSS_PROJECT_INSIGHTS_TABLE_SQL)
        _TABLE_ENSURED = True


# ── Shared Helpers ───────────────────────────────────────────


def _row_to_link(row):
    """Convert a DB row to an entity link dict."""
    return {
        "id": row["id"],
        "source_entity_id": row["source_entity_id"],
        "target_entity_id": row["target_entity_id"],
        "link_type": row["link_type"],
        "confidence": row["confidence"],
        "source": row["source"],
        "metadata": _parse_json_field(row["metadata_json"]),
        "created_at": row["created_at"],
    }


def _row_to_insight(row):
    """Convert a DB row to a cross-project insight dict."""
    return {
        "id": row["id"],
        "insight_type": row["insight_type"],
        "title": row["title"],
        "description": row["description"],
        "project_ids": _parse_json_field(row["project_ids"], []),
        "entity_ids": _parse_json_field(row["entity_ids"], []),
        "metadata": _parse_json_field(row["metadata_json"]),
        "severity": row["severity"],
        "is_dismissed": bool(row["is_dismissed"]),
        "created_at": row["created_at"],
    }


def _dice_similarity(a, b):
    """Dice coefficient on character bigrams.

    Returns a value between 0.0 (no similarity) and 1.0 (identical).
    Used for fuzzy entity name matching across projects.
    """
    if not a or not b:
        return 0.0
    a = a.lower().strip()
    b = b.lower().strip()
    if a == b:
        return 1.0
    bigrams_a = set(a[i:i + 2] for i in range(len(a) - 1))
    bigrams_b = set(b[i:i + 2] for i in range(len(b) - 1))
    if not bigrams_a or not bigrams_b:
        return 0.0
    return 2 * len(bigrams_a & bigrams_b) / (len(bigrams_a) + len(bigrams_b))


def _normalize_url(url):
    """Normalize a URL to its domain for comparison.

    Strips protocol and 'www.' prefix to get a canonical domain string.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        domain = parsed.netloc.lower().lstrip("www.")
        return domain
    except Exception:
        return url.lower().strip()


def _get_entity_attrs_summary(conn, entity_id):
    """Fetch the latest attribute values for an entity.

    Returns: dict of {attr_slug: value}
    """
    rows = conn.execute(
        """SELECT ea.attr_slug, ea.value
           FROM entity_attributes ea
           WHERE ea.entity_id = ?
             AND ea.id IN (
                 SELECT MAX(id) FROM entity_attributes
                 WHERE entity_id = ?
                 GROUP BY attr_slug
             )""",
        (entity_id, entity_id),
    ).fetchall()
    return {r["attr_slug"]: r["value"] for r in rows}


def _get_entity_with_project(conn, entity_id):
    """Fetch an entity joined with its project info.

    Returns: dict with entity fields + project_name, or None.
    """
    row = conn.execute(
        """SELECT e.id, e.name, e.type_slug, e.slug, e.status,
                  e.source, e.project_id, e.is_starred,
                  e.created_at, e.updated_at,
                  p.name AS project_name
           FROM entities e
           JOIN projects p ON p.id = e.project_id
           WHERE e.id = ? AND e.is_deleted = 0""",
        (entity_id,),
    ).fetchone()
    return dict(row) if row else None


def _link_exists(conn, source_id, target_id):
    """Check if a link already exists between two entities (in either direction)."""
    row = conn.execute(
        """SELECT id FROM entity_links
           WHERE (source_entity_id = ? AND target_entity_id = ?)
              OR (source_entity_id = ? AND target_entity_id = ?)""",
        (source_id, target_id, target_id, source_id),
    ).fetchone()
    return row is not None


# ═════════════════════════════════════════════════════════════
# Overlap Scanning Algorithm
# ═════════════════════════════════════════════════════════════

def _scan_for_overlaps(conn):
    """Scan all projects for overlapping entities.

    Compares entities across different projects using:
    1. Exact URL domain matching
    2. Dice coefficient name similarity (>= 0.8)

    Creates auto-sourced entity_links for new detections.
    Returns: list of newly created link dicts.
    """
    # Fetch all non-deleted entities with their URL attributes
    entities = conn.execute(
        """SELECT e.id, e.name, e.project_id, e.type_slug
           FROM entities e
           WHERE e.is_deleted = 0
           ORDER BY e.project_id, e.name COLLATE NOCASE""",
    ).fetchall()
    entities = [dict(r) for r in entities]

    if len(entities) < 2:
        return []

    # Fetch URL-like attributes for all entities
    entity_ids = [e["id"] for e in entities]
    if entity_ids:
        placeholders = ",".join("?" * len(entity_ids))
        url_rows = conn.execute(
            f"""SELECT entity_id, value FROM entity_attributes
                WHERE entity_id IN ({placeholders})
                  AND (attr_slug LIKE '%url%' OR attr_slug LIKE '%website%'
                       OR attr_slug LIKE '%domain%' OR attr_slug LIKE '%link%')
                  AND value IS NOT NULL AND value != ''
                ORDER BY id DESC""",
            entity_ids,
        ).fetchall()

        # Keep only the latest URL per entity
        entity_urls = {}
        for r in url_rows:
            eid = r["entity_id"]
            if eid not in entity_urls:
                entity_urls[eid] = _normalize_url(r["value"])
    else:
        entity_urls = {}

    # Group entities by project
    by_project = {}
    for e in entities:
        by_project.setdefault(e["project_id"], []).append(e)

    project_ids = sorted(by_project.keys())
    new_links = []

    # Compare entities across different projects
    for i in range(len(project_ids)):
        for j in range(i + 1, len(project_ids)):
            pid_a = project_ids[i]
            pid_b = project_ids[j]

            for entity_a in by_project[pid_a]:
                for entity_b in by_project[pid_b]:
                    # Skip if link already exists
                    if _link_exists(conn, entity_a["id"], entity_b["id"]):
                        continue

                    match_type = None
                    confidence = 0.0
                    metadata = {}

                    # 1. Check URL match
                    url_a = entity_urls.get(entity_a["id"], "")
                    url_b = entity_urls.get(entity_b["id"], "")
                    if url_a and url_b and url_a == url_b:
                        match_type = "url"
                        confidence = 0.95
                        metadata["match_method"] = "url_domain"
                        metadata["matched_domain"] = url_a

                    # 2. Check name similarity
                    if not match_type:
                        name_sim = _dice_similarity(entity_a["name"], entity_b["name"])
                        if name_sim >= _DICE_THRESHOLD:
                            match_type = "name"
                            confidence = round(name_sim, 4)
                            metadata["match_method"] = "name_similarity"
                            metadata["similarity_score"] = confidence

                    if match_type:
                        # Insert the link
                        try:
                            cursor = conn.execute(
                                """INSERT INTO entity_links
                                   (source_entity_id, target_entity_id, link_type,
                                    confidence, source, metadata_json)
                                   VALUES (?, ?, 'same_entity', ?, 'auto', ?)""",
                                (
                                    entity_a["id"],
                                    entity_b["id"],
                                    confidence,
                                    json.dumps(metadata),
                                ),
                            )
                            link_id = cursor.lastrowid
                            row = conn.execute(
                                "SELECT * FROM entity_links WHERE id = ?",
                                (link_id,),
                            ).fetchone()
                            link = _row_to_link(row)
                            # Annotate with entity names for the response
                            link["source_entity_name"] = entity_a["name"]
                            link["target_entity_name"] = entity_b["name"]
                            link["source_project_id"] = entity_a["project_id"]
                            link["target_project_id"] = entity_b["project_id"]
                            new_links.append(link)
                        except Exception as e:
                            # UNIQUE constraint violation — link already exists
                            logger.debug(
                                "Link already exists for entities %d <-> %d: %s",
                                entity_a["id"], entity_b["id"], e,
                            )

    return new_links


# ═════════════════════════════════════════════════════════════
# Cross-Project Analysis Detectors
# ═════════════════════════════════════════════════════════════

def _detect_multi_project_entities(conn):
    """Find entities linked across 3+ projects.

    These are entities that appear in many research efforts and may
    represent key market players worth tracking closely.

    Returns: list of insight dicts ready to INSERT.
    """
    rows = conn.execute(
        """SELECT el.source_entity_id, el.target_entity_id,
                  e1.project_id AS p1, e2.project_id AS p2,
                  e1.name AS name1, e2.name AS name2
           FROM entity_links el
           JOIN entities e1 ON e1.id = el.source_entity_id AND e1.is_deleted = 0
           JOIN entities e2 ON e2.id = el.target_entity_id AND e2.is_deleted = 0
           WHERE el.link_type = 'same_entity'""",
    ).fetchall()

    if not rows:
        return []

    # Build adjacency: entity_id -> set of project_ids it appears in
    entity_projects = {}
    entity_names = {}
    entity_linked = {}  # entity_id -> set of linked entity_ids

    for r in rows:
        sid, tid = r["source_entity_id"], r["target_entity_id"]
        p1, p2 = r["p1"], r["p2"]

        entity_projects.setdefault(sid, set()).add(p1)
        entity_projects.setdefault(tid, set()).add(p2)
        # Through linkage, both entities are effectively in both projects
        entity_projects[sid].add(p2)
        entity_projects[tid].add(p1)

        entity_names[sid] = r["name1"]
        entity_names[tid] = r["name2"]

        entity_linked.setdefault(sid, set()).add(tid)
        entity_linked.setdefault(tid, set()).add(sid)

    insights = []
    seen_groups = set()

    for eid, projects in entity_projects.items():
        if len(projects) < 3:
            continue

        # Create a canonical key for this group to avoid duplicates
        group = frozenset({eid} | entity_linked.get(eid, set()))
        if group in seen_groups:
            continue
        seen_groups.add(group)

        name = entity_names.get(eid, "Unknown")
        all_eids = sorted(group)
        all_pids = sorted(projects)

        insights.append({
            "insight_type": "overlap",
            "title": f"'{name}' appears across {len(all_pids)} projects",
            "description": (
                f"The entity '{name}' (and its linked counterparts) appear "
                f"in {len(all_pids)} different research projects. This entity "
                f"is a frequent subject of research and may warrant a "
                f"dedicated tracking effort or consolidated view."
            ),
            "project_ids": json.dumps(all_pids),
            "entity_ids": json.dumps(all_eids),
            "severity": "notable" if len(all_pids) >= 4 else "info",
            "metadata_json": json.dumps({
                "project_count": len(all_pids),
                "entity_count": len(all_eids),
            }),
        })

    return insights


def _detect_attribute_divergence(conn):
    """Find linked entities where the same attribute has different values.

    This highlights cases where different research projects have captured
    conflicting information about what should be the same entity.

    Returns: list of insight dicts ready to INSERT.
    """
    links = conn.execute(
        """SELECT el.id AS link_id,
                  el.source_entity_id, el.target_entity_id,
                  e1.name AS name1, e2.name AS name2,
                  e1.project_id AS p1, e2.project_id AS p2
           FROM entity_links el
           JOIN entities e1 ON e1.id = el.source_entity_id AND e1.is_deleted = 0
           JOIN entities e2 ON e2.id = el.target_entity_id AND e2.is_deleted = 0
           WHERE el.link_type = 'same_entity'""",
    ).fetchall()

    insights = []

    for link in links:
        attrs_a = _get_entity_attrs_summary(conn, link["source_entity_id"])
        attrs_b = _get_entity_attrs_summary(conn, link["target_entity_id"])

        # Find shared attribute slugs with different values
        common_slugs = set(attrs_a.keys()) & set(attrs_b.keys())
        divergent = []

        for slug in common_slugs:
            val_a = (attrs_a[slug] or "").strip().lower()
            val_b = (attrs_b[slug] or "").strip().lower()
            if val_a and val_b and val_a != val_b:
                divergent.append({
                    "attr_slug": slug,
                    "value_a": attrs_a[slug],
                    "value_b": attrs_b[slug],
                })

        if not divergent:
            continue

        # Limit to top 5 divergences for readability
        shown = divergent[:5]
        detail_parts = []
        for d in shown:
            detail_parts.append(
                f"  - {d['attr_slug']}: \"{d['value_a']}\" vs \"{d['value_b']}\""
            )
        detail_str = "\n".join(detail_parts)
        extra = f" (and {len(divergent) - 5} more)" if len(divergent) > 5 else ""

        insights.append({
            "insight_type": "divergence",
            "title": (
                f"Data conflict: '{link['name1']}' has "
                f"{len(divergent)} divergent attribute{'s' if len(divergent) != 1 else ''}"
            ),
            "description": (
                f"The linked entities '{link['name1']}' (project {link['p1']}) "
                f"and '{link['name2']}' (project {link['p2']}) have different "
                f"values for {len(divergent)} attribute{'s' if len(divergent) != 1 else ''}:\n"
                f"{detail_str}{extra}\n"
                f"Consider syncing data or verifying which values are current."
            ),
            "project_ids": json.dumps(sorted({link["p1"], link["p2"]})),
            "entity_ids": json.dumps(
                sorted([link["source_entity_id"], link["target_entity_id"]])
            ),
            "severity": "notable" if len(divergent) >= 3 else "info",
            "metadata_json": json.dumps({
                "link_id": link["link_id"],
                "divergent_count": len(divergent),
                "divergent_attrs": divergent,
            }),
        })

    return insights


def _detect_coverage_gaps(conn):
    """Find linked entities where one has significantly more data than the other.

    Highlights opportunities to carry forward research from a well-researched
    entity to its less-complete counterpart in another project.

    Returns: list of insight dicts ready to INSERT.
    """
    links = conn.execute(
        """SELECT el.source_entity_id, el.target_entity_id,
                  e1.name AS name1, e2.name AS name2,
                  e1.project_id AS p1, e2.project_id AS p2,
                  p1t.name AS project_name_1, p2t.name AS project_name_2
           FROM entity_links el
           JOIN entities e1 ON e1.id = el.source_entity_id AND e1.is_deleted = 0
           JOIN entities e2 ON e2.id = el.target_entity_id AND e2.is_deleted = 0
           JOIN projects p1t ON p1t.id = e1.project_id
           JOIN projects p2t ON p2t.id = e2.project_id
           WHERE el.link_type = 'same_entity'""",
    ).fetchall()

    insights = []

    for link in links:
        attrs_a = _get_entity_attrs_summary(conn, link["source_entity_id"])
        attrs_b = _get_entity_attrs_summary(conn, link["target_entity_id"])

        count_a = len(attrs_a)
        count_b = len(attrs_b)

        # Only flag if one has at least 3 more attributes and 2x the other
        if count_a == 0 and count_b == 0:
            continue

        richer_id = None
        sparser_id = None
        richer_name = None
        sparser_name = None
        richer_project = None
        sparser_project = None
        richer_count = 0
        sparser_count = 0
        unique_to_richer = []

        if count_a >= count_b + 3 and count_a >= 2 * max(count_b, 1):
            richer_id = link["source_entity_id"]
            sparser_id = link["target_entity_id"]
            richer_name = link["name1"]
            sparser_name = link["name2"]
            richer_project = link["project_name_1"]
            sparser_project = link["project_name_2"]
            richer_count = count_a
            sparser_count = count_b
            unique_to_richer = sorted(set(attrs_a.keys()) - set(attrs_b.keys()))
        elif count_b >= count_a + 3 and count_b >= 2 * max(count_a, 1):
            richer_id = link["target_entity_id"]
            sparser_id = link["source_entity_id"]
            richer_name = link["name2"]
            sparser_name = link["name1"]
            richer_project = link["project_name_2"]
            sparser_project = link["project_name_1"]
            richer_count = count_b
            sparser_count = count_a
            unique_to_richer = sorted(set(attrs_b.keys()) - set(attrs_a.keys()))

        if not richer_id:
            continue

        shown_attrs = unique_to_richer[:8]
        attr_str = ", ".join(shown_attrs)
        extra = f" and {len(unique_to_richer) - 8} more" if len(unique_to_richer) > 8 else ""

        insights.append({
            "insight_type": "coverage_gap",
            "title": (
                f"'{sparser_name}' has less data than its counterpart in "
                f"'{richer_project}'"
            ),
            "description": (
                f"'{richer_name}' in project '{richer_project}' has "
                f"{richer_count} attributes, while '{sparser_name}' in "
                f"'{sparser_project}' only has {sparser_count}. "
                f"Missing attributes: {attr_str}{extra}. "
                f"Consider syncing data from the richer entity."
            ),
            "project_ids": json.dumps(sorted({link["p1"], link["p2"]})),
            "entity_ids": json.dumps(sorted([richer_id, sparser_id])),
            "severity": "notable" if richer_count >= sparser_count + 5 else "info",
            "metadata_json": json.dumps({
                "richer_entity_id": richer_id,
                "sparser_entity_id": sparser_id,
                "richer_count": richer_count,
                "sparser_count": sparser_count,
                "missing_attrs": unique_to_richer,
            }),
        })

    return insights


# ═════════════════════════════════════════════════════════════
# 1. Scan for Overlaps
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/scan", methods=["POST"])
def scan_overlaps():
    """Scan all projects for overlapping entities.

    Uses name similarity (Dice coefficient, threshold 0.8) and URL domain
    matching to detect entities that appear in multiple projects. Creates
    auto-sourced entity_links for each detected overlap.

    Returns: {links: [...], found_count: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        new_links = _scan_for_overlaps(conn)

    logger.info("Overlap scan complete: %d new links detected", len(new_links))

    return jsonify({
        "links": new_links,
        "found_count": len(new_links),
    }), 201


# ═════════════════════════════════════════════════════════════
# 2. List Overlaps (Entity Links)
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/overlaps")
def list_overlaps():
    """List all detected entity links with optional filters.

    Query params:
        link_type (optional): Filter by type (same_entity|related|parent_child)
        source (optional): Filter by source (manual|auto|ai)
        limit (optional): Max results (default 50)
        offset (optional): Pagination offset (default 0)

    Returns: {links: [...], total: N, limit: N, offset: N}
    """
    link_type = request.args.get("link_type")
    source = request.args.get("source")
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    limit = max(1, min(limit, 200))

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = """
            SELECT el.*,
                   e1.name AS source_entity_name,
                   e2.name AS target_entity_name,
                   e1.project_id AS source_project_id,
                   e2.project_id AS target_project_id,
                   p1.name AS source_project_name,
                   p2.name AS target_project_name
            FROM entity_links el
            JOIN entities e1 ON e1.id = el.source_entity_id
            JOIN entities e2 ON e2.id = el.target_entity_id
            JOIN projects p1 ON p1.id = e1.project_id
            JOIN projects p2 ON p2.id = e2.project_id
            WHERE 1=1
        """
        params = []

        if link_type:
            query += " AND el.link_type = ?"
            params.append(link_type)
        if source:
            query += " AND el.source = ?"
            params.append(source)

        # Count
        count_query = (
            "SELECT COUNT(*) AS total FROM entity_links el "
            "JOIN entities e1 ON e1.id = el.source_entity_id "
            "JOIN entities e2 ON e2.id = el.target_entity_id "
            "WHERE 1=1"
        )
        count_params = []
        if link_type:
            count_query += " AND el.link_type = ?"
            count_params.append(link_type)
        if source:
            count_query += " AND el.source = ?"
            count_params.append(source)

        total = conn.execute(count_query, count_params).fetchone()["total"]

        query += " ORDER BY el.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

    links = []
    for row in rows:
        link = _row_to_link(row)
        link["source_entity_name"] = row["source_entity_name"]
        link["target_entity_name"] = row["target_entity_name"]
        link["source_project_id"] = row["source_project_id"]
        link["target_project_id"] = row["target_project_id"]
        link["source_project_name"] = row["source_project_name"]
        link["target_project_name"] = row["target_project_name"]
        links.append(link)

    return jsonify({
        "links": links,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


# ═════════════════════════════════════════════════════════════
# 3. Manually Link Two Entities
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/link", methods=["POST"])
def create_link():
    """Manually link two entities across projects.

    Body: {
        source_entity_id: int (required),
        target_entity_id: int (required),
        link_type: str (optional, default "same_entity"),
        confidence: float (optional, default 1.0)
    }

    Returns: {link: {...}, created: true}
    """
    data = request.get_json(silent=True) or {}

    source_id = data.get("source_entity_id")
    target_id = data.get("target_entity_id")

    if not source_id or not target_id:
        return jsonify({
            "error": "source_entity_id and target_entity_id are required",
        }), 400

    source_id = int(source_id)
    target_id = int(target_id)

    if source_id == target_id:
        return jsonify({"error": "Cannot link an entity to itself"}), 400

    link_type = data.get("link_type", "same_entity")
    if link_type not in _VALID_LINK_TYPES:
        return jsonify({
            "error": f"Invalid link_type. Must be one of: {', '.join(sorted(_VALID_LINK_TYPES))}",
        }), 400

    confidence = data.get("confidence", 1.0)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = 1.0

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Verify both entities exist
        e1 = conn.execute(
            "SELECT id, project_id FROM entities WHERE id = ? AND is_deleted = 0",
            (source_id,),
        ).fetchone()
        e2 = conn.execute(
            "SELECT id, project_id FROM entities WHERE id = ? AND is_deleted = 0",
            (target_id,),
        ).fetchone()

        if not e1:
            return jsonify({"error": f"Source entity {source_id} not found"}), 404
        if not e2:
            return jsonify({"error": f"Target entity {target_id} not found"}), 404

        # Check for existing link
        if _link_exists(conn, source_id, target_id):
            return jsonify({"error": "Link already exists between these entities"}), 409

        cursor = conn.execute(
            """INSERT INTO entity_links
               (source_entity_id, target_entity_id, link_type, confidence, source, metadata_json)
               VALUES (?, ?, ?, ?, 'manual', '{}')""",
            (source_id, target_id, link_type, confidence),
        )
        link_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM entity_links WHERE id = ?", (link_id,)
        ).fetchone()

    logger.info(
        "Created manual link #%d: entity %d <-> %d (%s)",
        link_id, source_id, target_id, link_type,
    )

    return jsonify({
        "link": _row_to_link(row),
        "created": True,
    }), 201


# ═════════════════════════════════════════════════════════════
# 4. Remove a Link
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/link/<int:link_id>", methods=["DELETE"])
def delete_link(link_id):
    """Remove an entity link.

    Returns: {deleted: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM entity_links WHERE id = ?", (link_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": f"Link {link_id} not found"}), 404

        conn.execute("DELETE FROM entity_links WHERE id = ?", (link_id,))

    logger.info("Deleted entity link #%d", link_id)
    return jsonify({"deleted": True, "id": link_id})


# ═════════════════════════════════════════════════════════════
# 5. Get Linked Entities
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/entity/<int:entity_id>/linked")
def get_linked_entities(entity_id):
    """Get all entities linked to a given entity, with project info and attribute summaries.

    Returns: {
        entity: {id, name, project_id, ...},
        linked: [{entity: {...}, project_name: str, attrs: {...}, link: {...}}, ...]
    }
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Fetch the source entity
        source = _get_entity_with_project(conn, entity_id)
        if not source:
            return jsonify({"error": f"Entity {entity_id} not found"}), 404

        # Find all links involving this entity (in either direction)
        link_rows = conn.execute(
            """SELECT * FROM entity_links
               WHERE source_entity_id = ? OR target_entity_id = ?""",
            (entity_id, entity_id),
        ).fetchall()

        linked = []
        for lr in link_rows:
            link = _row_to_link(lr)

            # Determine the "other" entity
            other_id = (
                lr["target_entity_id"]
                if lr["source_entity_id"] == entity_id
                else lr["source_entity_id"]
            )

            other = _get_entity_with_project(conn, other_id)
            if not other:
                continue

            attrs = _get_entity_attrs_summary(conn, other_id)

            linked.append({
                "entity": other,
                "project_name": other.get("project_name", ""),
                "attrs": attrs,
                "link": link,
            })

    return jsonify({
        "entity": source,
        "linked": linked,
    })


# ═════════════════════════════════════════════════════════════
# 6. Sync Attributes Between Linked Entities
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/sync", methods=["POST"])
def sync_attributes():
    """Sync specific attributes from one entity to its linked counterpart.

    Copies the latest attribute values from the source entity to the target.
    Only syncs attributes specified in the request body.

    Body: {
        source_entity_id: int (required),
        target_entity_id: int (required),
        attr_slugs: [str] (required, list of attribute slugs to sync)
    }

    Returns: {synced: [...], synced_count: N}
    """
    data = request.get_json(silent=True) or {}

    source_id = data.get("source_entity_id")
    target_id = data.get("target_entity_id")
    attr_slugs = data.get("attr_slugs", [])

    if not source_id or not target_id:
        return jsonify({
            "error": "source_entity_id and target_entity_id are required",
        }), 400

    source_id = int(source_id)
    target_id = int(target_id)

    if not attr_slugs or not isinstance(attr_slugs, list):
        return jsonify({"error": "attr_slugs must be a non-empty list"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Verify entities exist
        e1 = conn.execute(
            "SELECT id FROM entities WHERE id = ? AND is_deleted = 0",
            (source_id,),
        ).fetchone()
        e2 = conn.execute(
            "SELECT id FROM entities WHERE id = ? AND is_deleted = 0",
            (target_id,),
        ).fetchone()
        if not e1:
            return jsonify({"error": f"Source entity {source_id} not found"}), 404
        if not e2:
            return jsonify({"error": f"Target entity {target_id} not found"}), 404

        # Verify they are linked
        if not _link_exists(conn, source_id, target_id):
            return jsonify({
                "error": "These entities are not linked. Create a link first.",
            }), 400

        # Get source attributes
        source_attrs = _get_entity_attrs_summary(conn, source_id)

        synced = []
        now = _now_iso()

        for slug in attr_slugs:
            if slug not in source_attrs:
                continue

            value = source_attrs[slug]

            # Insert as a new attribute value on the target
            conn.execute(
                """INSERT INTO entity_attributes
                   (entity_id, attr_slug, value, source, confidence, captured_at)
                   VALUES (?, ?, ?, 'sync', 0.9, ?)""",
                (target_id, slug, value, now),
            )

            synced.append({
                "attr_slug": slug,
                "value": value,
                "source_entity_id": source_id,
                "target_entity_id": target_id,
            })

        # Update the target entity's updated_at
        if synced:
            conn.execute(
                "UPDATE entities SET updated_at = ? WHERE id = ?",
                (now, target_id),
            )

    logger.info(
        "Synced %d attributes from entity %d to entity %d",
        len(synced), source_id, target_id,
    )

    return jsonify({
        "synced": synced,
        "synced_count": len(synced),
    })


# ═════════════════════════════════════════════════════════════
# 7. Compare Attributes (Diff)
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/entity/<int:entity_id>/diff")
def diff_entities(entity_id):
    """Compare attributes between two linked entities.

    Query: ?compare_to=<other_entity_id>

    Returns: {
        entity_a: {id, name, project_id, ...},
        entity_b: {id, name, project_id, ...},
        diff: {
            only_in_a: [{attr_slug, value}, ...],
            only_in_b: [{attr_slug, value}, ...],
            different: [{attr_slug, value_a, value_b}, ...],
            same: [{attr_slug, value}, ...]
        },
        summary: {total_attrs: N, shared: N, divergent: N, only_a: N, only_b: N}
    }
    """
    compare_to = request.args.get("compare_to", type=int)
    if not compare_to:
        return jsonify({"error": "compare_to query parameter is required"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        entity_a = _get_entity_with_project(conn, entity_id)
        entity_b = _get_entity_with_project(conn, compare_to)

        if not entity_a:
            return jsonify({"error": f"Entity {entity_id} not found"}), 404
        if not entity_b:
            return jsonify({"error": f"Entity {compare_to} not found"}), 404

        attrs_a = _get_entity_attrs_summary(conn, entity_id)
        attrs_b = _get_entity_attrs_summary(conn, compare_to)

    slugs_a = set(attrs_a.keys())
    slugs_b = set(attrs_b.keys())
    all_slugs = slugs_a | slugs_b

    only_in_a = []
    only_in_b = []
    different = []
    same = []

    for slug in sorted(all_slugs):
        in_a = slug in attrs_a
        in_b = slug in attrs_b

        if in_a and not in_b:
            only_in_a.append({"attr_slug": slug, "value": attrs_a[slug]})
        elif in_b and not in_a:
            only_in_b.append({"attr_slug": slug, "value": attrs_b[slug]})
        else:
            val_a = (attrs_a[slug] or "").strip()
            val_b = (attrs_b[slug] or "").strip()
            if val_a.lower() == val_b.lower():
                same.append({"attr_slug": slug, "value": attrs_a[slug]})
            else:
                different.append({
                    "attr_slug": slug,
                    "value_a": attrs_a[slug],
                    "value_b": attrs_b[slug],
                })

    return jsonify({
        "entity_a": entity_a,
        "entity_b": entity_b,
        "diff": {
            "only_in_a": only_in_a,
            "only_in_b": only_in_b,
            "different": different,
            "same": same,
        },
        "summary": {
            "total_attrs": len(all_slugs),
            "shared": len(same),
            "divergent": len(different),
            "only_a": len(only_in_a),
            "only_b": len(only_in_b),
        },
    })


# ═════════════════════════════════════════════════════════════
# 8. Run Cross-Project Analysis
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/analyse", methods=["POST"])
def analyse_cross_project():
    """Run cross-project pattern analysis.

    Detects:
    - Entities appearing in multiple projects (overlap)
    - Attribute divergence (same entity, different values)
    - Coverage gaps (entity researched deeper in one project)

    Returns: {insights: [...], generated_count: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Check we have any links to analyse
        link_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM entity_links"
        ).fetchone()["cnt"]

        if link_count == 0:
            return jsonify({
                "insights": [],
                "generated_count": 0,
                "message": "No entity links found. Run a scan first.",
            })

        # Run all detectors
        all_insights = []

        detectors = [
            ("multi_project", _detect_multi_project_entities),
            ("divergence", _detect_attribute_divergence),
            ("coverage_gaps", _detect_coverage_gaps),
        ]

        for name, detector_fn in detectors:
            try:
                found = detector_fn(conn)
                all_insights.extend(found)
            except Exception as e:
                logger.warning(
                    "Cross-project detector '%s' failed: %s", name, e,
                )

        # Insert into DB
        inserted = []
        for insight in all_insights:
            cursor = conn.execute(
                """INSERT INTO cross_project_insights
                   (insight_type, title, description, project_ids,
                    entity_ids, metadata_json, severity)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    insight["insight_type"],
                    insight["title"],
                    insight["description"],
                    insight.get("project_ids", "[]"),
                    insight.get("entity_ids", "[]"),
                    insight.get("metadata_json", "{}"),
                    insight.get("severity", "info"),
                ),
            )
            insight_id = cursor.lastrowid

            row = conn.execute(
                "SELECT * FROM cross_project_insights WHERE id = ?",
                (insight_id,),
            ).fetchone()
            inserted.append(_row_to_insight(row))

    logger.info(
        "Cross-project analysis complete: %d insights generated", len(inserted),
    )

    return jsonify({
        "insights": inserted,
        "generated_count": len(inserted),
    }), 201


# ═════════════════════════════════════════════════════════════
# 9. List Cross-Project Insights
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/insights")
def list_insights():
    """List cross-project insights with optional filters.

    Query params:
        insight_type (optional): Filter by type (overlap|divergence|trend|coverage_gap)
        severity (optional): Filter by severity (info|notable|important|critical)
        is_dismissed (optional): "0" (default), "1", or "all"
        limit (optional): Max results (default 50)
        offset (optional): Pagination offset (default 0)

    Returns: {insights: [...], total: N, limit: N, offset: N}
    """
    insight_type = request.args.get("insight_type")
    severity = request.args.get("severity")
    is_dismissed = request.args.get("is_dismissed", "0", type=str)
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    limit = max(1, min(limit, 200))

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = "SELECT * FROM cross_project_insights WHERE 1=1"
        params = []

        if is_dismissed != "all":
            query += " AND is_dismissed = ?"
            params.append(int(is_dismissed) if is_dismissed.isdigit() else 0)

        if insight_type:
            query += " AND insight_type = ?"
            params.append(insight_type)
        if severity:
            query += " AND severity = ?"
            params.append(severity)

        # Count
        count_query = query.replace("SELECT *", "SELECT COUNT(*) AS total")
        total = conn.execute(count_query, params).fetchone()["total"]

        # Order by severity weight, then newest
        query += """
            ORDER BY
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
# 10. Dismiss a Cross-Project Insight
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route(
    "/api/cross-project/insights/<int:insight_id>/dismiss", methods=["PUT"],
)
def dismiss_insight(insight_id):
    """Dismiss a cross-project insight (hides from default listing).

    Returns: {updated: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM cross_project_insights WHERE id = ?",
            (insight_id,),
        ).fetchone()
        if not row:
            return jsonify({
                "error": f"Cross-project insight {insight_id} not found",
            }), 404

        conn.execute(
            "UPDATE cross_project_insights SET is_dismissed = 1 WHERE id = ?",
            (insight_id,),
        )

    return jsonify({"updated": True, "id": insight_id})


# ═════════════════════════════════════════════════════════════
# 11. Delete a Cross-Project Insight
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route(
    "/api/cross-project/insights/<int:insight_id>", methods=["DELETE"],
)
def delete_insight(insight_id):
    """Delete a cross-project insight permanently.

    Returns: {deleted: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM cross_project_insights WHERE id = ?",
            (insight_id,),
        ).fetchone()
        if not row:
            return jsonify({
                "error": f"Cross-project insight {insight_id} not found",
            }), 404

        conn.execute(
            "DELETE FROM cross_project_insights WHERE id = ?", (insight_id,),
        )

    logger.info("Deleted cross-project insight #%d", insight_id)
    return jsonify({"deleted": True, "id": insight_id})


# ═════════════════════════════════════════════════════════════
# 12. Summary Stats
# ═════════════════════════════════════════════════════════════

@crossproject_bp.route("/api/cross-project/stats")
def cross_project_stats():
    """Summary statistics for cross-project intelligence.

    Returns: {
        total_links: N,
        links_by_type: {same_entity: N, related: N, ...},
        links_by_source: {manual: N, auto: N, ai: N},
        overlapping_entities: N,
        projects_with_overlaps: N,
        total_insights: N,
        undismissed_insights: N,
        insights_by_type: {overlap: N, divergence: N, ...},
        insights_by_severity: {info: N, notable: N, ...}
    }
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # -- Link stats --
        total_links = conn.execute(
            "SELECT COUNT(*) AS cnt FROM entity_links"
        ).fetchone()["cnt"]

        links_by_type = {}
        for row in conn.execute(
            "SELECT link_type, COUNT(*) AS cnt FROM entity_links GROUP BY link_type"
        ).fetchall():
            links_by_type[row["link_type"]] = row["cnt"]

        links_by_source = {}
        for row in conn.execute(
            "SELECT source, COUNT(*) AS cnt FROM entity_links GROUP BY source"
        ).fetchall():
            links_by_source[row["source"]] = row["cnt"]

        # Count distinct entities that are part of any link
        overlapping_entities = conn.execute(
            """SELECT COUNT(DISTINCT eid) AS cnt FROM (
                   SELECT source_entity_id AS eid FROM entity_links
                   UNION
                   SELECT target_entity_id AS eid FROM entity_links
               )"""
        ).fetchone()["cnt"]

        # Count distinct projects that have at least one linked entity
        projects_with_overlaps = conn.execute(
            """SELECT COUNT(DISTINCT e.project_id) AS cnt
               FROM entities e
               WHERE e.id IN (
                   SELECT source_entity_id FROM entity_links
                   UNION
                   SELECT target_entity_id FROM entity_links
               )"""
        ).fetchone()["cnt"]

        # -- Insight stats --
        total_insights = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cross_project_insights"
        ).fetchone()["cnt"]

        undismissed_insights = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cross_project_insights WHERE is_dismissed = 0"
        ).fetchone()["cnt"]

        insights_by_type = {}
        for row in conn.execute(
            """SELECT insight_type, COUNT(*) AS cnt
               FROM cross_project_insights
               WHERE is_dismissed = 0
               GROUP BY insight_type"""
        ).fetchall():
            insights_by_type[row["insight_type"]] = row["cnt"]

        insights_by_severity = {}
        for row in conn.execute(
            """SELECT severity, COUNT(*) AS cnt
               FROM cross_project_insights
               WHERE is_dismissed = 0
               GROUP BY severity"""
        ).fetchall():
            insights_by_severity[row["severity"]] = row["cnt"]

    return jsonify({
        "total_links": total_links,
        "links_by_type": links_by_type,
        "links_by_source": links_by_source,
        "overlapping_entities": overlapping_entities,
        "projects_with_overlaps": projects_with_overlaps,
        "total_insights": total_insights,
        "undismissed_insights": undismissed_insights,
        "insights_by_type": insights_by_type,
        "insights_by_severity": insights_by_severity,
    })
