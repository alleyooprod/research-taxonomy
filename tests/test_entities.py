"""Tests for the Research Workbench entity system.

Covers:
- Schema validation and normalisation
- Entity type definition sync
- Entity CRUD (create, read, update, delete)
- Temporal attribute versioning
- Entity relationships (graph)
- Evidence library
- Snapshot grouping
"""
import json
import time
import pytest

from core.schema import (
    validate_schema, normalize_schema, get_entity_type_def,
    get_root_types, get_child_types, get_type_hierarchy,
    add_entity_type, add_attribute, add_relationship,
    DEFAULT_COMPANY_SCHEMA, SCHEMA_TEMPLATES,
)


# ═══════════════════════════════════════════════════════════════
# Schema Tests
# ═══════════════════════════════════════════════════════════════

class TestSchemaValidation:
    """Tests for schema validation logic."""

    def test_valid_default_schema(self):
        valid, errors = validate_schema(DEFAULT_COMPANY_SCHEMA)
        assert valid, f"Default schema should be valid: {errors}"

    def test_all_templates_valid(self):
        for key, template in SCHEMA_TEMPLATES.items():
            valid, errors = validate_schema(template["schema"])
            assert valid, f"Template '{key}' should be valid: {errors}"

    def test_empty_schema_invalid(self):
        valid, errors = validate_schema({})
        assert not valid
        assert any("entity_types" in e for e in errors)

    def test_no_entity_types_invalid(self):
        valid, errors = validate_schema({"entity_types": []})
        assert not valid

    def test_duplicate_type_slug_invalid(self):
        schema = {
            "entity_types": [
                {"name": "Company", "slug": "company"},
                {"name": "Corp", "slug": "company"},
            ]
        }
        valid, errors = validate_schema(schema)
        assert not valid
        assert any("Duplicate" in e for e in errors)

    def test_unknown_parent_type_invalid(self):
        schema = {
            "entity_types": [
                {"name": "Feature", "slug": "feature", "parent_type": "nonexistent"},
            ]
        }
        valid, errors = validate_schema(schema)
        assert not valid
        assert any("unknown parent_type" in e for e in errors)

    def test_enum_without_values_invalid(self):
        schema = {
            "entity_types": [
                {"name": "Thing", "slug": "thing", "attributes": [
                    {"name": "Status", "slug": "status", "data_type": "enum"}
                ]},
            ]
        }
        valid, errors = validate_schema(schema)
        assert not valid
        assert any("enum_values" in e for e in errors)

    def test_unknown_data_type_invalid(self):
        schema = {
            "entity_types": [
                {"name": "Thing", "slug": "thing", "attributes": [
                    {"name": "X", "slug": "x", "data_type": "magic"}
                ]},
            ]
        }
        valid, errors = validate_schema(schema)
        assert not valid

    def test_valid_relationship(self):
        schema = {
            "entity_types": [
                {"name": "Product", "slug": "product"},
                {"name": "Principle", "slug": "principle"},
            ],
            "relationships": [
                {"name": "demonstrates", "from_type": "product", "to_type": "principle"}
            ]
        }
        valid, errors = validate_schema(schema)
        assert valid, f"Should be valid: {errors}"

    def test_relationship_bad_type_invalid(self):
        schema = {
            "entity_types": [
                {"name": "Product", "slug": "product"},
            ],
            "relationships": [
                {"name": "demonstrates", "from_type": "product", "to_type": "ghost"}
            ]
        }
        valid, errors = validate_schema(schema)
        assert not valid


