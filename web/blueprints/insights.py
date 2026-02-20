"""Insights & Hypothesis Tracking API — the "So What?" engine.

Combines two complementary systems:

1. **Insight Engine** — rule-based and AI-enhanced pattern detection
   across project data. Scans entity attributes for gaps, outliers,
   clusters, stale data, duplicates, and sparse coverage. Optionally
   enhanced by LLM analysis for deeper cross-entity observations.

2. **Hypothesis Tracker** — user-stated beliefs about the market,
   linked to weighted evidence that supports or contradicts each
   hypothesis. Confidence is computed from directional evidence weights.

Endpoints:

    Insights (rule-based + AI):
        POST /api/insights/generate           — Run rule-based insight engine
        POST /api/insights/generate-ai        — AI-enhanced insight generation
        GET  /api/insights                    — List insights (with filters)
        GET  /api/insights/<id>               — Get single insight
        PUT  /api/insights/<id>/dismiss       — Dismiss an insight
        PUT  /api/insights/<id>/pin           — Toggle pin on an insight
        DELETE /api/insights/<id>             — Delete an insight
        GET  /api/insights/summary            — Dashboard summary stats

    Hypotheses:
        POST /api/insights/hypotheses                  — Create hypothesis
        GET  /api/insights/hypotheses                  — List hypotheses
        GET  /api/insights/hypotheses/<id>             — Get hypothesis + evidence
        PUT  /api/insights/hypotheses/<id>             — Update hypothesis
        DELETE /api/insights/hypotheses/<id>           — Delete hypothesis
        POST /api/insights/hypotheses/<id>/evidence    — Add evidence
        DELETE /api/insights/hypotheses/<hid>/evidence/<eid> — Remove evidence
        GET  /api/insights/hypotheses/<id>/score       — Compute confidence score
"""
import json
import math
import re
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, current_app
from loguru import logger

insights_bp = Blueprint("insights", __name__)

# ── Constants ────────────────────────────────────────────────

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


# ═════════════════════════════════════════════════════════════
# Rule-Based Insight Detectors
# ═════════════════════════════════════════════════════════════

