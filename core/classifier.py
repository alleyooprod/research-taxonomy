"""Classify a company into the taxonomy using the LLM layer.

Uses Instructor + Pydantic validation on the SDK path when available,
with prompt caching on the taxonomy context.  Falls back to CLI +
dict-based validation otherwise.

Classification does NOT require web tools, so the full Instructor path
is available when the SDK is configured.
"""
import json
import logging

from config import PROMPTS_DIR, CLASSIFY_TIMEOUT
from core.llm import run_cli, instructor_available, run_instructor, run_sdk_cached

logger = logging.getLogger(__name__)

# Optional: Pydantic model for structured validation
try:
    from core.models import ClassificationResult, PYDANTIC_AVAILABLE
except ImportError:
    ClassificationResult = None
    PYDANTIC_AVAILABLE = False


def classify_company(company_data, taxonomy_tree, model="claude-opus-4-6"):
    """Classify a company into the taxonomy.

    Args:
        company_data: Dict with company research fields.
        taxonomy_tree: String representation of current taxonomy with counts.
        model: Claude model to use.

    Returns dict with category, subcategory, is_new_category, confidence, reasoning.

    Strategy:
      1. If Instructor is available, use it with ClassificationResult model
         and prompt caching on the taxonomy context.
      2. Otherwise, use SDK with prompt caching (if SDK available).
      3. Fall back to CLI with json_schema (original path).
    """
    prompt_template = (PROMPTS_DIR / "classify.txt").read_text()

    # Strip internal metadata from company data before sending
    clean_data = {k: v for k, v in company_data.items() if not k.startswith("_")}
    company_json = json.dumps(clean_data, indent=2)

    prompt = prompt_template.format(
        company_json=company_json,
        taxonomy_tree=taxonomy_tree,
    )

    # --- Path 1: Instructor (SDK + Pydantic validation + prompt caching) ---
    if instructor_available() and ClassificationResult is not None:
        try:
            # Split prompt: taxonomy context (cacheable) + company question
            context = f"TAXONOMY:\n{taxonomy_tree}"
            question = prompt_template.format(
                company_json=company_json,
                taxonomy_tree="{see context above}",
            )

            result, meta = run_instructor(
                question, model,
                response_model=ClassificationResult,
                timeout=CLASSIFY_TIMEOUT,
                max_retries=3,
                context=context,
            )
            structured = result.model_dump()
            logger.info(
                "Instructor classification: %s -> %s (%.2f confidence, %dms)",
                clean_data.get("name", "?"), structured.get("category", "?"),
                structured.get("confidence", 0), meta.get("duration_ms", 0),
            )
            return structured
        except Exception as e:
            logger.warning("Instructor classification failed, falling back: %s", e)

    # --- Path 2: SDK with prompt caching (no Instructor) ---
    schema = (PROMPTS_DIR / "schemas" / "company_classification.json").read_text()

    try:
        response = run_sdk_cached(
            prompt, model, timeout=CLASSIFY_TIMEOUT,
            json_schema=schema,
            context=f"TAXONOMY:\n{taxonomy_tree}",
        )
    except Exception:
        # Final fallback: plain run_cli
        response = run_cli(prompt, model, timeout=CLASSIFY_TIMEOUT,
                           json_schema=schema)

    structured = response.get("structured_output")
    if not structured:
        raw = response.get("result", "")
        try:
            structured = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise ValueError(f"No structured classification output. Raw: {raw[:300]}")

    # Validate with Pydantic when available (non-fatal)
    if PYDANTIC_AVAILABLE and ClassificationResult is not None:
        try:
            validated = ClassificationResult.model_validate(structured)
            return validated.model_dump()
        except Exception as e:
            logger.debug("Pydantic classification validation failed: %s", e)

    # Dict-based fallback validation
    if not isinstance(structured, dict):
        raise ValueError("Classification output is not a dict")
    if "confidence" in structured and structured["confidence"] is not None:
        try:
            structured["confidence"] = max(0.0, min(1.0, float(structured["confidence"])))
        except (ValueError, TypeError):
            structured["confidence"] = None

    return structured


def build_taxonomy_tree_string(db, project_id=None):
    """Build a human-readable taxonomy tree string from the database."""
    stats = db.get_category_stats(project_id=project_id)
    lines = []
    # Top-level categories (no parent)
    top_level = [s for s in stats if s["parent_id"] is None]
    subcategories = [s for s in stats if s["parent_id"] is not None]

    for cat in sorted(top_level, key=lambda x: x["name"]):
        line = f"- {cat['name']} ({cat['company_count']} companies)"
        if cat.get("scope_note"):
            line += f" \u2014 {cat['scope_note']}"
        lines.append(line)
        if cat.get("inclusion_criteria"):
            lines.append(f"  Includes: {cat['inclusion_criteria']}")
        if cat.get("exclusion_criteria"):
            lines.append(f"  Excludes: {cat['exclusion_criteria']}")
        # Find subcategories
        subs = [s for s in subcategories if s["parent_id"] == cat["id"]]
        for sub in sorted(subs, key=lambda x: x["name"]):
            sub_line = f"  - {sub['name']} ({sub['company_count']} companies)"
            if sub.get("scope_note"):
                sub_line += f" \u2014 {sub['scope_note']}"
            lines.append(sub_line)

    return "\n".join(lines)
