"""Companies API: CRUD, star, relationship, re-research, notes, events,
version history, trash, duplicates, merge, compare."""
import json

from flask import Blueprint, current_app, jsonify, request

from config import DEFAULT_MODEL
from web.async_jobs import start_async_job, write_result, poll_result
from web.notifications import notify_sse
from storage.export import export_markdown, export_json

companies_bp = Blueprint("companies", __name__)


# --- Companies CRUD ---

@companies_bp.route("/api/companies")
def list_companies():
    db = current_app.db
    project_id = request.args.get("project_id", type=int)
    category_id = request.args.get("category_id", type=int)
    search = request.args.get("search")
    starred_only = request.args.get("starred") == "1"
    needs_enrichment = request.args.get("needs_enrichment") == "1"
    sort_by = request.args.get("sort_by", "name")
    sort_dir = request.args.get("sort_dir", "asc")
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


@companies_bp.route("/api/companies/<int:company_id>")
def get_company(company_id):
    db = current_app.db
    company = db.get_company(company_id)
    if not company:
        return jsonify({"error": "Not found"}), 404
    company["notes"] = db.get_notes(company_id)
    company["events"] = db.get_events(company_id)
    return jsonify(company)


@companies_bp.route("/api/companies/add", methods=["POST"])
def add_company():
    """Quick-add a company (used by tests and manual entry)."""
    db = current_app.db
    data = request.json or {}
    if not data.get("url"):
        return jsonify({"error": "url is required"}), 400
    if not data.get("project_id"):
        return jsonify({"error": "project_id is required"}), 400
    data.setdefault("name", data["url"])
    data.setdefault("slug", data["name"].lower().replace(" ", "-"))
    company_id = db.upsert_company(data)
    return jsonify({"id": company_id, "status": "ok"})


@companies_bp.route("/api/companies/<int:company_id>", methods=["POST"])
def update_company(company_id):
    db = current_app.db
    fields = request.json or {}
    project_id = fields.pop("project_id", None)
    db.update_company(company_id, fields)
    export_markdown(db, project_id=project_id)
    export_json(db, project_id=project_id)
    company = db.get_company(company_id)
    name = company["name"] if company else f"#{company_id}"
    if project_id:
        db.log_activity(project_id, "company_updated",
                        f"Updated {name}", "company", company_id)
        notify_sse(project_id, "company_updated",
                   {"company_id": company_id, "name": name})
    return jsonify({"status": "ok"})


@companies_bp.route("/api/companies/<int:company_id>", methods=["DELETE"])
def delete_company(company_id):
    db = current_app.db
    company = db.get_company(company_id)
    name = company["name"] if company else f"#{company_id}"
    project_id = company.get("project_id") if company else None
    db.delete_company(company_id)
    if project_id:
        db.log_activity(project_id, "company_deleted",
                        f"Deleted {name}", "company", company_id)
    return jsonify({"status": "ok"})


@companies_bp.route("/api/companies/<int:company_id>/star", methods=["POST"])
def toggle_star(company_id):
    db = current_app.db
    new_val = db.toggle_star(company_id)
    if new_val is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"is_starred": new_val})


@companies_bp.route("/api/companies/<int:company_id>/relationship", methods=["POST"])
def update_relationship(company_id):
    db = current_app.db
    data = request.json or {}
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


# --- Re-research ---

def _run_re_research(job_id, company_id, company, urls, model):
    from core.researcher import research_company_with_sources
    from storage.db import Database
    re_db = Database()

    existing = {}
    if company.get("raw_research"):
        try:
            existing = json.loads(company["raw_research"])
        except (json.JSONDecodeError, TypeError):
            pass

    updated = research_company_with_sources(urls, existing, model=model)

    update_fields = {
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
    }
    for pf in ("pricing_model", "pricing_b2c_low", "pricing_b2c_high",
               "pricing_b2b_low", "pricing_b2b_high", "has_free_tier",
               "revenue_model", "pricing_tiers", "pricing_notes"):
        if updated.get(pf) is not None:
            val = updated[pf]
            if pf == "pricing_tiers" and not isinstance(val, str):
                val = json.dumps(val)
            update_fields[pf] = val
    re_db.update_company(company_id, update_fields)

    for url in urls:
        re_db.add_company_source(company_id, url, "re-research")

    write_result("reresearch", job_id, {"status": "complete", "updated": updated})


