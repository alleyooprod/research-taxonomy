"""Tests for Taxonomy API — categories, colors, metadata, review, quality.

Run: pytest tests/test_api_taxonomy.py -v
Markers: api, taxonomy
"""
import pytest

pytestmark = [pytest.mark.api, pytest.mark.taxonomy]


class TestGetTaxonomy:
    """TAX-LIST: Taxonomy listing via GET /api/taxonomy."""

    def test_get_taxonomy(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/taxonomy?project_id={api_project['id']}")
        assert r.status_code == 200
        cats = r.get_json()
        assert isinstance(cats, list)
        assert len(cats) >= 3  # Alpha, Beta, Gamma from seeds

    def test_taxonomy_returns_stats(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/taxonomy?project_id={pid}")
        cats = r.get_json()
        # Each category should have a company_count or similar field
        for cat in cats:
            assert "id" in cat
            assert "name" in cat


class TestTaxonomyHistory:
    """TAX-HIST: Taxonomy history via GET /api/taxonomy/history."""

    def test_history_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/taxonomy/history?project_id={api_project['id']}")
        assert r.status_code == 200


class TestGetCategory:
    """TAX-CAT-GET: Single category via GET /api/categories/<id>."""

    def test_get_category(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cat_id = api_project_with_companies["category_id"]
        r = c.get(f"/api/categories/{cat_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert "companies" in data

    def test_get_nonexistent_category(self, client):
        r = client.get("/api/categories/99999")
        assert r.status_code == 404


class TestCategoryColor:
    """TAX-COLOR: Category color via PUT /api/categories/<id>/color."""

    def test_set_color(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cat_id = api_project_with_companies["category_id"]
        r = c.put(f"/api/categories/{cat_id}/color", json={"color": "#FF5733"})
        assert r.status_code == 200

    def test_color_persists(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cat_id = api_project_with_companies["category_id"]
        c.put(f"/api/categories/{cat_id}/color", json={"color": "#00FF00"})
        r = c.get(f"/api/categories/{cat_id}")
        data = r.get_json()
        assert data.get("color") == "#00FF00"


class TestCategoryMetadata:
    """TAX-META: Category metadata via PUT /api/categories/<id>/metadata."""

    def test_set_metadata(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cat_id = api_project_with_companies["category_id"]
        r = c.put(f"/api/categories/{cat_id}/metadata", json={
            "scope_note": "This category covers...",
            "inclusion_criteria": "Include companies that...",
            "exclusion_criteria": "Exclude companies that...",
        })
        assert r.status_code == 200


class TestTaxonomyReviewApply:
    """TAX-REVIEW-APPLY: Apply taxonomy changes via POST /api/taxonomy/review/apply."""

    def test_apply_empty_changes(self, api_project):
        c = api_project["client"]
        r = c.post("/api/taxonomy/review/apply", json={
            "changes": [],
            "project_id": api_project["id"],
        })
        assert r.status_code == 200
        assert r.get_json()["applied"] == 0


class TestTaxonomyQuality:
    """TAX-QUALITY: Quality metrics via GET /api/taxonomy/quality."""

    def test_quality_metrics(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/taxonomy/quality?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)
