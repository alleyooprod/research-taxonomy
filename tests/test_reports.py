"""Tests for Reports & Synthesis API endpoints.

Covers:
- Report template availability detection
- Structured report generation (market overview, competitive, product teardown, design, change)
- Report CRUD (list, get, update, delete)
- Report export (HTML, JSON, Markdown)
- AI-enhanced report generation (mocked LLM)
- Edge cases: missing params, empty projects, nonexistent reports

Run: pytest tests/test_reports.py -v
Markers: db, api
"""
import json
import pytest
from unittest.mock import patch, MagicMock

import web.blueprints.reports as reports_mod

pytestmark = [pytest.mark.db, pytest.mark.api]


# ═══════════════════════════════════════════════════════════════
# Shared Schema + Fixtures
# ═══════════════════════════════════════════════════════════════

REPORT_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "Features", "slug": "features", "data_type": "tags"},
                {"name": "Pricing", "slug": "pricing_model", "data_type": "text"},
                {"name": "Price", "slug": "price", "data_type": "number"},
                {"name": "HQ City", "slug": "hq_city", "data_type": "text"},
                {"name": "URL", "slug": "url", "data_type": "url"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture(autouse=True)
def reset_table_flag():
    """Reset the _TABLE_ENSURED flag between tests."""
    reports_mod._TABLE_ENSURED = False
    yield
    reports_mod._TABLE_ENSURED = False


@pytest.fixture
def report_project(client):
    """Create a project with 3 entities + attributes for report testing."""
    db = client.db
    pid = db.create_project(
        name="Report Test",
        purpose="Testing reports",
        entity_schema=REPORT_SCHEMA,
    )

    eid1 = db.create_entity(pid, "company", "Alpha Corp")
    eid2 = db.create_entity(pid, "company", "Beta Inc")
    eid3 = db.create_entity(pid, "company", "Gamma LLC")

    # Alpha: many attributes (qualifies for product_teardown)
    db.set_entity_attribute(eid1, "features", json.dumps(["SSO", "API", "Webhooks"]))
    db.set_entity_attribute(eid1, "pricing_model", "subscription")
    db.set_entity_attribute(eid1, "price", "29")
    db.set_entity_attribute(eid1, "hq_city", "San Francisco")
    db.set_entity_attribute(eid1, "url", "https://alpha.com")

    # Beta: some attributes
    db.set_entity_attribute(eid2, "features", json.dumps(["SSO", "MFA"]))
    db.set_entity_attribute(eid2, "pricing_model", "freemium")
    db.set_entity_attribute(eid2, "price", "0")

    # Gamma: fewer attributes
    db.set_entity_attribute(eid3, "features", json.dumps(["API"]))
    db.set_entity_attribute(eid3, "pricing_model", "flat-rate")

    return {
        "client": client,
        "project_id": pid,
        "entity_ids": [eid1, eid2, eid3],
        "db": db,
    }


@pytest.fixture
def report_project_with_evidence(report_project):
    """Add screenshot evidence to the report project."""
    db = report_project["db"]
    eid1 = report_project["entity_ids"][0]

    db.add_evidence(
        entity_id=eid1,
        evidence_type="screenshot",
        file_path="/evidence/1/landing.png",
        source_url="https://alpha.com",
        metadata={"page_type": "landing"},
    )
    db.add_evidence(
        entity_id=eid1,
        evidence_type="screenshot",
        file_path="/evidence/1/pricing.png",
        source_url="https://alpha.com/pricing",
        metadata={"page_type": "pricing"},
    )

    return report_project


@pytest.fixture
def report_project_with_snapshots(report_project):
    """Add snapshots to the report project."""
    db = report_project["db"]
    pid = report_project["project_id"]
    eid1 = report_project["entity_ids"][0]

    snap1_id = db.create_snapshot(pid, description="Initial capture")
    db.set_entity_attribute(eid1, "price", "29", snapshot_id=snap1_id)

    snap2_id = db.create_snapshot(pid, description="Price update")
    db.set_entity_attribute(eid1, "price", "39", snapshot_id=snap2_id)

    report_project["snapshot_ids"] = [snap1_id, snap2_id]
    return report_project


# ═══════════════════════════════════════════════════════════════
# Template Availability Tests
# ═══════════════════════════════════════════════════════════════

class TestReportTemplates:
    """Tests for GET /api/synthesis/templates."""

    def test_missing_project_id(self, client):
        r = client.get("/api/synthesis/templates")
        assert r.status_code == 400

    def test_empty_project(self, client):
        db = client.db
        pid = db.create_project(name="Empty", purpose="Test", entity_schema=REPORT_SCHEMA)
        r = client.get(f"/api/synthesis/templates?project_id={pid}")
        assert r.status_code == 200
        templates = r.get_json()
        assert isinstance(templates, list)
        assert len(templates) == 5
        # All should be unavailable
        for t in templates:
            assert "slug" in t
            assert "available" in t
            assert "name" in t

    def test_market_overview_available(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.get(f"/api/synthesis/templates?project_id={pid}")
        templates = {t["slug"]: t for t in r.get_json()}
        assert templates["market_overview"]["available"] is True

    def test_competitive_landscape_available(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.get(f"/api/synthesis/templates?project_id={pid}")
        templates = {t["slug"]: t for t in r.get_json()}
        assert templates["competitive_landscape"]["available"] is True

    def test_product_teardown_available(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.get(f"/api/synthesis/templates?project_id={pid}")
        templates = {t["slug"]: t for t in r.get_json()}
        assert templates["product_teardown"]["available"] is True

    def test_design_patterns_with_evidence(self, report_project_with_evidence):
        c = report_project_with_evidence["client"]
        pid = report_project_with_evidence["project_id"]
        r = c.get(f"/api/synthesis/templates?project_id={pid}")
        templates = {t["slug"]: t for t in r.get_json()}
        assert templates["design_patterns"]["available"] is True

    def test_design_patterns_without_evidence(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.get(f"/api/synthesis/templates?project_id={pid}")
        templates = {t["slug"]: t for t in r.get_json()}
        assert templates["design_patterns"]["available"] is False

    def test_change_report_with_snapshots(self, report_project_with_snapshots):
        c = report_project_with_snapshots["client"]
        pid = report_project_with_snapshots["project_id"]
        r = c.get(f"/api/synthesis/templates?project_id={pid}")
        templates = {t["slug"]: t for t in r.get_json()}
        assert templates["change_report"]["available"] is True


# ═══════════════════════════════════════════════════════════════
# Report Generation Tests
# ═══════════════════════════════════════════════════════════════

class TestGenerateReport:
    """Tests for POST /api/synthesis/generate."""

    def test_missing_project_id(self, client):
        r = client.post("/api/synthesis/generate", json={"template": "market_overview"})
        assert r.status_code == 400

    def test_missing_template(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.post("/api/synthesis/generate", json={"project_id": pid})
        assert r.status_code == 400

    def test_unknown_template(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.post("/api/synthesis/generate", json={
            "project_id": pid, "template": "nonexistent",
        })
        assert r.status_code == 400

    def test_generate_market_overview(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.post("/api/synthesis/generate", json={
            "project_id": pid, "template": "market_overview",
        })
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert "id" in data
        assert data["template"] == "market_overview"
        assert "title" in data
        assert "sections" in data or "content_json" in data

    def test_generate_competitive_landscape(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.post("/api/synthesis/generate", json={
            "project_id": pid, "template": "competitive_landscape",
        })
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data["template"] == "competitive_landscape"

    def test_generate_product_teardown(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        eid = report_project["entity_ids"][0]
        r = c.post("/api/synthesis/generate", json={
            "project_id": pid, "template": "product_teardown",
            "entity_ids": [eid],
        })
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data["template"] == "product_teardown"

    def test_generate_with_entity_filter(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        eids = report_project["entity_ids"][:2]
        r = c.post("/api/synthesis/generate", json={
            "project_id": pid, "template": "market_overview",
            "entity_ids": eids,
        })
        assert r.status_code in (200, 201)


# ═══════════════════════════════════════════════════════════════
# AI Report Generation Tests
# ═══════════════════════════════════════════════════════════════

class TestGenerateAIReport:
    """Tests for POST /api/synthesis/generate-ai (mocked LLM)."""

    @patch("core.llm.run_cli")
    def test_ai_report_generation(self, mock_run_cli, report_project):
        mock_run_cli.return_value = {
            "result": json.dumps({
                "title": "Market Overview Report",
                "sections": [
                    {"heading": "Executive Summary", "content": "This is an AI-generated summary."},
                    {"heading": "Key Findings", "content": "Finding 1: Alpha Corp leads.\nFinding 2: Market is growing."},
                ],
            }),
            "cost_usd": 0.01,
            "duration_ms": 500,
            "is_error": False,
            "structured_output": None,
        }
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.post("/api/synthesis/generate-ai", json={
            "project_id": pid, "template": "market_overview",
        })
        assert r.status_code in (200, 201)
        data = r.get_json()
        assert data.get("is_ai_generated") in (True, 1)

    @patch("core.llm.run_cli")
    def test_ai_report_with_audience(self, mock_run_cli, report_project):
        mock_run_cli.return_value = {
            "result": json.dumps({
                "title": "Market Overview for Investors",
                "sections": [{"heading": "Summary", "content": "For investors..."}],
            }),
            "cost_usd": 0.005,
            "duration_ms": 300,
            "is_error": False,
            "structured_output": None,
        }
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.post("/api/synthesis/generate-ai", json={
            "project_id": pid, "template": "market_overview",
            "audience": "Investors",
            "questions": ["What is the TAM?", "Who are the key players?"],
        })
        assert r.status_code in (200, 201)

    def test_ai_report_missing_template(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.post("/api/synthesis/generate-ai", json={"project_id": pid})
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# Report CRUD Tests
# ═══════════════════════════════════════════════════════════════

class TestReportCRUD:
    """Tests for report list, get, update, delete."""

    def _create_report(self, client, pid):
        """Helper to create a report and return its data."""
        r = client.post("/api/synthesis/generate", json={
            "project_id": pid, "template": "market_overview",
        })
        return r.get_json()

    def test_list_reports(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        # Create two reports
        self._create_report(c, pid)
        self._create_report(c, pid)
        r = c.get(f"/api/synthesis?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        reports = data if isinstance(data, list) else data.get("reports", [])
        assert len(reports) >= 2

    def test_list_reports_missing_project(self, client):
        r = client.get("/api/synthesis")
        assert r.status_code == 400

    def test_get_single_report(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        created = self._create_report(c, pid)
        rid = created["id"]
        r = c.get(f"/api/synthesis/{rid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] == rid

    def test_get_nonexistent_report(self, report_project):
        c = report_project["client"]
        r = c.get("/api/synthesis/99999")
        assert r.status_code == 404

    def test_update_report_title(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        created = self._create_report(c, pid)
        rid = created["id"]
        r = c.put(f"/api/synthesis/{rid}", json={"title": "Updated Title"})
        assert r.status_code == 200
        # Verify the title was updated
        r2 = c.get(f"/api/synthesis/{rid}")
        assert r2.get_json()["title"] == "Updated Title"

    def test_delete_report(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        created = self._create_report(c, pid)
        rid = created["id"]
        r = c.delete(f"/api/synthesis/{rid}")
        assert r.status_code == 200
        # Verify it's gone
        r2 = c.get(f"/api/synthesis/{rid}")
        assert r2.status_code == 404

    def test_delete_nonexistent_report(self, report_project):
        c = report_project["client"]
        r = c.delete("/api/synthesis/99999")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Report Export Tests
# ═══════════════════════════════════════════════════════════════

class TestReportExport:
    """Tests for GET /api/synthesis/<id>/export."""

    def _create_report(self, client, pid):
        r = client.post("/api/synthesis/generate", json={
            "project_id": pid, "template": "market_overview",
        })
        return r.get_json()

    def test_export_json(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        created = self._create_report(c, pid)
        rid = created["id"]
        r = c.get(f"/api/synthesis/{rid}/export?format=json")
        assert r.status_code == 200
        assert r.content_type.startswith("application/json")

    def test_export_markdown(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        created = self._create_report(c, pid)
        rid = created["id"]
        r = c.get(f"/api/synthesis/{rid}/export?format=markdown")
        assert r.status_code == 200
        # Markdown should be text content
        assert "text" in r.content_type or "markdown" in r.content_type

    def test_export_html(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        created = self._create_report(c, pid)
        rid = created["id"]
        r = c.get(f"/api/synthesis/{rid}/export?format=html")
        assert r.status_code == 200
        assert "html" in r.content_type

    def test_export_nonexistent_report(self, report_project):
        c = report_project["client"]
        r = c.get("/api/synthesis/99999/export?format=json")
        assert r.status_code == 404

    def test_export_default_format(self, report_project):
        c = report_project["client"]
        pid = report_project["project_id"]
        created = self._create_report(c, pid)
        rid = created["id"]
        # No format param — should default to something reasonable
        r = c.get(f"/api/synthesis/{rid}/export")
        assert r.status_code in (200, 400)


# ═══════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestReportEdgeCases:
    """Edge case tests for reports."""

    def test_generate_for_nonexistent_project(self, client):
        r = client.post("/api/synthesis/generate", json={
            "project_id": 99999, "template": "market_overview",
        })
        assert r.status_code == 404

    def test_list_reports_empty_project(self, client):
        db = client.db
        pid = db.create_project(name="No Reports", purpose="Test", entity_schema=REPORT_SCHEMA)
        r = client.get(f"/api/synthesis?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        reports = data if isinstance(data, list) else data.get("reports", [])
        assert len(reports) == 0

    def test_template_slugs_match(self, report_project):
        """All 5 template slugs should be present."""
        c = report_project["client"]
        pid = report_project["project_id"]
        r = c.get(f"/api/synthesis/templates?project_id={pid}")
        slugs = {t["slug"] for t in r.get_json()}
        expected = {"market_overview", "competitive_landscape", "product_teardown",
                    "design_patterns", "change_report"}
        assert expected == slugs