@companies_bp.route("/api/companies/<int:company_id>/re-research", methods=["POST"])
def re_research_company(company_id):
    db = current_app.db
    data = request.json or {}
    urls = data.get("urls", [])
    model = data.get("model", DEFAULT_MODEL)

    if not urls:
        return jsonify({"error": "No URLs provided"}), 400

    company = db.get_company(company_id)
    if not company:
        return jsonify({"error": "Company not found"}), 404

    research_id = start_async_job("reresearch", _run_re_research,
                                  company_id, company, urls, model)
    return jsonify({"research_id": research_id})


@companies_bp.route("/api/re-research/<research_id>")
def get_re_research_status(research_id):
    return jsonify(poll_result("reresearch", research_id))


# --- Notes ---

@companies_bp.route("/api/companies/<int:company_id>/notes")
def list_notes(company_id):
    return jsonify(current_app.db.get_notes(company_id))


@companies_bp.route("/api/companies/<int:company_id>/notes", methods=["POST"])
def add_note(company_id):
    db = current_app.db
    content = (request.json or {}).get("content", "").strip()
    if not content:
        return jsonify({"error": "Content is required"}), 400
    note_id = db.add_note(company_id, content)
    company = db.get_company(company_id)
    if company and company.get("project_id"):
        db.log_activity(company["project_id"], "note_added",
                        f"Added note to {company['name']}",
                        "company", company_id)
    return jsonify({"id": note_id, "status": "ok"})


@companies_bp.route("/api/notes/<int:note_id>", methods=["POST"])
def update_note(note_id):
    content = (request.json or {}).get("content", "").strip()
    if not content:
        return jsonify({"error": "Content is required"}), 400
    current_app.db.update_note(note_id, content)
    return jsonify({"status": "ok"})


@companies_bp.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    current_app.db.delete_note(note_id)
    return jsonify({"status": "ok"})


@companies_bp.route("/api/notes/<int:note_id>/pin", methods=["POST"])
def pin_note(note_id):
    new_val = current_app.db.toggle_pin_note(note_id)
    return jsonify({"is_pinned": new_val})


# --- Version History ---

@companies_bp.route("/api/companies/<int:company_id>/versions")
def list_versions(company_id):
    return jsonify(current_app.db.get_versions(company_id))


@companies_bp.route("/api/versions/<int:version_id>/restore", methods=["POST"])
def restore_version(version_id):
    db = current_app.db
    company_id = db.restore_version(version_id)
    if not company_id:
        return jsonify({"error": "Version not found"}), 404
    company = db.get_company(company_id)
    if company and company.get("project_id"):
        db.log_activity(company["project_id"], "version_restored",
                        f"Restored {company['name']} to version #{version_id}",
                        "company", company_id)
    return jsonify({"status": "ok", "company_id": company_id})


# --- Trash ---

@companies_bp.route("/api/trash")
def list_trash():
    project_id = request.args.get("project_id", type=int)
    return jsonify(current_app.db.get_trash(project_id=project_id))


@companies_bp.route("/api/companies/<int:company_id>/restore", methods=["POST"])
def restore_company(company_id):
    db = current_app.db
    db.restore_company(company_id)
    company = db.get_company(company_id)
    name = company["name"] if company else f"#{company_id}"
    project_id = company.get("project_id") if company else None
    if project_id:
        db.log_activity(project_id, "company_restored",
                        f"Restored {name} from trash", "company", company_id)
    return jsonify({"status": "ok"})


