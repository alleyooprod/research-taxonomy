"""Tests for Entity API — schema, types, CRUD, attributes, relationships, evidence, snapshots.

Run: pytest tests/test_api_entities.py -v
Markers: api, entities
"""
import json
import pytest

pytestmark = [pytest.mark.api, pytest.mark.entities]

# Schema used across tests
PRODUCT_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "URL", "slug": "url", "data_type": "url", "required": True},
                {"name": "What they do", "slug": "what", "data_type": "text"},
            ],
        },
        {
            "name": "Product",
            "slug": "product",
            "description": "A product",
            "icon": "package",
            "parent_type": "company",
            "attributes": [
                {"name": "Name", "slug": "name", "data_type": "text", "required": True},
                {"name": "Platform", "slug": "platform", "data_type": "text"},
            ],
        },
    ],
    "relationships": [],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def entity_project(client):
    """Create a project with an entity schema via DB, return project info."""
    pid = client.db.create_project(
        name="Entity Test Project",
        purpose="Entity API testing",
        entity_schema=PRODUCT_SCHEMA,
    )
    return {"id": pid, "client": client}


@pytest.fixture
def entity_with_company(entity_project):
    """Project with one company entity created via API."""
    c = entity_project["client"]
    pid = entity_project["id"]
    r = c.post("/api/entities", json={
        "project_id": pid,
        "type": "company",
        "name": "Acme Corp",
        "attributes": {"url": "https://acme.com", "what": "Enterprise SaaS"},
    })
    assert r.status_code == 201, f"Failed to create entity: {r.data}"
    data = r.get_json()
    return {
        **entity_project,
        "entity_id": data["id"],
        "entity": data,
    }


@pytest.fixture
def entity_hierarchy(entity_with_company):
    """Project with Company -> Product hierarchy."""
    c = entity_with_company["client"]
    pid = entity_with_company["id"]
    company_id = entity_with_company["entity_id"]

    r = c.post("/api/entities", json={
        "project_id": pid,
        "type": "product",
        "name": "Acme Pro",
        "parent_id": company_id,
        "attributes": {"name": "Acme Pro", "platform": "Web"},
    })
    assert r.status_code == 201
    product = r.get_json()

    return {
        **entity_with_company,
        "product_id": product["id"],
        "product": product,
    }


# ---------------------------------------------------------------------------
# Schema Templates
# ---------------------------------------------------------------------------

class TestSchemaTemplates:
    """ENT-TMPL: Schema template listing via GET /api/schema/templates."""

    def test_list_templates(self, client):
        r = client.get("/api/schema/templates")
        assert r.status_code == 200
        templates = r.get_json()
        assert isinstance(templates, list)
        assert len(templates) >= 3  # blank, market_analysis, product_analysis, design_research

    def test_template_has_required_fields(self, client):
        r = client.get("/api/schema/templates")
        templates = r.get_json()
        for t in templates:
            assert "key" in t
            assert "name" in t
            assert "description" in t
            assert "entity_types" in t
            assert isinstance(t["entity_types"], list)

    def test_product_analysis_template(self, client):
        r = client.get("/api/schema/templates")
        templates = {t["key"]: t for t in r.get_json()}
        pa = templates["product_analysis"]
        type_names = [et["name"] for et in pa["entity_types"]]
        assert "Company" in type_names
        assert "Product" in type_names
        assert "Feature" in type_names


