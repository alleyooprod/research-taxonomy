"""Tests for static file serving and index page.

Run: pytest tests/test_api_static.py -v
Markers: api, static
"""
import pytest

pytestmark = [pytest.mark.api, pytest.mark.static]


class TestIndexPage:
    """STATIC-INDEX: Homepage HTML via GET /."""

    def test_index_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"Research Taxonomy Library" in r.data

    def test_index_contains_csrf_meta(self, client):
        r = client.get("/")
        assert b'name="csrf-token"' in r.data

    def test_index_contains_app_version(self, client):
        r = client.get("/")
        assert b"app_version" in r.data or b"1.1.0" in r.data


class TestHealthEndpoint:
    """STATIC-HEALTH: Health check via GET /healthz."""

    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        assert data["db"] == "connected"


class TestStaticFiles:
    """STATIC-FILES: CSS and JS file serving."""

    def test_styles_css(self, client):
        r = client.get("/static/styles.css")
        assert r.status_code == 200
        assert b"@import" in r.data

    def test_base_css(self, client):
        r = client.get("/static/base.css")
        assert r.status_code == 200
        assert b":root" in r.data

    def test_core_js(self, client):
        r = client.get("/static/js/core.js")
        assert r.status_code == 200

    def test_companies_js(self, client):
        r = client.get("/static/js/companies.js")
        assert r.status_code == 200

    def test_taxonomy_js(self, client):
        r = client.get("/static/js/taxonomy.js")
        assert r.status_code == 200

    def test_canvas_js(self, client):
        r = client.get("/static/js/canvas.js")
        assert r.status_code == 200

    def test_maps_js(self, client):
        r = client.get("/static/js/maps.js")
        assert r.status_code == 200

    def test_diagram_js(self, client):
        r = client.get("/static/js/diagram.js")
        assert r.status_code == 200

    def test_projects_js(self, client):
        r = client.get("/static/js/projects.js")
        assert r.status_code == 200

    def test_init_js(self, client):
        r = client.get("/static/js/init.js")
        assert r.status_code == 200

    def test_ai_js(self, client):
        r = client.get("/static/js/ai.js")
        assert r.status_code == 200

    def test_integrations_js(self, client):
        r = client.get("/static/js/integrations.js")
        assert r.status_code == 200
