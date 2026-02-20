"""Tests for App Store and Play Store scrapers.

All external HTTP calls are mocked — no real network requests.

Covers:
- App Store: search, details, parse, download screenshots
- Play Store: details, parse, download screenshots
- Scraper API endpoints
- Evidence record creation from scraper results

Run: pytest tests/test_scrapers.py -v
Markers: db, capture
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from core.scrapers.appstore import (
    search_apps as appstore_search,
    get_app_details as appstore_details,
    download_screenshots as appstore_download,
    _parse_app_result,
    AppStoreApp,
    get_app_metadata_for_entity as appstore_metadata,
)
from core.scrapers.playstore import (
    get_app_details as playstore_details,
    download_screenshots as playstore_download,
    PlayStoreApp,
    get_app_metadata_for_entity as playstore_metadata,
)

pytestmark = [pytest.mark.db, pytest.mark.capture]


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def evidence_tmpdir(tmp_path, monkeypatch):
    """Redirect evidence storage to temp directory."""
    import core.capture as capture_mod
    test_evidence_dir = tmp_path / "evidence"
    test_evidence_dir.mkdir()
    monkeypatch.setattr(capture_mod, "EVIDENCE_DIR", test_evidence_dir)
    return test_evidence_dir


@pytest.fixture
def entity_project(tmp_path):
    """Create a DB with project + entity for scraper tests."""
    from storage.db import Database
    db = Database(db_path=tmp_path / "test.db")
    pid = db.create_project(
        name="Scraper Test",
        purpose="Testing scrapers",
        entity_schema={
            "version": 1,
            "entity_types": [{"name": "Company", "slug": "company", "attributes": []}],
            "relationships": [],
        },
    )
    eid = db.create_entity(pid, "company", "Vitality")
    return {"db": db, "project_id": pid, "entity_id": eid}


# ═══════════════════════════════════════════════════════════════
# Sample API Response Data
# ═══════════════════════════════════════════════════════════════

SAMPLE_ITUNES_RESULT = {
    "trackId": 123456,
    "trackName": "Vitality Health",
    "bundleId": "com.vitality.member",
    "artistName": "Vitality Health Ltd",
    "artistId": 789,
    "description": "Track your health journey with Vitality.",
    "releaseNotes": "Bug fixes and improvements.",
    "version": "5.2.1",
    "price": 0.0,
    "currency": "GBP",
    "averageUserRating": 4.7,
    "userRatingCount": 15000,
    "contentAdvisoryRating": "4+",
    "genres": ["Health & Fitness", "Lifestyle"],
    "artworkUrl100": "https://is1.mzstatic.com/image/100x100.png",
    "artworkUrl512": "https://is1.mzstatic.com/image/512x512.png",
    "screenshotUrls": [
        "https://is1.mzstatic.com/image/screen1.png",
        "https://is1.mzstatic.com/image/screen2.png",
        "https://is1.mzstatic.com/image/screen3.png",
    ],
    "ipadScreenshotUrls": [
        "https://is1.mzstatic.com/image/ipad1.png",
    ],
    "trackViewUrl": "https://apps.apple.com/gb/app/vitality/id123456",
    "minimumOsVersion": "16.0",
    "fileSizeBytes": "85000000",
    "releaseDate": "2020-01-15T00:00:00Z",
    "currentVersionReleaseDate": "2026-02-10T00:00:00Z",
    "kind": "software",
}


# ═══════════════════════════════════════════════════════════════
# App Store: Parsing
# ═══════════════════════════════════════════════════════════════

class TestAppStoreParser:
    """Tests for iTunes API result parsing."""

    def test_parse_full_result(self):
        app = _parse_app_result(SAMPLE_ITUNES_RESULT)
        assert app.app_id == 123456
        assert app.name == "Vitality Health"
        assert app.developer == "Vitality Health Ltd"
        assert app.version == "5.2.1"
        assert app.rating == 4.7
        assert app.rating_count == 15000
        assert len(app.screenshot_urls) == 3
        assert len(app.ipad_screenshot_urls) == 1
        assert app.price == 0.0
        assert "Health & Fitness" in app.genres

    def test_parse_minimal_result(self):
        app = _parse_app_result({"trackId": 1, "trackName": "Minimal"})
        assert app.app_id == 1
        assert app.name == "Minimal"
        assert app.screenshot_urls == []
        assert app.rating == 0.0

    def test_to_dict(self):
        app = _parse_app_result(SAMPLE_ITUNES_RESULT)
        d = app.to_dict()
        assert isinstance(d, dict)
        assert d["app_id"] == 123456
        assert isinstance(d["screenshot_urls"], list)


# ═══════════════════════════════════════════════════════════════
# App Store: Search
# ═══════════════════════════════════════════════════════════════

class TestAppStoreSearch:
    """Tests for App Store search (mocked HTTP)."""

    def test_search_returns_results(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "resultCount": 2,
            "results": [
                {**SAMPLE_ITUNES_RESULT, "trackId": 1, "trackName": "App One", "kind": "software"},
                {**SAMPLE_ITUNES_RESULT, "trackId": 2, "trackName": "App Two", "kind": "software"},
            ],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.appstore.requests.get", return_value=mock_resp):
            results = appstore_search("health")
        assert len(results) == 2
        assert results[0].name == "App One"
        assert results[1].name == "App Two"

    def test_search_empty_results(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"resultCount": 0, "results": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.appstore.requests.get", return_value=mock_resp):
            results = appstore_search("nonexistent app xyz")
        assert results == []

    def test_search_handles_error(self):
        with patch("core.scrapers.appstore.requests.get", side_effect=Exception("Network error")):
            results = appstore_search("test")
        assert results == []


# ═══════════════════════════════════════════════════════════════
# App Store: Details
# ═══════════════════════════════════════════════════════════════

class TestAppStoreDetails:
    """Tests for App Store app details (mocked HTTP)."""

    def test_get_details(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"resultCount": 1, "results": [SAMPLE_ITUNES_RESULT]}
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.appstore.requests.get", return_value=mock_resp):
            app = appstore_details(123456)
        assert app is not None
        assert app.app_id == 123456
        assert app.name == "Vitality Health"

    def test_get_details_not_found(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"resultCount": 0, "results": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.appstore.requests.get", return_value=mock_resp):
            app = appstore_details(999999)
        assert app is None

    def test_get_details_error(self):
        with patch("core.scrapers.appstore.requests.get", side_effect=Exception("Timeout")):
            app = appstore_details(123456)
        assert app is None


# ═══════════════════════════════════════════════════════════════
# App Store: Download Screenshots
# ═══════════════════════════════════════════════════════════════

class TestAppStoreDownload:
    """Tests for App Store screenshot downloads (mocked HTTP)."""

    def test_download_screenshots(self, evidence_tmpdir):
        # Mock: lookup returns app, then each screenshot URL returns image data
        lookup_resp = MagicMock()
        lookup_resp.json.return_value = {"resultCount": 1, "results": [SAMPLE_ITUNES_RESULT]}
        lookup_resp.raise_for_status = MagicMock()

        img_resp = MagicMock()
        img_resp.content = b"\x89PNG fake image data"
        img_resp.status_code = 200
        img_resp.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if "itunes.apple.com" in url:
                return lookup_resp
            return img_resp

        with patch("core.scrapers.appstore.requests.get", side_effect=mock_get):
            result = appstore_download(123456, project_id=1, entity_id=10)

        assert result.success
        # 3 screenshots + 1 icon = 4 files
        assert len(result.evidence_paths) == 4
        assert result.metadata["app_name"] == "Vitality Health"
        assert result.metadata["screenshots_downloaded"] == 4

    def test_download_with_db(self, evidence_tmpdir, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]
        eid = entity_project["entity_id"]

        lookup_resp = MagicMock()
        lookup_resp.json.return_value = {"resultCount": 1, "results": [SAMPLE_ITUNES_RESULT]}
        lookup_resp.raise_for_status = MagicMock()

        img_resp = MagicMock()
        img_resp.content = b"\x89PNG test"
        img_resp.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if "itunes.apple.com" in url:
                return lookup_resp
            return img_resp

        with patch("core.scrapers.appstore.requests.get", side_effect=mock_get):
            result = appstore_download(123456, pid, eid, db=db)

        assert result.success
        assert len(result.evidence_ids) == 4  # 3 screenshots + 1 icon

        # Verify DB records
        evidence = db.get_evidence(entity_id=eid)
        assert len(evidence) == 4
        assert all(e["source_name"] == "Apple App Store" for e in evidence)

    def test_download_app_not_found(self, evidence_tmpdir):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"resultCount": 0, "results": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.appstore.requests.get", return_value=mock_resp):
            result = appstore_download(999999, project_id=1, entity_id=10)

        assert not result.success
        assert "not found" in result.error

    def test_download_partial_failure(self, evidence_tmpdir):
        """Some screenshots fail but others succeed — should still return success."""
        lookup_resp = MagicMock()
        lookup_resp.json.return_value = {"resultCount": 1, "results": [SAMPLE_ITUNES_RESULT]}
        lookup_resp.raise_for_status = MagicMock()

        call_count = [0]

        def mock_get(url, **kwargs):
            if "itunes.apple.com" in url:
                return lookup_resp
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                raise Exception("Download failed")
            resp = MagicMock()
            resp.content = b"\x89PNG data"
            resp.raise_for_status = MagicMock()
            return resp

        with patch("core.scrapers.appstore.requests.get", side_effect=mock_get):
            result = appstore_download(123456, project_id=1, entity_id=10)

        assert result.success  # Some files downloaded
        assert result.metadata.get("download_errors")  # Some errors logged


# ═══════════════════════════════════════════════════════════════
# App Store: Metadata for Entity
# ═══════════════════════════════════════════════════════════════

class TestAppStoreMetadata:
    """Tests for App Store metadata extraction for entity attributes."""

    def test_get_metadata(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"resultCount": 1, "results": [SAMPLE_ITUNES_RESULT]}
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.appstore.requests.get", return_value=mock_resp):
            meta = appstore_metadata(123456)

        assert meta["app_store_id"] == "123456"
        assert meta["app_store_rating"] == 4.7
        assert meta["app_store_version"] == "5.2.1"
        assert "Vitality Health Ltd" in meta["app_store_developer"]

    def test_get_metadata_not_found(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"resultCount": 0, "results": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.appstore.requests.get", return_value=mock_resp):
            meta = appstore_metadata(999999)
        assert meta == {}


# ═══════════════════════════════════════════════════════════════
# Play Store: Details (mocked HTML)
# ═══════════════════════════════════════════════════════════════

SAMPLE_PLAY_HTML = """
<html>
<head><title>Vitality Member - Apps on Google Play</title>
<meta name="description" content="Track your health journey.">
</head>
<body>
<a href="/store/apps/developer?id=Vitality+Health">Vitality Health Ltd</a>
<div data-g-id="description">Full description of the app with features.</div>
<img alt="icon" src="https://play-lh.googleusercontent.com/icon=s180">
<img alt="Screenshot 1" src="https://play-lh.googleusercontent.com/screen1=w720">
<img alt="Screenshot 2" src="https://play-lh.googleusercontent.com/screen2=w720">
<div><span>4.5</span></div>
</body>
</html>
"""


class TestPlayStoreDetails:
    """Tests for Play Store details (mocked HTTP + HTML parsing)."""

    def test_get_details(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_PLAY_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.playstore.requests.get", return_value=mock_resp):
            app = playstore_details("com.vitality.member")

        assert app is not None
        assert app.package_id == "com.vitality.member"
        assert "Vitality" in app.name
        assert app.developer == "Vitality Health Ltd"

    def test_get_details_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("core.scrapers.playstore.requests.get", return_value=mock_resp):
            app = playstore_details("com.nonexistent.app")
        assert app is None

    def test_get_details_error(self):
        with patch("core.scrapers.playstore.requests.get", side_effect=Exception("Network error")):
            app = playstore_details("com.test.app")
        assert app is None


# ═══════════════════════════════════════════════════════════════
# Play Store: Download Screenshots
# ═══════════════════════════════════════════════════════════════

class TestPlayStoreDownload:
    """Tests for Play Store screenshot downloads (mocked HTTP)."""

    def test_download_screenshots(self, evidence_tmpdir):
        details_resp = MagicMock()
        details_resp.status_code = 200
        details_resp.text = SAMPLE_PLAY_HTML
        details_resp.raise_for_status = MagicMock()

        img_resp = MagicMock()
        img_resp.content = b"\x89PNG fake image"
        img_resp.status_code = 200
        img_resp.headers = {"Content-Type": "image/png"}
        img_resp.raise_for_status = MagicMock()

        def mock_get(url, **kwargs):
            if "play.google.com" in url:
                return details_resp
            return img_resp

        with patch("core.scrapers.playstore.requests.get", side_effect=mock_get):
            result = playstore_download("com.vitality.member", project_id=1, entity_id=10)

        # Result depends on how many screenshots the parser finds
        assert result.metadata["package_id"] == "com.vitality.member"

    def test_download_app_not_found(self, evidence_tmpdir):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("core.scrapers.playstore.requests.get", return_value=mock_resp):
            result = playstore_download("com.nonexistent", project_id=1, entity_id=10)

        assert not result.success
        assert "not found" in result.error

    def test_download_with_db(self, evidence_tmpdir, entity_project):
        db = entity_project["db"]
        pid = entity_project["project_id"]
        eid = entity_project["entity_id"]

        # Create a mock app with screenshot URLs
        mock_app = PlayStoreApp(
            package_id="com.test.app",
            name="Test App",
            developer="Test Dev",
            screenshot_urls=["https://play-lh.googleusercontent.com/img1=w720"],
            icon_url="https://play-lh.googleusercontent.com/icon=s180",
            store_url="https://play.google.com/store/apps/details?id=com.test.app",
        )

        img_resp = MagicMock()
        img_resp.content = b"\x89PNG test"
        img_resp.headers = {"Content-Type": "image/png"}
        img_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.playstore.get_app_details", return_value=mock_app), \
             patch("core.scrapers.playstore.requests.get", return_value=img_resp):
            result = playstore_download("com.test.app", pid, eid, db=db)

        assert result.success
        assert len(result.evidence_ids) == 2  # 1 screenshot + 1 icon
        evidence = db.get_evidence(entity_id=eid)
        assert len(evidence) == 2
        assert all(e["source_name"] == "Google Play Store" for e in evidence)


# ═══════════════════════════════════════════════════════════════
# Play Store: Metadata
# ═══════════════════════════════════════════════════════════════

class TestPlayStoreMetadata:
    """Tests for Play Store metadata extraction for entity attributes."""

    def test_get_metadata(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = SAMPLE_PLAY_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch("core.scrapers.playstore.requests.get", return_value=mock_resp):
            meta = playstore_metadata("com.vitality.member")

        assert meta["play_store_id"] == "com.vitality.member"
        assert "Vitality Health" in meta.get("play_store_developer", "")

    def test_get_metadata_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("core.scrapers.playstore.requests.get", return_value=mock_resp):
            meta = playstore_metadata("com.nonexistent")
        assert meta == {}


# ═══════════════════════════════════════════════════════════════
# Dataclass Tests
# ═══════════════════════════════════════════════════════════════

class TestDataclasses:
    """Tests for scraper dataclass structures."""

    def test_appstore_app_defaults(self):
        app = AppStoreApp(app_id=1, name="Test")
        assert app.app_id == 1
        assert app.screenshot_urls == []
        assert app.rating == 0.0
        assert app.genres == []

    def test_playstore_app_defaults(self):
        app = PlayStoreApp(package_id="com.test")
        assert app.name == ""
        assert app.screenshot_urls == []
        assert app.rating == 0.0

    def test_appstore_to_dict(self):
        app = AppStoreApp(app_id=42, name="MyApp", rating=4.5)
        d = app.to_dict()
        assert d["app_id"] == 42
        assert d["rating"] == 4.5

    def test_playstore_to_dict(self):
        app = PlayStoreApp(package_id="com.x", name="X", rating=3.8)
        d = app.to_dict()
        assert d["package_id"] == "com.x"
        assert d["rating"] == 3.8
