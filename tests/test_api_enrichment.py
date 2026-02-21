"""Tests for the Enrichment API endpoints.

Covers:
- Server listing: available MCP data sources
- Recommendations: source relevance for entities
- Single-entity enrichment: sync and async modes
- Batch enrichment: multiple entities asynchronously
- Job polling: async status checking
- CSRF protection on POST endpoints
- Error handling: missing entities, invalid params

Run: pytest tests/test_api_enrichment.py -v
Markers: enrichment, db, api
"""
import json
import pytest
from unittest.mock import patch, MagicMock


pytestmark = [pytest.mark.enrichment, pytest.mark.db, pytest.mark.api]


# ═══════════════════════════════════════════════════════════════
# Test Schema + Fixtures
# ═══════════════════════════════════════════════════════════════

ENRICH_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company entity",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "Website", "slug": "website", "data_type": "url"},
                {"name": "HQ Country", "slug": "hq_country", "data_type": "text"},
                {"name": "Description", "slug": "description", "data_type": "text"},
            ],
        },
    ],
    "relationships": [],
}

# Sample data returned by list_available_sources
MOCK_SOURCES = [
    {"name": "wikipedia", "description": "Wikipedia article lookup", "available": True, "needs_key": False},
    {"name": "hackernews", "description": "Hacker News search", "available": True, "needs_key": False},
    {"name": "duckduckgo", "description": "DuckDuckGo search", "available": True, "needs_key": False},
    {"name": "companies_house", "description": "UK Companies House", "available": False, "needs_key": True},
    {"name": "sec_edgar", "description": "SEC EDGAR filings", "available": True, "needs_key": False},
    {"name": "cloudflare_radar", "description": "Cloudflare Radar domain data", "available": True, "needs_key": False},
    {"name": "patents", "description": "USPTO patent search", "available": True, "needs_key": False},
]

# Sample adapters returned by select_adapters
MOCK_ADAPTERS = [
    {
        "name": "wikipedia",
        "description": "Wikipedia article lookup",
        "priority": 1,
        "produces": ["description", "founded_year"],
    },
    {
        "name": "hackernews",
        "description": "Hacker News search",
        "priority": 2,
        "produces": ["news_mentions"],
    },
]

# Sample enrichment result
MOCK_ENRICH_RESULT = {
    "entity_id": 1,
    "enriched_count": 5,
    "skipped_count": 2,
    "servers_used": [{"name": "wikipedia", "attr_count": 2}],
    "errors": [],
    "attributes": [
        {"slug": "description", "value": "A test company", "source": "wikipedia"},
    ],
}


@pytest.fixture
def enrich_project(client):
    """Create a project with an entity suitable for enrichment tests."""
    db = client.db
    pid = db.create_project(
        name="Enrichment Test",
        purpose="Testing enrichment endpoints",
        entity_schema=ENRICH_SCHEMA,
    )
    eid = db.create_entity(pid, "company", "Acme Corp")
    db.set_entity_attribute(eid, "website", "https://acme.com")
    db.set_entity_attribute(eid, "hq_country", "UK")

    return {
        "project_id": pid,
        "entity_id": eid,
        "client": client,
    }


@pytest.fixture
def enrich_project_multi(client):
    """Create a project with multiple entities for batch tests."""
    db = client.db
    pid = db.create_project(
        name="Batch Enrichment Test",
        purpose="Testing batch enrichment",
        entity_schema=ENRICH_SCHEMA,
    )
    eid1 = db.create_entity(pid, "company", "Alpha Corp")
    eid2 = db.create_entity(pid, "company", "Beta Inc")
    eid3 = db.create_entity(pid, "company", "Gamma LLC")

    return {
        "project_id": pid,
        "entity_ids": [eid1, eid2, eid3],
        "client": client,
    }


# ═══════════════════════════════════════════════════════════════
# Server Listing Tests
# ═══════════════════════════════════════════════════════════════

