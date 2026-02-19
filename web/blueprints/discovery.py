"""Product discovery API: context files, feature landscape, gap analysis.

Uses SDK prompt caching for feature landscape (which has a large company
data context but no web tool dependency).  Gap analysis uses web tools
so it stays on CLI with optional Pydantic post-validation.
"""
import json
import logging
import os as _os
import re

from flask import Blueprint, current_app, jsonify, request

from config import DEFAULT_MODEL, MODEL_CHOICES
from core.llm import run_cli, run_sdk_cached, sdk_available
from storage.db import Database
from web.async_jobs import start_async_job, write_result, poll_result

logger = logging.getLogger(__name__)

# --- Security constants ---
ALLOWED_EXTENSIONS = {".txt", ".csv", ".md", ".json", ".xml", ".yaml", ".yml", ".pdf"}
_VALID_CONTEXT_TYPES = {"roadmap", "features", "requirements", "comparison", "other"}
_VALID_MODELS = set(MODEL_CHOICES.values())


def _sanitize_context(text, max_length=50000):
    """Sanitize user-uploaded context before LLM prompt inclusion."""
    if not text:
        return text
    # Strip control characters (keep \t, \n, \r)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    # Truncate
    return text[:max_length]


# Optional: Pydantic models for validation
try:
    from core.models import (
        FeatureLandscapeResult, GapAnalysisResult, PYDANTIC_AVAILABLE,
    )
except ImportError:
    FeatureLandscapeResult = None
    GapAnalysisResult = None
    PYDANTIC_AVAILABLE = False

discovery_bp = Blueprint("discovery", __name__)


# --- Context Files ---

@discovery_bp.route("/api/discovery/contexts")
def list_contexts():
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    return jsonify(current_app.db.get_contexts(project_id))


