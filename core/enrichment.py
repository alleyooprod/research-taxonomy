"""Waterfall company enrichment: multi-step pipeline to fill missing fields.

Uses Instructor + Pydantic on Step 1 (extract from existing text) when
the SDK path is available.  Steps 2 and 3 require web tools so they
always use the CLI path.
"""
import json
import logging
import re as _re
import time

from core.llm import run_cli, instructor_available, run_instructor

logger = logging.getLogger(__name__)

# Optional: Pydantic model for structured validation
try:
    from core.models import EnrichmentResult, PYDANTIC_AVAILABLE
except ImportError:
    EnrichmentResult = None
    PYDANTIC_AVAILABLE = False


def _clean_for_prompt(text, max_len=3000):
    """Strip control chars and limit length for prompt safety."""
    if not text:
        return text or ""
    text = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(text))
    return text[:max_len]


# Fields that can be enriched
ENRICHABLE_FIELDS = [
    "what", "target", "products", "funding", "geography", "tam",
    "employee_range", "founded_year", "funding_stage", "total_funding_usd",
    "hq_city", "hq_country", "linkedin_url", "business_model",
    "company_stage", "primary_focus", "tags",
]


def identify_missing_fields(company):
    """Return list of fields that are empty or None."""
    missing = []
    for f in ENRICHABLE_FIELDS:
        val = company.get(f)
        if val is None or val == "" or val == []:
            missing.append(f)
    return missing


def _extract_fields_from_dict(result, remaining, enriched):
    """Extract valid field values from a result dict into enriched, updating remaining."""
    if isinstance(result, dict):
        for k, v in result.items():
            if k in remaining and v is not None and v != "" and v != []:
                enriched[k] = v
                remaining.remove(k)


def _parse_json_from_response(resp):
    """Extract a dict from an LLM response, trying structured_output first."""
    result = resp.get("structured_output") or resp.get("result", "")
    if isinstance(result, str):
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(result[start:end])
    return result


def run_enrichment(company, fields_to_fill=None, model="sonnet"):
    """Run 3-step waterfall enrichment for a single company.

    Steps:
        1. Extract from existing raw_research (Instructor if SDK available)
        2. Web search for missing data (CLI only)
        3. Targeted follow-up for remaining gaps (CLI only)

    Returns dict of enriched field values.
    """
    name = company.get("name", "Unknown")
    url = company.get("url", "")
    fields_to_fill = fields_to_fill or identify_missing_fields(company)

    if not fields_to_fill:
        return {"enriched_fields": {}, "steps_run": 0}

    enriched = {}
    remaining = list(fields_to_fill)

    # Sanitize inputs for prompt safety
    name = _clean_for_prompt(name, 200)
    url = _clean_for_prompt(url, 500)

    # Step 1: Extract from existing research text
    raw = company.get("raw_research", "")
    if raw and remaining:
        raw = _clean_for_prompt(raw[:3000], 3000)
        prompt = f"""Extract the following fields from this company research text.
Company: {name} ({url})

Research text:
{raw}

Fields to extract: {', '.join(remaining)}

Return JSON only with field names as keys. Use null for fields you cannot determine.
For 'tags', return a JSON array of strings. For numeric fields, return numbers.
"""
        # Try Instructor path (SDK, no web tools needed for extraction)
        if instructor_available() and EnrichmentResult is not None:
            try:
                result_model, meta = run_instructor(
                    prompt, model,
                    response_model=EnrichmentResult,
                    timeout=60,
                    max_retries=2,
                )
                result_dict = result_model.model_dump(exclude_none=True)
                _extract_fields_from_dict(result_dict, remaining, enriched)
                logger.info("Instructor enrichment step 1: extracted %d fields in %dms",
                            len(enriched), meta.get("duration_ms", 0))
            except Exception as e:
                logger.debug("Instructor enrichment step 1 failed: %s", e)
                # Fall through to CLI path below
                try:
                    resp = run_cli(prompt, model, timeout=60)
                    result = _parse_json_from_response(resp)
                    _extract_fields_from_dict(result, remaining, enriched)
                except Exception:
                    pass
        else:
            try:
                resp = run_cli(prompt, model, timeout=60)
                result = _parse_json_from_response(resp)
                _extract_fields_from_dict(result, remaining, enriched)
            except Exception:
                pass

    if not remaining:
        return {"enriched_fields": enriched, "steps_run": 1}

    # Step 2: Web search for missing data (CLI only — needs web tools)
    prompt = f"""Research the company "{name}" ({url}) and find the following information:
{', '.join(remaining)}

Search the web for this company's website, Crunchbase profile, LinkedIn page, and news articles.
Return JSON only with field names as keys. Use null for fields you cannot find.
For 'tags', return a JSON array of relevant industry tags.
For numeric fields like total_funding_usd and founded_year, return numbers.
"""
    try:
        resp = run_cli(prompt, model, timeout=120, tools="WebSearch,WebFetch")
        result = _parse_json_from_response(resp)
        _extract_fields_from_dict(result, remaining, enriched)
    except Exception:
        pass

    if not remaining:
        return {"enriched_fields": enriched, "steps_run": 2}

    # Step 3: Targeted follow-up for stubborn gaps (CLI only — needs web tools)
    prompt = f"""I need specific information about "{name}" ({url}).
Please search harder for these specific fields: {', '.join(remaining)}

Try searching for:
- "{name} funding crunchbase" for funding data
- "{name} linkedin" for employee and location data
- "{name} founded" for founding year
- The company website for product and business model details

Return JSON only with field names as keys. Use null if truly unavailable.
"""
    try:
        resp = run_cli(prompt, model, timeout=120, tools="WebSearch,WebFetch")
        result = _parse_json_from_response(resp)
        _extract_fields_from_dict(result, remaining, enriched)
    except Exception:
        pass

    return {"enriched_fields": enriched, "steps_run": 3}
