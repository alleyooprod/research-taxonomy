"""Pricing page extractor — specialized extraction from pricing/plan pages.

Extracts: plan names, pricing tiers, feature lists per plan,
billing periods, free tier availability, enterprise options.
"""
import json
import logging
import time

logger = logging.getLogger(__name__)


PRICING_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "has_pricing": {
            "type": "boolean",
            "description": "Whether pricing information was found",
        },
        "pricing_model": {
            "type": "string",
            "description": "Overall pricing model (freemium, subscription, pay-per-use, enterprise-only, usage-based)",
        },
        "currency": {"type": "string", "description": "Currency code if found (USD, GBP, EUR, etc.)"},
        "billing_periods": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Available billing periods (monthly, annual, etc.)",
        },
        "plans": {
            "type": "array",
            "description": "Pricing plans/tiers found",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Plan name (e.g. Basic, Pro, Enterprise)"},
                    "price_monthly": {"type": "string", "description": "Monthly price as string"},
                    "price_annual": {"type": "string", "description": "Annual price as string"},
                    "price_note": {"type": "string", "description": "Pricing note (e.g. per user, per seat, custom)"},
                    "is_free": {"type": "boolean"},
                    "is_enterprise": {"type": "boolean", "description": "Contact sales / custom pricing"},
                    "features": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Features included in this plan",
                    },
                    "limits": {
                        "type": "object",
                        "description": "Usage limits (e.g. users, storage, API calls)",
                    },
                },
                "required": ["name"],
            },
        },
        "has_free_tier": {"type": "boolean", "description": "Whether a free plan exists"},
        "has_free_trial": {"type": "boolean", "description": "Whether a free trial is offered"},
        "trial_duration": {"type": "string", "description": "Free trial duration if mentioned"},
        "confidence": {
            "type": "number", "minimum": 0, "maximum": 1,
            "description": "Confidence that this is a pricing page",
        },
    },
    "required": ["has_pricing", "confidence"],
}

# Pre-serialized schema to avoid re-serializing on every extract() call
_PRICING_PAGE_SCHEMA_JSON = json.dumps(PRICING_PAGE_SCHEMA)


def build_prompt(content, entity_name=None):
    """Build extraction prompt for a pricing page."""
    entity_context = f' for "{entity_name}"' if entity_name else ""
    return f"""You are a market research analyst extracting pricing data from a web page{entity_context}.

Analyse the following web page content and extract all pricing information:
1. Overall pricing model (freemium, subscription, usage-based, etc.)
2. All pricing plans/tiers with their names, prices, and features
3. Whether there's a free tier or free trial
4. Billing periods available
5. Any usage limits per plan
6. Currency used

Be precise about prices — extract exact amounts. If pricing says "Contact us" or "Custom", mark as enterprise.
Only extract what is explicitly stated. Set confidence to indicate how clearly this is a pricing page.

CONTENT:
---
{content}
---"""


def extract(content, entity_name=None, model=None, timeout=120):
    """Extract pricing data from content.

    Args:
        content: HTML/text content from a pricing page
        entity_name: Optional entity name for context
        model: LLM model override
        timeout: LLM timeout

    Returns:
        dict with extracted pricing data, or None on failure
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
            json_schema=_PRICING_PAGE_SCHEMA_JSON,
            operation="extraction_pricing",
        )
    except Exception as e:
        logger.error("Pricing extraction failed: %s", e)
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
        "extractor": "pricing_page",
        "model": model,
        "cost_usd": response.get("cost_usd", 0),
        "duration_ms": elapsed,
    }
    return result


def classify(content):
    """Heuristic check: does this content look like a pricing page?

    Returns confidence score 0.0-1.0.
    """
    content_lower = content.lower()
    signals = [
        "pricing" in content_lower,
        "/month" in content_lower or "/mo" in content_lower,
        "/year" in content_lower or "/yr" in content_lower,
        "free plan" in content_lower or "free tier" in content_lower,
        "enterprise" in content_lower,
        "per user" in content_lower or "per seat" in content_lower,
        "basic" in content_lower and "pro" in content_lower,
        "start free" in content_lower or "free trial" in content_lower,
        "$" in content or "£" in content or "€" in content,
        "billed annually" in content_lower or "billed monthly" in content_lower,
    ]
    score = sum(signals) / len(signals)
    return min(1.0, score * 2.5)  # Scale up: 4+ signals = 1.0
