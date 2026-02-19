"""Processing API: jobs, batches, triage, pipeline execution."""
import json

from flask import Blueprint, current_app, jsonify, request

from config import DEFAULT_MODEL, DEFAULT_WORKERS
from core.classifier import build_taxonomy_tree_string
from core.git_sync import sync_to_git_async
from core.pipeline import Pipeline
from core.url_resolver import extract_urls_from_text
from storage.db import Database
from web.async_jobs import make_job_id, run_in_thread
from web.notifications import notify_sse, send_slack

processing_bp = Blueprint("processing", __name__)


# --- Jobs / Batches ---

@processing_bp.route("/api/jobs")
def list_jobs():
    project_id = request.args.get("project_id", type=int)
    batches = current_app.db.get_recent_batches(project_id=project_id, limit=20)
    return jsonify(batches)


@processing_bp.route("/api/jobs/<batch_id>")
def get_batch(batch_id):
    return jsonify(current_app.db.get_batch_summary(batch_id))


@processing_bp.route("/api/jobs/<batch_id>/details")
def get_batch_details(batch_id):
    return jsonify(current_app.db.get_batch_details(batch_id))


# --- Retry helpers ---

def _run_retry(batch_id, urls, project_id, model, desc_prefix):
    pipe_db = Database()
    pipeline = Pipeline(pipe_db, workers=DEFAULT_WORKERS, model=model,
                        project_id=project_id)
    taxonomy_tree = build_taxonomy_tree_string(pipe_db, project_id=project_id)
    pipeline._process_sub_batch(urls, batch_id, taxonomy_tree, 1, 1)
    if project_id:
        stats = pipe_db.get_batch_summary(batch_id)
        done = stats.get("done", 0) if stats else 0
        desc = f"{desc_prefix} batch {batch_id}: processed {done} companies"
        pipe_db.log_activity(project_id, "batch_complete", desc, "batch", None)
        notify_sse(project_id, "batch_complete",
                   {"batch_id": batch_id, "count": done})


@processing_bp.route("/api/jobs/<batch_id>/retry-timeouts", methods=["POST"])
def retry_timeouts(batch_id):
    db = current_app.db
    data = request.json or {}
    model = data.get("model", DEFAULT_MODEL)
    details = db.get_batch_details(batch_id)
    timeout_jobs = [
        j for j in details.get("jobs", [])
        if j.get("status") == "error"
        and (j.get("error_message") or "").startswith("Timeout:")
    ]
    if not timeout_jobs:
        return jsonify({"error": "No timed-out jobs to retry"}), 400

    urls = [(j.get("source_url") or j["url"], j["url"]) for j in timeout_jobs]
    for j in timeout_jobs:
        db.update_job(j["id"], "pending", error_message=None)

    project_id = timeout_jobs[0].get("project_id")
    run_in_thread(_run_retry, batch_id, urls, project_id, model, "Retry")
    return jsonify({"batch_id": batch_id, "retry_count": len(timeout_jobs)})


@processing_bp.route("/api/jobs/<batch_id>/retry-errors", methods=["POST"])
def retry_all_errors(batch_id):
    db = current_app.db
    data = request.json or {}
    model = data.get("model", DEFAULT_MODEL)
    details = db.get_batch_details(batch_id)
    error_jobs = [
        j for j in details.get("jobs", [])
        if j.get("status") == "error"
    ]
    if not error_jobs:
        return jsonify({"error": "No failed jobs to retry"}), 400

    urls = [(j.get("source_url") or j["url"], j["url"]) for j in error_jobs]
    for j in error_jobs:
        db.update_job(j["id"], "pending", error_message=None)

    project_id = error_jobs[0].get("project_id")
    run_in_thread(_run_retry, batch_id, urls, project_id, model, "Retry all errors")
    return jsonify({"batch_id": batch_id, "retry_count": len(error_jobs)})


# --- Start Processing ---

