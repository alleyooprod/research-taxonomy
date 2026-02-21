"""Enrichment API — enrich entities via MCP data sources.

Provides endpoints for:
- Server listing: available MCP data sources and their status
- Recommendations: which sources are relevant for a given entity
- Single-entity enrichment: sync or async via background job
- Batch enrichment: enrich multiple entities asynchronously
- Job polling: check status of async enrichment jobs
"""
from flask import Blueprint, request, jsonify, current_app
from loguru import logger

enrichment_bp = Blueprint("enrichment", __name__)


# ── Helpers ──────────────────────────────────────────────────

def _build_reason(adapter, context):
    """Return a human-readable reason why this adapter is recommended."""
    name = adapter.get("name", "")
    entity_type = context.get("type_slug", "")
    country = context.get("country", "")
    has_url = bool(context.get("url"))

    if name == "companies_house" and country:
        return f"{country} company detected"
    if name in ("cloudflare_radar", "domain_rank") and has_url:
        return "Entity has a website URL"
    if name == "sec_edgar":
        return "US public company filings available"
    if name == "patents":
        return "Patent search available for entity name"
    if name in ("hackernews", "news_search", "wikipedia", "duckduckgo"):
        return "Available for all entities"
    if name == "morningstar":
        return "Financial data available"
    # Fallback
    desc = adapter.get("description", "")
    if desc:
        return desc
    return "Relevant data source for this entity"


def _enrich_worker(job_id, entity_id, servers, max_age):
    """Background enrichment worker for a single entity."""
    from web.async_jobs import write_result

    try:
        db = current_app.db
        from core.mcp_enrichment import enrich_entity
        result = enrich_entity(entity_id, db, servers=servers, max_age_hours=max_age)
        write_result("enrichment", job_id, {"status": "complete", **result})
    except Exception as e:
        logger.exception("Enrichment worker failed for entity {}", entity_id)
        write_result("enrichment", job_id, {"status": "error", "error": str(e)})


def _batch_enrich_worker(job_id, entity_ids, servers, max_age):
    """Background enrichment worker for batch of entities."""
    from web.async_jobs import write_result

    try:
        db = current_app.db
        from core.mcp_enrichment import enrich_batch
        result = enrich_batch(
            entity_ids, db, servers=servers,
            max_age_hours=max_age, delay=1.0,
        )
        write_result("enrichment_batch", job_id, {"status": "complete", **result})
    except Exception as e:
        logger.exception("Batch enrichment worker failed")
        write_result("enrichment_batch", job_id, {"status": "error", "error": str(e)})


# ── Endpoints ────────────────────────────────────────────────

@enrichment_bp.route("/api/enrichment/servers")
def list_servers():
    """List available MCP data sources with their status."""
    from core.mcp_client import list_available_sources
    sources = list_available_sources()
    return jsonify(sources)


@enrichment_bp.route("/api/entities/<int:entity_id>/enrichment/recommend")
def recommend_enrichment(entity_id):
    """Recommend enrichment sources for a specific entity."""
    from core.mcp_enrichment import build_entity_context, select_adapters, check_staleness

    db = current_app.db
    entity = db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": "Entity not found"}), 404

    attrs = entity.get("attributes", {})
    context = build_entity_context(entity, attrs)
    adapters = select_adapters(context)

    # Check which attributes are stale
    stale_attrs = []
    for adapter in adapters:
        for attr_slug in adapter.get("produces", []):
            if check_staleness(db, entity_id, attr_slug, max_age_hours=168):
                stale_attrs.append(attr_slug)

    # Deduplicate stale attrs
    stale_attrs = sorted(set(stale_attrs))

    recommended = []
    for adapter in adapters:
        recommended.append({
            "name": adapter["name"],
            "description": adapter.get("description", ""),
            "priority": adapter.get("priority", 0),
            "reason": _build_reason(adapter, context),
        })

    return jsonify({
        "entity_id": entity_id,
        "recommended_servers": recommended,
        "stale_attributes": stale_attrs,
    })


@enrichment_bp.route("/api/entities/<int:entity_id>/enrich", methods=["POST"])
def enrich_entity_endpoint(entity_id):
    """Trigger enrichment for a single entity (sync or async)."""
    from core.mcp_enrichment import enrich_entity

    db = current_app.db
    entity = db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": "Entity not found"}), 404

    data = request.get_json(silent=True) or {}
    servers = data.get("servers")
    max_age = data.get("max_age_hours", 168)
    run_async = data.get("async", False)

    if run_async:
        from web.async_jobs import start_async_job
        job_id = start_async_job(
            "enrichment",
            _enrich_worker,
            entity_id, servers, max_age,
        )
        return jsonify({"status": "pending", "job_id": job_id}), 202

    # Sync mode
    result = enrich_entity(entity_id, db, servers=servers, max_age_hours=max_age)
    return jsonify({"status": "completed", **result})


@enrichment_bp.route("/api/enrichment/poll/<job_id>")
def poll_enrichment(job_id):
    """Poll for async enrichment job status."""
    from web.async_jobs import poll_result
    result = poll_result("enrichment", job_id)
    return jsonify(result)


@enrichment_bp.route("/api/enrichment/batch", methods=["POST"])
def batch_enrich():
    """Batch enrich multiple entities (always async)."""
    data = request.get_json(silent=True) or {}
    entity_ids = data.get("entity_ids", [])
    project_id = data.get("project_id")
    servers = data.get("servers")
    max_age = data.get("max_age_hours", 168)

    if not entity_ids:
        return jsonify({"error": "entity_ids required"}), 400
    if not project_id:
        return jsonify({"error": "project_id required"}), 400

    from web.async_jobs import start_async_job
    job_id = start_async_job(
        "enrichment_batch",
        _batch_enrich_worker,
        entity_ids, servers, max_age,
    )
    return jsonify({
        "status": "pending",
        "job_id": job_id,
        "total": len(entity_ids),
    }), 202
