"""Entity API: CRUD for the Research Workbench entity system.

Provides endpoints for:
- Entity type definitions (schema)
- Entity CRUD (create, read, update, delete)
- Entity attributes (temporal versioning)
- Entity relationships (graph edges)
- Evidence library
- Snapshots
"""
import json
import logging

from flask import Blueprint, current_app, jsonify, request

from core.schema import (
    validate_schema, normalize_schema, get_type_hierarchy,
    SCHEMA_TEMPLATES,
)

logger = logging.getLogger(__name__)

entities_bp = Blueprint("entities", __name__)


# ═══════════════════════════════════════════════════════════════
# Schema Templates
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/schema/templates")
def list_schema_templates():
    """List available project schema templates."""
    result = []
    for key, template in SCHEMA_TEMPLATES.items():
        result.append({
            "key": key,
            "name": template["name"],
            "description": template["description"],
            "entity_types": [
                {"name": et["name"], "slug": et.get("slug", ""),
                 "parent_type": et.get("parent_type")}
                for et in template["schema"]["entity_types"]
            ],
        })
    return jsonify(result)


@entities_bp.route("/api/schema/validate", methods=["POST"])
def validate_schema_endpoint():
    """Validate a schema definition."""
    schema = (request.json or {}).get("schema")
    if not schema:
        return jsonify({"error": "schema is required"}), 400

    valid, errors = validate_schema(schema)
    return jsonify({"valid": valid, "errors": errors})


# ═══════════════════════════════════════════════════════════════
# Entity Type Definitions
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/entity-types")
def list_entity_types():
    """Get entity type definitions for a project."""
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    defs = current_app.db.get_entity_type_defs(project_id)
    return jsonify(defs)


@entities_bp.route("/api/entity-types/hierarchy")
def entity_type_hierarchy():
    """Get the entity type hierarchy for a project."""
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    project = current_app.db.get_project(project_id)
    if not project or not project.get("entity_schema"):
        return jsonify([])

    schema = json.loads(project["entity_schema"])
    return jsonify(get_type_hierarchy(schema))


@entities_bp.route("/api/entity-types/sync", methods=["POST"])
def sync_entity_types():
    """Sync entity type definitions from a schema (used after schema amendment)."""
    data = request.json or {}
    project_id = data.get("project_id")
    schema = data.get("schema")

    if not project_id or not schema:
        return jsonify({"error": "project_id and schema are required"}), 400

    valid, errors = validate_schema(schema)
    if not valid:
        return jsonify({"error": "Invalid schema", "details": errors}), 400

    schema = normalize_schema(schema)
    current_app.db.sync_entity_types(project_id, schema)
    current_app.db.update_project(project_id, {
        "entity_schema": json.dumps(schema)
    })

    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════════════════════