def _run_pipeline(batch_id, urls, workers, model, project_id):
    pipe_db = Database()
    pipeline = Pipeline(pipe_db, workers=workers, model=model,
                        project_id=project_id)
    pipeline.run(urls, batch_id)
    if project_id:
        stats = pipe_db.get_batch_summary(batch_id)
        done = stats.get("done", 0) if stats else len(urls)
        desc = f"Batch {batch_id}: processed {done} companies"
        pipe_db.log_activity(project_id, "batch_complete", desc, "batch", None)
        notify_sse(project_id, "batch_complete",
                   {"batch_id": batch_id, "count": done})
        prefs = pipe_db.get_notification_prefs(project_id)
        if prefs and prefs.get("notify_batch_complete"):
            send_slack(project_id, desc)
    sync_to_git_async(f"Batch {batch_id}: processed {len(urls)} URLs")


@processing_bp.route("/api/process", methods=["POST"])
def start_processing():
    db = current_app.db
    data = request.json or {}
    text = data.get("text", "")
    urls = extract_urls_from_text(text)
    model = data.get("model", DEFAULT_MODEL)
    workers = min(max(int(data.get("workers", 5)), 1), 20)
    project_id = data.get("project_id")

    if not urls:
        return jsonify({"error": "No URLs found"}), 400

    batch_id = make_job_id()
    run_in_thread(_run_pipeline, batch_id, urls, workers, model, project_id)

    if project_id:
        db.log_activity(project_id, "batch_started",
                        f"Started batch {batch_id} with {len(urls)} URLs",
                        "batch", None)

    return jsonify({"batch_id": batch_id, "url_count": len(urls)})


# --- Triage ---

def _run_triage(batch_id, urls, project_id, project_keywords, project_purpose):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from core.triage import triage_single_url

    triage_db = Database()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(
                triage_single_url, url,
                project_keywords=project_keywords,
                project_purpose=project_purpose,
            ): url
            for url in urls
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as e:
                from core.triage import TriageResult
                url = futures[future]
                result = TriageResult(
                    original_url=url, resolved_url=url,
                    status="error", reason=str(e),
                    title="", meta_description="",
                    scraped_text_preview="", is_accessible=False,
                )
            triage_db.save_triage_results(
                batch_id, [result.to_dict()], project_id=project_id
            )


@processing_bp.route("/api/triage", methods=["POST"])
def start_triage():
    db = current_app.db
    data = request.json or {}
    text = data.get("text", "")
    urls = extract_urls_from_text(text)
    project_id = data.get("project_id")

    if not urls:
        return jsonify({"error": "No URLs found"}), 400

    batch_id = make_job_id()

    project_keywords = None
    project_purpose = None
    if project_id:
        project = db.get_project(project_id)
        if project:
            kw_json = project.get("market_keywords")
            if kw_json:
                try:
                    kw_list = json.loads(kw_json) if isinstance(kw_json, str) else kw_json
                    if kw_list:
                        project_keywords = kw_list
                except (json.JSONDecodeError, TypeError):
                    pass
            project_purpose = project.get("purpose")

    run_in_thread(_run_triage, batch_id, urls, project_id,
                  project_keywords, project_purpose)
    return jsonify({"batch_id": batch_id, "url_count": len(urls)})


@processing_bp.route("/api/triage/<batch_id>")
def get_triage_status(batch_id):
    return jsonify(current_app.db.get_triage_results(batch_id))


@processing_bp.route("/api/triage/<batch_id>/confirm", methods=["POST"])
def confirm_triage(batch_id):
    db = current_app.db
    actions = (request.json or {}).get("actions", [])
    for action in actions:
        db.update_triage_action(
            action["triage_id"],
            action["action"],
            action.get("replacement_url"),
            action.get("comment"),
        )
    return jsonify({"status": "ok"})


@processing_bp.route("/api/triage/<batch_id>/process", methods=["POST"])
def process_after_triage(batch_id):
    db = current_app.db
    data = request.json or {}
    model = data.get("model", DEFAULT_MODEL)
    workers = min(max(int(data.get("workers", 5)), 1), 20)
    project_id = data.get("project_id")

    confirmed = db.get_confirmed_urls(batch_id)
    if not confirmed:
        return jsonify({"error": "No confirmed URLs"}), 400

    urls = [url for _, url in confirmed]
    run_in_thread(_run_pipeline, batch_id, urls, workers, model, project_id)
    return jsonify({"batch_id": batch_id, "url_count": len(urls)})
