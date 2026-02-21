"""Dimensions API: CRUD for research dimensions and company dimension values.

Uses Instructor + Pydantic validation on the SDK path for dimension
exploration and population (neither requires web tools).
Falls back to CLI + regex JSON extraction otherwise.
"""
import json
import logging
import re

from flask import Blueprint, current_app, jsonify, request

from config import DEFAULT_MODEL
from core.llm import run_cli, instructor_available, run_instructor
from storage.db import Database
from web.async_jobs import start_async_job, write_result, poll_result

logger = logging.getLogger(__name__)

# Optional: Pydantic model for structured validation
try:
    from core.models import DimensionValue, PYDANTIC_AVAILABLE
except ImportError:
    DimensionValue = None
    PYDANTIC_AVAILABLE = False

_VALID_DATA_TYPES = {"text", "number", "boolean", "enum", "url", "date"}

dimensions_bp = Blueprint("dimensions", __name__)


@dimensions_bp.route("/api/dimensions")
def list_dimensions():
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    return jsonify(current_app.db.get_dimensions(project_id))


@dimensions_bp.route("/api/dimensions", methods=["POST"])
def create_dimension():
    db = current_app.db
    data = request.json or {}
    project_id = data.get("project_id")
    name = data.get("name", "").strip()
    if not project_id or not name:
        return jsonify({"error": "project_id and name are required"}), 400

    data_type = data.get("data_type", "text")
    if data_type not in _VALID_DATA_TYPES:
        return jsonify({"error": f"Invalid data_type: {data_type}"}), 400

    dim_id = db.create_dimension(
        project_id=project_id,
        name=name,
        description=data.get("description"),
        data_type=data_type,
        source=data.get("source", "user_defined"),
        ai_prompt=data.get("ai_prompt"),
        enum_values=data.get("enum_values"),
    )
    return jsonify({"id": dim_id, "status": "ok"})


@dimensions_bp.route("/api/dimensions/<int:dim_id>", methods=["DELETE"])
def delete_dimension(dim_id):
    current_app.db.delete_dimension(dim_id)
    return jsonify({"status": "ok"})


@dimensions_bp.route("/api/dimensions/<int:dim_id>/values")
def get_dimension_values(dim_id):
    return jsonify(current_app.db.get_dimension_values(dim_id))


@dimensions_bp.route("/api/dimensions/<int:dim_id>/set-value", methods=["POST"])
def set_dimension_value(dim_id):
    data = request.json or {}
    company_id = data.get("company_id")
    value = data.get("value")
    if not company_id:
        return jsonify({"error": "company_id is required"}), 400
    current_app.db.set_company_dimension(company_id, dim_id, value,
                                          source="manual")
    return jsonify({"status": "ok"})


@dimensions_bp.route("/api/companies/<int:company_id>/dimensions")
def get_company_dimensions(company_id):
    return jsonify(current_app.db.get_company_dimensions(company_id))


# --- AI Dimension Exploration ---

def _run_explore_dimensions(job_id, project_id, model):
    """Explore dimensions using AI.

    No web tools needed -- full Instructor path available.
    """
    from pathlib import Path
    explore_db = Database()
    companies = explore_db.get_companies(project_id=project_id, limit=50)
    categories = explore_db.get_category_stats(project_id=project_id)

    cat_list = ", ".join(c["name"] for c in categories if not c.get("parent_id"))
    sample = "\n".join(
        f"- {c['name']}: {(c.get('what') or 'N/A')[:80]}"
        for c in companies[:20]
    )

    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "explore_dimensions.txt"
    prompt = prompt_path.read_text().format(
        categories=cat_list,
        sample_companies=sample,
        total_companies=len(companies),
    )

    try:
        response = run_cli(prompt, model, timeout=120)
        text = response.get("result", "")
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            dimensions = json.loads(match.group())
            result = {"status": "complete", "dimensions": dimensions}
        else:
            result = {"status": "complete", "dimensions": [], "raw": text}
    except Exception as e:
        result = {"status": "error", "error": str(e)[:200]}

    write_result("explore_dim", job_id, result)


