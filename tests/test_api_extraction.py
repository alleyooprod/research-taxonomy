"""Tests for Extraction API — extraction trigger, jobs, results, review, stats.

Covers:
- POST /api/extract (trigger extraction — mocked LLM)
- POST /api/extract/from-url (URL extraction — mocked HTTP + LLM)
- GET  /api/extract/jobs (list jobs)
- GET  /api/extract/jobs/<id> (get job + results)
- DELETE /api/extract/jobs/<id> (delete job)
- GET  /api/extract/results (list results with filters)
- GET  /api/extract/queue (review queue)
- POST /api/extract/results/<id>/review (accept/reject/edit)
- POST /api/extract/results/bulk-review (bulk review)
- GET  /api/extract/contradictions (contradiction detection)
- GET  /api/extract/stats (extraction statistics)
- Validation: missing fields, invalid entity, bad actions

Run: pytest tests/test_api_extraction.py -v
Markers: api, extraction
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.extraction import ExtractionResult

pytestmark = [pytest.mark.api, pytest.mark.extraction]

# Schema used across tests
TEST_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "Description", "slug": "description", "data_type": "text"},
                {"name": "Website", "slug": "website_url", "data_type": "url"},
                {"name": "Founded Year", "slug": "founded_year", "data_type": "number"},
                {"name": "Headquarters", "slug": "headquarters", "data_type": "text"},
                {"name": "Has Free Tier", "slug": "has_free_tier", "data_type": "boolean"},
            ],
        },
    ],
    "relationships": [],
}


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def extraction_project(client, tmp_path, monkeypatch):
    """Create a project with entity and evidence for extraction tests."""
    import core.capture as capture_mod
    test_evidence_dir = tmp_path / "evidence"
    test_evidence_dir.mkdir()
    monkeypatch.setattr(capture_mod, "EVIDENCE_DIR", test_evidence_dir)

    pid = client.db.create_project(
        name="Extraction API Test",
        purpose="Testing extraction API",
        entity_schema=TEST_SCHEMA,
    )
    eid = client.db.create_entity(pid, "company", "TestCo")

    # Create evidence file
    ev_dir = test_evidence_dir / str(pid) / str(eid) / "page_archive"
    ev_dir.mkdir(parents=True)
    html_file = ev_dir / "test_page.html"
    html_file.write_text("<html><body><h1>TestCo</h1><p>Founded 2020 in London</p></body></html>")

    rel_path = f"{pid}/{eid}/page_archive/test_page.html"
    ev_id = client.db.add_evidence(
        entity_id=eid,
        evidence_type="page_archive",
        file_path=rel_path,
        source_url="https://testco.com",
    )

    return {
        "client": client,
        "project_id": pid,
        "entity_id": eid,
        "evidence_id": ev_id,
        "evidence_dir": test_evidence_dir,
    }


@pytest.fixture
def extraction_with_results(extraction_project):
    """Project with extraction jobs and results already created."""
    c = extraction_project["client"]
    pid = extraction_project["project_id"]
    eid = extraction_project["entity_id"]

    j1 = c.db.create_extraction_job(pid, eid, source_type="evidence")
    c.db.update_extraction_job(j1, status="completed", cost_usd=0.005, result_count=3)

    r1 = c.db.create_extraction_result(j1, eid, "description", "SaaS platform", confidence=0.9)
    r2 = c.db.create_extraction_result(j1, eid, "headquarters", "London", confidence=0.85)
    r3 = c.db.create_extraction_result(j1, eid, "founded_year", "2020", confidence=0.95)

    return {
        **extraction_project,
        "job_id": j1,
        "result_ids": [r1, r2, r3],
    }


# ═══════════════════════════════════════════════════════════════
# Trigger Extraction
# ═══════════════════════════════════════════════════════════════

class TestTriggerExtraction:
    """EXT-API-TRIG: Extraction trigger endpoint tests."""

    @patch("core.llm.run_cli")
    def test_extract_from_evidence(self, mock_llm, extraction_project):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.005,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "extracted_attributes": [
                    {"attr_slug": "description", "value": "A SaaS company", "confidence": 0.9, "reasoning": "Found on page"},
                    {"attr_slug": "founded_year", "value": 2020, "confidence": 0.95, "reasoning": "Stated directly"},
                ],
                "entity_summary": "TestCo is a SaaS company",
            },
        }

        c = extraction_project["client"]
        r = c.post("/api/extract", json={
            "entity_id": extraction_project["entity_id"],
            "project_id": extraction_project["project_id"],
            "evidence_id": extraction_project["evidence_id"],
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["success"] is True
        assert len(data["extracted_attributes"]) == 2

    def test_extract_missing_entity_id(self, extraction_project):
        c = extraction_project["client"]
        r = c.post("/api/extract", json={
            "project_id": extraction_project["project_id"],
        })
        assert r.status_code == 400
        assert "entity_id" in r.get_json()["error"]

    def test_extract_missing_project_id(self, extraction_project):
        c = extraction_project["client"]
        r = c.post("/api/extract", json={
            "entity_id": extraction_project["entity_id"],
        })
        assert r.status_code == 400
        assert "project_id" in r.get_json()["error"]

    def test_extract_nonexistent_entity(self, extraction_project):
        c = extraction_project["client"]
        r = c.post("/api/extract", json={
            "entity_id": 99999,
            "project_id": extraction_project["project_id"],
        })
        assert r.status_code == 404

    def test_extract_nonexistent_evidence(self, extraction_project):
        c = extraction_project["client"]
        r = c.post("/api/extract", json={
            "entity_id": extraction_project["entity_id"],
            "project_id": extraction_project["project_id"],
            "evidence_id": 99999,
        })
        assert r.status_code == 404

    @patch("core.llm.run_cli")
    def test_extract_from_all_evidence(self, mock_llm, extraction_project):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.003,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "extracted_attributes": [
                    {"attr_slug": "headquarters", "value": "London", "confidence": 0.8, "reasoning": "Found"},
                ],
            },
        }

        c = extraction_project["client"]
        r = c.post("/api/extract", json={
            "entity_id": extraction_project["entity_id"],
            "project_id": extraction_project["project_id"],
            # No evidence_id — extract from all
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["success"] is True


class TestExtractFromURL:
    """EXT-API-URL: URL-based extraction endpoint tests."""

    @patch("core.extraction.extract_from_url")
    def test_extract_from_url(self, mock_extract, extraction_project):
        mock_extract.return_value = ExtractionResult(
            success=True,
            entity_id=extraction_project["entity_id"],
            extracted_attributes=[
                {"attr_slug": "description", "value": "Test", "confidence": 0.9, "reasoning": "OK"},
            ],
            cost_usd=0.004,
            duration_ms=2000,
        )

        c = extraction_project["client"]
        r = c.post("/api/extract/from-url", json={
            "url": "https://testco.com",
            "entity_id": extraction_project["entity_id"],
            "project_id": extraction_project["project_id"],
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["success"] is True

    def test_extract_url_missing_fields(self, extraction_project):
        c = extraction_project["client"]
        r = c.post("/api/extract/from-url", json={"entity_id": 1})
        assert r.status_code == 400

    def test_extract_url_nonexistent_entity(self, extraction_project):
        c = extraction_project["client"]
        r = c.post("/api/extract/from-url", json={
            "url": "https://example.com",
            "entity_id": 99999,
            "project_id": extraction_project["project_id"],
        })
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Job Endpoints
# ═══════════════════════════════════════════════════════════════

class TestJobEndpoints:
    """EXT-API-JOBS: Extraction job listing and detail endpoints."""

    def test_list_jobs(self, extraction_with_results):
        c = extraction_with_results["client"]
        pid = extraction_with_results["project_id"]
        r = c.get(f"/api/extract/jobs?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["status"] == "completed"

    def test_list_jobs_missing_project(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.get("/api/extract/jobs")
        assert r.status_code == 400

    def test_get_job_detail(self, extraction_with_results):
        c = extraction_with_results["client"]
        job_id = extraction_with_results["job_id"]
        r = c.get(f"/api/extract/jobs/{job_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] == job_id
        assert len(data["results"]) == 3

    def test_get_nonexistent_job(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.get("/api/extract/jobs/99999")
        assert r.status_code == 404

    def test_delete_job(self, extraction_with_results):
        c = extraction_with_results["client"]
        job_id = extraction_with_results["job_id"]
        r = c.delete(f"/api/extract/jobs/{job_id}")
        assert r.status_code == 200
        assert r.get_json()["status"] == "deleted"

        # Verify deletion
        r2 = c.get(f"/api/extract/jobs/{job_id}")
        assert r2.status_code == 404

    def test_delete_nonexistent_job(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.delete("/api/extract/jobs/99999")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Result Endpoints
# ═══════════════════════════════════════════════════════════════

class TestResultEndpoints:
    """EXT-API-RES: Extraction result listing endpoints."""

    def test_list_results(self, extraction_with_results):
        c = extraction_with_results["client"]
        eid = extraction_with_results["entity_id"]
        r = c.get(f"/api/extract/results?entity_id={eid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 3

    def test_list_results_filter_status(self, extraction_with_results):
        c = extraction_with_results["client"]
        eid = extraction_with_results["entity_id"]

        # Accept one result
        rid = extraction_with_results["result_ids"][0]
        c.post(f"/api/extract/results/{rid}/review", json={"action": "accept"})

        # Filter pending
        r = c.get(f"/api/extract/results?entity_id={eid}&status=pending")
        assert r.status_code == 200
        assert len(r.get_json()) == 2

    def test_list_results_filter_attr(self, extraction_with_results):
        c = extraction_with_results["client"]
        eid = extraction_with_results["entity_id"]
        r = c.get(f"/api/extract/results?entity_id={eid}&attr_slug=description")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["attr_slug"] == "description"


# ═══════════════════════════════════════════════════════════════
# Review Queue
# ═══════════════════════════════════════════════════════════════

class TestQueueEndpoint:
    """EXT-API-QUEUE: Review queue endpoint tests."""

    def test_get_queue(self, extraction_with_results):
        c = extraction_with_results["client"]
        pid = extraction_with_results["project_id"]
        r = c.get(f"/api/extract/queue?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 3
        assert all(d["status"] == "pending" for d in data)

    def test_queue_missing_project(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.get("/api/extract/queue")
        assert r.status_code == 400

    def test_queue_empty_project(self, extraction_project):
        c = extraction_project["client"]
        pid = extraction_project["project_id"]
        r = c.get(f"/api/extract/queue?project_id={pid}")
        assert r.status_code == 200
        assert r.get_json() == []


# ═══════════════════════════════════════════════════════════════
# Review Endpoints
# ═══════════════════════════════════════════════════════════════

class TestReviewEndpoints:
    """EXT-API-REV: Result review endpoint tests."""

    def test_accept_result(self, extraction_with_results):
        c = extraction_with_results["client"]
        rid = extraction_with_results["result_ids"][0]
        r = c.post(f"/api/extract/results/{rid}/review", json={"action": "accept"})
        assert r.status_code == 200
        assert "accepted" in r.get_json()["status"]

    def test_reject_result(self, extraction_with_results):
        c = extraction_with_results["client"]
        rid = extraction_with_results["result_ids"][1]
        r = c.post(f"/api/extract/results/{rid}/review", json={"action": "reject"})
        assert r.status_code == 200
        assert "rejected" in r.get_json()["status"]

    def test_edit_result(self, extraction_with_results):
        c = extraction_with_results["client"]
        rid = extraction_with_results["result_ids"][2]
        r = c.post(f"/api/extract/results/{rid}/review", json={
            "action": "edit",
            "edited_value": "2021",
        })
        assert r.status_code == 200
        assert "edited" in r.get_json()["status"]

    def test_review_missing_action(self, extraction_with_results):
        c = extraction_with_results["client"]
        rid = extraction_with_results["result_ids"][0]
        r = c.post(f"/api/extract/results/{rid}/review", json={})
        assert r.status_code == 400

    def test_review_invalid_action(self, extraction_with_results):
        c = extraction_with_results["client"]
        rid = extraction_with_results["result_ids"][0]
        r = c.post(f"/api/extract/results/{rid}/review", json={"action": "destroy"})
        assert r.status_code == 400

    def test_review_edit_missing_value(self, extraction_with_results):
        c = extraction_with_results["client"]
        rid = extraction_with_results["result_ids"][0]
        r = c.post(f"/api/extract/results/{rid}/review", json={"action": "edit"})
        assert r.status_code == 400
        assert "edited_value" in r.get_json()["error"]

    def test_review_nonexistent_result(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.post("/api/extract/results/99999/review", json={"action": "accept"})
        assert r.status_code == 404

    def test_review_already_reviewed(self, extraction_with_results):
        c = extraction_with_results["client"]
        rid = extraction_with_results["result_ids"][0]
        # Accept first
        c.post(f"/api/extract/results/{rid}/review", json={"action": "accept"})
        # Try again
        r = c.post(f"/api/extract/results/{rid}/review", json={"action": "reject"})
        assert r.status_code == 400
        assert "already reviewed" in r.get_json()["error"]

    def test_bulk_review(self, extraction_with_results):
        c = extraction_with_results["client"]
        rids = extraction_with_results["result_ids"]
        r = c.post("/api/extract/results/bulk-review", json={
            "result_ids": rids,
            "action": "accept",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["updated_count"] == 3
        assert data["requested_count"] == 3

    def test_bulk_review_missing_ids(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.post("/api/extract/results/bulk-review", json={"action": "accept"})
        assert r.status_code == 400

    def test_bulk_review_invalid_action(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.post("/api/extract/results/bulk-review", json={
            "result_ids": [1],
            "action": "edit",
        })
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# Contradiction & Stats Endpoints
# ═══════════════════════════════════════════════════════════════

class TestContradictionEndpoint:
    """EXT-API-CONTRA: Contradiction detection endpoint tests."""

    def test_no_contradictions(self, extraction_with_results):
        c = extraction_with_results["client"]
        eid = extraction_with_results["entity_id"]
        r = c.get(f"/api/extract/contradictions?entity_id={eid}")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_with_contradictions(self, extraction_with_results):
        c = extraction_with_results["client"]
        eid = extraction_with_results["entity_id"]
        pid = extraction_with_results["project_id"]

        # Add conflicting result from another job
        j2 = c.db.create_extraction_job(pid, eid, source_type="url")
        c.db.create_extraction_result(j2, eid, "headquarters", "Paris", confidence=0.7)

        r = c.get(f"/api/extract/contradictions?entity_id={eid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["attr_slug"] == "headquarters"

    def test_contradictions_missing_entity(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.get("/api/extract/contradictions")
        assert r.status_code == 400


class TestStatsEndpoint:
    """EXT-API-STATS: Extraction statistics endpoint tests."""

    def test_stats(self, extraction_with_results):
        c = extraction_with_results["client"]
        pid = extraction_with_results["project_id"]
        r = c.get(f"/api/extract/stats?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_jobs"] == 1
        assert data["total_results"] == 3
        assert data["pending_review"] == 3

    def test_stats_missing_project(self, extraction_with_results):
        c = extraction_with_results["client"]
        r = c.get("/api/extract/stats")
        assert r.status_code == 400

    def test_stats_empty_project(self, extraction_project):
        c = extraction_project["client"]
        pid = extraction_project["project_id"]
        r = c.get(f"/api/extract/stats?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_jobs"] == 0
