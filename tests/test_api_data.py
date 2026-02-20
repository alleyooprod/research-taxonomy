"""Tests for Data API — exports, imports, stats, charts, tags, views, map layouts.

Run: pytest tests/test_api_data.py -v
Markers: api, data
"""
import io
import json
import pytest

pytestmark = [pytest.mark.api, pytest.mark.data]


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

class TestExportJSON:
    """DATA-EXP-JSON: JSON export via GET /api/export/json."""

    def test_export_json(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/export/json?project_id={api_project['id']}")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "companies" in data
        assert "categories" in data

    def test_export_json_includes_extra_tables(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/export/json?project_id={api_project['id']}")
        data = json.loads(r.data)
        assert "taxonomy_history" in data
        assert "reports" in data
        assert "activity_log" in data
        assert "saved_views" in data


class TestExportCSV:
    """DATA-EXP-CSV: CSV export via GET /api/export/csv."""

    def test_export_csv(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/export/csv?project_id={api_project['id']}")
        assert r.status_code == 200
        assert b"name" in r.data or r.data == b""  # Header or empty

    def test_export_csv_with_companies(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/export/csv?project_id={pid}")
        assert r.status_code == 200
        lines = r.data.decode().strip().split("\n")
        assert len(lines) >= 2  # Header + at least 1 company


class TestExportMarkdown:
    """DATA-EXP-MD: Markdown export via GET /api/export/md."""

    def test_export_md(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/export/md?project_id={api_project['id']}")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class TestImportCSV:
    """DATA-IMP-CSV: CSV import via POST /api/import/csv."""

    def test_import_csv(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        csv_data = "name,url,what\nImported Co,https://imported.com,Does stuff\n"
        data = {
            "project_id": str(pid),
            "file": (io.BytesIO(csv_data.encode()), "test.csv"),
        }
        r = c.post("/api/import/csv",
                    data=data,
                    content_type="multipart/form-data")
        assert r.status_code == 200

    def test_import_csv_missing_file(self, api_project):
        c = api_project["client"]
        r = c.post("/api/import/csv",
                    data={"project_id": str(api_project["id"])},
                    content_type="multipart/form-data")
        assert r.status_code == 400

    def test_import_csv_missing_project(self, api_project):
        c = api_project["client"]
        csv_data = "name,url\nTest,https://test.com\n"
        data = {
            "file": (io.BytesIO(csv_data.encode()), "test.csv"),
        }
        r = c.post("/api/import/csv",
                    data=data,
                    content_type="multipart/form-data")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Stats & Charts
# ---------------------------------------------------------------------------

class TestStats:
    """DATA-STATS: Stats via GET /api/stats."""

    def test_stats_empty_project(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/stats?project_id={api_project['id']}")
        assert r.status_code == 200
        data = r.get_json()
        assert "total_companies" in data or isinstance(data, dict)

    def test_stats_with_companies(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/stats?project_id={pid}")
        assert r.status_code == 200


class TestCharts:
    """DATA-CHARTS: Chart data via GET /api/charts/data."""

    def test_chart_data(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/charts/data?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class TestFilterOptions:
    """DATA-FILTERS: Filter options via GET /api/filters/options."""

    def test_filter_options(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/filters/options?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "tags" in data
        assert "geographies" in data
        assert "funding_stages" in data


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTags:
    """DATA-TAGS: Tag management."""

    def test_list_tags(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/tags?project_id={pid}")
        assert r.status_code == 200

    def test_rename_tag(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        # First add a tag via bulk action
        ids = api_project_with_companies["company_ids"][:1]
        c.post("/api/companies/bulk", json={
            "action": "add_tags",
            "company_ids": ids,
            "params": {"tags": ["rename-me"]},
        })
        r = c.post("/api/tags/rename", json={
            "old_tag": "rename-me",
            "new_tag": "renamed",
            "project_id": pid,
        })
        assert r.status_code == 200

    def test_delete_tag(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        ids = api_project_with_companies["company_ids"][:1]
        c.post("/api/companies/bulk", json={
            "action": "add_tags",
            "company_ids": ids,
            "params": {"tags": ["delete-me"]},
        })
        r = c.post("/api/tags/delete", json={
            "tag": "delete-me",
            "project_id": pid,
        })
        assert r.status_code == 200

    def test_merge_tags(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        ids = api_project_with_companies["company_ids"][:1]
        c.post("/api/companies/bulk", json={
            "action": "add_tags",
            "company_ids": ids,
            "params": {"tags": ["merge-src", "merge-tgt"]},
        })
        r = c.post("/api/tags/merge", json={
            "source_tag": "merge-src",
            "target_tag": "merge-tgt",
            "project_id": pid,
        })
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Saved Views
# ---------------------------------------------------------------------------

class TestSavedViews:
    """DATA-VIEWS: Saved view management."""

    def test_list_views_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/views?project_id={api_project['id']}")
        assert r.status_code == 200

    def test_create_and_list_view(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/views", json={
            "project_id": pid,
            "name": "My View",
            "filters": {"starred": True, "search": "health"},
        })
        assert r.status_code == 200

        r = c.get(f"/api/views?project_id={pid}")
        views = r.get_json()
        assert any(v["name"] == "My View" for v in views)

    def test_delete_view(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        c.post("/api/views", json={
            "project_id": pid,
            "name": "Delete View",
            "filters": {},
        })
        r = c.get(f"/api/views?project_id={pid}")
        views = r.get_json()
        view_id = views[0]["id"]

        r = c.delete(f"/api/views/{view_id}")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Map Layouts
# ---------------------------------------------------------------------------

class TestMapLayouts:
    """DATA-MAP: Map layout persistence."""

    def test_list_layouts_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/map-layouts?project_id={api_project['id']}")
        assert r.status_code == 200

    def test_save_layout(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        r = c.post("/api/map-layouts", json={
            "project_id": pid,
            "name": "Default Map",
            "layout_data": {"center": [51.5, -0.1], "zoom": 5},
        })
        assert r.status_code == 200
