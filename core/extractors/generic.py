"""Generic content extractor — fallback for unclassified documents.

Extracts whatever structured information is available from any text content.
Used when no specialized extractor matches with high confidence.
"""
import json
import logging
import time

logger = logging.getLogger(__name__)


GENERIC_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "description": "Best guess at document type (marketing, pricing, help, blog, news, legal, other)",
        },
        "title": {"type": "string", "description": "Page/document title"},
        "summary": {"type": "string", "description": "Brief summary of the content (2-3 sentences)"},
        "key_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string"},
                    "category": {"type": "string", "description": "Category: company, product, pricing, feature, market, other"},
                },
                "required": ["fact", "category"],
            },
            "description": "Key facts extracted from the content",
        },
        "entities_mentioned": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Company/product/person names mentioned",
        },
        "dates_mentioned": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Dates or time references found",
        },
        "urls_mentioned": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URLs found in the content",
        },
    },
    "required": ["document_type", "summary", "key_facts"],
}

# Pre-serialized schema to avoid re-serializing on every extract() call
_GENERIC_SCHEMA_JSON = json.dumps(GENERIC_SCHEMA)


def build_prompt(content, entity_name=None):
    """Build extraction prompt for generic content."""
    entity_context = f' related to "{entity_name}"' if entity_name else ""
    return f"""You are a research analyst extracting structured information from a document{entity_context}.

Analyse the following content and extract:
1. What type of document this is (marketing, pricing, help/docs, blog, news, legal, other)
2. A brief summary (2-3 sentences)
3. Key facts — categorised as: company, product, pricing, feature, market, or other
4. Entity names mentioned (companies, products, people)
5. Any dates or time references
6. Any URLs found

Be concise and factual. Only extract what is explicitly stated.

CONTENT:
---
{content}
---"""


def extract(content, entity_name=None, model=None, timeout=120):
    """Extract generic structured data from content.

    Args:
        content: Any text content
        entity_name: Optional entity name for context
        model: LLM model override
        timeout: LLM timeout

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
            json_schema=_GENERIC_SCHEMA_JSON,
            operation="extraction_generic",
        )
    except Exception as e:
        logger.error("Generic extraction failed: %s", e)
        return None

    elapsed = int((time.time() - start) * 1000)

    if response.get("is_error"):
        return None

    result = response.get("structured_output")
    if not result:
        try:
            from json_repair import loads as repair_loads
            result = repair_loads(response.get("result", "{}"))
        except Exception:
            return None

    result["_meta"] = {
        "extractor": "generic",
        "model": model,
        "cost_usd": response.get("cost_usd", 0),
        "duration_ms": elapsed,
    }
    return result
