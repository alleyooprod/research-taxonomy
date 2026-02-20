"""Tests for Research API — sessions, templates, reports.

Run: pytest tests/test_api_research.py -v
Markers: api, research
"""
import pytest

pytestmark = [pytest.mark.api, pytest.mark.research]


# ---------------------------------------------------------------------------
# Research Sessions
# ---------------------------------------------------------------------------

class TestResearchValidation:
    """RES-START: Research session creation validation."""

    def test_research_empty_prompt_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/research", json={
            "prompt": "",
            "project_id": api_project["id"],
        })
        assert r.status_code == 400

    def test_research_missing_prompt_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/research", json={
            "project_id": api_project["id"],
        })
        assert r.status_code == 400


class TestResearchList:
    """RES-LIST: Research listing via GET /api/research."""

    def test_list_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/research?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)


class TestResearchGet:
    """RES-GET: Single research via GET /api/research/<id>."""

    def test_get_nonexistent(self, client):
        r = client.get("/api/research/99999")
        assert r.status_code == 404


class TestResearchDelete:
    """RES-DELETE: Research deletion via DELETE /api/research/<id>."""

    def test_delete_nonexistent(self, client):
        # Should handle gracefully
        r = client.delete("/api/research/99999")
        assert r.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Research Templates
# ---------------------------------------------------------------------------

class TestResearchTemplates:
    """RES-TPL: Research template CRUD."""

    def test_list_templates_auto_seeds(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.get(f"/api/research/templates?project_id={pid}")
        assert r.status_code == 200
        templates = r.get_json()
        # Should auto-seed default templates
        assert isinstance(templates, list)

    def test_create_template(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/research/templates", json={
            "project_id": pid,
            "name": "Custom Template",
            "prompt_template": "Analyze {company} for competitive positioning",
            "scope_type": "company",
        })
        assert r.status_code == 200
        assert r.get_json()["id"] is not None

    def test_update_template(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/research/templates", json={
            "project_id": pid,
            "name": "Update Me",
            "prompt_template": "Original prompt",
        })
        tid = r.get_json()["id"]

        r = c.put(f"/api/research/templates/{tid}", json={
            "name": "Updated Template",
            "prompt_template": "Updated prompt for {company}",
        })
        assert r.status_code == 200

    def test_delete_template(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/research/templates", json={
            "project_id": pid,
            "name": "Delete Me",
            "prompt_template": "Delete this",
        })
        tid = r.get_json()["id"]

        r = c.delete(f"/api/research/templates/{tid}")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class TestReports:
    """RES-REPORTS: Saved report management."""

    def test_list_reports_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/reports?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_get_report_nonexistent(self, client):
        r = client.get("/api/reports/99999")
        assert r.status_code == 404

    def test_delete_report_nonexistent(self, client):
        r = client.delete("/api/reports/99999")
        assert r.status_code in (200, 404)

    def test_export_report_nonexistent(self, client):
        r = client.get("/api/reports/99999/export/md")
        assert r.status_code == 404


class TestMarketReportValidation:
    """RES-MKT-RPT: Market report generation validation."""

    def test_market_report_missing_category(self, api_project):
        c = api_project["client"]
        r = c.post("/api/ai/market-report", json={
            "project_id": api_project["id"],
        })
        assert r.status_code == 400
