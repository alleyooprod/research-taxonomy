"""Tests for the backwards-compatible company <-> entity translation layer.

Covers:
- project_uses_entities() detection logic (flat vs entity-mode projects)
- entity_to_company() conversion (entity + attributes -> company dict)
- company_data_to_entity() conversion (company dict -> entity fields + attributes)
- list_entities_as_companies() query with filtering, sorting, pagination
- get_entity_as_company() single entity lookup
- create_entity_from_company_data() creation via company dict
- update_entity_from_company_data() update via company field names
- API delegation through /api/companies routes
"""
import json
import pytest

from core.compat import (
    project_uses_entities,
    entity_to_company,
    company_data_to_entity,
    list_entities_as_companies,
    get_entity_as_company,
    create_entity_from_company_data,
    update_entity_from_company_data,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

MULTI_TYPE_SCHEMA = {
    "entity_types": [
        {
            "slug": "company",
            "name": "Company",
            "description": "A company in the research scope",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "Website", "slug": "website", "data_type": "url"},
                {"name": "Description", "slug": "description", "data_type": "text"},
                {"name": "Target Market", "slug": "target_market", "data_type": "text"},
                {"name": "Funding", "slug": "funding", "data_type": "text"},
                {"name": "Geography", "slug": "geography", "data_type": "text"},
                {"name": "Employee Range", "slug": "employee_range", "data_type": "text"},
                {"name": "Founded Year", "slug": "founded_year", "data_type": "text"},
                {"name": "HQ City", "slug": "hq_city", "data_type": "text"},
                {"name": "HQ Country", "slug": "hq_country", "data_type": "text"},
            ],
        },
        {
            "slug": "product",
            "name": "Product",
            "description": "A product or service",
            "icon": "box",
            "parent_type": None,
            "attributes": [
                {"name": "Description", "slug": "description", "data_type": "text"},
            ],
        },
    ]
}


def _create_flat_project(db):
    """Create a project without entity_schema (flat company mode)."""
    return db.create_project(name="Flat Project", purpose="Testing flat mode")


def _create_entity_project(db):
    """Create a project with multi-type entity schema."""
    return db.create_project(
        name="Entity Project",
        purpose="Testing entity mode",
        entity_schema=MULTI_TYPE_SCHEMA,
    )


def _insert_entity(db, project_id, name, slug=None, attrs=None,
                   is_starred=0, category_id=None, tags=None):
    """Insert an entity directly into the DB. Returns entity_id."""
    slug = slug or name.lower().replace(" ", "-")
    with db._get_conn() as conn:
        conn.execute(
            """INSERT INTO entities
               (project_id, type_slug, name, slug, source, is_starred,
                category_id, tags, created_at, updated_at)
               VALUES (?, 'company', ?, ?, 'test', ?, ?, ?, datetime('now'), datetime('now'))""",
            (project_id, name, slug, is_starred, category_id, tags),
        )
        entity_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        for attr_slug, value in (attrs or []):
            conn.execute(
                """INSERT INTO entity_attributes
                   (entity_id, attr_slug, value, source, captured_at)
                   VALUES (?, ?, ?, 'test', datetime('now'))""",
                (entity_id, attr_slug, value),
            )
        conn.commit()
    return entity_id


# ═══════════════════════════════════════════════════════════════
# project_uses_entities()
# ═══════════════════════════════════════════════════════════════

