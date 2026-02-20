"""Tests for Scraper API endpoints (App Store + Play Store).

All external HTTP calls are mocked.

Run: pytest tests/test_api_scrapers.py -v
Markers: api, capture
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from core.scrapers.appstore import AppStoreApp
from core.scrapers.playstore import PlayStoreApp
from core.capture import CaptureResult

pytestmark = [pytest.mark.api, pytest.mark.capture]

TEST_SCHEMA = {
    "version": 1,
    "entity_types": [
        {"name": "Company", "slug": "company", "attributes": []},
    ],
    "relationships": [],
}


@pytest.fixture
def scraper_project(client, tmp_path, monkeypatch):
    """Create project + entity with redirected evidence dir."""
    import core.capture as capture_mod
    test_evidence_dir = tmp_path / "evidence"
    test_evidence_dir.mkdir()
    monkeypatch.setattr(capture_mod, "EVIDENCE_DIR", test_evidence_dir)

    pid = client.db.create_project(
        name="Scraper API Test",
        purpose="Testing scraper API endpoints",
        entity_schema=TEST_SCHEMA,
    )
    eid = client.db.create_entity(pid, "company", "Vitality")
    return {
        "client": client,
        "project_id": pid,
        "entity_id": eid,
    }


# ═══════════════════════════════════════════════════════════════
# App Store API
# ═══════════════════════════════════════════════════════════════

class TestAppStoreSearchAPI:
    """API tests for /api/scrape/appstore/search."""

    def test_search(self, scraper_project):
        c = scraper_project["client"]
        mock_apps = [
            AppStoreApp(app_id=1, name="App One", rating=4.5),
            AppStoreApp(app_id=2, name="App Two", rating=3.8),
        ]
        with patch("core.scrapers.appstore.search_apps", return_value=mock_apps):
            r = c.get("/api/scrape/appstore/search?term=health")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 2
        assert data[0]["name"] == "App One"

    def test_search_missing_term(self, scraper_project):
        c = scraper_project["client"]
        r = c.get("/api/scrape/appstore/search")
        assert r.status_code == 400
        assert "term" in r.get_json()["error"]

    def test_search_empty_results(self, scraper_project):
        c = scraper_project["client"]
        with patch("core.scrapers.appstore.search_apps", return_value=[]):
            r = c.get("/api/scrape/appstore/search?term=zzz")
        assert r.status_code == 200
        assert r.get_json() == []


class TestAppStoreDetailsAPI:
    """API tests for /api/scrape/appstore/details/<id>."""

    def test_get_details(self, scraper_project):
        c = scraper_project["client"]
        mock_app = AppStoreApp(app_id=123, name="Vitality", rating=4.7)
        with patch("core.scrapers.appstore.get_app_details", return_value=mock_app):
            r = c.get("/api/scrape/appstore/details/123")
        assert r.status_code == 200
        assert r.get_json()["name"] == "Vitality"

    def test_details_not_found(self, scraper_project):
        c = scraper_project["client"]
        with patch("core.scrapers.appstore.get_app_details", return_value=None):
            r = c.get("/api/scrape/appstore/details/999")
        assert r.status_code == 404


class TestAppStoreScreenshotsAPI:
    """API tests for /api/scrape/appstore/screenshots."""

    def test_download_success(self, scraper_project):
        c = scraper_project["client"]
        pid = scraper_project["project_id"]
        eid = scraper_project["entity_id"]

        mock_result = CaptureResult(
            success=True,
            url="https://apps.apple.com/app/123",
            evidence_paths=["1/2/screenshot/img.png"],
            evidence_ids=[42],
            metadata={"app_name": "Vitality"},
            duration_ms=500,
        )

        with patch("core.scrapers.appstore.download_screenshots", return_value=mock_result):
            r = c.post("/api/scrape/appstore/screenshots", json={
                "app_id": 123,
                "entity_id": eid,
                "project_id": pid,
            })
        assert r.status_code == 201
        assert r.get_json()["success"] is True

    def test_download_missing_fields(self, scraper_project):
        c = scraper_project["client"]
        r = c.post("/api/scrape/appstore/screenshots", json={
            "app_id": 123,
        })
        assert r.status_code == 400

    def test_download_invalid_entity(self, scraper_project):
        c = scraper_project["client"]
        r = c.post("/api/scrape/appstore/screenshots", json={
            "app_id": 123,
            "entity_id": 99999,
            "project_id": scraper_project["project_id"],
        })
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Play Store API
# ═══════════════════════════════════════════════════════════════

class TestPlayStoreSearchAPI:
    """API tests for /api/scrape/playstore/search."""

    def test_search(self, scraper_project):
        c = scraper_project["client"]
        mock_apps = [
            PlayStoreApp(package_id="com.app.one", name="App One"),
            PlayStoreApp(package_id="com.app.two", name="App Two"),
        ]
        with patch("core.scrapers.playstore.search_apps", return_value=mock_apps):
            r = c.get("/api/scrape/playstore/search?term=health")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 2

    def test_search_missing_term(self, scraper_project):
        c = scraper_project["client"]
        r = c.get("/api/scrape/playstore/search")
        assert r.status_code == 400


class TestPlayStoreDetailsAPI:
    """API tests for /api/scrape/playstore/details/<id>."""

    def test_get_details(self, scraper_project):
        c = scraper_project["client"]
        mock_app = PlayStoreApp(package_id="com.vitality", name="Vitality")
        with patch("core.scrapers.playstore.get_app_details", return_value=mock_app):
            r = c.get("/api/scrape/playstore/details/com.vitality")
        assert r.status_code == 200
        assert r.get_json()["name"] == "Vitality"

    def test_details_not_found(self, scraper_project):
        c = scraper_project["client"]
        with patch("core.scrapers.playstore.get_app_details", return_value=None):
            r = c.get("/api/scrape/playstore/details/com.nonexistent")
        assert r.status_code == 404


class TestPlayStoreScreenshotsAPI:
    """API tests for /api/scrape/playstore/screenshots."""

    def test_download_success(self, scraper_project):
        c = scraper_project["client"]
        pid = scraper_project["project_id"]
        eid = scraper_project["entity_id"]

        mock_result = CaptureResult(
            success=True,
            url="https://play.google.com/store/apps/details?id=com.vitality",
            evidence_paths=["1/2/screenshot/img.webp"],
            evidence_ids=[43],
            metadata={"app_name": "Vitality"},
            duration_ms=300,
        )

        with patch("core.scrapers.playstore.download_screenshots", return_value=mock_result):
            r = c.post("/api/scrape/playstore/screenshots", json={
                "package_id": "com.vitality",
                "entity_id": eid,
                "project_id": pid,
            })
        assert r.status_code == 201
        assert r.get_json()["success"] is True

    def test_download_missing_fields(self, scraper_project):
        c = scraper_project["client"]
        r = c.post("/api/scrape/playstore/screenshots", json={
            "package_id": "com.test",
        })
        assert r.status_code == 400

    def test_download_invalid_entity(self, scraper_project):
        c = scraper_project["client"]
        r = c.post("/api/scrape/playstore/screenshots", json={
            "package_id": "com.test",
            "entity_id": 99999,
            "project_id": scraper_project["project_id"],
        })
        assert r.status_code == 404
