"""Extraction engine — AI-powered structured data extraction from evidence.

Phase 3 of the Research Workbench: turn captured evidence into structured
entity attributes using LLM analysis.

Supports:
    - HTML/text content extraction (from page archives, documents)
    - URL-based extraction (fetch + extract in one step)
    - Schema-aware extraction (attributes matched to entity type definition)
    - Confidence scoring per extracted value
    - Contradiction detection across multiple sources
"""
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger(__name__)

# Maximum content length sent to LLM (characters)
MAX_CONTENT_LENGTH = 80_000


# ── HTML Stripping ────────────────────────────────────────────

def _strip_html(raw_content: str) -> str:
    """Strip HTML tags, scripts, styles and extract visible text to reduce token usage."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_content, "html.parser")
        # Remove script and style elements
        for element in soup(["script", "style", "noscript", "svg", "path", "meta", "link"]):
            element.decompose()
        # Remove nav, footer, header if they contain mostly links
        for tag in soup.find_all(["nav", "footer"]):
            tag.decompose()
        # Get text with some structure preserved
        text = soup.get_text(separator="\n", strip=True)
        # Collapse multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text
    except Exception:
        # Fallback: basic tag stripping
        text = re.sub(r'<script[^>]*>.*?</script>', '', raw_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', raw_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text


def _maybe_strip_html(content: str) -> str:
    """Strip HTML from content if it appears to be HTML, otherwise return as-is."""
    if content and "<" in content[:1000]:
        return _strip_html(content)
    return content


# ── LLM Result Cache ─────────────────────────────────────────

_EXTRACTION_CACHE_MAX = 256
_extraction_cache: OrderedDict = OrderedDict()


def _content_cache_key(content: str, extractor_type: str) -> str:
    """Generate a cache key from content + extractor type."""
    h = hashlib.sha256(f"{extractor_type}:{content}".encode()).hexdigest()[:32]
    return f"extraction:{h}"


def _cache_get(key: str):
    """Retrieve a cached extraction result, or None on miss."""
    if key in _extraction_cache:
        _extraction_cache.move_to_end(key)
        logger.debug("Extraction cache hit: %s", key)
        return _extraction_cache[key]
    return None


def _cache_set(key: str, value):
    """Store an extraction result in the cache (LRU eviction)."""
    _extraction_cache[key] = value
    _extraction_cache.move_to_end(key)
    while len(_extraction_cache) > _EXTRACTION_CACHE_MAX:
        _extraction_cache.popitem(last=False)


def clear_extraction_cache():
    """Clear the in-memory extraction cache. Useful for testing."""
    _extraction_cache.clear()

# Default model for extraction
DEFAULT_EXTRACTION_MODEL = "claude-sonnet-4-6"


@dataclass
class ExtractionResult:
    """Result of an extraction operation."""
    success: bool
    entity_id: int
    job_id: Optional[int] = None
    extracted_attributes: list = field(default_factory=list)
    error: Optional[str] = None
    model: Optional[str] = None
    cost_usd: float = 0.0
    duration_ms: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _build_extraction_prompt(entity_name, entity_type, attributes, content,
                             source_description="captured web page"):
    """Build the LLM prompt for attribute extraction.

    Args:
        entity_name: Name of the entity being analysed
        entity_type: Entity type name (e.g. "Company", "Product")
        attributes: List of attribute defs from schema
        content: The text/HTML content to analyse
        source_description: Human-readable description of the source

    Returns:
        prompt string
    """
    # Build attribute list for the prompt
    attr_descriptions = []
    for attr in attributes:
        desc = f"- {attr['name']} (slug: {attr['slug']}, type: {attr.get('data_type', 'text')})"
        if attr.get("description"):
            desc += f": {attr['description']}"
        if attr.get("enum_values"):
            desc += f" [allowed values: {', '.join(attr['enum_values'])}]"
        attr_descriptions.append(desc)

    attr_list = "\n".join(attr_descriptions) if attr_descriptions else "No specific attributes defined."

    # Truncate content if too long
    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH] + "\n\n[... content truncated ...]"

    return f"""You are a research analyst extracting structured data from evidence.