@dimensions_bp.route("/api/dimensions/explore", methods=["POST"])
def explore_dimensions():
    data = request.json or {}
    project_id = data.get("project_id")
    model = data.get("model", DEFAULT_MODEL)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    explore_id = start_async_job("explore_dim", _run_explore_dimensions,
                                  project_id, model)
    return jsonify({"explore_id": explore_id})


@dimensions_bp.route("/api/dimensions/explore/<explore_id>")
def get_explore_status(explore_id):
    return jsonify(poll_result("explore_dim", explore_id))


# --- AI Dimension Population ---

_BATCH_SIZE = 8

_BATCH_DIMENSION_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "number"}
                },
                "required": ["company", "value", "confidence"],
                "additionalProperties": False
            }
        }
    },
    "required": ["results"],
    "additionalProperties": False
})


def _populate_single_company(pop_db, c, dimension, dimension_id, model, prompt_template):
    """Populate a dimension for a single company (fallback path).

    Returns a result dict {id, name, value?, ok, error?}.
    """
    company_context = (
        f"Name: {c['name']}\nURL: {c['url']}\n"
        f"What: {c.get('what', 'N/A')}\n"
        f"Products: {c.get('products', 'N/A')}\n"
        f"Target: {c.get('target', 'N/A')}"
    )
    prompt = prompt_template.format(
        dimension_name=dimension["name"],
        dimension_description=dimension.get("description") or dimension["name"],
        data_type=dimension["data_type"],
        company_context=company_context,
    )

    # --- Path 1: Instructor (SDK + Pydantic) ---
    use_instructor = instructor_available() and DimensionValue is not None
    if use_instructor:
        try:
            result_model, meta = run_instructor(
                prompt, model,
                response_model=DimensionValue,
                timeout=60,
                max_retries=2,
            )
            value = result_model.value or ""
            confidence = result_model.confidence or 0.5
            pop_db.set_company_dimension(c["id"], dimension_id,
                                          str(value), confidence, "ai")
            return {"id": c["id"], "name": c["name"],
                    "value": str(value), "ok": True}
        except Exception as e:
            logger.debug("Instructor dimension population failed for %s: %s",
                         c["name"], e)

    # --- Path 2: CLI fallback ---
    try:
        response = run_cli(prompt, model, timeout=60)
        text = response.get("result", "")
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            if PYDANTIC_AVAILABLE and DimensionValue is not None:
                try:
                    validated = DimensionValue.model_validate(parsed)
                    parsed = validated.model_dump()
                except Exception:
                    pass
            value = parsed.get("value", "")
            confidence = parsed.get("confidence", 0.5)
            pop_db.set_company_dimension(c["id"], dimension_id,
                                          str(value), confidence, "ai")
            return {"id": c["id"], "name": c["name"],
                    "value": str(value), "ok": True}
        else:
            return {"id": c["id"], "name": c["name"],
                    "ok": False, "error": "No value extracted"}
    except Exception as e:
        return {"id": c["id"], "name": c["name"],
                "ok": False, "error": str(e)[:100]}


