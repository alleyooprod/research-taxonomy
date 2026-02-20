"""Tests for Feature Standardisation — DB layer.

Covers:
- Canonical feature CRUD (create, get, list, update, delete)
- Feature mappings (add, remove, list)
- Merge features (move mappings, delete sources)
- Resolve raw values (exact, case-insensitive, canonical name match)
- Unmapped values detection
- Vocabulary statistics
- Categories listing

Run: pytest tests/test_features.py -v
Markers: db, extraction
"""
import pytest

pytestmark = [pytest.mark.db, pytest.mark.extraction, pytest.mark.features]


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
                {"name": "Cover Type", "slug": "cover_type", "data_type": "text"},
                {"name": "Description", "slug": "description", "data_type": "text"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture
def feature_db(tmp_path):
    """Database with project for feature standardisation testing."""
    from storage.db import Database
    db = Database(db_path=tmp_path / "test.db")

    pid = db.create_project(
        name="Feature Test Project",
        purpose="Testing canonical features",
        entity_schema=FEATURE_SCHEMA,
    )

    return {"db": db, "project_id": pid}


@pytest.fixture
def feature_db_with_data(feature_db):
    """DB with some canonical features and mappings already created."""
    db = feature_db["db"]
    pid = feature_db["project_id"]

    f1 = db.create_canonical_feature(pid, "features", "Mental Health Support",
                                      description="Cover for mental health", category="Wellbeing")
    f2 = db.create_canonical_feature(pid, "features", "Dental Cover",
                                      description="Dental treatment cover", category="Core")
    f3 = db.create_canonical_feature(pid, "features", "Virtual GP",
                                      description="Remote doctor consultations", category="Digital")

    # Add mappings
    db.add_feature_mapping(f1, "Mental Health Support")
    db.add_feature_mapping(f1, "mental health cover")
    db.add_feature_mapping(f1, "MH support")
    db.add_feature_mapping(f2, "Dental Cover")
    db.add_feature_mapping(f2, "dental treatment")
    db.add_feature_mapping(f3, "Virtual GP")
    db.add_feature_mapping(f3, "online doctor")

    return {
        **feature_db,
        "feature_ids": [f1, f2, f3],
    }


# ═══════════════════════════════════════════════════════════════
# Canonical Feature CRUD
# ═══════════════════════════════════════════════════════════════

class TestCanonicalFeatureCRUD:
    """FEAT-DB-CRUD: Canonical feature CRUD tests."""

    def test_create_feature(self, feature_db):
        db = feature_db["db"]
        pid = feature_db["project_id"]
        fid = db.create_canonical_feature(pid, "features", "Hospital Cover",
                                           description="Inpatient hospital cover")
        assert fid is not None
        assert fid > 0

    def test_create_duplicate_returns_none(self, feature_db):
        db = feature_db["db"]
        pid = feature_db["project_id"]
        db.create_canonical_feature(pid, "features", "Hospital Cover")
        dup = db.create_canonical_feature(pid, "features", "Hospital Cover")
        assert dup is None

    def test_get_feature(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f1 = feature_db_with_data["feature_ids"][0]
        feature = db.get_canonical_feature(f1)
        assert feature is not None
        assert feature["canonical_name"] == "Mental Health Support"
        assert feature["category"] == "Wellbeing"
        assert "mappings" in feature
        assert len(feature["mappings"]) == 3

    def test_get_nonexistent_feature(self, feature_db):
        db = feature_db["db"]
        assert db.get_canonical_feature(99999) is None

    def test_list_features(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        features = db.get_canonical_features(pid)
        assert len(features) == 3

    def test_list_features_by_attr_slug(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        features = db.get_canonical_features(pid, attr_slug="features")
        assert len(features) == 3
        # Non-existent attr_slug
        features = db.get_canonical_features(pid, attr_slug="nonexistent")
        assert len(features) == 0

    def test_list_features_by_category(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        features = db.get_canonical_features(pid, category="Wellbeing")
        assert len(features) == 1
        assert features[0]["canonical_name"] == "Mental Health Support"

    def test_list_features_with_search(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        features = db.get_canonical_features(pid, search="Dental")
        assert len(features) == 1
        assert features[0]["canonical_name"] == "Dental Cover"

    def test_list_features_includes_mapping_count(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        features = db.get_canonical_features(pid)
        for f in features:
            assert "mapping_count" in f
        # Mental Health Support has 3 mappings
        mh = next(f for f in features if f["canonical_name"] == "Mental Health Support")
        assert mh["mapping_count"] == 3

    def test_update_feature(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f1 = feature_db_with_data["feature_ids"][0]
        db.update_canonical_feature(f1, canonical_name="Mental Health Cover",
                                     category="Health & Wellbeing")
        feature = db.get_canonical_feature(f1)
        assert feature["canonical_name"] == "Mental Health Cover"
        assert feature["category"] == "Health & Wellbeing"

    def test_delete_feature(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        f1 = feature_db_with_data["feature_ids"][0]
        db.delete_canonical_feature(f1)
        assert db.get_canonical_feature(f1) is None
        features = db.get_canonical_features(pid)
        assert len(features) == 2


# ═══════════════════════════════════════════════════════════════
# Feature Mappings
# ═══════════════════════════════════════════════════════════════

class TestFeatureMappings:
    """FEAT-DB-MAP: Feature mapping tests."""

    def test_add_mapping(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f2 = feature_db_with_data["feature_ids"][1]
        mid = db.add_feature_mapping(f2, "dental care")
        assert mid is not None

    def test_add_duplicate_mapping_returns_none(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f2 = feature_db_with_data["feature_ids"][1]
        dup = db.add_feature_mapping(f2, "Dental Cover")
        assert dup is None

    def test_remove_mapping(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f1 = feature_db_with_data["feature_ids"][0]
        mappings = db.get_feature_mappings(f1)
        assert len(mappings) == 3
        db.remove_feature_mapping(mappings[0]["id"])
        mappings = db.get_feature_mappings(f1)
        assert len(mappings) == 2

    def test_get_mappings(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f1 = feature_db_with_data["feature_ids"][0]
        mappings = db.get_feature_mappings(f1)
        raw_values = {m["raw_value"] for m in mappings}
        assert "Mental Health Support" in raw_values
        assert "mental health cover" in raw_values
        assert "MH support" in raw_values


# ═══════════════════════════════════════════════════════════════
# Merge Features
# ═══════════════════════════════════════════════════════════════

class TestMergeFeatures:
    """FEAT-DB-MERGE: Feature merge tests."""

    def test_merge_moves_mappings(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f1, f2, f3 = feature_db_with_data["feature_ids"]

        # Merge f3 (Virtual GP) into f1 (Mental Health Support)
        count = db.merge_canonical_features(f1, [f3])
        assert count == 2  # "Virtual GP" and "online doctor" moved
        # f3 should be deleted
        assert db.get_canonical_feature(f3) is None
        # f1 should have more mappings
        mappings = db.get_feature_mappings(f1)
        raw_values = {m["raw_value"] for m in mappings}
        assert "online doctor" in raw_values

    def test_merge_skips_duplicate_mappings(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f1, f2, _ = feature_db_with_data["feature_ids"]

        # Add overlapping mapping to both
        db.add_feature_mapping(f2, "mental health cover")
        count = db.merge_canonical_features(f1, [f2])
        # "Dental Cover", "dental treatment" moved; "mental health cover" is duplicate, skipped
        assert count == 2

    def test_merge_self_is_noop(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        f1 = feature_db_with_data["feature_ids"][0]
        count = db.merge_canonical_features(f1, [f1])
        assert count == 0


# ═══════════════════════════════════════════════════════════════
# Resolve Raw Values
# ═══════════════════════════════════════════════════════════════

class TestResolveValues:
    """FEAT-DB-RESOLVE: Value resolution tests."""

    def test_resolve_exact_match(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        result = db.resolve_raw_value(pid, "features", "mental health cover")
        assert result is not None
        assert result["canonical_name"] == "Mental Health Support"

    def test_resolve_case_insensitive(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        result = db.resolve_raw_value(pid, "features", "MENTAL HEALTH COVER")
        assert result is not None
        assert result["canonical_name"] == "Mental Health Support"

    def test_resolve_by_canonical_name(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        result = db.resolve_raw_value(pid, "features", "dental cover")
        assert result is not None
        assert result["canonical_name"] == "Dental Cover"

    def test_resolve_no_match(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        result = db.resolve_raw_value(pid, "features", "space travel insurance")
        assert result is None

    def test_resolve_wrong_attr_slug(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        result = db.resolve_raw_value(pid, "cover_type", "mental health cover")
        assert result is None


# ═══════════════════════════════════════════════════════════════
# Unmapped Values
# ═══════════════════════════════════════════════════════════════

class TestUnmappedValues:
    """FEAT-DB-UNMAP: Unmapped values detection tests."""

    def test_unmapped_values_finds_gaps(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]

        # Create entity with attribute values — some mapped, some not
        eid = db.create_entity(pid, "product", "Product A")
        db.set_entity_attribute(eid, "features", "mental health cover", source="manual")
        db.set_entity_attribute(eid, "features", "pet insurance", source="manual")
        # Need separate entity for second value as set_attribute overwrites
        eid2 = db.create_entity(pid, "product", "Product B")
        db.set_entity_attribute(eid2, "features", "pet insurance", source="manual")

        unmapped = db.get_unmapped_values(pid, "features")
        assert "pet insurance" in unmapped

    def test_unmapped_empty_when_all_mapped(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]

        eid = db.create_entity(pid, "product", "Product A")
        db.set_entity_attribute(eid, "features", "mental health cover", source="manual")

        unmapped = db.get_unmapped_values(pid, "features")
        assert "mental health cover" not in unmapped


# ═══════════════════════════════════════════════════════════════
# Vocabulary Stats
# ═══════════════════════════════════════════════════════════════

class TestVocabularyStats:
    """FEAT-DB-STATS: Vocabulary statistics tests."""

    def test_stats_returns_counts(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        stats = db.get_feature_vocabulary_stats(pid)
        assert len(stats) == 1  # Only "features" attr_slug
        assert stats[0]["attr_slug"] == "features"
        assert stats[0]["feature_count"] == 3

    def test_stats_empty_project(self, feature_db):
        db = feature_db["db"]
        pid = feature_db["project_id"]
        stats = db.get_feature_vocabulary_stats(pid)
        assert len(stats) == 0


# ═══════════════════════════════════════════════════════════════
# Categories
# ═══════════════════════════════════════════════════════════════

class TestCategories:
    """FEAT-DB-CAT: Category listing tests."""

    def test_get_categories(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        cats = db.get_canonical_categories(pid)
        assert set(cats) == {"Core", "Digital", "Wellbeing"}

    def test_get_categories_with_attr_filter(self, feature_db_with_data):
        db = feature_db_with_data["db"]
        pid = feature_db_with_data["project_id"]
        cats = db.get_canonical_categories(pid, attr_slug="features")
        assert len(cats) == 3

    def test_get_categories_empty(self, feature_db):
        db = feature_db["db"]
        pid = feature_db["project_id"]
        cats = db.get_canonical_categories(pid)
        assert len(cats) == 0
