"""Tests for Feature Standardisation — API layer.

Covers:
- GET/POST /api/features (list/create canonical features)
- GET/PUT/DELETE /api/features/<id> (CRUD)
- POST /api/features/merge (merge features)
- GET /api/features/categories (list categories)
- POST /api/features/<id>/mappings (add mapping)
- DELETE /api/features/mappings/<id> (remove mapping)
- POST /api/features/resolve (resolve raw value)
- GET /api/features/unmapped (find unmapped values)
- GET /api/features/stats (vocabulary stats)
- Validation: missing fields, duplicates, not found

Run: pytest tests/test_api_features.py -v
Markers: api, extraction
"""
import pytest
from unittest.mock import patch

pytestmark = [pytest.mark.api, pytest.mark.extraction, pytest.mark.features]


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

FEATURE_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Product",
            "slug": "product",
            "description": "An insurance product",
            "icon": "package",
            "parent_type": None,
            "attributes": [
                {"name": "Features", "slug": "features", "data_type": "tags"},
                {"name": "Description", "slug": "description", "data_type": "text"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture
def feature_project(client):
    """Create a project for feature testing."""
    pid = client.db.create_project(
        name="Feature API Test",
        purpose="Testing features API",
        entity_schema=FEATURE_SCHEMA,
    )
    return {"client": client, "project_id": pid}


@pytest.fixture
def feature_project_with_data(feature_project):
    """Project with canonical features already created."""
    c = feature_project["client"]
    pid = feature_project["project_id"]

    f1 = c.db.create_canonical_feature(pid, "features", "Mental Health Support",
                                        description="MH cover", category="Wellbeing")
    f2 = c.db.create_canonical_feature(pid, "features", "Dental Cover",
                                        category="Core")
    f3 = c.db.create_canonical_feature(pid, "features", "Virtual GP",
                                        category="Digital")

    c.db.add_feature_mapping(f1, "Mental Health Support")
    c.db.add_feature_mapping(f1, "mental health cover")
    c.db.add_feature_mapping(f2, "Dental Cover")
    c.db.add_feature_mapping(f3, "Virtual GP")

    return {
        **feature_project,
        "feature_ids": [f1, f2, f3],
    }


# ═══════════════════════════════════════════════════════════════
# List + Create
# ═══════════════════════════════════════════════════════════════

class TestFeatureListCreate:
    """FEAT-API-LC: List and create canonical features."""

    def test_list_features(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.get(f"/api/features?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 3

    def test_list_features_by_category(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.get(f"/api/features?project_id={pid}&category=Wellbeing")
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["canonical_name"] == "Mental Health Support"

    def test_list_features_search(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.get(f"/api/features?project_id={pid}&search=Dental")
        data = r.get_json()
        assert len(data) == 1

    def test_list_requires_project_id(self, feature_project):
        c = feature_project["client"]
        r = c.get("/api/features")
        assert r.status_code == 400

    def test_create_feature(self, feature_project):
        c = feature_project["client"]
        pid = feature_project["project_id"]
        r = c.post("/api/features", json={
            "project_id": pid,
            "attr_slug": "features",
            "canonical_name": "Hospital Cover",
            "description": "Inpatient cover",
            "category": "Core",
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["canonical_name"] == "Hospital Cover"
        assert data["category"] == "Core"
        # Auto-mapping created
        assert len(data["mappings"]) >= 1

    def test_create_with_initial_mappings(self, feature_project):
        c = feature_project["client"]
        pid = feature_project["project_id"]
        r = c.post("/api/features", json={
            "project_id": pid,
            "attr_slug": "features",
            "canonical_name": "Physiotherapy",
            "mappings": ["physio", "physical therapy", "PT"],
        })
        assert r.status_code == 201
        data = r.get_json()
        assert len(data["mappings"]) == 4  # canonical name + 3

    def test_create_duplicate_returns_409(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.post("/api/features", json={
            "project_id": pid,
            "attr_slug": "features",
            "canonical_name": "Mental Health Support",
        })
        assert r.status_code == 409

    def test_create_requires_fields(self, feature_project):
        c = feature_project["client"]
        r = c.post("/api/features", json={"project_id": 1})
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# Get / Update / Delete
# ═══════════════════════════════════════════════════════════════

class TestFeatureCRUD:
    """FEAT-API-CRUD: Get, update, delete canonical features."""

    def test_get_feature(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        fid = feature_project_with_data["feature_ids"][0]
        r = c.get(f"/api/features/{fid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["canonical_name"] == "Mental Health Support"
        assert "mappings" in data

    def test_get_nonexistent_feature(self, feature_project):
        c = feature_project["client"]
        r = c.get("/api/features/99999")
        assert r.status_code == 404

    def test_update_feature(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        fid = feature_project_with_data["feature_ids"][0]
        r = c.put(f"/api/features/{fid}", json={
            "canonical_name": "Mental Health Cover",
            "category": "Health",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["canonical_name"] == "Mental Health Cover"
        assert data["category"] == "Health"

    def test_delete_feature(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        fid = feature_project_with_data["feature_ids"][0]
        r = c.delete(f"/api/features/{fid}")
        assert r.status_code == 200
        # Verify deleted
        r = c.get(f"/api/features/{fid}")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Merge
# ═══════════════════════════════════════════════════════════════

class TestFeatureMerge:
    """FEAT-API-MERGE: Merge features."""

    def test_merge_features(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        fids = feature_project_with_data["feature_ids"]
        r = c.post("/api/features/merge", json={
            "target_id": fids[0],
            "source_ids": [fids[2]],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "merged"
        assert data["mappings_moved"] > 0
        # Source deleted
        r = c.get(f"/api/features/{fids[2]}")
        assert r.status_code == 404

    def test_merge_requires_fields(self, feature_project):
        c = feature_project["client"]
        r = c.post("/api/features/merge", json={})
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# Mappings
# ═══════════════════════════════════════════════════════════════

class TestFeatureMappings:
    """FEAT-API-MAP: Feature mapping CRUD."""

    def test_add_mapping(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        fid = feature_project_with_data["feature_ids"][1]
        r = c.post(f"/api/features/{fid}/mappings", json={
            "raw_value": "dental care",
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["raw_value"] == "dental care"

    def test_add_duplicate_mapping_409(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        fid = feature_project_with_data["feature_ids"][1]
        r = c.post(f"/api/features/{fid}/mappings", json={
            "raw_value": "Dental Cover",
        })
        assert r.status_code == 409

    def test_add_mapping_to_nonexistent_feature(self, feature_project):
        c = feature_project["client"]
        r = c.post("/api/features/99999/mappings", json={"raw_value": "test"})
        assert r.status_code == 404

    def test_remove_mapping(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        fid = feature_project_with_data["feature_ids"][0]
        feature = c.db.get_canonical_feature(fid)
        mid = feature["mappings"][0]["id"]
        r = c.delete(f"/api/features/mappings/{mid}")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# Resolve
# ═══════════════════════════════════════════════════════════════

class TestFeatureResolve:
    """FEAT-API-RESOLVE: Value resolution."""

    def test_resolve_known_value(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.post("/api/features/resolve", json={
            "project_id": pid,
            "attr_slug": "features",
            "raw_value": "mental health cover",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["matched"] is True
        assert data["canonical"]["canonical_name"] == "Mental Health Support"

    def test_resolve_unknown_value(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.post("/api/features/resolve", json={
            "project_id": pid,
            "attr_slug": "features",
            "raw_value": "unknown thing",
        })
        data = r.get_json()
        assert data["matched"] is False

    def test_resolve_requires_fields(self, feature_project):
        c = feature_project["client"]
        r = c.post("/api/features/resolve", json={})
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# Unmapped Values
# ═══════════════════════════════════════════════════════════════

class TestUnmappedAPI:
    """FEAT-API-UNMAP: Unmapped values endpoint."""

    def test_unmapped_requires_fields(self, feature_project):
        c = feature_project["client"]
        r = c.get("/api/features/unmapped")
        assert r.status_code == 400
        r = c.get(f"/api/features/unmapped?project_id={feature_project['project_id']}")
        assert r.status_code == 400

    def test_unmapped_returns_list(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.get(f"/api/features/unmapped?project_id={pid}&attr_slug=features")
        assert r.status_code == 200
        data = r.get_json()
        assert "unmapped" in data
        assert "count" in data


# ═══════════════════════════════════════════════════════════════
# Stats + Categories
# ═══════════════════════════════════════════════════════════════

class TestStatsAndCategories:
    """FEAT-API-MISC: Stats and categories endpoints."""

    def test_stats(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.get(f"/api/features/stats?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["feature_count"] == 3

    def test_categories(self, feature_project_with_data):
        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.get(f"/api/features/categories?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert set(data) == {"Core", "Digital", "Wellbeing"}

    def test_stats_requires_project_id(self, feature_project):
        c = feature_project["client"]
        r = c.get("/api/features/stats")
        assert r.status_code == 400

    def test_suggest_requires_fields(self, feature_project):
        c = feature_project["client"]
        r = c.post("/api/features/suggest", json={})
        assert r.status_code == 400

    @patch("core.llm.run_cli")
    def test_suggest_canonical_names(self, mock_llm, feature_project_with_data):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.002,
            "is_error": False,
            "structured_output": {
                "suggestions": [
                    {"raw_value": "physio", "canonical_name": "Physiotherapy", "is_new": True},
                    {"raw_value": "mh support", "canonical_name": "Mental Health Support", "is_new": False},
                ],
            },
        }

        c = feature_project_with_data["client"]
        pid = feature_project_with_data["project_id"]
        r = c.post("/api/features/suggest", json={
            "project_id": pid,
            "attr_slug": "features",
            "raw_values": ["physio", "mh support"],
        })
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["suggestions"]) == 2
        assert data["suggestions"][0]["canonical_name"] == "Physiotherapy"
