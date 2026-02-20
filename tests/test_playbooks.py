"""Tests for Research Playbooks API endpoints.

Covers:
- Playbook CRUD (create, list, get, update, delete)
- Playbook duplication (clone templates and custom playbooks)
- Playbook runs (start, list, get, step update, auto-complete, status)
- Template seeding and listing
- AI improve suggestions (mocked)
- Edge cases: not found, empty name, bad category, bad step type, delete template

Run: pytest tests/test_playbooks.py -v
Markers: db, api
"""
import json
import pytest

import web.blueprints.playbooks as playbooks_mod

pytestmark = [pytest.mark.db, pytest.mark.api]


# ===================================================================
# Shared Schema + Fixtures
# ===================================================================

PLAYBOOK_SCHEMA = {
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
                {"name": "URL", "slug": "url", "data_type": "url"},
            ],
        },
    ],
    "relationships": [],
}

SAMPLE_STEPS = [
    {"title": "Identify targets", "type": "discover", "description": "Find companies"},
    {"title": "Capture websites", "type": "capture", "description": "Grab pages"},
    {"title": "Extract data", "type": "extract", "description": "Pull attributes"},
]


@pytest.fixture(autouse=True)
def reset_table_flag():
    """Reset the _TABLE_ENSURED flag between tests."""
    playbooks_mod._TABLE_ENSURED = False
    yield
    playbooks_mod._TABLE_ENSURED = False


@pytest.fixture
def playbook_project(client):
    """Create a project for playbook run testing."""
    db = client.db
    pid = db.create_project(
        name="Playbook Test Project",
        purpose="Testing playbooks",
        entity_schema=PLAYBOOK_SCHEMA,
    )
    return {"client": client, "project_id": pid, "db": db}


