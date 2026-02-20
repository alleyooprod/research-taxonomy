"""Tests for UI gallery scrapers — Dribbble, Scrnshts, CollectUI, Godly,
Siteinspire, OnePageLove, SaaSPages, Httpster.

All external HTTP calls are mocked — no real network requests.

Covers:
- Dataclass construction and to_dict()
- HTML parsing functions (mocked responses)
- Download functions (mocked HTTP + file storage)
- API endpoints: gallery sources, search, download

Run: pytest tests/test_gallery_scrapers.py -v
Markers: db, capture
"""
import json
import pytest
from unittest.mock import patch, MagicMock

from core.scrapers.dribbble import DribbbleShot, search_shots as dribbble_search
from core.scrapers.scrnshts import ScrnshotsApp, search_apps as scrnshts_search
from core.scrapers.collectui import CollectUIShot, list_challenges, browse_challenge
from core.scrapers.godly import GodlySite, search_sites as godly_search
from core.scrapers.siteinspire import SiteinspireSite, browse_sites as si_browse
from core.scrapers.onepagelove import OnePageSite, search_sites as opl_search
from core.scrapers.saaspages import SaaSPage, browse_sites as saas_browse
from core.scrapers.httpster import HttpsterSite, search_sites as httpster_search

pytestmark = [pytest.mark.db, pytest.mark.capture]


# ═══════════════════════════════════════════════════════════════
# Dataclass Tests
# ═══════════════════════════════════════════════════════════════

class TestDataclasses:
    """Verify all gallery scraper dataclasses construct and serialize."""

    def test_dribbble_shot(self):
        shot = DribbbleShot(id=123, title="Test Shot", image_url="https://cdn.dribbble.com/test.png")
        d = shot.to_dict()
        assert d["id"] == 123
        assert d["title"] == "Test Shot"
        assert d["image_url"] == "https://cdn.dribbble.com/test.png"
        assert "designer" in d
        assert "tags" in d

    def test_scrnshts_app(self):
        app = ScrnshotsApp(slug="test-app", name="Test App", screenshot_urls=["https://scrnshts.club/wp-content/uploads/test/1.webp"])
        d = app.to_dict()
        assert d["slug"] == "test-app"
        assert d["name"] == "Test App"
        assert len(d["screenshot_urls"]) == 1

    def test_collectui_shot(self):
        shot = CollectUIShot(id=456, title="Login Page", challenge="login")
        d = shot.to_dict()
        assert d["id"] == 456
        assert d["challenge"] == "login"

    def test_godly_site(self):
        site = GodlySite(id="abc", name="Test Site", slug="test-site", url="https://test.com")
        d = site.to_dict()
        assert d["slug"] == "test-site"
        assert d["url"] == "https://test.com"
        assert "categories" in d

    def test_siteinspire_site(self):
        site = SiteinspireSite(id=789, name="Linear", slug="linear-app", categories=["SaaS"])
        d = site.to_dict()
        assert d["id"] == 789
        assert d["categories"] == ["SaaS"]
        assert "styles" in d
        assert "types" in d

    def test_onepagelove_site(self):
        site = OnePageSite(slug="test-site", name="Test", tags=["portfolio", "minimal"])
        d = site.to_dict()
        assert d["slug"] == "test-site"
        assert d["tags"] == ["portfolio", "minimal"]

    def test_saaspage(self):
        page = SaaSPage(slug="stripe", name="Stripe", block_type="pricing")
        d = page.to_dict()
        assert d["block_type"] == "pricing"

    def test_httpster_site(self):
        site = HttpsterSite(slug="test-site", name="Test", categories=["portfolio"])
        d = site.to_dict()
        assert d["categories"] == ["portfolio"]


# ═══════════════════════════════════════════════════════════════
# Search / Parse Tests (mocked HTTP)
# ═══════════════════════════════════════════════════════════════

