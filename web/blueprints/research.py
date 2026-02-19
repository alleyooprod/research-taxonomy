"""Research API: deep dive and open-ended research sessions."""
import json
import subprocess
import time

from flask import Blueprint, current_app, jsonify, request

from config import DEFAULT_MODEL, RESEARCH_TIMEOUT
from core.llm import run_cli
from core.git_sync import sync_to_git_async
from storage.db import Database
from web.async_jobs import start_async_job, write_result, poll_result

research_bp = Blueprint("research", __name__)


def _build_context(db, scope_type, scope_id, project_id):
    """Assemble context from the database based on research scope."""
    context = {"scope_type": scope_type, "scope_id": scope_id}

    if scope_type == "company" and scope_id:
        company = db.get_company(scope_id)
        if company:
            context["company"] = {
                "name": company.get("name"),
                "url": company.get("url"),
                "what": company.get("what"),
                "target": company.get("target"),
                "products": company.get("products"),
                "funding": company.get("funding"),
                "geography": company.get("geography"),
                "tam": company.get("tam"),
                "tags": company.get("tags", []),
                "funding_stage": company.get("funding_stage"),
                "total_funding_usd": company.get("total_funding_usd"),
                "employee_range": company.get("employee_range"),
                "founded_year": company.get("founded_year"),
                "hq_city": company.get("hq_city"),
                "hq_country": company.get("hq_country"),
                "category_name": company.get("category_name"),
                "business_model": company.get("business_model"),
                "primary_focus": company.get("primary_focus"),
            }
            context["notes"] = [n["content"] for n in db.get_notes(scope_id)]

    elif scope_type == "category" and scope_id:
        cat = db.get_category(scope_id)
        if cat:
            context["category"] = {"name": cat.get("name"), "description": cat.get("description")}
            companies = db.get_companies(category_id=scope_id, project_id=project_id, limit=50)
            context["companies"] = [
                {"name": c["name"], "what": c.get("what"), "target": c.get("target"),
                 "funding_stage": c.get("funding_stage"), "geography": c.get("geography")}
                for c in companies
            ]

    elif scope_type == "project":
        categories = db.get_category_stats(project_id=project_id)
        context["categories"] = [
            {"name": c["name"], "company_count": c["company_count"]} for c in categories
        ]
        companies = db.get_companies(project_id=project_id, limit=100)
        context["company_count"] = len(companies)
        context["top_companies"] = [
            {"name": c["name"], "category_name": c.get("category_name"), "what": c.get("what")}
            for c in companies[:20]
        ]

    return context


def _build_prompt(user_prompt, context, scope_type):
    """Build a rich LLM prompt from user question + assembled context."""
    ctx_text = ""

    if scope_type == "company" and context.get("company"):
        c = context["company"]
        ctx_text = f"""COMPANY CONTEXT:
Name: {c.get('name','N/A')}
URL: {c.get('url','N/A')}
Category: {c.get('category_name','N/A')}
What they do: {c.get('what','N/A')}
Target market: {c.get('target','N/A')}
Products: {c.get('products','N/A')}
Funding: {c.get('funding','N/A')} (Stage: {c.get('funding_stage','N/A')}, Total: ${c.get('total_funding_usd','N/A')})
Geography: {c.get('geography','N/A')} (HQ: {c.get('hq_city','')}, {c.get('hq_country','')})
Employees: {c.get('employee_range','N/A')}
Founded: {c.get('founded_year','N/A')}
TAM: {c.get('tam','N/A')}
Tags: {', '.join(c.get('tags',[]))}
Business Model: {c.get('business_model','N/A')}
Primary Focus: {c.get('primary_focus','N/A')}
"""
        if context.get("notes"):
            ctx_text += f"\nUser Notes:\n" + "\n".join(f"- {n}" for n in context["notes"])

    elif scope_type == "category" and context.get("category"):
        cat = context["category"]
        ctx_text = f"""CATEGORY CONTEXT:
Name: {cat.get('name','N/A')}
Description: {cat.get('description','N/A')}
Companies ({len(context.get('companies',[]))}):
"""
        for c in context.get("companies", []):
            ctx_text += f"- {c['name']}: {c.get('what','N/A')} | {c.get('funding_stage','N/A')} | {c.get('geography','N/A')}\n"

    elif scope_type == "project":
        ctx_text = f"""PROJECT CONTEXT:
Total companies: {context.get('company_count',0)}
Categories: {len(context.get('categories',[]))}
"""
        for cat in context.get("categories", []):
            ctx_text += f"- {cat['name']} ({cat['company_count']} companies)\n"
        ctx_text += "\nSample companies:\n"
        for c in context.get("top_companies", []):
            ctx_text += f"- {c['name']} [{c.get('category_name','N/A')}]: {c.get('what','N/A')}\n"

    return f"""You are a senior research analyst conducting deep-dive research. You have access to web search and web fetch tools to find real-time information.

{ctx_text}

RESEARCH QUESTION:
{user_prompt}

INSTRUCTIONS:
1. Use the context above as a starting point
2. Use WebSearch and WebFetch to find current, detailed information
3. Produce a comprehensive, well-structured research report in Markdown
4. Include specific data, numbers, and citations where possible
5. Every factual claim from web search must include a citation [Source](URL)
6. Be thorough — this is a deep dive, not a summary
"""


