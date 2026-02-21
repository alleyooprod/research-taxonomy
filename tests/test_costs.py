"""Tests for Cost Tracking API endpoints and log_cost function.

Covers:
- Cost summary endpoint (empty + with data)
- Daily costs endpoint
- Budget CRUD (get/set)
- Cost logging function (log_cost)
- Edge cases: missing params, invalid budget values

Run: pytest tests/test_costs.py -v
Markers: db, api
"""
import json
import sqlite3
import pytest
from unittest.mock import patch

import web.blueprints.costs as costs_mod
import core.llm as llm_mod

pytestmark = [pytest.mark.db, pytest.mark.api]


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_table_flags():
    """Reset _TABLE_ENSURED flags between tests."""
    costs_mod._TABLE_ENSURED = False
    llm_mod._COST_TABLE_ENSURED = False
    yield
    costs_mod._TABLE_ENSURED = False
    llm_mod._COST_TABLE_ENSURED = False


@pytest.fixture
def cost_project(client):
    """Create a project for cost testing."""
    db = client.db
    pid = db.create_project(name="Cost Test", purpose="Testing costs")
    return pid


def _insert_cost(client, project_id, model, cost_usd, operation=None,
                 duration_ms=100, input_tokens=0, output_tokens=0):
    """Insert a cost record directly into the DB."""
    with client.db._get_conn() as conn:
        costs_mod._ensure_tables(conn)
        conn.execute(
            "INSERT INTO llm_calls (project_id, operation, model, input_tokens, "
            "output_tokens, cost_usd, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, operation, model, input_tokens, output_tokens,
             cost_usd, duration_ms),
        )


# ═══════════════════════════════════════════════════════════════
# Cost Summary
# ═══════════════════════════════════════════════════════════════

class TestCostSummary:
    """GET /api/costs/summary"""

    def test_summary_empty(self, client, cost_project):
        """Summary with no cost data returns zeros."""
        r = client.get(f"/api/costs/summary?project_id={cost_project}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_cost_usd"] == 0
        assert data["total_calls"] == 0
        assert data["by_model"] == {}
        assert data["by_operation"] == {}

    def test_summary_with_data(self, client, cost_project):
        """Summary aggregates cost data correctly."""
        _insert_cost(client, cost_project, "claude-haiku-4-5", 0.0012, "extraction")
        _insert_cost(client, cost_project, "claude-haiku-4-5", 0.0008, "extraction")
        _insert_cost(client, cost_project, "claude-sonnet-4-5", 0.015, "research")

        r = client.get(f"/api/costs/summary?project_id={cost_project}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_calls"] == 3
        assert data["total_cost_usd"] == pytest.approx(0.017, abs=0.001)

        # By model
        assert "claude-haiku-4-5" in data["by_model"]
        assert data["by_model"]["claude-haiku-4-5"]["calls"] == 2

        # By operation
        assert "extraction" in data["by_operation"]
        assert data["by_operation"]["extraction"]["calls"] == 2
        assert "research" in data["by_operation"]
        assert data["by_operation"]["research"]["calls"] == 1

    def test_summary_no_project_id(self, client, cost_project):
        """Summary without project_id returns all costs."""
        _insert_cost(client, cost_project, "claude-haiku-4-5", 0.001, "extraction")

        r = client.get("/api/costs/summary")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total_calls"] >= 1

    def test_summary_filters_by_project(self, client):
        """Summary only includes costs for the specified project."""
        db = client.db
        pid1 = db.create_project(name="P1", purpose="t")
        pid2 = db.create_project(name="P2", purpose="t")

        _insert_cost(client, pid1, "claude-haiku-4-5", 0.01, "extraction")
        _insert_cost(client, pid2, "claude-sonnet-4-5", 0.05, "research")

        r = client.get(f"/api/costs/summary?project_id={pid1}")
        data = r.get_json()
        assert data["total_calls"] == 1
        assert data["total_cost_usd"] == pytest.approx(0.01, abs=0.001)


# ═══════════════════════════════════════════════════════════════
# Daily Costs
# ═══════════════════════════════════════════════════════════════

class TestDailyCosts:
    """GET /api/costs/daily"""

    def test_daily_empty(self, client, cost_project):
        """Daily endpoint with no data returns empty array."""
        r = client.get(f"/api/costs/daily?project_id={cost_project}&days=7")
        assert r.status_code == 200
        data = r.get_json()
        assert data == []

    def test_daily_with_data(self, client, cost_project):
        """Daily endpoint returns aggregated data per day."""
        _insert_cost(client, cost_project, "claude-haiku-4-5", 0.001, "extraction")
        _insert_cost(client, cost_project, "claude-haiku-4-5", 0.002, "research")

        r = client.get(f"/api/costs/daily?project_id={cost_project}&days=7")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1
        # Both calls are on the same day (today)
        assert data[0]["calls"] == 2
        assert data[0]["cost_usd"] == pytest.approx(0.003, abs=0.001)

    def test_daily_default_days(self, client, cost_project):
        """Daily endpoint defaults to 30 days if not specified."""
        _insert_cost(client, cost_project, "claude-haiku-4-5", 0.001)

        r = client.get(f"/api/costs/daily?project_id={cost_project}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1

    def test_daily_no_project(self, client, cost_project):
        """Daily endpoint without project_id returns all costs."""
        _insert_cost(client, cost_project, "claude-haiku-4-5", 0.001)

        r = client.get("/api/costs/daily?days=7")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) >= 1


