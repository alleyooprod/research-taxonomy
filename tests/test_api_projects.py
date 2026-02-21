"""Tests for Projects API — CRUD, feature toggles, validation.

Run: pytest tests/test_api_projects.py -v
Markers: api, projects
"""
import json
import pytest

pytestmark = [pytest.mark.api, pytest.mark.projects]


class TestCreateProject:
    """PRJ-CREATE: Project creation via POST /api/projects."""

    def test_create_minimal(self, client):
        r = client.post("/api/projects", json={"name": "Minimal"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] is not None
        assert data["status"] == "ok"

    def test_create_with_all_fields(self, client):
        r = client.post("/api/projects", json={
            "name": "Full Project",
            "purpose": "Research purpose",
            "outcome": "Expected outcome",
            "description": "Detailed description",
            "seed_categories": "Cat1\nCat2\nCat3",
            "example_links": "https://a.com\nhttps://b.com",
            "market_keywords": "health,tech,ai",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] is not None

    def test_create_seeds_categories(self, client):
        r = client.post("/api/projects", json={
            "name": "Seed Test",
            "seed_categories": "Alpha\nBeta\nGamma",
        })
        pid = r.get_json()["id"]

        r = client.get(f"/api/taxonomy?project_id={pid}")
        cats = r.get_json()
        names = {c["name"] for c in cats}
        assert {"Alpha", "Beta", "Gamma"} <= names

    def test_create_rejects_missing_name(self, client):
        r = client.post("/api/projects", json={"purpose": "No name"})
        assert r.status_code == 400

    def test_create_rejects_empty_name(self, client):
        r = client.post("/api/projects", json={"name": ""})
        assert r.status_code == 400

    def test_create_multiple_projects(self, client):
        for i in range(3):
            r = client.post("/api/projects", json={"name": f"Project {i}"})
            assert r.status_code == 200

        r = client.get("/api/projects")
        projects = r.get_json()
        assert len(projects) >= 3


class TestListProjects:
    """PRJ-LIST: Project listing via GET /api/projects."""

    def test_list_empty(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_list_returns_created_projects(self, client):
        client.post("/api/projects", json={"name": "Listed Project"})
        r = client.get("/api/projects")
        projects = r.get_json()
        assert any(p["name"] == "Listed Project" for p in projects)


class TestGetProject:
    """PRJ-GET: Single project retrieval via GET /api/projects/<id>."""

    def test_get_existing(self, api_project):
        client = api_project["client"]
        r = client.get(f"/api/projects/{api_project['id']}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "API Test Project"

    def test_get_nonexistent(self, client):
        r = client.get("/api/projects/99999")
        assert r.status_code == 404


class TestUpdateProject:
    """PRJ-UPDATE: Project update via POST /api/projects/<id>."""

    def test_update_purpose(self, api_project):
        client = api_project["client"]
        pid = api_project["id"]
        r = client.post(f"/api/projects/{pid}", json={"purpose": "Updated purpose"})
        assert r.status_code == 200

        r = client.get(f"/api/projects/{pid}")
        assert r.get_json()["purpose"] == "Updated purpose"

    def test_update_multiple_fields(self, api_project):
        client = api_project["client"]
        pid = api_project["id"]
        r = client.post(f"/api/projects/{pid}", json={
            "purpose": "New purpose",
            "outcome": "New outcome",
            "description": "New desc",
        })
        assert r.status_code == 200


class TestToggleFeature:
    """PRJ-FEATURE: Feature toggle via POST /api/projects/<id>/toggle-feature."""

    def test_toggle_feature(self, api_project):
        client = api_project["client"]
        pid = api_project["id"]
        r = client.post(f"/api/projects/{pid}/toggle-feature", json={
            "feature": "canvas_enabled",
            "enabled": True,
        })
        assert r.status_code == 200
        data = r.get_json()
        assert "features" in data

    def test_toggle_missing_feature_name(self, api_project):
        client = api_project["client"]
        pid = api_project["id"]
        r = client.post(f"/api/projects/{pid}/toggle-feature", json={
            "enabled": True,
        })
        assert r.status_code == 400

    def test_toggle_nonexistent_project(self, client):
        r = client.post("/api/projects/99999/toggle-feature", json={
            "feature": "test", "enabled": True,
        })
        assert r.status_code == 404


class TestDeleteProject:
    """PRJ-DELETE: Project deletion via DELETE /api/projects/<id>."""

    def test_delete_empty_project(self, api_project):
        client = api_project["client"]
        pid = api_project["id"]
        r = client.delete(f"/api/projects/{pid}")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"
        # Verify project is gone
        r = client.get(f"/api/projects/{pid}")
        assert r.status_code == 404

    def test_delete_project_with_companies(self, api_project_with_companies):
        client = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = client.delete(f"/api/projects/{pid}")
        assert r.status_code == 200

        # Verify project is gone
        r = client.get(f"/api/projects/{pid}")
        assert r.status_code == 404

    def test_delete_project_with_entities(self, client):
        # Create project with entity schema
        r = client.post("/api/projects", json={
            "name": "Delete Entity Test",
            "seed_categories": "Cat1",
            "entity_schema": {
                "entity_types": [
                    {"slug": "company", "name": "Company", "attributes": [
                        {"slug": "website", "name": "Website", "type": "url"},
                    ]},
                ],
                "relationships": [],
            },
        })
        pid = r.get_json()["id"]

        # Add an entity
        r = client.post("/api/entities", json={
            "project_id": pid, "type": "company", "name": "Test Corp",
        })
        assert r.status_code == 201

        # Delete project
        r = client.delete(f"/api/projects/{pid}")
        assert r.status_code == 200

        # Verify project is gone
        r = client.get(f"/api/projects/{pid}")
        assert r.status_code == 404

    def test_delete_nonexistent_project(self, client):
        r = client.delete("/api/projects/99999")
        assert r.status_code == 404

    def test_delete_removes_from_listing(self, api_project):
        client = api_project["client"]
        pid = api_project["id"]
        client.delete(f"/api/projects/{pid}")
        r = client.get("/api/projects")
        projects = r.get_json()
        assert not any(p["id"] == pid for p in projects)


class TestProjectHasData:
    """PRJ-HASDATA: Check if project has data via GET /api/projects/<id>/has-data."""

    def test_empty_project(self, api_project):
        client = api_project["client"]
        pid = api_project["id"]
        r = client.get(f"/api/projects/{pid}/has-data")
        assert r.status_code == 200
        data = r.get_json()
        assert data["has_data"] is False
        assert data["entity_count"] == 0
        assert data["company_count"] == 0

    def test_project_with_companies(self, api_project_with_companies):
        client = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = client.get(f"/api/projects/{pid}/has-data")
        assert r.status_code == 200
        data = r.get_json()
        assert data["has_data"] is True
        assert data["company_count"] > 0

    def test_nonexistent_project(self, client):
        r = client.get("/api/projects/99999/has-data")
        assert r.status_code == 404