class TestListServers:
    """Tests for GET /api/enrichment/servers."""

    @patch("core.mcp_client.list_available_sources", return_value=MOCK_SOURCES)
    def test_list_servers(self, mock_sources, client):
        """Returns list of available MCP data sources."""
        r = client.get("/api/enrichment/servers")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) == 7

    @patch("core.mcp_client.list_available_sources", return_value=MOCK_SOURCES)
    def test_list_servers_has_expected_fields(self, mock_sources, client):
        """Each source has name, description, available, needs_key fields."""
        r = client.get("/api/enrichment/servers")
        data = r.get_json()
        for source in data:
            assert "name" in source
            assert "description" in source
            assert "available" in source
            assert "needs_key" in source

    @patch("core.mcp_client.list_available_sources", return_value=MOCK_SOURCES)
    def test_list_servers_has_expected_sources(self, mock_sources, client):
        """All 7 expected sources are present."""
        r = client.get("/api/enrichment/servers")
        data = r.get_json()
        names = {s["name"] for s in data}
        assert "wikipedia" in names
        assert "hackernews" in names
        assert "duckduckgo" in names
        assert "companies_house" in names
        assert "sec_edgar" in names
        assert "cloudflare_radar" in names
        assert "patents" in names


# ═══════════════════════════════════════════════════════════════
# Recommendation Tests
# ═══════════════════════════════════════════════════════════════

class TestRecommendEnrichment:
    """Tests for GET /api/entities/<id>/enrichment/recommend."""

    @patch("core.mcp_enrichment.check_staleness", return_value=True)
    @patch("core.mcp_enrichment.select_adapters", return_value=MOCK_ADAPTERS)
    @patch("core.mcp_enrichment.build_entity_context", return_value={"type_slug": "company", "url": "https://acme.com", "country": "UK"})
    def test_recommend_for_entity(self, mock_context, mock_adapters, mock_stale, enrich_project):
        """Returns recommendations for a valid entity."""
        c = enrich_project["client"]
        eid = enrich_project["entity_id"]

        r = c.get(f"/api/entities/{eid}/enrichment/recommend")
        assert r.status_code == 200
        data = r.get_json()
        assert data["entity_id"] == eid
        assert "recommended_servers" in data
        assert "stale_attributes" in data
        assert len(data["recommended_servers"]) == 2
        assert data["recommended_servers"][0]["name"] == "wikipedia"

    @patch("core.mcp_enrichment.check_staleness", return_value=False)
    @patch("core.mcp_enrichment.select_adapters", return_value=MOCK_ADAPTERS)
    @patch("core.mcp_enrichment.build_entity_context", return_value={"type_slug": "company", "url": "", "country": ""})
    def test_recommend_no_stale_attributes(self, mock_context, mock_adapters, mock_stale, enrich_project):
        """When nothing is stale, stale_attributes is empty."""
        c = enrich_project["client"]
        eid = enrich_project["entity_id"]

        r = c.get(f"/api/entities/{eid}/enrichment/recommend")
        assert r.status_code == 200
        data = r.get_json()
        assert data["stale_attributes"] == []

    def test_recommend_entity_not_found(self, client):
        """Returns 404 for non-existent entity."""
        r = client.get("/api/entities/99999/enrichment/recommend")
        assert r.status_code == 404
        data = r.get_json()
        assert "error" in data

    @patch("core.mcp_enrichment.check_staleness", return_value=True)
    @patch("core.mcp_enrichment.select_adapters", return_value=MOCK_ADAPTERS)
    @patch("core.mcp_enrichment.build_entity_context", return_value={"type_slug": "company", "url": "https://acme.com", "country": "UK"})
    def test_recommend_includes_reason(self, mock_context, mock_adapters, mock_stale, enrich_project):
        """Each recommendation includes a human-readable reason."""
        c = enrich_project["client"]
        eid = enrich_project["entity_id"]

        r = c.get(f"/api/entities/{eid}/enrichment/recommend")
        data = r.get_json()
        for rec in data["recommended_servers"]:
            assert "reason" in rec
            assert isinstance(rec["reason"], str)
            assert len(rec["reason"]) > 0


# ═══════════════════════════════════════════════════════════════
# Sync Enrichment Tests
# ═══════════════════════════════════════════════════════════════

