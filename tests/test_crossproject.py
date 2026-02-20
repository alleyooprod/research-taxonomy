"""Tests for Cross-Project Intelligence API endpoints.

Covers:
- Entity overlap detection (scan, list overlaps)
- Manual entity linking (create, duplicate 409, self-link, delete)
- Linked entity retrieval with project info and attributes
- Attribute sync between linked entities
- Entity attribute diff/comparison
- Cross-project pattern analysis (multi-project, divergence, coverage)
- Cross-project insights CRUD (list, filter, dismiss, delete)
- Summary stats
- Edge cases: not-found entities, links, insights

Run: pytest tests/test_crossproject.py -v
Markers: db, api
"""
import json
import pytest

import web.blueprints.crossproject as crossproject_mod

pytestmark = [pytest.mark.db, pytest.mark.api]


# ═══════════════════════════════════════════════════════════════
# Shared Schema + Fixtures
# ═══════════════════════════════════════════════════════════════

SCHEMA = {
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
                {"name": "HQ City", "slug": "hq_city", "data_type": "text"},
                {"name": "Pricing", "slug": "pricing_model", "data_type": "text"},
                {"name": "Features", "slug": "features", "data_type": "tags"},
                {"name": "Founded", "slug": "founded_year", "data_type": "number"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture(autouse=True)
def reset_table_flag():
    """Reset the _TABLE_ENSURED flag between tests."""
    crossproject_mod._TABLE_ENSURED = False
    yield
    crossproject_mod._TABLE_ENSURED = False


def _add_attr(app, entity_id, slug, value):
    """Insert an entity attribute via raw DB connection."""
    with app.db._get_conn() as conn:
        conn.execute(
            "INSERT INTO entity_attributes "
            "(entity_id, attr_slug, value, source, confidence, captured_at) "
            "VALUES (?, ?, ?, 'manual', 1.0, datetime('now'))",
            (entity_id, slug, value),
        )


def _create_two_projects_with_entities(client):
    """Helper: create 2 projects, each with entities, return IDs."""
    db = client.db

    pid1 = db.create_project(
        name="Project Alpha",
        purpose="Alpha research",
        entity_schema=SCHEMA,
    )
    pid2 = db.create_project(
        name="Project Beta",
        purpose="Beta research",
        entity_schema=SCHEMA,
    )

    eid1 = db.create_entity(pid1, "company", "Acme Corp")
    eid2 = db.create_entity(pid2, "company", "Acme Corp")  # same name
    eid3 = db.create_entity(pid1, "company", "Zeta Inc")
    eid4 = db.create_entity(pid2, "company", "Omega Ltd")

    return {
        "pid1": pid1, "pid2": pid2,
        "eid1": eid1, "eid2": eid2,
        "eid3": eid3, "eid4": eid4,
    }


# ═══════════════════════════════════════════════════════════════
# 1. TestOverlapScan
# ═══════════════════════════════════════════════════════════════

class TestOverlapScan:
    """POST /api/cross-project/scan — auto-detect overlapping entities."""

    def test_scan_finds_matching_names(self, client, app):
        """Entities with identical names in different projects are linked."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/scan")
        assert r.status_code == 201
        data = r.get_json()
        assert data["found_count"] >= 1

        # The "Acme Corp" pair should be linked
        linked_pairs = [
            (lk["source_entity_id"], lk["target_entity_id"])
            for lk in data["links"]
        ]
        assert (ids["eid1"], ids["eid2"]) in linked_pairs or \
               (ids["eid2"], ids["eid1"]) in linked_pairs

        # All auto-created links should be auto source and same_entity type
        for lk in data["links"]:
            assert lk["source"] == "auto"
            assert lk["link_type"] == "same_entity"

    def test_scan_finds_url_match(self, client, app):
        """Entities with matching URL domains are linked even if names differ."""
        db = client.db
        pid1 = db.create_project(name="URL Proj A", purpose="A", entity_schema=SCHEMA)
        pid2 = db.create_project(name="URL Proj B", purpose="B", entity_schema=SCHEMA)

        eid1 = db.create_entity(pid1, "company", "Company X")
        eid2 = db.create_entity(pid2, "company", "Company Y")

        # Give both the same URL domain
        _add_attr(app, eid1, "url", "https://www.example.com/about")
        _add_attr(app, eid2, "url", "https://example.com/products")

        r = client.post("/api/cross-project/scan")
        assert r.status_code == 201
        data = r.get_json()
        assert data["found_count"] >= 1

        # Find the link between our two entities
        found = False
        for lk in data["links"]:
            pair = {lk["source_entity_id"], lk["target_entity_id"]}
            if pair == {eid1, eid2}:
                found = True
                assert lk["confidence"] == 0.95
                meta = lk.get("metadata", {})
                assert meta.get("match_method") == "url_domain"
        assert found, "URL-matched link not found"

    def test_scan_no_matches(self, client, app):
        """Scan with no overlapping entities returns empty."""
        db = client.db
        pid1 = db.create_project(name="Unique A", purpose="A", entity_schema=SCHEMA)
        pid2 = db.create_project(name="Unique B", purpose="B", entity_schema=SCHEMA)

        db.create_entity(pid1, "company", "Totally Unique Alpha")
        db.create_entity(pid2, "company", "Completely Different Beta")

        r = client.post("/api/cross-project/scan")
        assert r.status_code == 201
        data = r.get_json()
        assert data["found_count"] == 0
        assert data["links"] == []

    def test_scan_idempotent(self, client, app):
        """Re-scanning does not create duplicate links."""
        _create_two_projects_with_entities(client)

        r1 = client.post("/api/cross-project/scan")
        count1 = r1.get_json()["found_count"]
        assert count1 >= 1

        r2 = client.post("/api/cross-project/scan")
        count2 = r2.get_json()["found_count"]
        assert count2 == 0  # no new links on rescan

    def test_scan_single_project_no_overlap(self, client, app):
        """Entities within the same project should not be linked."""
        db = client.db
        pid = db.create_project(name="Solo", purpose="Solo", entity_schema=SCHEMA)
        db.create_entity(pid, "company", "Alpha Corp")
        db.create_entity(pid, "company", "Alpha Corp")  # same name, same project

        r = client.post("/api/cross-project/scan")
        assert r.status_code == 201
        assert r.get_json()["found_count"] == 0


# ═══════════════════════════════════════════════════════════════
# 2. TestManualLink
# ═══════════════════════════════════════════════════════════════

class TestManualLink:
    """POST /api/cross-project/link — manually link two entities."""

    def test_create_link(self, client, app):
        """Successfully create a manual entity link."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid3"],
            "target_entity_id": ids["eid4"],
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["created"] is True
        link = data["link"]
        assert link["source_entity_id"] == ids["eid3"]
        assert link["target_entity_id"] == ids["eid4"]
        assert link["link_type"] == "same_entity"
        assert link["confidence"] == 1.0
        assert link["source"] == "manual"

    def test_create_link_with_type_and_confidence(self, client, app):
        """Create a link with custom link_type and confidence."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid3"],
            "target_entity_id": ids["eid4"],
            "link_type": "related",
            "confidence": 0.75,
        })
        assert r.status_code == 201
        link = r.get_json()["link"]
        assert link["link_type"] == "related"
        assert link["confidence"] == 0.75

    def test_duplicate_link_blocked(self, client, app):
        """Creating a link that already exists returns 409."""
        ids = _create_two_projects_with_entities(client)

        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })
        assert r.status_code == 409
        assert "already exists" in r.get_json()["error"]

    def test_reverse_duplicate_blocked(self, client, app):
        """A->B link blocks B->A link too (bidirectional check)."""
        ids = _create_two_projects_with_entities(client)

        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid2"],
            "target_entity_id": ids["eid1"],
        })
        assert r.status_code == 409

    def test_self_link_blocked(self, client, app):
        """Cannot link an entity to itself."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid1"],
        })
        assert r.status_code == 400
        assert "itself" in r.get_json()["error"]

    def test_invalid_link_type(self, client, app):
        """Invalid link_type returns 400."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
            "link_type": "invalid_type",
        })
        assert r.status_code == 400
        assert "Invalid link_type" in r.get_json()["error"]

    def test_delete_link(self, client, app):
        """Delete an existing link."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })
        link_id = r.get_json()["link"]["id"]

        r = client.delete(f"/api/cross-project/link/{link_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["deleted"] is True
        assert data["id"] == link_id

    def test_missing_entity_ids(self, client, app):
        """Missing source or target entity IDs returns 400."""
        r = client.post("/api/cross-project/link", json={
            "source_entity_id": 1,
        })
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# 3. TestListOverlaps
# ═══════════════════════════════════════════════════════════════

class TestListOverlaps:
    """GET /api/cross-project/overlaps — list entity links."""

    def test_list_overlaps_empty(self, client, app):
        """Empty overlap list when no links exist."""
        r = client.get("/api/cross-project/overlaps")
        assert r.status_code == 200
        data = r.get_json()
        assert data["links"] == []
        assert data["total"] == 0

    def test_list_overlaps_with_data(self, client, app):
        """List overlaps returns created links."""
        ids = _create_two_projects_with_entities(client)
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.get("/api/cross-project/overlaps")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] == 1
        assert len(data["links"]) == 1
        link = data["links"][0]
        assert "source_entity_name" in link
        assert "target_project_name" in link

    def test_list_overlaps_filter_by_type(self, client, app):
        """Filter overlaps by link_type."""
        ids = _create_two_projects_with_entities(client)
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
            "link_type": "same_entity",
        })
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid3"],
            "target_entity_id": ids["eid4"],
            "link_type": "related",
        })

        r = client.get("/api/cross-project/overlaps?link_type=related")
        data = r.get_json()
        assert data["total"] == 1
        assert data["links"][0]["link_type"] == "related"

    def test_list_overlaps_filter_by_source(self, client, app):
        """Filter overlaps by source."""
        ids = _create_two_projects_with_entities(client)

        # Create a manual link
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.get("/api/cross-project/overlaps?source=manual")
        data = r.get_json()
        assert data["total"] == 1

        r = client.get("/api/cross-project/overlaps?source=auto")
        data = r.get_json()
        assert data["total"] == 0

    def test_list_overlaps_pagination(self, client, app):
        """Pagination with limit and offset."""
        ids = _create_two_projects_with_entities(client)
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid3"],
            "target_entity_id": ids["eid4"],
        })

        r = client.get("/api/cross-project/overlaps?limit=1&offset=0")
        data = r.get_json()
        assert len(data["links"]) == 1
        assert data["total"] == 2
        assert data["limit"] == 1
        assert data["offset"] == 0


