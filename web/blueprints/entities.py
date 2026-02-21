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

from config import RESEARCH_MODEL
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
            model=RESEARCH_MODEL,
            timeout=90,
            json_schema=schema_spec,
            operation="entity_inference",
        )

        if result.get("is_error"):
            # Fall back to rule-based suggestion
            return _rule_based_schema_suggestion(description, base_template)

        structured = result.get("structured_output")
        if not structured or "schema" not in structured:
            return _rule_based_schema_suggestion(description, base_template)

        suggested = structured["schema"]
        suggested = normalize_schema(suggested)
        valid, errors = validate_schema(suggested)

        if not valid:
            return _rule_based_schema_suggestion(description, base_template)

        return jsonify({
            "schema": suggested,
            "explanation": structured.get("explanation", ""),
            "cost_usd": result.get("cost_usd", 0),
        })

    except Exception as e:
        logger.warning("AI schema suggestion failed, using rule-based: %s", e)
        return _rule_based_schema_suggestion(description, base_template)


def _rule_based_schema_suggestion(description: str, base_template: str):
    """Generate a reasonable schema from the template + keyword analysis when AI is unavailable."""
    import re

    desc_lower = description.lower()
    tmpl = SCHEMA_TEMPLATES.get(base_template, SCHEMA_TEMPLATES["blank"])

    # Start with template schema
    schema = {
        "version": 1,
        "entity_types": [dict(et) for et in tmpl.get("entity_types", [])],
        "relationships": list(tmpl.get("relationships", [])),
    }

    # Add extra attributes based on keywords in description
    extra_attrs = []
    if any(w in desc_lower for w in ["price", "pricing", "cost", "plan", "tier"]):
        extra_attrs.append({"name": "Pricing Model", "slug": "pricing_model", "data_type": "text"})
        extra_attrs.append({"name": "Price Range", "slug": "price_range", "data_type": "text"})
    if any(w in desc_lower for w in ["region", "country", "geography", "uk", "eu", "us", "global"]):
        extra_attrs.append({"name": "Region", "slug": "region", "data_type": "text"})
        extra_attrs.append({"name": "Countries", "slug": "countries", "data_type": "tags"})
    if any(w in desc_lower for w in ["competitor", "competitive", "market share"]):
        extra_attrs.append({"name": "Market Position", "slug": "market_position", "data_type": "text"})
    if any(w in desc_lower for w in ["product", "service", "feature"]):
        extra_attrs.append({"name": "Key Features", "slug": "key_features", "data_type": "tags"})
        extra_attrs.append({"name": "Target Audience", "slug": "target_audience", "data_type": "text"})

    # Merge extra attrs into the first entity type
    if schema["entity_types"] and extra_attrs:
        existing_slugs = {a["slug"] for a in schema["entity_types"][0].get("attributes", [])}
        for attr in extra_attrs:
            if attr["slug"] not in existing_slugs:
                schema["entity_types"][0].setdefault("attributes", []).append(attr)

    # Try to extract a domain name from the description for the explanation
    words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', description)
    domain = words[0] if words else "your research"

    schema = normalize_schema(schema)

    return jsonify({
        "schema": schema,
        "explanation": f"Rule-based suggestion for {domain} research (AI was unavailable). "
                       f"Based on the '{tmpl['name']}' template with extra attributes detected from your description. "
                       f"You can refine this schema after creating the project.",
        "cost_usd": 0,
        "fallback": True,
    })