class TestSchemaNormalization:
    """Tests for schema normalisation."""

    def test_adds_missing_slugs(self):
        schema = {"entity_types": [{"name": "My Entity"}]}
        result = normalize_schema(schema)
        assert result["entity_types"][0]["slug"] == "my-entity"

    def test_adds_defaults(self):
        schema = {"entity_types": [{"name": "X"}]}
        result = normalize_schema(schema)
        et = result["entity_types"][0]
        assert et["description"] == ""
        assert et["icon"] == "circle"
        assert et["parent_type"] is None
        assert result["version"] == 1
        assert result["relationships"] == []

    def test_attribute_defaults(self):
        schema = {"entity_types": [{"name": "X", "attributes": [{"name": "Foo"}]}]}
        result = normalize_schema(schema)
        attr = result["entity_types"][0]["attributes"][0]
        assert attr["slug"] == "foo"
        assert attr["data_type"] == "text"
        assert attr["required"] is False

    def test_does_not_mutate_original(self):
        schema = {"entity_types": [{"name": "X"}]}
        result = normalize_schema(schema)
        assert "slug" not in schema["entity_types"][0]
        assert "slug" in result["entity_types"][0]


class TestSchemaHelpers:
    """Tests for schema query helpers."""

    def test_get_entity_type_def(self):
        et = get_entity_type_def(DEFAULT_COMPANY_SCHEMA, "company")
        assert et is not None
        assert et["name"] == "Company"

    def test_get_entity_type_def_missing(self):
        et = get_entity_type_def(DEFAULT_COMPANY_SCHEMA, "nonexistent")
        assert et is None

    def test_get_root_types(self):
        schema = SCHEMA_TEMPLATES["product_analysis"]["schema"]
        roots = get_root_types(schema)
        assert len(roots) == 1
        assert roots[0]["slug"] == "company"

    def test_get_child_types(self):
        schema = SCHEMA_TEMPLATES["product_analysis"]["schema"]
        children = get_child_types(schema, "company")
        assert len(children) == 1
        assert children[0]["slug"] == "product"

    def test_get_type_hierarchy(self):
        schema = SCHEMA_TEMPLATES["product_analysis"]["schema"]
        tree = get_type_hierarchy(schema)
        assert len(tree) == 1  # one root
        assert tree[0]["type"]["slug"] == "company"
        assert len(tree[0]["children"]) == 1  # product
        assert tree[0]["children"][0]["type"]["slug"] == "product"

    def test_design_research_has_two_roots(self):
        schema = SCHEMA_TEMPLATES["design_research"]["schema"]
        roots = get_root_types(schema)
        assert len(roots) == 2  # product and design-principle

    def test_add_entity_type(self):
        schema = normalize_schema({"entity_types": [{"name": "Company"}]})
        schema = add_entity_type(schema, {"name": "Product", "parent_type": "company"})
        assert len(schema["entity_types"]) == 2
        assert schema["entity_types"][1]["slug"] == "product"

    def test_add_duplicate_type_raises(self):
        schema = normalize_schema({"entity_types": [{"name": "Company"}]})
        with pytest.raises(ValueError, match="already exists"):
            add_entity_type(schema, {"name": "Company"})

    def test_add_attribute(self):
        schema = normalize_schema({"entity_types": [{"name": "Company"}]})
        schema = add_attribute(schema, "company", {"name": "Revenue", "data_type": "currency"})
        attrs = schema["entity_types"][0]["attributes"]
        assert any(a["slug"] == "revenue" for a in attrs)

    def test_add_relationship(self):
        schema = normalize_schema({
            "entity_types": [{"name": "A"}, {"name": "B"}]
        })
        schema = add_relationship(schema, {"from_type": "a", "to_type": "b", "name": "links_to"})
        assert len(schema["relationships"]) == 1
        assert schema["relationships"][0]["name"] == "links_to"


# ═══════════════════════════════════════════════════════════════
# Entity Database Tests
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def entity_project(tmp_db):
    """Create a project with the product_analysis schema."""
    schema = SCHEMA_TEMPLATES["product_analysis"]["schema"]
    pid = tmp_db.create_project(
        name="Entity Test Project",
        purpose="Testing entities",
        entity_schema=schema,
    )
    return {"project_id": pid, "db": tmp_db, "schema": schema}


