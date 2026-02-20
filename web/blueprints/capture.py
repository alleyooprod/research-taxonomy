"""Capture API — headless website capture, document download, evidence upload/serve.

Endpoints:
    POST /api/capture/website       — Capture URL screenshot + HTML archive
    POST /api/capture/document      — Download document from URL
    POST /api/evidence/upload       — Manual file upload
    GET  /api/evidence/<id>/file    — Serve evidence file
    DELETE /api/evidence/<id>/file  — Delete evidence file + record
    GET  /api/evidence/stats        — Evidence storage stats for a project
"""
import json
import threading
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app, send_file
from loguru import logger

from core.capture import (
    capture_website,
    capture_document,
    store_upload,
    evidence_path_absolute,
    delete_file,
    get_mime_type,
    validate_upload,
    ALLOWED_EVIDENCE_TYPES,
    MAX_UPLOAD_SIZE,
)

capture_bp = Blueprint("capture", __name__)


# ── Website Capture ───────────────────────────────────────────

@capture_bp.route("/api/capture/website", methods=["POST"])
def api_capture_website():
    """Capture a website: full-page screenshot + HTML archive.

    Request JSON:
        url (required): URL to capture
        entity_id (required): Entity to link evidence to
        project_id (required): Project context
        full_page (optional): Capture full scrollable page (default: true)
        viewport_width (optional): Browser viewport width (default: 1440)
        viewport_height (optional): Browser viewport height (default: 900)
        save_html (optional): Also archive HTML source (default: true)
        async (optional): Run capture in background (default: false)

    Returns:
        CaptureResult dict with evidence_ids and paths
    """
    data = request.json or {}
    url = data.get("url", "").strip()
    entity_id = data.get("entity_id")
    project_id = data.get("project_id")

    if not url:
        return jsonify({"error": "url is required"}), 400
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    # Validate URL scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Validate entity exists
    entity = current_app.db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": f"Entity {entity_id} not found"}), 404

    kwargs = {}
    if "full_page" in data:
        kwargs["full_page"] = bool(data["full_page"])
    if "viewport_width" in data:
        kwargs["viewport_width"] = int(data["viewport_width"])
    if "viewport_height" in data:
        kwargs["viewport_height"] = int(data["viewport_height"])
    if "save_html" in data:
        kwargs["save_html"] = bool(data["save_html"])

    run_async = data.get("async", False)

    if run_async:
        app = current_app._get_current_object()
        job_id = _start_capture_job(app, "website", url, project_id, entity_id, kwargs)
        return jsonify({"job_id": job_id, "status": "running"}), 202
    else:
        result = capture_website(
            url=url,
            project_id=project_id,
            entity_id=entity_id,
            db=current_app.db,
            **kwargs,
        )

        if result.success:
            logger.info(
                "Captured %s → %d evidence files in %dms",
                url, len(result.evidence_ids), result.duration_ms,
            )
            return jsonify(result.to_dict()), 201
        else:
            logger.warning("Capture failed for %s: %s", url, result.error)
            return jsonify(result.to_dict()), 422


# ── Document Capture ──────────────────────────────────────────

@capture_bp.route("/api/capture/document", methods=["POST"])
def api_capture_document():
    """Download a document from URL and store as evidence.

    Request JSON:
        url (required): Document URL to download
        entity_id (required): Entity to link evidence to
        project_id (required): Project context
        timeout (optional): Download timeout in seconds (default: 30)

    Returns:
        CaptureResult dict
    """
    data = request.json or {}
    url = data.get("url", "").strip()
    entity_id = data.get("entity_id")
    project_id = data.get("project_id")

    if not url:
        return jsonify({"error": "url is required"}), 400
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    entity = current_app.db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": f"Entity {entity_id} not found"}), 404

    timeout = data.get("timeout", 30)

    result = capture_document(
        url=url,
        project_id=project_id,
        entity_id=entity_id,
        db=current_app.db,
        timeout=timeout,
    )

    if result.success:
        logger.info("Downloaded document %s in %dms", url, result.duration_ms)
        return jsonify(result.to_dict()), 201
    else:
        logger.warning("Document download failed for %s: %s", url, result.error)
        return jsonify(result.to_dict()), 422


# ── Manual Evidence Upload ────────────────────────────────────