@pytest.mark.companies
class TestProjectUsesEntities:
    """Detect whether a project should use the entity system."""

    def test_flat_project_returns_false(self, app):
        """Project created without entity_schema should return False."""
        db = app.db
        pid = _create_flat_project(db)
        assert project_uses_entities(db, pid) is False

    def test_multi_type_schema_returns_true(self, app):
        """Project with multi-type entity schema should return True."""
        db = app.db
        pid = _create_entity_project(db)
        assert project_uses_entities(db, pid) is True

    def test_none_project_id_returns_false(self, app):
        """Passing None as project_id should return False."""
        assert project_uses_entities(app.db, None) is False

    def test_nonexistent_project_returns_false(self, app):
        """Nonexistent project_id should return False."""
        assert project_uses_entities(app.db, 99999) is False

    def test_single_type_no_entities_returns_false(self, app):
        """Single-type schema with no entities should return False."""
        db = app.db
        single_schema = {
            "entity_types": [
                {
                    "slug": "company",
                    "name": "Company",
                    "description": "",
                    "icon": "building",
                    "parent_type": None,
                    "attributes": [],
                }
            ]
        }
        pid = db.create_project(
            name="Single Type Empty",
            purpose="Test",
            entity_schema=single_schema,
        )
        assert project_uses_entities(db, pid) is False

    def test_single_type_with_entities_returns_true(self, app):
        """Single-type schema with actual entities should return True."""
        db = app.db
        single_schema = {
            "entity_types": [
                {
                    "slug": "company",
                    "name": "Company",
                    "description": "",
                    "icon": "building",
                    "parent_type": None,
                    "attributes": [],
                }
            ]
        }
        pid = db.create_project(
            name="Single With Entities",
            purpose="Test",
            entity_schema=single_schema,
        )
        _insert_entity(db, pid, "Acme Corp")
        assert project_uses_entities(db, pid) is True

    def test_invalid_json_schema_returns_false(self, app):
        """Corrupted entity_schema JSON should return False."""
        db = app.db
        pid = _create_flat_project(db)
        # Manually set invalid JSON
        with db._get_conn() as conn:
            conn.execute(
                "UPDATE projects SET entity_schema = ? WHERE id = ?",
                ("{not valid json!!!", pid),
            )
            conn.commit()
        assert project_uses_entities(db, pid) is False


# ═══════════════════════════════════════════════════════════════
# entity_to_company()
# ═══════════════════════════════════════════════════════════════

@pytest.mark.companies
class TestEntityToCompany:
    """Convert entity row + attributes to company-format dict."""

    def test_basic_conversion(self, app):
        """Entity with standard attributes maps to correct company fields."""
        entity_row = {
            "id": 1, "project_id": 10, "slug": "acme", "name": "Acme Corp",
            "category_id": 5, "is_starred": 1, "is_deleted": 0,
            "status": "active", "confidence_score": 0.85, "tags": None,
            "raw_research": None, "created_at": "2026-01-01", "updated_at": "2026-01-02",
        }
        attributes = [
            {"attr_slug": "website", "value": "https://acme.com"},
            {"attr_slug": "description", "value": "Enterprise SaaS"},
            {"attr_slug": "target_market", "value": "Large enterprises"},
            {"attr_slug": "funding", "value": "Series B"},
            {"attr_slug": "hq_city", "value": "San Francisco"},
            {"attr_slug": "hq_country", "value": "US"},
        ]
        company = entity_to_company(entity_row, attributes)

        assert company["id"] == 1
        assert company["name"] == "Acme Corp"
        assert company["url"] == "https://acme.com"
        assert company["what"] == "Enterprise SaaS"
        assert company["target"] == "Large enterprises"
        assert company["funding"] == "Series B"
        assert company["hq_city"] == "San Francisco"
        assert company["hq_country"] == "US"
        assert company["is_starred"] == 1

    def test_missing_attributes_default_to_none(self, app):
        """Standard company columns default to None when no attribute exists."""
        entity_row = {
            "id": 2, "project_id": 10, "slug": "bare", "name": "Bare Corp",
            "category_id": None, "is_starred": 0, "is_deleted": 0,
            "status": "active", "confidence_score": None, "tags": None,
            "raw_research": None, "created_at": "2026-01-01", "updated_at": "2026-01-02",
        }
        company = entity_to_company(entity_row, [])

        for col in ("url", "what", "target", "products", "funding",
                     "geography", "tam", "logo_url", "employee_range",
                     "founded_year", "funding_stage", "total_funding_usd",
                     "hq_city", "hq_country", "linkedin_url", "business_model",
                     "company_stage", "primary_focus", "pricing_model",
                     "has_free_tier", "revenue_model", "pricing_tiers",
                     "pricing_notes", "relationship_status", "relationship_note"):
            assert company[col] is None, f"{col} should be None"

    def test_tags_json_string_parsed(self, app):
        """Tags stored as JSON string should be parsed to a list."""
        entity_row = {
            "id": 3, "project_id": 10, "slug": "tagged", "name": "Tagged Co",
            "category_id": None, "is_starred": 0, "is_deleted": 0,
            "status": "active", "confidence_score": None,
            "tags": json.dumps(["saas", "fintech"]),
            "raw_research": None, "created_at": "2026-01-01", "updated_at": "2026-01-02",
        }
        company = entity_to_company(entity_row, [])
        assert company["tags"] == ["saas", "fintech"]

    def test_tags_none_stays_none(self, app):
        """Null tags should remain None (not parsed)."""
        entity_row = {
            "id": 4, "project_id": 10, "slug": "no-tags", "name": "No Tags",
            "category_id": None, "is_starred": 0, "is_deleted": 0,
            "status": "active", "confidence_score": None, "tags": None,
            "raw_research": None, "created_at": "2026-01-01", "updated_at": "2026-01-02",
        }
        company = entity_to_company(entity_row, [])
        assert company["tags"] is None

    def test_non_standard_attributes_preserved(self, app):
        """Attributes not in the field map appear under their slug key."""
        entity_row = {
            "id": 5, "project_id": 10, "slug": "custom", "name": "Custom Co",
            "category_id": None, "is_starred": 0, "is_deleted": 0,
            "status": "active", "confidence_score": None, "tags": None,
            "raw_research": None, "created_at": "2026-01-01", "updated_at": "2026-01-02",
        }
        attributes = [
            {"attr_slug": "custom_field", "value": "custom_value"},
        ]
        company = entity_to_company(entity_row, attributes)
        assert company["custom_field"] == "custom_value"