class TestEntityTypeDefs:
    """Tests for entity type definition storage."""

    def test_sync_creates_types(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        defs = db.get_entity_type_defs(pid)
        slugs = {d["slug"] for d in defs}
        assert "company" in slugs
        assert "product" in slugs
        assert "plan" in slugs
        assert "tier" in slugs
        assert "feature" in slugs

    def test_get_single_type_def(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        td = db.get_entity_type_def(pid, "company")
        assert td is not None
        assert td["name"] == "Company"
        assert isinstance(td["attributes"], list)
        assert len(td["attributes"]) > 0

    def test_get_missing_type_def(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        td = db.get_entity_type_def(pid, "nonexistent")
        assert td is None


class TestEntityCRUD:
    """Tests for entity create, read, update, delete."""

    def test_create_entity(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Bupa Health")
        assert eid is not None
        assert isinstance(eid, int)

    def test_get_entity(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Vitality", attributes={
            "url": "https://vitality.co.uk",
            "what": "Health insurance provider",
        })

        entity = db.get_entity(eid)
        assert entity["name"] == "Vitality"
        assert entity["type_slug"] == "company"
        assert entity["attributes"]["url"]["value"] == "https://vitality.co.uk"
        assert entity["attributes"]["what"]["value"] == "Health insurance provider"

    def test_get_entity_with_counts(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        parent = db.create_entity(pid, "company", "Bupa")
        db.create_entity(pid, "product", "Health Insurance", parent_entity_id=parent)
        db.create_entity(pid, "product", "Dental Cover", parent_entity_id=parent)

        entity = db.get_entity(parent)
        assert entity["child_count"] == 2
        assert entity["evidence_count"] == 0

    def test_list_entities_by_type(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        db.create_entity(pid, "company", "A Corp")
        db.create_entity(pid, "company", "B Corp")
        db.create_entity(pid, "product", "X Product")

        companies = db.get_entities(pid, type_slug="company")
        assert len(companies) == 2
        assert all(e["type_slug"] == "company" for e in companies)

    def test_list_entities_by_parent(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        parent = db.create_entity(pid, "company", "Bupa")
        db.create_entity(pid, "product", "Health", parent_entity_id=parent)
        db.create_entity(pid, "product", "Dental", parent_entity_id=parent)

        children = db.get_entities(pid, parent_entity_id=parent)
        assert len(children) == 2

    def test_list_root_entities(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        parent = db.create_entity(pid, "company", "Bupa")
        db.create_entity(pid, "product", "Health", parent_entity_id=parent)

        roots = db.get_entities(pid, parent_entity_id="root")
        assert len(roots) == 1
        assert roots[0]["name"] == "Bupa"

    def test_search_entities(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        db.create_entity(pid, "company", "Vitality Health")
        db.create_entity(pid, "company", "Bupa")

        results = db.get_entities(pid, search="vital")
        assert len(results) == 1
        assert results[0]["name"] == "Vitality Health"

    def test_update_entity(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Old Name")
        db.update_entity(eid, {"name": "New Name"})

        entity = db.get_entity(eid)
        assert entity["name"] == "New Name"
        assert entity["slug"] == "new-name"

    def test_soft_delete_entity(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "To Delete")
        db.delete_entity(eid)

        entity = db.get_entity(eid)
        assert entity is None  # filtered by is_deleted

        entities = db.get_entities(pid, type_slug="company")
        assert len(entities) == 0

    def test_cascade_delete(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        parent = db.create_entity(pid, "company", "Parent")
        child = db.create_entity(pid, "product", "Child", parent_entity_id=parent)
        grandchild = db.create_entity(pid, "plan", "GChild", parent_entity_id=child)

        db.delete_entity(parent, cascade=True)

        assert db.get_entity(parent) is None
        assert db.get_entity(child) is None
        assert db.get_entity(grandchild) is None

    def test_restore_entity(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Restored")
        db.delete_entity(eid, cascade=False)
        assert db.get_entity(eid) is None

        db.restore_entity(eid)
        entity = db.get_entity(eid)
        assert entity is not None
        assert entity["name"] == "Restored"


class TestEntityAttributes:
    """Tests for temporal attribute versioning."""

    def test_set_and_get_attribute(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.set_entity_attribute(eid, "url", "https://test.com")

        entity = db.get_entity(eid)
        assert entity["attributes"]["url"]["value"] == "https://test.com"

    def test_attribute_history(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.set_entity_attribute(eid, "what", "Version 1",
                                captured_at="2026-01-01T00:00:00")
        db.set_entity_attribute(eid, "what", "Version 2",
                                captured_at="2026-02-01T00:00:00")
        db.set_entity_attribute(eid, "what", "Version 3",
                                captured_at="2026-03-01T00:00:00")

        history = db.get_entity_attribute_history(eid, "what")
        assert len(history) == 3
        assert history[0]["value"] == "Version 3"  # newest first
        assert history[2]["value"] == "Version 1"  # oldest last

    def test_current_attribute_is_latest(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.set_entity_attribute(eid, "what", "Old",
                                captured_at="2026-01-01T00:00:00")
        db.set_entity_attribute(eid, "what", "Current",
                                captured_at="2026-02-01T00:00:00")

        entity = db.get_entity(eid)
        assert entity["attributes"]["what"]["value"] == "Current"

    def test_attributes_at_point_in_time(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.set_entity_attribute(eid, "what", "Old description",
                                captured_at="2026-01-01T00:00:00")
        db.set_entity_attribute(eid, "url", "https://old.com",
                                captured_at="2026-01-01T00:00:00")
        db.set_entity_attribute(eid, "what", "New description",
                                captured_at="2026-03-01T00:00:00")

        # Query at Feb — should get Jan values
        attrs = db.get_entity_attributes_at(eid, "2026-02-01T00:00:00")
        assert attrs["what"]["value"] == "Old description"
        assert attrs["url"]["value"] == "https://old.com"

        # Query at April — should get latest values
        attrs = db.get_entity_attributes_at(eid, "2026-04-01T00:00:00")
        assert attrs["what"]["value"] == "New description"

    def test_set_multiple_attributes(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.set_entity_attributes(eid, {
            "url": "https://test.com",
            "what": "Testing company",
            "founded_year": "2020",
        }, source="ai", confidence=0.9)

        entity = db.get_entity(eid)
        assert entity["attributes"]["url"]["value"] == "https://test.com"
        assert entity["attributes"]["what"]["source"] == "ai"
        assert entity["attributes"]["what"]["confidence"] == 0.9

    def test_boolean_attribute(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.set_entity_attribute(eid, "has_free_tier", True)

        entity = db.get_entity(eid)
        assert entity["attributes"]["has_free_tier"]["value"] == "1"

    def test_json_attribute(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.set_entity_attribute(eid, "pricing_tiers", [{"name": "Basic", "price": 29}])

        entity = db.get_entity(eid)
        parsed = json.loads(entity["attributes"]["pricing_tiers"]["value"])
        assert parsed[0]["name"] == "Basic"


class TestEntityRelationships:
    """Tests for many-to-many entity relationships."""

    def test_create_relationship(self, tmp_db):
        schema = SCHEMA_TEMPLATES["design_research"]["schema"]
        pid = tmp_db.create_project(name="Design Test", entity_schema=schema)

        prod = tmp_db.create_entity(pid, "product", "Stripe")
        principle = tmp_db.create_entity(pid, "design-principle", "Progressive Disclosure")

        tmp_db.create_entity_relationship(prod, principle, "demonstrates")

        rels = tmp_db.get_entity_relationships(prod, direction="outgoing")
        assert len(rels) == 1
        assert rels[0]["related_name"] == "Progressive Disclosure"
        assert rels[0]["relationship_type"] == "demonstrates"

    def test_bidirectional_query(self, tmp_db):
        schema = SCHEMA_TEMPLATES["design_research"]["schema"]
        pid = tmp_db.create_project(name="Design Test", entity_schema=schema)

        prod = tmp_db.create_entity(pid, "product", "Linear")
        principle = tmp_db.create_entity(pid, "design-principle", "Spatial Navigation")

        tmp_db.create_entity_relationship(prod, principle, "demonstrates")

        # From product side
        from_prod = tmp_db.get_entity_relationships(prod, direction="outgoing")
        assert len(from_prod) == 1

        # From principle side
        from_principle = tmp_db.get_entity_relationships(principle, direction="incoming")
        assert len(from_principle) == 1
        assert from_principle[0]["related_name"] == "Linear"

    def test_both_directions(self, tmp_db):
        schema = SCHEMA_TEMPLATES["design_research"]["schema"]
        pid = tmp_db.create_project(name="Design Test", entity_schema=schema)

        a = tmp_db.create_entity(pid, "product", "A")
        b = tmp_db.create_entity(pid, "product", "B")
        p = tmp_db.create_entity(pid, "design-principle", "P")

        tmp_db.create_entity_relationship(a, p, "demonstrates")
        tmp_db.create_entity_relationship(b, p, "demonstrates")

        both = tmp_db.get_entity_relationships(p, direction="both")
        assert len(both) == 2  # two incoming

    def test_delete_relationship(self, tmp_db):
        schema = SCHEMA_TEMPLATES["design_research"]["schema"]
        pid = tmp_db.create_project(name="Design Test", entity_schema=schema)

        a = tmp_db.create_entity(pid, "product", "A")
        b = tmp_db.create_entity(pid, "design-principle", "B")
        tmp_db.create_entity_relationship(a, b, "demonstrates")

        rels = tmp_db.get_entity_relationships(a)
        assert len(rels) == 1
        tmp_db.delete_entity_relationship(rels[0]["id"])

        rels = tmp_db.get_entity_relationships(a)
        assert len(rels) == 0


class TestEvidence:
    """Tests for evidence library."""

    def test_add_evidence(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Bupa")
        ev_id = db.add_evidence(
            eid, "screenshot", "evidence/bupa_homepage.png",
            source_url="https://bupa.co.uk",
            source_name="Company Website",
            metadata={"width": 1920, "height": 1080},
        )
        assert ev_id is not None

    def test_get_evidence(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Vitality")
        db.add_evidence(eid, "screenshot", "evidence/v1.png", source_name="Mobbin")
        db.add_evidence(eid, "screenshot", "evidence/v2.png", source_name="Mobbin")
        db.add_evidence(eid, "document", "evidence/ipid.pdf", source_name="Company Website")

        all_ev = db.get_evidence(entity_id=eid)
        assert len(all_ev) == 3

        screenshots = db.get_evidence(entity_id=eid, evidence_type="screenshot")
        assert len(screenshots) == 2

        mobbin = db.get_evidence(entity_id=eid, source_name="Mobbin")
        assert len(mobbin) == 2

    def test_evidence_metadata(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.add_evidence(eid, "screenshot", "test.png",
                        metadata={"width": 800, "format": "png"})

        ev = db.get_evidence(entity_id=eid)
        assert ev[0]["metadata"]["width"] == 800

    def test_delete_evidence(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        ev_id = db.add_evidence(eid, "screenshot", "test.png")

        db.delete_evidence(ev_id)
        ev = db.get_evidence(entity_id=eid)
        assert len(ev) == 0

    def test_evidence_count_on_entity(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        eid = db.create_entity(pid, "company", "Test")
        db.add_evidence(eid, "screenshot", "a.png")
        db.add_evidence(eid, "screenshot", "b.png")

        entity = db.get_entity(eid)
        assert entity["evidence_count"] == 2


class TestSnapshots:
    """Tests for capture snapshot grouping."""

    def test_create_snapshot(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        sid = db.create_snapshot(pid, description="February 2026 capture")
        assert sid is not None

    def test_list_snapshots(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        db.create_snapshot(pid, "Snapshot 1")
        db.create_snapshot(pid, "Snapshot 2")

        snaps = db.get_snapshots(pid)
        assert len(snaps) == 2
        descriptions = {s["description"] for s in snaps}
        assert "Snapshot 1" in descriptions
        assert "Snapshot 2" in descriptions

    def test_snapshot_attribute_count(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        sid = db.create_snapshot(pid, "Test snapshot")
        eid = db.create_entity(pid, "company", "Test")
        db.set_entity_attribute(eid, "url", "https://test.com", snapshot_id=sid)
        db.set_entity_attribute(eid, "what", "Testing", snapshot_id=sid)

        snaps = db.get_snapshots(pid)
        assert snaps[0]["attribute_count"] == 2


class TestEntityStats:
    """Tests for entity statistics."""

    def test_entity_stats(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        db.create_entity(pid, "company", "A")
        db.create_entity(pid, "company", "B")
        parent = db.create_entity(pid, "company", "C")
        db.create_entity(pid, "product", "X", parent_entity_id=parent)

        stats = db.get_entity_stats(pid)
        assert stats["company"] == 3
        assert stats["product"] == 1


class TestProjectWithSchema:
    """Tests for project creation with entity schema."""

    def test_create_project_with_schema(self, tmp_db):
        schema = SCHEMA_TEMPLATES["product_analysis"]["schema"]
        pid = tmp_db.create_project(
            name="Schema Project",
            entity_schema=schema,
        )

        project = tmp_db.get_project(pid)
        assert project["entity_schema"] is not None
        stored_schema = json.loads(project["entity_schema"])
        assert len(stored_schema["entity_types"]) == 5

    def test_project_without_schema(self, tmp_db):
        pid = tmp_db.create_project(name="No Schema Project")
        project = tmp_db.get_project(pid)
        assert project["entity_schema"] is None

    def test_schema_syncs_type_defs(self, tmp_db):
        schema = SCHEMA_TEMPLATES["design_research"]["schema"]
        pid = tmp_db.create_project(name="Design Project", entity_schema=schema)

        defs = tmp_db.get_entity_type_defs(pid)
        assert len(defs) == 2
        slugs = {d["slug"] for d in defs}
        assert "product" in slugs
        assert "design-principle" in slugs


class TestHierarchicalEntities:
    """Tests for the full Company > Product > Plan > Tier > Feature hierarchy."""

    def test_full_hierarchy(self, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]

        company = db.create_entity(pid, "company", "Bupa", attributes={
            "url": "https://bupa.co.uk",
            "what": "Health insurance provider",
        })
        product = db.create_entity(pid, "product", "Health Insurance",
                                   parent_entity_id=company, attributes={
            "platform": "Web, iOS, Android",
        })
        plan = db.create_entity(pid, "plan", "Comprehensive",
                                parent_entity_id=product)
        tier = db.create_entity(pid, "tier", "Essential",
                                parent_entity_id=plan, attributes={
            "headline_price": "45",
            "price_period": "monthly",
        })
        feature = db.create_entity(pid, "feature", "Mental Health Cover",
                                   parent_entity_id=tier, attributes={
            "included": True,
            "limit": "£1,500 per year",
        })

        # Navigate down
        company_entity = db.get_entity(company)
        assert company_entity["child_count"] == 1

        products = db.get_entities(pid, parent_entity_id=company)
        assert len(products) == 1
        assert products[0]["name"] == "Health Insurance"

        plans = db.get_entities(pid, parent_entity_id=product)
        assert len(plans) == 1

        tiers = db.get_entities(pid, parent_entity_id=plan)
        assert len(tiers) == 1
        assert tiers[0]["attributes"]["headline_price"]["value"] == "45"

        features = db.get_entities(pid, parent_entity_id=tier)
        assert len(features) == 1
        assert features[0]["attributes"]["included"]["value"] == "1"
        assert features[0]["attributes"]["limit"]["value"] == "£1,500 per year"
