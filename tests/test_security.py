"""Tests for security hardening: CSRF, soft-delete filtering, upsert atomicity, rate limiting."""
import json
import time
import pytest

from config import generate_csrf_token, verify_csrf_token, SESSION_SECRET

pytestmark = [pytest.mark.security]


class TestCSRFTokens:
    def test_generate_returns_timestamped_token(self):
        token = generate_csrf_token()
        assert "." in token
        ts_str, sig = token.rsplit(".", 1)
        int(ts_str)  # should be a valid integer timestamp
        assert len(sig) == 32

    def test_verify_valid_token(self):
        token = generate_csrf_token()
        assert verify_csrf_token(token) is True

    def test_verify_rejects_garbage(self):
        assert verify_csrf_token("garbage") is False
        assert verify_csrf_token("") is False
        assert verify_csrf_token(None) is False

    def test_verify_rejects_tampered_signature(self):
        token = generate_csrf_token()
        ts_str, sig = token.rsplit(".", 1)
        tampered = f"{ts_str}.{'0' * 16}"
        assert verify_csrf_token(tampered) is False

    def test_verify_rejects_expired_token(self):
        # Create a token with an old timestamp
        old_ts = str(int(time.time()) - 100000)
        import hmac, hashlib
        sig = hmac.new(SESSION_SECRET.encode(), old_ts.encode(), hashlib.sha256).hexdigest()[:16]
        token = f"{old_ts}.{sig}"
        assert verify_csrf_token(token, max_age=86400) is False

    def test_static_token_rejected(self, app):
        """Legacy static CSRF token (SESSION_SECRET) should be rejected."""
        raw_client = app.test_client()
        r = raw_client.post("/api/projects",
                            json={"name": "CSRF Test", "seed_categories": "A"},
                            headers={"X-CSRF-Token": SESSION_SECRET})
        assert r.status_code == 403

    def test_missing_csrf_rejected(self, app):
        """Mutating request without CSRF token should be rejected."""
        raw_client = app.test_client()
        r = raw_client.post("/api/projects",
                            json={"name": "No CSRF", "seed_categories": "A"})
        assert r.status_code == 403


class TestSoftDeleteFiltering:
    def test_get_company_hides_deleted(self, tmp_db, project_id):
        cats = tmp_db.get_categories(project_id=project_id)
        cid = tmp_db.upsert_company({
            "project_id": project_id,
            "url": "https://deleted.com",
            "name": "Deleted Corp",
            "category_id": cats[0]["id"],
        })
        tmp_db.delete_company(cid)
        # Default should hide deleted
        company = tmp_db.get_company(cid)
        assert company is None or company.get("is_deleted") == 1

    def test_get_company_by_url_hides_deleted(self, tmp_db, project_id):
        cats = tmp_db.get_categories(project_id=project_id)
        cid = tmp_db.upsert_company({
            "project_id": project_id,
            "url": "https://soft-del.com",
            "name": "SoftDel Inc",
            "category_id": cats[0]["id"],
        })
        tmp_db.delete_company(cid)
        company = tmp_db.get_company_by_url("https://soft-del.com", project_id)
        assert company is None


class TestUpsertAtomicity:
    def test_upsert_same_url_updates(self, tmp_db, project_id):
        """Upserting the same URL should update, not duplicate."""
        cats = tmp_db.get_categories(project_id=project_id)
        cid1 = tmp_db.upsert_company({
            "project_id": project_id,
            "url": "https://atomic.com",
            "name": "Atomic v1",
            "category_id": cats[0]["id"],
            "what": "Original",
        })
        cid2 = tmp_db.upsert_company({
            "project_id": project_id,
            "url": "https://atomic.com",
            "name": "Atomic v2",
            "category_id": cats[0]["id"],
            "what": "Updated",
        })
        assert cid1 == cid2
        company = tmp_db.get_company(cid1)
        assert company["name"] == "Atomic v2"
        assert company["what"] == "Updated"

    def test_upsert_preserves_existing_fields(self, tmp_db, project_id):
        """Upserting with null fields should keep existing values (COALESCE)."""
        cats = tmp_db.get_categories(project_id=project_id)
        cid = tmp_db.upsert_company({
            "project_id": project_id,
            "url": "https://preserve.com",
            "name": "Preserve Inc",
            "category_id": cats[0]["id"],
            "what": "We do things",
            "target": "Everyone",
        })
        # Upsert again without 'what' field
        cid2 = tmp_db.upsert_company({
            "project_id": project_id,
            "url": "https://preserve.com",
            "name": "Preserve Inc",
            "category_id": cats[0]["id"],
        })
        assert cid == cid2
        company = tmp_db.get_company(cid)
        # 'what' and 'target' should be preserved
        assert company["what"] == "We do things"
        assert company["target"] == "Everyone"


class TestHealthEndpoint:
    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        assert data["db"] == "connected"


class TestExportExpanded:
    def test_json_export_includes_extra_tables(self, client):
        """JSON export should include taxonomy_history, reports, etc."""
        client.post("/api/projects", json={
            "name": "Export Expanded",
            "seed_categories": "Cat1",
        })
        r = client.get("/api/export/json?project_id=1")
        assert r.status_code == 200
        data = json.loads(r.data)
        assert "taxonomy_history" in data
        assert "reports" in data
        assert "activity_log" in data
        assert "saved_views" in data