def _get_active_entities(conn, project_id):
    """Fetch non-deleted entities for a project. Returns list of dicts."""
    rows = conn.execute(
        """SELECT id, name, type_slug, slug, status, is_starred,
                  source, created_at, updated_at
           FROM entities
           WHERE project_id = ? AND is_deleted = 0
           ORDER BY name COLLATE NOCASE""",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_latest_attributes(conn, entity_ids):
    """Fetch the latest attribute value per (entity_id, attr_slug).

    Returns: dict of {entity_id: {attr_slug: value}}
    """
    if not entity_ids:
        return {}

    placeholders = ",".join("?" * len(entity_ids))
    rows = conn.execute(
        f"""SELECT ea.entity_id, ea.attr_slug, ea.value
            FROM entity_attributes ea
            WHERE ea.entity_id IN ({placeholders})
              AND ea.id IN (
                  SELECT MAX(id) FROM entity_attributes
                  WHERE entity_id IN ({placeholders})
                  GROUP BY entity_id, attr_slug
              )""",
        list(entity_ids) + list(entity_ids),
    ).fetchall()

    result = {}
    for r in rows:
        result.setdefault(r["entity_id"], {})[r["attr_slug"]] = r["value"]
    return result


def _detect_feature_gaps(conn, project_id):
    """Find attributes where >50% of entities have values but some don't.

    These represent data collection gaps: attributes that are clearly relevant
    (most entities have them) but are missing for specific entities.

    Returns: list of insight dicts ready to INSERT.
    """
    entities = _get_active_entities(conn, project_id)
    if len(entities) < 2:
        return []

    eids = [e["id"] for e in entities]
    eid_to_name = {e["id"]: e["name"] for e in entities}
    attrs = _get_latest_attributes(conn, eids)
    total = len(eids)

    # Count coverage per attr_slug
    slug_counts = {}
    slug_missing = {}
    for eid in eids:
        entity_attrs = attrs.get(eid, {})
        for slug in entity_attrs:
            slug_counts[slug] = slug_counts.get(slug, 0) + 1

    # Find slugs above threshold
    insights = []
    for slug, count in slug_counts.items():
        coverage = count / total
        if coverage >= _FEATURE_GAP_THRESHOLD and count < total:
            # Find which entities are missing this attribute
            missing_entities = []
            for eid in eids:
                if slug not in attrs.get(eid, {}):
                    missing_entities.append(eid)

            missing_names = [eid_to_name[eid] for eid in missing_entities]
            evidence_refs = [
                {"entity_id": eid, "attr_slug": slug, "value": None}
                for eid in missing_entities
            ]

            pct = round(coverage * 100)
            insights.append({
                "project_id": project_id,
                "insight_type": "gap",
                "title": f"Missing '{slug}' for {len(missing_entities)} entit{'y' if len(missing_entities) == 1 else 'ies'}",
                "description": (
                    f"The attribute '{slug}' is present on {pct}% of entities "
                    f"({count}/{total}), but missing for: {', '.join(missing_names)}. "
                    f"Consider collecting this data to complete the picture."
                ),
                "evidence_refs": json.dumps(evidence_refs),
                "severity": "notable" if coverage >= 0.75 else "info",
                "category": "features",
                "confidence": round(coverage, 2),
                "source": "rule",
            })

    return insights


def _detect_pricing_outliers(conn, project_id):
    """Find entities with pricing attributes >2 standard deviations from mean.

    Scans all numeric-looking attributes with pricing-related slugs (price,
    cost, fee, subscription, etc.) and flags statistical outliers.

    Returns: list of insight dicts ready to INSERT.
    """
    pricing_keywords = {"price", "cost", "fee", "subscription", "plan", "tier", "pricing"}

    entities = _get_active_entities(conn, project_id)
    if len(entities) < 3:
        return []

    eids = [e["id"] for e in entities]
    eid_to_name = {e["id"]: e["name"] for e in entities}
    attrs = _get_latest_attributes(conn, eids)

    # Collect all pricing-related slugs with numeric values
    pricing_data = {}  # slug -> [(entity_id, numeric_value)]
    for eid in eids:
        for slug, value in attrs.get(eid, {}).items():
            slug_lower = slug.lower()
            if not any(kw in slug_lower for kw in pricing_keywords):
                continue
            # Try to parse as a number (strip currency symbols, commas)
            numeric = _parse_numeric(value)
            if numeric is not None:
                pricing_data.setdefault(slug, []).append((eid, numeric))

    insights = []
    for slug, values in pricing_data.items():
        if len(values) < 3:
            continue

        nums = [v for _, v in values]
        mean = sum(nums) / len(nums)
        variance = sum((x - mean) ** 2 for x in nums) / len(nums)
        stdev = math.sqrt(variance) if variance > 0 else 0

        if stdev == 0:
            continue

        for eid, val in values:
            z_score = abs(val - mean) / stdev
            if z_score >= _PRICING_OUTLIER_STDEVS:
                direction = "above" if val > mean else "below"
                name = eid_to_name[eid]
                evidence_refs = [
                    {"entity_id": eid, "attr_slug": slug, "value": str(val)}
                ]

                insights.append({
                    "project_id": project_id,
                    "insight_type": "outlier",
                    "title": f"Pricing outlier: {name} ({slug})",
                    "description": (
                        f"{name} has {slug} = {val}, which is {z_score:.1f} standard "
                        f"deviations {direction} the mean of {mean:.2f} "
                        f"(stdev: {stdev:.2f}, n={len(values)}). "
                        f"This could indicate a premium/budget positioning "
                        f"or a data entry error."
                    ),
                    "evidence_refs": json.dumps(evidence_refs),
                    "severity": "important" if z_score >= 3 else "notable",
                    "category": "pricing",
                    "confidence": round(min(z_score / 5.0, 1.0), 2),
                    "source": "rule",
                })

    return insights


def _detect_sparse_coverage(conn, project_id):
    """Find attributes with <25% coverage across entities.

    These are attributes defined in very few entities, suggesting either
    niche data points or incomplete research.

    Returns: list of insight dicts ready to INSERT.
    """
    entities = _get_active_entities(conn, project_id)
    if len(entities) < 4:
        return []

    eids = [e["id"] for e in entities]
    attrs = _get_latest_attributes(conn, eids)
    total = len(eids)

    # Count coverage per slug
    slug_counts = {}
    for eid in eids:
        for slug in attrs.get(eid, {}):
            slug_counts[slug] = slug_counts.get(slug, 0) + 1

    insights = []
    sparse_slugs = []
    for slug, count in sorted(slug_counts.items()):
        coverage = count / total
        if coverage < _SPARSE_COVERAGE_THRESHOLD:
            sparse_slugs.append((slug, count, coverage))

    if not sparse_slugs:
        return []

    # Group into a single insight if many, or individual if few
    if len(sparse_slugs) > 5:
        slug_list = ", ".join(f"'{s}' ({c}/{total})" for s, c, _ in sparse_slugs[:10])
        remaining = len(sparse_slugs) - 10
        suffix = f" and {remaining} more" if remaining > 0 else ""
        insights.append({
            "project_id": project_id,
            "insight_type": "gap",
            "title": f"{len(sparse_slugs)} attributes have very sparse coverage",
            "description": (
                f"The following attributes are present on fewer than {int(_SPARSE_COVERAGE_THRESHOLD * 100)}% "
                f"of entities: {slug_list}{suffix}. "
                f"Consider whether these attributes are worth tracking broadly "
                f"or are only relevant to specific entity types."
            ),
            "evidence_refs": json.dumps([]),
            "severity": "info",
            "category": "features",
            "confidence": 0.7,
            "source": "rule",
        })
    else:
        for slug, count, coverage in sparse_slugs:
            pct = round(coverage * 100)
            # Find which entities have this attribute
            entities_with = [
                {"entity_id": eid, "attr_slug": slug, "value": attrs[eid][slug]}
                for eid in eids if slug in attrs.get(eid, {})
            ]

            insights.append({
                "project_id": project_id,
                "insight_type": "gap",
                "title": f"Sparse attribute: '{slug}' ({pct}% coverage)",
                "description": (
                    f"The attribute '{slug}' is only present on {count}/{total} entities "
                    f"({pct}% coverage). It may be worth investigating whether "
                    f"this data point applies to more entities in the project."
                ),
                "evidence_refs": json.dumps(entities_with),
                "severity": "info",
                "category": "features",
                "confidence": 0.6,
                "source": "rule",
            })

    return insights


def _detect_stale_entities(conn, project_id):
    """Find entities not updated in >30 days.

    Stale entities may have outdated information that needs refreshing.

    Returns: list of insight dicts ready to INSERT.
    """
    entities = _get_active_entities(conn, project_id)
    if not entities:
        return []

    stale_entities = []
    for e in entities:
        updated_at = e.get("updated_at") or e.get("created_at")
        if not updated_at:
            stale_entities.append((e, None))
            continue

        try:
            # Parse ISO datetime — handle both formats
            dt_str = updated_at.replace("Z", "+00:00")
            if "T" in dt_str:
                updated_dt = datetime.fromisoformat(dt_str)
            else:
                updated_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                updated_dt = updated_dt.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            days_old = (now - updated_dt).days
            if days_old >= _STALE_DAYS:
                stale_entities.append((e, days_old))
        except (ValueError, TypeError):
            stale_entities.append((e, None))

    if not stale_entities:
        return []

    insights = []

    if len(stale_entities) > 10:
        # Batch into a single insight
        names = [e["name"] for e, _ in stale_entities[:15]]
        remaining = len(stale_entities) - 15
        suffix = f" and {remaining} more" if remaining > 0 else ""
        evidence_refs = [
            {"entity_id": e["id"], "attr_slug": "_updated_at", "value": str(days)}
            for e, days in stale_entities
        ]

        insights.append({
            "project_id": project_id,
            "insight_type": "trend",
            "title": f"{len(stale_entities)} entities haven't been updated in 30+ days",
            "description": (
                f"The following entities may have stale data: "
                f"{', '.join(names)}{suffix}. "
                f"Consider re-checking these entities to ensure their "
                f"attributes and evidence are current."
            ),
            "evidence_refs": json.dumps(evidence_refs),
            "severity": "notable",
            "category": "competitive",
            "confidence": 0.8,
            "source": "rule",
        })
    else:
        for e, days in stale_entities:
            days_str = f"{days} days" if days is not None else "unknown duration"
            evidence_refs = [
                {"entity_id": e["id"], "attr_slug": "_updated_at", "value": str(days)}
            ]

            insights.append({
                "project_id": project_id,
                "insight_type": "trend",
                "title": f"Stale entity: {e['name']} (not updated in {days_str})",
                "description": (
                    f"{e['name']} has not been updated for {days_str}. "
                    f"Its data may be outdated. Consider re-checking its website, "
                    f"app store listing, or other sources for changes."
                ),
                "evidence_refs": json.dumps(evidence_refs),
                "severity": "info",
                "category": "competitive",
                "confidence": 0.6,
                "source": "rule",
            })

    return insights


def _detect_feature_clusters(conn, project_id):
    """Find groups of entities with overlapping feature sets.

    Uses Jaccard similarity on the set of attr_slugs that each entity has.
    Groups entities with >60% overlap into clusters.

    Returns: list of insight dicts ready to INSERT.
    """
    entities = _get_active_entities(conn, project_id)
    if len(entities) < 3:
        return []

    eids = [e["id"] for e in entities]
    eid_to_name = {e["id"]: e["name"] for e in entities}
    attrs = _get_latest_attributes(conn, eids)

    # Build feature sets per entity
    feature_sets = {}
    for eid in eids:
        slugs = set(attrs.get(eid, {}).keys())
        if slugs:
            feature_sets[eid] = slugs

    if len(feature_sets) < 3:
        return []

    # Simple clustering: find pairs with high Jaccard similarity
    entity_list = list(feature_sets.keys())
    clusters = []  # list of sets of entity_ids
    assigned = set()

    for i in range(len(entity_list)):
        if entity_list[i] in assigned:
            continue
        cluster = {entity_list[i]}
        for j in range(i + 1, len(entity_list)):
            if entity_list[j] in assigned:
                continue
            set_a = feature_sets[entity_list[i]]
            set_b = feature_sets[entity_list[j]]
            intersection = len(set_a & set_b)
            union = len(set_a | set_b)
            jaccard = intersection / union if union > 0 else 0

            if jaccard >= _CLUSTER_MIN_OVERLAP:
                cluster.add(entity_list[j])

        if len(cluster) >= 2:
            clusters.append(cluster)
            assigned.update(cluster)

    insights = []
    for idx, cluster in enumerate(clusters):
        names = sorted(eid_to_name[eid] for eid in cluster)
        # Find common attributes in this cluster
        common_attrs = None
        for eid in cluster:
            if common_attrs is None:
                common_attrs = set(feature_sets[eid])
            else:
                common_attrs &= feature_sets[eid]

        common_list = sorted(common_attrs) if common_attrs else []
        evidence_refs = [
            {"entity_id": eid, "attr_slug": "_cluster", "value": str(idx)}
            for eid in cluster
        ]

        insights.append({
            "project_id": project_id,
            "insight_type": "pattern",
            "title": f"Feature cluster: {', '.join(names[:4])}" + (f" +{len(names) - 4}" if len(names) > 4 else ""),
            "description": (
                f"{len(names)} entities share a similar feature profile: "
                f"{', '.join(names)}. "
                f"They have {len(common_list)} attributes in common"
                + (f": {', '.join(common_list[:8])}" if common_list else "")
                + (f" and {len(common_list) - 8} more" if len(common_list) > 8 else "")
                + ". This may indicate a market segment or product category."
            ),
            "evidence_refs": json.dumps(evidence_refs),
            "severity": "info",
            "category": "competitive",
            "confidence": 0.65,
            "source": "rule",
        })

    return insights


def _detect_duplicates(conn, project_id):
    """Find entities with very similar names.

    Uses a simplified string similarity check (normalised common bigrams).
    Flags potential duplicates that may need merging or disambiguation.

    Returns: list of insight dicts ready to INSERT.
    """
    entities = _get_active_entities(conn, project_id)
    if len(entities) < 2:
        return []

    # Normalise names
    def normalise(name):
        """Lowercase, strip non-alpha, collapse whitespace."""
        return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\s]', '', name.lower())).strip()

    def bigrams(s):
        """Return set of character bigrams."""
        if len(s) < 2:
            return {s}
        return {s[i:i+2] for i in range(len(s) - 1)}

    def similarity(a, b):
        """Dice coefficient on bigrams."""
        ba, bb = bigrams(a), bigrams(b)
        if not ba or not bb:
            return 0.0
        return 2.0 * len(ba & bb) / (len(ba) + len(bb))

    normalised = [(e, normalise(e["name"])) for e in entities]
    seen_pairs = set()
    insights = []

    for i in range(len(normalised)):
        for j in range(i + 1, len(normalised)):
            e_a, norm_a = normalised[i]
            e_b, norm_b = normalised[j]

            # Skip if either name is very short (high false positive rate)
            if len(norm_a) < 3 or len(norm_b) < 3:
                continue

            pair_key = (min(e_a["id"], e_b["id"]), max(e_a["id"], e_b["id"]))
            if pair_key in seen_pairs:
                continue

            sim = similarity(norm_a, norm_b)
            if sim >= _DUPLICATE_SIMILARITY:
                seen_pairs.add(pair_key)
                evidence_refs = [
                    {"entity_id": e_a["id"], "attr_slug": "_name", "value": e_a["name"]},
                    {"entity_id": e_b["id"], "attr_slug": "_name", "value": e_b["name"]},
                ]

                pct = round(sim * 100)
                insights.append({
                    "project_id": project_id,
                    "insight_type": "pattern",
                    "title": f"Possible duplicate: '{e_a['name']}' and '{e_b['name']}'",
                    "description": (
                        f"These two entities have {pct}% name similarity and may "
                        f"represent the same product or company. Consider merging "
                        f"them or adding disambiguating information."
                    ),
                    "evidence_refs": json.dumps(evidence_refs),
                    "severity": "notable" if sim >= 0.9 else "info",
                    "category": "competitive",
                    "confidence": round(sim, 2),
                    "source": "rule",
                })

    return insights