@companies_bp.route("/api/companies/<int:company_id>/permanent-delete", methods=["DELETE"])
def permanent_delete(company_id):
    current_app.db.permanently_delete(company_id)
    return jsonify({"status": "ok"})


# --- Events / Lifecycle ---

@companies_bp.route("/api/companies/<int:company_id>/events")
def list_events(company_id):
    return jsonify(current_app.db.get_events(company_id))


@companies_bp.route("/api/companies/<int:company_id>/events", methods=["POST"])
def add_event(company_id):
    data = request.json or {}
    event_type = data.get("event_type", "").strip()
    description = data.get("description", "")
    event_date = data.get("event_date")
    if not event_type:
        return jsonify({"error": "event_type is required"}), 400
    current_app.db.add_event(company_id, event_type, description, event_date)
    return jsonify({"status": "ok"})


@companies_bp.route("/api/events/<int:event_id>", methods=["DELETE"])
def delete_event(event_id):
    current_app.db.delete_event(event_id)
    return jsonify({"status": "ok"})


# --- Duplicates & Merge ---

@companies_bp.route("/api/duplicates")
def find_duplicates():
    project_id = request.args.get("project_id", type=int)
    return jsonify(current_app.db.find_duplicates(project_id=project_id))


@companies_bp.route("/api/companies/merge", methods=["POST"])
def merge_companies():
    db = current_app.db
    data = request.json or {}
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


# --- Bulk Actions ---

@companies_bp.route("/api/companies/bulk", methods=["POST"])
def bulk_action():
    db = current_app.db
    data = request.json or {}
    action = data.get("action")
    company_ids = data.get("company_ids", [])
    if not company_ids or len(company_ids) > 500:
        return jsonify({"error": "Provide 1-500 company IDs"}), 400
    params = data.get("params", {})

    if not action:
        return jsonify({"error": "action is required"}), 400

    updated = 0

    if action == "assign_category":
        category_id = params.get("category_id")
        if not category_id:
            return jsonify({"error": "category_id is required"}), 400
        for cid in company_ids:
            db.update_company(cid, {"category_id": category_id})
            updated += 1

    elif action == "add_tags":
        new_tags = params.get("tags", [])
        if not new_tags:
            return jsonify({"error": "tags are required"}), 400
        for cid in company_ids:
            company = db.get_company(cid)
            if company:
                existing = company.get("tags") or []
                merged = list(set(existing + new_tags))
                db.update_company(cid, {"tags": merged})
                updated += 1

    elif action == "set_relationship":
        status = params.get("status")
        for cid in company_ids:
            db.update_relationship(cid, status, None)
            updated += 1

    elif action == "delete":
        for cid in company_ids:
            db.delete_company(cid)
            updated += 1

    else:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    # Log activity
    if company_ids:
        company = db.get_company(company_ids[0], include_deleted=True)
        project_id = company.get("project_id") if company else None
        if project_id:
            db.log_activity(project_id, f"bulk_{action}",
                            f"Bulk {action} on {updated} companies",
                            "company", None)

    return jsonify({"updated": updated})


# --- Compare ---

# --- Enrichment ---

def _run_enrich_single(job_id, company_id, fields_to_fill, model):
    from core.enrichment import run_enrichment
    from storage.db import Database
    from datetime import datetime
    enrich_db = Database()
    company = enrich_db.get_company(company_id)
    if not company:
        write_result("enrich", job_id, {"status": "error", "error": "Company not found"})
        return

    enrich_db.update_company(company_id, {"enrichment_status": "enriching"})
    try:
        result = run_enrichment(company, fields_to_fill, model)
        enriched = result.get("enriched_fields", {})
        if enriched:
            # Handle tags specially (merge instead of replace)
            if "tags" in enriched:
                existing_tags = company.get("tags") or []
                enriched["tags"] = list(set(existing_tags + enriched["tags"]))
            enriched["enrichment_status"] = "enriched"
            enriched["last_verified_at"] = datetime.now().isoformat()
            enrich_db.update_company(company_id, enriched)
        else:
            enrich_db.update_company(company_id, {"enrichment_status": "enriched"})
        write_result("enrich", job_id, {
            "status": "complete", "enriched_fields": list(enriched.keys()),
            "steps_run": result.get("steps_run", 0),
        })
    except Exception as e:
        enrich_db.update_company(company_id, {"enrichment_status": "failed"})
        write_result("enrich", job_id, {"status": "error", "error": str(e)[:300]})


