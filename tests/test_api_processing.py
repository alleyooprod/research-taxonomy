"""Tests for Processing API — jobs, batches, triage.

Run: pytest tests/test_api_processing.py -v
Markers: api, processing
"""
import pytest

pytestmark = [pytest.mark.api, pytest.mark.processing]


class TestListJobs:
    """PROC-JOBS-LIST: Job listing via GET /api/jobs."""

    def test_list_jobs_empty(self, client):
        r = client.get("/api/jobs")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_list_jobs_with_project_filter(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/jobs?project_id={api_project['id']}")
        assert r.status_code == 200


class TestGetBatch:
    """PROC-BATCH-GET: Batch summary via GET /api/jobs/<batch_id>."""

    def test_get_nonexistent_batch(self, client):
        r = client.get("/api/jobs/nonexistent-batch")
        assert r.status_code == 200  # Returns empty summary


class TestProcessValidation:
    """PROC-START: Process batch validation via POST /api/process."""

    def test_process_no_urls_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/process", json={
            "text": "no urls here",
            "project_id": api_project["id"],
        })
        assert r.status_code == 400

    def test_process_empty_text_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/process", json={
            "text": "",
            "project_id": api_project["id"],
        })
        assert r.status_code == 400


class TestTriageValidation:
    """PROC-TRIAGE: Triage validation via POST /api/triage."""

    def test_triage_no_urls_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/triage", json={
            "text": "no urls at all",
            "project_id": api_project["id"],
        })
        assert r.status_code == 400

    def test_triage_empty_rejected(self, api_project):
        c = api_project["client"]
        r = c.post("/api/triage", json={
            "text": "",
        })
        assert r.status_code == 400

    def test_poll_triage_nonexistent(self, client):
        r = client.get("/api/triage/nonexistent-batch")
        assert r.status_code == 200  # Returns empty or pending


class TestRetryValidation:
    """PROC-RETRY: Retry validation."""

    def test_retry_timeouts_nonexistent_batch(self, client):
        r = client.post("/api/jobs/nonexistent/retry-timeouts", json={})
        assert r.status_code == 400

    def test_retry_errors_nonexistent_batch(self, client):
        r = client.post("/api/jobs/nonexistent/retry-errors", json={})
        assert r.status_code == 400
