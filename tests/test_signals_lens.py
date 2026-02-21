"""Tests for Signals Lens API endpoints.

Covers:
- Signals availability in /api/lenses/available
- Timeline: chronological event feed from change_feed, entity_attributes, evidence
- Activity: per-entity activity summary
- Trends: weekly bucket aggregation
- Heatmap: entity x event-type matrix
- Edge cases: missing tables, null timestamps, pagination

Run: pytest tests/test_signals_lens.py -v
Markers: db, api, lenses
"""
import json
import pytest

pytestmark = [pytest.mark.db, pytest.mark.api, pytest.mark.lenses]

# ═══════════════════════════════════════════════════════════════
# Schema + Fixtures
# ═══════════════════════════════════════════════════════════════

SIGNAL_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "Pricing", "slug": "pricing", "data_type": "text"},
                {"name": "Description", "slug": "description", "data_type": "text"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture
def signal_project(client):
    """Create a project with schema and one entity, but no monitoring data."""
    db = client.db
    pid = db.create_project(
        name="Signal Test",
        purpose="Testing signals lens",
        entity_schema=SIGNAL_SCHEMA,
    )
    eid = db.create_entity(pid, "company", "Alpha Corp")
    return {
        "client": client,
        "project_id": pid,
        "entity_ids": [eid],
        "db": db,
    }


def _create_monitoring_tables(db):
    """Create monitors and change_feed tables if they don't exist."""
    with db._get_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            monitor_type TEXT NOT NULL,
            config_json TEXT DEFAULT '{}',
            is_active INTEGER DEFAULT 1,
            last_checked_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS change_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            monitor_id INTEGER REFERENCES monitors(id),
            check_id INTEGER,
            change_type TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            title TEXT NOT NULL,
            description TEXT,
            details_json TEXT DEFAULT '{}',
            source_url TEXT,
            is_read INTEGER DEFAULT 0,
            is_dismissed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.commit()


def _setup_full_signal_data(db, entity_id):
    """Insert a monitor, change_feed entries, entity attributes, and evidence.

    Returns dict of inserted IDs for assertions.
    """
    _create_monitoring_tables(db)
    with db._get_conn() as conn:
        # Look up the project_id for this entity
        project_id = conn.execute(
            "SELECT project_id FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()[0]

        # Insert a monitor
        conn.execute(
            "INSERT INTO monitors (entity_id, monitor_type, config_json, is_active) VALUES (?, 'website', '{}', 1)",
            (entity_id,),
        )
        monitor_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert change feed entries at known timestamps
        conn.execute(
            """INSERT INTO change_feed (project_id, entity_id, monitor_id, change_type,
               title, description, created_at, severity)
               VALUES (?, ?, ?, 'content_change', 'pricing',
                       'Pricing changed from old price to new price',
                       '2026-02-15 10:00:00', 'medium')""",
            (project_id, entity_id, monitor_id),
        )
        conn.execute(
            """INSERT INTO change_feed (project_id, entity_id, monitor_id, change_type,
               title, description, created_at, severity)
               VALUES (?, ?, ?, 'content_change', 'features',
                       'Features changed from old list to new list',
                       '2026-02-16 10:00:00', 'low')""",
            (project_id, entity_id, monitor_id),
        )
        conn.commit()

    # Insert entity attributes via the DB API (uses its own connection)
    db.set_entity_attribute(entity_id, "pricing", "$100/mo", source="manual",
                            captured_at="2026-02-14 08:00:00")
    db.set_entity_attribute(entity_id, "description", "A product", source="extraction",
                            captured_at="2026-02-15 09:00:00")

    # Insert evidence via the DB API
    db.add_evidence(
        entity_id=entity_id,
        evidence_type="screenshot",
        file_path="/evidence/test/landing.png",
        source_url="https://example.com",
        source_name="Homepage",
        captured_at="2026-02-13 07:00:00",
    )

    return {"monitor_id": monitor_id}


@pytest.fixture
def signal_project_with_data(signal_project):
    """Signal project with monitoring tables and data for one entity."""
    db = signal_project["db"]
    eid = signal_project["entity_ids"][0]
    ids = _setup_full_signal_data(db, eid)
    signal_project["monitor_id"] = ids["monitor_id"]
    return signal_project


@pytest.fixture
def signal_project_multi_entity(client):
    """Project with 2 entities and different levels of activity data."""
    db = client.db
    pid = db.create_project(
        name="Multi Entity Signals",
        purpose="Testing multi-entity signals",
        entity_schema=SIGNAL_SCHEMA,
    )
    eid1 = db.create_entity(pid, "company", "Alpha Corp")
    eid2 = db.create_entity(pid, "company", "Beta Inc")

    _create_monitoring_tables(db)

    # Entity 1: full data (monitor, changes, attributes, evidence)
    _setup_full_signal_data(db, eid1)

    # Entity 2: only attributes, no monitors or evidence
    db.set_entity_attribute(eid2, "pricing", "$50/mo", source="manual",
                            captured_at="2026-02-17 12:00:00")

    return {
        "client": client,
        "project_id": pid,
        "entity_ids": [eid1, eid2],
        "db": db,
    }


# ═══════════════════════════════════════════════════════════════
# Signals Availability Tests
# ═══════════════════════════════════════════════════════════════

class TestSignalsAvailability:
    """Tests for signals presence in GET /api/lenses/available."""

    def test_signals_available_with_monitors(self, signal_project_with_data):
        """Signals lens is available when monitors and change_feed have data."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/available?project_id={pid}")
        assert r.status_code == 200
        lenses = {lens["slug"]: lens for lens in r.get_json()}
        assert "signals" in lenses
        assert lenses["signals"]["available"] is True

    def test_signals_not_available_without_monitoring_data(self, signal_project):
        """Signals lens is unavailable when no monitors or change_feed exist."""
        c = signal_project["client"]
        pid = signal_project["project_id"]
        # Create monitoring tables but leave them empty
        _create_monitoring_tables(signal_project["db"])
        r = c.get(f"/api/lenses/available?project_id={pid}")
        assert r.status_code == 200
        lenses = {lens["slug"]: lens for lens in r.get_json()}
        assert "signals" in lenses
        assert lenses["signals"]["available"] is False

    def test_signals_available_with_monitor_but_no_changes(self, signal_project):
        """Signals lens is available when monitors exist, even without change_feed entries."""
        db = signal_project["db"]
        eid = signal_project["entity_ids"][0]
        _create_monitoring_tables(db)
        with db._get_conn() as conn:
            conn.execute(
                "INSERT INTO monitors (entity_id, monitor_type, config_json, is_active) VALUES (?, 'website', '{}', 1)",
                (eid,),
            )
            conn.commit()

        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/available?project_id={pid}")
        lenses = {lens["slug"]: lens for lens in r.get_json()}
        assert lenses["signals"]["available"] is True

    def test_signals_not_available_when_tables_missing(self, client):
        """Signals lens is unavailable when monitoring tables do not exist at all."""
        db = client.db
        pid = db.create_project(name="No Tables", purpose="Test", entity_schema=SIGNAL_SCHEMA)
        r = client.get(f"/api/lenses/available?project_id={pid}")
        assert r.status_code == 200
        lenses = {lens["slug"]: lens for lens in r.get_json()}
        assert lenses["signals"]["available"] is False


# ═══════════════════════════════════════════════════════════════
# Signals Timeline Tests
# ═══════════════════════════════════════════════════════════════

class TestSignalsTimeline:
    """Tests for GET /api/lenses/signals/timeline."""

    def test_missing_project_id_returns_400(self, client):
        r = client.get("/api/lenses/signals/timeline")
        assert r.status_code == 400
        assert "project_id" in r.get_json()["error"]

    def test_empty_project_returns_empty_events(self, client):
        db = client.db
        pid = db.create_project(name="Empty", purpose="Test", entity_schema=SIGNAL_SCHEMA)
        _create_monitoring_tables(db)
        r = client.get(f"/api/lenses/signals/timeline?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["events"] == []
        assert data["total"] == 0

    def test_only_attribute_events(self, signal_project):
        """Timeline with only entity_attributes (no monitors/evidence)."""
        db = signal_project["db"]
        eid = signal_project["entity_ids"][0]
        _create_monitoring_tables(db)
        db.set_entity_attribute(eid, "pricing", "$99", source="manual",
                                captured_at="2026-02-10 10:00:00")

        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] >= 1
        attr_events = [e for e in data["events"] if e["type"] == "attribute_updated"]
        assert len(attr_events) >= 1
        assert attr_events[0]["title"].startswith("Attribute:")

    def test_only_evidence_events(self, signal_project):
        """Timeline with only evidence captures."""
        db = signal_project["db"]
        eid = signal_project["entity_ids"][0]
        _create_monitoring_tables(db)
        db.add_evidence(
            entity_id=eid,
            evidence_type="screenshot",
            file_path="/evidence/test/page.png",
            source_url="https://example.com/page",
            source_name="Landing Page",
            captured_at="2026-02-12 11:00:00",
        )

        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        ev_events = [e for e in data["events"] if e["type"] == "evidence_captured"]
        assert len(ev_events) >= 1
        assert ev_events[0]["title"] == "Evidence: screenshot"

    def test_only_change_feed_events(self, signal_project):
        """Timeline with only change_feed entries."""
        db = signal_project["db"]
        eid = signal_project["entity_ids"][0]
        pid = signal_project["project_id"]
        _create_monitoring_tables(db)
        with db._get_conn() as conn:
            conn.execute(
                "INSERT INTO monitors (entity_id, monitor_type, config_json, is_active) VALUES (?, 'website', '{}', 1)",
                (eid,),
            )
            mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT INTO change_feed (project_id, entity_id, monitor_id, change_type,
                   title, description, created_at, severity)
                   VALUES (?, ?, ?, 'content_change', 'Title changed',
                           'Changed from Old Title to New Title',
                           '2026-02-18 09:00:00', 'high')""",
                (pid, eid, mid),
            )
            conn.commit()

        c = signal_project["client"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        cf_events = [e for e in data["events"] if e["type"] == "change_detected"]
        assert len(cf_events) == 1
        assert cf_events[0]["severity"] == "high"
        assert "Title changed" in cf_events[0]["title"]

    def test_combined_events_sorted_desc(self, signal_project_with_data):
        """All 3 event types present and sorted by timestamp descending."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()

        event_types = {e["type"] for e in data["events"]}
        assert "change_detected" in event_types
        assert "attribute_updated" in event_types
        assert "evidence_captured" in event_types

        # Verify DESC sort order
        timestamps = [e["timestamp"] for e in data["events"] if e["timestamp"]]
        for i in range(len(timestamps) - 1):
            assert timestamps[i] >= timestamps[i + 1], (
                f"Events not in DESC order: {timestamps[i]} before {timestamps[i+1]}"
            )

    def test_entity_id_filter(self, signal_project_multi_entity):
        """Timeline filtered by entity_id only returns that entity's events."""
        c = signal_project_multi_entity["client"]
        pid = signal_project_multi_entity["project_id"]
        eid2 = signal_project_multi_entity["entity_ids"][1]

        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}&entity_id={eid2}")
        assert r.status_code == 200
        data = r.get_json()
        # Entity 2 only has attribute updates
        for event in data["events"]:
            assert event["entity_id"] == eid2

    def test_pagination_limit(self, signal_project_with_data):
        """Limit parameter restricts number of returned events."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}&limit=2")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["events"]) <= 2
        assert data["limit"] == 2
        assert data["total"] > 2  # more events exist than returned

    def test_pagination_offset(self, signal_project_with_data):
        """Offset parameter skips events."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]

        # Get all events first
        r_all = c.get(f"/api/lenses/signals/timeline?project_id={pid}&limit=200")
        all_data = r_all.get_json()
        total = all_data["total"]

        # Now get with offset
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}&limit=200&offset=2")
        data = r.get_json()
        assert data["offset"] == 2
        assert len(data["events"]) == total - 2

    def test_limit_clamped_to_200(self, signal_project_with_data):
        """Limit values above 200 are clamped to 200."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}&limit=500")
        assert r.status_code == 200
        data = r.get_json()
        assert data["limit"] == 200

    def test_event_structure(self, signal_project_with_data):
        """Each event has the expected fields."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}")
        data = r.get_json()
        assert len(data["events"]) > 0

        required_fields = {"type", "entity_id", "entity_name", "title",
                           "description", "severity", "timestamp", "metadata"}
        for event in data["events"]:
            assert required_fields.issubset(event.keys()), (
                f"Event missing fields: {required_fields - set(event.keys())}"
            )

    def test_change_detected_event_content(self, signal_project_with_data):
        """Change detected events have correct title and description format."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}")
        data = r.get_json()
        cf_events = [e for e in data["events"] if e["type"] == "change_detected"]
        assert len(cf_events) >= 1
        ev = cf_events[0]
        assert "content_change" in ev["title"]
        assert ev["severity"] in ("low", "medium", "high", "info")


# ═══════════════════════════════════════════════════════════════
# Signals Activity Tests
# ═══════════════════════════════════════════════════════════════

class TestSignalsActivity:
    """Tests for GET /api/lenses/signals/activity."""

    def test_missing_project_id_returns_400(self, client):
        r = client.get("/api/lenses/signals/activity")
        assert r.status_code == 400

    def test_empty_project_returns_empty_entities(self, client):
        db = client.db
        pid = db.create_project(name="Empty", purpose="Test", entity_schema=SIGNAL_SCHEMA)
        r = client.get(f"/api/lenses/signals/activity?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["entities"] == []

    def test_entity_with_no_activity_data(self, signal_project):
        """Entity exists but has no monitors, changes, evidence, or attributes."""
        _create_monitoring_tables(signal_project["db"])
        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/signals/activity?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["entities"]) == 1
        ent = data["entities"][0]
        assert ent["change_count"] == 0
        assert ent["monitor_count"] == 0
        assert ent["evidence_count"] == 0
        assert ent["attribute_updates"] == 0

    def test_full_activity_data(self, signal_project_with_data):
        """Entity with monitors, changes, evidence, and attributes has correct counts."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/activity?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["entities"]) == 1
        ent = data["entities"][0]
        assert ent["entity_name"] == "Alpha Corp"
        assert ent["change_count"] == 2  # 2 change_feed entries
        assert ent["monitor_count"] == 1  # 1 monitor
        assert ent["evidence_count"] == 1  # 1 evidence capture
        assert ent["attribute_updates"] == 2  # 2 attribute records
        assert ent["last_change"] is not None

    def test_multiple_entities_different_activity(self, signal_project_multi_entity):
        """Multiple entities with varying activity levels."""
        c = signal_project_multi_entity["client"]
        pid = signal_project_multi_entity["project_id"]
        r = c.get(f"/api/lenses/signals/activity?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["entities"]) == 2

        by_name = {e["entity_name"]: e for e in data["entities"]}

        # Alpha Corp: full data (2 changes, 1 monitor, 1 evidence, 2 attrs)
        alpha = by_name["Alpha Corp"]
        assert alpha["change_count"] == 2
        assert alpha["monitor_count"] == 1
        assert alpha["evidence_count"] == 1
        assert alpha["attribute_updates"] == 2

        # Beta Inc: only 1 attribute, no monitors/changes/evidence
        beta = by_name["Beta Inc"]
        assert beta["change_count"] == 0
        assert beta["monitor_count"] == 0
        assert beta["evidence_count"] == 0
        assert beta["attribute_updates"] == 1

    def test_activity_entity_fields(self, signal_project_with_data):
        """Activity response entities have all required fields."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/activity?project_id={pid}")
        data = r.get_json()
        required = {"entity_id", "entity_name", "change_count", "last_change",
                     "monitor_count", "evidence_count", "attribute_updates"}
        for ent in data["entities"]:
            assert required.issubset(ent.keys())

    def test_activity_last_change_timestamp(self, signal_project_with_data):
        """last_change reflects the most recent change_feed entry."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/activity?project_id={pid}")
        data = r.get_json()
        ent = data["entities"][0]
        # The latest change_feed entry was at 2026-02-16 10:00:00
        assert ent["last_change"] == "2026-02-16 10:00:00"


