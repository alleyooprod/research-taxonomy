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

def _run_populate_dimension(job_id, dimension_id, project_id, model):
    """Populate a dimension for all companies using AI.

    No web tools needed -- uses Instructor when available for validated
    dimension values with confidence scores.
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

    use_instructor = instructor_available() and DimensionValue is not None

    results = []
    for c in companies:
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
                results.append({"id": c["id"], "name": c["name"],
                                "value": str(value), "ok": True})
                continue
            except Exception as e:
                logger.debug("Instructor dimension population failed for %s: %s",
                             c["name"], e)
                # Fall through to CLI path

        # --- Path 2: CLI fallback ---
        try:
            response = run_cli(prompt, model, timeout=60)
            text = response.get("result", "")
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                parsed = json.loads(match.group())

                # Validate through Pydantic when available
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
                results.append({"id": c["id"], "name": c["name"],
                                "value": str(value), "ok": True})
            else:
                results.append({"id": c["id"], "name": c["name"],
                                "ok": False, "error": "No value extracted"})
        except Exception as e:
            results.append({"id": c["id"], "name": c["name"],
                            "ok": False, "error": str(e)[:100]})

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