def _run_research(job_id, research_id, project_id, user_prompt,
                  scope_type, scope_id, model):
    """Background worker for research generation."""
    research_db = Database()
    research_db.update_research(research_id, {"status": "running"})

    start = time.time()
    context = _build_context(research_db, scope_type, scope_id, project_id)
    prompt = _build_prompt(user_prompt, context, scope_type)

    try:
        response = run_cli(prompt, model, timeout=RESEARCH_TIMEOUT, tools="WebSearch,WebFetch")
        result = response.get("result", "")
        duration_ms = int((time.time() - start) * 1000)
        cost_usd = response.get("cost_usd")

        research_db.update_research(research_id, {
            "result": result,
            "status": "completed",
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
        })
        write_result("research", job_id, {
            "status": "completed", "research_id": research_id,
        })
    except subprocess.TimeoutExpired:
        timeout_min = RESEARCH_TIMEOUT // 60
        research_db.update_research(research_id, {
            "status": "failed",
            "result": f"Research timed out after {timeout_min} minutes. The question may be too broad or web searches took too long. Try a more focused question or a faster model.",
        })
        write_result("research", job_id, {"status": "error", "error": f"Research timed out after {timeout_min} minutes."})
    except Exception as e:
        research_db.update_research(research_id, {"status": "failed", "result": str(e)[:500]})
        write_result("research", job_id, {"status": "error", "error": str(e)[:300]})

    sync_to_git_async("Research completed")


@research_bp.route("/api/research", methods=["POST"])
def start_research():
    db = current_app.db
    data = request.json or {}
    project_id = data.get("project_id")
    title = data.get("title", "").strip() or "Untitled Research"
    scope_type = data.get("scope_type", "custom")
    scope_id = data.get("scope_id")
    user_prompt = data.get("prompt", "").strip()
    model = data.get("model", DEFAULT_MODEL)

    if not user_prompt:
        return jsonify({"error": "Research prompt is required"}), 400

    research_id = db.create_research(
        project_id=project_id, title=title, scope_type=scope_type,
        scope_id=scope_id, prompt=user_prompt, model=model,
    )

    job_id = start_async_job(
        "research", _run_research,
        research_id, project_id, user_prompt, scope_type, scope_id, model,
    )

    return jsonify({"research_id": research_id, "job_id": job_id})


@research_bp.route("/api/research")
def list_research():
    project_id = request.args.get("project_id", type=int)
    items = current_app.db.list_research(project_id)
    return jsonify(items)


@research_bp.route("/api/research/<int:research_id>")
def get_research(research_id):
    item = current_app.db.get_research(research_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item)


@research_bp.route("/api/research/<int:research_id>", methods=["DELETE"])
def delete_research(research_id):
    current_app.db.delete_research(research_id)
    return jsonify({"status": "ok"})


@research_bp.route("/api/research/<int:research_id>/poll")
def poll_research(research_id):
    item = current_app.db.get_research(research_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": item["status"], "research_id": research_id})


# --- Research Templates ---

@research_bp.route("/api/research/templates")
def list_templates():
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id required"}), 400
    templates = current_app.db.get_research_templates(project_id)
    if not templates:
        current_app.db.seed_default_templates(project_id)
        templates = current_app.db.get_research_templates(project_id)
    return jsonify(templates)


@research_bp.route("/api/research/templates", methods=["POST"])
def create_template():
    data = request.json or {}
    project_id = data.get("project_id")
    name = data.get("name", "").strip()
    prompt_template = data.get("prompt_template", "").strip()
    if not project_id or not name or not prompt_template:
        return jsonify({"error": "project_id, name, and prompt_template required"}), 400
    tid = current_app.db.create_research_template(
        project_id, name, prompt_template, data.get("scope_type", "project"),
    )
    return jsonify({"id": tid, "status": "ok"})


@research_bp.route("/api/research/templates/<int:template_id>", methods=["PUT"])
def update_template(template_id):
    data = request.json or {}
    name = data.get("name", "").strip()
    prompt_template = data.get("prompt_template", "").strip()
    if not name or not prompt_template:
        return jsonify({"error": "name and prompt_template required"}), 400
    current_app.db.update_research_template(
        template_id, name, prompt_template, data.get("scope_type"),
    )
    return jsonify({"status": "ok"})


@research_bp.route("/api/research/templates/<int:template_id>", methods=["DELETE"])
def delete_template(template_id):
    current_app.db.delete_research_template(template_id)
    return jsonify({"status": "ok"})