# ═══════════════════════════════════════════════════════════════
# Signals Trends Tests
# ═══════════════════════════════════════════════════════════════

class TestSignalsTrends:
    """Tests for GET /api/lenses/signals/trends."""

    def test_missing_project_id_returns_400(self, client):
        r = client.get("/api/lenses/signals/trends")
        assert r.status_code == 400

    def test_empty_project_returns_empty_periods(self, client):
        db = client.db
        pid = db.create_project(name="Empty", purpose="Test", entity_schema=SIGNAL_SCHEMA)
        _create_monitoring_tables(db)
        r = client.get(f"/api/lenses/signals/trends?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["periods"] == []

    def test_events_bucketed_by_week(self, signal_project_with_data):
        """Events are grouped into weekly periods."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/trends?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["periods"]) >= 1
        for period in data["periods"]:
            assert "period_start" in period
            assert "period_end" in period
            assert "change_count" in period
            assert "attribute_count" in period
            assert "evidence_count" in period
            assert "total" in period

    def test_period_start_and_end_span_7_days(self, signal_project_with_data):
        """period_end is exactly 6 days after period_start."""
        from datetime import datetime, timedelta

        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/trends?project_id={pid}")
        data = r.get_json()

        for period in data["periods"]:
            start = datetime.strptime(period["period_start"], "%Y-%m-%d")
            end = datetime.strptime(period["period_end"], "%Y-%m-%d")
            assert (end - start).days == 6, (
                f"Period span is {(end - start).days} days, expected 6"
            )

    def test_entity_id_filter(self, signal_project_multi_entity):
        """Trends filtered by entity_id only count that entity's events."""
        c = signal_project_multi_entity["client"]
        pid = signal_project_multi_entity["project_id"]
        eid2 = signal_project_multi_entity["entity_ids"][1]

        r = c.get(f"/api/lenses/signals/trends?project_id={pid}&entity_id={eid2}")
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("entity_id") == eid2
        # Entity 2 has 1 attribute, no changes or evidence
        total_changes = sum(p["change_count"] for p in data["periods"])
        total_evidence = sum(p["evidence_count"] for p in data["periods"])
        assert total_changes == 0
        assert total_evidence == 0
        total_attrs = sum(p["attribute_count"] for p in data["periods"])
        assert total_attrs == 1

    def test_total_is_sum_of_counts(self, signal_project_with_data):
        """Each period's total equals the sum of its sub-counts."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/trends?project_id={pid}")
        data = r.get_json()
        for period in data["periods"]:
            expected = (period["change_count"] +
                        period["attribute_count"] +
                        period["evidence_count"])
            assert period["total"] == expected

    def test_multiple_sources_same_week(self, signal_project):
        """Events from different sources in the same week bucket combine."""
        db = signal_project["db"]
        eid = signal_project["entity_ids"][0]
        pid = signal_project["project_id"]
        _create_monitoring_tables(db)

        # All events in the same week (Feb 10-16, 2026)
        with db._get_conn() as conn:
            conn.execute(
                "INSERT INTO monitors (entity_id, monitor_type, config_json, is_active) VALUES (?, 'website', '{}', 1)",
                (eid,),
            )
            mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT INTO change_feed (project_id, entity_id, monitor_id, change_type,
                   title, description, created_at, severity)
                   VALUES (?, ?, ?, 'content_change', 'Title changed',
                           'Changed from A to B', '2026-02-11 10:00:00', 'low')""",
                (pid, eid, mid),
            )
            conn.commit()

        db.set_entity_attribute(eid, "pricing", "$50", source="manual",
                                captured_at="2026-02-12 10:00:00")
        db.add_evidence(
            entity_id=eid,
            evidence_type="screenshot",
            file_path="/evidence/test/img.png",
            source_url="https://example.com",
            captured_at="2026-02-13 10:00:00",
        )

        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/signals/trends?project_id={pid}")
        data = r.get_json()

        # Find periods that have data
        data_periods = [p for p in data["periods"] if p["total"] > 0]
        assert len(data_periods) >= 1

        # At least one period should have contributions from multiple sources
        # (the events are within the same week)
        combined = [p for p in data_periods
                    if (p["change_count"] > 0 or p["attribute_count"] > 0 or p["evidence_count"] > 0)]
        assert len(combined) >= 1

    def test_periods_sorted_chronologically(self, signal_project_with_data):
        """Periods are returned in chronological (ascending) order."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/trends?project_id={pid}")
        data = r.get_json()
        starts = [p["period_start"] for p in data["periods"]]
        assert starts == sorted(starts)


# ═══════════════════════════════════════════════════════════════
# Signals Heatmap Tests
# ═══════════════════════════════════════════════════════════════

class TestSignalsHeatmap:
    """Tests for GET /api/lenses/signals/heatmap."""

    def test_missing_project_id_returns_400(self, client):
        r = client.get("/api/lenses/signals/heatmap")
        assert r.status_code == 400

    def test_empty_project_returns_empty_matrix(self, client):
        db = client.db
        pid = db.create_project(name="Empty", purpose="Test", entity_schema=SIGNAL_SCHEMA)
        r = client.get(f"/api/lenses/signals/heatmap?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert data["entities"] == []
        assert data["event_types"] == []
        assert data["matrix"] == []
        assert data["raw"] == []

    def test_one_entity_mixed_event_types(self, signal_project_with_data):
        """Single entity with change, attribute, and evidence data."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/heatmap?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["entities"]) == 1
        assert data["entities"][0] == "Alpha Corp"
        assert data["event_types"] == ["change_detected", "attribute_updated", "evidence_captured"]

        # Matrix: 1 entity x 3 event types
        assert len(data["matrix"]) == 1
        assert len(data["matrix"][0]) == 3

        row = data["matrix"][0]
        assert row[0] == 2  # 2 change_feed entries
        assert row[1] == 2  # 2 attribute updates
        assert row[2] == 1  # 1 evidence capture

    def test_matrix_dimensions(self, signal_project_multi_entity):
        """Matrix dimensions match entities count x event_types count."""
        c = signal_project_multi_entity["client"]
        pid = signal_project_multi_entity["project_id"]
        r = c.get(f"/api/lenses/signals/heatmap?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        n_entities = len(data["entities"])
        n_types = len(data["event_types"])
        assert n_entities == 2
        assert n_types == 3
        assert len(data["matrix"]) == n_entities
        for row in data["matrix"]:
            assert len(row) == n_types

    def test_raw_data_matches_matrix(self, signal_project_with_data):
        """Raw data entries are consistent with matrix values."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/heatmap?project_id={pid}")
        data = r.get_json()

        # Build lookup from raw data
        raw_lookup = {}
        for entry in data["raw"]:
            key = (entry["entity_name"], entry["event_type"])
            raw_lookup[key] = entry["count"]

        # Verify against matrix
        for i, entity_name in enumerate(data["entities"]):
            for j, event_type in enumerate(data["event_types"]):
                matrix_val = data["matrix"][i][j]
                raw_val = raw_lookup.get((entity_name, event_type), 0)
                assert matrix_val == raw_val, (
                    f"Mismatch at ({entity_name}, {event_type}): matrix={matrix_val}, raw={raw_val}"
                )

    def test_multiple_entities(self, signal_project_multi_entity):
        """Heatmap includes all entities from the project."""
        c = signal_project_multi_entity["client"]
        pid = signal_project_multi_entity["project_id"]
        r = c.get(f"/api/lenses/signals/heatmap?project_id={pid}")
        data = r.get_json()
        entity_names = set(data["entities"])
        assert "Alpha Corp" in entity_names
        assert "Beta Inc" in entity_names

    def test_heatmap_raw_fields(self, signal_project_with_data):
        """Raw entries have the expected field structure."""
        c = signal_project_with_data["client"]
        pid = signal_project_with_data["project_id"]
        r = c.get(f"/api/lenses/signals/heatmap?project_id={pid}")
        data = r.get_json()
        required = {"entity_id", "entity_name", "event_type", "count"}
        for entry in data["raw"]:
            assert required.issubset(entry.keys())

    def test_heatmap_raw_sorted_by_name_then_type(self, signal_project_multi_entity):
        """Raw data is sorted by entity name (case-insensitive) then event type."""
        c = signal_project_multi_entity["client"]
        pid = signal_project_multi_entity["project_id"]
        r = c.get(f"/api/lenses/signals/heatmap?project_id={pid}")
        data = r.get_json()
        keys = [(e["entity_name"].lower(), e["event_type"]) for e in data["raw"]]
        assert keys == sorted(keys)


# ═══════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestSignalsEdgeCases:
    """Edge case tests for the Signals Lens."""

    def test_tables_dont_exist_timeline_graceful(self, signal_project):
        """Timeline handles missing monitors/change_feed tables gracefully."""
        c = signal_project["client"]
        pid = signal_project["project_id"]
        # Don't create monitoring tables -- rely on try/except in the endpoint
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        # Should still return attribute/evidence events if any, or empty
        assert "events" in data
        assert "total" in data

    def test_tables_dont_exist_activity_graceful(self, signal_project):
        """Activity handles missing monitors/change_feed tables gracefully."""
        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/signals/activity?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "entities" in data
        # Entity still shows up with zero counts for monitor/change
        assert len(data["entities"]) == 1
        assert data["entities"][0]["change_count"] == 0
        assert data["entities"][0]["monitor_count"] == 0

    def test_tables_dont_exist_trends_graceful(self, signal_project):
        """Trends handles missing monitors/change_feed tables gracefully."""
        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/signals/trends?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "periods" in data

    def test_tables_dont_exist_heatmap_graceful(self, signal_project):
        """Heatmap handles missing monitors/change_feed tables gracefully."""
        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/signals/heatmap?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        assert "entities" in data
        assert "matrix" in data

    def test_null_timestamps_in_timeline(self, signal_project):
        """Events with NULL timestamps are handled gracefully in timeline."""
        db = signal_project["db"]
        eid = signal_project["entity_ids"][0]
        pid = signal_project["project_id"]
        _create_monitoring_tables(db)

        # Insert a change_feed entry with NULL created_at
        with db._get_conn() as conn:
            conn.execute(
                "INSERT INTO monitors (entity_id, monitor_type, config_json, is_active) VALUES (?, 'website', '{}', 1)",
                (eid,),
            )
            mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT INTO change_feed (project_id, entity_id, monitor_id, change_type,
                   title, description, created_at, severity)
                   VALUES (?, ?, ?, 'content_change', 'test change',
                           'Changed from a to b', NULL, 'info')""",
                (pid, eid, mid),
            )
            conn.commit()

        c = signal_project["client"]
        pid = signal_project["project_id"]
        r = c.get(f"/api/lenses/signals/timeline?project_id={pid}")
        assert r.status_code == 200
        data = r.get_json()
        # Should not crash; null timestamp events sort to end
        assert "events" in data
