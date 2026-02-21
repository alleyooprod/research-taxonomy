"""Product page extractor — specialized extraction from marketing/product pages.

Extracts: company description, value proposition, target audience,
key features, integrations, industries served.
"""
import json
import logging
import time

logger = logging.getLogger(__name__)


PRODUCT_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "company_name": {"type": "string", "description": "Company or product name"},
        "tagline": {"type": "string", "description": "Main tagline or value proposition"},
        "description": {"type": "string", "description": "What the company/product does (1-2 sentences)"},
        "target_audience": {"type": "string", "description": "Who is the target customer"},
        "key_features": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of key features or capabilities mentioned",
        },
        "industries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Industries or verticals served",
        },
        "integrations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Third-party integrations or platforms mentioned",
        },
        "social_proof": {
            "type": "object",
            "properties": {
                "customer_count": {"type": "string"},
                "notable_customers": {"type": "array", "items": {"type": "string"}},
                "awards_certifications": {"type": "array", "items": {"type": "string"}},
            },
        },
        "cta_text": {"type": "string", "description": "Primary call-to-action text"},
        "confidence": {
            "type": "number", "minimum": 0, "maximum": 1,
            "description": "Overall confidence that this is a product/marketing page",
        },
    },
    "required": ["description", "confidence"],
}

# Pre-serialized schema to avoid re-serializing on every extract() call
_PRODUCT_PAGE_SCHEMA_JSON = json.dumps(PRODUCT_PAGE_SCHEMA)


def build_prompt(content, entity_name=None):
    """Build extraction prompt for a product/marketing page."""
    entity_context = f' for "{entity_name}"' if entity_name else ""
    return f"""You are a market research analyst extracting structured data from a product or marketing web page{entity_context}.

Analyse the following web page content and extract:
1. Company/product name and tagline
2. What the product does (concise description)
3. Target audience / customer profile
4. Key features and capabilities
5. Industries or verticals served
6. Third-party integrations mentioned
7. Social proof (customer count, notable customers, awards)
8. Primary call-to-action

Only extract what is explicitly stated or strongly implied. Do not fabricate information.
Set confidence to indicate how clearly this is a product/marketing page (1.0 = definitely, 0.5 = unclear, 0.0 = not a product page).

CONTENT:
---
{content}
---"""


def extract(content, entity_name=None, model=None, timeout=120):
    """Extract product page data from content.

    Args:
        content: HTML/text content
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
            json_schema=_PRODUCT_PAGE_SCHEMA_JSON,
            operation="extraction_product",
        )
    except Exception as e:
        logger.error("Product page extraction failed: %s", e)
        return None

    elapsed = int((time.time() - start) * 1000)

    if response.get("is_error"):
        logger.warning("Product page extraction error: %s", response.get("result"))
        return None

    result = response.get("structured_output")
    if not result:
        try:
            from json_repair import loads as repair_loads
            result = repair_loads(response.get("result", "{}"))
        except Exception:
            return None

    result["_meta"] = {
        "extractor": "product_page",
        "model": model,
        "cost_usd": response.get("cost_usd", 0),
        "duration_ms": elapsed,
    }
    return result


def classify(content):
    """Heuristic check: does this content look like a product/marketing page?

    Returns confidence score 0.0-1.0.
    """
    content_lower = content.lower()
    signals = [
        "get started" in content_lower,
        "sign up" in content_lower,
        "free trial" in content_lower,
        "request demo" in content_lower,
        "pricing" in content_lower,
        "features" in content_lower,
        "how it works" in content_lower,
        "our platform" in content_lower,
        "trusted by" in content_lower,
        "customers" in content_lower,
        "integrations" in content_lower,
        "solutions" in content_lower,
    ]
    score = sum(signals) / len(signals)
    return min(1.0, score * 2)  # Scale up: 6+ signals = 1.0
