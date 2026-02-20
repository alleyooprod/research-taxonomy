"""Tests for AI API — models, setup, discovery, chat, find-similar, pricing.

Run: pytest tests/test_api_ai.py -v
Markers: api, ai
"""
import pytest

pytestmark = [pytest.mark.api, pytest.mark.ai]


class TestAIModels:
    """AI-MODELS: Model listing via GET /api/ai/models."""

    def test_list_models(self, client):
        r = client.get("/api/ai/models")
        assert r.status_code == 200
        data = r.get_json()
        assert "models" in data


class TestAISetupStatus:
    """AI-SETUP: Setup status via GET /api/ai/setup-status."""

    def test_setup_status(self, client):
        r = client.get("/api/ai/setup-status")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)


class TestAIDefaultModel:
    """AI-MODEL-DEFAULT: Default model get/set."""

    def test_get_default_model(self, client):
        r = client.get("/api/ai/default-model")
        assert r.status_code == 200
        data = r.get_json()
        assert "model" in data

    def test_set_default_model(self, client):
        r = client.post("/api/ai/default-model", json={
            "model": "claude-haiku-4-5-20251001",
        })
        assert r.status_code == 200


class TestAISaveAPIKey:
    """AI-APIKEY: API key management."""

    def test_save_invalid_key_rejected(self, client):
        r = client.post("/api/ai/save-api-key", json={
            "api_key": "not-a-valid-key",
        })
        assert r.status_code == 400


class TestAITestBackend:
    """AI-TEST: Backend testing validation."""

    def test_test_invalid_backend(self, client):
        r = client.post("/api/ai/test-backend", json={
            "backend": "nonexistent_backend",
        })
        # Should fail gracefully
        assert r.status_code in (200, 400)
        if r.status_code == 200:
            data = r.get_json()
            assert data.get("ok") is False


class TestAIDiscoverValidation:
    """AI-DISCOVER: Company discovery validation."""

    def test_discover_empty_query_rejected(self, client):
        r = client.post("/api/ai/discover", json={"query": ""})
        assert r.status_code == 400

    def test_poll_discover_nonexistent(self, client):
        r = client.get("/api/ai/discover/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("pending", "error")


class TestAIFindSimilarValidation:
    """AI-SIMILAR: Find similar companies validation."""

    def test_find_similar_missing_company_rejected(self, client):
        r = client.post("/api/ai/find-similar", json={})
        assert r.status_code == 400

    def test_find_similar_nonexistent_company(self, client):
        r = client.post("/api/ai/find-similar", json={"company_id": 99999})
        assert r.status_code == 404

    def test_poll_similar_nonexistent(self, client):
        r = client.get("/api/ai/find-similar/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("pending", "error")


class TestAIChatValidation:
    """AI-CHAT: Chat endpoint validation."""

    def test_chat_empty_question(self, client):
        r = client.post("/api/ai/chat", json={"question": ""})
        # Should return error or 400
        assert r.status_code in (200, 400)


class TestAIPricingValidation:
    """AI-PRICING: Pricing research validation."""

    def test_pricing_no_companies(self, api_project):
        c = api_project["client"]
        r = c.post("/api/ai/research-pricing", json={
            "project_id": api_project["id"],
        })
        # May return 400 if no companies need pricing, or 200 with job
        assert r.status_code in (200, 400)

    def test_poll_pricing_nonexistent(self, client):
        r = client.get("/api/ai/research-pricing/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("pending", "error")


class TestAIMarketReportValidation:
    """AI-REPORT: Market report validation."""

    def test_report_missing_category(self, client):
        r = client.post("/api/ai/market-report", json={})
        assert r.status_code == 400

    def test_poll_report_nonexistent(self, client):
        r = client.get("/api/ai/market-report/abcdef0123456789")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] in ("pending", "error")
