"""Canvas API: visual workspaces for arranging companies and notes."""
import json
import subprocess
import time

from flask import Blueprint, current_app, jsonify, request

from config import RESEARCH_MODEL
from core.llm import run_cli
from storage.db import Database
from web.async_jobs import start_async_job, write_result, poll_result

canvas_bp = Blueprint("canvas", __name__)

# --- Structured output schema for diagram generation ---
DIAGRAM_SCHEMA = json.dumps({
    "name": "diagram_layout",
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "layout_style": {
                "type": "string",
                "enum": [
                    "stacked_horizontal", "stacked_vertical",
                    "grid", "radial", "flow", "enterprise_stack",
                ],
            },
            "category_blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "integer"},
                        "category_name": {"type": "string"},
                        "label": {"type": "string"},
                        "color": {"type": "string"},
                        "row": {"type": "integer"},
                        "col": {"type": "integer"},
                        "width_units": {
                            "type": "integer", "minimum": 1, "maximum": 6,
                        },
                        "height_units": {
                            "type": "integer", "minimum": 1, "maximum": 6,
                        },
                        "companies": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "company_id": {"type": "integer"},
                                    "name": {"type": "string"},
                                    "fields": {
                                        "type": "object",
                                        "additionalProperties": {
                                            "type": "string",
                                        },
                                    },
                                },
                                "required": ["company_id", "name"],
                            },
                        },
                    },
                    "required": [
                        "category_id", "category_name", "label",
                        "row", "col", "width_units", "height_units",
                        "companies",
                    ],
                },
            },
            "connectors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_category_id": {"type": "integer"},
                        "to_category_id": {"type": "integer"},
                        "label": {"type": "string"},
                    },
                    "required": ["from_category_id", "to_category_id"],
                },
            },
            "annotations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "row": {"type": "number"},
                        "col": {"type": "number"},
                        "style": {
                            "type": "string",
                            "enum": ["heading", "subheading", "note"],
                        },
                    },
                    "required": ["text", "row", "col"],
                },
            },
        },
        "required": ["title", "layout_style", "category_blocks"],
    },
})


# --- CRUD ---

@canvas_bp.route("/api/canvases", methods=["POST"])
def create_canvas():
    data = request.json or {}
    project_id = data.get("project_id")
    title = data.get("title", "Untitled Canvas").strip() or "Untitled Canvas"
    canvas_id = current_app.db.create_canvas(project_id, title)
    return jsonify({"id": canvas_id, "status": "ok"})


@canvas_bp.route("/api/canvases")
def list_canvases():
    project_id = request.args.get("project_id", type=int)
    items = current_app.db.list_canvases(project_id)
    return jsonify(items)


@canvas_bp.route("/api/canvases/<int:canvas_id>")
def get_canvas(canvas_id):
    item = current_app.db.get_canvas(canvas_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item)


@canvas_bp.route("/api/canvases/<int:canvas_id>", methods=["PUT"])
def update_canvas(canvas_id):
    fields = request.json or {}
    current_app.db.update_canvas(canvas_id, fields)
    return jsonify({"status": "ok"})


@canvas_bp.route("/api/canvases/<int:canvas_id>", methods=["DELETE"])
def delete_canvas(canvas_id):
    current_app.db.delete_canvas(canvas_id)
    return jsonify({"status": "ok"})


# --- AI Diagram Generation ---

def _build_diagram_prompt(user_prompt, categories_data, layout_style):
    """Build the LLM prompt for diagram layout generation."""
    context_parts = []
    for cat in categories_data:
        lines = [f"## {cat['name']} (ID: {cat['id']}, Color: {cat.get('color', '#888')}, "
                 f"{len(cat['companies'])} companies)"]
        for co in cat["companies"]:
            field_parts = [co["name"]]
            for k, v in co.get("fields", {}).items():
                if v:
                    field_parts.append(f"{k}: {v}")
            lines.append("- " + " | ".join(field_parts))
        context_parts.append("\n".join(lines))

    taxonomy_context = "\n\n".join(context_parts)

    return f"""You are a visual information architect specializing in enterprise market landscapes.
Your task is to arrange companies into a structured diagram layout.

TAXONOMY DATA:
{taxonomy_context}

USER'S VISUALIZATION REQUEST:
"{user_prompt}"

REQUESTED LAYOUT STYLE: {layout_style}

INSTRUCTIONS:
1. Arrange category blocks using row/col grid coordinates (0-indexed).
   Each grid unit is approximately 300px wide and 200px tall.
2. Size each block (width_units x height_units) to fit its companies.
   Rule of thumb: 1 height_unit per ~6 companies.
3. Use the category's provided color. If none, assign a visually distinct hex color.
4. Include ALL companies from the provided data in the appropriate block.
5. For each company, include exactly the data fields shown in the input.
6. If relationships between categories are implied by the user's request,
   add connectors with optional labels.
7. Add annotations (headings, subheadings, notes) if the layout benefits from them.
8. Do NOT overlap blocks — ensure (row,col) + (width,height) don't conflict.
9. Max grid: 12 columns x 10 rows.
10. Prioritize readability: largest categories first, related categories nearby.
"""


