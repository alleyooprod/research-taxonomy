"""Backwards-compatible company ↔ entity translation layer.

When a project has been migrated to the entity system (has entity_schema with
multi-type support OR has entities of type "company"), this module translates
between the flat company dict format that the frontend/CSV import expects and
the entity + entity_attributes format used by the new data layer.

Usage:
    from core.compat import project_uses_entities, entity_to_company, company_data_to_entity
"""
from core.migration import _COMPANY_FIELD_MAP

# Reverse map: attribute slug → company column name
_ATTR_TO_COMPANY = {v: k for k, v in _COMPANY_FIELD_MAP.items()}


def project_uses_entities(db, project_id):
    """Check whether a project has migrated to entity-based data.

    Returns True if the project has an entity_schema with entity_types
    that include a "company" type_slug (or any multi-type schema).
    """
    if not project_id:
        return False
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT entity_schema FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if not row or not row["entity_schema"]:
            return False
        import json
        try:
            schema = json.loads(row["entity_schema"])
        except (json.JSONDecodeError, TypeError):
            return False
        entity_types = schema.get("entity_types", [])
        # Multi-type schemas use entity system; single-type "company" schemas
        # may or may not — check if entities actually exist
        if len(entity_types) > 1:
            return True
        # For single-type, check if there are actual entities
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM entities WHERE project_id = ? AND is_deleted = 0",
            (project_id,),
        ).fetchone()["cnt"]
        return count > 0


def entity_to_company(entity_row, attributes):
    """Convert an entity + its attributes into a company-format dict.

    Args:
        entity_row: dict from entities table (id, name, type_slug, etc.)
        attributes: list of dicts from entity_attributes (attr_slug, value, ...)

    Returns:
        dict matching the company table format (id, name, url, what, etc.)
    """
    e = dict(entity_row)
    attr_map = {a["attr_slug"]: a["value"] for a in attributes}

    company = {
        "id": e["id"],
        "project_id": e["project_id"],
        "slug": e.get("slug", ""),
        "name": e["name"],
        "category_id": e.get("category_id"),
        "is_starred": e.get("is_starred", 0),
        "is_deleted": e.get("is_deleted", 0),
        "status": e.get("status", "active"),
        "confidence_score": e.get("confidence_score"),
        "tags": e.get("tags"),
        "raw_research": e.get("raw_research"),
        "created_at": e.get("created_at"),
        "updated_at": e.get("updated_at"),
    }

    # Map entity attributes back to company columns
    for attr_slug, value in attr_map.items():
        col_name = _ATTR_TO_COMPANY.get(attr_slug)
        if col_name:
            company[col_name] = value
        else:
            # Non-standard attributes go into a generic key
            company[attr_slug] = value

    # Ensure standard company columns exist even if NULL
    for col in ("url", "what", "target", "products", "funding", "geography",
                "tam", "logo_url", "employee_range", "founded_year",
                "funding_stage", "total_funding_usd", "hq_city", "hq_country",
                "linkedin_url", "business_model", "company_stage",
                "primary_focus", "pricing_model", "has_free_tier",
                "revenue_model", "pricing_tiers", "pricing_notes",
                "relationship_status", "relationship_note"):
        company.setdefault(col, None)

    # Parse tags if stored as JSON string
    if isinstance(company.get("tags"), str):
        import json
        try:
            company["tags"] = json.loads(company["tags"])
        except (json.JSONDecodeError, TypeError):
            company["tags"] = []

    return company


def company_data_to_entity(data, project_id):
    """Convert company-format input data to entity + attributes format.

    Args:
        data: dict with company field names (url, what, target, etc.)
        project_id: project ID

    Returns:
        tuple of (entity_fields, attributes_list)
        entity_fields: dict for entity creation (name, type_slug, etc.)
        attributes_list: list of (attr_slug, value) tuples
    """
    import json

    entity_fields = {
        "project_id": project_id,
        "type_slug": "company",
        "name": data.get("name", data.get("url", "")),
        "slug": data.get("slug", ""),
        "category_id": data.get("category_id"),
        "is_starred": data.get("is_starred", 0),
        "status": data.get("status", "active"),
        "confidence_score": data.get("confidence_score"),
        "raw_research": data.get("raw_research"),
    }

    # Handle tags
    tags = data.get("tags")
    if tags and not isinstance(tags, str):
        tags = json.dumps(tags)
    entity_fields["tags"] = tags

    # Extract attributes from company columns
    attributes = []
    for col, attr_slug in _COMPANY_FIELD_MAP.items():
        val = data.get(col)
        if val is not None:
            val_str = str(val).strip()
            if val_str:
                attributes.append((attr_slug, val_str))

    return entity_fields, attributes


