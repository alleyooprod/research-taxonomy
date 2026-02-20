"""IPID extractor — specialized extraction from Insurance Product Information Documents.

IPIDs are standardised EU/UK insurance documents mandated by the Insurance
Distribution Directive (IDD).  They follow a consistent structure with sections
covering what is insured, exclusions, restrictions, geographic coverage,
obligations, payment terms, policy period, and cancellation.

Extracts: insurer name, product name, insurance type, covered items,
exclusions, restrictions, geographic coverage, obligations, payment terms,
policy period, cancellation terms, excess, premium indication, regulatory info.
"""
import json
import logging
import re
import time

logger = logging.getLogger(__name__)


# Standard IPID section headings (lowercase for matching)
SECTION_HEADINGS = [
    "what is this type of insurance",
    "what is insured",
    "what is not insured",
    "are there any restrictions on cover",
    "where am i covered",
    "what are my obligations",
    "when and how do i pay",
    "when does the cover start and end",
    "how do i cancel the contract",
]

# Keywords used for classification
KEYWORDS = {
    "insurance product information document", "ipid",
    "what is insured", "what is not insured",
    "are there any restrictions", "where am i covered",
    "what are my obligations", "when and how do i pay",
    "how do i cancel", "insurance distribution directive",
    "policyholder", "insurer", "underwritten by",
    "general insurance", "non-investment insurance",
}

# URL path patterns that indicate IPID documents
URL_PATTERNS = [
    r"/ipid/",
    r"/ipid-",
    r"_ipid",
    r"\.ipid\.",
    r"/product-information/",
]

# IPID symbols commonly used in these documents
IPID_SYMBOLS = {"✓", "✗", "⚠"}


IPID_SCHEMA = {
    "type": "object",
    "properties": {
        "insurer_name": {
            "type": "string",
            "description": "Name of the insurance company / underwriter",
        },
        "product_name": {
            "type": "string",
            "description": "Name of the insurance product",
        },
        "insurance_type": {
            "type": "string",
            "description": "Type of insurance (e.g. travel, home, motor, pet, health, life, business)",
        },
        "what_is_insured": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of covered risks / items",
        },
        "what_is_not_insured": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of exclusions / items not covered",
        },
        "restrictions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of restrictions or limitations on cover",
        },
        "geographic_coverage": {
            "type": "string",
            "description": "Where the cover applies geographically",
        },
        "obligations": {
            "type": "string",
            "description": "Policyholder obligations",
        },
        "payment_terms": {
            "type": "string",
            "description": "When and how to pay for the insurance",
        },
        "policy_period": {
            "type": "string",
            "description": "When cover starts and ends",
        },
        "cancellation_terms": {
            "type": "string",
            "description": "How to cancel the insurance contract",
        },
        "excess_amount": {
            "type": "string",
            "description": "Excess / deductible amount if mentioned",
        },
        "premium_indication": {
            "type": "string",
            "description": "Premium or price indication if mentioned",
        },
        "regulatory_info": {
            "type": "string",
            "description": "Regulatory references (FCA, PRA, BaFin, etc.)",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence that this is an IPID document (1.0 = definitely, 0.0 = not)",
        },
    },
    "required": ["confidence"],
}

# Mapping from schema property names to typical entity attribute slugs
ATTRIBUTE_SLUG_MAP = {
    "insurer_name": "insurer_name",
    "product_name": "product_name",
    "insurance_type": "insurance_type",
    "what_is_insured": "what_is_insured",
    "what_is_not_insured": "what_is_not_insured",
    "restrictions": "restrictions",
    "geographic_coverage": "geographic_coverage",
    "obligations": "obligations",
    "payment_terms": "payment_terms",
    "policy_period": "policy_period",
    "cancellation_terms": "cancellation_terms",
    "excess_amount": "excess_amount",
    "premium_indication": "premium_indication",
    "regulatory_info": "regulatory_info",
}