@companies_bp.route("/api/companies/<int:company_id>/enrich", methods=["POST"])
def enrich_company(company_id):
    db = current_app.db
    company = db.get_company(company_id)
    if not company:
        return jsonify({"error": "Company not found"}), 404
    data = request.json or {}
    fields_to_fill = data.get("fields_to_fill")
    model = data.get("model", DEFAULT_MODEL)
    job_id = start_async_job("enrich", _run_enrich_single,
                              company_id, fields_to_fill, model)
    return jsonify({"job_id": job_id})


@companies_bp.route("/api/enrich/<job_id>")
def poll_enrich(job_id):
    return jsonify(poll_result("enrich", job_id))


def _run_enrich_batch(job_id, project_id, company_ids, model):
    from core.enrichment import run_enrichment, identify_missing_fields
    from storage.db import Database
    from datetime import datetime
    enrich_db = Database()

    results = []
    for cid in company_ids:
        company = enrich_db.get_company(cid)
        if not company:
            continue
        missing = identify_missing_fields(company)
        if not missing:
            continue
        enrich_db.update_company(cid, {"enrichment_status": "enriching"})
        try:
            result = run_enrichment(company, missing, model)
            enriched = result.get("enriched_fields", {})
            if enriched:
                if "tags" in enriched:
                    existing_tags = company.get("tags") or []
                    enriched["tags"] = list(set(existing_tags + enriched["tags"]))
                enriched["enrichment_status"] = "enriched"
                enriched["last_verified_at"] = datetime.now().isoformat()
                enrich_db.update_company(cid, enriched)
            else:
                enrich_db.update_company(cid, {"enrichment_status": "enriched"})
            results.append({"id": cid, "fields": list(enriched.keys())})
        except Exception as e:
            enrich_db.update_company(cid, {"enrichment_status": "failed"})
            results.append({"id": cid, "error": str(e)[:200]})

    write_result("enrich", job_id, {"status": "complete", "results": results})


@companies_bp.route("/api/companies/enrich-batch", methods=["POST"])
def enrich_batch():
    db = current_app.db
    data = request.json or {}
    project_id = data.get("project_id")
    company_ids = data.get("company_ids")
    model = data.get("model", DEFAULT_MODEL)

    if not company_ids:
        # Enrich all companies with missing fields
        companies = db.get_companies(project_id=project_id, limit=500)
        from core.enrichment import identify_missing_fields
        company_ids = [c["id"] for c in companies if identify_missing_fields(c)]

    if not company_ids:
        return jsonify({"error": "No companies need enrichment"}), 400

    job_id = start_async_job("enrich", _run_enrich_batch,
                              project_id, company_ids, model)
    return jsonify({"job_id": job_id, "count": len(company_ids)})


@companies_bp.route("/api/companies/compare")
def compare_companies():
    db = current_app.db
    ids = request.args.get("ids", "")
    company_ids = []
    for x in ids.split(","):
        x = x.strip()
        if x:
            try:
                company_ids.append(int(x))
            except ValueError:
                continue
        if len(company_ids) >= 20:
            break
    companies = []
    for cid in company_ids:
        c = db.get_company(cid)
        if c:
            companies.append(c)
    return jsonify(companies)