@entities_bp.route("/api/schema/refine", methods=["POST"])
def refine_schema():
    """AI-powered schema refinement with challenges and suggestions.

    Input: {
        project_id: int,
        current_schema: dict,
        research_goal: str,
        feedback: str (optional — user feedback on previous suggestions)
    }
    Output: {
        suggestions: [...],
        challenges: [...],
        completeness_score: float,
        completeness_areas: {...}
    }
    """
    data = request.json or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    current_schema = data.get("current_schema")
    if not current_schema:
        # Try to load from project
        project = current_app.db.get_project(project_id)
        if project and project.get("entity_schema"):
            current_schema = json.loads(project["entity_schema"]) if isinstance(
                project["entity_schema"], str
            ) else project["entity_schema"]
        if not current_schema:
            return jsonify({"error": "current_schema is required"}), 400

    research_goal = data.get("research_goal", "").strip()
    feedback = data.get("feedback", "").strip()

    # Try AI-powered refinement first, fall back to rule-based
    try:
        result = _ai_refine_schema(current_schema, research_goal, feedback, project_id)
        return jsonify(result)
    except Exception as e:
        logger.warning("AI schema refinement failed, using rule-based: %s", e)
        result = _rule_based_refine(current_schema, research_goal)
        return jsonify(result)


def _ai_refine_schema(current_schema, research_goal, feedback, project_id=None):
    """Use LLM to analyse and suggest schema improvements."""
    from core.llm import run_cli

    schema_json = json.dumps(current_schema, indent=2)

    prompt = f"""You are a research methodology expert reviewing an entity schema for a research workbench.

CURRENT SCHEMA:
{schema_json}

RESEARCH GOAL: {research_goal or "(not specified)"}

{f"USER FEEDBACK ON PREVIOUS SUGGESTIONS: {feedback}" if feedback else ""}

Analyse this schema critically. Your job is to:

1. CHALLENGE assumptions — identify gaps, missing entity types, under-specified attributes, and structural weaknesses.
2. SUGGEST 3-6 specific improvements ranked by impact on research quality. Each suggestion must be one of these types:
   - add_type: Add a new entity type (include full definition with attributes)
   - add_attribute: Add a new attribute to an existing type
   - modify_attribute: Change an existing attribute (e.g. text to enum, add enum_values)
   - add_relationship: Add a relationship between entity types
   - remove_attribute: Suggest removing a low-value attribute
3. SCORE completeness across 4 dimensions (0.0 to 1.0):
   - entity_coverage: Are all relevant things being tracked?
   - attribute_depth: Are attributes rich enough for analysis?
   - relationship_richness: Are connections between entities captured?
   - analysis_readiness: Could you run competitive/product/temporal analysis with this data?

Rules:
- Available data_types: text, number, boolean, currency, enum, url, date, json, image_ref, tags
- Enum attributes need enum_values array
- Each entity type needs a slug (lowercase, hyphenated)
- schema_change must be a concrete, applicable change dict
- Be specific and opinionated — don't just say "add more attributes", say exactly which ones and why
- If the research goal mentions a specific domain (insurance, fintech, healthcare), tailor suggestions to that domain"""

    refine_schema_spec = {
        "type": "object",
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["add_type", "add_attribute", "modify_attribute",
                                     "add_relationship", "remove_attribute"]
                        },
                        "target": {"type": ["string", "null"]},
                        "suggestion": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "schema_change": {"type": "object"}
                    },
                    "required": ["type", "suggestion", "reasoning", "schema_change"]
                }
            },
            "challenges": {
                "type": "array",
                "items": {"type": "string"}
            },
            "completeness_score": {"type": "number"},
            "completeness_areas": {
                "type": "object",
                "properties": {
                    "entity_coverage": {"type": "number"},
                    "attribute_depth": {"type": "number"},
                    "relationship_richness": {"type": "number"},
                    "analysis_readiness": {"type": "number"}
                },
                "required": ["entity_coverage", "attribute_depth",
                             "relationship_richness", "analysis_readiness"]
            }
        },
        "required": ["suggestions", "challenges", "completeness_score", "completeness_areas"]
    }

    result = run_cli(
        prompt=prompt,
        model=RESEARCH_MODEL,
        timeout=90,
        json_schema=refine_schema_spec,
        project_id=project_id, operation="schema_refinement",
    )

    if result.get("is_error"):
        raise RuntimeError(result.get("result", "LLM call failed"))

    structured = result.get("structured_output")
    if not structured:
        raise RuntimeError("LLM did not return structured output")

    # Clamp scores to 0-1
    structured["completeness_score"] = max(0.0, min(1.0, structured.get("completeness_score", 0.5)))
    areas = structured.get("completeness_areas", {})
    for key in ["entity_coverage", "attribute_depth", "relationship_richness", "analysis_readiness"]:
        areas[key] = max(0.0, min(1.0, areas.get(key, 0.5)))
    structured["completeness_areas"] = areas

    structured["cost_usd"] = result.get("cost_usd", 0)
    return structured