def classify(content, url=None):
    """Heuristic check: does this content look like an IPID document?

    Scoring is based on the number of standard IPID section headings found
    in the content, plus URL pattern bonuses.

    Args:
        content: Text/HTML content to classify
        url: Optional URL for path-based signals

    Returns:
        Confidence score 0.0-1.0.
    """
    if not content:
        return 0.0

    content_lower = content.lower()

    # Count how many standard section headings are present
    section_hits = 0
    for heading in SECTION_HEADINGS:
        if heading in content_lower:
            section_hits += 1

    # Primary score: section heading count / total sections * 1.5
    total_sections = len(SECTION_HEADINGS)
    score = min(1.0, (section_hits / total_sections) * 1.5)

    # Keyword bonus for additional IPID-specific terms
    keyword_hits = 0
    for keyword in KEYWORDS:
        if keyword in content_lower:
            keyword_hits += 1

    # If very few section headings but strong keyword presence, boost slightly
    if section_hits < 3 and keyword_hits >= 4:
        score = max(score, 0.3)

    # IPID symbol bonus (checkmarks, crosses, warnings)
    symbol_count = sum(1 for s in IPID_SYMBOLS if s in content)
    if symbol_count >= 2:
        score = min(1.0, score + 0.1)

    # URL pattern bonus
    url_bonus = 0.0
    if url:
        url_lower = url.lower()
        for pattern in URL_PATTERNS:
            if re.search(pattern, url_lower):
                url_bonus = 0.15
                break

    return min(1.0, score + url_bonus)


def build_prompt(content, entity_name=None):
    """Build extraction prompt for an IPID document."""
    entity_context = f' for "{entity_name}"' if entity_name else ""
    return f"""You are an insurance analyst extracting structured data from an Insurance Product Information Document (IPID){entity_context}.

IPIDs are standardised documents required under the EU/UK Insurance Distribution Directive (IDD).
They follow a consistent format with specific sections.

Analyse the following IPID content and extract:
1. The insurer / underwriter name
2. The insurance product name
3. The type of insurance (e.g. travel, home, motor, pet, health, life, business, liability, cyber, etc.)
4. What is insured — list each covered item/risk as a separate entry
5. What is not insured — list each exclusion as a separate entry
6. Restrictions on cover — list each restriction/limitation as a separate entry
7. Geographic coverage — where the cover applies
8. Policyholder obligations
9. Payment terms (when and how to pay)
10. Policy period (when cover starts and ends)
11. Cancellation terms (how to cancel the contract)
12. Excess / deductible amount if mentioned
13. Premium or price indication if mentioned
14. Regulatory information (FCA, PRA, BaFin, or other regulatory references)

Only extract what is explicitly stated or strongly implied. Do not fabricate information.
For list fields (what_is_insured, what_is_not_insured, restrictions), return each item as a separate array element.
Set confidence to indicate how clearly this is an IPID document (1.0 = definitely, 0.5 = unclear, 0.0 = not an IPID).

CONTENT:
---
{content}
---"""


def extract(content, entity_name=None, model=None, timeout=120):
    """Extract IPID data from content.

    Args:
        content: HTML/text content from an IPID document
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
            json_schema=json.dumps(IPID_SCHEMA),
        )
    except Exception as e:
        logger.error("IPID extraction failed: %s", e)
        return None

    elapsed = int((time.time() - start) * 1000)

    if response.get("is_error"):
        logger.warning("IPID extraction error: %s", response.get("result"))
        return None

    result = response.get("structured_output")
    if not result:
        try:
            from json_repair import loads as repair_loads
            result = repair_loads(response.get("result", "{}"))
        except Exception:
            return None

    # Convert list fields to semicolon-separated strings for attribute storage
    for list_field in ("what_is_insured", "what_is_not_insured", "restrictions"):
        if isinstance(result.get(list_field), list):
            result[list_field] = "; ".join(str(item) for item in result[list_field])

    result["_meta"] = {
        "extractor": "ipid",
        "model": model,
        "cost_usd": response.get("cost_usd", 0),
        "duration_ms": elapsed,
    }
    return result


def extract_for_schema(content, entity_name, schema_attributes, url=None,
                       model=None, timeout=120):
    """Extract IPID data filtered to match entity schema attributes.

    This is the schema-aware entry point that only returns attributes whose
    slugs are present in schema_attributes.

    Args:
        content: HTML/text content from an IPID document
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
