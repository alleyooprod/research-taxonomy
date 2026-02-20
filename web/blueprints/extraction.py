"""Extraction API — AI-powered attribute extraction from evidence.

Endpoints:
    POST /api/extract                    — Trigger extraction for an entity
    POST /api/extract/from-url           — Extract from a URL directly
    GET  /api/extract/jobs               — List extraction jobs
    GET  /api/extract/jobs/<id>          — Get job status + results
    DELETE /api/extract/jobs/<id>        — Delete a job and its results
    GET  /api/extract/results            — List extraction results (with filters)
    GET  /api/extract/queue              — Get pending review queue for project
    POST /api/extract/results/<id>/review — Review (accept/reject/edit) a result
    POST /api/extract/results/bulk-review — Bulk accept/reject results
    GET  /api/extract/contradictions     — Detect contradictions for an entity
    GET  /api/extract/stats              — Extraction statistics for a project
"""
import threading

from flask import Blueprint, request, jsonify, current_app
from loguru import logger

extraction_bp = Blueprint("extraction", __name__)

# ── Background Jobs ──────────────────────────────────────────

_extraction_jobs = {}  # {job_key: {status, result, ...}}
_job_lock = threading.Lock()
_job_counter = 0


def _start_extraction_job(app, entity_id, evidence_id=None,
                          project_id=None, model=None):
    """Start an extraction job in a background thread.

    Returns: job_key (str)
    """
    global _job_counter
    with _job_lock:
        _job_counter += 1
        job_key = f"extract_{_job_counter}"
        _extraction_jobs[job_key] = {
            "status": "running",
            "entity_id": entity_id,
            "evidence_id": evidence_id,
            "result": None,
        }

    def _run():
        with app.app_context():
            try:
                db = current_app.db
                entity = db.get_entity(entity_id)
                if not entity:
                    with _job_lock:
                        _extraction_jobs[job_key]["status"] = "failed"
                        _extraction_jobs[job_key]["result"] = {"error": "Entity not found"}
                    return

                pid = project_id or entity["project_id"]
                type_def = db.get_entity_type_def(pid, entity["type_slug"])
                if not type_def:
                    with _job_lock:
                        _extraction_jobs[job_key]["status"] = "failed"
                        _extraction_jobs[job_key]["result"] = {"error": "Entity type not found"}
                    return

                if evidence_id:
                    evidence = db.get_evidence_by_id(evidence_id)
                    if not evidence:
                        with _job_lock:
                            _extraction_jobs[job_key]["status"] = "failed"
                            _extraction_jobs[job_key]["result"] = {"error": "Evidence not found"}
                        return
                    from core.extraction import extract_from_evidence
                    result = extract_from_evidence(
                        evidence=evidence, entity=entity,
                        schema_type_def=type_def, db=db, model=model,
                    )
                else:
                    # Extract from all text-based evidence for this entity
                    all_evidence = db.get_evidence(entity_id=entity_id)
                    from core.extraction import extract_from_evidence, ExtractionResult
                    combined_attrs = []
                    total_cost = 0.0
                    total_duration = 0

                    for ev in all_evidence:
                        r = extract_from_evidence(
                            evidence=ev, entity=entity,
                            schema_type_def=type_def, db=db, model=model,
                        )
                        if r.success:
                            combined_attrs.extend(r.extracted_attributes)
                            total_cost += r.cost_usd
                            total_duration += r.duration_ms

                    result = ExtractionResult(
                        success=len(combined_attrs) > 0,
                        entity_id=entity_id,
                        extracted_attributes=combined_attrs,
                        model=model,
                        cost_usd=total_cost,
                        duration_ms=total_duration,
                        error="No extractable evidence found" if not combined_attrs and all_evidence else None,
                    )

                with _job_lock:
                    _extraction_jobs[job_key]["status"] = "completed"
                    _extraction_jobs[job_key]["result"] = result.to_dict()

            except Exception as e:
                logger.error("Extraction job %s failed: %s", job_key, e)
                with _job_lock:
                    _extraction_jobs[job_key]["status"] = "failed"
                    _extraction_jobs[job_key]["result"] = {"error": str(e)}

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return job_key


# ── Endpoints ────────────────────────────────────────────────

