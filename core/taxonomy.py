"""Taxonomy evolution: reviews and restructures categories after each batch.

Uses Instructor + Pydantic validation on the SDK path when available,
with prompt caching on the taxonomy context.  Falls back to CLI +
dict-based validation otherwise.

Neither evolve_taxonomy nor review_taxonomy require web tools, so the
full Instructor path is available when the SDK is configured.
"""
import json
import logging
import re
import threading

from config import PROMPTS_DIR, EVOLVE_TIMEOUT
from core.classifier import build_taxonomy_tree_string
from core.llm import (
    run_cli, instructor_available, run_instructor, run_sdk_cached,
)

logger = logging.getLogger(__name__)

REVIEW_TIMEOUT = 180  # Full review is more complex, allow 3 minutes

# Lock to prevent concurrent taxonomy mutations (#5)
_taxonomy_lock = threading.Lock()

# Optional: Pydantic model for structured validation
try:
    from core.models import TaxonomyEvolution, PYDANTIC_AVAILABLE
except ImportError:
    TaxonomyEvolution = None
    PYDANTIC_AVAILABLE = False


def _apply_single_change(db, change, project_id=None):
    """Apply one taxonomy change dict. Returns the change if successful, else None."""
    # Accept both dict and Pydantic model
    if hasattr(change, "model_dump"):
        change = change.model_dump()

    change_type = change.get("type")
    reason = change.get("reason", "")

    try:
        if change_type == "add":
            name = change.get("category_name")
            if name:
                cat_id = db.add_category(name, project_id=project_id)
                if cat_id:
                    db.log_taxonomy_change("add", {"name": name}, reason, [cat_id],
                                           project_id=project_id)
                    return change

        elif change_type == "merge":
            source = change.get("category_name")
            target = change.get("merge_into")
            if source and target:
                success = db.merge_categories(source, target, reason,
                                              project_id=project_id)
                if success:
                    return change

        elif change_type == "rename":
            old_name = change.get("category_name")
            new_name = change.get("new_name")
            if old_name and new_name:
                success = db.rename_category(old_name, new_name, reason,
                                             project_id=project_id)
                if success:
                    return change

        elif change_type == "add_subcategory":
            name = change.get("category_name")
            parent_name = change.get("parent_category")
            if name and parent_name:
                parent = db.get_category_by_name(parent_name, project_id=project_id)
                if parent:
                    cat_id = db.add_category(name, parent_id=parent["id"],
                                             project_id=project_id)
                    if cat_id:
                        db.log_taxonomy_change(
                            "add_subcategory",
                            {"name": name, "parent": parent_name},
                            reason, [cat_id], project_id=project_id,
                        )
                        return change

        elif change_type == "split":
            source = change.get("category_name")
            new_cats = change.get("split_into", [])
            if source and new_cats:
                new_cat_ids = []
                for new_name in new_cats:
                    cat_id = db.add_category(new_name, project_id=project_id)
                    if cat_id:
                        new_cat_ids.append((new_name, cat_id))

                source_cat = db.get_category_by_name(source, project_id=project_id)
                if source_cat and new_cat_ids:
                    companies = db.get_companies(
                        project_id=project_id, category_id=source_cat["id"]
                    )
                    if companies and len(new_cat_ids) > 0:
                        for i, c in enumerate(companies):
                            target_name, target_id = new_cat_ids[i % len(new_cat_ids)]
                            db.update_company(c["id"], {"category_id": target_id},
                                              save_history=False)

                db.log_taxonomy_change(
                    "split",
                    {"from": source, "into": new_cats},
                    reason, project_id=project_id,
                )
                return change

        elif change_type == "move":
            company_name = change.get("category_name")
            target_cat = change.get("merge_into")
            if company_name and target_cat:
                target = db.get_category_by_name(target_cat, project_id=project_id)
                if target:
                    companies = db.get_companies(search=company_name,
                                                 project_id=project_id)
                    for c in companies:
                        if c["name"].lower() == company_name.lower():
                            db.update_company(c["id"], {
                                "category_id": target["id"],
                            }, save_history=False)
                            db.log_taxonomy_change(
                                "move",
                                {"company": company_name, "to": target_cat},
                                reason, project_id=project_id,
                            )
                            return change

    except Exception as e:
        print(f"  Warning: Failed to apply {change_type} change: {e}")

    return None