@capture_bp.route("/api/evidence/upload", methods=["POST"])
def api_upload_evidence():
    """Upload a file as evidence.

    Multipart form data:
        file (required): The file to upload
        entity_id (required): Entity to link evidence to
        project_id (required): Project context
        evidence_type (optional): Override type (default: guessed from extension)
        source_name (optional): Source description (default: "Manual upload")
        metadata (optional): JSON string of additional metadata

    Returns:
        CaptureResult dict with evidence_id
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    entity_id = request.form.get("entity_id", type=int)
    project_id = request.form.get("project_id", type=int)

    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    entity = current_app.db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": f"Entity {entity_id} not found"}), 404

    file_data = file.read()
    original_filename = file.filename or "unnamed"

    is_valid, err = validate_upload(original_filename, len(file_data))
    if not is_valid:
        return jsonify({"error": err}), 400

    evidence_type = request.form.get("evidence_type")
    source_name = request.form.get("source_name", "Manual upload")
    metadata_str = request.form.get("metadata", "{}")
    try:
        metadata = json.loads(metadata_str)
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    result = store_upload(
        project_id=project_id,
        entity_id=entity_id,
        file_data=file_data,
        original_filename=original_filename,
        evidence_type=evidence_type,
        db=current_app.db,
        source_name=source_name,
        metadata=metadata,
    )

    if result.success:
        logger.info(
            "Uploaded %s (%d bytes) for entity %d",
            original_filename, len(file_data), entity_id,
        )
        return jsonify(result.to_dict()), 201
    else:
        return jsonify(result.to_dict()), 400


# ── Evidence File Serving ─────────────────────────────────────

@capture_bp.route("/api/evidence/<int:evidence_id>/file")
def serve_evidence_file(evidence_id):
    """Serve an evidence file by its DB record ID.

    Returns the actual file with correct Content-Type.
    """
    record = current_app.db.get_evidence_by_id(evidence_id)
    if not record:
        return jsonify({"error": "Evidence not found"}), 404

    relative_path = record["file_path"]
    abs_path = evidence_path_absolute(relative_path)

    if not abs_path.exists():
        return jsonify({"error": "Evidence file not found on disk"}), 404

    mime = get_mime_type(relative_path)
    return send_file(abs_path, mimetype=mime)


# ── Evidence File Deletion (file + record) ────────────────────

@capture_bp.route("/api/evidence/<int:evidence_id>/file", methods=["DELETE"])
def delete_evidence_with_file(evidence_id):
    """Delete an evidence file from disk AND its database record.

    Unlike DELETE /api/evidence/<id> (which only deletes the DB record),
    this endpoint also removes the actual file from disk.
    """
    record = current_app.db.get_evidence_by_id(evidence_id)
    if not record:
        return jsonify({"error": "Evidence not found"}), 404

    relative_path = record["file_path"]
    file_deleted = delete_file(relative_path)
    current_app.db.delete_evidence(evidence_id)

    return jsonify({
        "status": "ok",
        "file_deleted": file_deleted,
        "record_deleted": True,
    })


# ── Evidence Storage Stats ────────────────────────────────────

@capture_bp.route("/api/evidence/stats")
def evidence_stats():
    """Get evidence storage statistics for a project.

    Query params:
        project_id (required): Project to get stats for

    Returns:
        Total count, size by type, recent captures
    """
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    all_evidence = current_app.db.get_evidence()

    # Filter to entities belonging to this project
    project_evidence = []
    for ev in all_evidence:
        entity = current_app.db.get_entity(ev["entity_id"])
        if entity and entity.get("project_id") == project_id:
            project_evidence.append(ev)

    total_count = len(project_evidence)
    by_type = {}
    total_size = 0

    for ev in project_evidence:
        t = ev["evidence_type"]
        by_type.setdefault(t, {"count": 0, "size": 0})
        by_type[t]["count"] += 1

        abs_path = evidence_path_absolute(ev["file_path"])
        if abs_path.exists():
            sz = abs_path.stat().st_size
            by_type[t]["size"] += sz
            total_size += sz

    return jsonify({
        "project_id": project_id,
        "total_count": total_count,
        "total_size": total_size,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "by_type": by_type,
    })


# ── Background Capture Jobs ──────────────────────────────────

_capture_jobs = {}  # job_id -> {"status": ..., "result": ..., "type": ...}
_job_lock = threading.Lock()
_job_counter = 0


def _start_capture_job(app, capture_type: str, url: str,
                       project_id: int, entity_id: int,
                       kwargs: dict) -> str:
    """Start a capture job in a background thread.

    Args:
        app: Flask application instance (not the proxy)
        capture_type: "website" or "document"
        url: URL to capture
        project_id: Project ID
        entity_id: Entity ID
        kwargs: Additional capture kwargs
    """
    global _job_counter
    with _job_lock:
        _job_counter += 1
        job_id = f"capture_{_job_counter}"
        _capture_jobs[job_id] = {
            "status": "running",
            "type": capture_type,
            "url": url,
            "result": None,
            "started_at": datetime.now().isoformat(),
        }

    def _run():
        with app.app_context():
            if capture_type == "website":
                result = capture_website(
                    url=url, project_id=project_id, entity_id=entity_id,
                    db=app.db, **kwargs,
                )
            elif capture_type == "document":
                result = capture_document(
                    url=url, project_id=project_id, entity_id=entity_id,
                    db=app.db,
                )
            else:
                result = None

            with _job_lock:
                _capture_jobs[job_id]["status"] = "completed" if (result and result.success) else "failed"
                _capture_jobs[job_id]["result"] = result.to_dict() if result else None

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return job_id


@capture_bp.route("/api/capture/jobs/<job_id>")
def get_capture_job(job_id):
    """Get the status of a background capture job."""
    with _job_lock:
        job = _capture_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@capture_bp.route("/api/capture/jobs")
def list_capture_jobs():
    """List all capture jobs (most recent first)."""
    with _job_lock:
        jobs = dict(_capture_jobs)
    result = []
    for jid, jdata in sorted(jobs.items(), reverse=True):
        result.append({"id": jid, **jdata})
    return jsonify(result)


# ── App Store Scrapers ────────────────────────────────────────

@capture_bp.route("/api/scrape/appstore/search")
def appstore_search():
    """Search the Apple App Store.

    Query params:
        term (required): Search query
        country (optional): Two-letter country code (default: "gb")
        limit (optional): Max results (default: 10)

    Returns:
        List of AppStoreApp dicts
    """
    from core.scrapers.appstore import search_apps

    term = request.args.get("term", "").strip()
    if not term:
        return jsonify({"error": "term is required"}), 400

    country = request.args.get("country", "gb")
    limit = request.args.get("limit", 10, type=int)

    results = search_apps(term, country=country, limit=limit)
    return jsonify([r.to_dict() for r in results])


@capture_bp.route("/api/scrape/appstore/details/<int:app_id>")
def appstore_details(app_id):
    """Get detailed info for a specific App Store app.

    Path param:
        app_id: iTunes track ID

    Returns:
        AppStoreApp dict or 404
    """
    from core.scrapers.appstore import get_app_details

    country = request.args.get("country", "gb")
    app = get_app_details(app_id, country=country)
    if not app:
        return jsonify({"error": f"App {app_id} not found"}), 404
    return jsonify(app.to_dict())


@capture_bp.route("/api/scrape/appstore/screenshots", methods=["POST"])
def appstore_screenshots():
    """Download screenshots from App Store and store as evidence.

    Request JSON:
        app_id (required): iTunes track ID
        entity_id (required): Entity to link evidence to
        project_id (required): Project context
        country (optional): Country code (default: "gb")
        include_ipad (optional): Also download iPad screenshots (default: false)
        include_icon (optional): Download app icon (default: true)

    Returns:
        CaptureResult dict
    """
    from core.scrapers.appstore import download_screenshots

    data = request.json or {}
    app_id = data.get("app_id")
    entity_id = data.get("entity_id")
    project_id = data.get("project_id")

    if not app_id:
        return jsonify({"error": "app_id is required"}), 400
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    entity = current_app.db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": f"Entity {entity_id} not found"}), 404

    result = download_screenshots(
        app_id=int(app_id),
        project_id=project_id,
        entity_id=entity_id,
        db=current_app.db,
        country=data.get("country", "gb"),
        include_ipad=data.get("include_ipad", False),
        include_icon=data.get("include_icon", True),
    )

    status = 201 if result.success else 422
    return jsonify(result.to_dict()), status


@capture_bp.route("/api/scrape/playstore/search")
def playstore_search():
    """Search the Google Play Store.

    Query params:
        term (required): Search query
        country (optional): Country code (default: "gb")
        limit (optional): Max results (default: 10)

    Returns:
        List of PlayStoreApp dicts
    """
    from core.scrapers.playstore import search_apps

    term = request.args.get("term", "").strip()
    if not term:
        return jsonify({"error": "term is required"}), 400

    country = request.args.get("country", "gb")
    limit = request.args.get("limit", 10, type=int)

    results = search_apps(term, country=country, limit=limit)
    return jsonify([r.to_dict() for r in results])


@capture_bp.route("/api/scrape/playstore/details/<package_id>")
def playstore_details(package_id):
    """Get detailed info for a specific Play Store app.

    Path param:
        package_id: Android package ID (e.g. "com.vitality.mobile")

    Returns:
        PlayStoreApp dict or 404
    """
    from core.scrapers.playstore import get_app_details

    country = request.args.get("country", "gb")
    app = get_app_details(package_id, country=country)
    if not app:
        return jsonify({"error": f"App {package_id} not found"}), 404
    return jsonify(app.to_dict())


@capture_bp.route("/api/scrape/playstore/screenshots", methods=["POST"])
def playstore_screenshots():
    """Download screenshots from Play Store and store as evidence.

    Request JSON:
        package_id (required): Android package ID
        entity_id (required): Entity to link evidence to
        project_id (required): Project context
        country (optional): Country code (default: "gb")
        include_icon (optional): Download app icon (default: true)

    Returns:
        CaptureResult dict
    """
    from core.scrapers.playstore import download_screenshots

    data = request.json or {}
    package_id = data.get("package_id", "").strip()
    entity_id = data.get("entity_id")
    project_id = data.get("project_id")

    if not package_id:
        return jsonify({"error": "package_id is required"}), 400
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    entity = current_app.db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": f"Entity {entity_id} not found"}), 404

    result = download_screenshots(
        package_id=package_id,
        project_id=project_id,
        entity_id=entity_id,
        db=current_app.db,
        country=data.get("country", "gb"),
        include_icon=data.get("include_icon", True),
    )

    status = 201 if result.success else 422
    return jsonify(result.to_dict()), status