# Entities
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/entities")
def list_entities():
    """List entities with filtering."""
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    type_slug = request.args.get("type")
    parent_id = request.args.get("parent_id")
    category_id = request.args.get("category_id", type=int)
    search = request.args.get("search")
    sort_by = request.args.get("sort", "name")
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int)

    # Handle "root" as special parent_id value
    if parent_id and parent_id != "root":
        parent_id = int(parent_id)

    entities = current_app.db.get_entities(
        project_id,
        type_slug=type_slug,
        parent_entity_id=parent_id,
        category_id=category_id,
        search=search,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return jsonify(entities)


@entities_bp.route("/api/entities/<int:entity_id>")
def get_entity(entity_id):
    """Get a single entity with attributes and counts."""
    entity = current_app.db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": "Not found"}), 404
    return jsonify(entity)


@entities_bp.route("/api/entities", methods=["POST"])
def create_entity():
    """Create a new entity."""
    data = request.json or {}
    project_id = data.get("project_id")
    type_slug = data.get("type")
    name = data.get("name", "").strip()

    if not project_id or not type_slug or not name:
        return jsonify({"error": "project_id, type, and name are required"}), 400

    parent_id = data.get("parent_id")
    category_id = data.get("category_id")
    attributes = data.get("attributes", {})

    entity_id = current_app.db.create_entity(
        project_id, type_slug, name,
        parent_entity_id=parent_id,
        category_id=category_id,
        attributes=attributes,
    )

    entity = current_app.db.get_entity(entity_id)
    return jsonify(entity), 201


@entities_bp.route("/api/entities/<int:entity_id>", methods=["POST"])
def update_entity(entity_id):
    """Update an entity's core fields."""
    data = request.json or {}

    entity = current_app.db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": "Not found"}), 404

    fields = {}
    if "name" in data:
        fields["name"] = data["name"]
    if "category_id" in data:
        fields["category_id"] = data["category_id"]
    if "parent_id" in data:
        fields["parent_entity_id"] = data["parent_id"]
    if "is_starred" in data:
        fields["is_starred"] = 1 if data["is_starred"] else 0

    if fields:
        current_app.db.update_entity(entity_id, fields)

    # Update attributes if provided
    attributes = data.get("attributes", {})
    if attributes:
        source = data.get("source", "manual")
        current_app.db.set_entity_attributes(entity_id, attributes, source=source)

    return jsonify(current_app.db.get_entity(entity_id))


@entities_bp.route("/api/entities/<int:entity_id>", methods=["DELETE"])
def delete_entity(entity_id):
    """Soft-delete an entity (cascades to children)."""
    cascade = request.args.get("cascade", "true").lower() != "false"
    current_app.db.delete_entity(entity_id, cascade=cascade)
    return jsonify({"status": "ok"})


@entities_bp.route("/api/entities/<int:entity_id>/restore", methods=["POST"])
def restore_entity(entity_id):
    """Restore a soft-deleted entity."""
    current_app.db.restore_entity(entity_id)
    return jsonify({"status": "ok"})


@entities_bp.route("/api/entities/<int:entity_id>/star", methods=["POST"])
def toggle_star(entity_id):
    """Toggle the starred status of an entity."""
    entity = current_app.db.get_entity(entity_id)
    if not entity:
        return jsonify({"error": "Not found"}), 404

    new_val = 0 if entity.get("is_starred") else 1
    current_app.db.update_entity(entity_id, {"is_starred": new_val})
    return jsonify({"is_starred": bool(new_val)})


# ═══════════════════════════════════════════════════════════════
# Entity Attributes
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/entities/<int:entity_id>/attributes", methods=["POST"])
def set_attributes(entity_id):
    """Set one or more attributes on an entity."""
    data = request.json or {}
    attributes = data.get("attributes", {})
    source = data.get("source", "manual")
    confidence = data.get("confidence")
    snapshot_id = data.get("snapshot_id")

    if not attributes:
        return jsonify({"error": "attributes dict is required"}), 400

    current_app.db.set_entity_attributes(
        entity_id, attributes,
        source=source, confidence=confidence,
        snapshot_id=snapshot_id,
    )
    return jsonify({"status": "ok"})


@entities_bp.route("/api/entities/<int:entity_id>/attributes/<attr_slug>/history")
def attribute_history(entity_id, attr_slug):
    """Get historical values for an attribute."""
    limit = request.args.get("limit", 50, type=int)
    history = current_app.db.get_entity_attribute_history(entity_id, attr_slug, limit=limit)
    return jsonify(history)


@entities_bp.route("/api/entities/<int:entity_id>/attributes/at")
def attributes_at_time(entity_id):
    """Get all attributes as they were at a specific point in time."""
    at_date = request.args.get("date")
    if not at_date:
        return jsonify({"error": "date parameter is required"}), 400

    attrs = current_app.db.get_entity_attributes_at(entity_id, at_date)
    return jsonify(attrs)


# ═══════════════════════════════════════════════════════════════
# Entity Relationships
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/entities/<int:entity_id>/relationships")
def list_relationships(entity_id):
    """Get relationships for an entity."""
    direction = request.args.get("direction", "both")
    rels = current_app.db.get_entity_relationships(entity_id, direction=direction)
    return jsonify(rels)


@entities_bp.route("/api/entity-relationships", methods=["POST"])
def create_relationship():
    """Create a relationship between two entities."""
    data = request.json or {}
    from_id = data.get("from_id")
    to_id = data.get("to_id")
    rel_type = data.get("type")

    if not from_id or not to_id or not rel_type:
        return jsonify({"error": "from_id, to_id, and type are required"}), 400

    current_app.db.create_entity_relationship(
        from_id, to_id, rel_type,
        metadata=data.get("metadata"),
    )
    return jsonify({"status": "ok"}), 201


@entities_bp.route("/api/entity-relationships/<int:rel_id>", methods=["DELETE"])
def delete_relationship(rel_id):
    """Delete a relationship."""
    current_app.db.delete_entity_relationship(rel_id)
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════════════════════
# Evidence
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/entities/<int:entity_id>/evidence")
def list_evidence(entity_id):
    """Get evidence for an entity."""
    evidence_type = request.args.get("type")
    source_name = request.args.get("source")
    limit = request.args.get("limit", 100, type=int)

    evidence = current_app.db.get_evidence(
        entity_id=entity_id,
        evidence_type=evidence_type,
        source_name=source_name,
        limit=limit,
    )
    return jsonify(evidence)


@entities_bp.route("/api/evidence", methods=["POST"])
def add_evidence():
    """Add evidence linked to an entity."""
    data = request.json or {}
    entity_id = data.get("entity_id")
    evidence_type = data.get("type")
    file_path = data.get("file_path")

    if not entity_id or not evidence_type or not file_path:
        return jsonify({"error": "entity_id, type, and file_path are required"}), 400

    ev_id = current_app.db.add_evidence(
        entity_id, evidence_type, file_path,
        source_url=data.get("source_url"),
        source_name=data.get("source_name"),
        metadata=data.get("metadata"),
    )
    return jsonify({"id": ev_id}), 201


@entities_bp.route("/api/evidence/<int:evidence_id>", methods=["DELETE"])
def delete_evidence(evidence_id):
    """Delete evidence record."""
    current_app.db.delete_evidence(evidence_id)
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════════════════════
# Snapshots
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/snapshots")
def list_snapshots():
    """List capture snapshots for a project."""
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    return jsonify(current_app.db.get_snapshots(project_id))


@entities_bp.route("/api/snapshots", methods=["POST"])
def create_snapshot():
    """Create a new capture snapshot."""
    data = request.json or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    sid = current_app.db.create_snapshot(project_id, description=data.get("description"))
    return jsonify({"id": sid}), 201


# ═══════════════════════════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/entity-stats")
def entity_stats():
    """Get entity counts per type for a project."""
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    return jsonify(current_app.db.get_entity_stats(project_id))