TASK: Analyse the following {source_description} and extract attribute values for the entity "{entity_name}" (type: {entity_type}).

ATTRIBUTES TO EXTRACT:
{attr_list}

RULES:
1. Only extract values you can actually find or confidently infer from the content.
2. Do NOT guess or fabricate values. If a value isn't present, omit it.
3. For each extracted value, provide:
   - The attribute slug (exactly matching the slugs above)
   - The extracted value (matching the expected data type)
   - A confidence score from 0.0 to 1.0 (1.0 = explicitly stated, 0.7+ = strongly implied, 0.5 = inferred, below 0.5 = uncertain)
   - Brief reasoning explaining where/how you found this value
4. For "tags" type attributes, return a JSON array of strings.
5. For "boolean" type, return true or false.
6. For "number" or "currency" type, return numeric values only.
7. For "date" type, return ISO format (YYYY-MM-DD).
8. For "enum" type, only use the allowed values listed.

CONTENT TO ANALYSE:
---
{content}
---

Extract all attributes you can find from this content."""


def _build_extraction_schema(attributes):
    """Build the JSON schema for structured LLM output.

    Returns:
        dict: Raw JSON schema (not SDK wrapper format)
    """
    return {
        "type": "object",
        "properties": {
            "extracted_attributes": {
                "type": "array",
                "description": "List of extracted attribute values",
                "items": {
                    "type": "object",
                    "properties": {
                        "attr_slug": {
                            "type": "string",
                            "description": "The attribute slug from the schema",
                        },
                        "value": {
                            "description": "The extracted value",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Confidence score (0-1)",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Brief explanation of how this value was found",
                        },
                    },
                    "required": ["attr_slug", "value", "confidence", "reasoning"],
                },
            },
            "entity_summary": {
                "type": "string",
                "description": "Brief summary of what was found about this entity",
            },
        },
        "required": ["extracted_attributes"],
    }


def _read_evidence_content(evidence, max_length=MAX_CONTENT_LENGTH):
    """Read content from an evidence file for extraction.

    Supports page_archive (HTML) and document types.
    Returns (content_string, content_type) or (None, None) if unreadable.
    """
    from core.capture import evidence_path_absolute

    evidence_type = evidence["evidence_type"]

    # Screenshot evidence — return a reference (actual vision analysis in Phase 3.3)
    # Check type BEFORE file existence since we know screenshots can't be read as text
    if evidence_type == "screenshot":
        return None, "image"

    file_path = evidence_path_absolute(evidence["file_path"])
    if not file_path.exists():
        return None, None

    # Text-based evidence
    if evidence_type in ("page_archive", "document"):
        ext = file_path.suffix.lower()
        if ext in (".html", ".htm", ".txt", ".md", ".csv", ".json", ".xml"):
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if len(content) > max_length:
                    content = content[:max_length]
                return content, "text"
            except Exception as e:
                logger.warning("Failed to read evidence file %s: %s", file_path, e)
                return None, None

    return None, None


def extract_from_content(content, entity_name, entity_type, attributes,
                         source_description="captured content",
                         model=None, timeout=120):
    """Extract structured attributes from text/HTML content.

    Args:
        content: Text or HTML content to analyse
        entity_name: Name of the entity
        entity_type: Entity type name
        attributes: List of attribute definitions from schema
        source_description: Human description of the source
        model: LLM model to use (default: claude-sonnet-4-6)
        timeout: LLM call timeout in seconds

    Returns:
        ExtractionResult
    """
    from core.llm import run_cli

    if not content or not content.strip():
        return ExtractionResult(
            success=False,
            entity_id=0,
            error="No content provided for extraction",
        )

    if not attributes:
        return ExtractionResult(
            success=False,
            entity_id=0,
            error="No attributes defined in schema for extraction",
        )

    model = model or DEFAULT_EXTRACTION_MODEL

    # Strip HTML before sending to LLM to reduce token usage
    content = _maybe_strip_html(content)
    content = content[:MAX_CONTENT_LENGTH]

    # Check extraction cache
    attr_key = ",".join(sorted(a["slug"] for a in attributes))
    cache_key = _content_cache_key(content + attr_key, model or "default")
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("Returning cached extraction result (%d attributes)", len(cached.extracted_attributes))
        return cached

    start = time.time()

    prompt = _build_extraction_prompt(
        entity_name, entity_type, attributes, content, source_description,
    )
    schema = _build_extraction_schema(attributes)

    try:
        response = run_cli(
            prompt=prompt,
            model=model,
            timeout=timeout,
            json_schema=json.dumps(schema),
        )
    except Exception as e:
        elapsed = int((time.time() - start) * 1000)
        logger.error("LLM extraction failed: %s", e)
        return ExtractionResult(
            success=False,
            entity_id=0,
            error=str(e),
            model=model,
            duration_ms=elapsed,
        )

    elapsed = int((time.time() - start) * 1000)

    if response.get("is_error"):
        return ExtractionResult(
            success=False,
            entity_id=0,
            error=response.get("result", "Unknown LLM error"),
            model=model,
            cost_usd=response.get("cost_usd", 0),
            duration_ms=elapsed,
        )

    # Parse structured output
    structured = response.get("structured_output")
    if not structured:
        # Try parsing the text response as JSON
        try:
            from json_repair import loads as repair_loads
            structured = repair_loads(response.get("result", "{}"))
        except Exception:
            return ExtractionResult(
                success=False,
                entity_id=0,
                error="LLM did not return structured output",
                model=model,
                cost_usd=response.get("cost_usd", 0),
                duration_ms=elapsed,
            )

    extracted = structured.get("extracted_attributes", [])

    # Validate extracted attributes against schema
    valid_slugs = {a["slug"] for a in attributes}
    validated = []
    for item in extracted:
        slug = item.get("attr_slug", "")
        if slug not in valid_slugs:
            logger.debug("Skipping unknown attribute slug: %s", slug)
            continue
        validated.append({
            "attr_slug": slug,
            "value": item.get("value"),
            "confidence": max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
            "reasoning": item.get("reasoning", ""),
        })

    result = ExtractionResult(
        success=True,
        entity_id=0,
        extracted_attributes=validated,
        model=model,
        cost_usd=response.get("cost_usd", 0),
        duration_ms=elapsed,
        metadata={
            "entity_summary": structured.get("entity_summary", ""),
            "raw_count": len(extracted),
            "valid_count": len(validated),
        },
    )

    # Cache successful extraction results
    if result.success:
        _cache_set(cache_key, result)

    return result


def extract_from_evidence(evidence, entity, schema_type_def, db=None,
                          model=None, timeout=120):
    """Extract attributes from a single evidence item.

    Args:
        evidence: Evidence dict (from DB — must include file_path, evidence_type)
        entity: Entity dict (from DB — must include id, name, type_slug)
        schema_type_def: Entity type definition dict (with attributes list)
        db: Database instance (if provided, stores results)
        model: LLM model override
        timeout: LLM call timeout

    Returns:
        ExtractionResult
    """
    content, content_type = _read_evidence_content(evidence)
    if content is None:
        if content_type == "image":
            return ExtractionResult(
                success=False,
                entity_id=entity["id"],
                error="Screenshot extraction requires vision model (Phase 3.3)",
            )
        return ExtractionResult(
            success=False,
            entity_id=entity["id"],
            error=f"Could not read evidence file: {evidence.get('file_path', 'unknown')}",
        )

    source_desc = f"captured {evidence['evidence_type']}"
    if evidence.get("source_url"):
        source_desc += f" from {evidence['source_url']}"

    attributes = schema_type_def.get("attributes", [])
    result = extract_from_content(
        content=content,
        entity_name=entity["name"],
        entity_type=schema_type_def.get("name", entity["type_slug"]),
        attributes=attributes,
        source_description=source_desc,
        model=model,
        timeout=timeout,
    )
    result.entity_id = entity["id"]

    # Store results in DB if provided
    if db and result.success and result.extracted_attributes:
        job_id = db.create_extraction_job(
            project_id=entity.get("project_id"),
            entity_id=entity["id"],
            source_type="evidence",
            evidence_id=evidence["id"],
            source_ref=evidence.get("source_url"),
        )
        result.job_id = job_id

        db.create_extraction_results_batch(
            job_id=job_id,
            entity_id=entity["id"],
            results=result.extracted_attributes,
            source_evidence_id=evidence["id"],
        )

        db.update_extraction_job(
            job_id,
            status="completed",
            model=result.model,
            cost_usd=result.cost_usd,
            duration_ms=result.duration_ms,
            result_count=len(result.extracted_attributes),
            completed_at=datetime.now().isoformat(),
        )

    return result


def extract_from_url(url, entity, schema_type_def, db=None,
                     model=None, timeout=120):
    """Fetch a URL and extract attributes from its content.

    Args:
        url: URL to fetch
        entity: Entity dict
        schema_type_def: Entity type definition with attributes
        db: Database instance (optional)
        model: LLM model override
        timeout: LLM call timeout

    Returns:
        ExtractionResult
    """
    import requests as req

    try:
        resp = req.get(
            url,
            timeout=30,
            headers={"User-Agent": "ResearchWorkbench/1.0"},
        )
        resp.raise_for_status()
        content = resp.text
    except Exception as e:
        return ExtractionResult(
            success=False,
            entity_id=entity["id"],
            error=f"Failed to fetch URL: {e}",
        )

    attributes = schema_type_def.get("attributes", [])
    result = extract_from_content(
        content=content,
        entity_name=entity["name"],
        entity_type=schema_type_def.get("name", entity["type_slug"]),
        attributes=attributes,
        source_description=f"web page at {url}",
        model=model,
        timeout=timeout,
    )
    result.entity_id = entity["id"]

    # Store results in DB
    if db and result.success and result.extracted_attributes:
        job_id = db.create_extraction_job(
            project_id=entity.get("project_id"),
            entity_id=entity["id"],
            source_type="url",
            source_ref=url,
        )
        result.job_id = job_id

        db.create_extraction_results_batch(
            job_id=job_id,
            entity_id=entity["id"],
            results=result.extracted_attributes,
        )

        db.update_extraction_job(
            job_id,
            status="completed",
            model=result.model,
            cost_usd=result.cost_usd,
            duration_ms=result.duration_ms,
            result_count=len(result.extracted_attributes),
            completed_at=datetime.now().isoformat(),
        )

    return result


def detect_contradictions(entity_id, db):
    """Check for contradictory extraction results for the same attribute.

    Finds attributes where multiple extraction results disagree.

    Args:
        entity_id: Entity to check
        db: Database instance

    Returns:
        list of dicts: [{attr_slug, values: [{value, confidence, job_id, source}], ...}]
    """
    results = db.get_extraction_results(entity_id=entity_id, status="pending")
    if not results:
        return []

    # Group by attr_slug
    by_attr = {}
    for r in results:
        slug = r["attr_slug"]
        if slug not in by_attr:
            by_attr[slug] = []
        by_attr[slug].append(r)

    contradictions = []
    for slug, items in by_attr.items():
        if len(items) < 2:
            continue

        # Check if values actually differ
        values = set()
        for item in items:
            v = item.get("extracted_value", "")
            values.add(str(v).strip().lower() if v else "")

        if len(values) > 1:
            contradictions.append({
                "attr_slug": slug,
                "values": [
                    {
                        "value": item["extracted_value"],
                        "confidence": item.get("confidence", 0.5),
                        "job_id": item["job_id"],
                        "result_id": item["id"],
                    }
                    for item in items
                ],
            })

    return contradictions