# ═══════════════════════════════════════════════════════════════
# 4. TestLinkedEntities
# ═══════════════════════════════════════════════════════════════

class TestLinkedEntities:
    """GET /api/cross-project/entity/<id>/linked — get linked entities."""

    def test_get_linked_entities(self, client, app):
        """Returns linked entities with project info and attributes."""
        ids = _create_two_projects_with_entities(client)

        # Add attributes to entity 2
        _add_attr(app, ids["eid2"], "hq_city", "London")
        _add_attr(app, ids["eid2"], "pricing_model", "freemium")

        # Link entities
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.get(f"/api/cross-project/entity/{ids['eid1']}/linked")
        assert r.status_code == 200
        data = r.get_json()

        assert data["entity"]["id"] == ids["eid1"]
        assert len(data["linked"]) == 1

        linked = data["linked"][0]
        assert linked["entity"]["id"] == ids["eid2"]
        assert linked["project_name"] == "Project Beta"
        assert "hq_city" in linked["attrs"]
        assert linked["attrs"]["hq_city"] == "London"
        assert "link" in linked

    def test_get_linked_no_links(self, client, app):
        """Entity with no links returns empty linked list."""
        ids = _create_two_projects_with_entities(client)

        r = client.get(f"/api/cross-project/entity/{ids['eid3']}/linked")
        assert r.status_code == 200
        data = r.get_json()
        assert data["entity"]["id"] == ids["eid3"]
        assert data["linked"] == []

    def test_get_linked_bidirectional(self, client, app):
        """Linked entities appear regardless of link direction."""
        ids = _create_two_projects_with_entities(client)

        # Link eid1 -> eid2
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        # Query from the target side
        r = client.get(f"/api/cross-project/entity/{ids['eid2']}/linked")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["linked"]) == 1
        assert data["linked"][0]["entity"]["id"] == ids["eid1"]