def _detect_attribute_coverage(conn, project_id):
    """Generate a high-level attribute coverage summary as an insight.

    Reports overall data completeness across all entities and attributes.

    Returns: list of insight dicts (usually 0 or 1).
    """
    entities = _get_active_entities(conn, project_id)
    if len(entities) < 2:
        return []

    eids = [e["id"] for e in entities]
    attrs = _get_latest_attributes(conn, eids)
    total = len(eids)

    # Collect all known slugs
    all_slugs = set()
    for eid in eids:
        all_slugs.update(attrs.get(eid, {}).keys())

    if not all_slugs:
        return []

    # Coverage matrix
    total_cells = total * len(all_slugs)
    filled_cells = sum(len(attrs.get(eid, {})) for eid in eids)
    overall_pct = round(filled_cells / total_cells * 100, 1) if total_cells > 0 else 0

    # Find best and worst covered attributes
    slug_coverage = []
    for slug in all_slugs:
        count = sum(1 for eid in eids if slug in attrs.get(eid, {}))
        slug_coverage.append((slug, count, round(count / total * 100)))

    slug_coverage.sort(key=lambda x: x[1])
    worst = slug_coverage[:3]
    best = slug_coverage[-3:]

    worst_str = ", ".join(f"'{s}' ({p}%)" for s, _, p in worst)
    best_str = ", ".join(f"'{s}' ({p}%)" for s, _, p in best)

    severity = "info"
    if overall_pct < 30:
        severity = "important"
    elif overall_pct < 50:
        severity = "notable"

    return [{
        "project_id": project_id,
        "insight_type": "trend",
        "title": f"Overall data coverage: {overall_pct}%",
        "description": (
            f"Across {total} entities and {len(all_slugs)} attributes, "
            f"{filled_cells}/{total_cells} data points are filled ({overall_pct}%). "
            f"Best covered: {best_str}. "
            f"Least covered: {worst_str}."
        ),
        "evidence_refs": json.dumps([]),
        "severity": severity,
        "category": "features",
        "confidence": 0.9,
        "source": "rule",
    }]