def _run_populate_dimension(job_id, dimension_id, project_id, model):
    """Populate a dimension for all companies using AI.

    Batches companies into groups of 8 for a single LLM call each,
    reducing total API calls by ~8x. Falls back to individual calls
    if batch parsing fails for specific companies.
    """
    from pathlib import Path
    pop_db = Database()
    dimension = pop_db.get_dimension(dimension_id)
    if not dimension:
        write_result("populate_dim", job_id, {"status": "error", "error": "Dimension not found"})
        return

    companies = pop_db.get_companies(project_id=project_id, limit=500)
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "populate_dimension.txt"
    prompt_template = prompt_path.read_text() if prompt_path.exists() else ""

    dim_name = dimension["name"]
    dim_desc = dimension.get("description") or dim_name
    data_type = dimension["data_type"]

    results = []

    for i in range(0, len(companies), _BATCH_SIZE):
        batch = companies[i:i + _BATCH_SIZE]

        # Build a batch prompt
        company_lines = []
        for c in batch:
            company_lines.append(
                f"- {c['name']}: {(c.get('what') or 'N/A')[:100]} "
                f"(URL: {c.get('url', 'N/A')}, Target: {(c.get('target') or 'N/A')[:60]})"
            )
        company_list = "\n".join(company_lines)

        batch_prompt = (
            f"For each company below, determine the value for the dimension "
            f"\"{dim_name}\" ({dim_desc}).\n"
            f"Data type: {data_type}\n\n"
            f"Companies:\n{company_list}\n\n"
            f"Return a JSON object with a \"results\" key containing an array. "
            f"Each element: {{\"company\": \"exact company name\", \"value\": \"extracted value\", "
            f"\"confidence\": 0.0-1.0}}.\n"
            f"If you cannot determine a value, use an empty string with low confidence."
        )

        try:
            response = run_cli(batch_prompt, model, timeout=90,
                               json_schema=_BATCH_DIMENSION_SCHEMA)
            structured = response.get("structured_output")
            batch_results = None

            if structured and isinstance(structured, dict) and "results" in structured:
                batch_results = structured["results"]
            else:
                # Fallback: parse from raw text
                text = response.get("result", "").strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                try:
                    parsed = json.loads(text.strip())
                    if isinstance(parsed, dict) and "results" in parsed:
                        batch_results = parsed["results"]
                    elif isinstance(parsed, list):
                        batch_results = parsed
                except (json.JSONDecodeError, TypeError):
                    batch_results = None

            if batch_results:
                # Map results by company name (case-insensitive)
                result_map = {}
                for r in batch_results:
                    if isinstance(r, dict) and "company" in r:
                        result_map[r["company"].strip().lower()] = r

                for c in batch:
                    match = result_map.get(c["name"].strip().lower())
                    if match and match.get("value") is not None:
                        value = str(match.get("value", ""))
                        confidence = match.get("confidence", 0.5)
                        if not isinstance(confidence, (int, float)):
                            confidence = 0.5
                        confidence = max(0.0, min(1.0, float(confidence)))

                        if PYDANTIC_AVAILABLE and DimensionValue is not None:
                            try:
                                validated = DimensionValue.model_validate({
                                    "value": value, "confidence": confidence
                                })
                                value = str(validated.value or "")
                                confidence = validated.confidence or 0.5
                            except Exception:
                                pass

                        pop_db.set_company_dimension(c["id"], dimension_id,
                                                      value, confidence, "ai")
                        results.append({"id": c["id"], "name": c["name"],
                                        "value": value, "ok": True})
                    else:
                        # Company not in batch response — fall back to single
                        result = _populate_single_company(
                            pop_db, c, dimension, dimension_id, model, prompt_template
                        )
                        results.append(result)
            else:
                # Entire batch failed — fall back to individual calls
                logger.warning("Batch dimension population failed, falling back to individual calls")
                for c in batch:
                    result = _populate_single_company(
                        pop_db, c, dimension, dimension_id, model, prompt_template
                    )
                    results.append(result)

        except Exception as e:
            logger.warning("Batch dimension call failed: %s — falling back to individual", e)
            for c in batch:
                result = _populate_single_company(
                    pop_db, c, dimension, dimension_id, model, prompt_template
                )
                results.append(result)

    write_result("populate_dim", job_id,
                  {"status": "complete", "results": results,
                   "dimension": dimension["name"]})


@dimensions_bp.route("/api/dimensions/<int:dim_id>/populate", methods=["POST"])
def populate_dimension(dim_id):
    data = request.json or {}
    project_id = data.get("project_id")
    model = data.get("model", DEFAULT_MODEL)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    populate_id = start_async_job("populate_dim", _run_populate_dimension,
                                   dim_id, project_id, model)
    return jsonify({"populate_id": populate_id})


@dimensions_bp.route("/api/dimensions/populate/<populate_id>")
def get_populate_status(populate_id):
    return jsonify(poll_result("populate_dim", populate_id))
