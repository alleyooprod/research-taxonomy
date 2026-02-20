"""Tests for Companies API — CRUD, bulk actions, notes, events, versions, trash.

Run: pytest tests/test_api_companies.py -v
Markers: api, companies
"""
import json
import pytest

pytestmark = [pytest.mark.api, pytest.mark.companies]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _create_company(client, pid, name="Test Co", url="https://test.com", **extra):
    """Quick helper to create a company and return its id."""
    r = client.post("/api/companies/add", json={
        "url": url, "name": name, "project_id": pid, **extra,
    })
    assert r.status_code == 200, f"Failed to create company: {r.data}"
    return r.get_json()["id"]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestAddCompany:
    """CMP-ADD: Company creation via POST /api/companies/add."""

    def test_add_basic(self, api_project):
        c = api_project["client"]
        pid = api_project["id"]
        cid = _create_company(c, pid, "New Corp", "https://newcorp.com")
        assert cid is not None

    def test_add_with_name_only(self, api_project):
        c = api_project["client"]
        r = c.post("/api/companies/add", json={
            "url": "https://named.com",
            "name": "Named Co",
            "project_id": api_project["id"],
        })
        assert r.status_code == 200

    def test_add_rejects_missing_url(self, api_project):
        c = api_project["client"]
        r = c.post("/api/companies/add", json={
            "name": "No URL",
            "project_id": api_project["id"],
        })
        assert r.status_code == 400

    def test_add_rejects_missing_project_id(self, api_project):
        c = api_project["client"]
        r = c.post("/api/companies/add", json={
            "url": "https://nopid.com", "name": "No PID",
        })
        assert r.status_code == 400


