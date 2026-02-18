"""Flask web app for browsing and managing the taxonomy."""
import csv
import io
import json
import os
import re
import subprocess
import time
import uuid
from threading import Thread

from flask import Flask, render_template, request, jsonify, send_file

from config import (
    WEB_HOST, WEB_PORT, DATA_DIR, DEFAULT_MODEL, DEFAULT_WORKERS,
    CLAUDE_BIN, CLAUDE_COMMON_FLAGS, SESSION_SECRET,
)
from core.classifier import build_taxonomy_tree_string
from core.git_sync import sync_to_git_async
from core.pipeline import Pipeline
from core.url_resolver import extract_urls_from_text
from storage.db import Database
from storage.export import export_csv, export_json, export_markdown


def _cleanup_stale_results():
    """Remove stale async result files older than 7 days."""
    cutoff = time.time() - 86400 * 7
    prefixes = ("report_", "discover_", "similar_", "reresearch_", "review_")
    try:
        for f in DATA_DIR.iterdir():
            if f.suffix == ".json" and f.name.startswith(prefixes):
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
    except Exception:
        pass  # Non-critical; don't block startup


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    db = Database()

    # Cleanup stale result files on startup (older than 7 days)
    _cleanup_stale_results()

    # --- CSRF Protection ---
    # Write endpoints require X-CSRF-Token header matching the session secret.
    # The token is embedded in the rendered page and sent with every mutating request.

    @app.before_request
    def _csrf_check():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return  # Read-only requests are fine
        if request.path.startswith("/shared/"):
            return  # Public endpoints
        token = request.headers.get("X-CSRF-Token")
        if token != SESSION_SECRET:
            return jsonify({"error": "Invalid CSRF token"}), 403

    # --- Pages ---

    @app.route("/")
    def index():
        return render_template("index.html", csrf_token=SESSION_SECRET)

    # --- Projects API ---

    @app.route("/api/projects")
    def list_projects():
        projects = db.get_projects()
        return jsonify(projects)

    @app.route("/api/projects", methods=["POST"])
    def create_project():
        data = request.json
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Project name is required"}), 400

        purpose = data.get("purpose", "")
        outcome = data.get("outcome", "")
        description = data.get("description", "")

        # Parse seed categories (one per line)
        seed_text = data.get("seed_categories", "")
        seed_categories = [c.strip() for c in seed_text.split("\n") if c.strip()]

        # Parse example links (one per line)
        links_text = data.get("example_links", "")
        example_links = [l.strip() for l in links_text.split("\n") if l.strip()]

        # Parse market keywords (comma-separated)
        kw_text = data.get("market_keywords", "")
        market_keywords = [k.strip() for k in kw_text.split(",") if k.strip()]

        try:
            project_id = db.create_project(
                name=name,
                purpose=purpose,
                outcome=outcome,
                seed_categories=seed_categories,
                example_links=example_links,
                market_keywords=market_keywords,
                description=description,
            )
            return jsonify({"id": project_id, "status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    @app.route("/api/projects/<int:project_id>")
    def get_project(project_id):
        project = db.get_project(project_id)
        if not project:
            return jsonify({"error": "Not found"}), 404
        return jsonify(project)

    @app.route("/api/projects/<int:project_id>", methods=["POST"])
    def update_project(project_id):
        fields = request.json
        db.update_project(project_id, fields)
        return jsonify({"status": "ok"})

    # --- Companies API ---

    @app.route("/api/companies")
    def list_companies():
        project_id = request.args.get("project_id", type=int)
        category_id = request.args.get("category_id", type=int)
        search = request.args.get("search")
        starred_only = request.args.get("starred") == "1"
        needs_enrichment = request.args.get("needs_enrichment") == "1"
        sort_by = request.args.get("sort_by", "name")
        sort_dir = request.args.get("sort_dir", "asc")
        # Multi-filter params
        tags_param = request.args.get("tags")
        tags = [t.strip() for t in tags_param.split(",") if t.strip()] if tags_param else None
        geography = request.args.get("geography")
        funding_stage = request.args.get("funding_stage")
        relationship_status = request.args.get("relationship_status")

        offset = request.args.get("offset", 0, type=int)
        companies = db.get_companies(
            project_id=project_id, category_id=category_id, search=search,
            starred_only=starred_only, needs_enrichment=needs_enrichment,
            sort_by=sort_by, sort_dir=sort_dir, offset=offset,
            tags=tags, geography=geography, funding_stage=funding_stage,
            relationship_status=relationship_status,
        )
        return jsonify(companies)

    @app.route("/api/companies/<int:company_id>")
    def get_company(company_id):
        company = db.get_company(company_id)
        if not company:
            return jsonify({"error": "Not found"}), 404
        company["notes"] = db.get_notes(company_id)
        company["events"] = db.get_events(company_id)
        return jsonify(company)

    @app.route("/api/companies/<int:company_id>", methods=["POST"])
    def update_company(company_id):
        fields = request.json
        project_id = fields.pop("project_id", None)
        db.update_company(company_id, fields)
        # Re-export after edit
        export_markdown(db, project_id=project_id)
        export_json(db, project_id=project_id)
        # Activity + SSE
        company = db.get_company(company_id)
        name = company["name"] if company else f"#{company_id}"
        if project_id:
            db.log_activity(project_id, "company_updated",
                            f"Updated {name}", "company", company_id)
            notify_sse(project_id, "company_updated",
                       {"company_id": company_id, "name": name})
        return jsonify({"status": "ok"})

    @app.route("/api/companies/<int:company_id>", methods=["DELETE"])
    def delete_company(company_id):
        company = db.get_company(company_id)
        name = company["name"] if company else f"#{company_id}"
        project_id = company.get("project_id") if company else None
        db.delete_company(company_id)
        if project_id:
            db.log_activity(project_id, "company_deleted",
                            f"Deleted {name}", "company", company_id)
        return jsonify({"status": "ok"})

    @app.route("/api/companies/<int:company_id>/star", methods=["POST"])
    def toggle_star(company_id):
        new_val = db.toggle_star(company_id)
        if new_val is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"is_starred": new_val})

    @app.route("/api/companies/<int:company_id>/relationship", methods=["POST"])
    def update_relationship(company_id):
        data = request.json
        status = data.get("status")
        note = data.get("note")
        result = db.update_relationship(company_id, status, note)
        company = db.get_company(company_id)
        if company:
            db.log_activity(
                company.get("project_id", 1), "company_edited",
                f"Updated relationship for {company['name']}: {status or 'cleared'}",
                "company", company_id,
            )
        return jsonify(result)

    @app.route("/api/companies/<int:company_id>/re-research", methods=["POST"])
    def re_research_company(company_id):
        """Re-research a company with additional source URLs."""
        data = request.json
        urls = data.get("urls", [])
        model = data.get("model", DEFAULT_MODEL)

        if not urls:
            return jsonify({"error": "No URLs provided"}), 400

        company = db.get_company(company_id)
        if not company:
            return jsonify({"error": "Company not found"}), 404

        research_id = str(uuid.uuid4())[:8]

        def run_re_research():
            from core.researcher import research_company_with_sources
            re_db = Database()

            try:
                # Parse existing research
                existing = {}
                if company.get("raw_research"):
                    try:
                        existing = json.loads(company["raw_research"])
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Run re-research
                updated = research_company_with_sources(urls, existing, model=model)

                # Update company record
                re_db.update_company(company_id, {
                    "what": updated.get("what"),
                    "target": updated.get("target"),
                    "products": updated.get("products"),
                    "funding": updated.get("funding"),
                    "geography": updated.get("geography"),
                    "tam": updated.get("tam"),
                    "tags": updated.get("tags", []),
                    "confidence_score": updated.get("confidence", 0),
                    "raw_research": json.dumps(updated),
                    "employee_range": updated.get("employee_range"),
                    "founded_year": updated.get("founded_year"),
                    "funding_stage": updated.get("funding_stage"),
                    "total_funding_usd": updated.get("total_funding_usd"),
                    "hq_city": updated.get("hq_city"),
                    "hq_country": updated.get("hq_country"),
                    "linkedin_url": updated.get("linkedin_url"),
                })

                # Save new sources
                for url in urls:
                    re_db.add_company_source(company_id, url, "re-research")

                # Write result file for polling
                result_path = DATA_DIR / f"reresearch_{research_id}.json"
                result_path.write_text(json.dumps({"status": "complete", "updated": updated}))

            except Exception as e:
                result_path = DATA_DIR / f"reresearch_{research_id}.json"
                result_path.write_text(json.dumps({"status": "error", "error": str(e)}))

        thread = Thread(target=run_re_research, daemon=True)
        thread.start()

        return jsonify({"research_id": research_id})

    @app.route("/api/re-research/<research_id>")
    def get_re_research_status(research_id):
        """Poll for re-research results."""
        result_path = DATA_DIR / f"reresearch_{research_id}.json"
        if not result_path.exists():
            return jsonify({"status": "pending"})
        result = json.loads(result_path.read_text())
        return jsonify(result)

    # --- Taxonomy API ---

    @app.route("/api/taxonomy")
    def get_taxonomy():
        project_id = request.args.get("project_id", type=int)
        stats = db.get_category_stats(project_id=project_id)
        return jsonify(stats)

    @app.route("/api/taxonomy/history")
    def taxonomy_history():
        project_id = request.args.get("project_id", type=int)
        history = db.get_taxonomy_history(project_id=project_id)
        return jsonify(history)

    @app.route("/api/taxonomy/review", methods=["POST"])
    def start_taxonomy_review():
        """Start a full taxonomy review via Claude CLI (runs in background)."""
        review_id = str(uuid.uuid4())[:8]
        data = request.json or {}
        project_id = data.get("project_id")
        model = data.get("model", DEFAULT_MODEL)
        observations = data.get("observations", "")

        def run_review():
            from core.taxonomy import review_taxonomy
            review_db = Database()
            result = review_taxonomy(review_db, model=model, project_id=project_id, observations=observations)
            review_path = DATA_DIR / f"review_{review_id}.json"
            review_path.write_text(json.dumps(result))

        thread = Thread(target=run_review, daemon=True)
        thread.start()

        return jsonify({"review_id": review_id})

    @app.route("/api/taxonomy/review/<review_id>")
    def get_taxonomy_review(review_id):
        """Poll for taxonomy review results."""
        review_path = DATA_DIR / f"review_{review_id}.json"
        if not review_path.exists():
            return jsonify({"status": "pending"})
        result = json.loads(review_path.read_text())
        return jsonify({"status": "complete", "result": result})

    @app.route("/api/taxonomy/review/apply", methods=["POST"])
    def apply_taxonomy_review():
        """Apply selected taxonomy changes from a review."""
        from core.taxonomy import apply_taxonomy_changes
        data = request.json
        changes = data.get("changes", [])
        project_id = data.get("project_id")
        applied = apply_taxonomy_changes(db, changes, project_id=project_id)
        # Re-export after taxonomy changes
        export_markdown(db, project_id=project_id)
        export_json(db, project_id=project_id)
        # Activity + SSE + Slack
        if project_id and applied:
            desc = f"Applied {len(applied)} taxonomy changes"
            db.log_activity(project_id, "taxonomy_changed", desc,
                            "taxonomy", None)
            notify_sse(project_id, "taxonomy_changed",
                       {"count": len(applied), "changes": applied})
            prefs = db.get_notification_prefs(project_id)
            if prefs and prefs.get("notify_taxonomy_change"):
                send_slack(project_id, f"Taxonomy updated: {desc}")
        if applied:
            sync_to_git_async(f"Taxonomy: {len(applied)} changes applied")
        return jsonify({"applied": len(applied), "changes": applied})

    # --- Jobs / Processing API ---

    @app.route("/api/jobs")
    def list_jobs():
        project_id = request.args.get("project_id", type=int)
        batches = db.get_recent_batches(project_id=project_id, limit=20)
        return jsonify(batches)

    @app.route("/api/jobs/<batch_id>")
    def get_batch(batch_id):
        summary = db.get_batch_summary(batch_id)
        return jsonify(summary)

    @app.route("/api/jobs/<batch_id>/details")
    def get_batch_details(batch_id):
        details = db.get_batch_details(batch_id)
        return jsonify(details)

    @app.route("/api/jobs/<batch_id>/retry-timeouts", methods=["POST"])
    def retry_timeouts(batch_id):
        """Retry only timed-out jobs in a batch."""
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
        # Reset these jobs to pending
        for j in timeout_jobs:
            db.update_job(j["id"], "pending", error_message=None)

        project_id = timeout_jobs[0].get("project_id")

        def run_retry():
            pipe_db = Database()
            pipeline = Pipeline(pipe_db, workers=DEFAULT_WORKERS, model=model,
                                project_id=project_id)
            taxonomy_tree = build_taxonomy_tree_string(pipe_db, project_id=project_id)
            pipeline._process_sub_batch(urls, batch_id, taxonomy_tree, 1, 1)
            if project_id:
                stats = pipe_db.get_batch_summary(batch_id)
                done = stats.get("done", 0) if stats else 0
                desc = f"Retry batch {batch_id}: processed {done} companies"
                pipe_db.log_activity(project_id, "batch_complete",
                                     desc, "batch", None)
                notify_sse(project_id, "batch_complete",
                           {"batch_id": batch_id, "count": done})

        thread = Thread(target=run_retry, daemon=True)
        thread.start()

        return jsonify({"batch_id": batch_id, "retry_count": len(timeout_jobs)})

    @app.route("/api/jobs/<batch_id>/retry-errors", methods=["POST"])
    def retry_all_errors(batch_id):
        """Retry ALL failed jobs in a batch (timeouts + errors)."""
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
        # Reset these jobs to pending
        for j in error_jobs:
            db.update_job(j["id"], "pending", error_message=None)

        project_id = error_jobs[0].get("project_id")

        def run_retry():
            pipe_db = Database()
            pipeline = Pipeline(pipe_db, workers=DEFAULT_WORKERS, model=model,
                                project_id=project_id)
            taxonomy_tree = build_taxonomy_tree_string(pipe_db, project_id=project_id)
            pipeline._process_sub_batch(urls, batch_id, taxonomy_tree, 1, 1)
            if project_id:
                stats = pipe_db.get_batch_summary(batch_id)
                done = stats.get("done", 0) if stats else 0
                desc = f"Retry all errors batch {batch_id}: processed {done} companies"
                pipe_db.log_activity(project_id, "batch_complete",
                                     desc, "batch", None)
                notify_sse(project_id, "batch_complete",
                           {"batch_id": batch_id, "count": done})

        thread = Thread(target=run_retry, daemon=True)
        thread.start()

        return jsonify({"batch_id": batch_id, "retry_count": len(error_jobs)})

    @app.route("/api/process", methods=["POST"])
    def start_processing():
        data = request.json
        text = data.get("text", "")
        urls = extract_urls_from_text(text)
        model = data.get("model", DEFAULT_MODEL)
        workers = data.get("workers", 5)
        project_id = data.get("project_id")

        if not urls:
            return jsonify({"error": "No URLs found"}), 400

        batch_id = str(uuid.uuid4())[:8]

        def run_pipeline():
            pipe_db = Database()
            pipeline = Pipeline(pipe_db, workers=workers, model=model,
                                project_id=project_id)
            pipeline.run(urls, batch_id)
            # Post-completion: activity + SSE + Slack
            if project_id:
                stats = pipe_db.get_batch_summary(batch_id)
                done = stats.get("done", 0) if stats else len(urls)
                desc = f"Batch {batch_id}: processed {done} companies"
                pipe_db.log_activity(project_id, "batch_complete",
                                     desc, "batch", None)
                notify_sse(project_id, "batch_complete",
                           {"batch_id": batch_id, "count": done})
                prefs = pipe_db.get_notification_prefs(project_id)
                if prefs and prefs.get("notify_batch_complete"):
                    send_slack(project_id, desc)
            sync_to_git_async(f"Batch {batch_id}: processed {len(urls)} URLs")

        thread = Thread(target=run_pipeline, daemon=True)
        thread.start()

        if project_id:
            db.log_activity(project_id, "batch_started",
                            f"Started batch {batch_id} with {len(urls)} URLs",
                            "batch", None)

        return jsonify({"batch_id": batch_id, "url_count": len(urls)})

    # --- Triage API ---

    @app.route("/api/triage", methods=["POST"])
    def start_triage():
        """Phase 1: Triage URLs before processing."""
        data = request.json
        text = data.get("text", "")
        urls = extract_urls_from_text(text)
        project_id = data.get("project_id")

        if not urls:
            return jsonify({"error": "No URLs found"}), 400

        batch_id = str(uuid.uuid4())[:8]

        # Load project-specific keywords for relevance checking
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

        def run_triage():
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

        thread = Thread(target=run_triage, daemon=True)
        thread.start()

        return jsonify({"batch_id": batch_id, "url_count": len(urls)})

    @app.route("/api/triage/<batch_id>")
    def get_triage_status(batch_id):
        """Get triage results for a batch."""
        results = db.get_triage_results(batch_id)
        return jsonify(results)

    @app.route("/api/triage/<batch_id>/confirm", methods=["POST"])
    def confirm_triage(batch_id):
        """User confirms triage results with actions (skip/replace/include)."""
        actions = request.json.get("actions", [])
        for action in actions:
            db.update_triage_action(
                action["triage_id"],
                action["action"],
                action.get("replacement_url"),
                action.get("comment"),
            )
        return jsonify({"status": "ok"})

    @app.route("/api/triage/<batch_id>/process", methods=["POST"])
    def process_after_triage(batch_id):
        """Phase 2: Start processing confirmed URLs from triage."""
        data = request.json or {}
        model = data.get("model", DEFAULT_MODEL)
        workers = data.get("workers", 5)
        project_id = data.get("project_id")

        confirmed = db.get_confirmed_urls(batch_id)
        if not confirmed:
            return jsonify({"error": "No confirmed URLs"}), 400

        urls = [url for _, url in confirmed]

        def run_pipeline():
            pipe_db = Database()
            pipeline = Pipeline(pipe_db, workers=workers, model=model,
                                project_id=project_id)
            pipeline.run(urls, batch_id)
            if project_id:
                stats = pipe_db.get_batch_summary(batch_id)
                done = stats.get("done", 0) if stats else len(urls)
                desc = f"Batch {batch_id}: processed {done} companies"
                pipe_db.log_activity(project_id, "batch_complete",
                                     desc, "batch", None)
                notify_sse(project_id, "batch_complete",
                           {"batch_id": batch_id, "count": done})
                prefs = pipe_db.get_notification_prefs(project_id)
                if prefs and prefs.get("notify_batch_complete"):
                    send_slack(project_id, desc)

        thread = Thread(target=run_pipeline, daemon=True)
        thread.start()

        return jsonify({"batch_id": batch_id, "url_count": len(urls)})

    # --- Notes API ---

    @app.route("/api/companies/<int:company_id>/notes")
    def list_notes(company_id):
        notes = db.get_notes(company_id)
        return jsonify(notes)

    @app.route("/api/companies/<int:company_id>/notes", methods=["POST"])
    def add_note(company_id):
        content = request.json.get("content", "").strip()
        if not content:
            return jsonify({"error": "Content is required"}), 400
        note_id = db.add_note(company_id, content)
        company = db.get_company(company_id)
        if company and company.get("project_id"):
            db.log_activity(company["project_id"], "note_added",
                            f"Added note to {company['name']}",
                            "company", company_id)
        return jsonify({"id": note_id, "status": "ok"})

    @app.route("/api/notes/<int:note_id>", methods=["POST"])
    def update_note(note_id):
        content = request.json.get("content", "").strip()
        if not content:
            return jsonify({"error": "Content is required"}), 400
        db.update_note(note_id, content)
        return jsonify({"status": "ok"})

    @app.route("/api/notes/<int:note_id>", methods=["DELETE"])
    def delete_note(note_id):
        db.delete_note(note_id)
        return jsonify({"status": "ok"})

    @app.route("/api/notes/<int:note_id>/pin", methods=["POST"])
    def pin_note(note_id):
        new_val = db.toggle_pin_note(note_id)
        return jsonify({"is_pinned": new_val})

    # --- Version History API ---

    @app.route("/api/companies/<int:company_id>/versions")
    def list_versions(company_id):
        versions = db.get_versions(company_id)
        return jsonify(versions)

    @app.route("/api/versions/<int:version_id>/restore", methods=["POST"])
    def restore_version(version_id):
        company_id = db.restore_version(version_id)
        if not company_id:
            return jsonify({"error": "Version not found"}), 404
        company = db.get_company(company_id)
        if company and company.get("project_id"):
            db.log_activity(company["project_id"], "version_restored",
                            f"Restored {company['name']} to version #{version_id}",
                            "company", company_id)
        return jsonify({"status": "ok", "company_id": company_id})

    # --- Trash API ---

    @app.route("/api/trash")
    def list_trash():
        project_id = request.args.get("project_id", type=int)
        items = db.get_trash(project_id=project_id)
        return jsonify(items)

    @app.route("/api/companies/<int:company_id>/restore", methods=["POST"])
    def restore_company(company_id):
        db.restore_company(company_id)
        company = db.get_company(company_id)
        name = company["name"] if company else f"#{company_id}"
        project_id = company.get("project_id") if company else None
        if project_id:
            db.log_activity(project_id, "company_restored",
                            f"Restored {name} from trash", "company", company_id)
        return jsonify({"status": "ok"})

    @app.route("/api/companies/<int:company_id>/permanent-delete", methods=["DELETE"])
    def permanent_delete(company_id):
        db.permanently_delete(company_id)
        return jsonify({"status": "ok"})

    # --- Events / Lifecycle API ---

    @app.route("/api/companies/<int:company_id>/events")
    def list_events(company_id):
        events = db.get_events(company_id)
        return jsonify(events)

    @app.route("/api/companies/<int:company_id>/events", methods=["POST"])
    def add_event(company_id):
        data = request.json
        event_type = data.get("event_type", "").strip()
        description = data.get("description", "")
        event_date = data.get("event_date")
        if not event_type:
            return jsonify({"error": "event_type is required"}), 400
        db.add_event(company_id, event_type, description, event_date)
        return jsonify({"status": "ok"})

    @app.route("/api/events/<int:event_id>", methods=["DELETE"])
    def delete_event(event_id):
        db.delete_event(event_id)
        return jsonify({"status": "ok"})

    # --- Duplicates API ---

    @app.route("/api/duplicates")
    def find_duplicates():
        project_id = request.args.get("project_id", type=int)
        duplicates = db.find_duplicates(project_id=project_id)
        return jsonify(duplicates)

    # --- Merge API ---

    @app.route("/api/companies/merge", methods=["POST"])
    def merge_companies():
        data = request.json
        target_id = data.get("target_id")
        source_id = data.get("source_id")
        if not target_id or not source_id:
            return jsonify({"error": "target_id and source_id are required"}), 400
        target = db.get_company(target_id)
        source = db.get_company(source_id)
        db.merge_companies(target_id, source_id)
        project_id = (target or {}).get("project_id")
        if project_id:
            t_name = target["name"] if target else f"#{target_id}"
            s_name = source["name"] if source else f"#{source_id}"
            db.log_activity(project_id, "companies_merged",
                            f"Merged {s_name} into {t_name}", "company", target_id)
        return jsonify({"status": "ok"})

    # --- CSV Import API ---

    @app.route("/api/import/csv", methods=["POST"])
    def import_csv():
        project_id = request.form.get("project_id", type=int)
        if not project_id:
            return jsonify({"error": "project_id is required"}), 400
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        content = file.stream.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        imported = db.import_companies_from_rows(rows, project_id)
        db.log_activity(project_id, "csv_imported",
                        f"Imported {imported} companies from CSV ({len(rows)} rows)",
                        "project", project_id)
        notify_sse(project_id, "company_added",
                   {"count": imported, "source": "csv_import"})
        sync_to_git_async(f"CSV import: {imported} companies")
        return jsonify({"imported": imported, "total_rows": len(rows)})

    # --- Tags API ---

    @app.route("/api/tags")
    def list_tags():
        project_id = request.args.get("project_id", type=int)
        tags = db.get_all_tags(project_id=project_id)
        return jsonify(tags)

    @app.route("/api/tags/rename", methods=["POST"])
    def rename_tag():
        data = request.json
        old_tag = data.get("old_tag", "").strip()
        new_tag = data.get("new_tag", "").strip()
        project_id = data.get("project_id")
        if not old_tag or not new_tag:
            return jsonify({"error": "Both old_tag and new_tag are required"}), 400
        updated = db.rename_tag(old_tag, new_tag, project_id=project_id)
        if project_id:
            db.log_activity(project_id, "tag_renamed",
                            f"Renamed tag '{old_tag}' to '{new_tag}' ({updated} companies)",
                            "tag", None)
        return jsonify({"updated": updated})

    @app.route("/api/tags/merge", methods=["POST"])
    def merge_tags():
        data = request.json
        source = data.get("source_tag", "").strip()
        target = data.get("target_tag", "").strip()
        project_id = data.get("project_id")
        if not source or not target:
            return jsonify({"error": "Both source_tag and target_tag are required"}), 400
        updated = db.merge_tags(source, target, project_id=project_id)
        if project_id:
            db.log_activity(project_id, "tag_merged",
                            f"Merged tag '{source}' into '{target}' ({updated} companies)",
                            "tag", None)
        return jsonify({"updated": updated})

    @app.route("/api/tags/delete", methods=["POST"])
    def delete_tag():
        data = request.json
        tag_name = data.get("tag", "").strip()
        project_id = data.get("project_id")
        if not tag_name:
            return jsonify({"error": "Tag name required"}), 400
        updated = db.delete_tag(tag_name, project_id=project_id)
        return jsonify({"updated": updated})

    # --- Saved Views API ---

    @app.route("/api/views")
    def list_views():
        project_id = request.args.get("project_id", type=int)
        if not project_id:
            return jsonify([])
        views = db.get_saved_views(project_id)
        return jsonify(views)

    @app.route("/api/views", methods=["POST"])
    def save_view():
        data = request.json
        project_id = data.get("project_id")
        name = data.get("name", "").strip()
        filters = data.get("filters", {})
        if not project_id or not name:
            return jsonify({"error": "project_id and name are required"}), 400
        db.save_view(project_id, name, filters)
        return jsonify({"status": "ok"})

    @app.route("/api/views/<int:view_id>", methods=["DELETE"])
    def delete_view(view_id):
        db.delete_saved_view(view_id)
        return jsonify({"status": "ok"})

    # --- Map Layouts API ---

    @app.route("/api/map-layouts")
    def list_map_layouts():
        project_id = request.args.get("project_id", type=int)
        if not project_id:
            return jsonify([])
        return jsonify(db.get_map_layouts(project_id))

    @app.route("/api/map-layouts", methods=["POST"])
    def save_map_layout():
        data = request.json
        project_id = data.get("project_id")
        name = data.get("name", "Default")
        layout_data = data.get("layout_data", {})
        if not project_id:
            return jsonify({"error": "project_id required"}), 400
        db.save_map_layout(project_id, name, layout_data)
        return jsonify({"status": "ok"})

    # --- Compare API ---

    @app.route("/api/companies/compare")
    def compare_companies():
        ids = request.args.get("ids", "")
        company_ids = [int(x) for x in ids.split(",") if x.strip()]
        companies = []
        for cid in company_ids:
            c = db.get_company(cid)
            if c:
                companies.append(c)
        return jsonify(companies)

    # --- Filter Metadata API ---

    @app.route("/api/filters/options")
    def filter_options():
        """Get available filter values for dropdowns."""
        project_id = request.args.get("project_id", type=int)
        return jsonify({
            "tags": db.get_all_tags(project_id=project_id),
            "geographies": db.get_distinct_geographies(project_id=project_id),
            "funding_stages": db.get_distinct_funding_stages(project_id=project_id),
        })

    # --- AI Features API ---

    def _sanitize_for_prompt(text, max_length=500):
        """Sanitize user input before interpolating into AI prompts.
        Strips prompt injection markers and truncates to prevent abuse."""
        if not text:
            return ""
        # Remove common prompt injection patterns
        sanitized = text.replace("```", "").replace("---", "")
        # Remove instruction-like patterns that could override the system prompt
        for marker in ["SYSTEM:", "ASSISTANT:", "HUMAN:", "USER:", "INSTRUCTION:",
                       "IGNORE PREVIOUS", "ignore above", "disregard"]:
            sanitized = sanitized.replace(marker, "").replace(marker.lower(), "")
        return sanitized[:max_length].strip()

    @app.route("/api/ai/discover", methods=["POST"])
    def ai_discover():
        """Discover companies by describing a market segment."""
        data = request.json
        query = data.get("query", "").strip()
        project_id = data.get("project_id")
        model = data.get("model", DEFAULT_MODEL)
        if not query:
            return jsonify({"error": "Query is required"}), 400

        discover_id = str(uuid.uuid4())[:8]

        def run_discover():
            safe_query = _sanitize_for_prompt(query)

            prompt = f"""You are a market research assistant. The user is looking for companies in this space:

"{safe_query}"

Search the web and return a JSON array of 5-10 company objects, each with:
- "name": company name
- "url": company website URL (must be real, working URLs)
- "description": 1-sentence description of what they do

Only return the JSON array, nothing else. Focus on real, existing companies."""

            try:
                result = subprocess.run(
                    [CLAUDE_BIN, "-p", prompt, "--output-format", "json",
                     "--dangerously-skip-permissions",
                     "--model", model],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    stderr = (result.stderr or "").strip()[:200]
                    result_data = {"status": "error", "error": f"Discovery failed: {stderr or 'unknown error'}"}
                else:
                    output = result.stdout.strip()
                    parsed = json.loads(output)
                    text = parsed.get("result", "") if isinstance(parsed, dict) else output
                    match = re.search(r'\[.*\]', text, re.DOTALL)
                    if match:
                        companies = json.loads(match.group())
                        result_data = {"status": "complete", "companies": companies}
                    else:
                        result_data = {"status": "complete", "companies": [], "raw": text}
            except subprocess.TimeoutExpired:
                result_data = {"status": "error", "error": "Discovery timed out. Try a simpler query."}
            except json.JSONDecodeError:
                result_data = {"status": "error", "error": "Failed to parse AI response."}
            except Exception as e:
                result_data = {"status": "error", "error": str(e)[:200]}

            result_path = DATA_DIR / f"discover_{discover_id}.json"
            result_path.write_text(json.dumps(result_data))

        thread = Thread(target=run_discover, daemon=True)
        thread.start()
        return jsonify({"discover_id": discover_id})

    @app.route("/api/ai/discover/<discover_id>")
    def get_discover_status(discover_id):
        result_path = DATA_DIR / f"discover_{discover_id}.json"
        if not result_path.exists():
            return jsonify({"status": "pending"})
        return jsonify(json.loads(result_path.read_text()))

    @app.route("/api/ai/find-similar", methods=["POST"])
    def ai_find_similar():
        """Find companies similar to a given company."""
        data = request.json
        company_id = data.get("company_id")
        model = data.get("model", DEFAULT_MODEL)
        if not company_id:
            return jsonify({"error": "company_id is required"}), 400

        company = db.get_company(company_id)
        if not company:
            return jsonify({"error": "Company not found"}), 404

        similar_id = str(uuid.uuid4())[:8]

        def run_similar():
            safe_name = _sanitize_for_prompt(company['name'], 100)
            safe_what = _sanitize_for_prompt(company.get('what', 'N/A'), 200)
            safe_target = _sanitize_for_prompt(company.get('target', 'N/A'), 200)

            prompt = f"""You are a market research assistant. Given this company:

Name: {safe_name}
URL: {company['url']}
What they do: {safe_what}
Target: {safe_target}
Category: {company.get('category_name', 'N/A')}

Search the web and find 5 similar or competing companies. Return a JSON array with:
- "name": company name
- "url": company website URL
- "description": 1-sentence description
- "similarity": brief explanation of why it's similar

Only return the JSON array, nothing else."""

            try:
                result = subprocess.run(
                    [CLAUDE_BIN, "-p", prompt, "--output-format", "json",
                     "--dangerously-skip-permissions",
                     "--model", model],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    stderr = (result.stderr or "").strip()[:200]
                    result_data = {"status": "error", "error": f"Search failed: {stderr or 'unknown error'}"}
                else:
                    output = result.stdout.strip()
                    parsed = json.loads(output)
                    text = parsed.get("result", "") if isinstance(parsed, dict) else output
                    match = re.search(r'\[.*\]', text, re.DOTALL)
                    if match:
                        companies = json.loads(match.group())
                        result_data = {"status": "complete", "companies": companies}
                    else:
                        result_data = {"status": "complete", "companies": [], "raw": text}
            except subprocess.TimeoutExpired:
                result_data = {"status": "error", "error": "Search timed out. Please try again."}
            except json.JSONDecodeError:
                result_data = {"status": "error", "error": "Failed to parse AI response."}
            except Exception as e:
                result_data = {"status": "error", "error": str(e)[:200]}

            result_path = DATA_DIR / f"similar_{similar_id}.json"
            result_path.write_text(json.dumps(result_data))

        thread = Thread(target=run_similar, daemon=True)
        thread.start()
        return jsonify({"similar_id": similar_id})

    @app.route("/api/ai/find-similar/<similar_id>")
    def get_similar_status(similar_id):
        result_path = DATA_DIR / f"similar_{similar_id}.json"
        if not result_path.exists():
            return jsonify({"status": "pending"})
        return jsonify(json.loads(result_path.read_text()))

    @app.route("/api/ai/chat", methods=["POST"])
    def ai_chat():
        """Ask questions about your taxonomy data."""
        data = request.json
        question = data.get("question", "").strip()
        project_id = data.get("project_id")
        model = data.get("model", "claude-haiku-4-5-20251001")
        if not question:
            return jsonify({"error": "Question is required"}), 400

        # Build context from current data
        companies = db.get_companies(project_id=project_id, limit=200)
        stats = db.get_stats(project_id=project_id)
        categories = db.get_category_stats(project_id=project_id)

        context = f"""You have access to a taxonomy database with {stats['total_companies']} companies across {stats['total_categories']} categories.

Categories: {', '.join(c['name'] + f' ({c["company_count"]})' for c in categories if not c.get('parent_id'))}

Companies (name | category | what they do | tags):
"""
        for c in companies[:100]:
            tags = ', '.join(c.get('tags', []))
            context += f"- {c['name']} | {c.get('category_name', 'N/A')} | {c.get('what', 'N/A')[:80]} | {tags}\n"

        prompt = f"""{context}

Answer this question using ONLY the data above. Be extremely brief and data-focused.
Rules:
- Use bullet points, not paragraphs
- Include specific company names, numbers, and categories
- Maximum 5-8 bullet points
- No preamble or pleasantries

Question: {_sanitize_for_prompt(question)}"""

        try:
            result = subprocess.run(
                [CLAUDE_BIN, "-p", prompt, "--output-format", "json",
                 "--dangerously-skip-permissions", "--model", model],
                capture_output=True, text=True, timeout=60,
            )

            if result.returncode != 0:
                stderr = (result.stderr or "").strip()[:200]
                return jsonify({"error": f"Chat failed: {stderr or 'unknown error'}"}), 500

            output = result.stdout.strip()
            parsed = json.loads(output)
            if parsed.get("is_error"):
                return jsonify({"error": parsed.get("result", "Unknown error")[:300]}), 500
            answer = parsed.get("result", "")
            return jsonify({"answer": answer})
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Request timed out. Try a simpler question."}), 500
        except json.JSONDecodeError:
            return jsonify({"error": "Failed to parse AI response."}), 500
        except Exception as e:
            return jsonify({"error": str(e)[:200]}), 500

    @app.route("/api/ai/market-report", methods=["POST"])
    def ai_market_report():
        """Generate an analyst-grade market report for a category."""
        from config import RESEARCH_MODEL
        data = request.json
        category_name = data.get("category_name", "").strip()
        project_id = data.get("project_id")
        model = data.get("model", RESEARCH_MODEL)
        if not category_name:
            return jsonify({"error": "category_name is required"}), 400

        report_id = str(uuid.uuid4())[:8]

        def run_report():
            report_db = Database()
            companies = report_db.get_companies(project_id=project_id, limit=200)
            cat_companies = [c for c in companies if c.get('category_name') == category_name]

            company_summaries = "\n".join([
                f"### {c['name']}\n"
                f"- URL: {c.get('url','')}\n"
                f"- Description: {c.get('what','N/A')}\n"
                f"- Target Market: {c.get('target','N/A')}\n"
                f"- Products: {c.get('products','N/A')}\n"
                f"- Funding: {c.get('funding','N/A')}\n"
                f"- Funding Stage: {c.get('funding_stage','N/A')}\n"
                f"- Total Raised: {c.get('total_funding_usd','N/A')}\n"
                f"- Geography: {c.get('geography','N/A')}\n"
                f"- HQ: {c.get('hq_city','')}, {c.get('hq_country','')}\n"
                f"- Employees: {c.get('employee_range','N/A')}\n"
                f"- Founded: {c.get('founded_year','N/A')}\n"
                f"- TAM: {c.get('tam','N/A')}\n"
                f"- Tags: {', '.join(c.get('tags',[]))}\n"
                for c in cat_companies
            ])

            prompt = f"""You are a senior market analyst at a tier-1 research firm (similar to Gartner, IDC, or Mintel). Generate a rigorous, data-driven market intelligence briefing for the "{category_name}" category.

COMPANY DATA (from our proprietary database):
{company_summaries}

INSTRUCTIONS:
1. First, analyze the company data provided above
2. Then, use WebSearch to validate and enrich your findings:
   - Search for recent market reports, funding announcements, or industry trends related to this category
   - Search for market size data (TAM/SAM/SOM) for this sector
   - Search for any recent news about the key companies listed
3. Synthesize everything into a structured analyst briefing

REQUIRED FORMAT (Markdown):

# {category_name}: Market Intelligence Briefing

## Executive Summary
[2-3 sentence overview. Include estimated market size if found via search.]

## Market Landscape
[Include a mermaid quadrant chart showing competitive positioning]

```mermaid
quadrantChart
    title Competitive Positioning
    x-axis Low Market Focus --> High Market Focus
    y-axis Early Stage --> Mature
    [Position companies based on your analysis]
```

## Key Players & Competitive Analysis
[For each significant company: what they do, differentiation, funding stage, and competitive position. Use a markdown table.]

| Company | Focus | Funding Stage | Differentiation |
|---------|-------|--------------|-----------------|
...

## Market Dynamics
### Tailwinds
[3-4 factors driving growth, with citations]

### Headwinds
[2-3 challenges or risks, with citations]

## Funding & Investment Patterns
[Aggregate funding analysis. Include total capital deployed, average round size, most active investors if findable]

## Outlook & Implications
[Forward-looking analysis with points AND counterpoints. What does this mean for insurers/investors/operators?]

## Sources & Citations
[List all web sources consulted with URLs]

CONSTRAINTS:
- Total length: 1500-2000 words (approximately 2 A4 pages)
- Every factual claim from web search must include a citation [Source Name](URL)
- Be specific: use company names, dollar amounts, dates
- Maintain analytical objectivity - present both bull and bear cases
- If you cannot verify a claim via web search, explicitly note it as "per company self-reporting"
"""

            try:
                result = subprocess.run(
                    [CLAUDE_BIN, "-p", prompt, "--output-format", "json",
                     "--dangerously-skip-permissions",
                     "--tools", "WebSearch,WebFetch",
                     "--model", model],
                    capture_output=True, text=True, timeout=300,
                )

                if result.returncode != 0:
                    stderr = (result.stderr or "").strip()[:300]
                    result_data = {"status": "error", "error": f"Report generation failed: {stderr or 'unknown error'}"}
                else:
                    output = result.stdout.strip()
                    parsed = json.loads(output)
                    if parsed.get("is_error"):
                        result_data = {"status": "error", "error": parsed.get("result", "Unknown error")[:500]}
                    else:
                        report = parsed.get("result", "")
                        result_data = {"status": "complete", "report": report, "category": category_name, "company_count": len(cat_companies)}
            except subprocess.TimeoutExpired:
                result_data = {"status": "error", "error": "Report generation timed out after 5 minutes. Try a smaller category or a faster model."}
            except json.JSONDecodeError:
                result_data = {"status": "error", "error": "Failed to parse AI response. Please try again."}
            except Exception as e:
                result_data = {"status": "error", "error": str(e)[:300]}

            result_path = DATA_DIR / f"report_{report_id}.json"
            result_path.write_text(json.dumps(result_data))

            # Persist completed reports in DB
            if result_data.get("status") == "complete":
                report_db.save_report(
                    project_id=project_id or 1, report_id=report_id,
                    category_name=category_name,
                    company_count=len(cat_companies),
                    model=model,
                    markdown_content=result_data.get("report", ""),
                )
            elif result_data.get("status") == "error":
                report_db.save_report(
                    project_id=project_id or 1, report_id=report_id,
                    category_name=category_name,
                    company_count=len(cat_companies),
                    model=model, markdown_content=None,
                    status="error",
                    error_message=result_data.get("error", ""),
                )
            sync_to_git_async(f"Report generated: {category_name}")

        thread = Thread(target=run_report, daemon=True)
        thread.start()
        return jsonify({"report_id": report_id})

    @app.route("/api/ai/market-report/<report_id>")
    def get_market_report(report_id):
        result_path = DATA_DIR / f"report_{report_id}.json"
        if not result_path.exists():
            return jsonify({"status": "pending"})
        return jsonify(json.loads(result_path.read_text()))

    # --- Reports API ---

    @app.route("/api/reports")
    def list_reports():
        project_id = request.args.get("project_id", type=int)
        reports = db.get_reports(project_id=project_id)
        # Don't send full markdown in list view
        for r in reports:
            r.pop("markdown_content", None)
        return jsonify(reports)

    @app.route("/api/reports/<report_id>")
    def get_report(report_id):
        report = db.get_report(report_id)
        if not report:
            return jsonify({"error": "Not found"}), 404
        return jsonify(report)

    @app.route("/api/reports/<report_id>", methods=["DELETE"])
    def delete_report(report_id):
        db.delete_report(report_id)
        # Also clean up the data file if it exists
        result_path = DATA_DIR / f"report_{report_id}.json"
        result_path.unlink(missing_ok=True)
        return jsonify({"status": "ok"})

    @app.route("/api/reports/<report_id>/export/md")
    def export_report_md(report_id):
        report = db.get_report(report_id)
        if not report or not report.get("markdown_content"):
            return jsonify({"error": "Report not found"}), 404
        md = report["markdown_content"]
        buf = io.BytesIO(md.encode("utf-8"))
        buf.seek(0)
        filename = f"report_{report['category_name'].replace(' ', '_')}_{report_id}.md"
        return send_file(buf, as_attachment=True, download_name=filename,
                         mimetype="text/markdown")

    # --- Stats ---

    @app.route("/api/stats")
    def get_stats():
        project_id = request.args.get("project_id", type=int)
        stats = db.get_stats(project_id=project_id)
        return jsonify(stats)

    # --- Export ---

    @app.route("/api/export/json")
    def download_json():
        project_id = request.args.get("project_id", type=int)
        path = export_json(db, project_id=project_id)
        return send_file(path, as_attachment=True, download_name="taxonomy_data.json")

    @app.route("/api/export/md")
    def download_md():
        project_id = request.args.get("project_id", type=int)
        path = export_markdown(db, project_id=project_id)
        return send_file(path, as_attachment=True, download_name="taxonomy_master.md")

    @app.route("/api/export/csv")
    def download_csv():
        project_id = request.args.get("project_id", type=int)
        path = export_csv(db, project_id=project_id)
        return send_file(path, as_attachment=True, download_name="taxonomy_export.csv")

    # --- SSE (Server-Sent Events) ---

    import queue
    sse_clients = {}  # project_id -> list of queues

    def notify_sse(project_id, event_type, data):
        """Push an event to all SSE clients for a project."""
        if project_id in sse_clients:
            msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            dead = []
            for q in sse_clients[project_id]:
                try:
                    q.put_nowait(msg)
                except Exception:
                    dead.append(q)
            # Cleanup dead client queues to prevent memory leak
            for q in dead:
                try:
                    sse_clients[project_id].remove(q)
                except ValueError:
                    pass
            if not sse_clients[project_id]:
                del sse_clients[project_id]

    def _is_valid_slack_webhook(url):
        """Validate that a URL is a legitimate Slack webhook to prevent SSRF."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            return (
                parsed.scheme == "https"
                and parsed.hostname == "hooks.slack.com"
                and parsed.path.startswith("/services/")
            )
        except Exception:
            return False

    def send_slack(project_id, message):
        """Send a Slack webhook notification if configured."""
        try:
            prefs = db.get_notification_prefs(project_id)
            webhook_url = prefs.get("slack_webhook_url") if prefs else None
            if webhook_url and _is_valid_slack_webhook(webhook_url):
                import urllib.request
                req = urllib.request.Request(
                    webhook_url,
                    data=json.dumps({"text": message}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    @app.route("/api/events/stream")
    def sse_stream():
        project_id = request.args.get("project_id", type=int)
        if not project_id:
            return "project_id required", 400

        q = queue.Queue()
        if project_id not in sse_clients:
            sse_clients[project_id] = []
        sse_clients[project_id].append(q)

        def generate():
            try:
                yield "event: connected\ndata: {}\n\n"
                while True:
                    try:
                        msg = q.get(timeout=30)
                        yield msg
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                if project_id in sse_clients and q in sse_clients[project_id]:
                    sse_clients[project_id].remove(q)

        return app.response_class(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Share Tokens ---

    @app.route("/api/share-tokens", methods=["GET"])
    def list_share_tokens():
        project_id = request.args.get("project_id", type=int)
        tokens = db.get_share_tokens(project_id)
        return jsonify(tokens)

    @app.route("/api/share-tokens", methods=["POST"])
    def create_share_token():
        data = request.json
        project_id = data.get("project_id")
        label = data.get("label", "Shared link")
        token = db.create_share_token(project_id, label=label)
        if project_id:
            db.log_activity(project_id, "share_created",
                            f"Created share link: {label}", "project", project_id)
        return jsonify({"token": token, "url": f"/shared/{token}"})

    @app.route("/api/share-tokens/<int:token_id>", methods=["DELETE"])
    def revoke_share_token(token_id):
        db.revoke_share_token(token_id)
        return jsonify({"ok": True})

    # --- Tag operations activity logging ---

    @app.route("/shared/<token>")
    def shared_view(token):
        share = db.validate_share_token(token)
        if not share:
            return jsonify({"error": "Invalid or expired share link"}), 404
        # Return read-only version of the project data
        project_id = share["project_id"]
        companies = db.get_companies(project_id=project_id)
        categories = db.get_category_stats(project_id=project_id)
        stats = db.get_stats(project_id=project_id)
        return jsonify({
            "project_id": project_id,
            "companies": companies,
            "categories": categories,
            "stats": stats,
            "label": share.get("label", "Shared view"),
            "read_only": True,
        })

    # --- Activity Log ---

    @app.route("/api/activity")
    def get_activity():
        project_id = request.args.get("project_id", type=int)
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        events = db.get_activity(project_id, limit=limit, offset=offset)
        return jsonify(events)

    # --- Notification Prefs ---

    @app.route("/api/notification-prefs", methods=["GET"])
    def get_notification_prefs():
        project_id = request.args.get("project_id", type=int)
        prefs = db.get_notification_prefs(project_id)
        return jsonify(prefs or {"slack_webhook_url": None, "notify_batch_complete": 1,
                                  "notify_taxonomy_change": 1, "notify_new_company": 0})

    @app.route("/api/notification-prefs", methods=["POST"])
    def save_notification_prefs():
        data = request.json
        db.save_notification_prefs(
            project_id=data.get("project_id"),
            slack_webhook_url=data.get("slack_webhook_url"),
            notify_batch_complete=data.get("notify_batch_complete", 1),
            notify_taxonomy_change=data.get("notify_taxonomy_change", 1),
            notify_new_company=data.get("notify_new_company", 0),
        )
        return jsonify({"ok": True})

    @app.route("/api/notification-prefs/test-slack", methods=["POST"])
    def test_slack():
        data = request.json
        webhook_url = data.get("slack_webhook_url", "").strip()
        if not webhook_url:
            return jsonify({"error": "No webhook URL provided"}), 400
        if not _is_valid_slack_webhook(webhook_url):
            return jsonify({"error": "Invalid Slack webhook URL. Must be https://hooks.slack.com/services/..."}), 400
        import urllib.request
        try:
            req = urllib.request.Request(
                webhook_url,
                data=json.dumps({"text": "Test notification from Research Taxonomy Library"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # --- Taxonomy Quality ---

    @app.route("/api/taxonomy/quality")
    def taxonomy_quality():
        project_id = request.args.get("project_id", type=int)
        quality = db.get_taxonomy_quality(project_id)
        return jsonify(quality)

    return app


def _register_shutdown():
    """Register cleanup handlers for graceful shutdown."""
    import atexit
    import signal

    def _cleanup():
        try:
            from core.scraper import close_browser_sync
            close_browser_sync()
        except Exception:
            pass

    atexit.register(_cleanup)

    def _signal_handler(signum, frame):
        _cleanup()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


if __name__ == "__main__":
    _register_shutdown()
    app = create_app()
    print(f"\n  Research Taxonomy Library")
    print(f"  http://{WEB_HOST}:{WEB_PORT}\n")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=True)