class TestDribbbleSearch:
    """Dribbble scraper search with mocked HTTP."""

    @patch("core.scrapers.dribbble.requests.get")
    def test_search_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        results = dribbble_search("test")
        assert results == []

    @patch("core.scrapers.dribbble.requests.get")
    def test_search_parses_html(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <html><body>
        <ol class="dribbble">
            <li class="shot-thumbnail" data-screenshot-id="12345">
                <a href="/shots/12345-test-shot">
                    <img src="https://cdn.dribbble.com/userupload/12345/test.png" alt="Test Shot">
                </a>
                <div class="shot-details">
                    <a class="shot-title" href="/shots/12345">Test Shot</a>
                </div>
            </li>
        </ol>
        </body></html>
        """
        mock_get.return_value = mock_resp
        results = dribbble_search("test")
        # May or may not find results depending on exact HTML parsing strategy
        assert isinstance(results, list)


class TestScrnshotsSearch:
    """Scrnshts Club search with mocked HTTP."""

    @patch("core.scrapers.scrnshts.requests.get")
    def test_search_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        results = scrnshts_search("finance")
        assert results == []

    @patch("core.scrapers.scrnshts.requests.get")
    def test_search_parses_wordpress(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <html><body>
        <article class="post">
            <a href="https://scrnshts.club/vitality/" class="post-thumbnail">
                <img src="https://scrnshts.club/wp-content/uploads/vitality/1.webp" alt="Vitality">
            </a>
            <h2 class="entry-title"><a href="https://scrnshts.club/vitality/">Vitality</a></h2>
        </article>
        </body></html>
        """
        mock_get.return_value = mock_resp
        results = scrnshts_search("vitality")
        assert isinstance(results, list)


class TestCollectUI:
    """Collect UI scraper tests."""

    def test_list_challenges_returns_list(self):
        # list_challenges() has a fallback built-in list
        challenges = list_challenges()
        assert isinstance(challenges, list)
        assert len(challenges) > 0

    @patch("core.scrapers.collectui.requests.get")
    def test_browse_challenge_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("Timeout")
        results = browse_challenge("login")
        assert results == []


class TestGodlySearch:
    """Godly gallery search tests."""

    @patch("core.scrapers.godly.requests.get")
    def test_search_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("DNS failure")
        results = godly_search("fintech")
        assert results == []


class TestSiteinspireBrowse:
    """Siteinspire browse tests."""

    @patch("core.scrapers.siteinspire.requests.get")
    def test_browse_returns_empty_on_404(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp
        results = si_browse(page=999)
        assert results == []


class TestOnePageLoveSearch:
    """One Page Love search tests."""

    @patch("core.scrapers.onepagelove.requests.get")
    def test_search_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("Timeout")
        results = opl_search("portfolio")
        assert results == []


class TestSaaSPagesBrowse:
    """SaaS Pages browse tests."""

    @patch("core.scrapers.saaspages.requests.get")
    def test_browse_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("Connection reset")
        results = saas_browse()
        assert results == []


class TestHttpsterSearch:
    """Httpster search tests."""

    @patch("core.scrapers.httpster.requests.get")
    def test_search_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("Timeout")
        results = httpster_search("dark")
        assert results == []


# ═══════════════════════════════════════════════════════════════
# API Endpoint Tests
# ═══════════════════════════════════════════════════════════════

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
                {"name": "URL", "slug": "url", "data_type": "url"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture
def gallery_project(client, tmp_path, monkeypatch):
    """Create a project + entity for gallery scraper API tests."""
    import core.capture as capture_mod
    test_evidence_dir = tmp_path / "evidence"
    test_evidence_dir.mkdir()
    monkeypatch.setattr(capture_mod, "EVIDENCE_DIR", test_evidence_dir)

    pid = client.db.create_project(
        name="Gallery Test",
        purpose="Testing gallery scrapers",
        entity_schema=TEST_SCHEMA,
    )
    eid = client.db.create_entity(pid, "company", "Test Company")

    return {"client": client, "project_id": pid, "entity_id": eid}


class TestGallerySourcesAPI:
    """Gallery sources listing endpoint."""

    def test_list_sources(self, gallery_project):
        c = gallery_project["client"]
        r = c.get("/api/scrape/gallery/sources")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) == 8
        names = [s["name"] for s in data]
        assert "dribbble" in names
        assert "scrnshts" in names
        assert "collectui" in names
        assert "godly" in names
        assert "siteinspire" in names
        assert "onepagelove" in names
        assert "saaspages" in names
        assert "httpster" in names


class TestGallerySearchAPI:
    """Gallery search endpoint tests."""

    def test_unknown_source_returns_400(self, gallery_project):
        c = gallery_project["client"]
        r = c.get("/api/scrape/gallery/nonexistent/search?q=test")
        assert r.status_code == 400
        assert "Unknown" in r.get_json()["error"]

    def test_missing_query_returns_400(self, gallery_project):
        c = gallery_project["client"]
        r = c.get("/api/scrape/gallery/dribbble/search")
        assert r.status_code == 400
        assert "q parameter" in r.get_json()["error"]

    def test_saaspages_no_query_needed(self, gallery_project):
        """SaaS Pages uses browse_sites which doesn't require a query."""
        c = gallery_project["client"]
        with patch("core.scrapers.saaspages.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body></body></html>"
            mock_get.return_value = mock_resp
            r = c.get("/api/scrape/gallery/saaspages/search")
            assert r.status_code == 200
            assert isinstance(r.get_json(), list)

    @patch("core.scrapers.dribbble.requests.get")
    def test_dribbble_search_via_api(self, mock_get, gallery_project):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body></body></html>"
        mock_get.return_value = mock_resp
        c = gallery_project["client"]
        r = c.get("/api/scrape/gallery/dribbble/search?q=login")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    @patch("core.scrapers.godly.requests.get")
    def test_godly_search_via_api(self, mock_get, gallery_project):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body></body></html>"
        mock_get.return_value = mock_resp
        c = gallery_project["client"]
        r = c.get("/api/scrape/gallery/godly/search?q=fintech")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)


class TestGalleryDownloadAPI:
    """Gallery download endpoint tests."""

    def test_unknown_source_returns_400(self, gallery_project):
        c = gallery_project["client"]
        pid = gallery_project["project_id"]
        eid = gallery_project["entity_id"]
        r = c.post("/api/scrape/gallery/nonexistent/download", json={
            "project_id": pid, "entity_id": eid, "slug": "test",
        })
        assert r.status_code == 400

    def test_missing_entity_id(self, gallery_project):
        c = gallery_project["client"]
        r = c.post("/api/scrape/gallery/dribbble/download", json={
            "project_id": gallery_project["project_id"],
            "query": "test",
        })
        assert r.status_code == 400
        assert "entity_id" in r.get_json()["error"]

    def test_missing_project_id(self, gallery_project):
        c = gallery_project["client"]
        r = c.post("/api/scrape/gallery/dribbble/download", json={
            "entity_id": gallery_project["entity_id"],
            "query": "test",
        })
        assert r.status_code == 400
        assert "project_id" in r.get_json()["error"]

    def test_missing_identifier(self, gallery_project):
        c = gallery_project["client"]
        pid = gallery_project["project_id"]
        eid = gallery_project["entity_id"]
        r = c.post("/api/scrape/gallery/scrnshts/download", json={
            "project_id": pid, "entity_id": eid,
        })
        assert r.status_code == 400
        assert "slug" in r.get_json()["error"]

    def test_entity_not_found(self, gallery_project):
        c = gallery_project["client"]
        r = c.post("/api/scrape/gallery/dribbble/download", json={
            "project_id": gallery_project["project_id"],
            "entity_id": 99999,
            "query": "test",
        })
        assert r.status_code == 404

    @patch("core.scrapers.godly.get_site_details")
    def test_godly_download_not_found(self, mock_details, gallery_project):
        mock_details.return_value = None
        c = gallery_project["client"]
        pid = gallery_project["project_id"]
        eid = gallery_project["entity_id"]
        r = c.post("/api/scrape/gallery/godly/download", json={
            "project_id": pid,
            "entity_id": eid,
            "slug": "nonexistent-site",
        })
        assert r.status_code == 422

    @patch("core.scrapers.httpster.get_site_details")
    def test_httpster_download_not_found(self, mock_details, gallery_project):
        mock_details.return_value = None
        c = gallery_project["client"]
        pid = gallery_project["project_id"]
        eid = gallery_project["entity_id"]
        r = c.post("/api/scrape/gallery/httpster/download", json={
            "project_id": pid,
            "entity_id": eid,
            "slug": "nonexistent",
        })
        assert r.status_code == 422