def _parse_numeric(value):
    """Try to parse a value as a float. Strips currency symbols and commas.

    Returns: float or None
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    # Strip currency symbols, commas, whitespace
    cleaned = re.sub(r'[£$€¥,\s]', '', value.strip())
    # Handle ranges like "10-20" by taking the first number
    if '-' in cleaned and not cleaned.startswith('-'):
        cleaned = cleaned.split('-')[0]
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


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
{json.dumps(entity_summaries, indent=2, default=str)}

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

Return a JSON array of insight objects. Return ONLY the JSON array.
Aim for 3-8 high-quality insights. Do not repeat obvious observations."""

    try:
        from core.llm import run_cli
        llm_result = run_cli(prompt, model=model, timeout=90)
    except Exception as e:
        logger.error("LLM call failed for AI insights: %s", e)
        return jsonify({"error": f"AI generation failed: {str(e)}"}), 500

    # Parse LLM response
    raw_text = llm_result.get("result", "")
    structured = llm_result.get("structured_output")
    cost_usd = llm_result.get("cost_usd", 0)
    duration_ms = llm_result.get("duration_ms", 0)

    raw_insights = []

    if structured and isinstance(structured, list):
        raw_insights = structured
    else:
        # Parse from text
        try:
            text = raw_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            parsed = json.loads(text)
            if isinstance(parsed, list):
                raw_insights = parsed
            elif isinstance(parsed, dict) and "insights" in parsed:
                raw_insights = parsed["insights"]
        except (json.JSONDecodeError, TypeError):
            logger.warning("Could not parse AI insight response as JSON")
            # Create a single insight from raw text
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
