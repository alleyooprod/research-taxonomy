"""Press release extractor — specialized extraction from press releases and news announcements.

Extracts: headline, publication date, announcement type, key entities mentioned,
summary, notable quotes, media contact info, business implications.
"""
import json
import logging
import re
import time

logger = logging.getLogger(__name__)


# Keywords used for classification
KEYWORDS = {
    "press release", "media contact", "for immediate release",
    "media inquiries", "about the company", "about us",
    "announces", "announced today", "partnership", "acquisition",
    "launch", "launched", "newsroom", "press room",
    "investor relations", "forward-looking statements",
    "public relations", "media relations",
}

# URL path patterns that indicate press release pages
URL_PATTERNS = [
    r"/press/",
    r"/press-release",
    r"/press_release",
    r"/news/",
    r"/newsroom",
    r"/media/",
    r"/media-center",
    r"/media-centre",
    r"/announcements?/",
]


PRESS_RELEASE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "Press release headline or title",
        },
        "date_published": {
            "type": "string",
            "description": "Publication date (ISO format YYYY-MM-DD if possible)",
        },
        "announcement_type": {
            "type": "string",
            "enum": [
                "product_launch", "partnership", "acquisition", "funding",
                "hiring", "expansion", "award", "other",
            ],
            "description": "Type of announcement",
        },
        "key_entities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Companies, products, or people mentioned",
        },
        "summary": {
            "type": "string",
            "description": "2-3 sentence summary of the press release",
        },
        "quotes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string", "description": "Name and title of the speaker"},
                    "quote": {"type": "string", "description": "The quote text"},
                },
                "required": ["speaker", "quote"],
            },
            "description": "Notable quotes from executives or spokespeople",
        },
        "contact_info": {
            "type": "string",
            "description": "Media contact information if present",
        },
        "implications": {
            "type": "string",
            "description": "Business implications or significance of the announcement",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence that this is a press release (1.0 = definitely, 0.0 = not)",
        },
    },
    "required": ["summary", "confidence"],
}

# Mapping from schema property names to typical entity attribute slugs
ATTRIBUTE_SLUG_MAP = {
    "headline": "headline",
    "date_published": "date_published",
    "announcement_type": "announcement_type",
    "key_entities": "key_entities",
    "summary": "summary",
    "quotes": "quotes",
    "contact_info": "contact_info",
    "implications": "implications",
}


def classify(content, url=None):
    """Heuristic check: does this content look like a press release?

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

    signals = [
        "press release" in content_lower,
        "for immediate release" in content_lower,
        "media contact" in content_lower or "media inquiries" in content_lower,
        "announces" in content_lower or "announced today" in content_lower,
        "partnership" in content_lower or "acquisition" in content_lower,
        "about the company" in content_lower or "about us" in content_lower,
        "forward-looking statements" in content_lower,
        "investor relations" in content_lower,
        "launch" in content_lower and ("today" in content_lower or "new" in content_lower),
        keyword_hits >= 4,
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
    """Build extraction prompt for a press release."""
    entity_context = f' for "{entity_name}"' if entity_name else ""
    return f"""You are a market research analyst extracting structured data from a press release or news announcement{entity_context}.

Analyse the following content and extract:
1. The headline or title of the press release
2. The publication date (in ISO format YYYY-MM-DD if possible)
3. The type of announcement: product_launch, partnership, acquisition, funding, hiring, expansion, award, or other
4. Key entities mentioned (companies, products, people)
5. A 2-3 sentence summary of the announcement
6. Notable quotes from executives or spokespeople (with speaker name and title)
7. Media contact information if present
8. Business implications or significance of the announcement

Only extract what is explicitly stated or strongly implied. Do not fabricate information.
Set confidence to indicate how clearly this is a press release (1.0 = definitely, 0.5 = unclear, 0.0 = not a press release).
For key_entities, return the names of all companies, products, and notable people mentioned.

CONTENT:
---
{content}
---"""


def extract(content, entity_name=None, model=None, timeout=120):
    """Extract press release data from content.

    Args:
        content: HTML/text content from a press release
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
            json_schema=json.dumps(PRESS_RELEASE_SCHEMA),
        )
    except Exception as e:
        logger.error("Press release extraction failed: %s", e)
        return None

    elapsed = int((time.time() - start) * 1000)

    if response.get("is_error"):
        logger.warning("Press release extraction error: %s", response.get("result"))
        return None

    result = response.get("structured_output")
    if not result:
        try:
            from json_repair import loads as repair_loads
            result = repair_loads(response.get("result", "{}"))
        except Exception:
            return None

    # Convert list fields to comma-separated strings for attribute storage
    if isinstance(result.get("key_entities"), list):
        result["key_entities"] = ", ".join(str(item) for item in result["key_entities"])

    # Convert quotes list to readable string for attribute storage
    if isinstance(result.get("quotes"), list):
        formatted_quotes = []
        for q in result["quotes"]:
            if isinstance(q, dict):
                speaker = q.get("speaker", "Unknown")
                quote = q.get("quote", "")
                formatted_quotes.append(f'{speaker}: "{quote}"')
            else:
                formatted_quotes.append(str(q))
        result["quotes"] = "; ".join(formatted_quotes)

    result["_meta"] = {
        "extractor": "press_release",
        "model": model,
        "cost_usd": response.get("cost_usd", 0),
        "duration_ms": elapsed,
    }
    return result


def extract_for_schema(content, entity_name, schema_attributes, url=None,
                       model=None, timeout=120):
    """Extract press release data filtered to match entity schema attributes.

    This is the schema-aware entry point that only returns attributes whose
    slugs are present in schema_attributes.

    Args:
        content: HTML/text content from a press release
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
