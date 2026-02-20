"""Tests for Dimensions API — CRUD, values, AI explore, AI populate.

Run: pytest tests/test_api_dimensions.py -v
Markers: api, dimensions
"""
import pytest

pytestmark = [pytest.mark.api, pytest.mark.dimensions]


class TestDimensionsList:
    """DIM-LIST: Dimension listing via GET /api/dimensions."""

    def test_list_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/dimensions?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_list_missing_project_rejected(self, client):
        r = client.get("/api/dimensions")
        assert r.status_code == 400


class TestDimensionCreate:
    """DIM-CREATE: Dimension creation via POST /api/dimensions."""

    def test_create_text_dimension(self, api_project):
        c = api_project["client"]
        r = c.post("/api/dimensions", json={
            "project_id": api_project["id"],
            "name": "Market Segment",
            "description": "Primary market segment",
            "data_type": "text",
        })
        assert r.status_code == 200
        assert r.get_json()["id"] is not None

    def test_create_number_dimension(self, api_project):
        c = api_project["client"]
        r = c.post("/api/dimensions", json={
            "project_id": api_project["id"],
            "name": "Revenue",
            "data_type": "number",
        })
        assert r.status_code == 200

    def test_create_enum_dimension(self, api_project):
        c = api_project["client"]
        r = c.post("/api/dimensions", json={
            "project_id": api_project["id"],
            "name": "Stage",
            "data_type": "enum",
            "enum_values": "early,growth,mature",
        })
        assert r.status_code == 200

    def test_create_boolean_dimension(self, api_project):
        c = api_project["client"]
        r = c.post("/api/dimensions", json={
            "project_id": api_project["id"],
            "name": "Has API",
            "data_type": "boolean",
        })
        assert r.status_code == 200

    def test_create_missing_name_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/dimensions", json={
            "project_id": api_project["id"],
        })
        assert r.status_code == 400

    def test_create_missing_project_rejected(self, client):
        r = client.post("/api/dimensions", json={"name": "Orphan"})
        assert r.status_code == 400

    def test_create_invalid_data_type_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/dimensions", json={
            "project_id": api_project["id"],
            "name": "Bad Type",
            "data_type": "invalid_type",
        })
        assert r.status_code == 400


class TestDimensionDelete:
    """DIM-DELETE: Dimension deletion via DELETE /api/dimensions/<id>."""

    def test_delete_dimension(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/dimensions", json={
            "project_id": pid,
            "name": "Delete Me",
            "data_type": "text",
        })
        dim_id = r.get_json()["id"]

        r = c.delete(f"/api/dimensions/{dim_id}")
        assert r.status_code == 200


class TestDimensionValues:
    """DIM-VALUES: Dimension value get/set."""

    def test_get_values_empty(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/dimensions", json={
            "project_id": pid,
            "name": "Values Test",
            "data_type": "text",
        })
        dim_id = r.get_json()["id"]

        r = c.get(f"/api/dimensions/{dim_id}/values")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_set_value(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cid = api_project_with_companies["company_ids"][0]

        r = c.post("/api/dimensions", json={
            "project_id": pid,
            "name": "Test Dim",
            "data_type": "text",
        })
        dim_id = r.get_json()["id"]

        r = c.post(f"/api/dimensions/{dim_id}/set-value", json={
            "company_id": cid,
            "value": "Some value",
        })
        assert r.status_code == 200

    def test_set_value_missing_company_rejected(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/dimensions", json={
            "project_id": pid,
            "name": "No Company",
            "data_type": "text",
        })
        dim_id = r.get_json()["id"]

        r = c.post(f"/api/dimensions/{dim_id}/set-value", json={
            "value": "Orphan value",
        })
        assert r.status_code == 400


class TestCompanyDimensions:
    """DIM-COMPANY: Company dimension values via GET /api/companies/<id>/dimensions."""

    def test_get_company_dimensions(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.get(f"/api/companies/{cid}/dimensions")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)


class TestExploreValidation:
    """DIM-EXPLORE: Dimension exploration validation."""

    def test_explore_missing_project_rejected(self, client):
        r = client.post("/api/dimensions/explore", json={})
        assert r.status_code == 400

    def test_poll_explore_nonexistent(self, client):
        r = client.get("/api/dimensions/explore/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("pending", "error")


class TestPopulateValidation:
    """DIM-POPULATE: Dimension populate validation."""

    def test_populate_missing_project_rejected(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/dimensions", json={
            "project_id": pid,
            "name": "Pop Test",
            "data_type": "text",
        })
        dim_id = r.get_json()["id"]

        # Missing project_id in populate request
        r = c.post(f"/api/dimensions/{dim_id}/populate", json={})
        assert r.status_code == 400

    def test_poll_populate_nonexistent(self, client):
        r = client.get("/api/dimensions/populate/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("pending", "error")
