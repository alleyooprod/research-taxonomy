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


@entities_bp.route("/api/schema/suggest", methods=["POST"])
def suggest_schema():
    """AI-powered schema suggestion based on research description.

    Input: {description: str, template: str (optional starting point)}
    Output: {schema: {...}, explanation: str}
    """
    data = request.json or {}
    description = data.get("description", "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400

    base_template = data.get("template", "blank")
    if base_template not in SCHEMA_TEMPLATES:
        base_template = "blank"

    prompt = f"""You are a research methodology expert helping design a data schema for a research workbench.

The user wants to conduct research described as:
"{description}"

They've selected the "{SCHEMA_TEMPLATES[base_template]['name']}" template as a starting point.

Design an entity schema that captures the right data structure for this research.

Rules:
- Entity types represent the things being researched (companies, products, features, etc.)
- Use parent_type to create hierarchies (e.g. Company > Product > Feature)
- Use relationships for many-to-many connections (e.g. Product demonstrates Design Principle)
- Each entity type needs meaningful attributes with correct data_types
- Available data_types: text, number, boolean, currency, enum, url, date, json, image_ref, tags
- Enum attributes need enum_values array
- Keep it focused — 2-6 entity types is ideal
- Every entity type needs at least a name attribute"""

    schema_spec = {
        "type": "object",
        "properties": {
            "schema": {
                "type": "object",
                "properties": {
                    "version": {"type": "integer"},
                    "entity_types": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "slug": {"type": "string"},
                                "description": {"type": "string"},
                                "icon": {"type": "string"},
                                "parent_type": {"type": ["string", "null"]},
                                "attributes": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "slug": {"type": "string"},
                                            "data_type": {"type": "string"},
                                            "required": {"type": "boolean"},
                                            "enum_values": {"type": "array", "items": {"type": "string"}}
                                        },
                                        "required": ["name", "slug", "data_type"]
                                    }
                                }
                            },
                            "required": ["name", "slug"]
                        }
                    },
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "from_type": {"type": "string"},
                                "to_type": {"type": "string"},
                                "description": {"type": "string"}
                            },
                            "required": ["name", "from_type", "to_type"]
                        }
                    }
                },
                "required": ["entity_types"]
            },
            "explanation": {"type": "string"}
        },
        "required": ["schema", "explanation"]
    }

    try:
        from core.llm import run_cli
        result = run_cli(
            prompt=prompt,
            model="sonnet",
            timeout=60,
            json_schema=schema_spec,
        )

        if result.get("is_error"):
            return jsonify({"error": "AI suggestion failed", "detail": result.get("result", "")}), 500

        structured = result.get("structured_output")
        if not structured or "schema" not in structured:
            return jsonify({"error": "AI did not return a valid schema"}), 500

        suggested = structured["schema"]
        suggested = normalize_schema(suggested)
        valid, errors = validate_schema(suggested)

        if not valid:
            return jsonify({
                "error": "AI-generated schema has validation errors",
                "details": errors,
                "schema": suggested,
                "explanation": structured.get("explanation", ""),
            }), 422

        return jsonify({
            "schema": suggested,
            "explanation": structured.get("explanation", ""),
            "cost_usd": result.get("cost_usd", 0),
        })

    except Exception as e:
        logger.exception("Schema suggestion failed")
        return jsonify({"error": f"Schema suggestion failed: {str(e)}"}), 500


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
# Bulk Entity Operations
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/entities/bulk", methods=["POST"])
def bulk_entity_action():
    """Perform bulk operations on multiple entities.

    Actions: delete, star, unstar, set_category, set_attribute
    """
    data = request.json or {}
    entity_ids = data.get("ids", [])
    action = data.get("action")

    if not entity_ids or not action:
        return jsonify({"error": "ids and action are required"}), 400

    if not isinstance(entity_ids, list) or not all(isinstance(i, int) for i in entity_ids):
        return jsonify({"error": "ids must be a list of integers"}), 400

    affected = 0

    if action == "delete":
        cascade = data.get("cascade", True)
        for eid in entity_ids:
            current_app.db.delete_entity(eid, cascade=cascade)
            affected += 1

    elif action == "star":
        for eid in entity_ids:
            current_app.db.update_entity(eid, {"is_starred": 1})
            affected += 1

    elif action == "unstar":
        for eid in entity_ids:
            current_app.db.update_entity(eid, {"is_starred": 0})
            affected += 1

    elif action == "set_category":
        category_id = data.get("category_id")
        for eid in entity_ids:
            current_app.db.update_entity(eid, {"category_id": category_id})
            affected += 1

    elif action == "set_attribute":
        attr_slug = data.get("attr_slug")
        attr_value = data.get("attr_value")
        source = data.get("source", "manual")
        if not attr_slug:
            return jsonify({"error": "attr_slug is required for set_attribute"}), 400
        for eid in entity_ids:
            current_app.db.set_entity_attributes(eid, {attr_slug: attr_value}, source=source)
            affected += 1

    else:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    return jsonify({"status": "ok", "affected": affected})


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


