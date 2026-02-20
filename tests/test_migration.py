"""Tests for Company → Entity migration (core/migration.py + API endpoint)."""
import pytest

from core.migration import migrate_companies_to_entities

pytestmark = [pytest.mark.entities, pytest.mark.api]


# ---------------------------------------------------------------------------
# Fixtures (use conftest's app/client which handle CSRF + temp DB)
# ---------------------------------------------------------------------------

@pytest.fixture
def proj(client):
    """Create a test project and return its id."""
    return client.db.create_project(name="Migration Test", purpose="testing")


def _insert_company(db, project_id, name, url="https://example.com", **kwargs):
    """Insert a company directly into the companies table."""
    with db._get_conn() as conn:
        slug = name.lower().replace(" ", "_")
        conn.execute(
            """INSERT INTO companies
               (project_id, slug, name, url, what, target, geography,
                pricing_model, has_free_tier, is_starred, is_deleted, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'active')""",
            (
                project_id,
                slug,
                name,
                url,
                kwargs.get("what", "A test company"),
                kwargs.get("target", "SMBs"),
                kwargs.get("geography", "US"),
                kwargs.get("pricing_model", "subscription"),
                kwargs.get("has_free_tier", 0),
                kwargs.get("is_starred", 0),
            ),
        )
        company_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        return company_id


def _insert_company_source(db, company_id, url, source_type="research"):
    """Insert a company source record."""
    with db._get_conn() as conn:
        conn.execute(
            """INSERT INTO company_sources (company_id, url, source_type)
               VALUES (?, ?, ?)""",
            (company_id, url, source_type),
        )
        conn.commit()


