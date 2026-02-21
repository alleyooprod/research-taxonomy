"""Funding round extractor — specialized extraction from funding announcements.

Extracts: company name, round type, amount raised, valuation,
lead investors, other investors, date announced, use of funds,
previous funding, summary.
"""
import json
import logging
import re
import time

logger = logging.getLogger(__name__)


# Keywords used for classification
KEYWORDS = {
    "series a", "series b", "series c", "series d", "series e",
    "seed round", "pre-seed", "funding round", "funding",
    "raised", "raises", "million", "billion", "valuation",
    "led by", "participated", "investors", "venture capital",
    "investment", "capital raise", "growth equity",
}

# URL path patterns that indicate funding pages
URL_PATTERNS = [
    r"/funding",
    r"/investment",
    r"/raise",
    r"crunchbase\.com",
    r"techcrunch\.com",
    r"/press-release",
    r"/press/",
    r"/news/.*fund",
]

# Money amount patterns ($10M, $1.5 billion, etc.)
MONEY_PATTERN = re.compile(
    r"(?:\$|USD\s*)\s*\d+(?:\.\d+)?\s*(?:million|billion|m|b|mn|bn|M|B)",
    re.IGNORECASE,
)


FUNDING_ROUND_SCHEMA = {
    "type": "object",
    "properties": {
        "company_name": {
            "type": "string",
            "description": "Company that raised funding",
        },
        "round_type": {
            "type": "string",
            "description": "Type of funding round",
            "enum": [
                "pre_seed", "seed", "series_a", "series_b", "series_c",
                "series_d_plus", "growth", "bridge", "debt", "undisclosed",
            ],
        },
        "amount": {
            "type": "string",
            "description": "Amount raised as stated (e.g. '$10M', '$1.5 billion')",
        },
        "amount_usd": {
            "type": "integer",
            "description": "Normalised USD amount as integer (e.g. 10000000 for $10M)",
        },
        "valuation": {
            "type": "string",
            "description": "Post-money valuation if mentioned (e.g. '$500M')",
        },
        "lead_investors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Lead investors in the round",
        },
        "other_investors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Other participating investors",
        },
        "date_announced": {
            "type": "string",
            "description": "Announcement date (ISO format YYYY-MM-DD if possible)",
        },
        "use_of_funds": {
            "type": "string",
            "description": "Stated use of proceeds / what the funding will be used for",
        },
        "previous_funding": {
            "type": "string",
            "description": "Any mention of previous rounds or total raised to date",
        },
        "summary": {
            "type": "string",
            "description": "2-3 sentence summary of the funding announcement",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence that this is a funding announcement",
        },
    },
    "required": ["confidence"],
}

# Pre-serialized schema to avoid re-serializing on every extract() call
_FUNDING_ROUND_SCHEMA_JSON = json.dumps(FUNDING_ROUND_SCHEMA)

# Mapping from schema property names to typical entity attribute slugs
ATTRIBUTE_SLUG_MAP = {
    "company_name": "company_name",
    "round_type": "round_type",
    "amount": "amount",
    "amount_usd": "amount_usd",
    "valuation": "valuation",
    "lead_investors": "lead_investors",
    "other_investors": "other_investors",
    "date_announced": "date_announced",
    "use_of_funds": "use_of_funds",
    "previous_funding": "previous_funding",
    "summary": "summary",
}


def classify(content, url=None):
    """Heuristic check: does this content look like a funding announcement?

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

    # Money amount signals — multiple dollar amounts strongly indicate funding
    money_matches = MONEY_PATTERN.findall(content)
    has_money_amounts = len(money_matches) >= 1

    signals = [
        "series a" in content_lower or "series b" in content_lower or "series c" in content_lower,
        "seed round" in content_lower or "pre-seed" in content_lower,
        "funding round" in content_lower or "funding" in content_lower,
        "raised" in content_lower or "raises" in content_lower,
        "million" in content_lower or "billion" in content_lower,
        "led by" in content_lower,
        "investors" in content_lower or "venture capital" in content_lower,
        "valuation" in content_lower,
        has_money_amounts,
        keyword_hits >= 5,
    ]
    score = sum(signals) / len(signals)

    # URL pattern bonus
    url_bonus = 0.0
    if url:
        url_lower = url.lower()
        for pattern in URL_PATTERNS:
            if re.search(pattern, url_lower):
                url_bonus = 0.2
                break

    return min(1.0, score * 2.0 + url_bonus)


def build_prompt(content, entity_name=None):
    """Build extraction prompt for a funding announcement."""
    entity_context = f' for "{entity_name}"' if entity_name else ""
    return f"""You are a market research analyst extracting structured data from a funding announcement or investment news article{entity_context}.

Analyse the following content and extract:
1. The company that raised funding
2. The type of funding round (pre_seed, seed, series_a, series_b, series_c, series_d_plus, growth, bridge, debt, or undisclosed)
3. The amount raised — both as stated (e.g. "$10M") and normalised to integer USD (e.g. 10000000)
4. Post-money valuation if mentioned
5. Lead investors (firms or individuals who led the round)
6. Other participating investors
7. Date the funding was announced (ISO format YYYY-MM-DD if possible)
8. Stated use of funds / what the capital will be used for
9. Any mention of previous funding rounds or total raised to date
10. A brief 2-3 sentence summary of the funding announcement

Only extract what is explicitly stated or strongly implied. Do not fabricate information.
For round_type, use one of: pre_seed, seed, series_a, series_b, series_c, series_d_plus, growth, bridge, debt, undisclosed.
Set confidence to indicate how clearly this is a funding announcement (1.0 = definitely, 0.5 = unclear, 0.0 = not a funding announcement).

CONTENT:
---
{content}
---"""


def extract(content, entity_name=None, model=None, timeout=120):
    """Extract funding round data from content.

    Args:
        content: HTML/text content from a funding announcement
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
            json_schema=_FUNDING_ROUND_SCHEMA_JSON,
            operation="extraction_funding",
        )
    except Exception as e:
        logger.error("Funding round extraction failed: %s", e)
        return None

    elapsed = int((time.time() - start) * 1000)

    if response.get("is_error"):
        logger.warning("Funding round extraction error: %s", response.get("result"))
        return None

    result = response.get("structured_output")
    if not result:
        try:
            from json_repair import loads as repair_loads
            result = repair_loads(response.get("result", "{}"))
        except Exception:
            return None

    # Convert list fields to comma-separated strings for attribute storage
    for list_field in ("lead_investors", "other_investors"):
        if isinstance(result.get(list_field), list):
            result[list_field] = ", ".join(str(item) for item in result[list_field])

    result["_meta"] = {
        "extractor": "funding_round",
        "model": model,
        "cost_usd": response.get("cost_usd", 0),
        "duration_ms": elapsed,
    }
    return result


def extract_for_schema(content, entity_name, schema_attributes, url=None,
                       model=None, timeout=120):
    """Extract funding round data filtered to match entity schema attributes.

    This is the schema-aware entry point that only returns attributes whose
    slugs are present in schema_attributes.

    Args:
        content: HTML/text content from a funding announcement
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
