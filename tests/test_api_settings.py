"""Tests for Settings API — share tokens, backups, logs, notifications, activity.

Run: pytest tests/test_api_settings.py -v
Markers: api, settings
"""
import pytest

pytestmark = [pytest.mark.api, pytest.mark.settings]


# ---------------------------------------------------------------------------
# Share Tokens
# ---------------------------------------------------------------------------

class TestShareTokensList:
    """SET-SHARE-LIST: Share token listing via GET /api/share-tokens."""

    def test_list_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/share-tokens?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)


class TestShareTokenCreate:
    """SET-SHARE-CREATE: Share token creation via POST /api/share-tokens."""

    def test_create_share_token(self, api_project):
        c = api_project["client"]
        r = c.post("/api/share-tokens", json={
            "project_id": api_project["id"],
            "label": "Test Share",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert "token" in data
        assert "url" in data

    def test_create_share_token_without_label(self, api_project):
        c = api_project["client"]
        r = c.post("/api/share-tokens", json={
            "project_id": api_project["id"],
        })
        assert r.status_code == 200


class TestShareTokenDelete:
    """SET-SHARE-DEL: Share token deletion via DELETE /api/share-tokens/<id>."""

    def test_delete_share_token(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/share-tokens", json={"project_id": pid, "label": "Del"})
        # Get token ID from list
        r = c.get(f"/api/share-tokens?project_id={pid}")
        tokens = r.get_json()
        assert len(tokens) >= 1
        token_id = tokens[0]["id"]

        r = c.delete(f"/api/share-tokens/{token_id}")
        assert r.status_code == 200


class TestSharedView:
    """SET-SHARED-VIEW: Public shared view via GET /shared/<token>."""

    def test_shared_view(self, api_project):
        c = api_project["client"]
        r = c.post("/api/share-tokens", json={
            "project_id": api_project["id"],
        })
        token = r.get_json()["token"]

        r = c.get(f"/shared/{token}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["read_only"] is True

    def test_shared_view_invalid_token(self, client):
        r = client.get("/shared/invalid-token-12345")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Activity Log
# ---------------------------------------------------------------------------

class TestActivityLog:
    """SET-ACTIVITY: Activity log via GET /api/activity."""

    def test_activity_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/activity?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_activity_with_limit(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/activity?project_id={api_project['id']}&limit=5")
        assert r.status_code == 200

    def test_activity_with_offset(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/activity?project_id={api_project['id']}&offset=10")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class TestNotificationPrefs:
    """SET-NOTIF: Notification preferences."""

    def test_get_prefs(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/notification-prefs?project_id={api_project['id']}")
        assert r.status_code == 200

    def test_save_prefs(self, api_project):
        c = api_project["client"]
        r = c.post("/api/notification-prefs", json={
            "project_id": api_project["id"],
            "notify_batch_complete": True,
            "notify_taxonomy_change": False,
            "notify_new_company": True,
        })
        assert r.status_code == 200

    def test_test_slack_missing_url_rejected(self, client):
        r = client.post("/api/notification-prefs/test-slack", json={})
        assert r.status_code == 400

    def test_test_slack_invalid_url_rejected(self, client):
        r = client.post("/api/notification-prefs/test-slack", json={
            "slack_webhook_url": "not-a-url",
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# App Settings
# ---------------------------------------------------------------------------

class TestAppSettings:
    """SET-APP: App settings get/save."""

    def test_get_settings(self, client):
        r = client.get("/api/app-settings")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)

    def test_save_settings(self, client):
        r = client.post("/api/app-settings", json={
            "default_model": "claude-haiku-4-5-20251001",
        })
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

class TestPrerequisites:
    """SET-PREREQ: Prerequisites check via GET /api/prerequisites."""

    def test_check_prerequisites(self, client):
        r = client.get("/api/prerequisites")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Backups
# ---------------------------------------------------------------------------

class TestBackups:
    """SET-BACKUP: Backup management."""

    def test_list_backups(self, client):
        r = client.get("/api/backups")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_create_backup(self, client):
        r = client.post("/api/backups")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert "filename" in data

    def test_restore_nonexistent_rejected(self, client):
        r = client.post("/api/backups/nonexistent.db/restore")
        assert r.status_code == 404

    def test_delete_nonexistent_rejected(self, client):
        r = client.delete("/api/backups/nonexistent.db")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

class TestLogs:
    """SET-LOGS: Log management."""

    def test_list_logs(self, client):
        r = client.get("/api/logs")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_get_nonexistent_log(self, client):
        r = client.get("/api/logs/nonexistent.log")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Update Check
# ---------------------------------------------------------------------------

class TestUpdateCheck:
    """SET-UPDATE: Update check via GET /api/update-check."""

    def test_update_check(self, client):
        r = client.get("/api/update-check")
        assert r.status_code == 200
        data = r.get_json()
        assert "current_version" in data
