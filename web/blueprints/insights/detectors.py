"""Rule-based insight detectors — feature gaps, pricing outliers, clusters, etc."""
import json
import math
import re
from datetime import datetime, timezone, timedelta

from flask import current_app
from loguru import logger

from ._shared import (
    _parse_json_field,
    _FEATURE_GAP_THRESHOLD, _SPARSE_COVERAGE_THRESHOLD,
    _PRICING_OUTLIER_STDEVS, _STALE_DAYS,
    _DUPLICATE_SIMILARITY, _CLUSTER_MIN_OVERLAP,
)

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


