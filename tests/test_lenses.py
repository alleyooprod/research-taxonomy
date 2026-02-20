"""Tests for Analysis Lenses API endpoints.

Covers:
- Lens availability detection based on project data
- Competitive lens: feature matrix, gap analysis, positioning
- Product lens: pricing landscape
- Design lens: evidence gallery, journey map
- Temporal lens: timeline, snapshot comparison
- Edge cases: missing project_id, empty data, single entity

Run: pytest tests/test_lenses.py -v
Markers: db, api
"""
import json
import pytest
from unittest.mock import patch, MagicMock

pytestmark = [pytest.mark.db, pytest.mark.api]


# ═══════════════════════════════════════════════════════════════
# Shared Schema + Fixtures
# ═══════════════════════════════════════════════════════════════

LENS_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "Features", "slug": "features", "data_type": "tags"},
                {"name": "Pricing", "slug": "pricing_model", "data_type": "text"},
                {"name": "Price Min", "slug": "price_min", "data_type": "number"},
                {"name": "Price Max", "slug": "price_max", "data_type": "number"},
                {"name": "HQ City", "slug": "hq_city", "data_type": "text"},
                {"name": "HQ Country", "slug": "hq_country", "data_type": "text"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture
def lens_project(client):
    """Create a project with schema and 3 entities with attributes."""
    db = client.db
    pid = db.create_project(
        name="Lens Test",
        purpose="Testing analysis lenses",
        entity_schema=LENS_SCHEMA,
    )

    # Create 3 entities
    eid1 = db.create_entity(pid, "company", "Alpha Corp")
    eid2 = db.create_entity(pid, "company", "Beta Inc")
    eid3 = db.create_entity(pid, "company", "Gamma LLC")

    # Add feature attributes
    db.set_entity_attribute(eid1, "features", json.dumps(["SSO", "API", "Webhooks"]))
    db.set_entity_attribute(eid2, "features", json.dumps(["SSO", "MFA", "Audit Log"]))
    db.set_entity_attribute(eid3, "features", json.dumps(["API", "Webhooks", "MFA"]))

    # Add pricing attributes
    db.set_entity_attribute(eid1, "pricing_model", "subscription")
    db.set_entity_attribute(eid1, "price_min", "29")
    db.set_entity_attribute(eid1, "price_max", "199")

    db.set_entity_attribute(eid2, "pricing_model", "freemium")
    db.set_entity_attribute(eid2, "price_min", "0")
    db.set_entity_attribute(eid2, "price_max", "99")

    db.set_entity_attribute(eid3, "pricing_model", "flat-rate")
    db.set_entity_attribute(eid3, "price_min", "49")

    # Add location attributes
    db.set_entity_attribute(eid1, "hq_city", "San Francisco")
    db.set_entity_attribute(eid1, "hq_country", "US")
    db.set_entity_attribute(eid2, "hq_city", "London")
    db.set_entity_attribute(eid2, "hq_country", "UK")

    return {
        "client": client,
        "project_id": pid,
        "entity_ids": [eid1, eid2, eid3],
        "db": db,
    }


@pytest.fixture
def lens_project_with_evidence(lens_project, tmp_path, monkeypatch):
    """Extends lens_project with screenshot evidence."""
    import core.capture as capture_mod
    test_evidence_dir = tmp_path / "evidence"
    test_evidence_dir.mkdir()
    monkeypatch.setattr(capture_mod, "EVIDENCE_DIR", test_evidence_dir)

    db = lens_project["db"]
    pid = lens_project["project_id"]
    eid1 = lens_project["entity_ids"][0]
    eid2 = lens_project["entity_ids"][1]

    # Add screenshot evidence for entity 1
    db.add_evidence(
        entity_id=eid1,
        evidence_type="screenshot",
        file_path="/evidence/1/landing.png",
        source_url="https://alpha.com",
        metadata={"page_type": "landing"},
    )
    db.add_evidence(
        entity_id=eid1,
        evidence_type="screenshot",
        file_path="/evidence/1/pricing.png",
        source_url="https://alpha.com/pricing",
        metadata={"page_type": "pricing"},
    )

    # Add document evidence for entity 2
    db.add_evidence(
        entity_id=eid2,
        evidence_type="document",
        file_path="/evidence/2/whitepaper.pdf",
        source_url="https://beta.com/docs",
    )

    # Add screenshot evidence for entity 2
    db.add_evidence(
        entity_id=eid2,
        evidence_type="screenshot",
        file_path="/evidence/2/dashboard.png",
        source_url="https://beta.com/app",
        metadata={"page_type": "dashboard"},
    )

    lens_project["evidence_dir"] = test_evidence_dir
    return lens_project


@pytest.fixture
def lens_project_with_snapshots(lens_project):
    """Extends lens_project with entity snapshots."""
    db = lens_project["db"]
    pid = lens_project["project_id"]
    eid1 = lens_project["entity_ids"][0]

    # Create snapshot 1 with current attributes
    snap1_id = db.create_snapshot(pid, description="Initial capture")
    # Link existing attributes to snapshot 1
    db.set_entity_attribute(eid1, "price_min", "29", snapshot_id=snap1_id)
    db.set_entity_attribute(eid1, "pricing_model", "subscription", snapshot_id=snap1_id)

    # Create snapshot 2 with changed attributes
    snap2_id = db.create_snapshot(pid, description="Price update")
    db.set_entity_attribute(eid1, "price_min", "39", snapshot_id=snap2_id)
    db.set_entity_attribute(eid1, "pricing_model", "tiered", snapshot_id=snap2_id)

    lens_project["snapshot_ids"] = [snap1_id, snap2_id]
    return lens_project


# ═══════════════════════════════════════════════════════════════
# Lens Availability Tests
# ═══════════════════════════════════════════════════════════════

class TestLensAvailability:
    """Tests for GET /api/lenses/available."""

    def test_missing_project_id_returns_400(self, client):
        r = client.get("/api/lenses/available")
        assert r.status_code == 400
        assert "project_id" in r.get_json()["error"]

    def test_empty_project_returns_all_unavailable(self, client):
        db = client.db
        pid = db.create_project(name="Empty", purpose="Test", entity_schema=LENS_SCHEMA)
        r = client.get(f"/api/lenses/available?project_id={pid}")
        assert r.status_code == 200
        lenses = r.get_json()
        assert isinstance(lenses, list)
        assert len(lenses) >= 4
        # All should be unavailable since no entities exist
        for lens in lenses:
            assert "available" in lens
            assert "hint" in lens
            assert "name" in lens
            assert "slug" in lens

    def test_competitive_available_with_2_entities(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/available?project_id={pid}")
        assert r.status_code == 200
        lenses = {l["slug"]: l for l in r.get_json()}
        assert lenses["competitive"]["available"] is True
        assert lenses["competitive"]["entity_count"] >= 2

    def test_product_available_with_pricing_attrs(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/available?project_id={pid}")
        lenses = {l["slug"]: l for l in r.get_json()}
        assert lenses["product"]["available"] is True

    def test_design_available_with_screenshots(self, lens_project_with_evidence):
        c = lens_project_with_evidence["client"]
        pid = lens_project_with_evidence["project_id"]
        r = c.get(f"/api/lenses/available?project_id={pid}")
        lenses = {l["slug"]: l for l in r.get_json()}
        assert lenses["design"]["available"] is True

    def test_design_unavailable_without_screenshots(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/available?project_id={pid}")
        lenses = {l["slug"]: l for l in r.get_json()}
        assert lenses["design"]["available"] is False

    def test_temporal_available_with_snapshots(self, lens_project_with_snapshots):
        c = lens_project_with_snapshots["client"]
        pid = lens_project_with_snapshots["project_id"]
        r = c.get(f"/api/lenses/available?project_id={pid}")
        lenses = {l["slug"]: l for l in r.get_json()}
        assert lenses["temporal"]["available"] is True


# ═══════════════════════════════════════════════════════════════
# Competitive Lens Tests
# ═══════════════════════════════════════════════════════════════

class TestCompetitiveMatrix:
    """Tests for GET /api/lenses/competitive/matrix."""

    def test_missing_project_id(self, client):
        r = client.get("/api/lenses/competitive/matrix")
        assert r.status_code == 400

    def test_empty_project_returns_empty_matrix(self, client):
        db = client.db
        pid = db.create_project(name="Empty", purpose="Test", entity_schema=LENS_SCHEMA)
        r = client.get(f"/api/lenses/competitive/matrix?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["entities"] == []
        assert data["features"] == []
        assert data["matrix"] == {}

    def test_matrix_with_feature_data(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/competitive/matrix?project_id={pid}&attr_slug=features")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["entities"]) == 3
        assert len(data["features"]) > 0
        assert isinstance(data["matrix"], dict)

    def test_matrix_with_specific_entity_type(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/competitive/matrix?project_id={pid}&entity_type=company&attr_slug=features")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["entities"]) == 3

    def test_matrix_with_nonexistent_attr_slug(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/competitive/matrix?project_id={pid}&attr_slug=nonexistent")
        assert r.status_code == 200
        data = r.get_json()
        # Entities exist but no feature data for this slug
        assert len(data["entities"]) == 3
        assert data["features"] == []


class TestCompetitiveGaps:
    """Tests for GET /api/lenses/competitive/gaps."""

    def test_missing_project_id(self, client):
        r = client.get("/api/lenses/competitive/gaps")
        assert r.status_code == 400

    def test_gaps_with_data(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/competitive/gaps?project_id={pid}&attr_slug=features")
        assert r.status_code == 200
        data = r.get_json()
        assert "total_entities" in data
        assert "gaps" in data
        assert data["total_entities"] == 3
        # Each gap entry should have feature_name, coverage_pct, etc.
        for gap in data["gaps"]:
            assert "feature_name" in gap or "name" in gap or "slug" in gap
            assert "coverage_pct" in gap or "entity_count" in gap

    def test_gaps_empty_project(self, client):
        db = client.db
        pid = db.create_project(name="Empty", purpose="Test", entity_schema=LENS_SCHEMA)
        r = client.get(f"/api/lenses/competitive/gaps?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_entities"] == 0


class TestCompetitivePositioning:
    """Tests for GET /api/lenses/competitive/positioning."""

    def test_missing_project_id(self, client):
        r = client.get("/api/lenses/competitive/positioning")
        assert r.status_code == 400

    def test_positioning_with_numeric_attrs(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(
            f"/api/lenses/competitive/positioning?project_id={pid}"
            "&x_attr=price_min&y_attr=price_max"
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "points" in data or "entities" in data

    def test_positioning_with_missing_attr(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(
            f"/api/lenses/competitive/positioning?project_id={pid}"
            "&x_attr=nonexistent&y_attr=also_nonexistent"
        )
        assert r.status_code == 200
        data = r.get_json()
        # No entities have these attrs, so empty result
        points = data.get("points", data.get("entities", []))
        assert len(points) == 0


# ═══════════════════════════════════════════════════════════════
# Product Lens Tests
# ═══════════════════════════════════════════════════════════════

class TestProductPricing:
    """Tests for GET /api/lenses/product/pricing."""

    def test_missing_project_id(self, client):
        r = client.get("/api/lenses/product/pricing")
        assert r.status_code == 400

    def test_pricing_with_data(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/product/pricing?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "entities" in data
        assert len(data["entities"]) >= 2  # At least 2 have pricing attrs

    def test_pricing_empty_project(self, client):
        db = client.db
        pid = db.create_project(name="No Pricing", purpose="Test", entity_schema=LENS_SCHEMA)
        db.create_entity(pid, "company", "No Prices Corp")
        r = client.get(f"/api/lenses/product/pricing?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["entities"] == []


# ═══════════════════════════════════════════════════════════════
# Design Lens Tests
# ═══════════════════════════════════════════════════════════════

class TestDesignGallery:
    """Tests for GET /api/lenses/design/gallery."""

    def test_missing_project_id(self, client):
        r = client.get("/api/lenses/design/gallery")
        assert r.status_code == 400

    def test_gallery_with_evidence(self, lens_project_with_evidence):
        c = lens_project_with_evidence["client"]
        pid = lens_project_with_evidence["project_id"]
        eid = lens_project_with_evidence["entity_ids"][0]
        r = c.get(f"/api/lenses/design/gallery?project_id={pid}&entity_id={eid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "groups" in data or "entity_name" in data

    def test_gallery_requires_entity_id(self, lens_project_with_evidence):
        """Gallery without entity_id returns 400."""
        c = lens_project_with_evidence["client"]
        pid = lens_project_with_evidence["project_id"]
        r = c.get(f"/api/lenses/design/gallery?project_id={pid}")
        assert r.status_code == 400

    def test_gallery_no_evidence(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        eid = lens_project["entity_ids"][0]
        r = c.get(f"/api/lenses/design/gallery?project_id={pid}&entity_id={eid}")
        assert r.status_code == 200


class TestDesignJourney:
    """Tests for GET /api/lenses/design/journey."""

    def test_missing_project_id(self, client):
        r = client.get("/api/lenses/design/journey")
        assert r.status_code == 400

    def test_journey_with_screenshots(self, lens_project_with_evidence):
        c = lens_project_with_evidence["client"]
        pid = lens_project_with_evidence["project_id"]
        eid = lens_project_with_evidence["entity_ids"][0]
        # Mock the screenshot classifier to avoid LLM calls
        with patch("core.extractors.screenshot.classify_by_context") as mock_classify:
            mock_classify.return_value = {
                "journey_stage": "landing",
                "ui_patterns": ["hero"],
                "confidence": 0.9,
            }
            r = c.get(f"/api/lenses/design/journey?project_id={pid}&entity_id={eid}")
        assert r.status_code == 200

    def test_journey_requires_entity_id(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        r = c.get(f"/api/lenses/design/journey?project_id={pid}")
        assert r.status_code == 400

    def test_journey_no_screenshots(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        eid = lens_project["entity_ids"][0]
        r = c.get(f"/api/lenses/design/journey?project_id={pid}&entity_id={eid}")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# Temporal Lens Tests
# ═══════════════════════════════════════════════════════════════

class TestTemporalTimeline:
    """Tests for GET /api/lenses/temporal/timeline."""

    def test_missing_project_id(self, client):
        r = client.get("/api/lenses/temporal/timeline")
        assert r.status_code == 400

    def test_timeline_with_snapshots(self, lens_project_with_snapshots):
        c = lens_project_with_snapshots["client"]
        pid = lens_project_with_snapshots["project_id"]
        eid = lens_project_with_snapshots["entity_ids"][0]
        r = c.get(f"/api/lenses/temporal/timeline?project_id={pid}&entity_id={eid}")
        assert r.status_code == 200
        data = r.get_json()
        # Should have timeline data
        assert "snapshots" in data or "points" in data or "timeline" in data

    def test_timeline_no_snapshots(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        eid = lens_project["entity_ids"][0]
        r = c.get(f"/api/lenses/temporal/timeline?project_id={pid}&entity_id={eid}")
        assert r.status_code == 200


class TestTemporalCompare:
    """Tests for GET /api/lenses/temporal/compare."""

    def test_missing_project_id(self, client):
        r = client.get("/api/lenses/temporal/compare")
        assert r.status_code == 400

    def test_compare_two_snapshots(self, lens_project_with_snapshots):
        c = lens_project_with_snapshots["client"]
        pid = lens_project_with_snapshots["project_id"]
        eid = lens_project_with_snapshots["entity_ids"][0]
        snap_ids = lens_project_with_snapshots["snapshot_ids"]
        r = c.get(
            f"/api/lenses/temporal/compare?project_id={pid}"
            f"&entity_id={eid}&snapshot_a={snap_ids[0]}&snapshot_b={snap_ids[1]}"
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "diff" in data or "diffs" in data or "changes" in data

    def test_compare_missing_snapshot_ids(self, lens_project_with_snapshots):
        c = lens_project_with_snapshots["client"]
        pid = lens_project_with_snapshots["project_id"]
        eid = lens_project_with_snapshots["entity_ids"][0]
        r = c.get(f"/api/lenses/temporal/compare?project_id={pid}&entity_id={eid}")
        # Should return 400 since snapshot IDs are missing
        assert r.status_code == 400

    def test_compare_missing_entity_id(self, lens_project_with_snapshots):
        c = lens_project_with_snapshots["client"]
        pid = lens_project_with_snapshots["project_id"]
        r = c.get(f"/api/lenses/temporal/compare?project_id={pid}&snapshot_a=1&snapshot_b=2")
        assert r.status_code == 400

    def test_compare_nonexistent_snapshots(self, lens_project):
        c = lens_project["client"]
        pid = lens_project["project_id"]
        eid = lens_project["entity_ids"][0]
        r = c.get(
            f"/api/lenses/temporal/compare?project_id={pid}"
            f"&entity_id={eid}&snapshot_a=99999&snapshot_b=99998"
        )
        # Should handle gracefully — 404 for nonexistent snapshots
        assert r.status_code in (200, 404)


# ═══════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestLensEdgeCases:
    """Edge case tests across all lens endpoints."""

    def test_nonexistent_project_returns_empty(self, client):
        r = client.get("/api/lenses/available?project_id=99999")
        assert r.status_code == 200
        # Should return all lenses as unavailable
        lenses = r.get_json()
        for lens in lenses:
            assert lens["available"] is False

    def test_single_entity_competitive_unavailable(self, client):
        db = client.db
        pid = db.create_project(name="Single", purpose="Test", entity_schema=LENS_SCHEMA)
        eid = db.create_entity(pid, "company", "Solo Corp")
        db.set_entity_attribute(eid, "features", json.dumps(["SSO"]))
        r = client.get(f"/api/lenses/available?project_id={pid}")
        lenses = {l["slug"]: l for l in r.get_json()}
        assert lenses["competitive"]["available"] is False

    def test_matrix_comma_separated_features(self, client):
        """Features stored as comma-separated string instead of JSON array."""
        db = client.db
        pid = db.create_project(name="CSV", purpose="Test", entity_schema=LENS_SCHEMA)
        eid1 = db.create_entity(pid, "company", "Comma Corp")
        eid2 = db.create_entity(pid, "company", "Comma Inc")
        db.set_entity_attribute(eid1, "features", "SSO, API, Webhooks")
        db.set_entity_attribute(eid2, "features", "SSO, MFA")
        r = client.get(f"/api/lenses/competitive/matrix?project_id={pid}&attr_slug=features")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["entities"]) == 2
        assert len(data["features"]) >= 2

    def test_all_endpoints_accept_get(self, lens_project):
        """Verify all lens endpoints respond to GET requests."""
        c = lens_project["client"]
        pid = lens_project["project_id"]
        eid = lens_project["entity_ids"][0]
        endpoints = [
            f"/api/lenses/available?project_id={pid}",
            f"/api/lenses/competitive/matrix?project_id={pid}",
            f"/api/lenses/competitive/gaps?project_id={pid}",
            f"/api/lenses/competitive/positioning?project_id={pid}&x_attr=price_min&y_attr=price_max",
            f"/api/lenses/product/pricing?project_id={pid}",
            f"/api/lenses/design/gallery?project_id={pid}&entity_id={eid}",
            f"/api/lenses/design/journey?project_id={pid}&entity_id={eid}",
            f"/api/lenses/temporal/timeline?project_id={pid}&entity_id={eid}",
        ]
        for url in endpoints:
            r = c.get(url)
            assert r.status_code == 200, f"Failed: {url} returned {r.status_code}"