class TestMigrationDryRun:
    """Test dry_run mode — counts but doesn't write."""

    def test_dry_run_counts_companies(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp")
        _insert_company(client.db, proj, "Beta Inc", url="https://beta.com")

        resp = client.post("/api/migrate/companies",
                           json={"project_id": proj, "dry_run": True})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["dry_run"] is True
        assert data["companies_found"] == 2
        assert data["entities_created"] == 2
        assert data["attributes_created"] > 0

    def test_dry_run_doesnt_create_entities(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp")

        client.post("/api/migrate/companies",
                     json={"project_id": proj, "dry_run": True})

        with client.db._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM entities WHERE project_id = ?",
                (proj,),
            ).fetchone()["cnt"]
        assert count == 0


class TestMigrationBasic:
    """Test actual migration of company data."""

    def test_migrate_single_company(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp", what="Cloud platform",
                        target="Enterprise", pricing_model="subscription")

        resp = client.post("/api/migrate/companies",
                           json={"project_id": proj})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["entities_created"] == 1
        assert data["attributes_created"] >= 4  # website, description, target_market, pricing_model

    def test_entity_has_correct_type(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp")

        client.post("/api/migrate/companies",
                     json={"project_id": proj})

        with client.db._get_conn() as conn:
            entity = conn.execute(
                "SELECT * FROM entities WHERE project_id = ? AND name = 'Acme Corp'",
                (proj,),
            ).fetchone()

        assert entity is not None
        assert entity["type_slug"] == "company"
        assert entity["source"] == "migration"

    def test_attributes_migrated(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp",
                        what="Cloud platform",
                        geography="US, UK",
                        pricing_model="freemium")

        client.post("/api/migrate/companies",
                     json={"project_id": proj})

        with client.db._get_conn() as conn:
            entity = conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND name = 'Acme Corp'",
                (proj,),
            ).fetchone()
            attrs = conn.execute(
                "SELECT attr_slug, value, source FROM entity_attributes WHERE entity_id = ?",
                (entity["id"],),
            ).fetchall()

        attr_map = {a["attr_slug"]: a for a in attrs}
        assert "description" in attr_map
        assert attr_map["description"]["value"] == "Cloud platform"
        assert "geography" in attr_map
        assert attr_map["geography"]["value"] == "US, UK"
        assert "pricing_model" in attr_map
        assert attr_map["pricing_model"]["value"] == "freemium"
        # All should have source='migration'
        for a in attrs:
            assert a["source"] == "migration"

    def test_company_url_becomes_website_attribute(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp", url="https://acme.com")

        client.post("/api/migrate/companies",
                     json={"project_id": proj})

        with client.db._get_conn() as conn:
            entity = conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND name = 'Acme Corp'",
                (proj,),
            ).fetchone()
            website = conn.execute(
                "SELECT value FROM entity_attributes WHERE entity_id = ? AND attr_slug = 'website'",
                (entity["id"],),
            ).fetchone()

        assert website is not None
        assert website["value"] == "https://acme.com"

    def test_migrate_multiple_companies(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp")
        _insert_company(client.db, proj, "Beta Inc", url="https://beta.com")
        _insert_company(client.db, proj, "Gamma Ltd", url="https://gamma.com")

        resp = client.post("/api/migrate/companies",
                           json={"project_id": proj})
        data = resp.get_json()
        assert data["entities_created"] == 3


class TestMigrationIdempotency:
    """Test that migration can be run multiple times safely."""

    def test_second_run_skips_existing(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp")

        # First run
        resp1 = client.post("/api/migrate/companies",
                            json={"project_id": proj})
        data1 = resp1.get_json()
        assert data1["entities_created"] == 1
        assert data1["skipped_already_migrated"] == 0

        # Second run
        resp2 = client.post("/api/migrate/companies",
                            json={"project_id": proj})
        data2 = resp2.get_json()
        assert data2["entities_created"] == 0
        assert data2["skipped_already_migrated"] == 1

    def test_idempotent_no_duplicate_entities(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp")

        # Run twice
        client.post("/api/migrate/companies",
                     json={"project_id": proj})
        client.post("/api/migrate/companies",
                     json={"project_id": proj})

        with client.db._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM entities WHERE project_id = ? AND name = 'Acme Corp'",
                (proj,),
            ).fetchone()["cnt"]
        assert count == 1


class TestMigrationEvidence:
    """Test migration of company_sources to evidence."""

    def test_company_sources_become_evidence(self, client, proj):
        cid = _insert_company(client.db, proj, "Acme Corp")
        _insert_company_source(client.db, cid, "https://acme.com/product", "research")
        _insert_company_source(client.db, cid, "https://acme.com/pricing", "manual")

        resp = client.post("/api/migrate/companies",
                           json={"project_id": proj})
        data = resp.get_json()
        assert data["evidence_migrated"] == 2

    def test_evidence_has_correct_fields(self, client, proj):
        cid = _insert_company(client.db, proj, "Acme Corp")
        _insert_company_source(client.db, cid, "https://acme.com/product", "research")

        client.post("/api/migrate/companies",
                     json={"project_id": proj})

        with client.db._get_conn() as conn:
            entity = conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND name = 'Acme Corp'",
                (proj,),
            ).fetchone()
            evidence = conn.execute(
                "SELECT * FROM evidence WHERE entity_id = ?",
                (entity["id"],),
            ).fetchone()

        assert evidence is not None
        assert evidence["source_url"] == "https://acme.com/product"
        assert evidence["evidence_type"] == "page_archive"


class TestMigrationMetadata:
    """Test that metadata (stars, status, tags, etc.) is preserved."""

    def test_starred_preserved(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp", is_starred=1)

        client.post("/api/migrate/companies",
                     json={"project_id": proj})

        with client.db._get_conn() as conn:
            entity = conn.execute(
                "SELECT is_starred FROM entities WHERE project_id = ? AND name = 'Acme Corp'",
                (proj,),
            ).fetchone()
        assert entity["is_starred"] == 1

    def test_null_values_not_migrated_as_attributes(self, client, proj):
        """NULL company fields should not create entity attributes."""
        _insert_company(client.db, proj, "Acme Corp")

        client.post("/api/migrate/companies",
                     json={"project_id": proj})

        with client.db._get_conn() as conn:
            entity = conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND name = 'Acme Corp'",
                (proj,),
            ).fetchone()
            # linkedin_url, logo_url etc. were NULL — should not have attr rows
            linkedin = conn.execute(
                "SELECT * FROM entity_attributes WHERE entity_id = ? AND attr_slug = 'linkedin_url'",
                (entity["id"],),
            ).fetchone()
        assert linkedin is None


class TestMigrationEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_project_id_returns_400(self, client):
        resp = client.post("/api/migrate/companies", json={})
        assert resp.status_code == 400

    def test_empty_project_returns_zero_stats(self, client, proj):
        resp = client.post("/api/migrate/companies",
                           json={"project_id": proj})
        data = resp.get_json()
        assert data["companies_found"] == 0
        assert data["entities_created"] == 0

    def test_deleted_companies_not_migrated(self, client, proj):
        cid = _insert_company(client.db, proj, "Acme Corp")
        # Soft-delete the company
        with client.db._get_conn() as conn:
            conn.execute("UPDATE companies SET is_deleted = 1 WHERE id = ?", (cid,))
            conn.commit()

        resp = client.post("/api/migrate/companies",
                           json={"project_id": proj})
        data = resp.get_json()
        assert data["companies_found"] == 0

    def test_has_free_tier_migrated_as_string(self, client, proj):
        _insert_company(client.db, proj, "Acme Corp", has_free_tier=1)

        client.post("/api/migrate/companies",
                     json={"project_id": proj})

        with client.db._get_conn() as conn:
            entity = conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND name = 'Acme Corp'",
                (proj,),
            ).fetchone()
            attr = conn.execute(
                "SELECT value FROM entity_attributes WHERE entity_id = ? AND attr_slug = 'has_free_tier'",
                (entity["id"],),
            ).fetchone()
        assert attr is not None
        assert attr["value"] == "1"