@extraction_bp.route("/api/extract", methods=["POST"])
def trigger_extraction():
    """Trigger extraction for an entity from its evidence.

    Body: {entity_id, project_id, [evidence_id], [model], [async]}
    """
    data = request.json or {}
    entity_id = data.get("entity_id")
    project_id = data.get("project_id")
    evidence_id = data.get("evidence_id")
    model = data.get("model")
    is_async = data.get("async", False)

    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    db = current_app.db
    entity = db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": f"Entity {entity_id} not found"}), 404

    type_def = db.get_entity_type_def(project_id, entity["type_slug"])
    if not type_def:
        return jsonify({"error": f"Entity type '{entity['type_slug']}' not found in project schema"}), 404

    attributes = type_def.get("attributes", [])
    if not attributes:
        return jsonify({"error": "No attributes defined for this entity type"}), 400

    if evidence_id:
        evidence = db.get_evidence_by_id(evidence_id)
        if not evidence:
            return jsonify({"error": f"Evidence {evidence_id} not found"}), 404

    # Async mode — run in background
    if is_async:
        job_key = _start_extraction_job(
            current_app._get_current_object(),
            entity_id, evidence_id, project_id, model,
        )
        return jsonify({"job_key": job_key, "status": "running"}), 202

    # Sync mode
    if evidence_id:
        evidence = db.get_evidence_by_id(evidence_id)
        from core.extraction import extract_from_evidence
        result = extract_from_evidence(
            evidence=evidence, entity=entity,
            schema_type_def=type_def, db=db, model=model,
        )
    else:
        # Extract from all evidence
        all_evidence = db.get_evidence(entity_id=entity_id)
        if not all_evidence:
            return jsonify({"error": "No evidence found for this entity"}), 404

        from core.extraction import extract_from_evidence, ExtractionResult
        combined_attrs = []
        total_cost = 0.0
        total_duration = 0

        for ev in all_evidence:
            r = extract_from_evidence(
                evidence=ev, entity=entity,
                schema_type_def=type_def, db=db, model=model,
            )
            if r.success:
                combined_attrs.extend(r.extracted_attributes)
                total_cost += r.cost_usd
                total_duration += r.duration_ms

        result = ExtractionResult(
            success=len(combined_attrs) > 0,
            entity_id=entity_id,
            extracted_attributes=combined_attrs,
            model=model,
            cost_usd=total_cost,
            duration_ms=total_duration,
        )

    if result.success:
        return jsonify(result.to_dict()), 201
    else:
        return jsonify(result.to_dict()), 422


@extraction_bp.route("/api/extract/from-url", methods=["POST"])
def extract_from_url_endpoint():
    """Extract attributes from a URL directly.

    Body: {url, entity_id, project_id, [model]}
    """
    data = request.json or {}
    url = data.get("url")
    entity_id = data.get("entity_id")
    project_id = data.get("project_id")
    model = data.get("model")

    if not url:
        return jsonify({"error": "url is required"}), 400
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    db = current_app.db
    entity = db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": f"Entity {entity_id} not found"}), 404

    type_def = db.get_entity_type_def(project_id, entity["type_slug"])
    if not type_def:
        return jsonify({"error": f"Entity type '{entity['type_slug']}' not found"}), 404

    from core.extraction import extract_from_url
    result = extract_from_url(
        url=url, entity=entity,
        schema_type_def=type_def, db=db, model=model,
    )

    if result.success:
        return jsonify(result.to_dict()), 201
    else:
        return jsonify(result.to_dict()), 422


@extraction_bp.route("/api/extract/jobs", methods=["GET"])
def list_extraction_jobs():
    """List extraction jobs. Query: ?project_id=X&entity_id=Y&status=Z"""
    project_id = request.args.get("project_id", type=int)
    entity_id = request.args.get("entity_id", type=int)
    status = request.args.get("status")
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    db = current_app.db
    jobs = db.get_extraction_jobs(
        project_id=project_id, entity_id=entity_id,
        status=status, limit=limit, offset=offset,
    )
    return jsonify(jobs)


@extraction_bp.route("/api/extract/jobs/<int:job_id>", methods=["GET"])
def get_extraction_job(job_id):
    """Get a single extraction job with its results."""
    db = current_app.db
    job = db.get_extraction_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    results = db.get_extraction_results(job_id=job_id)
    job["results"] = results
    return jsonify(job)