class TestEnrichEntitySync:
    """Tests for POST /api/entities/<id>/enrich (sync mode)."""

    @patch("core.mcp_enrichment.enrich_entity", return_value=MOCK_ENRICH_RESULT)
    def test_enrich_entity_sync(self, mock_enrich, enrich_project):
        """Sync enrichment returns completed result."""
        c = enrich_project["client"]
        eid = enrich_project["entity_id"]

        r = c.post(f"/api/entities/{eid}/enrich", json={})
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "completed"
        assert data["enriched_count"] == 5
        assert data["skipped_count"] == 2
        assert len(data["servers_used"]) == 1
        mock_enrich.assert_called_once()

    def test_enrich_entity_not_found(self, client):
        """Returns 404 for non-existent entity."""
        r = client.post("/api/entities/99999/enrich", json={})
        assert r.status_code == 404
        data = r.get_json()
        assert "error" in data

    @patch("core.mcp_enrichment.enrich_entity", return_value=MOCK_ENRICH_RESULT)
    def test_enrich_with_servers_filter(self, mock_enrich, enrich_project):
        """Passes servers filter through to enrich_entity."""
        c = enrich_project["client"]
        eid = enrich_project["entity_id"]

        r = c.post(f"/api/entities/{eid}/enrich", json={
            "servers": ["wikipedia", "hackernews"],
        })
        assert r.status_code == 200
        # Verify the servers filter was passed to the function
        call_kwargs = mock_enrich.call_args
        assert call_kwargs[1]["servers"] == ["wikipedia", "hackernews"]

    @patch("core.mcp_enrichment.enrich_entity", return_value=MOCK_ENRICH_RESULT)
    def test_enrich_with_max_age(self, mock_enrich, enrich_project):
        """Custom max_age_hours is passed through."""
        c = enrich_project["client"]
        eid = enrich_project["entity_id"]

        r = c.post(f"/api/entities/{eid}/enrich", json={
            "max_age_hours": 24,
        })
        assert r.status_code == 200
        call_kwargs = mock_enrich.call_args
        assert call_kwargs[1]["max_age_hours"] == 24

    @patch("core.mcp_enrichment.enrich_entity", return_value=MOCK_ENRICH_RESULT)
    def test_enrich_default_max_age(self, mock_enrich, enrich_project):
        """Default max_age_hours is 168 (1 week)."""
        c = enrich_project["client"]
        eid = enrich_project["entity_id"]

        r = c.post(f"/api/entities/{eid}/enrich", json={})
        assert r.status_code == 200
        call_kwargs = mock_enrich.call_args
        assert call_kwargs[1]["max_age_hours"] == 168


# ═══════════════════════════════════════════════════════════════
# Async Enrichment Tests
# ═══════════════════════════════════════════════════════════════

class TestEnrichEntityAsync:
    """Tests for POST /api/entities/<id>/enrich (async mode)."""

    def test_enrich_entity_async(self, enrich_project):
        """Async enrichment returns 202 with job_id."""
        c = enrich_project["client"]
        eid = enrich_project["entity_id"]

        with patch("web.async_jobs.start_async_job", return_value="abc123def456") as mock_start:
            r = c.post(f"/api/entities/{eid}/enrich", json={
                "async": True,
            })
            mock_start.assert_called_once()
            call_args = mock_start.call_args
            assert call_args[0][0] == "enrichment"  # prefix

        assert r.status_code == 202
        data = r.get_json()
        assert data["status"] == "pending"
        assert data["job_id"] == "abc123def456"

    def test_enrich_entity_async_not_found(self, client):
        """Async enrichment also returns 404 for missing entity."""
        r = client.post("/api/entities/99999/enrich", json={"async": True})
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Poll Tests
# ═══════════════════════════════════════════════════════════════

