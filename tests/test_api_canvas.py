"""Tests for Canvas API — CRUD, diagram generation.

Run: pytest tests/test_api_canvas.py -v
Markers: api, canvas
"""
import pytest

pytestmark = [pytest.mark.api, pytest.mark.canvas]


class TestCanvasCreate:
    """CVS-CREATE: Canvas creation via POST /api/canvases."""

    def test_create_canvas(self, api_project):
        c = api_project["client"]
        r = c.post("/api/canvases", json={
            "project_id": api_project["id"],
            "title": "Test Canvas",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] is not None
        assert data["status"] == "ok"

    def test_create_canvas_default_title(self, api_project):
        c = api_project["client"]
        r = c.post("/api/canvases", json={
            "project_id": api_project["id"],
        })
        assert r.status_code == 200


class TestCanvasList:
    """CVS-LIST: Canvas listing via GET /api/canvases."""

    def test_list_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/canvases?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_list_returns_created(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        c.post("/api/canvases", json={"project_id": pid, "title": "Canvas 1"})
        c.post("/api/canvases", json={"project_id": pid, "title": "Canvas 2"})

        r = c.get(f"/api/canvases?project_id={pid}")
        canvases = r.get_json()
        assert len(canvases) >= 2


class TestCanvasGet:
    """CVS-GET: Single canvas via GET /api/canvases/<id>."""

    def test_get_canvas(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/canvases", json={"project_id": pid, "title": "Get Me"})
        canvas_id = r.get_json()["id"]

        r = c.get(f"/api/canvases/{canvas_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["title"] == "Get Me"

    def test_get_nonexistent(self, client):
        r = client.get("/api/canvases/99999")
        assert r.status_code == 404


class TestCanvasUpdate:
    """CVS-UPDATE: Canvas update via PUT /api/canvases/<id>."""

    def test_update_title(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/canvases", json={"project_id": pid, "title": "Old Title"})
        canvas_id = r.get_json()["id"]

        r = c.put(f"/api/canvases/{canvas_id}", json={"title": "New Title"})
        assert r.status_code == 200

        r = c.get(f"/api/canvases/{canvas_id}")
        assert r.get_json()["title"] == "New Title"

    def test_update_data(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/canvases", json={"project_id": pid, "title": "Data Test"})
        canvas_id = r.get_json()["id"]

        canvas_data = {"elements": [{"type": "rectangle", "x": 0, "y": 0}]}
        r = c.put(f"/api/canvases/{canvas_id}", json={
            "data": canvas_data,
        })
        assert r.status_code == 200


class TestCanvasDelete:
    """CVS-DELETE: Canvas deletion via DELETE /api/canvases/<id>."""

    def test_delete_canvas(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/canvases", json={"project_id": pid, "title": "Delete Me"})
        canvas_id = r.get_json()["id"]

        r = c.delete(f"/api/canvases/{canvas_id}")
        assert r.status_code == 200

        # Should no longer appear
        r = c.get(f"/api/canvases?project_id={pid}")
        ids = [cv["id"] for cv in r.get_json()]
        assert canvas_id not in ids


class TestDiagramGeneration:
    """CVS-DIAGRAM: Diagram generation endpoint validation."""

    def test_generate_diagram_missing_fields(self, api_project):
        c = api_project["client"]
        r = c.post("/api/canvases/generate-diagram", json={
            "project_id": api_project["id"],
        })
        assert r.status_code == 400

    def test_generate_diagram_missing_project_id(self, client):
        r = client.post("/api/canvases/generate-diagram", json={
            "category_ids": [1],
            "prompt": "Test diagram",
        })
        assert r.status_code == 400

    def test_generate_diagram_missing_categories(self, api_project):
        c = api_project["client"]
        r = c.post("/api/canvases/generate-diagram", json={
            "project_id": api_project["id"],
            "prompt": "Test diagram",
        })
        assert r.status_code == 400

    def test_poll_nonexistent_diagram(self, client):
        r = client.get("/api/canvases/generate-diagram/nonexistent1234")
        assert r.status_code == 200
        data = r.get_json()
        # Should be pending or error (invalid hex)
        assert data["status"] in ("pending", "error")
