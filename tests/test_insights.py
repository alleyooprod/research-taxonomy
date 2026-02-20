"""Tests for Insights & Hypothesis Tracking API endpoints.

Covers:
- Insight generation (rule-based + AI)
- Insight CRUD (list, get, dismiss, pin, delete)
- Insight summary/stats
- Hypothesis CRUD (create, list, get, update, delete)
- Hypothesis evidence (add, remove, confidence scoring)
- Filters and edge cases

Run: pytest tests/test_insights.py -v
Markers: db, api, insights
"""
import json
import pytest
from unittest.mock import patch

import web.blueprints.insights as insights_mod

pytestmark = [pytest.mark.db, pytest.mark.api]


# ═══════════════════════════════════════════════════════════════
# Schema + Fixtures
# ═══════════════════════════════════════════════════════════════

INSIGHT_SCHEMA = {
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
                {"name": "Features", "slug": "features", "data_type": "tags"},
                {"name": "Pricing", "slug": "pricing_model", "data_type": "text"},
                {"name": "Price", "slug": "price", "data_type": "currency"},
                {"name": "Founded", "slug": "founded", "data_type": "text"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture(autouse=True)
def reset_table_flag():
    """Reset the _TABLE_ENSURED flag between tests."""
    insights_mod._TABLE_ENSURED = False
    yield
    insights_mod._TABLE_ENSURED = False


@pytest.fixture
def insight_project(client):
    """Create a project with entities and attributes for insight testing."""
    db = client.db
    pid = db.create_project(
        name="Insight Test",
        purpose="Testing insights",
        entity_schema=INSIGHT_SCHEMA,
    )

    eid1 = db.create_entity(pid, "company", "Alpha Corp")
    eid2 = db.create_entity(pid, "company", "Beta Inc")
    eid3 = db.create_entity(pid, "company", "Gamma LLC")

    # Set varied attributes for pattern detection
    db.set_entity_attribute(eid1, "url", "https://alpha.com")
    db.set_entity_attribute(eid1, "features", "CRM, Analytics, API")
    db.set_entity_attribute(eid1, "price", "$99")
    db.set_entity_attribute(eid1, "founded", "2015")

    db.set_entity_attribute(eid2, "url", "https://beta.io")
    db.set_entity_attribute(eid2, "features", "CRM, Analytics")
    db.set_entity_attribute(eid2, "price", "$149")
    db.set_entity_attribute(eid2, "founded", "2018")

    db.set_entity_attribute(eid3, "url", "https://gamma.com")
    db.set_entity_attribute(eid3, "features", "CRM, API, Dashboard")
    # No price for Gamma — creates a gap
    # No founded for Gamma — another gap

    return {
        "client": client,
        "project_id": pid,
        "entity_ids": [eid1, eid2, eid3],
        "db": db,
    }


def _make_insight(client, project_id):
    """Helper to generate insights and return the response data."""
    r = client.post(f"/api/insights/generate?project_id={project_id}", json={})
    return r


def _make_hypothesis(client, project_id, statement="Market is consolidating", category="market"):
    """Helper to create a hypothesis."""
    r = client.post("/api/insights/hypotheses", json={
        "project_id": project_id,
        "statement": statement,
        "category": category,
    })
    return r


# ═══════════════════════════════════════════════════════════════
# Insight Generation Tests
# ═══════════════════════════════════════════════════════════════

class TestInsightGeneration:
    """Test rule-based insight generation."""

    @pytest.mark.insights
    def test_generate_insights_basic(self, insight_project):
        """Generating insights should return some detections."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = _make_insight(c, pid)
        assert r.status_code == 201

        data = r.get_json()
        assert "insights" in data
        assert "generated_count" in data
        assert data["generated_count"] == len(data["insights"])
        assert data["generated_count"] > 0  # Should find at least gaps

    @pytest.mark.insights
    def test_generate_insights_missing_project_id(self, client):
        """Should return 400 without project_id."""
        r = client.post("/api/insights/generate", json={})
        assert r.status_code == 400

    @pytest.mark.insights
    def test_generate_insights_nonexistent_project(self, client):
        """Should return 404 for unknown project."""
        r = client.post("/api/insights/generate?project_id=99999", json={})
        assert r.status_code == 404

    @pytest.mark.insights
    def test_generate_insights_structure(self, insight_project):
        """Each insight should have required fields."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = _make_insight(c, pid)
        data = r.get_json()

        for insight in data["insights"]:
            assert "id" in insight
            assert "insight_type" in insight
            assert "title" in insight
            assert "description" in insight
            assert "severity" in insight
            assert "source" in insight
            assert insight["source"] == "rule"

    @pytest.mark.insights
    def test_generate_insights_detects_gaps(self, insight_project):
        """Should detect feature gaps (price and founded missing for Gamma)."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = _make_insight(c, pid)
        data = r.get_json()

        gap_insights = [i for i in data["insights"] if i["insight_type"] == "gap"]
        assert len(gap_insights) > 0

    @pytest.mark.insights
    def test_generate_ai_insights_mock(self, insight_project):
        """AI insight generation with mocked LLM."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        mock_result = {
            "result": json.dumps([
                {
                    "type": "pattern",
                    "title": "CRM is universal",
                    "description": "All entities offer CRM features.",
                    "severity": "notable",
                    "category": "features",
                    "confidence": 0.8,
                },
            ]),
            "cost_usd": 0.01,
            "duration_ms": 500,
            "is_error": False,
            "structured_output": None,
        }

        with patch("core.llm.run_cli", return_value=mock_result):
            r = c.post(f"/api/insights/generate-ai?project_id={pid}", json={})

        assert r.status_code == 201
        data = r.get_json()
        assert data["generated_count"] >= 1
        assert data["insights"][0]["source"] == "ai"

    @pytest.mark.insights
    def test_generate_ai_insights_invalid_focus(self, insight_project):
        """Should reject invalid focus parameter."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = c.post(f"/api/insights/generate-ai?project_id={pid}", json={"focus": "invalid"})
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# Insight CRUD Tests
# ═══════════════════════════════════════════════════════════════

class TestInsightCRUD:
    """Test insight listing, filtering, dismissal, pinning, deletion."""

    @pytest.mark.insights
    def test_list_insights(self, insight_project):
        """List insights after generation."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        _make_insight(c, pid)

        r = c.get(f"/api/insights?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "insights" in data
        assert "total" in data
        assert len(data["insights"]) > 0

    @pytest.mark.insights
    def test_list_insights_filter_by_type(self, insight_project):
        """Filter insights by type."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        _make_insight(c, pid)

        r = c.get(f"/api/insights?project_id={pid}&insight_type=gap")
        assert r.status_code == 200
        data = r.get_json()
        for insight in data["insights"]:
            assert insight["insight_type"] == "gap"

    @pytest.mark.insights
    def test_list_insights_filter_by_severity(self, insight_project):
        """Filter insights by severity."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        _make_insight(c, pid)

        r = c.get(f"/api/insights?project_id={pid}&severity=info")
        assert r.status_code == 200
        data = r.get_json()
        for insight in data["insights"]:
            assert insight["severity"] == "info"

    @pytest.mark.insights
    def test_get_single_insight(self, insight_project):
        """Get a single insight by ID."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        gen = _make_insight(c, pid)
        insight_id = gen.get_json()["insights"][0]["id"]

        r = c.get(f"/api/insights/{insight_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] == insight_id

    @pytest.mark.insights
    def test_get_nonexistent_insight(self, client):
        """Should return 404 for unknown insight ID."""
        r = client.get("/api/insights/99999")
        assert r.status_code == 404

    @pytest.mark.insights
    def test_dismiss_insight(self, insight_project):
        """Dismiss an insight."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        gen = _make_insight(c, pid)
        insight_id = gen.get_json()["insights"][0]["id"]

        r = c.put(f"/api/insights/{insight_id}/dismiss", json={})
        assert r.status_code == 200
        data = r.get_json()
        assert data["updated"] is True
        assert data["id"] == insight_id

        # Should not appear in default listing
        r2 = c.get(f"/api/insights?project_id={pid}")
        ids = [i["id"] for i in r2.get_json()["insights"]]
        assert insight_id not in ids

    @pytest.mark.insights
    def test_pin_insight(self, insight_project):
        """Pin and unpin an insight."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        gen = _make_insight(c, pid)
        insight_id = gen.get_json()["insights"][0]["id"]

        # Pin
        r = c.put(f"/api/insights/{insight_id}/pin", json={})
        assert r.status_code == 200
        assert r.get_json()["is_pinned"] is True

        # Unpin (toggle)
        r = c.put(f"/api/insights/{insight_id}/pin", json={})
        assert r.status_code == 200
        assert r.get_json()["is_pinned"] is False

    @pytest.mark.insights
    def test_delete_insight(self, insight_project):
        """Delete an insight permanently."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        gen = _make_insight(c, pid)
        insight_id = gen.get_json()["insights"][0]["id"]

        r = c.delete(f"/api/insights/{insight_id}")
        assert r.status_code == 200

        # Confirm deleted
        r2 = c.get(f"/api/insights/{insight_id}")
        assert r2.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Insight Summary Tests
# ═══════════════════════════════════════════════════════════════

class TestInsightSummary:
    """Test dashboard summary stats."""

    @pytest.mark.insights
    def test_summary_basic(self, insight_project):
        """Summary should return counts by type, severity, source."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        _make_insight(c, pid)

        r = c.get(f"/api/insights/summary?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "total" in data
        assert "by_severity" in data
        assert "by_type" in data
        assert "by_source" in data
        assert data["total"] > 0

    @pytest.mark.insights
    def test_summary_empty_project(self, client):
        """Summary for a project with no insights should return zeros."""
        db = client.db
        pid = db.create_project(name="Empty Project", purpose="test", entity_schema=INSIGHT_SCHEMA)

        r = client.get(f"/api/insights/summary?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] == 0


# ═══════════════════════════════════════════════════════════════
# Hypothesis CRUD Tests
# ═══════════════════════════════════════════════════════════════

class TestHypothesisCRUD:
    """Test hypothesis creation, listing, updating, deletion."""

    @pytest.mark.insights
    def test_create_hypothesis(self, insight_project):
        """Create a new hypothesis."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = _make_hypothesis(c, pid)
        assert r.status_code == 201
        data = r.get_json()
        assert data["statement"] == "Market is consolidating"
        assert data["status"] == "open"
        assert data["confidence"] == 0.5
        assert data["category"] == "market"

    @pytest.mark.insights
    def test_create_hypothesis_missing_statement(self, insight_project):
        """Should reject empty statement."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = c.post("/api/insights/hypotheses", json={
            "project_id": pid,
            "statement": "",
        })
        assert r.status_code == 400

    @pytest.mark.insights
    def test_create_hypothesis_invalid_category(self, insight_project):
        """Should reject invalid category."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = c.post("/api/insights/hypotheses", json={
            "project_id": pid,
            "statement": "Test",
            "category": "invalid_cat",
        })
        assert r.status_code == 400

    @pytest.mark.insights
    def test_create_hypothesis_nonexistent_project(self, client):
        """Should return 404 for unknown project."""
        r = client.post("/api/insights/hypotheses", json={
            "project_id": 99999,
            "statement": "Test",
        })
        assert r.status_code == 404

    @pytest.mark.insights
    def test_list_hypotheses(self, insight_project):
        """List hypotheses for a project."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        _make_hypothesis(c, pid, "Hyp A")
        _make_hypothesis(c, pid, "Hyp B", "pricing")

        r = c.get(f"/api/insights/hypotheses?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 2

    @pytest.mark.insights
    def test_list_hypotheses_filter_status(self, insight_project):
        """Filter hypotheses by status."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r1 = _make_hypothesis(c, pid, "Open one")
        hyp_id = r1.get_json()["id"]

        # Update to supported
        c.put(f"/api/insights/hypotheses/{hyp_id}", json={"status": "supported"})
        _make_hypothesis(c, pid, "Still open")

        r = c.get(f"/api/insights/hypotheses?project_id={pid}&status=open")
        assert r.status_code == 200
        data = r.get_json()
        for hyp in data:
            assert hyp["status"] == "open"

    @pytest.mark.insights
    def test_get_hypothesis_detail(self, insight_project):
        """Get hypothesis with full detail."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = _make_hypothesis(c, pid)
        hyp_id = r.get_json()["id"]

        r2 = c.get(f"/api/insights/hypotheses/{hyp_id}")
        assert r2.status_code == 200
        data = r2.get_json()
        assert data["id"] == hyp_id
        assert "evidence" in data

    @pytest.mark.insights
    def test_update_hypothesis(self, insight_project):
        """Update hypothesis statement and status."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = _make_hypothesis(c, pid)
        hyp_id = r.get_json()["id"]

        r2 = c.put(f"/api/insights/hypotheses/{hyp_id}", json={
            "statement": "Updated statement",
            "status": "supported",
        })
        assert r2.status_code == 200
        data = r2.get_json()
        assert data["statement"] == "Updated statement"
        assert data["status"] == "supported"

    @pytest.mark.insights
    def test_update_hypothesis_invalid_status(self, insight_project):
        """Should reject invalid status value."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = _make_hypothesis(c, pid)
        hyp_id = r.get_json()["id"]

        r2 = c.put(f"/api/insights/hypotheses/{hyp_id}", json={
            "status": "bogus",
        })
        assert r2.status_code == 400

    @pytest.mark.insights
    def test_delete_hypothesis(self, insight_project):
        """Delete hypothesis and verify cascade."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = _make_hypothesis(c, pid)
        hyp_id = r.get_json()["id"]

        r2 = c.delete(f"/api/insights/hypotheses/{hyp_id}")
        assert r2.status_code == 200

        r3 = c.get(f"/api/insights/hypotheses/{hyp_id}")
        assert r3.status_code == 404

    @pytest.mark.insights
    def test_delete_nonexistent_hypothesis(self, client):
        """Should return 404 for unknown hypothesis."""
        r = client.delete("/api/insights/hypotheses/99999")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Hypothesis Evidence Tests