# ═══════════════════════════════════════════════════════════════
# company_data_to_entity()
# ═══════════════════════════════════════════════════════════════

@pytest.mark.companies
class TestCompanyDataToEntity:
    """Convert company-format dict into entity fields + attributes."""

    def test_basic_conversion(self):
        """Standard company fields map to entity fields and attributes."""
        data = {
            "name": "Acme Corp",
            "slug": "acme-corp",
            "url": "https://acme.com",
            "what": "Enterprise SaaS",
            "target": "Large enterprises",
            "funding": "Series B",
            "hq_city": "San Francisco",
        }
        entity_fields, attributes = company_data_to_entity(data, project_id=10)

        assert entity_fields["name"] == "Acme Corp"
        assert entity_fields["slug"] == "acme-corp"
        assert entity_fields["type_slug"] == "company"
        assert entity_fields["project_id"] == 10

        attr_map = dict(attributes)
        assert attr_map["website"] == "https://acme.com"
        assert attr_map["description"] == "Enterprise SaaS"
        assert attr_map["target_market"] == "Large enterprises"
        assert attr_map["funding"] == "Series B"
        assert attr_map["hq_city"] == "San Francisco"

    def test_name_falls_back_to_url(self):
        """If name is missing, URL is used as the entity name."""
        data = {"url": "https://fallback.com"}
        entity_fields, _ = company_data_to_entity(data, project_id=10)
        assert entity_fields["name"] == "https://fallback.com"

    def test_tags_list_becomes_json_string(self):
        """Tags provided as a list are JSON-encoded for storage."""
        data = {"name": "Tagged", "tags": ["saas", "fintech"]}
        entity_fields, _ = company_data_to_entity(data, project_id=10)
        assert entity_fields["tags"] == json.dumps(["saas", "fintech"])

    def test_tags_string_kept_as_is(self):
        """Tags already a string should stay as-is."""
        data = {"name": "Tagged", "tags": '["saas"]'}
        entity_fields, _ = company_data_to_entity(data, project_id=10)
        assert entity_fields["tags"] == '["saas"]'

    def test_none_values_excluded_from_attributes(self):
        """Columns with None values should not generate attribute tuples."""
        data = {"name": "Sparse", "url": "https://sparse.com", "what": None, "target": None}
        _, attributes = company_data_to_entity(data, project_id=10)
        attr_slugs = {slug for slug, _ in attributes}
        assert "description" not in attr_slugs
        assert "target_market" not in attr_slugs
        assert "website" in attr_slugs

    def test_empty_string_values_excluded_from_attributes(self):
        """Columns with empty/whitespace-only values should not generate attributes."""
        data = {"name": "Blank", "url": "https://blank.com", "what": "  ", "target": ""}
        _, attributes = company_data_to_entity(data, project_id=10)
        attr_slugs = {slug for slug, _ in attributes}
        assert "description" not in attr_slugs
        assert "target_market" not in attr_slugs

    def test_entity_level_fields_preserved(self):
        """Fields like is_starred, status, category_id map to entity-level fields."""
        data = {
            "name": "Starred",
            "is_starred": 1,
            "status": "reviewing",
            "category_id": 42,
            "confidence_score": 0.9,
            "raw_research": '{"key": "value"}',
        }
        entity_fields, _ = company_data_to_entity(data, project_id=10)
        assert entity_fields["is_starred"] == 1
        assert entity_fields["status"] == "reviewing"
        assert entity_fields["category_id"] == 42
        assert entity_fields["confidence_score"] == 0.9
        assert entity_fields["raw_research"] == '{"key": "value"}'


