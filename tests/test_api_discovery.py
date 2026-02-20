"""Tests for Discovery API — contexts, analyses, feature landscape, gap analysis.

Run: pytest tests/test_api_discovery.py -v
Markers: api, discovery
"""
import io
import pytest

pytestmark = [pytest.mark.api, pytest.mark.discovery]


# ---------------------------------------------------------------------------
# Context Files
# ---------------------------------------------------------------------------

class TestContextsList:
    """DISC-CTX-LIST: Context listing via GET /api/discovery/contexts."""

    def test_list_contexts_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/discovery/contexts?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_list_contexts_missing_project(self, client):
        r = client.get("/api/discovery/contexts")
        assert r.status_code == 400


class TestContextUpload:
    """DISC-CTX-UPLOAD: Context upload via POST /api/discovery/upload-context."""

    def test_upload_text_content(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/discovery/upload-context", json={
            "project_id": pid,
            "name": "Test Context",
            "content": "This is a test context document with product features.",
            "context_type": "features",
        })
        assert r.status_code == 200
        assert r.get_json()["id"] is not None

    def test_upload_missing_content_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/discovery/upload-context", json={
            "project_id": api_project["id"],
            "name": "Empty",
        })
        assert r.status_code == 400

    def test_upload_missing_project_rejected(self, client):
        r = client.post("/api/discovery/upload-context", json={
            "content": "Some content",
        })
        assert r.status_code == 400


class TestContextGet:
    """DISC-CTX-GET: Single context via GET /api/discovery/contexts/<id>."""

    def test_get_context(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/discovery/upload-context", json={
            "project_id": pid,
            "name": "Get Me",
            "content": "Context content here",
        })
        ctx_id = r.get_json()["id"]

        r = c.get(f"/api/discovery/contexts/{ctx_id}")
        assert r.status_code == 200

    def test_get_nonexistent(self, client):
        r = client.get("/api/discovery/contexts/99999")
        assert r.status_code == 404


class TestContextDelete:
    """DISC-CTX-DEL: Context deletion via DELETE /api/discovery/contexts/<id>."""

    def test_delete_context(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/discovery/upload-context", json={
            "project_id": pid,
            "name": "Delete Me",
            "content": "Will be deleted",
        })
        ctx_id = r.get_json()["id"]

        r = c.delete(f"/api/discovery/contexts/{ctx_id}")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

class TestAnalysesList:
    """DISC-ANALYSIS-LIST: Analysis listing via GET /api/discovery/analyses."""

    def test_list_analyses_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/discovery/analyses?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_list_analyses_missing_project(self, client):
        r = client.get("/api/discovery/analyses")
        assert r.status_code == 400


class TestAnalysisGet:
    """DISC-ANALYSIS-GET: Single analysis via GET /api/discovery/analyses/<id>."""

    def test_get_nonexistent(self, client):
        r = client.get("/api/discovery/analyses/99999")
        assert r.status_code == 404


class TestAnalysisDelete:
    """DISC-ANALYSIS-DEL: Analysis deletion."""

    def test_delete_nonexistent(self, client):
        r = client.delete("/api/discovery/analyses/99999")
        assert r.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Feature Landscape Validation
# ---------------------------------------------------------------------------

class TestFeatureLandscapeValidation:
    """DISC-LANDSCAPE: Feature landscape validation."""

    def test_landscape_missing_project(self, client):
        r = client.post("/api/discovery/feature-landscape", json={})
        assert r.status_code == 400

    def test_poll_landscape_nonexistent(self, client):
        r = client.get("/api/discovery/feature-landscape/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("pending", "error")


# ---------------------------------------------------------------------------
# Gap Analysis Validation
# ---------------------------------------------------------------------------

class TestGapAnalysisValidation:
    """DISC-GAP: Gap analysis validation."""

    def test_gap_analysis_missing_project(self, client):
        r = client.post("/api/discovery/gap-analysis", json={})
        assert r.status_code == 400

    def test_poll_gap_nonexistent(self, client):
        r = client.get("/api/discovery/gap-analysis/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("pending", "error")