@discovery_bp.route("/api/discovery/upload-context", methods=["POST"])
def upload_context():
    db = current_app.db
    project_id = request.form.get("project_id", type=int)
    context_type = request.form.get("context_type", "roadmap")
    if context_type not in _VALID_CONTEXT_TYPES:
        context_type = "other"
    name = request.form.get("name", "").strip()

    if "file" in request.files:
        f = request.files["file"]
        # Validate file extension
        if f.filename:
            ext = _os.path.splitext(f.filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                return jsonify({"error": f"Unsupported file type: {ext}"}), 400
        content = f.read().decode("utf-8", errors="replace")
        filename = f.filename
        if not name:
            name = filename
    else:
        data = request.json or {}
        project_id = project_id or data.get("project_id")
        content = data.get("content", "")
        filename = data.get("filename")
        name = name or data.get("name", "Untitled")
        context_type = data.get("context_type", context_type)
        if context_type not in _VALID_CONTEXT_TYPES:
            context_type = "other"

    if not project_id or not content:
        return jsonify({"error": "project_id and content are required"}), 400

    # Limit content size (500KB)
    if len(content) > 512000:
        return jsonify({"error": "File too large (max 500KB)"}), 400

    ctx_id = db.save_context(project_id, name, content,
                              filename=filename, context_type=context_type)
    return jsonify({"id": ctx_id, "status": "ok"})


@discovery_bp.route("/api/discovery/contexts/<int:ctx_id>")
def get_context(ctx_id):
    ctx = current_app.db.get_context(ctx_id)
    if not ctx:
        return jsonify({"error": "Not found"}), 404
    return jsonify(ctx)


@discovery_bp.route("/api/discovery/contexts/<int:ctx_id>", methods=["DELETE"])
def delete_context(ctx_id):
    current_app.db.delete_context(ctx_id)
    return jsonify({"status": "ok"})


# --- Analyses ---

@discovery_bp.route("/api/discovery/analyses")
def list_analyses():
    project_id = request.args.get("project_id", type=int)
    analysis_type = request.args.get("type")
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    analyses = current_app.db.get_analyses(project_id, analysis_type=analysis_type)
    for a in analyses:
        if a.get("result") and isinstance(a["result"], dict):
            a["has_result"] = True
            a.pop("result", None)  # Don't send full result in list
    return jsonify(analyses)


@discovery_bp.route("/api/discovery/analyses/<int:analysis_id>")
def get_analysis(analysis_id):
    analysis = current_app.db.get_analysis(analysis_id)
    if not analysis:
        return jsonify({"error": "Not found"}), 404
    return jsonify(analysis)


@discovery_bp.route("/api/discovery/analyses/<int:analysis_id>", methods=["DELETE"])
def delete_analysis(analysis_id):
    current_app.db.delete_analysis(analysis_id)
    return jsonify({"status": "ok"})


# --- Feature Landscape ---

def _run_feature_landscape(job_id, analysis_id, project_id, model, category_filter):
    """Run feature landscape analysis.

    No web tools needed -- uses SDK prompt caching on company data context
    when available.  Falls back to CLI otherwise.
    """
    from pathlib import Path
    fl_db = Database()
    companies = fl_db.get_companies(project_id=project_id, limit=200)
    categories = fl_db.get_category_stats(project_id=project_id)

    if category_filter:
        companies = [c for c in companies if c.get("category_name") == category_filter]

    company_data = "\n".join(
        f"- {c['name']} ({c.get('category_name', 'N/A')}): {(c.get('products') or c.get('what') or 'N/A')[:150]}"
        for c in companies
    )
    cat_list = ", ".join(c["name"] for c in categories if not c.get("parent_id"))

    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "feature_landscape.txt"
    prompt = prompt_path.read_text().format(
        company_data=company_data,
        categories=cat_list,
        total_companies=len(companies),
        category_filter=category_filter or "all categories",
    )

    try:
        fl_db.update_analysis(analysis_id, status="running")

        # Use SDK with prompt caching on the company data context
        if sdk_available():
            try:
                response = run_sdk_cached(
                    prompt, model, timeout=300,
                    context=f"COMPANY DATA:\n{company_data}\n\nCATEGORIES: {cat_list}",
                )
            except Exception as e:
                logger.warning("SDK cached landscape failed, falling back to CLI: %s", e)
                response = run_cli(prompt, model, timeout=300)
        else:
            response = run_cli(prompt, model, timeout=300)

        text = response.get("result", "")

        # Try to parse structured JSON
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                result_data = json.loads(match.group())
            except json.JSONDecodeError:
                result_data = {"markdown": text}
        else:
            result_data = {"markdown": text}

        # Validate through Pydantic when available (non-fatal)
        if PYDANTIC_AVAILABLE and FeatureLandscapeResult is not None:
            try:
                validated = FeatureLandscapeResult.model_validate(result_data)
                result_data = validated.model_dump(exclude_none=True)
                # Ensure at least markdown is present
                if not result_data:
                    result_data = {"markdown": text}
            except Exception as e:
                logger.debug("Pydantic landscape validation failed: %s", e)

        fl_db.update_analysis(analysis_id, status="completed", result=result_data)
        write_result("landscape", job_id, {"status": "complete", "analysis_id": analysis_id})
    except Exception as e:
        fl_db.update_analysis(analysis_id, status="failed", error_message=str(e)[:300])
        write_result("landscape", job_id, {"status": "error", "error": str(e)[:200]})


@discovery_bp.route("/api/discovery/feature-landscape", methods=["POST"])
def feature_landscape():
    db = current_app.db
    data = request.json or {}
    project_id = data.get("project_id")
    model = data.get("model", DEFAULT_MODEL) if data.get("model") in _VALID_MODELS else DEFAULT_MODEL
    category_filter = data.get("category")

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    title = f"Feature Landscape{' \u2014 ' + category_filter if category_filter else ''}"
    analysis_id = db.save_analysis(
        project_id, "feature_landscape", title=title,
        parameters={"category": category_filter, "model": model},
        status="pending",
    )

    landscape_id = start_async_job("landscape", _run_feature_landscape,
                                    analysis_id, project_id, model, category_filter)
    return jsonify({"landscape_id": landscape_id, "analysis_id": analysis_id})


@discovery_bp.route("/api/discovery/feature-landscape/<landscape_id>")
def get_landscape_status(landscape_id):
    return jsonify(poll_result("landscape", landscape_id))


# --- Gap Analysis ---

def _run_gap_analysis(job_id, analysis_id, project_id, model, context_id):
    """Run gap analysis.

    Uses web tools (WebSearch/WebFetch) so CLI is always used.
    Results are validated through Pydantic when available.
    """
    from pathlib import Path
    ga_db = Database()

    companies = ga_db.get_companies(project_id=project_id, limit=200)
    categories = ga_db.get_category_stats(project_id=project_id)

    company_data = "\n".join(
        f"- {c['name']} ({c.get('category_name', 'N/A')}): {(c.get('products') or c.get('what') or 'N/A')[:150]}"
        for c in companies
    )
    cat_list = ", ".join(c["name"] for c in categories if not c.get("parent_id"))

    context_content = ""
    context_name = ""
    if context_id:
        ctx = ga_db.get_context(context_id)
        if ctx:
            context_content = _sanitize_context(ctx["content"])
            context_name = ctx["name"]

    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "gap_analysis.txt"
    prompt = prompt_path.read_text().format(
        company_data=company_data,
        categories=cat_list,
        total_companies=len(companies),
        context_content=context_content or "No comparison context provided \u2014 analyze best-in-class features only.",
        context_name=context_name or "N/A",
        has_context="true" if context_content else "false",
    )

    try:
        ga_db.update_analysis(analysis_id, status="running")
        response = run_cli(prompt, model, timeout=300,
                           tools="WebSearch,WebFetch")
        text = response.get("result", "")

        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                result_data = json.loads(match.group())
            except json.JSONDecodeError:
                result_data = {"markdown": text}
        else:
            result_data = {"markdown": text}

        # Validate through Pydantic when available (non-fatal)
        if PYDANTIC_AVAILABLE and GapAnalysisResult is not None:
            try:
                validated = GapAnalysisResult.model_validate(result_data)
                result_data = validated.model_dump(exclude_none=True)
                if not result_data:
                    result_data = {"markdown": text}
            except Exception as e:
                logger.debug("Pydantic gap analysis validation failed: %s", e)

        ga_db.update_analysis(analysis_id, status="completed", result=result_data)
        write_result("gap", job_id, {"status": "complete", "analysis_id": analysis_id})
    except Exception as e:
        ga_db.update_analysis(analysis_id, status="failed", error_message=str(e)[:300])
        write_result("gap", job_id, {"status": "error", "error": str(e)[:200]})


@discovery_bp.route("/api/discovery/gap-analysis", methods=["POST"])
def gap_analysis():
    db = current_app.db
    data = request.json or {}
    project_id = data.get("project_id")
    model = data.get("model", DEFAULT_MODEL) if data.get("model") in _VALID_MODELS else DEFAULT_MODEL
    context_id = data.get("context_id")

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    title = "Gap Analysis"
    if context_id:
        ctx = db.get_context(context_id)
        if ctx:
            title = f"Gap Analysis vs {ctx['name']}"

    analysis_id = db.save_analysis(
        project_id, "gap_analysis", title=title,
        parameters={"context_id": context_id, "model": model},
        context_id=context_id, status="pending",
    )

    gap_id = start_async_job("gap", _run_gap_analysis,
                              analysis_id, project_id, model, context_id)
    return jsonify({"gap_id": gap_id, "analysis_id": analysis_id})


@discovery_bp.route("/api/discovery/gap-analysis/<gap_id>")
def get_gap_status(gap_id):
    return jsonify(poll_result("gap", gap_id))
