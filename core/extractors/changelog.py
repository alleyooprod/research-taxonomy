"""Changelog/release notes extractor — specialized extraction from changelog pages.

Extracts: latest version, release date, release frequency, recent features,
improvements, breaking changes, product maturity assessment.
"""
import json
import logging
import re
import time

logger = logging.getLogger(__name__)


# Keywords used for classification
KEYWORDS = {
    "changelog", "release notes", "what's new", "updates", "version",
    "release", "patch", "update log", "product updates", "feature updates",
    "new features", "improvements", "bug fixes", "breaking changes",
}

# URL path patterns that indicate changelog pages
URL_PATTERNS = [
    r"/changelog",
    r"/releases",
    r"/whats-new",
    r"/what-s-new",
    r"/updates",
    r"/release-notes",
    r"/release_notes",
]

# Version string patterns (v1.0, v2.3.1, 1.0.0, etc.)
VERSION_PATTERN = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?\b", re.IGNORECASE)


CHANGELOG_SCHEMA = {
    "type": "object",
    "properties": {
        "latest_version": {
            "type": "string",
            "description": "Most recent version string mentioned (e.g. v2.5.0, 3.1.0)",
        },
        "latest_release_date": {
            "type": "string",
            "description": "Date of the most recent release (ISO format YYYY-MM-DD if possible)",
        },
        "release_frequency": {
            "type": "string",
            "description": "Estimated release cadence: weekly, bi-weekly, monthly, quarterly, or irregular",
        },
        "recent_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Notable new features from recent releases",
        },
        "recent_improvements": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Recent improvements, enhancements, or optimisations",
        },
        "breaking_changes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Any breaking changes mentioned in recent releases",
        },
        "product_maturity": {
            "type": "string",
            "description": "Assessment of product maturity based on changelog patterns: early-stage, growing, mature, or enterprise",
        },
        "total_releases_visible": {
            "type": "integer",
            "description": "Approximate number of releases visible on the page",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence that this is a changelog/release notes page",
        },
    },
    "required": ["confidence"],
}

# Mapping from schema property names to typical entity attribute slugs
ATTRIBUTE_SLUG_MAP = {
    "latest_version": "latest_version",
    "latest_release_date": "latest_release_date",
    "release_frequency": "release_frequency",
    "recent_features": "recent_features",
    "recent_improvements": "recent_improvements",
    "breaking_changes": "breaking_changes",
    "product_maturity": "product_maturity",
}


def classify(content, url=None):
    """Heuristic check: does this content look like a changelog/release notes page?

    Args:
        content: Text/HTML content to classify
        url: Optional URL for path-based signals

    Returns:
        Confidence score 0.0-1.0.
    """
    if not content:
        return 0.0

    content_lower = content.lower()

    # Keyword signals
    keyword_hits = 0
    for keyword in KEYWORDS:
        if keyword in content_lower:
            keyword_hits += 1

    # Version string signals — multiple version strings strongly indicate a changelog
    version_matches = VERSION_PATTERN.findall(content)
    has_many_versions = len(version_matches) >= 3

    signals = [
        "changelog" in content_lower,
        "release notes" in content_lower,
        "what's new" in content_lower or "whats new" in content_lower,
        "bug fixes" in content_lower or "bugfixes" in content_lower,
        "breaking changes" in content_lower or "breaking change" in content_lower,
        "new features" in content_lower or "new feature" in content_lower,
        "improvements" in content_lower,
        "patch" in content_lower and "version" in content_lower,
        has_many_versions,
        keyword_hits >= 4,
    ]
    score = sum(signals) / len(signals)

    # URL pattern bonus
    url_bonus = 0.0
    if url:
        url_lower = url.lower()
        for pattern in URL_PATTERNS:
            if re.search(pattern, url_lower):
                url_bonus = 0.25
                break

    return min(1.0, score * 2.0 + url_bonus)


