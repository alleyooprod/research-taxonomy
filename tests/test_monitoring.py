"""Tests for Monitoring & Intelligence API endpoints.

Covers:
- Monitor CRUD (create, list, update, delete)
- Check execution (single + batch)
- Change feed (list, mark read, dismiss, mark all read)
- Dashboard stats
- Auto-setup monitors from entity URLs
- Edge cases: missing params, nonexistent entities, duplicate monitors

Run: pytest tests/test_monitoring.py -v
Markers: db, api, monitoring
"""
import json
import pytest
from unittest.mock import patch, MagicMock

import web.blueprints.monitoring._shared as monitoring_mod

pytestmark = [pytest.mark.db, pytest.mark.api]


# ═══════════════════════════════════════════════════════════════
# Schema + Fixtures
# ═══════════════════════════════════════════════════════════════

MONITOR_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "URL", "slug": "url", "data_type": "url"},
                {"name": "Features", "slug": "features", "data_type": "tags"},
                {"name": "Pricing", "slug": "pricing_model", "data_type": "text"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture(autouse=True)
def reset_table_flag():
    """Reset the _TABLE_ENSURED flag between tests."""
    monitoring_mod._TABLE_ENSURED = False
    yield
    monitoring_mod._TABLE_ENSURED = False


@pytest.fixture
def monitor_project(client):
    """Create a project with entities for monitoring tests."""
    db = client.db
    pid = db.create_project(
        name="Monitor Test",
        purpose="Testing monitoring",
        entity_schema=MONITOR_SCHEMA,
    )

    eid1 = db.create_entity(pid, "company", "Alpha Corp")
    eid2 = db.create_entity(pid, "company", "Beta Inc")
    eid3 = db.create_entity(pid, "company", "Gamma LLC")

    # Set URL attributes for auto-setup testing
    db.set_entity_attribute(eid1, "url", "https://alpha.com")
    db.set_entity_attribute(eid2, "url", "https://beta.io")
    db.set_entity_attribute(eid3, "url", "https://gamma.com")

    return {
        "client": client,
        "project_id": pid,
        "entity_ids": [eid1, eid2, eid3],
        "db": db,
    }


def _create_monitor(client, pid, eid, monitor_type="website", url="https://example.com"):
    """Helper to create a monitor."""
    r = client.post("/api/monitoring/monitors", json={
        "project_id": pid,
        "entity_id": eid,
        "monitor_type": monitor_type,
        "target_url": url,
    })
    return r


# ═══════════════════════════════════════════════════════════════
# Monitor CRUD Tests
# ═══════════════════════════════════════════════════════════════

class TestMonitorCRUD:
    """Tests for monitor create, list, update, delete."""

    def test_create_monitor(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        r = _create_monitor(c, pid, eid, url="https://alpha.com")
        assert r.status_code == 201
        data = r.get_json()
        assert data["entity_id"] == eid
        assert data["monitor_type"] == "website"
        assert data["target_url"] == "https://alpha.com"
        assert data["is_active"] in (True, 1)

    def test_create_monitor_missing_fields(self, monitor_project):
        c = monitor_project["client"]
        r = c.post("/api/monitoring/monitors", json={})
        assert r.status_code == 400

    def test_create_monitor_invalid_type(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        r = c.post("/api/monitoring/monitors", json={
            "project_id": pid,
            "entity_id": eid,
            "monitor_type": "invalid_type",
            "target_url": "https://example.com",
        })
        assert r.status_code == 400

    def test_create_monitor_nonexistent_entity(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        r = c.post("/api/monitoring/monitors", json={
            "project_id": pid,
            "entity_id": 99999,
            "monitor_type": "website",
            "target_url": "https://example.com",
        })
        assert r.status_code in (400, 404)

    def test_list_monitors(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid1 = monitor_project["entity_ids"][0]
        eid2 = monitor_project["entity_ids"][1]
        _create_monitor(c, pid, eid1, url="https://alpha.com")
        _create_monitor(c, pid, eid2, url="https://beta.io")
        r = c.get(f"/api/monitoring/monitors?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        monitors = data if isinstance(data, list) else data.get("monitors", [])
        assert len(monitors) >= 2

    def test_list_monitors_missing_project(self, client):
        r = client.get("/api/monitoring/monitors")
        assert r.status_code == 400

    def test_list_monitors_filter_by_type(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        _create_monitor(c, pid, eid, monitor_type="website", url="https://alpha.com")
        _create_monitor(c, pid, eid, monitor_type="rss", url="https://alpha.com/feed.xml")
        r = c.get(f"/api/monitoring/monitors?project_id={pid}&monitor_type=website")
        assert r.status_code == 200
        data = r.get_json()
        monitors = data if isinstance(data, list) else data.get("monitors", [])
        for m in monitors:
            assert m["monitor_type"] == "website"

    def test_delete_monitor(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        created = _create_monitor(c, pid, eid, url="https://alpha.com")
        mid = created.get_json()["id"]
        r = c.delete(f"/api/monitoring/monitors/{mid}")
        assert r.status_code == 200
        # Verify it's gone
        r2 = c.get(f"/api/monitoring/monitors?project_id={pid}")
        monitors = r2.get_json() if isinstance(r2.get_json(), list) else r2.get_json().get("monitors", [])
        ids = [m["id"] for m in monitors]
        assert mid not in ids

    def test_delete_nonexistent_monitor(self, monitor_project):
        c = monitor_project["client"]
        r = c.delete("/api/monitoring/monitors/99999")
        assert r.status_code == 404

    def test_update_monitor_toggle_active(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        created = _create_monitor(c, pid, eid, url="https://alpha.com")
        mid = created.get_json()["id"]
        r = c.put(f"/api/monitoring/monitors/{mid}", json={"is_active": False})
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("is_active") in (False, 0)

    def test_update_monitor_change_interval(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        created = _create_monitor(c, pid, eid, url="https://alpha.com")
        mid = created.get_json()["id"]
        r = c.put(f"/api/monitoring/monitors/{mid}", json={"check_interval_hours": 12})
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("check_interval_hours") == 12


# ═══════════════════════════════════════════════════════════════
# Check Execution Tests
# ═══════════════════════════════════════════════════════════════

class TestMonitorChecks:
    """Tests for triggering monitor checks."""

    @patch("requests.get")
    def test_check_website_monitor(self, mock_get, monitor_project):
        """Check a website monitor — mocked HTTP."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Hello World</body></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        created = _create_monitor(c, pid, eid, url="https://alpha.com")
        mid = created.get_json()["id"]

        r = c.post(f"/api/monitoring/monitors/{mid}/check")
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("status") == "completed"

    @patch("requests.get")
    def test_check_detects_change(self, mock_get, monitor_project):
        """Second check with different content detects a change."""
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        created = _create_monitor(c, pid, eid, url="https://alpha.com")
        mid = created.get_json()["id"]

        # First check
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "<html><body>Version 1</body></html>"
        mock_resp1.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp1
        c.post(f"/api/monitoring/monitors/{mid}/check")

        # Second check with different content
        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = "<html><body>Version 2 - Updated!</body></html>"
        mock_resp2.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp2
        r = c.post(f"/api/monitoring/monitors/{mid}/check")
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("changes_detected") in (True, 1)

    @patch("requests.get")
    def test_check_no_change(self, mock_get, monitor_project):
        """Two checks with same content — no change detected."""
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        created = _create_monitor(c, pid, eid, url="https://alpha.com")
        mid = created.get_json()["id"]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Same Content</body></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        c.post(f"/api/monitoring/monitors/{mid}/check")
        r = c.post(f"/api/monitoring/monitors/{mid}/check")
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("changes_detected") in (False, 0)

    @patch("requests.get")
    def test_check_error_handling(self, mock_get, monitor_project):
        """Check that errors are handled gracefully."""
        mock_get.side_effect = Exception("Connection refused")

        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        created = _create_monitor(c, pid, eid, url="https://alpha.com")
        mid = created.get_json()["id"]

        r = c.post(f"/api/monitoring/monitors/{mid}/check")
        assert r.status_code == 422
        data = r.get_json()
        assert data.get("status") == "error"

    def test_check_nonexistent_monitor(self, monitor_project):
        c = monitor_project["client"]
        r = c.post("/api/monitoring/monitors/99999/check")
        assert r.status_code == 404

    @patch("requests.get")
    def test_check_all_monitors(self, mock_get, monitor_project):
        """Check all due monitors."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>content</html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eids = monitor_project["entity_ids"]

        _create_monitor(c, pid, eids[0], url="https://alpha.com")
        _create_monitor(c, pid, eids[1], url="https://beta.io")

        r = c.post(f"/api/monitoring/check-all?project_id={pid}", json={})
        assert r.status_code == 200
        data = r.get_json()
        assert "checked" in data or "total_checked" in data or "results" in data


# ═══════════════════════════════════════════════════════════════
# Change Feed Tests
# ═══════════════════════════════════════════════════════════════

class TestChangeFeed:
    """Tests for the change feed."""

    @patch("requests.get")
    def _create_change(self, client, pid, eid, mock_get):
        """Helper: create a monitor, check twice to generate a change."""
        created = _create_monitor(client, pid, eid, url="https://example.com/changing")
        mid = created.get_json()["id"]

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "<html>V1</html>"
        mock_resp1.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp1
        client.post(f"/api/monitoring/monitors/{mid}/check")

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = "<html>V2 changed</html>"
        mock_resp2.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp2
        client.post(f"/api/monitoring/monitors/{mid}/check")

        return mid

    def test_feed_empty_project(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        r = c.get(f"/api/monitoring/feed?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        feed = data if isinstance(data, list) else data.get("items", data.get("feed", []))
        assert len(feed) == 0

    def test_feed_missing_project(self, client):
        r = client.get("/api/monitoring/feed")
        assert r.status_code == 400

    @patch("requests.get")
    def test_feed_has_changes(self, mock_get, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]

        # Create initial check
        created = _create_monitor(c, pid, eid, url="https://alpha.com/page")
        mid = created.get_json()["id"]

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "<html>Original</html>"
        mock_resp1.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp1
        c.post(f"/api/monitoring/monitors/{mid}/check")

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = "<html>Updated content here</html>"
        mock_resp2.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp2
        c.post(f"/api/monitoring/monitors/{mid}/check")

        r = c.get(f"/api/monitoring/feed?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        feed = data if isinstance(data, list) else data.get("items", data.get("feed", []))
        assert len(feed) >= 1

    @patch("requests.get")
    def test_mark_feed_read(self, mock_get, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]

        created = _create_monitor(c, pid, eid, url="https://alpha.com/read-test")
        mid = created.get_json()["id"]

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "v1"
        mock_resp1.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp1
        c.post(f"/api/monitoring/monitors/{mid}/check")

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = "v2"
        mock_resp2.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp2
        c.post(f"/api/monitoring/monitors/{mid}/check")

        feed = c.get(f"/api/monitoring/feed?project_id={pid}").get_json()
        items = feed if isinstance(feed, list) else feed.get("items", feed.get("feed", []))
        if items:
            fid = items[0]["id"]
            r = c.put(f"/api/monitoring/feed/{fid}/read")
            assert r.status_code == 200

    @patch("requests.get")
    def test_dismiss_feed_item(self, mock_get, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]

        created = _create_monitor(c, pid, eid, url="https://alpha.com/dismiss-test")
        mid = created.get_json()["id"]

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "a"
        mock_resp1.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp1
        c.post(f"/api/monitoring/monitors/{mid}/check")

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = "b"
        mock_resp2.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp2
        c.post(f"/api/monitoring/monitors/{mid}/check")

        feed = c.get(f"/api/monitoring/feed?project_id={pid}").get_json()
        items = feed if isinstance(feed, list) else feed.get("items", feed.get("feed", []))
        if items:
            fid = items[0]["id"]
            r = c.put(f"/api/monitoring/feed/{fid}/dismiss")
            assert r.status_code == 200

    @patch("requests.get")
    def test_mark_all_read(self, mock_get, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]

        created = _create_monitor(c, pid, eid, url="https://alpha.com/all-read")
        mid = created.get_json()["id"]

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.text = "x"
        mock_resp1.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp1
        c.post(f"/api/monitoring/monitors/{mid}/check")

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.text = "y"
        mock_resp2.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp2
        c.post(f"/api/monitoring/monitors/{mid}/check")

        r = c.post(f"/api/monitoring/feed/mark-all-read?project_id={pid}", json={})
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# Stats Tests
# ═══════════════════════════════════════════════════════════════

class TestMonitoringStats:
    """Tests for the dashboard stats endpoint."""

    def test_stats_empty_project(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        r = c.get(f"/api/monitoring/stats?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "total_monitors" in data or "monitors" in data

    def test_stats_missing_project(self, client):
        r = client.get("/api/monitoring/stats")
        assert r.status_code == 400

    def test_stats_with_monitors(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eids = monitor_project["entity_ids"]
        _create_monitor(c, pid, eids[0], url="https://alpha.com")
        _create_monitor(c, pid, eids[1], url="https://beta.io")

        r = c.get(f"/api/monitoring/stats?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        total = data.get("total_monitors", data.get("monitors", 0))
        assert total >= 2


# ═══════════════════════════════════════════════════════════════
# Auto-Setup Tests
# ═══════════════════════════════════════════════════════════════

class TestAutoSetup:
    """Tests for auto-creating monitors from entity URLs."""

    def test_auto_setup(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        r = c.post(f"/api/monitoring/auto-setup?project_id={pid}", json={})
        assert r.status_code == 200
        data = r.get_json()
        assert "created" in data or "monitors_created" in data or "count" in data

    def test_auto_setup_missing_project(self, client):
        r = client.post("/api/monitoring/auto-setup", json={})
        assert r.status_code == 400

    def test_auto_setup_idempotent(self, monitor_project):
        """Running auto-setup twice shouldn't duplicate monitors."""
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        c.post(f"/api/monitoring/auto-setup?project_id={pid}", json={})
        r2 = c.post(f"/api/monitoring/auto-setup?project_id={pid}", json={})
        assert r2.status_code == 200
        data = r2.get_json()
        count = data.get("created", data.get("monitors_created", data.get("count", 0)))
        assert count == 0  # No new monitors on second run


# ═══════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestMonitoringEdgeCases:
    """Edge case tests."""

    def test_monitor_types_valid(self, monitor_project):
        """All 4 monitor types should be creatable."""
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        for mtype in ["website", "appstore", "playstore", "rss"]:
            r = _create_monitor(c, pid, eid, monitor_type=mtype, url=f"https://example.com/{mtype}")
            assert r.status_code == 201, f"Failed for type {mtype}: {r.get_json()}"

    def test_unread_count(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        r = c.get(f"/api/monitoring/feed/unread-count?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "count" in data or "unread" in data or "unread_count" in data

    def test_check_history(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        created = _create_monitor(c, pid, eid, url="https://alpha.com")
        mid = created.get_json()["id"]
        r = c.get(f"/api/monitoring/monitors/{mid}/checks")
        assert r.status_code == 200

    def test_entity_summary(self, monitor_project):
        c = monitor_project["client"]
        pid = monitor_project["project_id"]
        eid = monitor_project["entity_ids"][0]
        r = c.get(f"/api/monitoring/entity/{eid}/summary?project_id={pid}")
        assert r.status_code == 200