def _run_diagram_generation(job_id, project_id, category_ids, fields,
                            user_prompt, model, layout_style):
    """Background worker for diagram generation."""
    db = Database()
    start = time.time()

    try:
        # Fetch category + company data
        categories_data = []
        all_categories = db.get_categories(project_id)
        cat_map = {c["id"]: c for c in all_categories}

        for cat_id in category_ids:
            cat = cat_map.get(cat_id)
            if not cat:
                continue
            companies = db.get_companies(project_id=project_id,
                                         category_id=cat_id, limit=100)
            cat_entry = {
                "id": cat_id,
                "name": cat["name"],
                "color": cat.get("color", "#888"),
                "companies": [],
            }
            for co in companies:
                co_entry = {
                    "name": co["name"],
                    "fields": {},
                }
                for f in fields:
                    if f == "name":
                        continue
                    val = co.get(f)
                    if val is not None:
                        co_entry["fields"][f] = str(val)
                    else:
                        co_entry["fields"][f] = ""
                co_entry["company_id"] = co["id"]
                cat_entry["companies"].append(co_entry)
            categories_data.append(cat_entry)

        prompt = _build_diagram_prompt(user_prompt, categories_data,
                                       layout_style)
        response = run_cli(prompt, model, timeout=120,
                           json_schema=DIAGRAM_SCHEMA)
        duration_ms = int((time.time() - start) * 1000)

        layout = response.get("structured_output")
        if not layout:
            # Fallback: try parsing the text result as JSON
            try:
                layout = json.loads(response.get("result", "{}"))
            except (json.JSONDecodeError, TypeError):
                layout = None

        if not layout or "category_blocks" not in layout:
            write_result("diagram", job_id, {
                "status": "error",
                "error": "LLM did not return a valid diagram layout. "
                         "Try rephrasing your prompt or using a different model.",
            })
            return

        write_result("diagram", job_id, {
            "status": "complete",
            "layout": layout,
            "cost_usd": response.get("cost_usd"),
            "duration_ms": duration_ms,
        })

    except subprocess.TimeoutExpired:
        write_result("diagram", job_id, {
            "status": "error",
            "error": "Diagram generation timed out after 2 minutes. "
                     "Try fewer categories or a faster model.",
        })
    except Exception as e:
        write_result("diagram", job_id, {
            "status": "error",
            "error": str(e)[:500],
        })


@canvas_bp.route("/api/canvases/generate-diagram", methods=["POST"])
def generate_diagram():
    """Start async LLM diagram generation."""
    data = request.json or {}
    project_id = data.get("project_id")
    category_ids = data.get("category_ids", [])
    fields = data.get("fields", ["name"])
    user_prompt = data.get("prompt", "").strip()
    model = data.get("model", RESEARCH_MODEL)
    layout_style = data.get("layout_style", "grid")

    if not project_id or not category_ids:
        return jsonify({"error": "project_id and category_ids required"}), 400
    if not user_prompt:
        return jsonify({"error": "A diagram prompt is required"}), 400

    job_id = start_async_job(
        "diagram", _run_diagram_generation,
        project_id, category_ids, fields, user_prompt, model, layout_style,
    )
    return jsonify({"job_id": job_id})


@canvas_bp.route("/api/canvases/generate-diagram/<job_id>")
def poll_diagram(job_id):
    """Poll for diagram generation result."""
    return jsonify(poll_result("diagram", job_id))