def list_entities_as_companies(db, project_id, **filters):
    """Query entities and return them formatted as company dicts.

    Supports the same filter params as the company list endpoint.
    """
    with db._get_conn() as conn:
        conditions = ["e.project_id = ?", "e.is_deleted = 0", "e.type_slug = 'company'"]
        params = [project_id]

        if filters.get("category_id"):
            conditions.append("e.category_id = ?")
            params.append(filters["category_id"])

        if filters.get("starred_only"):
            conditions.append("e.is_starred = 1")

        if filters.get("search"):
            conditions.append("e.name LIKE ?")
            params.append(f"%{filters['search']}%")

        sort_by = filters.get("sort_by", "name")
        sort_dir = "DESC" if filters.get("sort_dir", "asc").lower() == "desc" else "ASC"
        sort_col = {
            "name": "e.name",
            "created_at": "e.created_at",
            "updated_at": "e.updated_at",
        }.get(sort_by, "e.name")

        offset = filters.get("offset", 0)

        sql = f"""SELECT e.* FROM entities e
                  WHERE {' AND '.join(conditions)}
                  ORDER BY {sort_col} {sort_dir}
                  LIMIT 200 OFFSET ?"""
        params.append(offset)

        entities = conn.execute(sql, params).fetchall()

        result = []
        for ent in entities:
            attrs = conn.execute(
                "SELECT attr_slug, value FROM entity_attributes WHERE entity_id = ?",
                (ent["id"],),
            ).fetchall()
            result.append(entity_to_company(ent, attrs))

        return result


def get_entity_as_company(db, entity_id):
    """Get a single entity formatted as a company dict."""
    with db._get_conn() as conn:
        entity = conn.execute(
            "SELECT * FROM entities WHERE id = ? AND is_deleted = 0",
            (entity_id,),
        ).fetchone()
        if not entity:
            return None
        attrs = conn.execute(
            "SELECT attr_slug, value FROM entity_attributes WHERE entity_id = ?",
            (entity_id,),
        ).fetchall()
        return entity_to_company(entity, attrs)


def create_entity_from_company_data(db, data, project_id):
    """Create an entity from company-format data. Returns entity ID."""
    entity_fields, attributes = company_data_to_entity(data, project_id)

    with db._get_conn() as conn:
        conn.execute(
            """INSERT INTO entities
               (project_id, type_slug, name, slug, category_id,
                is_starred, status, confidence_score, tags, raw_research,
                source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'api', datetime('now'), datetime('now'))""",
            (
                entity_fields["project_id"],
                entity_fields["type_slug"],
                entity_fields["name"],
                entity_fields.get("slug", ""),
                entity_fields.get("category_id"),
                entity_fields.get("is_starred", 0),
                entity_fields.get("status", "active"),
                entity_fields.get("confidence_score"),
                entity_fields.get("tags"),
                entity_fields.get("raw_research"),
            ),
        )
        entity_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for attr_slug, value in attributes:
            conn.execute(
                """INSERT INTO entity_attributes
                   (entity_id, attr_slug, value, source, captured_at)
                   VALUES (?, ?, ?, 'api', datetime('now'))""",
                (entity_id, attr_slug, value),
            )

        conn.commit()
        return entity_id


def update_entity_from_company_data(db, entity_id, fields):
    """Update an entity using company-format field names."""
    import json

    entity_updates = {}
    attribute_updates = []

    for key, value in fields.items():
        # Entity-level fields
        if key in ("name", "slug", "category_id", "is_starred", "status",
                    "confidence_score", "raw_research"):
            entity_updates[key] = value
        elif key == "tags":
            if not isinstance(value, str):
                value = json.dumps(value)
            entity_updates["tags"] = value
        elif key in _COMPANY_FIELD_MAP:
            # Company column → entity attribute
            attr_slug = _COMPANY_FIELD_MAP[key]
            attribute_updates.append((attr_slug, str(value) if value is not None else None))
        elif key in ("project_id",):
            # Skip meta fields
            continue
        else:
            # Try as direct attribute slug
            attribute_updates.append((key, str(value) if value is not None else None))

    with db._get_conn() as conn:
        if entity_updates:
            entity_updates["updated_at"] = "datetime('now')"
            set_parts = []
            params = []
            for col, val in entity_updates.items():
                if val == "datetime('now')":
                    set_parts.append(f"{col} = datetime('now')")
                else:
                    set_parts.append(f"{col} = ?")
                    params.append(val)
            params.append(entity_id)
            conn.execute(
                f"UPDATE entities SET {', '.join(set_parts)} WHERE id = ?",
                params,
            )

        for attr_slug, value in attribute_updates:
            if value is None:
                conn.execute(
                    "DELETE FROM entity_attributes WHERE entity_id = ? AND attr_slug = ?",
                    (entity_id, attr_slug),
                )
            else:
                existing = conn.execute(
                    "SELECT id FROM entity_attributes WHERE entity_id = ? AND attr_slug = ?",
                    (entity_id, attr_slug),
                ).fetchone()
                if existing:
                    conn.execute(
                        """UPDATE entity_attributes
                           SET value = ?, source = 'api', captured_at = datetime('now')
                           WHERE entity_id = ? AND attr_slug = ?""",
                        (value, entity_id, attr_slug),
                    )
                else:
                    conn.execute(
                        """INSERT INTO entity_attributes
                           (entity_id, attr_slug, value, source, captured_at)
                           VALUES (?, ?, ?, 'api', datetime('now'))""",
                        (entity_id, attr_slug, value),
                    )

        conn.commit()