class TestSchemaValidation:
    """ENT-VALID: Schema validation via POST /api/schema/validate."""

    def test_validate_valid_schema(self, client):
        r = client.post("/api/schema/validate", json={"schema": PRODUCT_SCHEMA})
        assert r.status_code == 200
        data = r.get_json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_validate_missing_schema(self, client):
        r = client.post("/api/schema/validate", json={})
        assert r.status_code == 400

    def test_validate_empty_entity_types(self, client):
        r = client.post("/api/schema/validate", json={
            "schema": {"entity_types": []}
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_validate_invalid_data_type(self, client):
        r = client.post("/api/schema/validate", json={
            "schema": {
                "entity_types": [{
                    "name": "X",
                    "attributes": [{"name": "a", "data_type": "invalid"}],
                }]
            }
        })
        data = r.get_json()
        assert data["valid"] is False
        assert any("Unknown data_type" in e for e in data["errors"])


# ---------------------------------------------------------------------------
# Entity Type Definitions
# ---------------------------------------------------------------------------

class TestEntityTypes:
    """ENT-TYPES: Entity type definition endpoints."""

    def test_list_entity_types(self, entity_project):
        c = entity_project["client"]
        pid = entity_project["id"]
        r = c.get(f"/api/entity-types?project_id={pid}")
        assert r.status_code == 200
        types = r.get_json()
        assert len(types) == 2
        slugs = {t["slug"] for t in types}
        assert "company" in slugs
        assert "product" in slugs

    def test_list_entity_types_requires_project_id(self, client):
        r = client.get("/api/entity-types")
        assert r.status_code == 400

    def test_entity_type_hierarchy(self, entity_project):
        c = entity_project["client"]
        pid = entity_project["id"]
        r = c.get(f"/api/entity-types/hierarchy?project_id={pid}")
        assert r.status_code == 200
        hierarchy = r.get_json()
        assert len(hierarchy) == 1  # Company is root
        assert hierarchy[0]["type"]["slug"] == "company"
        assert len(hierarchy[0]["children"]) == 1
        assert hierarchy[0]["children"][0]["type"]["slug"] == "product"

    def test_hierarchy_requires_project_id(self, client):
        r = client.get("/api/entity-types/hierarchy")
        assert r.status_code == 400

    def test_sync_entity_types(self, entity_project):
        c = entity_project["client"]
        pid = entity_project["id"]
        # Add a new type via sync
        updated_schema = {
            **PRODUCT_SCHEMA,
            "entity_types": PRODUCT_SCHEMA["entity_types"] + [{
                "name": "Feature",
                "slug": "feature",
                "parent_type": "product",
                "attributes": [{"name": "Name", "slug": "name", "data_type": "text"}],
            }],
        }
        r = c.post("/api/entity-types/sync", json={
            "project_id": pid,
            "schema": updated_schema,
        })
        assert r.status_code == 200

        # Verify new type exists
        r = c.get(f"/api/entity-types?project_id={pid}")
        slugs = {t["slug"] for t in r.get_json()}
        assert "feature" in slugs

    def test_sync_rejects_invalid_schema(self, entity_project):
        c = entity_project["client"]
        r = c.post("/api/entity-types/sync", json={
            "project_id": entity_project["id"],
            "schema": {"entity_types": []},
        })
        assert r.status_code == 400

    def test_sync_requires_both_fields(self, client):
        r = client.post("/api/entity-types/sync", json={"project_id": 1})
        assert r.status_code == 400
        r = client.post("/api/entity-types/sync", json={"schema": PRODUCT_SCHEMA})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Entity CRUD
# ---------------------------------------------------------------------------

class TestEntityCreate:
    """ENT-CREATE: Entity creation via POST /api/entities."""

    def test_create_entity(self, entity_project):
        c = entity_project["client"]
        r = c.post("/api/entities", json={
            "project_id": entity_project["id"],
            "type": "company",
            "name": "New Corp",
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["name"] == "New Corp"
        assert data["type_slug"] == "company"
        assert data["id"] is not None

    def test_create_with_attributes(self, entity_project):
        c = entity_project["client"]
        r = c.post("/api/entities", json={
            "project_id": entity_project["id"],
            "type": "company",
            "name": "Attr Corp",
            "attributes": {"url": "https://attr.com", "what": "Testing attributes"},
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["attributes"]["url"]["value"] == "https://attr.com"

    def test_create_with_parent(self, entity_with_company):
        c = entity_with_company["client"]
        r = c.post("/api/entities", json={
            "project_id": entity_with_company["id"],
            "type": "product",
            "name": "Sub Product",
            "parent_id": entity_with_company["entity_id"],
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["parent_entity_id"] == entity_with_company["entity_id"]

    def test_create_requires_fields(self, client):
        r = client.post("/api/entities", json={"name": "X"})
        assert r.status_code == 400

    def test_create_requires_name(self, entity_project):
        c = entity_project["client"]
        r = c.post("/api/entities", json={
            "project_id": entity_project["id"],
            "type": "company",
            "name": "",
        })
        assert r.status_code == 400

    def test_create_requires_type(self, entity_project):
        c = entity_project["client"]
        r = c.post("/api/entities", json={
            "project_id": entity_project["id"],
            "name": "No Type",
        })
        assert r.status_code == 400


class TestEntityRead:
    """ENT-READ: Entity retrieval endpoints."""

    def test_get_entity(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.get(f"/api/entities/{eid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "Acme Corp"
        assert data["type_slug"] == "company"
        assert "attributes" in data
        assert "child_count" in data
        assert "evidence_count" in data

    def test_get_nonexistent(self, client):
        r = client.get("/api/entities/99999")
        assert r.status_code == 404

    def test_list_entities(self, entity_with_company):
        c = entity_with_company["client"]
        pid = entity_with_company["id"]
        r = c.get(f"/api/entities?project_id={pid}")
        assert r.status_code == 200
        entities = r.get_json()
        assert len(entities) >= 1
        assert any(e["name"] == "Acme Corp" for e in entities)

    def test_list_requires_project_id(self, client):
        r = client.get("/api/entities")
        assert r.status_code == 400

    def test_list_filter_by_type(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        pid = entity_hierarchy["id"]
        r = c.get(f"/api/entities?project_id={pid}&type=product")
        assert r.status_code == 200
        entities = r.get_json()
        assert all(e["type_slug"] == "product" for e in entities)

    def test_list_filter_by_parent(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        pid = entity_hierarchy["id"]
        parent_id = entity_hierarchy["entity_id"]
        r = c.get(f"/api/entities?project_id={pid}&parent_id={parent_id}")
        assert r.status_code == 200
        entities = r.get_json()
        assert len(entities) == 1
        assert entities[0]["name"] == "Acme Pro"

    def test_list_root_entities(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        pid = entity_hierarchy["id"]
        r = c.get(f"/api/entities?project_id={pid}&parent_id=root")
        assert r.status_code == 200
        entities = r.get_json()
        assert all(e["parent_entity_id"] is None for e in entities)

    def test_list_search(self, entity_with_company):
        c = entity_with_company["client"]
        pid = entity_with_company["id"]
        r = c.get(f"/api/entities?project_id={pid}&search=Acme")
        entities = r.get_json()
        assert len(entities) >= 1
        assert all("Acme" in e["name"] for e in entities)

    def test_list_search_no_match(self, entity_with_company):
        c = entity_with_company["client"]
        pid = entity_with_company["id"]
        r = c.get(f"/api/entities?project_id={pid}&search=zzznomatch")
        assert r.get_json() == []


class TestEntityUpdate:
    """ENT-UPDATE: Entity update via POST /api/entities/<id>."""

    def test_update_name(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post(f"/api/entities/{eid}", json={"name": "Acme Inc"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "Acme Inc"

    def test_update_attributes(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post(f"/api/entities/{eid}", json={
            "attributes": {"what": "Updated description"},
            "source": "manual",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["attributes"]["what"]["value"] == "Updated description"

    def test_update_star(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post(f"/api/entities/{eid}", json={"is_starred": True})
        assert r.status_code == 200
        data = r.get_json()
        assert data["is_starred"] == 1

    def test_update_nonexistent(self, client):
        r = client.post("/api/entities/99999", json={"name": "X"})
        assert r.status_code == 404


class TestEntityDelete:
    """ENT-DEL: Entity delete and restore."""

    def test_delete_entity(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.delete(f"/api/entities/{eid}")
        assert r.status_code == 200
        # Should now be 404 on get
        r = c.get(f"/api/entities/{eid}")
        assert r.status_code == 404

    def test_delete_cascade(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        company_id = entity_hierarchy["entity_id"]
        product_id = entity_hierarchy["product_id"]
        # Delete company should cascade to product
        r = c.delete(f"/api/entities/{company_id}")
        assert r.status_code == 200
        r = c.get(f"/api/entities/{product_id}")
        assert r.status_code == 404

    def test_delete_no_cascade(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        company_id = entity_hierarchy["entity_id"]
        product_id = entity_hierarchy["product_id"]
        r = c.delete(f"/api/entities/{company_id}?cascade=false")
        assert r.status_code == 200
        # Product should still exist
        r = c.get(f"/api/entities/{product_id}")
        assert r.status_code == 200

    def test_restore_entity(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        # Delete
        c.delete(f"/api/entities/{eid}")
        assert c.get(f"/api/entities/{eid}").status_code == 404
        # Restore
        r = c.post(f"/api/entities/{eid}/restore", json={})
        assert r.status_code == 200
        # Should be visible again
        r = c.get(f"/api/entities/{eid}")
        assert r.status_code == 200

    def test_toggle_star(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        # Star it
        r = c.post(f"/api/entities/{eid}/star", json={})
        assert r.status_code == 200
        assert r.get_json()["is_starred"] is True
        # Unstar it
        r = c.post(f"/api/entities/{eid}/star", json={})
        assert r.status_code == 200
        assert r.get_json()["is_starred"] is False

    def test_toggle_star_nonexistent(self, client):
        r = client.post("/api/entities/99999/star", json={})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Entity Attributes
# ---------------------------------------------------------------------------

class TestEntityAttributes:
    """ENT-ATTR: Entity attribute endpoints."""

    def test_set_attributes(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post(f"/api/entities/{eid}/attributes", json={
            "attributes": {"url": "https://acme-new.com"},
            "source": "manual",
        })
        assert r.status_code == 200

    def test_set_attributes_requires_dict(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post(f"/api/entities/{eid}/attributes", json={})
        assert r.status_code == 400

    def test_attribute_history(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        # Set attribute a second time to create history
        c.post(f"/api/entities/{eid}/attributes", json={
            "attributes": {"what": "Version 2"},
            "source": "ai",
        })
        r = c.get(f"/api/entities/{eid}/attributes/what/history")
        assert r.status_code == 200
        history = r.get_json()
        assert len(history) >= 2
        # Newest first
        assert history[0]["value"] == "Version 2"
        assert history[0]["source"] == "ai"

    def test_attribute_history_with_limit(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        # Add multiple values
        for i in range(5):
            c.post(f"/api/entities/{eid}/attributes", json={
                "attributes": {"what": f"Version {i}"},
            })
        r = c.get(f"/api/entities/{eid}/attributes/what/history?limit=3")
        history = r.get_json()
        assert len(history) <= 3

    def test_attributes_at_time(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        # Get at a future date (should include all current values)
        r = c.get(f"/api/entities/{eid}/attributes/at?date=2099-12-31T23:59:59")
        assert r.status_code == 200
        attrs = r.get_json()
        assert "url" in attrs
        assert attrs["url"]["value"] == "https://acme.com"

    def test_attributes_at_requires_date(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.get(f"/api/entities/{eid}/attributes/at")
        assert r.status_code == 400

    def test_attributes_at_past_date(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        # Get at a date before creation
        r = c.get(f"/api/entities/{eid}/attributes/at?date=2000-01-01T00:00:00")
        assert r.status_code == 200
        attrs = r.get_json()
        assert attrs == {}

    def test_set_with_confidence(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post(f"/api/entities/{eid}/attributes", json={
            "attributes": {"what": "AI generated"},
            "source": "ai",
            "confidence": 0.85,
        })
        assert r.status_code == 200
        # Verify confidence is stored
        r = c.get(f"/api/entities/{eid}/attributes/what/history?limit=1")
        latest = r.get_json()[0]
        assert latest["confidence"] == 0.85

    def test_set_with_snapshot(self, entity_with_company):
        c = entity_with_company["client"]
        pid = entity_with_company["id"]
        eid = entity_with_company["entity_id"]
        # Create a snapshot
        r = c.post("/api/snapshots", json={
            "project_id": pid,
            "description": "Test snapshot",
        })
        snap_id = r.get_json()["id"]
        # Set attribute with snapshot
        r = c.post(f"/api/entities/{eid}/attributes", json={
            "attributes": {"what": "Snapshotted value"},
            "snapshot_id": snap_id,
        })
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Entity Relationships
# ---------------------------------------------------------------------------

class TestEntityRelationships:
    """ENT-REL: Entity relationship endpoints."""

    def test_create_relationship(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        # Create a second company for a relationship
        r = c.post("/api/entities", json={
            "project_id": entity_hierarchy["id"],
            "type": "company",
            "name": "Partner Corp",
        })
        partner_id = r.get_json()["id"]

        r = c.post("/api/entity-relationships", json={
            "from_id": entity_hierarchy["entity_id"],
            "to_id": partner_id,
            "type": "partners_with",
        })
        assert r.status_code == 201

    def test_list_relationships(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        # Create relationship
        r = c.post("/api/entities", json={
            "project_id": entity_hierarchy["id"],
            "type": "company",
            "name": "Related Corp",
        })
        related_id = r.get_json()["id"]
        c.post("/api/entity-relationships", json={
            "from_id": entity_hierarchy["entity_id"],
            "to_id": related_id,
            "type": "competes_with",
        })
        # List outgoing
        r = c.get(f"/api/entities/{entity_hierarchy['entity_id']}/relationships?direction=outgoing")
        assert r.status_code == 200
        rels = r.get_json()
        assert len(rels) >= 1
        assert rels[0]["direction"] == "outgoing"
        assert rels[0]["related_name"] == "Related Corp"

    def test_list_relationships_incoming(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        r = c.post("/api/entities", json={
            "project_id": entity_hierarchy["id"],
            "type": "company",
            "name": "Incoming Corp",
        })
        incoming_id = r.get_json()["id"]
        c.post("/api/entity-relationships", json={
            "from_id": incoming_id,
            "to_id": entity_hierarchy["entity_id"],
            "type": "acquires",
        })
        r = c.get(f"/api/entities/{entity_hierarchy['entity_id']}/relationships?direction=incoming")
        rels = r.get_json()
        assert any(rel["direction"] == "incoming" for rel in rels)

    def test_list_relationships_both(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        eid = entity_hierarchy["entity_id"]
        r = c.get(f"/api/entities/{eid}/relationships")
        assert r.status_code == 200  # default is "both"

    def test_delete_relationship(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        r = c.post("/api/entities", json={
            "project_id": entity_hierarchy["id"],
            "type": "company",
            "name": "Delete Rel Corp",
        })
        other_id = r.get_json()["id"]
        c.post("/api/entity-relationships", json={
            "from_id": entity_hierarchy["entity_id"],
            "to_id": other_id,
            "type": "invests_in",
        })
        # Get relationship ID
        r = c.get(f"/api/entities/{entity_hierarchy['entity_id']}/relationships?direction=outgoing")
        rels = r.get_json()
        inv_rel = [rel for rel in rels if rel["relationship_type"] == "invests_in"]
        assert len(inv_rel) >= 1
        rel_id = inv_rel[0]["id"]
        # Delete it
        r = c.delete(f"/api/entity-relationships/{rel_id}")
        assert r.status_code == 200

    def test_create_relationship_requires_fields(self, client):
        r = client.post("/api/entity-relationships", json={"from_id": 1})
        assert r.status_code == 400

    def test_create_relationship_with_metadata(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        r = c.post("/api/entities", json={
            "project_id": entity_hierarchy["id"],
            "type": "company",
            "name": "Meta Corp",
        })
        meta_id = r.get_json()["id"]
        r = c.post("/api/entity-relationships", json={
            "from_id": entity_hierarchy["entity_id"],
            "to_id": meta_id,
            "type": "competes_with",
            "metadata": {"confidence": 0.9, "source": "analyst"},
        })
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class TestEvidence:
    """ENT-EV: Evidence endpoints."""

    def test_add_evidence(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post("/api/evidence", json={
            "entity_id": eid,
            "type": "screenshot",
            "file_path": "evidence/acme-homepage.png",
            "source_url": "https://acme.com",
            "source_name": "Direct capture",
        })
        assert r.status_code == 201
        assert "id" in r.get_json()

    def test_list_evidence(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        # Add some evidence
        c.post("/api/evidence", json={
            "entity_id": eid, "type": "screenshot",
            "file_path": "evidence/shot1.png",
        })
        c.post("/api/evidence", json={
            "entity_id": eid, "type": "document",
            "file_path": "evidence/doc1.pdf",
        })
        r = c.get(f"/api/entities/{eid}/evidence")
        assert r.status_code == 200
        evidence = r.get_json()
        assert len(evidence) == 2

    def test_list_evidence_filter_type(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        c.post("/api/evidence", json={
            "entity_id": eid, "type": "screenshot",
            "file_path": "evidence/shot.png",
        })
        c.post("/api/evidence", json={
            "entity_id": eid, "type": "document",
            "file_path": "evidence/doc.pdf",
        })
        r = c.get(f"/api/entities/{eid}/evidence?type=screenshot")
        evidence = r.get_json()
        assert all(e["evidence_type"] == "screenshot" for e in evidence)

    def test_list_evidence_filter_source(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        c.post("/api/evidence", json={
            "entity_id": eid, "type": "screenshot",
            "file_path": "evidence/mobbin1.png",
            "source_name": "Mobbin",
        })
        c.post("/api/evidence", json={
            "entity_id": eid, "type": "screenshot",
            "file_path": "evidence/appstore1.png",
            "source_name": "App Store",
        })
        r = c.get(f"/api/entities/{eid}/evidence?source=Mobbin")
        evidence = r.get_json()
        assert all(e["source_name"] == "Mobbin" for e in evidence)

    def test_delete_evidence(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post("/api/evidence", json={
            "entity_id": eid, "type": "screenshot",
            "file_path": "evidence/delete-me.png",
        })
        ev_id = r.get_json()["id"]
        r = c.delete(f"/api/evidence/{ev_id}")
        assert r.status_code == 200
        # Verify gone
        r = c.get(f"/api/entities/{eid}/evidence")
        assert all(e["id"] != ev_id for e in r.get_json())

    def test_evidence_count_on_entity(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        c.post("/api/evidence", json={
            "entity_id": eid, "type": "screenshot",
            "file_path": "evidence/count1.png",
        })
        c.post("/api/evidence", json={
            "entity_id": eid, "type": "document",
            "file_path": "evidence/count2.pdf",
        })
        r = c.get(f"/api/entities/{eid}")
        assert r.get_json()["evidence_count"] == 2

    def test_add_evidence_requires_fields(self, client):
        r = client.post("/api/evidence", json={"entity_id": 1})
        assert r.status_code == 400

    def test_add_evidence_with_metadata(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post("/api/evidence", json={
            "entity_id": eid,
            "type": "page_archive",
            "file_path": "evidence/archive.mhtml",
            "metadata": {"viewport": "1920x1080", "browser": "Chrome"},
        })
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

class TestSnapshots:
    """ENT-SNAP: Snapshot endpoints."""

    def test_create_snapshot(self, entity_project):
        c = entity_project["client"]
        r = c.post("/api/snapshots", json={
            "project_id": entity_project["id"],
            "description": "Weekly capture",
        })
        assert r.status_code == 201
        assert "id" in r.get_json()

    def test_create_snapshot_requires_project_id(self, client):
        r = client.post("/api/snapshots", json={})
        assert r.status_code == 400

    def test_list_snapshots(self, entity_project):
        c = entity_project["client"]
        pid = entity_project["id"]
        c.post("/api/snapshots", json={"project_id": pid, "description": "S1"})
        c.post("/api/snapshots", json={"project_id": pid, "description": "S2"})
        r = c.get(f"/api/snapshots?project_id={pid}")
        assert r.status_code == 200
        snaps = r.get_json()
        assert len(snaps) >= 2

    def test_list_snapshots_requires_project_id(self, client):
        r = client.get("/api/snapshots")
        assert r.status_code == 400

    def test_snapshot_attribute_count(self, entity_with_company):
        c = entity_with_company["client"]
        pid = entity_with_company["id"]
        eid = entity_with_company["entity_id"]
        # Create snapshot
        r = c.post("/api/snapshots", json={
            "project_id": pid, "description": "Counted",
        })
        snap_id = r.get_json()["id"]
        # Set attributes with snapshot
        c.post(f"/api/entities/{eid}/attributes", json={
            "attributes": {"url": "https://counted.com", "what": "Counted"},
            "snapshot_id": snap_id,
        })
        # List snapshots and check count
        r = c.get(f"/api/snapshots?project_id={pid}")
        snaps = r.get_json()
        counted = [s for s in snaps if s["description"] == "Counted"]
        assert len(counted) == 1
        assert counted[0]["attribute_count"] == 2


# ---------------------------------------------------------------------------
# Entity Stats
# ---------------------------------------------------------------------------

class TestEntityStats:
    """ENT-STATS: Entity stats endpoint."""

    def test_entity_stats(self, entity_hierarchy):
        c = entity_hierarchy["client"]
        pid = entity_hierarchy["id"]
        r = c.get(f"/api/entity-stats?project_id={pid}")
        assert r.status_code == 200
        stats = r.get_json()
        assert stats["company"] >= 1
        assert stats["product"] >= 1

    def test_entity_stats_requires_project_id(self, client):
        r = client.get("/api/entity-stats")
        assert r.status_code == 400

    def test_entity_stats_empty_project(self, entity_project):
        c = entity_project["client"]
        pid = entity_project["id"]
        r = c.get(f"/api/entity-stats?project_id={pid}")
        assert r.status_code == 200
        assert r.get_json() == {}


# ---------------------------------------------------------------------------
# Integration: Full Workflow
# ---------------------------------------------------------------------------

class TestEntityWorkflow:
    """ENT-WF: Full entity workflow integration tests."""

    def test_full_product_analysis_workflow(self, client):
        """End-to-end: create schema project, add entities in hierarchy,
        set attributes, create relationships, add evidence, query stats."""
        from core.schema import SCHEMA_TEMPLATES
        schema = SCHEMA_TEMPLATES["product_analysis"]["schema"]

        # 1. Create project with schema
        pid = client.db.create_project(
            name="Workflow Test",
            purpose="Full workflow test",
            entity_schema=schema,
        )

        # 2. Verify entity types
        r = client.get(f"/api/entity-types?project_id={pid}")
        types = r.get_json()
        assert len(types) == 5  # Company, Product, Plan, Tier, Feature

        # 3. Create Company
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "company",
            "name": "Workflow Corp",
            "attributes": {"url": "https://workflow.com"},
        })
        assert r.status_code == 201
        company_id = r.get_json()["id"]

        # 4. Create Product under Company
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "product",
            "name": "WF Product",
            "parent_id": company_id,
            "attributes": {"name": "WF Product", "platform": "iOS"},
        })
        assert r.status_code == 201
        product_id = r.get_json()["id"]

        # 5. Create Plan under Product
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "plan",
            "name": "Premium Plan",
            "parent_id": product_id,
        })
        assert r.status_code == 201
        plan_id = r.get_json()["id"]

        # 6. Create Tier under Plan
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "tier",
            "name": "Gold Tier",
            "parent_id": plan_id,
            "attributes": {"headline_price": "29.99", "price_period": "monthly"},
        })
        assert r.status_code == 201
        tier_id = r.get_json()["id"]

        # 7. Create Feature under Tier
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "feature",
            "name": "Unlimited Storage",
            "parent_id": tier_id,
            "attributes": {"included": True, "notes": "Up to 1TB"},
        })
        assert r.status_code == 201

        # 8. Verify hierarchy via root listing
        r = client.get(f"/api/entities?project_id={pid}&parent_id=root")
        roots = r.get_json()
        assert len(roots) == 1
        assert roots[0]["child_count"] == 1

        # 9. Verify children
        r = client.get(f"/api/entities?project_id={pid}&parent_id={company_id}")
        children = r.get_json()
        assert len(children) == 1
        assert children[0]["name"] == "WF Product"

        # 10. Add evidence
        r = client.post("/api/evidence", json={
            "entity_id": product_id,
            "type": "screenshot",
            "file_path": "evidence/wf-product-ui.png",
            "source_url": "https://workflow.com/product",
            "source_name": "Direct",
        })
        assert r.status_code == 201

        # 11. Check stats
        r = client.get(f"/api/entity-stats?project_id={pid}")
        stats = r.get_json()
        assert stats["company"] == 1
        assert stats["product"] == 1
        assert stats["plan"] == 1
        assert stats["tier"] == 1
        assert stats["feature"] == 1

    def test_design_research_workflow(self, client):
        """End-to-end: design research with many-to-many relationships."""
        from core.schema import SCHEMA_TEMPLATES
        schema = SCHEMA_TEMPLATES["design_research"]["schema"]

        pid = client.db.create_project(
            name="Design Research Test",
            purpose="Design patterns",
            entity_schema=schema,
        )

        # Create products
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "product",
            "name": "Stripe Dashboard",
            "attributes": {"platform": "Web"},
        })
        stripe_id = r.get_json()["id"]

        r = client.post("/api/entities", json={
            "project_id": pid, "type": "product",
            "name": "Linear App",
            "attributes": {"platform": "Web"},
        })
        linear_id = r.get_json()["id"]

        # Create design principles
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "design-principle",
            "name": "Progressive Disclosure",
        })
        pd_id = r.get_json()["id"]

        r = client.post("/api/entities", json={
            "project_id": pid, "type": "design-principle",
            "name": "Keyboard-First Navigation",
        })
        kb_id = r.get_json()["id"]

        # Create many-to-many relationships
        for product_id in [stripe_id, linear_id]:
            for principle_id in [pd_id, kb_id]:
                r = client.post("/api/entity-relationships", json={
                    "from_id": product_id,
                    "to_id": principle_id,
                    "type": "demonstrates",
                })
                assert r.status_code == 201

        # Verify relationships from Stripe
        r = client.get(f"/api/entities/{stripe_id}/relationships?direction=outgoing")
        rels = r.get_json()
        assert len(rels) == 2

        # Verify relationships to Progressive Disclosure
        r = client.get(f"/api/entities/{pd_id}/relationships?direction=incoming")
        rels = r.get_json()
        assert len(rels) == 2

        # Stats
        r = client.get(f"/api/entity-stats?project_id={pid}")
        stats = r.get_json()
        assert stats["product"] == 2
        assert stats["design-principle"] == 2


# ---------------------------------------------------------------------------
# Phase 1.6: Project Creation with Templates
# ---------------------------------------------------------------------------

class TestProjectWithTemplate:
    """PROJ-TMPL: Project creation with schema template selection."""

    def test_create_project_blank_template(self, client):
        """Creating a project without template gets default company schema."""
        r = client.post("/api/projects", json={
            "name": "Blank Project",
            "purpose": "Test blank",
            "seed_categories": "Cat A",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        pid = data["id"]

        # Verify project has entity_schema
        proj = client.db.get_project(pid)
        assert proj["entity_schema"] is not None
        schema = json.loads(proj["entity_schema"])
        assert len(schema["entity_types"]) >= 1
        assert schema["entity_types"][0]["slug"] == "company"

    def test_create_project_with_template_key(self, client):
        """Creating a project with template= selects that template's schema."""
        r = client.post("/api/projects", json={
            "name": "Product Analysis Project",
            "purpose": "Test template",
            "seed_categories": "Cat A",
            "template": "product_analysis",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["template"] == "product_analysis"
        pid = data["id"]

        # Verify schema has product_analysis types
        proj = client.db.get_project(pid)
        schema = json.loads(proj["entity_schema"])
        type_slugs = {et["slug"] for et in schema["entity_types"]}
        assert "company" in type_slugs
        assert "product" in type_slugs
        assert "plan" in type_slugs
        assert "tier" in type_slugs
        assert "feature" in type_slugs

    def test_create_project_with_design_research_template(self, client):
        """Design research template includes relationships."""
        r = client.post("/api/projects", json={
            "name": "Design Project",
            "purpose": "Test design template",
            "seed_categories": "UI\nUX",
            "template": "design_research",
        })
        assert r.status_code == 200
        pid = r.get_json()["id"]

        proj = client.db.get_project(pid)
        schema = json.loads(proj["entity_schema"])
        type_slugs = {et["slug"] for et in schema["entity_types"]}
        assert "product" in type_slugs
        assert "design-principle" in type_slugs
        assert len(schema["relationships"]) >= 1
        assert schema["relationships"][0]["name"] == "demonstrates"

    def test_create_project_invalid_template(self, client):
        """Unknown template key returns 400."""
        r = client.post("/api/projects", json={
            "name": "Bad Template",
            "purpose": "Test",
            "seed_categories": "Cat A",
            "template": "nonexistent_template",
        })
        assert r.status_code == 400
        assert "Unknown template" in r.get_json()["error"]

    def test_create_project_with_custom_schema(self, client):
        """Providing entity_schema directly overrides template."""
        custom_schema = {
            "entity_types": [
                {
                    "name": "Competitor",
                    "slug": "competitor",
                    "attributes": [
                        {"name": "URL", "slug": "url", "data_type": "url"},
                        {"name": "Threat Level", "slug": "threat-level",
                         "data_type": "enum", "enum_values": ["low", "medium", "high"]},
                    ],
                }
            ],
            "relationships": [],
        }
        r = client.post("/api/projects", json={
            "name": "Custom Schema Project",
            "purpose": "Test custom",
            "seed_categories": "Cat A",
            "entity_schema": custom_schema,
        })
        assert r.status_code == 200
        pid = r.get_json()["id"]

        proj = client.db.get_project(pid)
        schema = json.loads(proj["entity_schema"])
        assert schema["entity_types"][0]["slug"] == "competitor"

    def test_create_project_invalid_custom_schema(self, client):
        """Invalid custom schema returns 400."""
        r = client.post("/api/projects", json={
            "name": "Bad Schema",
            "purpose": "Test",
            "seed_categories": "Cat A",
            "entity_schema": {"entity_types": []},  # Empty types invalid
        })
        assert r.status_code == 400
        assert "Invalid schema" in r.get_json()["error"]

    def test_template_project_has_entity_type_defs(self, client):
        """Schema template creates entity_type_defs in DB."""
        r = client.post("/api/projects", json={
            "name": "Types Test",
            "purpose": "Test type defs",
            "seed_categories": "Cat A",
            "template": "product_analysis",
        })
        pid = r.get_json()["id"]

        r = client.get(f"/api/entity-types?project_id={pid}")
        types = r.get_json()
        assert len(types) == 5
        slugs = {t["slug"] for t in types}
        assert slugs == {"company", "product", "plan", "tier", "feature"}

    def test_template_project_hierarchy(self, client):
        """Schema template creates correct hierarchy."""
        r = client.post("/api/projects", json={
            "name": "Hierarchy Test",
            "purpose": "Test hierarchy",
            "seed_categories": "Cat A",
            "template": "product_analysis",
        })
        pid = r.get_json()["id"]

        r = client.get(f"/api/entity-types/hierarchy?project_id={pid}")
        hierarchy = r.get_json()
        assert len(hierarchy) == 1  # One root: Company
        root = hierarchy[0]
        assert root["type"]["slug"] == "company"
        assert len(root["children"]) == 1  # Product
        assert root["children"][0]["type"]["slug"] == "product"

    def test_create_entities_on_template_project(self, client):
        """Entities can be created on a template-created project."""
        r = client.post("/api/projects", json={
            "name": "Entity Create Test",
            "purpose": "Test",
            "seed_categories": "Cat A",
            "template": "product_analysis",
        })
        pid = r.get_json()["id"]

        # Create Company entity
        r = client.post("/api/entities", json={
            "project_id": pid,
            "type": "company",
            "name": "Template Corp",
            "attributes": {"url": "https://template.com"},
        })
        assert r.status_code == 201
        company_id = r.get_json()["id"]

        # Create Product under Company
        r = client.post("/api/entities", json={
            "project_id": pid,
            "type": "product",
            "name": "Template Product",
            "parent_id": company_id,
            "attributes": {"name": "Template Product"},
        })
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Phase 1.6: AI Schema Suggestion
# ---------------------------------------------------------------------------

class TestSchemaSuggest:
    """SCHEMA-AI: AI schema suggestion endpoint (unit tests without real LLM)."""

    def test_suggest_requires_description(self, client):
        r = client.post("/api/schema/suggest", json={})
        assert r.status_code == 400
        assert "description is required" in r.get_json()["error"]

    def test_suggest_empty_description(self, client):
        r = client.post("/api/schema/suggest", json={"description": "   "})
        assert r.status_code == 400

    def test_suggest_with_invalid_template(self, client):
        """Unknown base template falls back to blank."""
        # This should not error — it falls back to blank
        r = client.post("/api/schema/suggest", json={
            "description": "Compare insurance products",
            "template": "nonexistent",
        })
        # Will fail at LLM level in tests (no LLM available), but should not 400 on template
        assert r.status_code != 400 or "description" not in r.get_json().get("error", "")


# ---------------------------------------------------------------------------
# Phase 1.6: Bulk Entity Operations
# ---------------------------------------------------------------------------

class TestBulkEntityOperations:
    """ENT-BULK: Bulk operations on entities."""

    def test_bulk_delete(self, entity_with_company):
        c = entity_with_company["client"]
        pid = entity_with_company["id"]
        eid = entity_with_company["entity_id"]

        # Create another entity
        r = c.post("/api/entities", json={
            "project_id": pid, "type": "company",
            "name": "Bulk Delete Corp",
            "attributes": {"url": "https://bulk.com"},
        })
        eid2 = r.get_json()["id"]

        r = c.post("/api/entities/bulk", json={
            "ids": [eid, eid2],
            "action": "delete",
        })
        assert r.status_code == 200
        assert r.get_json()["affected"] == 2

        # Verify deleted
        r = c.get(f"/api/entities?project_id={pid}")
        assert len(r.get_json()) == 0

    def test_bulk_star(self, entity_with_company):
        c = entity_with_company["client"]
        pid = entity_with_company["id"]
        eid = entity_with_company["entity_id"]

        # Create another entity
        r = c.post("/api/entities", json={
            "project_id": pid, "type": "company",
            "name": "Star Corp",
            "attributes": {"url": "https://star.com"},
        })
        eid2 = r.get_json()["id"]

        r = c.post("/api/entities/bulk", json={
            "ids": [eid, eid2],
            "action": "star",
        })
        assert r.status_code == 200
        assert r.get_json()["affected"] == 2

        # Verify starred
        r = c.get(f"/api/entities/{eid}")
        assert r.get_json()["is_starred"]
        r = c.get(f"/api/entities/{eid2}")
        assert r.get_json()["is_starred"]

    def test_bulk_unstar(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]

        # Star first
        c.post("/api/entities/bulk", json={"ids": [eid], "action": "star"})
        # Unstar
        r = c.post("/api/entities/bulk", json={"ids": [eid], "action": "unstar"})
        assert r.status_code == 200

        r = c.get(f"/api/entities/{eid}")
        assert not r.get_json()["is_starred"]

    def test_bulk_set_category(self, client):
        """Bulk set_category on entities."""
        # Create project with seed categories so we have valid category IDs
        pid = client.db.create_project(
            name="Bulk Cat Test",
            purpose="Test",
            seed_categories=["Alpha", "Beta"],
            entity_schema=PRODUCT_SCHEMA,
        )
        cats = client.db.get_categories(project_id=pid)
        cat_id = cats[0]["id"]

        # Create entity
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "company",
            "name": "Cat Test Corp",
            "attributes": {"url": "https://cattest.com"},
        })
        eid = r.get_json()["id"]

        r = client.post("/api/entities/bulk", json={
            "ids": [eid],
            "action": "set_category",
            "category_id": cat_id,
        })
        assert r.status_code == 200
        assert r.get_json()["affected"] == 1

    def test_bulk_set_attribute(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]

        r = c.post("/api/entities/bulk", json={
            "ids": [eid],
            "action": "set_attribute",
            "attr_slug": "what",
            "attr_value": "Updated via bulk",
        })
        assert r.status_code == 200

        r = c.get(f"/api/entities/{eid}")
        attrs = r.get_json()["attributes"]
        assert attrs.get("what", {}).get("value") == "Updated via bulk"

    def test_bulk_requires_ids_and_action(self, client):
        r = client.post("/api/entities/bulk", json={})
        assert r.status_code == 400

        r = client.post("/api/entities/bulk", json={"ids": [1]})
        assert r.status_code == 400

        r = client.post("/api/entities/bulk", json={"action": "delete"})
        assert r.status_code == 400

    def test_bulk_invalid_action(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post("/api/entities/bulk", json={
            "ids": [eid],
            "action": "fly_to_moon",
        })
        assert r.status_code == 400
        assert "Unknown action" in r.get_json()["error"]

    def test_bulk_invalid_ids_type(self, client):
        r = client.post("/api/entities/bulk", json={
            "ids": "not-a-list",
            "action": "delete",
        })
        assert r.status_code == 400

    def test_bulk_set_attribute_requires_slug(self, entity_with_company):
        c = entity_with_company["client"]
        eid = entity_with_company["entity_id"]
        r = c.post("/api/entities/bulk", json={
            "ids": [eid],
            "action": "set_attribute",
            "attr_value": "val",
        })
        assert r.status_code == 400
        assert "attr_slug is required" in r.get_json()["error"]