def _rule_based_refine(current_schema, research_goal):
    """Fallback: analyse schema with deterministic rules when LLM unavailable."""
    entity_types = current_schema.get("entity_types", [])
    relationships = current_schema.get("relationships", [])
    suggestions = []
    challenges = []

    # Common useful attributes that schemas often miss
    common_attrs = {
        "website": {"name": "Website", "slug": "website", "data_type": "url"},
        "description": {"name": "Description", "slug": "description", "data_type": "text"},
        "url": {"name": "URL", "slug": "url", "data_type": "url"},
        "founded_year": {"name": "Founded Year", "slug": "founded_year", "data_type": "number"},
        "hq_country": {"name": "HQ Country", "slug": "hq_country", "data_type": "text"},
    }

    # 1. Check entity type count
    type_count = len(entity_types)
    if type_count < 2:
        challenges.append(
            "Your schema has only one entity type — consider whether you need"
            " sub-entities (e.g. Products under Companies, or Features under Products)"
            " to capture hierarchical structure."
        )
        # Suggest adding a child type
        if entity_types:
            parent = entity_types[0]
            suggestions.append({
                "type": "add_type",
                "target": None,
                "suggestion": f"Add a child entity type under '{parent['name']}'",
                "reasoning": (
                    "A single entity type limits your ability to do hierarchical analysis."
                    " Adding a child type lets you drill down into sub-components."
                ),
                "schema_change": {
                    "slug": "sub-item",
                    "name": "Sub-Item",
                    "parent_type": parent.get("slug", ""),
                    "description": f"A sub-component of {parent['name']}",
                    "icon": "layers",
                    "attributes": [
                        {"name": "Name", "slug": "name", "data_type": "text", "required": True},
                        {"name": "Description", "slug": "description", "data_type": "text"},
                    ],
                },
            })

    # 2. Check attribute depth per type
    for et in entity_types:
        attrs = et.get("attributes", [])
        attr_slugs = {a.get("slug", "") for a in attrs}
        type_name = et.get("name", "Unknown")

        if len(attrs) < 3:
            challenges.append(
                f"Entity type '{type_name}' has only {len(attrs)} attribute(s)"
                " — this is quite sparse for meaningful analysis."
            )
            # Suggest common missing attributes
            for slug, attr_def in common_attrs.items():
                if slug not in attr_slugs:
                    suggestions.append({
                        "type": "add_attribute",
                        "target": et.get("slug", ""),
                        "suggestion": f"Add '{attr_def['name']}' attribute to {type_name}",
                        "reasoning": f"'{attr_def['name']}' is a commonly useful attribute for research entities.",
                        "schema_change": {**attr_def, "required": False},
                    })
                    break  # Only suggest one per sparse type

        # 3. Check for missing common attributes
        if "url" not in attr_slugs and "website" not in attr_slugs:
            suggestions.append({
                "type": "add_attribute",
                "target": et.get("slug", ""),
                "suggestion": f"Add a URL/website attribute to {type_name}",
                "reasoning": "Without a URL, you cannot link entities to their web presence for evidence capture.",
                "schema_change": {"name": "URL", "slug": "url", "data_type": "url", "required": False},
            })

        # 4. Check for free-text attributes that could be enums
        for attr in attrs:
            name_lower = attr.get("name", "").lower()
            if attr.get("data_type") == "text" and any(
                kw in name_lower for kw in ["status", "stage", "model", "type", "category", "tier", "level"]
            ):
                suggestions.append({
                    "type": "modify_attribute",
                    "target": f"{et.get('slug', '')}.{attr.get('slug', '')}",
                    "suggestion": f"Consider changing '{attr['name']}' from free text to enum",
                    "reasoning": (
                        "Attributes like status, stage, or model usually have a finite set of values."
                        " Using an enum ensures consistency and enables filtering/grouping."
                    ),
                    "schema_change": {
                        "data_type": "enum",
                        "enum_values": ["(define values based on your domain)"],
                    },
                })

    # 5. Check relationships
    if len(entity_types) >= 2 and len(relationships) == 0:
        challenges.append(
            "No relationships defined between entity types."
            " Consider adding explicit relationships (e.g. competes_with, integrates_with)"
            " to enable graph analysis."
        )
        # Suggest a relationship between first two root types
        root_types = [et for et in entity_types if not et.get("parent_type")]
        if len(root_types) >= 2:
            suggestions.append({
                "type": "add_relationship",
                "target": None,
                "suggestion": f"Add a relationship between {root_types[0]['name']} and {root_types[1]['name']}",
                "reasoning": "Explicit relationships enable knowledge graph views and cross-entity analysis.",
                "schema_change": {
                    "from_type": root_types[0].get("slug", ""),
                    "to_type": root_types[1].get("slug", ""),
                    "relationship_type": "related_to",
                    "name": "related_to",
                },
            })

    # Score completeness
    entity_coverage = min(1.0, type_count / 4.0)  # 4 types = full coverage
    avg_attrs = (
        sum(len(et.get("attributes", [])) for et in entity_types) / max(type_count, 1)
    )
    attribute_depth = min(1.0, avg_attrs / 8.0)  # 8 attrs avg = full depth
    rel_count = len(relationships)
    relationship_richness = min(1.0, rel_count / 3.0)  # 3 rels = full richness
    analysis_readiness = (entity_coverage + attribute_depth + relationship_richness) / 3.0

    completeness_score = round(
        (entity_coverage + attribute_depth + relationship_richness + analysis_readiness) / 4.0, 2
    )
    completeness_areas = {
        "entity_coverage": round(entity_coverage, 2),
        "attribute_depth": round(attribute_depth, 2),
        "relationship_richness": round(relationship_richness, 2),
        "analysis_readiness": round(analysis_readiness, 2),
    }

    # Limit suggestions to 6
    suggestions = suggestions[:6]

    return {
        "suggestions": suggestions,
        "challenges": challenges,
        "completeness_score": completeness_score,
        "completeness_areas": completeness_areas,
    }


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
    if offset is not None:
        offset = max(0, offset)

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

    # Reject path traversal attempts
    if file_path and (".." in file_path or file_path.startswith("/") or file_path.startswith("\\")):
        return jsonify({"error": "Invalid file path"}), 400

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


# ═══════════════════════════════════════════════════════════════
# Company → Entity Migration
# ═══════════════════════════════════════════════════════════════

@entities_bp.route("/api/migrate/companies", methods=["POST"])
def migrate_companies():
    """Migrate companies from the legacy table into the entity system.

    Body: { project_id: int, dry_run: bool (optional, default false) }

    Returns migration stats including entities created, attributes migrated,
    and any errors encountered.
    """
    from core.migration import migrate_companies_to_entities

    data = request.json or {}
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    dry_run = data.get("dry_run", False)

    try:
        stats = migrate_companies_to_entities(
            current_app.db, project_id, dry_run=dry_run,
        )
        return jsonify({"status": "ok", "dry_run": dry_run, **stats})
    except Exception as e:
        logger.exception("Migration failed: %s", e)
        return jsonify({"error": "Internal server error"}), 500
