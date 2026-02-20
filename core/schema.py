"""Schema system for the Research Workbench.

Each project has a configurable entity schema that defines:
- Entity types (e.g. Company, Product, Plan, Tier, Feature)
- Attributes per type (name, data_type, required, etc.)
- Hierarchy relationships (parent-child between types)
- Graph relationships (many-to-many between types)

Schemas are stored as JSON in the project record and in
a dedicated `entity_type_defs` table for query efficiency.
"""

import json
import re
from copy import deepcopy

# Supported attribute data types
ATTRIBUTE_TYPES = {
    "text",       # Free text string
    "number",     # Numeric (integer or float)
    "boolean",    # True/False
    "currency",   # Numeric with currency context
    "enum",       # One of a fixed set of values
    "url",        # URL string
    "date",       # ISO date string
    "json",       # Arbitrary JSON
    "image_ref",  # Reference to evidence image
    "tags",       # JSON array of strings
}

# Default "Company" schema — matches the existing flat model
# so that existing projects migrate seamlessly
DEFAULT_COMPANY_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company or organisation in the research scope",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "URL", "slug": "url", "data_type": "url", "required": True},
                {"name": "What they do", "slug": "what", "data_type": "text"},
                {"name": "Target market", "slug": "target", "data_type": "text"},
                {"name": "Products", "slug": "products", "data_type": "text"},
                {"name": "Funding", "slug": "funding", "data_type": "text"},
                {"name": "Geography", "slug": "geography", "data_type": "text"},
                {"name": "TAM", "slug": "tam", "data_type": "text"},
                {"name": "Employee range", "slug": "employee_range", "data_type": "text"},
                {"name": "Founded year", "slug": "founded_year", "data_type": "number"},
                {"name": "Funding stage", "slug": "funding_stage", "data_type": "text"},
                {"name": "Total funding (USD)", "slug": "total_funding_usd", "data_type": "currency"},
                {"name": "HQ city", "slug": "hq_city", "data_type": "text"},
                {"name": "HQ country", "slug": "hq_country", "data_type": "text"},
                {"name": "LinkedIn URL", "slug": "linkedin_url", "data_type": "url"},
                {"name": "Business model", "slug": "business_model", "data_type": "text"},
                {"name": "Company stage", "slug": "company_stage", "data_type": "text"},
                {"name": "Primary focus", "slug": "primary_focus", "data_type": "text"},
                {"name": "Pricing model", "slug": "pricing_model", "data_type": "text"},
                {"name": "Pricing B2C low", "slug": "pricing_b2c_low", "data_type": "currency"},
                {"name": "Pricing B2C high", "slug": "pricing_b2c_high", "data_type": "currency"},
                {"name": "Pricing B2B low", "slug": "pricing_b2b_low", "data_type": "currency"},
                {"name": "Pricing B2B high", "slug": "pricing_b2b_high", "data_type": "currency"},
                {"name": "Has free tier", "slug": "has_free_tier", "data_type": "boolean"},
                {"name": "Revenue model", "slug": "revenue_model", "data_type": "text"},
                {"name": "Pricing tiers", "slug": "pricing_tiers", "data_type": "json"},
                {"name": "Pricing notes", "slug": "pricing_notes", "data_type": "text"},
            ],
        }
    ],
    "relationships": [],
}