# ═══════════════════════════════════════════════════════════════
# 5. TestAttributeSync
# ═══════════════════════════════════════════════════════════════

class TestAttributeSync:
    """POST /api/cross-project/sync — sync attributes between linked entities."""

    def test_sync_attributes(self, client, app):
        """Successfully sync attributes from source to target."""
        ids = _create_two_projects_with_entities(client)

        # Add attrs to source entity
        _add_attr(app, ids["eid1"], "hq_city", "San Francisco")
        _add_attr(app, ids["eid1"], "pricing_model", "subscription")

        # Link entities
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.post("/api/cross-project/sync", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
            "attr_slugs": ["hq_city", "pricing_model"],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["synced_count"] == 2

        synced_slugs = {s["attr_slug"] for s in data["synced"]}
        assert "hq_city" in synced_slugs
        assert "pricing_model" in synced_slugs

        # Verify the target entity now has the attributes
        r2 = client.get(f"/api/cross-project/entity/{ids['eid2']}/linked")
        # Check via diff instead — get the target entity's attrs
        r3 = client.get(
            f"/api/cross-project/entity/{ids['eid1']}/diff"
            f"?compare_to={ids['eid2']}"
        )
        diff = r3.get_json()
        # The synced attributes should now appear in 'same'
        same_slugs = {s["attr_slug"] for s in diff["diff"]["same"]}
        assert "hq_city" in same_slugs

    def test_sync_unlinked_entities_rejected(self, client, app):
        """Syncing between unlinked entities returns 400."""
        ids = _create_two_projects_with_entities(client)

        _add_attr(app, ids["eid1"], "hq_city", "Berlin")

        r = client.post("/api/cross-project/sync", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
            "attr_slugs": ["hq_city"],
        })
        assert r.status_code == 400
        assert "not linked" in r.get_json()["error"]

    def test_sync_partial_attrs(self, client, app):
        """Only attributes that exist on source are synced; missing ones skipped."""
        ids = _create_two_projects_with_entities(client)

        _add_attr(app, ids["eid1"], "hq_city", "Tokyo")

        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.post("/api/cross-project/sync", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
            "attr_slugs": ["hq_city", "nonexistent_attr"],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["synced_count"] == 1
        assert data["synced"][0]["attr_slug"] == "hq_city"

    def test_sync_empty_attr_slugs(self, client, app):
        """Empty attr_slugs list returns 400."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/sync", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
            "attr_slugs": [],
        })
        assert r.status_code == 400

    def test_sync_missing_entity_ids(self, client, app):
        """Missing entity IDs returns 400."""
        r = client.post("/api/cross-project/sync", json={
            "attr_slugs": ["hq_city"],
        })
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# 6. TestEntityDiff
# ═══════════════════════════════════════════════════════════════

class TestEntityDiff:
    """GET /api/cross-project/entity/<id>/diff — compare attributes."""

    def test_diff_with_shared_and_unique_attrs(self, client, app):
        """Diff shows same, different, only_in_a, only_in_b correctly."""
        ids = _create_two_projects_with_entities(client)

        # Entity A attributes
        _add_attr(app, ids["eid1"], "hq_city", "San Francisco")
        _add_attr(app, ids["eid1"], "pricing_model", "subscription")
        _add_attr(app, ids["eid1"], "founded_year", "2020")

        # Entity B attributes — hq_city same, pricing_model different, features unique
        _add_attr(app, ids["eid2"], "hq_city", "San Francisco")
        _add_attr(app, ids["eid2"], "pricing_model", "freemium")
        _add_attr(app, ids["eid2"], "features", "SSO,API")

        r = client.get(
            f"/api/cross-project/entity/{ids['eid1']}/diff"
            f"?compare_to={ids['eid2']}"
        )
        assert r.status_code == 200
        data = r.get_json()

        assert data["entity_a"]["id"] == ids["eid1"]
        assert data["entity_b"]["id"] == ids["eid2"]

        diff = data["diff"]

        # hq_city should be in "same"
        same_slugs = {s["attr_slug"] for s in diff["same"]}
        assert "hq_city" in same_slugs

        # pricing_model should be in "different"
        diff_slugs = {d["attr_slug"] for d in diff["different"]}
        assert "pricing_model" in diff_slugs

        # founded_year only in A
        only_a_slugs = {a["attr_slug"] for a in diff["only_in_a"]}
        assert "founded_year" in only_a_slugs

        # features only in B
        only_b_slugs = {b["attr_slug"] for b in diff["only_in_b"]}
        assert "features" in only_b_slugs

        # Summary
        summary = data["summary"]
        assert summary["shared"] >= 1
        assert summary["divergent"] >= 1
        assert summary["only_a"] >= 1
        assert summary["only_b"] >= 1
        assert summary["total_attrs"] == (
            summary["shared"] + summary["divergent"]
            + summary["only_a"] + summary["only_b"]
        )

    def test_diff_missing_compare_to(self, client, app):
        """Missing compare_to query param returns 400."""
        ids = _create_two_projects_with_entities(client)

        r = client.get(f"/api/cross-project/entity/{ids['eid1']}/diff")
        assert r.status_code == 400
        assert "compare_to" in r.get_json()["error"]

    def test_diff_no_attrs(self, client, app):
        """Diff between entities with no attributes returns empty diff."""
        ids = _create_two_projects_with_entities(client)

        r = client.get(
            f"/api/cross-project/entity/{ids['eid1']}/diff"
            f"?compare_to={ids['eid2']}"
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["diff"]["same"] == []
        assert data["diff"]["different"] == []
        assert data["diff"]["only_in_a"] == []
        assert data["diff"]["only_in_b"] == []
        assert data["summary"]["total_attrs"] == 0


# ═══════════════════════════════════════════════════════════════
# 7. TestCrossProjectAnalysis
# ═══════════════════════════════════════════════════════════════

class TestCrossProjectAnalysis:
    """POST /api/cross-project/analyse — run pattern analysis."""

    def test_analyse_no_links(self, client, app):
        """Analysis with no links returns message."""
        r = client.post("/api/cross-project/analyse")
        assert r.status_code == 200
        data = r.get_json()
        assert data["generated_count"] == 0
        assert "message" in data

    def test_analyse_with_links(self, client, app):
        """Analysis with linked entities generates insights."""
        ids = _create_two_projects_with_entities(client)

        # Add divergent attributes to trigger the divergence detector
        _add_attr(app, ids["eid1"], "pricing_model", "subscription")
        _add_attr(app, ids["eid2"], "pricing_model", "freemium")

        # Link them
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.post("/api/cross-project/analyse")
        assert r.status_code == 201
        data = r.get_json()
        assert data["generated_count"] >= 1
        assert len(data["insights"]) >= 1

        # Check insight structure
        insight = data["insights"][0]
        assert "id" in insight
        assert "insight_type" in insight
        assert "title" in insight
        assert "description" in insight
        assert "severity" in insight
        assert "is_dismissed" in insight

    def test_analyse_divergence_detected(self, client, app):
        """Divergent attributes between linked entities produce divergence insights."""
        ids = _create_two_projects_with_entities(client)

        _add_attr(app, ids["eid1"], "hq_city", "San Francisco")
        _add_attr(app, ids["eid1"], "pricing_model", "subscription")
        _add_attr(app, ids["eid2"], "hq_city", "New York")
        _add_attr(app, ids["eid2"], "pricing_model", "freemium")

        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.post("/api/cross-project/analyse")
        data = r.get_json()

        divergence_insights = [
            i for i in data["insights"] if i["insight_type"] == "divergence"
        ]
        assert len(divergence_insights) >= 1

    def test_analyse_coverage_gap_detected(self, client, app):
        """Entity with many more attributes triggers coverage_gap insight."""
        ids = _create_two_projects_with_entities(client)

        # Give eid1 many attributes, eid2 none
        for slug in ["hq_city", "pricing_model", "founded_year", "features",
                      "url"]:
            _add_attr(app, ids["eid1"], slug, f"val_{slug}")

        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.post("/api/cross-project/analyse")
        data = r.get_json()

        coverage_insights = [
            i for i in data["insights"] if i["insight_type"] == "coverage_gap"
        ]
        assert len(coverage_insights) >= 1


# ═══════════════════════════════════════════════════════════════
# 8. TestCrossProjectInsights
# ═══════════════════════════════════════════════════════════════

class TestCrossProjectInsights:
    """GET/PUT/DELETE /api/cross-project/insights — manage insights."""

    def _create_insight_via_analysis(self, client, app):
        """Helper: create linked entities with divergent data, run analysis."""
        ids = _create_two_projects_with_entities(client)
        _add_attr(app, ids["eid1"], "pricing_model", "subscription")
        _add_attr(app, ids["eid2"], "pricing_model", "freemium")

        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })

        r = client.post("/api/cross-project/analyse")
        return r.get_json()

    def test_list_insights(self, client, app):
        """List insights returns generated insights."""
        self._create_insight_via_analysis(client, app)

        r = client.get("/api/cross-project/insights")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] >= 1
        assert len(data["insights"]) >= 1
        assert "limit" in data
        assert "offset" in data

    def test_list_insights_filter_by_type(self, client, app):
        """Filter insights by insight_type."""
        self._create_insight_via_analysis(client, app)

        r = client.get("/api/cross-project/insights?insight_type=divergence")
        data = r.get_json()
        for insight in data["insights"]:
            assert insight["insight_type"] == "divergence"

    def test_list_insights_filter_by_severity(self, client, app):
        """Filter insights by severity."""
        self._create_insight_via_analysis(client, app)

        r = client.get("/api/cross-project/insights?severity=info")
        data = r.get_json()
        for insight in data["insights"]:
            assert insight["severity"] == "info"

    def test_dismiss_insight(self, client, app):
        """Dismiss an insight hides it from default listing."""
        analysis = self._create_insight_via_analysis(client, app)
        insight_id = analysis["insights"][0]["id"]

        r = client.put(f"/api/cross-project/insights/{insight_id}/dismiss")
        assert r.status_code == 200
        data = r.get_json()
        assert data["updated"] is True
        assert data["id"] == insight_id

        # Default listing should not include dismissed
        r = client.get("/api/cross-project/insights")
        ids_returned = {i["id"] for i in r.get_json()["insights"]}
        assert insight_id not in ids_returned

        # But is_dismissed=all should include it
        r = client.get("/api/cross-project/insights?is_dismissed=all")
        ids_all = {i["id"] for i in r.get_json()["insights"]}
        assert insight_id in ids_all

    def test_delete_insight(self, client, app):
        """Delete an insight permanently."""
        analysis = self._create_insight_via_analysis(client, app)
        insight_id = analysis["insights"][0]["id"]

        r = client.delete(f"/api/cross-project/insights/{insight_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["deleted"] is True
        assert data["id"] == insight_id

        # Verify it is gone
        r = client.get("/api/cross-project/insights?is_dismissed=all")
        ids_returned = {i["id"] for i in r.get_json()["insights"]}
        assert insight_id not in ids_returned


# ═══════════════════════════════════════════════════════════════
# 9. TestCrossProjectStats
# ═══════════════════════════════════════════════════════════════

class TestCrossProjectStats:
    """GET /api/cross-project/stats — summary statistics."""

    def test_stats_empty(self, client, app):
        """Stats on empty system returns zeros."""
        r = client.get("/api/cross-project/stats")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_links"] == 0
        assert data["overlapping_entities"] == 0
        assert data["projects_with_overlaps"] == 0
        assert data["total_insights"] == 0
        assert data["undismissed_insights"] == 0
        assert data["links_by_type"] == {}
        assert data["links_by_source"] == {}
        assert data["insights_by_type"] == {}
        assert data["insights_by_severity"] == {}

    def test_stats_with_data(self, client, app):
        """Stats reflect created links and insights."""
        ids = _create_two_projects_with_entities(client)

        # Create a manual link
        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
            "link_type": "same_entity",
        })

        # Add divergent data and run analysis
        _add_attr(app, ids["eid1"], "pricing_model", "subscription")
        _add_attr(app, ids["eid2"], "pricing_model", "freemium")

        client.post("/api/cross-project/analyse")

        r = client.get("/api/cross-project/stats")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_links"] == 1
        assert data["links_by_type"].get("same_entity", 0) == 1
        assert data["links_by_source"].get("manual", 0) == 1
        assert data["overlapping_entities"] == 2
        assert data["projects_with_overlaps"] == 2
        assert data["total_insights"] >= 1
        assert data["undismissed_insights"] >= 1

    def test_stats_dismissed_insights(self, client, app):
        """Dismissed insights are counted separately in stats."""
        ids = _create_two_projects_with_entities(client)

        _add_attr(app, ids["eid1"], "pricing_model", "subscription")
        _add_attr(app, ids["eid2"], "pricing_model", "freemium")

        client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": ids["eid2"],
        })
        analysis = client.post("/api/cross-project/analyse").get_json()

        if analysis["generated_count"] > 0:
            insight_id = analysis["insights"][0]["id"]
            client.put(f"/api/cross-project/insights/{insight_id}/dismiss")

        r = client.get("/api/cross-project/stats")
        data = r.get_json()
        assert data["total_insights"] >= 1
        assert data["undismissed_insights"] < data["total_insights"]


# ═══════════════════════════════════════════════════════════════
# 10. TestCrossProjectEdgeCases
# ═══════════════════════════════════════════════════════════════

class TestCrossProjectEdgeCases:
    """Edge cases: not-found resources, boundary conditions."""

    def test_link_nonexistent_source_entity(self, client, app):
        """Linking from a non-existent entity returns 404."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": 99999,
            "target_entity_id": ids["eid1"],
        })
        assert r.status_code == 404
        assert "not found" in r.get_json()["error"]

    def test_link_nonexistent_target_entity(self, client, app):
        """Linking to a non-existent entity returns 404."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/link", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": 99999,
        })
        assert r.status_code == 404
        assert "not found" in r.get_json()["error"]

    def test_delete_nonexistent_link(self, client, app):
        """Deleting a non-existent link returns 404."""
        r = client.delete("/api/cross-project/link/99999")
        assert r.status_code == 404

    def test_get_linked_nonexistent_entity(self, client, app):
        """Getting linked entities for non-existent entity returns 404."""
        r = client.get("/api/cross-project/entity/99999/linked")
        assert r.status_code == 404

    def test_diff_nonexistent_entity_a(self, client, app):
        """Diff with non-existent entity A returns 404."""
        ids = _create_two_projects_with_entities(client)

        r = client.get(
            f"/api/cross-project/entity/99999/diff"
            f"?compare_to={ids['eid1']}"
        )
        assert r.status_code == 404

    def test_diff_nonexistent_entity_b(self, client, app):
        """Diff with non-existent compare_to entity returns 404."""
        ids = _create_two_projects_with_entities(client)

        r = client.get(
            f"/api/cross-project/entity/{ids['eid1']}/diff"
            f"?compare_to=99999"
        )
        assert r.status_code == 404

    def test_dismiss_nonexistent_insight(self, client, app):
        """Dismissing a non-existent insight returns 404."""
        r = client.put("/api/cross-project/insights/99999/dismiss")
        assert r.status_code == 404

    def test_delete_nonexistent_insight(self, client, app):
        """Deleting a non-existent insight returns 404."""
        r = client.delete("/api/cross-project/insights/99999")
        assert r.status_code == 404

    def test_sync_nonexistent_source(self, client, app):
        """Sync from non-existent source entity returns 404."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/sync", json={
            "source_entity_id": 99999,
            "target_entity_id": ids["eid1"],
            "attr_slugs": ["hq_city"],
        })
        assert r.status_code == 404

    def test_sync_nonexistent_target(self, client, app):
        """Sync to non-existent target entity returns 404."""
        ids = _create_two_projects_with_entities(client)

        r = client.post("/api/cross-project/sync", json={
            "source_entity_id": ids["eid1"],
            "target_entity_id": 99999,
            "attr_slugs": ["hq_city"],
        })
        assert r.status_code == 404