# ═══════════════════════════════════════════════════════════════
# list_entities_as_companies()
# ═══════════════════════════════════════════════════════════════

@pytest.mark.companies
class TestListEntitiesAsCompanies:
    """Query entities and return company-format list with filtering."""

    def test_lists_all_company_entities(self, app):
        """Returns all non-deleted company entities in a project."""
        db = app.db
        pid = _create_entity_project(db)
        _insert_entity(db, pid, "Alpha Inc", attrs=[("website", "https://alpha.com")])
        _insert_entity(db, pid, "Beta LLC", attrs=[("website", "https://beta.com")])

        companies = list_entities_as_companies(db, pid)
        assert len(companies) == 2
        names = {c["name"] for c in companies}
        assert names == {"Alpha Inc", "Beta LLC"}

    def test_excludes_deleted_entities(self, app):
        """Deleted entities should not appear in the list."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Deleted Co")
        _insert_entity(db, pid, "Active Co")
        with db._get_conn() as conn:
            conn.execute("UPDATE entities SET is_deleted = 1 WHERE id = ?", (eid,))
            conn.commit()

        companies = list_entities_as_companies(db, pid)
        assert len(companies) == 1
        assert companies[0]["name"] == "Active Co"

    def test_search_filter(self, app):
        """Search parameter filters by entity name."""
        db = app.db
        pid = _create_entity_project(db)
        _insert_entity(db, pid, "Acme Corp")
        _insert_entity(db, pid, "Beta Health")
        _insert_entity(db, pid, "Acme Labs")

        results = list_entities_as_companies(db, pid, search="Acme")
        assert len(results) == 2
        assert all("Acme" in c["name"] for c in results)

    def test_starred_only_filter(self, app):
        """starred_only=True returns only starred entities."""
        db = app.db
        pid = _create_entity_project(db)
        _insert_entity(db, pid, "Starred Co", is_starred=1)
        _insert_entity(db, pid, "Normal Co", is_starred=0)

        results = list_entities_as_companies(db, pid, starred_only=True)
        assert len(results) == 1
        assert results[0]["name"] == "Starred Co"

    def test_category_filter(self, app):
        """category_id filter returns only entities in that category."""
        db = app.db
        pid = _create_entity_project(db)
        cats = db.get_categories(project_id=pid)
        # Create a category if none exist
        if not cats:
            with db._get_conn() as conn:
                conn.execute(
                    "INSERT INTO categories (project_id, name) VALUES (?, 'Test Cat')",
                    (pid,),
                )
                conn.commit()
            cats = db.get_categories(project_id=pid)
        cat_id = cats[0]["id"]

        _insert_entity(db, pid, "Categorized", category_id=cat_id)
        _insert_entity(db, pid, "Uncategorized")

        results = list_entities_as_companies(db, pid, category_id=cat_id)
        assert len(results) == 1
        assert results[0]["name"] == "Categorized"

    def test_sort_by_name_desc(self, app):
        """sort_by=name, sort_dir=desc returns in reverse alphabetical order."""
        db = app.db
        pid = _create_entity_project(db)
        _insert_entity(db, pid, "Charlie")
        _insert_entity(db, pid, "Alpha")
        _insert_entity(db, pid, "Bravo")

        results = list_entities_as_companies(db, pid, sort_by="name", sort_dir="desc")
        names = [c["name"] for c in results]
        assert names == ["Charlie", "Bravo", "Alpha"]

    def test_company_format_has_standard_columns(self, app):
        """Each returned dict has all standard company columns."""
        db = app.db
        pid = _create_entity_project(db)
        _insert_entity(db, pid, "Full Co", attrs=[
            ("website", "https://full.co"),
            ("description", "A full company"),
        ])

        companies = list_entities_as_companies(db, pid)
        assert len(companies) == 1
        c = companies[0]
        # Check key company columns exist
        for col in ("id", "name", "url", "what", "target", "funding",
                     "geography", "hq_city", "hq_country", "is_starred",
                     "status", "created_at", "updated_at"):
            assert col in c, f"Missing column: {col}"
        assert c["url"] == "https://full.co"
        assert c["what"] == "A full company"


# ═══════════════════════════════════════════════════════════════
# get_entity_as_company()
# ═══════════════════════════════════════════════════════════════

@pytest.mark.companies
class TestGetEntityAsCompany:
    """Single entity lookup returning company-format dict."""

    def test_returns_company_dict(self, app):
        """Existing entity is returned as company dict."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Lookup Co", attrs=[
            ("website", "https://lookup.co"),
            ("description", "Lookup company"),
            ("hq_country", "US"),
        ])

        company = get_entity_as_company(db, eid)
        assert company is not None
        assert company["id"] == eid
        assert company["name"] == "Lookup Co"
        assert company["url"] == "https://lookup.co"
        assert company["what"] == "Lookup company"
        assert company["hq_country"] == "US"

    def test_nonexistent_entity_returns_none(self, app):
        """Nonexistent entity ID returns None."""
        assert get_entity_as_company(app.db, 99999) is None

    def test_deleted_entity_returns_none(self, app):
        """Soft-deleted entity returns None."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Deleted Co")
        with db._get_conn() as conn:
            conn.execute("UPDATE entities SET is_deleted = 1 WHERE id = ?", (eid,))
            conn.commit()

        assert get_entity_as_company(db, eid) is None


# ═══════════════════════════════════════════════════════════════
# create_entity_from_company_data()
# ═══════════════════════════════════════════════════════════════

@pytest.mark.companies
class TestCreateEntityFromCompanyData:
    """Create an entity from company-format data."""

    def test_creates_entity_with_attributes(self, app):
        """Company data results in a new entity with mapped attributes."""
        db = app.db
        pid = _create_entity_project(db)
        data = {
            "name": "New Corp",
            "slug": "new-corp",
            "url": "https://newcorp.com",
            "what": "New corporation",
            "target": "SMBs",
            "hq_city": "Austin",
        }
        eid = create_entity_from_company_data(db, data, pid)
        assert eid is not None
        assert eid > 0

        # Verify entity was created
        company = get_entity_as_company(db, eid)
        assert company["name"] == "New Corp"
        assert company["url"] == "https://newcorp.com"
        assert company["what"] == "New corporation"
        assert company["target"] == "SMBs"
        assert company["hq_city"] == "Austin"

    def test_entity_type_slug_is_company(self, app):
        """Created entity has type_slug='company'."""
        db = app.db
        pid = _create_entity_project(db)
        eid = create_entity_from_company_data(db, {"name": "TypeCheck"}, pid)

        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT type_slug FROM entities WHERE id = ?", (eid,)
            ).fetchone()
        assert row["type_slug"] == "company"

    def test_starred_entity(self, app):
        """is_starred flag is carried through to entity."""
        db = app.db
        pid = _create_entity_project(db)
        eid = create_entity_from_company_data(
            db, {"name": "Star Co", "is_starred": 1}, pid
        )
        company = get_entity_as_company(db, eid)
        assert company["is_starred"] == 1

    def test_tags_persisted(self, app):
        """Tags list is JSON-encoded and persisted on the entity."""
        db = app.db
        pid = _create_entity_project(db)
        eid = create_entity_from_company_data(
            db, {"name": "Tagged Co", "tags": ["ai", "ml"]}, pid
        )
        company = get_entity_as_company(db, eid)
        assert company["tags"] == ["ai", "ml"]


# ═══════════════════════════════════════════════════════════════
# update_entity_from_company_data()
# ═══════════════════════════════════════════════════════════════

@pytest.mark.companies
class TestUpdateEntityFromCompanyData:
    """Update an entity using company-format field names."""

    def test_update_entity_level_fields(self, app):
        """Entity-level fields (name, status, etc.) are updated directly."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Old Name")

        update_entity_from_company_data(db, eid, {
            "name": "New Name",
            "status": "reviewing",
            "is_starred": 1,
        })

        company = get_entity_as_company(db, eid)
        assert company["name"] == "New Name"
        assert company["status"] == "reviewing"
        assert company["is_starred"] == 1

    def test_update_company_column_creates_attribute(self, app):
        """Company column names (url, what, etc.) create entity attributes."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Attr Co")

        update_entity_from_company_data(db, eid, {
            "url": "https://attr.co",
            "what": "Attribute company",
            "hq_country": "UK",
        })

        company = get_entity_as_company(db, eid)
        assert company["url"] == "https://attr.co"
        assert company["what"] == "Attribute company"
        assert company["hq_country"] == "UK"

    def test_update_existing_attribute(self, app):
        """Updating a company column that already has an attribute replaces the value."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Update Co", attrs=[
            ("website", "https://old.com"),
        ])

        update_entity_from_company_data(db, eid, {"url": "https://new.com"})
        company = get_entity_as_company(db, eid)
        assert company["url"] == "https://new.com"

    def test_update_none_value_deletes_attribute(self, app):
        """Setting a company column to None deletes the entity attribute."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Remove Co", attrs=[
            ("website", "https://remove.com"),
            ("description", "Will be removed"),
        ])

        update_entity_from_company_data(db, eid, {"url": None})
        company = get_entity_as_company(db, eid)
        assert company["url"] is None
        # Other attributes should still be there
        assert company["what"] == "Will be removed"

    def test_update_tags_as_list(self, app):
        """Tags provided as a list are JSON-encoded for storage."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Tag Update Co")

        update_entity_from_company_data(db, eid, {"tags": ["new", "tags"]})
        company = get_entity_as_company(db, eid)
        assert company["tags"] == ["new", "tags"]

    def test_project_id_field_skipped(self, app):
        """The project_id field should be ignored during updates."""
        db = app.db
        pid = _create_entity_project(db)
        eid = _insert_entity(db, pid, "Skip PID")

        # Should not raise or change project_id
        update_entity_from_company_data(db, eid, {
            "project_id": 99999,
            "name": "Still Same Project",
        })
        company = get_entity_as_company(db, eid)
        assert company["project_id"] == pid
        assert company["name"] == "Still Same Project"