# Project templates
SCHEMA_TEMPLATES = {
    "blank": {
        "name": "Blank Project",
        "description": "Start with a single Company entity type. Add more as needed.",
        "schema": DEFAULT_COMPANY_SCHEMA,
    },
    "market_analysis": {
        "name": "Market Analysis",
        "description": "Company-level analysis with competitive positioning and market signals.",
        "schema": {
            "version": 1,
            "entity_types": [
                {
                    "name": "Company",
                    "slug": "company",
                    "description": "A company in the market",
                    "icon": "building",
                    "parent_type": None,
                    "attributes": [
                        {"name": "URL", "slug": "url", "data_type": "url", "required": True},
                        {"name": "What they do", "slug": "what", "data_type": "text"},
                        {"name": "Target market", "slug": "target", "data_type": "text"},
                        {"name": "Products", "slug": "products", "data_type": "text"},
                        {"name": "Funding", "slug": "funding", "data_type": "text"},
                        {"name": "Geography", "slug": "geography", "data_type": "text"},
                        {"name": "TAM", "slug": "tam", "data_type": "text"},
                        {"name": "Employee range", "slug": "employee_range", "data_type": "text"},
                        {"name": "Founded year", "slug": "founded_year", "data_type": "number"},
                        {"name": "Funding stage", "slug": "funding_stage", "data_type": "text"},
                        {"name": "Total funding (USD)", "slug": "total_funding_usd", "data_type": "currency"},
                        {"name": "HQ city", "slug": "hq_city", "data_type": "text"},
                        {"name": "HQ country", "slug": "hq_country", "data_type": "text"},
                        {"name": "LinkedIn URL", "slug": "linkedin_url", "data_type": "url"},
                        {"name": "Business model", "slug": "business_model", "data_type": "text"},
                        {"name": "Company stage", "slug": "company_stage", "data_type": "text"},
                        {"name": "Primary focus", "slug": "primary_focus", "data_type": "text"},
                    ],
                },
            ],
            "relationships": [],
        },
    },
    "product_analysis": {
        "name": "Product Analysis",
        "description": "Deep product teardown: Company > Product > Plan > Tier > Feature.",
        "schema": {
            "version": 1,
            "entity_types": [
                {
                    "name": "Company",
                    "slug": "company",
                    "description": "A company offering products in this market",
                    "icon": "building",
                    "parent_type": None,
                    "attributes": [
                        {"name": "URL", "slug": "url", "data_type": "url", "required": True},
                        {"name": "What they do", "slug": "what", "data_type": "text"},
                        {"name": "Target market", "slug": "target", "data_type": "text"},
                        {"name": "Geography", "slug": "geography", "data_type": "text"},
                        {"name": "Employee range", "slug": "employee_range", "data_type": "text"},
                        {"name": "Founded year", "slug": "founded_year", "data_type": "number"},
                        {"name": "Funding stage", "slug": "funding_stage", "data_type": "text"},
                        {"name": "Total funding (USD)", "slug": "total_funding_usd", "data_type": "currency"},
                        {"name": "HQ city", "slug": "hq_city", "data_type": "text"},
                        {"name": "HQ country", "slug": "hq_country", "data_type": "text"},
                    ],
                },
                {
                    "name": "Product",
                    "slug": "product",
                    "description": "A distinct product or service offered by a company",
                    "icon": "package",
                    "parent_type": "company",
                    "attributes": [
                        {"name": "Name", "slug": "name", "data_type": "text", "required": True},
                        {"name": "Description", "slug": "description", "data_type": "text"},
                        {"name": "Platform", "slug": "platform", "data_type": "text"},
                        {"name": "Category", "slug": "category", "data_type": "text"},
                        {"name": "App Store rating", "slug": "app_store_rating", "data_type": "number"},
                        {"name": "URL", "slug": "url", "data_type": "url"},
                    ],
                },
                {
                    "name": "Plan",
                    "slug": "plan",
                    "description": "A product plan or package",
                    "icon": "layers",
                    "parent_type": "product",
                    "attributes": [
                        {"name": "Name", "slug": "name", "data_type": "text", "required": True},
                        {"name": "Target segment", "slug": "target_segment", "data_type": "text"},
                        {"name": "Description", "slug": "description", "data_type": "text"},
                    ],
                },
                {
                    "name": "Tier",
                    "slug": "tier",
                    "description": "A pricing tier within a plan",
                    "icon": "tag",
                    "parent_type": "plan",
                    "attributes": [
                        {"name": "Name", "slug": "name", "data_type": "text", "required": True},
                        {"name": "Headline price", "slug": "headline_price", "data_type": "currency"},
                        {"name": "Price period", "slug": "price_period", "data_type": "text"},
                        {"name": "Description", "slug": "description", "data_type": "text"},
                    ],
                },
                {
                    "name": "Feature",
                    "slug": "feature",
                    "description": "A feature or service within a tier",
                    "icon": "check-circle",
                    "parent_type": "tier",
                    "attributes": [
                        {"name": "Name", "slug": "name", "data_type": "text", "required": True},
                        {"name": "Included", "slug": "included", "data_type": "boolean"},
                        {"name": "Limit", "slug": "limit", "data_type": "text"},
                        {"name": "Excess", "slug": "excess", "data_type": "currency"},
                        {"name": "Notes", "slug": "notes", "data_type": "text"},
                    ],
                },
            ],
            "relationships": [],
        },
    },
    "design_research": {
        "name": "Design Research",
        "description": "Analyse design principles and patterns across products.",
        "schema": {
            "version": 1,
            "entity_types": [
                {
                    "name": "Product",
                    "slug": "product",
                    "description": "An app or website being studied for design quality",
                    "icon": "smartphone",
                    "parent_type": None,
                    "attributes": [
                        {"name": "Name", "slug": "name", "data_type": "text", "required": True},
                        {"name": "URL", "slug": "url", "data_type": "url"},
                        {"name": "Platform", "slug": "platform", "data_type": "text"},
                        {"name": "Design studio", "slug": "design_studio", "data_type": "text"},
                        {"name": "Launch year", "slug": "launch_year", "data_type": "number"},
                        {"name": "Category", "slug": "category", "data_type": "text"},
                    ],
                },
                {
                    "name": "Design Principle",
                    "slug": "design-principle",
                    "description": "An abstract design pattern or principle observed across products",
                    "icon": "palette",
                    "parent_type": None,
                    "attributes": [
                        {"name": "Name", "slug": "name", "data_type": "text", "required": True},
                        {"name": "Category", "slug": "category", "data_type": "enum",
                         "enum_values": ["interaction", "layout", "typography", "motion", "colour", "navigation", "information-architecture", "accessibility", "other"]},
                        {"name": "Description", "slug": "description", "data_type": "text"},
                        {"name": "Maturity", "slug": "maturity", "data_type": "enum",
                         "enum_values": ["emerging", "established", "declining"]},
                        {"name": "Scope", "slug": "scope", "data_type": "enum",
                         "enum_values": ["screen-level", "flow-level", "system-level"]},
                    ],
                },
            ],
            "relationships": [
                {
                    "name": "demonstrates",
                    "from_type": "product",
                    "to_type": "design-principle",
                    "description": "Product demonstrates a design principle",
                },
            ],
        },
    },
}