def _parse_structured(response):
    """Extract structured output from LLM response, falling back to parsing result text.

    When Pydantic is available, validates through TaxonomyEvolution model.
    """
    structured = response.get("structured_output")
    if not structured:
        raw = response.get("result", "")
        try:
            structured = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    # Validate through Pydantic when available (non-fatal)
    if PYDANTIC_AVAILABLE and TaxonomyEvolution is not None and structured:
        try:
            validated = TaxonomyEvolution.model_validate(structured)
            return validated.model_dump()
        except Exception as e:
            logger.debug("Pydantic taxonomy validation failed: %s", e)

    return structured


def evolve_taxonomy(db, batch_id, model="claude-opus-4-6", project_id=None):
    """Review and evolve taxonomy after a batch completes.

    Calls Claude to analyze the current taxonomy state and propose changes.
    Applies approved changes to the database.

    Strategy:
      1. Instructor + prompt caching on taxonomy context (if available).
      2. SDK with prompt caching (if SDK available).
      3. CLI with json_schema (original path).
    """
    taxonomy_tree = build_taxonomy_tree_string(db, project_id=project_id)
    batch_companies = db.get_batch_companies(batch_id)
    stats = db.get_stats(project_id=project_id)

    if not batch_companies:
        print("  No companies in batch to analyze for taxonomy evolution.")
        return []

    company_summaries = []
    for c in batch_companies:
        company_summaries.append(
            f"- {c['name']}: {(c.get('what') or '')[:150]}"
        )
    new_companies_text = "\n".join(company_summaries)
    # Wrap company data in XML delimiters for prompt injection safety
    new_companies_delimited = f"<company_data>\n{new_companies_text}\n</company_data>"

    prompt_template = (PROMPTS_DIR / "evolve_taxonomy.txt").read_text()
    prompt = prompt_template.format(
        taxonomy_tree=taxonomy_tree,
        new_companies=new_companies_delimited,
        total_companies=stats["total_companies"],
    )

    structured = None

    # --- Path 1: Instructor (SDK + Pydantic + prompt caching) ---
    if instructor_available() and TaxonomyEvolution is not None:
        try:
            context = f"TAXONOMY:\n{taxonomy_tree}"
            question = prompt_template.format(
                taxonomy_tree="{see context above}",
                new_companies=new_companies_delimited,
                total_companies=stats["total_companies"],
            )
            result, meta = run_instructor(
                question, model,
                response_model=TaxonomyEvolution,
                timeout=EVOLVE_TIMEOUT,
                max_retries=3,
                context=context,
            )
            structured = result.model_dump()
            logger.info("Instructor taxonomy evolution completed in %dms", meta.get("duration_ms", 0))
        except Exception as e:
            logger.warning("Instructor taxonomy evolution failed, falling back: %s", e)
            structured = None

    # --- Path 2: SDK cached or CLI fallback ---
    if structured is None:
        schema = (PROMPTS_DIR / "schemas" / "taxonomy_evolution.json").read_text()
        try:
            response = run_sdk_cached(
                prompt, model, timeout=EVOLVE_TIMEOUT,
                json_schema=schema,
                context=f"TAXONOMY:\n{taxonomy_tree}",
            )
            structured = _parse_structured(response)
        except Exception as e:
            # Final fallback: plain CLI
            try:
                response = run_cli(prompt, model, timeout=EVOLVE_TIMEOUT,
                                   json_schema=schema)
                structured = _parse_structured(response)
            except Exception as e2:
                print(f"  Warning: Taxonomy evolution failed: {e2}")
                return []

    if not structured:
        print("  Warning: No structured taxonomy evolution output")
        return []

    print(f"  Taxonomy analysis: {structured.get('analysis', '')[:200]}")

    if structured.get("no_changes_needed"):
        print("  No taxonomy changes needed.")
        return []

    changes = structured.get("changes", [])
    applied = []

    with _taxonomy_lock:
        for change in changes:
            result = _apply_single_change(db, change, project_id=project_id)
            if result:
                change_type = change.get("type", "?")
                name = change.get("category_name", "")
                if change_type == "add":
                    print(f"  + Added category: {name}")
                elif change_type == "merge":
                    print(f"  ~ Merged '{name}' into '{change.get('merge_into')}'")
                elif change_type == "rename":
                    print(f"  ~ Renamed '{name}' to '{change.get('new_name')}'")
                elif change_type == "add_subcategory":
                    print(f"  + Added subcategory: {name} (under {change.get('parent_category')})")
                elif change_type == "split":
                    print(f"  / Split '{name}' into {change.get('split_into', [])}")
                applied.append(result)

    return applied