# ═══════════════════════════════════════════════════════════════
# View Compatibility: Graph Data
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/entity-graph")
def entity_graph():
    """Get entities and relationships as graph nodes + edges for KG views.

    Returns: {nodes: [{id, name, type, attributes, ...}], edges: [{from, to, type, ...}]}
    """
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    type_slug = request.args.get("type")
    limit = request.args.get("limit", 200, type=int)

    entities = current_app.db.get_entities(
        project_id,
        type_slug=type_slug,
        limit=limit,
        include_attributes=True,
    )

    nodes = []
    all_entity_ids = {e["id"] for e in entities}

    for e in entities:
        node = {
            "id": f"entity-{e['id']}",
            "entity_id": e["id"],
            "name": e["name"],
            "type": e["type_slug"],
            "parent_entity_id": e.get("parent_entity_id"),
            "child_count": e.get("child_count", 0),
            "evidence_count": e.get("evidence_count", 0),
            "is_starred": e.get("is_starred", False),
            "category_id": e.get("category_id"),
        }
        # Flatten top-level attributes for display
        attrs = e.get("attributes", {})
        for attr_slug, attr_data in attrs.items():
            val = attr_data["value"] if isinstance(attr_data, dict) else attr_data
            node[f"attr_{attr_slug}"] = val
        nodes.append(node)

    # Collect edges: parent-child (hierarchy) + explicit relationships
    edges = []

    # Hierarchy edges
    for e in entities:
        if e.get("parent_entity_id") and e["parent_entity_id"] in all_entity_ids:
            edges.append({
                "source": f"entity-{e['parent_entity_id']}",
                "target": f"entity-{e['id']}",
                "type": "has_child",
                "label": "has",
            })

    # Explicit entity relationships
    for e in entities:
        try:
            rels = current_app.db.get_entity_relationships(e["id"], direction="outgoing")
            for rel in rels:
                if rel["to_entity_id"] in all_entity_ids:
                    edges.append({
                        "source": f"entity-{rel['from_entity_id']}",
                        "target": f"entity-{rel['to_entity_id']}",
                        "type": rel["relationship_type"],
                        "label": rel["relationship_type"],
                    })
        except Exception:
            pass

    return jsonify({"nodes": nodes, "edges": edges})


@entities_bp.route("/api/entity-locations")
def entity_locations():
    """Get entities with location data for map views.

    Returns entities that have any location-related attributes populated.
    """
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    type_slug = request.args.get("type")
    limit = request.args.get("limit", 500, type=int)

    entities = current_app.db.get_entities(
        project_id,
        type_slug=type_slug,
        limit=limit,
        include_attributes=True,
    )

    location_attrs = {"hq_city", "hq_country", "geography", "location", "city", "country", "address"}
    results = []

    for e in entities:
        attrs = e.get("attributes", {})
        # Check if entity has any location-related attribute
        has_location = False
        flat_attrs = {}
        for attr_slug, attr_data in attrs.items():
            val = attr_data["value"] if isinstance(attr_data, dict) else attr_data
            flat_attrs[attr_slug] = val
            if attr_slug in location_attrs and val:
                has_location = True

        if has_location:
            results.append({
                "id": e["id"],
                "name": e["name"],
                "type": e["type_slug"],
                "attributes": flat_attrs,
                "category_id": e.get("category_id"),
                "is_starred": e.get("is_starred", False),
            })

    return jsonify(results)