def make_slug(name):
    """Convert a name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


def validate_schema(schema):
    """Validate a schema definition. Returns (is_valid, errors)."""
    errors = []

    if not isinstance(schema, dict):
        return False, ["Schema must be a dictionary"]

    if "entity_types" not in schema:
        errors.append("Schema must have 'entity_types'")
        return False, errors

    if not isinstance(schema["entity_types"], list) or len(schema["entity_types"]) == 0:
        errors.append("Schema must have at least one entity type")
        return False, errors

    slugs_seen = set()
    type_slugs = set()

    for et in schema["entity_types"]:
        if "name" not in et or not et["name"]:
            errors.append("Every entity type must have a 'name'")
            continue

        slug = et.get("slug", make_slug(et["name"]))
        if slug in slugs_seen:
            errors.append(f"Duplicate entity type slug: '{slug}'")
        slugs_seen.add(slug)
        type_slugs.add(slug)

        if et.get("parent_type") and et["parent_type"] not in type_slugs and et["parent_type"] not in {
            e.get("slug", make_slug(e.get("name", ""))) for e in schema["entity_types"]
        }:
            errors.append(f"Entity type '{et['name']}' references unknown parent_type '{et['parent_type']}'")

        attrs = et.get("attributes", [])
        attr_slugs = set()
        for attr in attrs:
            if "name" not in attr or not attr["name"]:
                errors.append(f"Entity type '{et['name']}' has an attribute without a name")
                continue
            a_slug = attr.get("slug", make_slug(attr["name"]))
            if a_slug in attr_slugs:
                errors.append(f"Duplicate attribute slug '{a_slug}' in entity type '{et['name']}'")
            attr_slugs.add(a_slug)

            dt = attr.get("data_type", "text")
            if dt not in ATTRIBUTE_TYPES:
                errors.append(f"Unknown data_type '{dt}' for attribute '{attr['name']}' in '{et['name']}'")

            if dt == "enum" and not attr.get("enum_values"):
                errors.append(f"Enum attribute '{attr['name']}' in '{et['name']}' needs 'enum_values'")

    # Validate relationships
    for rel in schema.get("relationships", []):
        if "from_type" not in rel or "to_type" not in rel:
            errors.append("Relationships need 'from_type' and 'to_type'")
            continue
        all_slugs = {e.get("slug", make_slug(e.get("name", ""))) for e in schema["entity_types"]}
        if rel["from_type"] not in all_slugs:
            errors.append(f"Relationship from_type '{rel['from_type']}' not found in entity types")
        if rel["to_type"] not in all_slugs:
            errors.append(f"Relationship to_type '{rel['to_type']}' not found in entity types")

    return len(errors) == 0, errors


def normalize_schema(schema):
    """Ensure all entity types and attributes have slugs, fill defaults."""
    schema = deepcopy(schema)
    schema.setdefault("version", 1)
    schema.setdefault("relationships", [])

    for et in schema["entity_types"]:
        et.setdefault("slug", make_slug(et["name"]))
        et.setdefault("description", "")
        et.setdefault("icon", "circle")
        et.setdefault("parent_type", None)
        et.setdefault("attributes", [])

        for attr in et["attributes"]:
            attr.setdefault("slug", make_slug(attr["name"]))
            attr.setdefault("data_type", "text")
            attr.setdefault("required", False)

    for rel in schema["relationships"]:
        rel.setdefault("name", f"{rel['from_type']}_to_{rel['to_type']}")
        rel.setdefault("description", "")

    return schema


def get_entity_type_def(schema, type_slug):
    """Get an entity type definition by slug from a schema."""
    for et in schema.get("entity_types", []):
        if et.get("slug") == type_slug:
            return et
    return None


def get_root_types(schema):
    """Get entity types that have no parent (top-level)."""
    return [et for et in schema.get("entity_types", []) if not et.get("parent_type")]


def get_child_types(schema, parent_type_slug):
    """Get entity types whose parent_type matches the given slug."""
    return [et for et in schema.get("entity_types", [])
            if et.get("parent_type") == parent_type_slug]


def get_type_hierarchy(schema):
    """Return the hierarchy as a nested dict. Useful for UI rendering.

    Returns: [{"type": {...}, "children": [{"type": {...}, "children": [...]}, ...]}, ...]
    """
    def _build_tree(parent_slug):
        children = get_child_types(schema, parent_slug)
        return [
            {"type": child, "children": _build_tree(child["slug"])}
            for child in children
        ]

    roots = get_root_types(schema)
    return [
        {"type": root, "children": _build_tree(root["slug"])}
        for root in roots
    ]


def add_entity_type(schema, entity_type_def):
    """Add a new entity type to a schema. Returns updated schema."""
    schema = deepcopy(schema)
    entity_type_def = deepcopy(entity_type_def)
    entity_type_def.setdefault("slug", make_slug(entity_type_def["name"]))
    entity_type_def.setdefault("attributes", [])
    entity_type_def.setdefault("parent_type", None)
    entity_type_def.setdefault("icon", "circle")
    entity_type_def.setdefault("description", "")

    for attr in entity_type_def["attributes"]:
        attr.setdefault("slug", make_slug(attr["name"]))
        attr.setdefault("data_type", "text")
        attr.setdefault("required", False)

    # Check for duplicate slug
    existing_slugs = {et["slug"] for et in schema["entity_types"]}
    if entity_type_def["slug"] in existing_slugs:
        raise ValueError(f"Entity type slug '{entity_type_def['slug']}' already exists")

    schema["entity_types"].append(entity_type_def)
    return schema


def add_attribute(schema, type_slug, attribute_def):
    """Add a new attribute to an entity type. Returns updated schema."""
    schema = deepcopy(schema)
    et = get_entity_type_def(schema, type_slug)
    if not et:
        raise ValueError(f"Entity type '{type_slug}' not found")

    attribute_def = deepcopy(attribute_def)
    attribute_def.setdefault("slug", make_slug(attribute_def["name"]))
    attribute_def.setdefault("data_type", "text")
    attribute_def.setdefault("required", False)

    existing_slugs = {a["slug"] for a in et["attributes"]}
    if attribute_def["slug"] in existing_slugs:
        raise ValueError(f"Attribute slug '{attribute_def['slug']}' already exists in '{type_slug}'")

    et["attributes"].append(attribute_def)
    return schema


def add_relationship(schema, relationship_def):
    """Add a new relationship between entity types. Returns updated schema."""
    schema = deepcopy(schema)
    relationship_def = deepcopy(relationship_def)
    relationship_def.setdefault("name", f"{relationship_def['from_type']}_to_{relationship_def['to_type']}")
    relationship_def.setdefault("description", "")

    schema.setdefault("relationships", [])
    schema["relationships"].append(relationship_def)
    return schema