def review_taxonomy(db, model="claude-opus-4-6", project_id=None, observations=""):
    """Full taxonomy review -- proposes changes but does NOT apply them.

    Returns dict with 'analysis' and 'changes' for user confirmation.

    Strategy:
      1. Instructor + prompt caching (if available).
      2. SDK with prompt caching.
      3. CLI (original path).
    """
    taxonomy_tree = build_taxonomy_tree_string(db, project_id=project_id)
    companies = db.get_companies(project_id=project_id)
    stats = db.get_stats(project_id=project_id)

    if not companies:
        return {"analysis": "No companies in taxonomy to review.", "changes": []}

    company_lines = []
    for c in companies:
        cat = c.get("category_name", "Uncategorized")
        company_lines.append(
            f"- [{cat}] {c['name']}: {(c.get('what') or '')[:120]}"
        )
    all_companies_text = "\n".join(company_lines)
    # Wrap company data in XML delimiters for prompt injection safety
    all_companies_delimited = f"<company_data>\n{all_companies_text}\n</company_data>"

    prompt_template = (PROMPTS_DIR / "review_taxonomy.txt").read_text()
    prompt = prompt_template.format(
        taxonomy_tree=taxonomy_tree,
        all_companies=all_companies_delimited,
        total_companies=stats["total_companies"],
    )

    if observations:
        # Sanitize: strip control chars, limit length
        clean_obs = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(observations))[:2000]
        prompt += f"\n\n<user_observations>\n{clean_obs}\n</user_observations>\nConsider the user observations above as additional context."

    # --- Path 1: Instructor (SDK + Pydantic + prompt caching) ---
    if instructor_available() and TaxonomyEvolution is not None:
        try:
            context = (
                f"TAXONOMY:\n{taxonomy_tree}\n\n"
                f"<company_data>\n{all_companies_text}\n</company_data>"
            )
            question = prompt_template.format(
                taxonomy_tree="{see context above}",
                all_companies="{see context above}",
                total_companies=stats["total_companies"],
            )
            if observations:
                clean_obs = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(observations))[:2000]
                question += f"\n\n<user_observations>\n{clean_obs}\n</user_observations>\nConsider the user observations above as additional context."

            result, meta = run_instructor(
                question, model,
                response_model=TaxonomyEvolution,
                timeout=REVIEW_TIMEOUT,
                max_retries=3,
                context=context,
            )
            structured = result.model_dump()
            logger.info("Instructor taxonomy review completed in %dms", meta.get("duration_ms", 0))
            return structured
        except Exception as e:
            logger.warning("Instructor taxonomy review failed, falling back: %s", e)

    # --- Path 2: SDK cached ---
    schema = (PROMPTS_DIR / "schemas" / "taxonomy_evolution.json").read_text()

    try:
        response = run_sdk_cached(
            prompt, model, timeout=REVIEW_TIMEOUT,
            json_schema=schema,
            context=f"TAXONOMY:\n{taxonomy_tree}\n\n<company_data>\n{all_companies_text}\n</company_data>",
        )
    except Exception:
        # Final fallback: plain CLI
        try:
            response = run_cli(prompt, model, timeout=REVIEW_TIMEOUT,
                               json_schema=schema)
        except Exception as e:
            return {"error": f"Review failed: {e}", "changes": []}

    structured = _parse_structured(response)
    if not structured:
        return {"error": "No structured output from review", "changes": []}

    return structured


def apply_taxonomy_changes(db, changes, project_id=None):
    """Apply a list of taxonomy changes (after user confirmation).

    Returns list of successfully applied changes.
    """
    applied = []
    with _taxonomy_lock:
        for change in changes:
            result = _apply_single_change(db, change, project_id=project_id)
            if result:
                applied.append(result)
    return applied