class TestPollEnrichment:
    """Tests for GET /api/enrichment/poll/<job_id>."""

    def test_poll_enrichment_pending(self, client):
        """Polling a non-existent job returns pending status."""
        with patch("web.async_jobs.poll_result", return_value={"status": "pending"}):
            r = client.get("/api/enrichment/poll/abcdef0123456789")
        assert r.status_code == 200
        assert r.get_json()["status"] == "pending"

    def test_poll_enrichment_complete(self, client):
        """Polling a completed job returns full result data."""
        completed = {
            "status": "complete",
            "entity_id": 1,
            "enriched_count": 3,
            "skipped_count": 1,
            "servers_used": [{"name": "wikipedia", "attr_count": 2}],
            "errors": [],
        }
        with patch("web.async_jobs.poll_result", return_value=completed):
            r = client.get("/api/enrichment/poll/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "complete"
        assert data["enriched_count"] == 3

    def test_poll_enrichment_error(self, client):
        """Polling a failed job returns error details."""
        error_result = {
            "status": "error",
            "error": "Connection timeout",
        }
        with patch("web.async_jobs.poll_result", return_value=error_result):
            r = client.get("/api/enrichment/poll/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "error"
        assert "Connection timeout" in data["error"]

    def test_poll_enrichment_invalid_job_id(self, client):
        """Invalid job_id format returns error from poll_result."""
        with patch("web.async_jobs.poll_result", return_value={"status": "error", "error": "Invalid job ID"}):
            r = client.get("/api/enrichment/poll/INVALID")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "error"


# ═══════════════════════════════════════════════════════════════
# Batch Enrichment Tests
# ═══════════════════════════════════════════════════════════════

class TestBatchEnrich:
    """Tests for POST /api/enrichment/batch."""

    def test_batch_enrich(self, enrich_project_multi):
        """Batch enrichment starts job and returns 202."""
        c = enrich_project_multi["client"]
        pid = enrich_project_multi["project_id"]
        eids = enrich_project_multi["entity_ids"]

        with patch("web.async_jobs.start_async_job", return_value="batch123456ab") as mock_start:
            r = c.post("/api/enrichment/batch", json={
                "project_id": pid,
                "entity_ids": eids,
            })
            mock_start.assert_called_once()
            call_args = mock_start.call_args
            assert call_args[0][0] == "enrichment_batch"

        assert r.status_code == 202
        data = r.get_json()
        assert data["status"] == "pending"
        assert data["job_id"] == "batch123456ab"
        assert data["total"] == 3

    def test_batch_enrich_no_ids(self, client):
        """Returns 400 when entity_ids is empty."""
        r = client.post("/api/enrichment/batch", json={
            "project_id": 1,
            "entity_ids": [],
        })
        assert r.status_code == 400
        data = r.get_json()
        assert "entity_ids" in data["error"]

    def test_batch_enrich_no_project(self, client):
        """Returns 400 when project_id is missing."""
        r = client.post("/api/enrichment/batch", json={
            "entity_ids": [1, 2, 3],
        })
        assert r.status_code == 400
        data = r.get_json()
        assert "project_id" in data["error"]

    def test_batch_enrich_with_servers_filter(self, enrich_project_multi):
        """Servers filter is passed to the batch worker."""
        c = enrich_project_multi["client"]
        pid = enrich_project_multi["project_id"]
        eids = enrich_project_multi["entity_ids"]

        with patch("web.async_jobs.start_async_job", return_value="filtertest123") as mock_start:
            r = c.post("/api/enrichment/batch", json={
                "project_id": pid,
                "entity_ids": eids,
                "servers": ["wikipedia"],
            })
            # Verify servers filter is in args passed to worker
            call_args = mock_start.call_args[0]
            # Args: prefix, work_fn, entity_ids, servers, max_age
            assert call_args[3] == ["wikipedia"]

        assert r.status_code == 202

    def test_batch_enrich_with_custom_max_age(self, enrich_project_multi):
        """Custom max_age_hours is passed through in batch mode."""
        c = enrich_project_multi["client"]
        pid = enrich_project_multi["project_id"]
        eids = enrich_project_multi["entity_ids"]

        with patch("web.async_jobs.start_async_job", return_value="agetest12345a") as mock_start:
            r = c.post("/api/enrichment/batch", json={
                "project_id": pid,
                "entity_ids": eids,
                "max_age_hours": 48,
            })
            call_args = mock_start.call_args[0]
            # Args: prefix, work_fn, entity_ids, servers, max_age
            assert call_args[4] == 48

        assert r.status_code == 202


# ═══════════════════════════════════════════════════════════════
# CSRF Protection Tests
# ═══════════════════════════════════════════════════════════════

class TestCSRFProtection:
    """Tests that POST endpoints require CSRF tokens."""

    def test_enrich_requires_csrf(self, app, enrich_project):
        """POST /api/entities/<id>/enrich rejects requests without CSRF."""
        raw = app.test_client()
        eid = enrich_project["entity_id"]

        r = raw.post(
            f"/api/entities/{eid}/enrich",
            json={},
            content_type="application/json",
        )
        assert r.status_code == 403

    def test_batch_enrich_requires_csrf(self, app):
        """POST /api/enrichment/batch rejects requests without CSRF."""
        raw = app.test_client()
        r = raw.post(
            "/api/enrichment/batch",
            json={"entity_ids": [1], "project_id": 1},
            content_type="application/json",
        )
        assert r.status_code == 403