def _create_playbook(client, name="Test Playbook", steps=None, category="market",
                     description="A test playbook", metadata=None):
    """Helper to create a playbook and return the response."""
    payload = {
        "name": name,
        "steps": steps or SAMPLE_STEPS,
        "category": category,
        "description": description,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    return client.post("/api/playbooks", json=payload)


# ===================================================================
# 1. TestPlaybookCRUD
# ===================================================================

class TestPlaybookCRUD:
    """Tests for playbook create, list, get, update, and delete."""

    def test_create_playbook(self, client):
        """Create a playbook with valid data returns 201."""
        r = _create_playbook(client)
        assert r.status_code == 201
        data = r.get_json()
        assert data["name"] == "Test Playbook"
        assert data["description"] == "A test playbook"
        assert data["category"] == "market"
        assert data["is_template"] is False
        assert data["usage_count"] == 0
        assert isinstance(data["steps"], list)
        assert len(data["steps"]) == 3
        assert data["steps"][0]["title"] == "Identify targets"
        assert data["steps"][0]["type"] == "discover"
        assert data["id"] is not None
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

    def test_create_playbook_with_metadata(self, client):
        """Create a playbook with custom metadata."""
        r = _create_playbook(client, metadata={"author": "tester", "version": 2})
        assert r.status_code == 201
        data = r.get_json()
        assert data["metadata"]["author"] == "tester"
        assert data["metadata"]["version"] == 2

    def test_create_playbook_missing_name(self, client):
        """Create with no name returns 400."""
        r = client.post("/api/playbooks", json={"steps": SAMPLE_STEPS})
        assert r.status_code == 400
        assert "name" in r.get_json()["error"].lower()

    def test_create_playbook_missing_steps(self, client):
        """Create with no steps returns 400."""
        r = client.post("/api/playbooks", json={"name": "No Steps"})
        assert r.status_code == 400
        assert "steps" in r.get_json()["error"].lower()

    def test_create_playbook_empty_steps(self, client):
        """Create with empty steps array returns 400."""
        r = client.post("/api/playbooks", json={"name": "Empty", "steps": []})
        assert r.status_code == 400
        assert "at least one step" in r.get_json()["error"].lower()

    def test_list_playbooks_empty(self, client):
        """List playbooks when none exist returns empty list."""
        r = client.get("/api/playbooks")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_list_playbooks(self, client):
        """List playbooks returns all created playbooks."""
        _create_playbook(client, name="PB One")
        _create_playbook(client, name="PB Two", category="product")
        r = client.get("/api/playbooks")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 2
        names = {pb["name"] for pb in data}
        assert names == {"PB One", "PB Two"}

    def test_list_playbooks_filter_category(self, client):
        """List playbooks filtered by category."""
        _create_playbook(client, name="Market PB", category="market")
        _create_playbook(client, name="Product PB", category="product")
        r = client.get("/api/playbooks?category=market")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 1
        assert data[0]["name"] == "Market PB"

    def test_list_playbooks_filter_is_template(self, client):
        """List playbooks filtered by template status."""
        _create_playbook(client, name="Custom PB")
        # Seed templates for comparison
        client.post("/api/playbooks/templates/seed")
        r = client.get("/api/playbooks?is_template=0")
        assert r.status_code == 200
        data = r.get_json()
        assert all(not pb["is_template"] for pb in data)

    def test_get_playbook(self, client):
        """Get a single playbook by ID with run stats."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.get(f"/api/playbooks/{pb_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] == pb_id
        assert data["name"] == "Test Playbook"
        assert "run_stats" in data
        assert data["run_stats"]["total_runs"] == 0
        # SUM returns None when no matching rows exist
        assert not data["run_stats"]["completed_runs"]
        assert not data["run_stats"]["active_runs"]
        assert not data["run_stats"]["abandoned_runs"]

    def test_get_playbook_not_found(self, client):
        """Get nonexistent playbook returns 404."""
        r = client.get("/api/playbooks/9999")
        assert r.status_code == 404

    def test_update_playbook_name(self, client):
        """Update playbook name."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.put(f"/api/playbooks/{pb_id}", json={"name": "Renamed PB"})
        assert r.status_code == 200
        assert r.get_json()["name"] == "Renamed PB"

    def test_update_playbook_description(self, client):
        """Update playbook description."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.put(f"/api/playbooks/{pb_id}", json={"description": "Updated desc"})
        assert r.status_code == 200
        assert r.get_json()["description"] == "Updated desc"

    def test_update_playbook_steps(self, client):
        """Update playbook steps validates and replaces."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        new_steps = [{"title": "Only step", "type": "review"}]
        r = client.put(f"/api/playbooks/{pb_id}", json={"steps": new_steps})
        assert r.status_code == 200
        assert len(r.get_json()["steps"]) == 1
        assert r.get_json()["steps"][0]["title"] == "Only step"

    def test_update_playbook_no_fields(self, client):
        """Update with no fields returns 400."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.put(f"/api/playbooks/{pb_id}", json={})
        assert r.status_code == 400
        assert "at least one field" in r.get_json()["error"].lower()

    def test_update_playbook_not_found(self, client):
        """Update nonexistent playbook returns 404."""
        r = client.put("/api/playbooks/9999", json={"name": "Ghost"})
        assert r.status_code == 404

    def test_delete_playbook(self, client):
        """Delete a custom playbook succeeds."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.delete(f"/api/playbooks/{pb_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["deleted"] is True
        assert data["id"] == pb_id
        # Verify gone
        r = client.get(f"/api/playbooks/{pb_id}")
        assert r.status_code == 404

    def test_delete_playbook_not_found(self, client):
        """Delete nonexistent playbook returns 404."""
        r = client.delete("/api/playbooks/9999")
        assert r.status_code == 404


# ===================================================================
# 2. TestPlaybookDuplicate
# ===================================================================

class TestPlaybookDuplicate:
    """Tests for playbook duplication."""

    def test_duplicate_custom_playbook(self, client):
        """Duplicate a custom playbook creates a copy."""
        r = _create_playbook(client, name="Original")
        original_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{original_id}/duplicate", json={})
        assert r.status_code == 201
        data = r.get_json()
        assert data["name"] == "Original (copy)"
        assert data["is_template"] is False
        assert data["usage_count"] == 0
        assert data["id"] != original_id
        assert len(data["steps"]) == 3

    def test_duplicate_template(self, client):
        """Duplicate a template creates a non-template copy."""
        client.post("/api/playbooks/templates/seed")
        templates = client.get("/api/playbooks/templates").get_json()
        assert len(templates) > 0
        tpl_id = templates[0]["id"]
        r = client.post(f"/api/playbooks/{tpl_id}/duplicate", json={})
        assert r.status_code == 201
        data = r.get_json()
        assert data["is_template"] is False
        assert data["usage_count"] == 0
        assert data["category"] == templates[0]["category"]

    def test_duplicate_with_custom_name(self, client):
        """Duplicate with a custom name uses that name."""
        r = _create_playbook(client, name="Base")
        base_id = r.get_json()["id"]
        r = client.post(
            f"/api/playbooks/{base_id}/duplicate",
            json={"name": "My Custom Copy"},
        )
        assert r.status_code == 201
        assert r.get_json()["name"] == "My Custom Copy"

    def test_duplicate_not_found(self, client):
        """Duplicate nonexistent playbook returns 404."""
        r = client.post("/api/playbooks/9999/duplicate", json={})
        assert r.status_code == 404


# ===================================================================
# 3. TestPlaybookRuns
# ===================================================================

class TestPlaybookRuns:
    """Tests for playbook run lifecycle."""

    def test_start_run(self, playbook_project):
        """Start a run for a project returns 201 with run dict."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]

        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        assert r.status_code == 201
        data = r.get_json()
        assert data["playbook_id"] == pb_id
        assert data["project_id"] == pid
        assert data["status"] == "in_progress"
        assert data["playbook_name"] == "Test Playbook"
        assert len(data["progress"]) == 3
        assert all(not p["completed"] for p in data["progress"])

    def test_start_run_increments_usage_count(self, playbook_project):
        """Starting a run increments the playbook usage_count."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        assert r.get_json()["usage_count"] == 0

        client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        r = client.get(f"/api/playbooks/{pb_id}")
        assert r.get_json()["usage_count"] == 1

        client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        r = client.get(f"/api/playbooks/{pb_id}")
        assert r.get_json()["usage_count"] == 2

    def test_start_run_missing_project_id(self, client):
        """Start run without project_id returns 400."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={})
        assert r.status_code == 400
        assert "project_id" in r.get_json()["error"].lower()

    def test_start_run_playbook_not_found(self, playbook_project):
        """Start run on nonexistent playbook returns 404."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = client.post("/api/playbooks/9999/run", json={"project_id": pid})
        assert r.status_code == 404

    def test_start_run_project_not_found(self, client):
        """Start run with nonexistent project returns 404."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": 9999})
        assert r.status_code == 404

    def test_list_runs(self, playbook_project):
        """List runs for a project returns runs with progress info."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]

        client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})

        r = client.get(f"/api/playbooks/runs?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 2
        for run in data:
            assert "playbook_name" in run
            assert "progress_pct" in run
            assert "total_steps" in run
            assert "completed_steps" in run
            assert run["total_steps"] == 3
            assert run["completed_steps"] == 0
            assert run["progress_pct"] == 0

    def test_list_runs_missing_project_id(self, client):
        """List runs without project_id returns 400."""
        r = client.get("/api/playbooks/runs")
        assert r.status_code == 400

    def test_get_run(self, playbook_project):
        """Get a single run with merged step definitions and progress."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]

        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.get(f"/api/playbooks/runs/{run_id}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["id"] == run_id
        assert data["playbook_name"] == "Test Playbook"
        assert "steps" in data
        assert len(data["steps"]) == 3
        # Each step has both definition fields and progress fields
        step = data["steps"][0]
        assert step["title"] == "Identify targets"
        assert step["type"] == "discover"
        assert step["completed"] is False
        assert step["step_index"] == 0

    def test_get_run_not_found(self, client):
        """Get nonexistent run returns 404."""
        r = client.get("/api/playbooks/runs/9999")
        assert r.status_code == 404

    def test_update_step_complete(self, playbook_project):
        """Mark a step as completed updates progress."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.put(
            f"/api/playbooks/runs/{run_id}/step/0",
            json={"completed": True},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["progress"][0]["completed"] is True
        assert data["progress"][0]["completed_at"] is not None
        assert data["completed_steps"] == 1
        assert data["total_steps"] == 3
        # ~33.3%
        assert data["progress_pct"] == pytest.approx(33.3, abs=0.1)

    def test_update_step_with_notes(self, playbook_project):
        """Update a step with notes."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.put(
            f"/api/playbooks/runs/{run_id}/step/1",
            json={"notes": "Found 5 interesting pages"},
        )
        assert r.status_code == 200
        assert r.get_json()["progress"][1]["notes"] == "Found 5 interesting pages"

    def test_update_step_uncomplete(self, playbook_project):
        """Mark a step as not completed clears completed_at."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        # Complete then uncomplete
        client.put(f"/api/playbooks/runs/{run_id}/step/0", json={"completed": True})
        r = client.put(f"/api/playbooks/runs/{run_id}/step/0", json={"completed": False})
        assert r.status_code == 200
        assert r.get_json()["progress"][0]["completed"] is False
        assert r.get_json()["progress"][0]["completed_at"] is None

    def test_update_step_invalid_index(self, playbook_project):
        """Update step with out-of-range index returns 400."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.put(f"/api/playbooks/runs/{run_id}/step/99", json={"completed": True})
        assert r.status_code == 400
        assert "invalid step_index" in r.get_json()["error"].lower()

    def test_update_step_no_fields(self, playbook_project):
        """Update step with no completed or notes returns 400."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.put(f"/api/playbooks/runs/{run_id}/step/0", json={})
        assert r.status_code == 400

    def test_update_step_run_not_found(self, client):
        """Update step on nonexistent run returns 404."""
        r = client.put("/api/playbooks/runs/9999/step/0", json={"completed": True})
        assert r.status_code == 404

    def test_auto_complete_run(self, playbook_project):
        """Completing all steps auto-completes the run."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        # Complete all 3 steps
        client.put(f"/api/playbooks/runs/{run_id}/step/0", json={"completed": True})
        client.put(f"/api/playbooks/runs/{run_id}/step/1", json={"completed": True})
        r = client.put(f"/api/playbooks/runs/{run_id}/step/2", json={"completed": True})
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "completed"
        assert data["completed_at"] is not None
        assert data["progress_pct"] == 100.0

    def test_update_step_on_completed_run(self, playbook_project):
        """Cannot update steps on a completed run."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        # Complete all steps to auto-complete
        for i in range(3):
            client.put(f"/api/playbooks/runs/{run_id}/step/{i}", json={"completed": True})

        # Try to update a step on completed run
        r = client.put(f"/api/playbooks/runs/{run_id}/step/0", json={"completed": False})
        assert r.status_code == 400
        assert "status" in r.get_json()["error"].lower()

    def test_update_run_status_abandon(self, playbook_project):
        """Abandon a run sets status and completed_at."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.put(
            f"/api/playbooks/runs/{run_id}/status",
            json={"status": "abandoned"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "abandoned"
        assert data["completed_at"] is not None

    def test_update_run_status_complete(self, playbook_project):
        """Manually complete a run sets status and completed_at."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.put(
            f"/api/playbooks/runs/{run_id}/status",
            json={"status": "completed"},
        )
        assert r.status_code == 200
        assert r.get_json()["status"] == "completed"
        assert r.get_json()["completed_at"] is not None

    def test_update_run_status_invalid(self, playbook_project):
        """Invalid run status returns 400."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.put(
            f"/api/playbooks/runs/{run_id}/status",
            json={"status": "paused"},
        )
        assert r.status_code == 400

    def test_update_run_status_missing(self, playbook_project):
        """Update run status with no status field returns 400."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        r = client.put(f"/api/playbooks/runs/{run_id}/status", json={})
        assert r.status_code == 400

    def test_update_run_status_not_found(self, client):
        """Update status on nonexistent run returns 404."""
        r = client.put("/api/playbooks/runs/9999/status", json={"status": "completed"})
        assert r.status_code == 404

    def test_update_run_status_resume(self, playbook_project):
        """Resume an abandoned run back to in_progress clears completed_at."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]

        # Abandon then resume
        client.put(f"/api/playbooks/runs/{run_id}/status", json={"status": "abandoned"})
        r = client.put(
            f"/api/playbooks/runs/{run_id}/status",
            json={"status": "in_progress"},
        )
        assert r.status_code == 200
        assert r.get_json()["status"] == "in_progress"
        assert r.get_json()["completed_at"] is None


# ===================================================================
# 4. TestPlaybookTemplates
# ===================================================================

class TestPlaybookTemplates:
    """Tests for template seeding and listing."""

    def test_seed_templates(self, client):
        """Seed default templates returns 201 with count."""
        r = client.post("/api/playbooks/templates/seed")
        assert r.status_code == 201
        data = r.get_json()
        assert data["seeded"] == 4
        assert "4" in data["message"]

    def test_seed_templates_idempotent(self, client):
        """Seeding twice does not duplicate templates."""
        r1 = client.post("/api/playbooks/templates/seed")
        assert r1.status_code == 201
        assert r1.get_json()["seeded"] == 4

        r2 = client.post("/api/playbooks/templates/seed")
        assert r2.status_code == 200
        assert r2.get_json()["seeded"] == 0
        assert "already exist" in r2.get_json()["message"].lower()

    def test_list_templates(self, client):
        """List templates returns only template playbooks."""
        client.post("/api/playbooks/templates/seed")
        _create_playbook(client, name="Custom One")

        r = client.get("/api/playbooks/templates")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data) == 4
        assert all(pb["is_template"] for pb in data)
        names = {pb["name"] for pb in data}
        assert "Market Mapping" in names
        assert "Product Teardown" in names
        assert "Design Research" in names
        assert "Competitive Intelligence" in names

    def test_template_has_expected_structure(self, client):
        """Seeded templates have steps with correct types."""
        client.post("/api/playbooks/templates/seed")
        r = client.get("/api/playbooks/templates")
        templates = r.get_json()

        for tpl in templates:
            assert tpl["is_template"] is True
            assert len(tpl["steps"]) > 0
            assert tpl["category"] in {"market", "product", "design", "competitive"}
            for step in tpl["steps"]:
                assert "title" in step
                assert step["type"] in {
                    "discover", "capture", "extract", "analyse", "review", "custom"
                }

    def test_delete_template_blocked(self, client):
        """Cannot delete a built-in template returns 403."""
        client.post("/api/playbooks/templates/seed")
        templates = client.get("/api/playbooks/templates").get_json()
        tpl_id = templates[0]["id"]

        r = client.delete(f"/api/playbooks/{tpl_id}")
        assert r.status_code == 403
        assert "template" in r.get_json()["error"].lower()


# ===================================================================
# 5. TestPlaybookImprove
# ===================================================================

class TestPlaybookImprove:
    """Tests for AI-suggest improvements."""

    def test_improve_no_runs(self, client):
        """Improve with no runs returns info suggestion."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]

        r = client.post(f"/api/playbooks/{pb_id}/improve")
        assert r.status_code == 200
        data = r.get_json()
        assert data["playbook_id"] == pb_id
        assert data["run_data"]["total_runs"] == 0
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0]["type"] == "info"
        assert "no run data" in data["suggestions"][0]["title"].lower()

    def test_improve_with_completed_runs(self, playbook_project):
        """Improve with completed runs returns relevant suggestions."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        # Create a playbook with steps lacking guidance
        steps_no_guidance = [
            {"title": "Step A", "type": "discover"},
            {"title": "Step B", "type": "capture"},
        ]
        r = _create_playbook(client, steps=steps_no_guidance)
        pb_id = r.get_json()["id"]

        # Run and complete
        r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run_id = r.get_json()["id"]
        client.put(f"/api/playbooks/runs/{run_id}/step/0", json={"completed": True})
        client.put(f"/api/playbooks/runs/{run_id}/step/1", json={"completed": True})

        r = client.post(f"/api/playbooks/{pb_id}/improve")
        assert r.status_code == 200
        data = r.get_json()
        assert data["run_data"]["total_runs"] == 1
        assert data["run_data"]["completed"] == 1
        # Should get guidance suggestion since steps lack guidance
        suggestion_types = [s["type"] for s in data["suggestions"]]
        assert "improvement" in suggestion_types

    def test_improve_high_abandonment(self, playbook_project):
        """Improve with high abandonment rate returns warning."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]

        # Create 4 runs, abandon 3 of them
        for i in range(4):
            r = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
            run_id = r.get_json()["id"]
            if i < 3:
                client.put(
                    f"/api/playbooks/runs/{run_id}/status",
                    json={"status": "abandoned"},
                )
            else:
                # Complete only 1
                for s in range(3):
                    client.put(
                        f"/api/playbooks/runs/{run_id}/step/{s}",
                        json={"completed": True},
                    )

        r = client.post(f"/api/playbooks/{pb_id}/improve")
        assert r.status_code == 200
        data = r.get_json()
        assert data["run_data"]["total_runs"] == 4
        assert data["run_data"]["abandoned"] == 3
        suggestion_types = [s["type"] for s in data["suggestions"]]
        assert "warning" in suggestion_types

    def test_improve_not_found(self, client):
        """Improve nonexistent playbook returns 404."""
        r = client.post("/api/playbooks/9999/improve")
        assert r.status_code == 404