# ═══════════════════════════════════════════════════════════════

class TestHypothesisEvidence:
    """Test evidence addition, removal, and confidence scoring."""

    @pytest.mark.insights
    def test_add_supporting_evidence(self, insight_project):
        """Add supporting evidence to a hypothesis."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        r = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Alpha Corp recently acquired a CRM company",
            "weight": 2.0,
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["direction"] == "supports"
        assert data["weight"] == 2.0

    @pytest.mark.insights
    def test_add_contradicting_evidence(self, insight_project):
        """Add contradicting evidence."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        r = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "contradicts",
            "description": "New competitors entering the market",
            "weight": 1.5,
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["direction"] == "contradicts"

    @pytest.mark.insights
    def test_add_evidence_with_entity_link(self, insight_project):
        """Add evidence linked to an entity."""
        c = insight_project["client"]
        pid = insight_project["project_id"]
        eid1 = insight_project["entity_ids"][0]

        hyp = _make_hypothesis(c, pid).get_json()

        r = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Alpha Corp raised $50M",
            "entity_id": eid1,
            "attr_slug": "funding",
        })
        assert r.status_code == 201
        data = r.get_json()
        assert data["entity_id"] == eid1

    @pytest.mark.insights
    def test_add_evidence_invalid_direction(self, insight_project):
        """Should reject invalid direction."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        r = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "invalid",
            "description": "Something",
        })
        assert r.status_code == 400

    @pytest.mark.insights
    def test_add_evidence_missing_description(self, insight_project):
        """Should reject empty description."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        r = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "",
        })
        assert r.status_code == 400

    @pytest.mark.insights
    def test_add_evidence_nonexistent_hypothesis(self, client):
        """Should return 404 for unknown hypothesis."""
        r = client.post("/api/insights/hypotheses/99999/evidence", json={
            "direction": "supports",
            "description": "Something",
        })
        assert r.status_code == 404

    @pytest.mark.insights
    def test_add_evidence_nonexistent_entity(self, insight_project):
        """Should return 404 for nonexistent entity_id."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        r = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Something",
            "entity_id": 99999,
        })
        assert r.status_code == 404

    @pytest.mark.insights
    def test_remove_evidence(self, insight_project):
        """Remove evidence from a hypothesis."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        ev = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Some evidence",
        }).get_json()

        r = c.delete(f"/api/insights/hypotheses/{hyp['id']}/evidence/{ev['id']}")
        assert r.status_code == 200

    @pytest.mark.insights
    def test_remove_nonexistent_evidence(self, insight_project):
        """Should return 404 for unknown evidence ID."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        r = c.delete(f"/api/insights/hypotheses/{hyp['id']}/evidence/99999")
        assert r.status_code == 404

    @pytest.mark.insights
    def test_confidence_updates_on_add(self, insight_project):
        """Confidence should update when evidence is added."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()
        assert hyp["confidence"] == 0.5  # Default

        # Add supporting evidence
        c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Strong support",
            "weight": 2.0,
        })

        # Fetch updated hypothesis
        r = c.get(f"/api/insights/hypotheses/{hyp['id']}")
        data = r.get_json()
        assert data["confidence"] > 0.5  # Should increase

    @pytest.mark.insights
    def test_confidence_balances(self, insight_project):
        """Balanced evidence should yield ~0.5 confidence."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        # Equal supports and contradicts
        c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Support 1",
            "weight": 1.0,
        })
        c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "contradicts",
            "description": "Contradict 1",
            "weight": 1.0,
        })

        r = c.get(f"/api/insights/hypotheses/{hyp['id']}/score")
        assert r.status_code == 200
        data = r.get_json()
        assert data["confidence"] == 0.5
        assert data["supports_weight"] == 1.0
        assert data["contradicts_weight"] == 1.0


# ═══════════════════════════════════════════════════════════════
# Hypothesis Score Tests
# ═══════════════════════════════════════════════════════════════

class TestHypothesisScore:
    """Test confidence score computation endpoint."""

    @pytest.mark.insights
    def test_score_no_evidence(self, insight_project):
        """Score with no evidence should be 0.5."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        r = c.get(f"/api/insights/hypotheses/{hyp['id']}/score")
        assert r.status_code == 200
        data = r.get_json()
        assert data["confidence"] == 0.5
        assert data["evidence_count"] == 0

    @pytest.mark.insights
    def test_score_supports_only(self, insight_project):
        """Score with only supports should be 1.0."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Support 1",
            "weight": 1.0,
        })
        c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Support 2",
            "weight": 2.0,
        })

        r = c.get(f"/api/insights/hypotheses/{hyp['id']}/score")
        data = r.get_json()
        assert data["confidence"] == 1.0
        assert data["supports_weight"] == 3.0

    @pytest.mark.insights
    def test_score_contradicts_only(self, insight_project):
        """Score with only contradicts should be 0.0."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "contradicts",
            "description": "Against 1",
            "weight": 2.0,
        })

        r = c.get(f"/api/insights/hypotheses/{hyp['id']}/score")
        data = r.get_json()
        assert data["confidence"] == 0.0

    @pytest.mark.insights
    def test_score_neutral_ignored(self, insight_project):
        """Neutral evidence should not affect confidence score."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "neutral",
            "description": "Observation",
            "weight": 3.0,
        })

        r = c.get(f"/api/insights/hypotheses/{hyp['id']}/score")
        data = r.get_json()
        assert data["confidence"] == 0.5  # Still default, neutral doesn't count
        assert data["neutral_weight"] == 3.0

    @pytest.mark.insights
    def test_score_nonexistent_hypothesis(self, client):
        """Should return 404 for unknown hypothesis."""
        r = client.get("/api/insights/hypotheses/99999/score")
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestInsightsEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.insights
    def test_weight_clamping(self, insight_project):
        """Evidence weight should be clamped to [0.1, 3.0]."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        hyp = _make_hypothesis(c, pid).get_json()

        # Too high
        r = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Heavy",
            "weight": 10.0,
        })
        assert r.status_code == 201
        assert r.get_json()["weight"] == 3.0

        # Too low
        r = c.post(f"/api/insights/hypotheses/{hyp['id']}/evidence", json={
            "direction": "supports",
            "description": "Light",
            "weight": 0.0,
        })
        assert r.status_code == 201
        assert r.get_json()["weight"] == 0.1

    @pytest.mark.insights
    def test_dismiss_and_show_all(self, insight_project):
        """Dismissed insights visible with is_dismissed=all filter."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        gen = _make_insight(c, pid)
        insight_id = gen.get_json()["insights"][0]["id"]

        c.put(f"/api/insights/{insight_id}/dismiss", json={})

        # Default listing excludes dismissed
        r1 = c.get(f"/api/insights?project_id={pid}")
        ids1 = [i["id"] for i in r1.get_json()["insights"]]
        assert insight_id not in ids1

        # Show all including dismissed
        r2 = c.get(f"/api/insights?project_id={pid}&is_dismissed=all")
        ids2 = [i["id"] for i in r2.get_json()["insights"]]
        assert insight_id in ids2

    @pytest.mark.insights
    def test_empty_project_generates_no_insights(self, client):
        """Project with no entities should generate empty insights."""
        db = client.db
        pid = db.create_project(name="Empty", purpose="test", entity_schema=INSIGHT_SCHEMA)

        r = client.post(f"/api/insights/generate?project_id={pid}", json={})
        assert r.status_code == 201
        data = r.get_json()
        assert data["generated_count"] == 0

    @pytest.mark.insights
    def test_hypothesis_without_category(self, insight_project):
        """Create hypothesis without specifying category."""
        c = insight_project["client"]
        pid = insight_project["project_id"]

        r = c.post("/api/insights/hypotheses", json={
            "project_id": pid,
            "statement": "Just a hunch",
        })
        assert r.status_code == 201
        assert r.get_json()["category"] is None

    @pytest.mark.insights
    def test_list_insights_missing_project_id(self, client):
        """Should return 400 without project_id."""
        r = client.get("/api/insights")
        assert r.status_code == 400

    @pytest.mark.insights
    def test_summary_missing_project_id(self, client):
        """Should return 400 without project_id."""
        r = client.get("/api/insights/summary")
        assert r.status_code == 400