# ═══════════════════════════════════════════════════════════════
# API delegation tests
# ═══════════════════════════════════════════════════════════════

@pytest.mark.api
@pytest.mark.companies
class TestAPIDelegation:
    """Test that /api/companies routes delegate correctly for entity-mode projects."""

    def _setup_entity_project(self, client):
        """Helper to create entity project with entities via DB."""
        db = client.db
        pid = _create_entity_project(db)
        eid1 = _insert_entity(db, pid, "API Corp", attrs=[
            ("website", "https://api-corp.com"),
            ("description", "API testing company"),
            ("target_market", "Developers"),
        ])
        eid2 = _insert_entity(db, pid, "Widget Inc", attrs=[
            ("website", "https://widget.inc"),
            ("description", "Widget manufacturing"),
        ])
        return pid, eid1, eid2

    def test_list_companies_delegates_to_entities(self, client):
        """GET /api/companies returns entity data for entity-mode projects."""
        pid, _, _ = self._setup_entity_project(client)

        r = client.get(f"/api/companies?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 2
        names = {c["name"] for c in data}
        assert names == {"API Corp", "Widget Inc"}

    def test_get_company_returns_entity(self, client):
        """GET /api/companies/<id> returns entity as company dict."""
        _, eid1, _ = self._setup_entity_project(client)

        r = client.get(f"/api/companies/{eid1}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "API Corp"
        assert data["url"] == "https://api-corp.com"
        assert data["what"] == "API testing company"

    def test_add_company_creates_entity(self, client):
        """POST /api/companies/add creates entity in entity-mode project."""
        db = client.db
        pid = _create_entity_project(db)
        # Need at least one entity for single-type detection, but we have multi-type
        # so project_uses_entities returns True already

        r = client.post("/api/companies/add", json={
            "url": "https://new-entity.com",
            "name": "New Entity Co",
            "project_id": pid,
            "what": "A new entity company",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        eid = data["id"]

        # Verify it was created as an entity
        company = get_entity_as_company(db, eid)
        assert company is not None
        assert company["name"] == "New Entity Co"
        assert company["url"] == "https://new-entity.com"
        assert company["what"] == "A new entity company"

    def test_update_company_updates_entity(self, client):
        """POST /api/companies/<id> updates entity fields."""
        _, eid1, _ = self._setup_entity_project(client)

        r = client.post(f"/api/companies/{eid1}", json={
            "name": "Renamed Corp",
            "what": "Updated description",
        })
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

        company = get_entity_as_company(client.db, eid1)
        assert company["name"] == "Renamed Corp"
        assert company["what"] == "Updated description"

    def test_delete_company_soft_deletes_entity(self, client):
        """DELETE /api/companies/<id> soft-deletes entity."""
        _, eid1, _ = self._setup_entity_project(client)

        r = client.delete(f"/api/companies/{eid1}")
        assert r.status_code == 200

        # Entity should no longer appear via get_entity_as_company
        assert get_entity_as_company(client.db, eid1) is None

        # But still exists in DB as deleted
        with client.db._get_conn() as conn:
            row = conn.execute(
                "SELECT is_deleted FROM entities WHERE id = ?", (eid1,)
            ).fetchone()
        assert row["is_deleted"] == 1

    def test_star_entity_via_company_api(self, client):
        """POST /api/companies/<id>/star toggles star on entity."""
        _, eid1, _ = self._setup_entity_project(client)

        r = client.post(f"/api/companies/{eid1}/star")
        assert r.status_code == 200
        data = r.get_json()
        assert data["is_starred"] == 1

        # Toggle back
        r = client.post(f"/api/companies/{eid1}/star")
        assert r.status_code == 200
        data = r.get_json()
        assert data["is_starred"] == 0

    def test_relationship_update_via_entity(self, client):
        """POST /api/companies/<id>/relationship stores as entity attributes."""
        _, eid1, _ = self._setup_entity_project(client)

        r = client.post(f"/api/companies/{eid1}/relationship", json={
            "status": "partner",
            "note": "Strategic partner for 2026",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        assert data["relationship_status"] == "partner"
        assert data["relationship_note"] == "Strategic partner for 2026"

        # Verify stored as attributes
        company = get_entity_as_company(client.db, eid1)
        assert company["relationship_status"] == "partner"
        assert company["relationship_note"] == "Strategic partner for 2026"

    def test_list_with_search_filter_via_api(self, client):
        """GET /api/companies?search= filters entity list."""
        pid, _, _ = self._setup_entity_project(client)

        r = client.get(f"/api/companies?project_id={pid}&search=Widget")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["name"] == "Widget Inc"

    def test_list_starred_only_via_api(self, client):
        """GET /api/companies?starred=1 filters to starred entities."""
        pid, eid1, _ = self._setup_entity_project(client)
        # Star eid1
        with client.db._get_conn() as conn:
            conn.execute("UPDATE entities SET is_starred = 1 WHERE id = ?", (eid1,))
            conn.commit()

        r = client.get(f"/api/companies?project_id={pid}&starred=1")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["name"] == "API Corp"