# ===================================================================
# 6. TestPlaybookEdgeCases
# ===================================================================

class TestPlaybookEdgeCases:
    """Edge case and validation tests."""

    def test_create_empty_name(self, client):
        """Create with whitespace-only name returns 400."""
        r = client.post("/api/playbooks", json={
            "name": "   ",
            "steps": SAMPLE_STEPS,
        })
        assert r.status_code == 400
        assert "name" in r.get_json()["error"].lower()

    def test_create_bad_category(self, client):
        """Create with invalid category returns 400."""
        r = client.post("/api/playbooks", json={
            "name": "Bad Cat",
            "steps": SAMPLE_STEPS,
            "category": "nonexistent",
        })
        assert r.status_code == 400
        assert "invalid category" in r.get_json()["error"].lower()

    def test_create_bad_step_type(self, client):
        """Create with invalid step type returns 400."""
        r = client.post("/api/playbooks", json={
            "name": "Bad Step",
            "steps": [{"title": "Invalid", "type": "zzzz"}],
        })
        assert r.status_code == 400
        assert "invalid type" in r.get_json()["error"].lower()

    def test_create_step_missing_title(self, client):
        """Create with step missing title returns 400."""
        r = client.post("/api/playbooks", json={
            "name": "No Title",
            "steps": [{"type": "discover"}],
        })
        assert r.status_code == 400
        assert "missing a title" in r.get_json()["error"].lower()

    def test_create_step_not_object(self, client):
        """Create with step that is not a dict returns 400."""
        r = client.post("/api/playbooks", json={
            "name": "String Step",
            "steps": ["just a string"],
        })
        assert r.status_code == 400
        assert "must be an object" in r.get_json()["error"].lower()

    def test_create_steps_not_array(self, client):
        """Create with steps not an array returns 400."""
        r = client.post("/api/playbooks", json={
            "name": "Not Array",
            "steps": "nope",
        })
        assert r.status_code == 400
        assert "must be a json array" in r.get_json()["error"].lower()

    def test_update_bad_category(self, client):
        """Update with invalid category returns 400."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.put(f"/api/playbooks/{pb_id}", json={"category": "bogus"})
        assert r.status_code == 400
        assert "invalid category" in r.get_json()["error"].lower()

    def test_update_empty_name(self, client):
        """Update with empty name returns 400."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.put(f"/api/playbooks/{pb_id}", json={"name": "   "})
        assert r.status_code == 400
        assert "name" in r.get_json()["error"].lower()

    def test_update_bad_steps(self, client):
        """Update with invalid steps returns 400."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.put(f"/api/playbooks/{pb_id}", json={
            "steps": [{"title": "Bad", "type": "invalid_type"}],
        })
        assert r.status_code == 400

    def test_step_default_type_is_custom(self, client):
        """Step without type defaults to 'custom'."""
        r = client.post("/api/playbooks", json={
            "name": "Default Type",
            "steps": [{"title": "No type specified"}],
        })
        assert r.status_code == 201
        assert r.get_json()["steps"][0]["type"] == "custom"

    def test_get_run_stats_after_runs(self, playbook_project):
        """Get playbook includes accurate run_stats after runs."""
        client = playbook_project["client"]
        pid = playbook_project["project_id"]
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]

        # Start 3 runs: complete 1, abandon 1, leave 1 active
        r1 = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run1_id = r1.get_json()["id"]
        for i in range(3):
            client.put(f"/api/playbooks/runs/{run1_id}/step/{i}", json={"completed": True})

        r2 = client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})
        run2_id = r2.get_json()["id"]
        client.put(f"/api/playbooks/runs/{run2_id}/status", json={"status": "abandoned"})

        client.post(f"/api/playbooks/{pb_id}/run", json={"project_id": pid})

        r = client.get(f"/api/playbooks/{pb_id}")
        stats = r.get_json()["run_stats"]
        assert stats["total_runs"] == 3
        assert stats["completed_runs"] == 1
        assert stats["abandoned_runs"] == 1
        assert stats["active_runs"] == 1

    def test_update_playbook_metadata(self, client):
        """Update playbook metadata field."""
        r = _create_playbook(client)
        pb_id = r.get_json()["id"]
        r = client.put(f"/api/playbooks/{pb_id}", json={
            "metadata": {"tags": ["v2", "improved"]},
        })
        assert r.status_code == 200
        assert r.get_json()["metadata"]["tags"] == ["v2", "improved"]