class TestListCompanies:
    """CMP-LIST: Company listing via GET /api/companies."""

    def test_list_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/companies?project_id={api_project['id']}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_list_returns_created(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/companies?project_id={pid}")
        companies = r.get_json()
        assert len(companies) >= 3

    def test_list_search_filter(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/companies?project_id={pid}&search=Test")
        companies = r.get_json()
        assert all("Test" in co["name"] for co in companies)

    def test_list_starred_filter(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        # Star one company
        cid = api_project_with_companies["company_ids"][0]
        c.post(f"/api/companies/{cid}/star")
        r = c.get(f"/api/companies?project_id={pid}&starred=1")
        companies = r.get_json()
        assert all(co.get("is_starred") for co in companies)

    def test_list_sort_by_name(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/companies?project_id={pid}&sort_by=name&sort_dir=asc")
        companies = r.get_json()
        names = [co["name"] for co in companies]
        assert names == sorted(names)

    def test_list_with_category_filter(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cat_id = api_project_with_companies["category_id"]
        r = c.get(f"/api/companies?project_id={pid}&category_id={cat_id}")
        assert r.status_code == 200


class TestGetCompany:
    """CMP-GET: Single company retrieval via GET /api/companies/<id>."""

    def test_get_existing(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.get(f"/api/companies/{cid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "Test Corp"
        assert "notes" in data
        assert "events" in data

    def test_get_nonexistent(self, client):
        r = client.get("/api/companies/99999")
        assert r.status_code == 404


class TestUpdateCompany:
    """CMP-UPDATE: Company update via POST /api/companies/<id>."""

    def test_update_fields(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}", json={
            "what": "Updated description",
            "target": "New target market",
            "project_id": pid,
        })
        assert r.status_code == 200

        r = c.get(f"/api/companies/{cid}")
        data = r.get_json()
        assert data["what"] == "Updated description"
        assert data["target"] == "New target market"

    def test_update_funding_fields(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}", json={
            "funding_stage": "series_b",
            "total_funding_usd": 50000000,
            "project_id": pid,
        })
        assert r.status_code == 200


class TestDeleteCompany:
    """CMP-DELETE: Company soft-delete via DELETE /api/companies/<id>."""

    def test_soft_delete(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cid = api_project_with_companies["company_ids"][0]

        r = c.delete(f"/api/companies/{cid}")
        assert r.status_code == 200

        # Should not appear in normal listing
        r = c.get(f"/api/companies?project_id={pid}")
        ids = [co["id"] for co in r.get_json()]
        assert cid not in ids

    def test_deleted_appears_in_trash(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cid = api_project_with_companies["company_ids"][0]

        c.delete(f"/api/companies/{cid}")
        r = c.get(f"/api/trash?project_id={pid}")
        assert r.status_code == 200
        ids = [co["id"] for co in r.get_json()]
        assert cid in ids


# ---------------------------------------------------------------------------
# Star & Relationship
# ---------------------------------------------------------------------------

class TestStarCompany:
    """CMP-STAR: Star toggle via POST /api/companies/<id>/star."""

    def test_star_toggle(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]

        r = c.post(f"/api/companies/{cid}/star")
        assert r.status_code == 200
        assert r.get_json()["is_starred"]  # truthy (1 or True)

        r = c.post(f"/api/companies/{cid}/star")
        assert not r.get_json()["is_starred"]  # falsy (0 or False)

    def test_star_nonexistent(self, client):
        r = client.post("/api/companies/99999/star")
        assert r.status_code == 404


class TestRelationship:
    """CMP-REL: Relationship update via POST /api/companies/<id>/relationship."""

    def test_set_relationship(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/relationship", json={
            "status": "watching",
            "note": "Interesting company",
        })
        assert r.status_code == 200

    def test_update_relationship_status(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        for status in ["watching", "to_reach_out", "in_conversation", "met", "partner", "not_relevant"]:
            r = c.post(f"/api/companies/{cid}/relationship", json={"status": status})
            assert r.status_code == 200


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

class TestNotes:
    """CMP-NOTES: Company notes CRUD."""

    def test_add_note(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/notes", json={"content": "Test note"})
        assert r.status_code == 200
        assert r.get_json()["id"] is not None

    def test_list_notes(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        c.post(f"/api/companies/{cid}/notes", json={"content": "Note 1"})
        c.post(f"/api/companies/{cid}/notes", json={"content": "Note 2"})

        r = c.get(f"/api/companies/{cid}/notes")
        assert r.status_code == 200
        assert len(r.get_json()) >= 2

    def test_update_note(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/notes", json={"content": "Original"})
        note_id = r.get_json()["id"]

        r = c.post(f"/api/notes/{note_id}", json={"content": "Updated"})
        assert r.status_code == 200

    def test_delete_note(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/notes", json={"content": "To delete"})
        note_id = r.get_json()["id"]

        r = c.delete(f"/api/notes/{note_id}")
        assert r.status_code == 200

    def test_pin_note(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/notes", json={"content": "Pin me"})
        note_id = r.get_json()["id"]

        r = c.post(f"/api/notes/{note_id}/pin")
        assert r.status_code == 200
        assert r.get_json()["is_pinned"]  # truthy (1 or True)

    def test_add_empty_note_rejected(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/notes", json={"content": ""})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEvents:
    """CMP-EVENTS: Company lifecycle events."""

    def test_add_event(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/events", json={
            "event_type": "funding_round",
            "description": "Series A at $10M",
        })
        assert r.status_code == 200

    def test_list_events(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        c.post(f"/api/companies/{cid}/events", json={
            "event_type": "acquisition", "description": "Acquired by XYZ",
        })
        r = c.get(f"/api/companies/{cid}/events")
        assert r.status_code == 200
        assert len(r.get_json()) >= 1

    def test_delete_event(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/events", json={
            "event_type": "ipo", "description": "Went public",
        })
        # Get the event to find its ID
        r = c.get(f"/api/companies/{cid}/events")
        events = r.get_json()
        event_id = events[0]["id"]

        r = c.delete(f"/api/events/{event_id}")
        assert r.status_code == 200

    def test_add_event_missing_type_rejected(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.post(f"/api/companies/{cid}/events", json={
            "description": "No type given",
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Version History
# ---------------------------------------------------------------------------

class TestVersionHistory:
    """CMP-VERSIONS: Company version history and restore."""

    def test_list_versions(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        cid = api_project_with_companies["company_ids"][0]
        r = c.get(f"/api/companies/{cid}/versions")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_version_created_on_update(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cid = api_project_with_companies["company_ids"][0]

        # Update company to create a version
        c.post(f"/api/companies/{cid}", json={
            "what": "Version 2", "project_id": pid,
        })
        r = c.get(f"/api/companies/{cid}/versions")
        versions = r.get_json()
        assert len(versions) >= 1


# ---------------------------------------------------------------------------
# Trash Management
# ---------------------------------------------------------------------------

class TestTrash:
    """CMP-TRASH: Trash listing, restore, permanent delete."""

    def test_trash_empty(self, api_project):
        c = api_project["client"]
        r = c.get(f"/api/trash?project_id={api_project['id']}")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_restore_from_trash(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cid = api_project_with_companies["company_ids"][0]

        c.delete(f"/api/companies/{cid}")
        r = c.post(f"/api/companies/{cid}/restore")
        assert r.status_code == 200

        # Should appear in listing again
        r = c.get(f"/api/companies?project_id={pid}")
        ids = [co["id"] for co in r.get_json()]
        assert cid in ids

    def test_permanent_delete(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        cid = api_project_with_companies["company_ids"][0]

        c.delete(f"/api/companies/{cid}")
        r = c.delete(f"/api/companies/{cid}/permanent-delete")
        assert r.status_code == 200

        # Should not appear in trash either
        r = c.get(f"/api/trash?project_id={pid}")
        ids = [co["id"] for co in r.get_json()]
        assert cid not in ids


# ---------------------------------------------------------------------------
# Bulk Actions
# ---------------------------------------------------------------------------

class TestBulkActions:
    """CMP-BULK: Bulk operations via POST /api/companies/bulk."""

    def test_bulk_assign_category(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        ids = api_project_with_companies["company_ids"][:2]
        cat_id = api_project_with_companies["category_id"]
        r = c.post("/api/companies/bulk", json={
            "action": "assign_category",
            "company_ids": ids,
            "params": {"category_id": cat_id},
        })
        assert r.status_code == 200
        assert r.get_json()["updated"] == 2

    def test_bulk_add_tags(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        ids = api_project_with_companies["company_ids"][:2]
        r = c.post("/api/companies/bulk", json={
            "action": "add_tags",
            "company_ids": ids,
            "params": {"tags": ["bulk-tag-1", "bulk-tag-2"]},
        })
        assert r.status_code == 200

    def test_bulk_set_relationship(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        ids = api_project_with_companies["company_ids"]
        r = c.post("/api/companies/bulk", json={
            "action": "set_relationship",
            "company_ids": ids,
            "params": {"status": "watching"},
        })
        assert r.status_code == 200

    def test_bulk_delete(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        ids = api_project_with_companies["company_ids"][:2]
        r = c.post("/api/companies/bulk", json={
            "action": "delete",
            "company_ids": ids,
        })
        assert r.status_code == 200
        assert r.get_json()["updated"] == 2

    def test_bulk_no_ids_rejected(self, client):
        r = client.post("/api/companies/bulk", json={
            "action": "delete", "company_ids": [],
        })
        assert r.status_code == 400

    def test_bulk_invalid_action_rejected(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        r = c.post("/api/companies/bulk", json={
            "action": "invalid_action",
            "company_ids": api_project_with_companies["company_ids"],
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Compare & Duplicates
# ---------------------------------------------------------------------------

class TestCompare:
    """CMP-COMPARE: Company comparison via GET /api/companies/compare."""

    def test_compare_companies(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        ids = api_project_with_companies["company_ids"][:2]
        r = c.get(f"/api/companies/compare?ids={','.join(str(i) for i in ids)}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 2


class TestDuplicates:
    """CMP-DUP: Duplicate detection via GET /api/duplicates."""

    def test_duplicates_endpoint(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        pid = api_project_with_companies["project_id"]
        r = c.get(f"/api/duplicates?project_id={pid}")
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)


class TestMerge:
    """CMP-MERGE: Company merge via POST /api/companies/merge."""

    def test_merge_companies(self, api_project_with_companies):
        c = api_project_with_companies["client"]
        ids = api_project_with_companies["company_ids"]
        r = c.post("/api/companies/merge", json={
            "target_id": ids[0],
            "source_id": ids[1],
        })
        assert r.status_code == 200

    def test_merge_missing_ids_rejected(self, client):
        r = client.post("/api/companies/merge", json={"target_id": 1})
        assert r.status_code == 400