# ═══════════════════════════════════════════════════════════════
# Budget
# ═══════════════════════════════════════════════════════════════

class TestBudget:
    """GET/PUT /api/costs/budget"""

    def test_get_budget_default(self, client, cost_project):
        """Budget defaults to 0 when not set."""
        r = client.get(f"/api/costs/budget?project_id={cost_project}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["budget_usd"] == 0.0
        assert data["spent_usd"] == 0.0
        assert data["remaining_usd"] == 0.0
        assert data["percentage_used"] == 0.0

    def test_set_budget(self, client, cost_project):
        """Setting a budget returns ok status."""
        r = client.put(
            f"/api/costs/budget?project_id={cost_project}",
            json={"budget_usd": 50.0},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        assert data["budget_usd"] == 50.0

    def test_get_budget_after_set(self, client, cost_project):
        """Budget is returned correctly after being set."""
        client.put(
            f"/api/costs/budget?project_id={cost_project}",
            json={"budget_usd": 100.0},
        )

        r = client.get(f"/api/costs/budget?project_id={cost_project}")
        data = r.get_json()
        assert data["budget_usd"] == 100.0

    def test_budget_with_spend(self, client, cost_project):
        """Budget shows correct remaining and percentage after spending."""
        client.put(
            f"/api/costs/budget?project_id={cost_project}",
            json={"budget_usd": 10.0},
        )
        _insert_cost(client, cost_project, "claude-haiku-4-5", 2.5, "extraction")

        r = client.get(f"/api/costs/budget?project_id={cost_project}")
        data = r.get_json()
        assert data["budget_usd"] == 10.0
        assert data["spent_usd"] == pytest.approx(2.5, abs=0.01)
        assert data["remaining_usd"] == pytest.approx(7.5, abs=0.01)
        assert data["percentage_used"] == pytest.approx(25.0, abs=0.1)

    def test_update_budget(self, client, cost_project):
        """Updating budget overwrites previous value."""
        client.put(
            f"/api/costs/budget?project_id={cost_project}",
            json={"budget_usd": 50.0},
        )
        client.put(
            f"/api/costs/budget?project_id={cost_project}",
            json={"budget_usd": 75.0},
        )

        r = client.get(f"/api/costs/budget?project_id={cost_project}")
        data = r.get_json()
        assert data["budget_usd"] == 75.0

    def test_set_budget_missing_project(self, client):
        """Setting budget without project_id returns 400."""
        r = client.put("/api/costs/budget", json={"budget_usd": 10.0})
        assert r.status_code == 400

    def test_set_budget_missing_amount(self, client, cost_project):
        """Setting budget without amount returns 400."""
        r = client.put(
            f"/api/costs/budget?project_id={cost_project}",
            json={},
        )
        assert r.status_code == 400

    def test_set_budget_negative(self, client, cost_project):
        """Setting negative budget returns 400."""
        r = client.put(
            f"/api/costs/budget?project_id={cost_project}",
            json={"budget_usd": -5.0},
        )
        assert r.status_code == 400

    def test_set_budget_invalid_type(self, client, cost_project):
        """Setting non-numeric budget returns 400."""
        r = client.put(
            f"/api/costs/budget?project_id={cost_project}",
            json={"budget_usd": "abc"},
        )
        assert r.status_code == 400

    def test_get_budget_missing_project(self, client):
        """Getting budget without project_id returns 400."""
        r = client.get("/api/costs/budget")
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# log_cost function
# ═══════════════════════════════════════════════════════════════

class TestLogCost:
    """Test the log_cost function in core.llm."""

    def test_log_cost_writes_to_db(self, client, cost_project):
        """log_cost inserts a row into llm_calls."""
        db_path = str(client.db.db_path)
        with patch.object(llm_mod, "DB_PATH", db_path):
            llm_mod.log_cost(
                model="claude-haiku-4-5",
                cost_usd=0.0042,
                duration_ms=350,
                project_id=cost_project,
                operation="test_op",
                input_tokens=100,
                output_tokens=50,
            )

        # Verify via API
        r = client.get(f"/api/costs/summary?project_id={cost_project}")
        data = r.get_json()
        assert data["total_calls"] == 1
        assert data["total_cost_usd"] == pytest.approx(0.0042, abs=0.001)
        assert "test_op" in data["by_operation"]

    def test_log_cost_no_project(self, client):
        """log_cost works without project_id."""
        db_path = str(client.db.db_path)
        with patch.object(llm_mod, "DB_PATH", db_path):
            llm_mod.log_cost(
                model="claude-sonnet-4-5",
                cost_usd=0.01,
                duration_ms=500,
            )

        # Should appear in global summary (no project filter)
        r = client.get("/api/costs/summary")
        data = r.get_json()
        assert data["total_calls"] >= 1

    def test_log_cost_handles_errors(self, client):
        """log_cost silently handles DB errors (non-fatal)."""
        with patch.object(llm_mod, "DB_PATH", "/nonexistent/path/db.sqlite"):
            # Should not raise
            llm_mod.log_cost(
                model="claude-haiku-4-5",
                cost_usd=0.001,
                duration_ms=100,
            )