@extraction_bp.route("/api/extract/jobs/<int:job_id>", methods=["DELETE"])
def delete_extraction_job(job_id):
    """Delete an extraction job and all its results."""
    db = current_app.db
    job = db.get_extraction_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    db.delete_extraction_job(job_id)
    return jsonify({"status": "deleted", "job_id": job_id})


@extraction_bp.route("/api/extract/async-jobs", methods=["GET"])
def list_async_jobs():
    """List in-memory async extraction jobs."""
    job_key = request.args.get("job_key")
    if job_key:
        with _job_lock:
            job = _extraction_jobs.get(job_key)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({"job_key": job_key, **job})

    with _job_lock:
        jobs = {k: v for k, v in _extraction_jobs.items()}
    return jsonify(jobs)


@extraction_bp.route("/api/extract/results", methods=["GET"])
def list_extraction_results():
    """List extraction results. Query: ?entity_id=X&status=Y&job_id=Z&attr_slug=W"""
    entity_id = request.args.get("entity_id", type=int)
    job_id = request.args.get("job_id", type=int)
    status = request.args.get("status")
    attr_slug = request.args.get("attr_slug")
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)

    db = current_app.db
    results = db.get_extraction_results(
        entity_id=entity_id, job_id=job_id,
        status=status, attr_slug=attr_slug,
        limit=limit, offset=offset,
    )
    return jsonify(results)


@extraction_bp.route("/api/extract/queue", methods=["GET"])
def get_review_queue():
    """Get pending extraction results for review. Query: ?project_id=X"""
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)

    db = current_app.db
    queue = db.get_extraction_queue(project_id, limit=limit, offset=offset)
    return jsonify(queue)


@extraction_bp.route("/api/extract/results/<int:result_id>/review", methods=["POST"])
def review_result(result_id):
    """Review an extraction result.

    Body: {action: "accept"|"reject"|"edit", [edited_value]}
    """
    data = request.json or {}
    action = data.get("action")
    edited_value = data.get("edited_value")

    if not action:
        return jsonify({"error": "action is required"}), 400
    if action not in ("accept", "reject", "edit"):
        return jsonify({"error": "action must be 'accept', 'reject', or 'edit'"}), 400
    if action == "edit" and edited_value is None:
        return jsonify({"error": "edited_value is required for 'edit' action"}), 400

    db = current_app.db
    result = db.get_extraction_result(result_id)
    if not result:
        return jsonify({"error": "Result not found"}), 404
    if result["status"] != "pending":
        return jsonify({"error": f"Result already reviewed (status: {result['status']})"}), 400

    success = db.review_extraction_result(result_id, action, edited_value)
    if success:
        return jsonify({"status": action + "ed", "result_id": result_id})
    return jsonify({"error": "Failed to review result"}), 422


@extraction_bp.route("/api/extract/results/bulk-review", methods=["POST"])
def bulk_review_results():
    """Bulk accept or reject extraction results.

    Body: {result_ids: [1,2,3], action: "accept"|"reject"}
    """
    data = request.json or {}
    result_ids = data.get("result_ids", [])
    action = data.get("action")

    if not result_ids:
        return jsonify({"error": "result_ids is required"}), 400
    if action not in ("accept", "reject"):
        return jsonify({"error": "action must be 'accept' or 'reject'"}), 400

    db = current_app.db
    count = db.bulk_review_extraction_results(result_ids, action)
    return jsonify({
        "status": "ok",
        "action": action,
        "updated_count": count,
        "requested_count": len(result_ids),
    })


@extraction_bp.route("/api/extract/contradictions", methods=["GET"])
def get_contradictions():
    """Detect contradictions in pending extraction results for an entity.

    Query: ?entity_id=X
    """
    entity_id = request.args.get("entity_id", type=int)
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400

    from core.extraction import detect_contradictions
    db = current_app.db
    contradictions = detect_contradictions(entity_id, db)
    return jsonify(contradictions)


@extraction_bp.route("/api/extract/stats", methods=["GET"])
def get_extraction_stats():
    """Get extraction statistics for a project. Query: ?project_id=X"""
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    db = current_app.db
    stats = db.get_extraction_stats(project_id)
    return jsonify(stats)