def build_prompt(content, entity_name=None):
    """Build extraction prompt for a changelog/release notes page."""
    entity_context = f' for "{entity_name}"' if entity_name else ""
    return f"""You are a market research analyst extracting structured data from a changelog or release notes page{entity_context}.

Analyse the following web page content and extract:
1. The most recent version string (e.g. v2.5.0, 3.1.0)
2. The date of the most recent release (in ISO format YYYY-MM-DD if possible)
3. Estimated release frequency/cadence (weekly, bi-weekly, monthly, quarterly, or irregular) based on the dates visible
4. Notable new features from recent releases (list the most important ones)
5. Recent improvements, enhancements, or optimisations
6. Any breaking changes mentioned
7. Product maturity assessment based on changelog patterns:
   - "early-stage": few releases, rapid changes, breaking changes common, alpha/beta labels
   - "growing": regular releases, mostly new features, occasional breaking changes
   - "mature": stable release cadence, mostly improvements and bug fixes, rare breaking changes
   - "enterprise": long-term support mentions, migration guides, deprecation notices, semantic versioning
8. Approximate number of releases visible on the page

Only extract what is explicitly stated or strongly implied. Do not fabricate information.
Set confidence to indicate how clearly this is a changelog/release notes page (1.0 = definitely, 0.5 = unclear, 0.0 = not a changelog page).
For recent_features and recent_improvements, return comma-separated descriptions.

CONTENT:
---
{content}
---"""


def extract(content, entity_name=None, model=None, timeout=120):
    """Extract changelog data from content.

    Args:
        content: HTML/text content from a changelog page
        entity_name: Optional entity name for context
        model: LLM model override
        timeout: LLM timeout in seconds

    Returns:
        dict with extracted data, or None on failure
    """
    from core.llm import run_cli
    from core.extraction import DEFAULT_EXTRACTION_MODEL

    model = model or DEFAULT_EXTRACTION_MODEL
    prompt = build_prompt(content, entity_name)
    start = time.time()

    try:
        response = run_cli(
            prompt=prompt,
            model=model,
            timeout=timeout,
            json_schema=json.dumps(CHANGELOG_SCHEMA),
        )
    except Exception as e:
        logger.error("Changelog extraction failed: %s", e)
        return None

    elapsed = int((time.time() - start) * 1000)

    if response.get("is_error"):
        logger.warning("Changelog extraction error: %s", response.get("result"))
        return None

    result = response.get("structured_output")
    if not result:
        try:
            from json_repair import loads as repair_loads
            result = repair_loads(response.get("result", "{}"))
        except Exception:
            return None

    # Convert list fields to comma-separated strings for attribute storage
    for list_field in ("recent_features", "recent_improvements", "breaking_changes"):
        if isinstance(result.get(list_field), list):
            result[list_field] = ", ".join(str(item) for item in result[list_field])

    result["_meta"] = {
        "extractor": "changelog",
        "model": model,
        "cost_usd": response.get("cost_usd", 0),
        "duration_ms": elapsed,
    }
    return result


def extract_for_schema(content, entity_name, schema_attributes, url=None,
                       model=None, timeout=120):
    """Extract changelog data filtered to match entity schema attributes.

    This is the schema-aware entry point that only returns attributes whose
    slugs are present in schema_attributes.

    Args:
        content: HTML/text content from a changelog page
        entity_name: Entity name for context
        schema_attributes: List of attribute slug strings the schema expects
        url: Optional URL (unused in extraction, for consistency)
        model: LLM model override
        timeout: LLM timeout in seconds

    Returns:
        dict mapping attribute slugs to plain string values, or None on failure
    """
    result = extract(content, entity_name, model, timeout)
    if not result:
        return None

    # Filter to only schema-requested attributes
    schema_set = set(schema_attributes) if schema_attributes else set()
    filtered = {}

    for schema_key, slug in ATTRIBUTE_SLUG_MAP.items():
        if slug in schema_set and schema_key in result:
            value = result[schema_key]
            if value is not None and value != "":
                # Ensure plain string output
                filtered[slug] = str(value)

    if not filtered:
        return None

    filtered["_meta"] = result.get("_meta", {})
    return filtered
