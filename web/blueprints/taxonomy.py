"""Taxonomy API: tree, history, review, quality."""
from flask import Blueprint, current_app, jsonify, request

from config import DEFAULT_MODEL
from core.git_sync import sync_to_git_async
from storage.export import export_markdown, export_json
from web.async_jobs import start_async_job, write_result, poll_result
from web.notifications import notify_sse, send_slack

taxonomy_bp = Blueprint("taxonomy", __name__)


@taxonomy_bp.route("/api/taxonomy")
def get_taxonomy():
    project_id = request.args.get("project_id", type=int)
    stats = current_app.db.get_category_stats(project_id=project_id)
    return jsonify(stats)


@taxonomy_bp.route("/api/taxonomy/history")
def taxonomy_history():
    project_id = request.args.get("project_id", type=int)
    history = current_app.db.get_taxonomy_history(project_id=project_id)
    return jsonify(history)


# --- Review ---

def _run_taxonomy_review(job_id, project_id, model, observations):
    import json
    from core.taxonomy import review_taxonomy
    from storage.db import Database
    review_db = Database()
    result = review_taxonomy(review_db, model=model, project_id=project_id,
                             observations=observations)
    write_result("review", job_id, result)


@taxonomy_bp.route("/api/taxonomy/review", methods=["POST"])
def start_taxonomy_review():
    data = request.json or {}
    project_id = data.get("project_id")
    model = data.get("model", DEFAULT_MODEL)
    observations = data.get("observations", "")

    review_id = start_async_job("review", _run_taxonomy_review,
                                project_id, model, observations)
    return jsonify({"review_id": review_id})


@taxonomy_bp.route("/api/taxonomy/review/<review_id>")
def get_taxonomy_review(review_id):
    result = poll_result("review", review_id)
    if result.get("status") == "pending":
        return jsonify(result)
    return jsonify({"status": "complete", "result": result})


@taxonomy_bp.route("/api/taxonomy/review/apply", methods=["POST"])
def apply_taxonomy_review():
    from core.taxonomy import apply_taxonomy_changes
    db = current_app.db
    data = request.json or {}
    changes = data.get("changes", [])
    project_id = data.get("project_id")
    applied = apply_taxonomy_changes(db, changes, project_id=project_id)
    export_markdown(db, project_id=project_id)
    export_json(db, project_id=project_id)
    if project_id and applied:
        desc = f"Applied {len(applied)} taxonomy changes"
        db.log_activity(project_id, "taxonomy_changed", desc, "taxonomy", None)
        notify_sse(project_id, "taxonomy_changed",
                   {"count": len(applied), "changes": applied})
        prefs = db.get_notification_prefs(project_id)
        if prefs and prefs.get("notify_taxonomy_change"):
            send_slack(project_id, f"Taxonomy updated: {desc}")
    if applied:
        sync_to_git_async(f"Taxonomy: {len(applied)} changes applied")
    return jsonify({"applied": len(applied), "changes": applied})


@taxonomy_bp.route("/api/categories/<int:category_id>")
def get_category(category_id):
    cat = current_app.db.get_category(category_id)
    if not cat:
        return jsonify({"error": "Not found"}), 404
    # Include companies in this category
    # For subcategories (has parent_id), companies link via subcategory_id
    if cat.get("parent_id"):
        companies = current_app.db.get_companies_by_subcategory(
            subcategory_id=category_id,
            project_id=cat.get("project_id"),
        )
    else:
        companies = current_app.db.get_companies(
            category_id=category_id,
            project_id=cat.get("project_id"),
        )
    cat["companies"] = companies
    return jsonify(cat)


@taxonomy_bp.route("/api/categories/<int:category_id>/color", methods=["PUT"])
def update_category_color(category_id):
    data = request.json or {}
    color = data.get("color")
    current_app.db.update_category_color(category_id, color)
    return jsonify({"status": "ok"})


@taxonomy_bp.route("/api/categories/<int:category_id>/metadata", methods=["PUT"])
def update_category_metadata(category_id):
    data = request.json or {}
    current_app.db.update_category_metadata(
        category_id,
        scope_note=data.get("scope_note"),
        inclusion_criteria=data.get("inclusion_criteria"),
        exclusion_criteria=data.get("exclusion_criteria"),
    )
    return jsonify({"status": "ok"})


@taxonomy_bp.route("/api/taxonomy/quality")
def taxonomy_quality():
    project_id = request.args.get("project_id", type=int)
    quality = current_app.db.get_taxonomy_quality(project_id)
    return jsonify(quality)
