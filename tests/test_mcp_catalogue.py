"""Tests for MCP server capability catalogue and smart routing.

Covers:
- Catalogue integrity (all entries valid)
- Enrichment server filtering
- Category-based lookups
- Smart routing score calculation
- Health tracking
- Recommendation engine

Markers: enrichment
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from core.mcp_catalogue import (
    SERVER_CATALOGUE,
    ServerCapability,
    CATEGORIES,
    COST_TIERS,
    get_enrichment_servers,
    get_servers_by_category,
    get_server,
)
from core.mcp_enrichment import (
    _score_server,
    recommend_servers,
    _record_health,
    get_server_health,
    get_all_server_health,
    build_entity_context,
    select_adapters,
)

pytestmark = pytest.mark.enrichment


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def mem_conn():
    """In-memory SQLite connection for cache/health tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _reset_cache_flag():
    import core.mcp_client as mod
    mod._CACHE_TABLE_ENSURED = False
    yield
    mod._CACHE_TABLE_ENSURED = False


@pytest.fixture
def uk_company_context():
    return {
        "entity_id": 1,
        "name": "Aviva",
        "type_slug": "company",
        "url": "https://www.aviva.co.uk",
        "country": "UK",
        "has_url": True,
        "existing_attrs": set(),
    }


@pytest.fixture
def us_company_context():
    return {
        "entity_id": 2,
        "name": "Lemonade",
        "type_slug": "company",
        "url": "https://www.lemonade.com",
        "country": "US",
        "has_url": True,
        "existing_attrs": set(),
    }


@pytest.fixture
def design_entity_context():
    return {
        "entity_id": 3,
        "name": "Bauhaus Chair",
        "type_slug": "design",
        "url": None,
        "country": None,
        "has_url": False,
        "existing_attrs": set(),
    }


# ═══════════════════════════════════════════════════════════════
# Catalogue Integrity
# ═══════════════════════════════════════════════════════════════

class TestCatalogueIntegrity:

    def test_catalogue_not_empty(self):
        assert len(SERVER_CATALOGUE) >= 16

    def test_all_entries_are_server_capability(self):
        for name, cap in SERVER_CATALOGUE.items():
            assert isinstance(cap, ServerCapability), f"{name} is not ServerCapability"

    def test_name_matches_key(self):
        for key, cap in SERVER_CATALOGUE.items():
            assert cap.name == key, f"Key {key} != cap.name {cap.name}"

    def test_all_categories_valid(self):
        for name, cap in SERVER_CATALOGUE.items():
            for cat in cap.categories:
                assert cat in CATEGORIES, f"{name} has invalid category: {cat}"

    def test_all_cost_tiers_valid(self):
        for name, cap in SERVER_CATALOGUE.items():
            assert cap.cost_tier in COST_TIERS, f"{name} has invalid cost_tier: {cap.cost_tier}"

    def test_priority_is_positive(self):
        for name, cap in SERVER_CATALOGUE.items():
            assert cap.priority > 0, f"{name} has non-positive priority"

    def test_display_name_not_empty(self):
        for name, cap in SERVER_CATALOGUE.items():
            assert cap.display_name, f"{name} has empty display_name"

    def test_description_not_empty(self):
        for name, cap in SERVER_CATALOGUE.items():
            assert cap.description, f"{name} has empty description"


# ═══════════════════════════════════════════════════════════════
# Catalogue Helpers
# ═══════════════════════════════════════════════════════════════

class TestCatalogueHelpers:

    def test_get_enrichment_servers(self):
        enrichment = get_enrichment_servers()
        assert len(enrichment) >= 11
        # All enrichment servers should have enrichment_capable=True
        for name, cap in enrichment.items():
            assert cap.enrichment_capable is True

    def test_macro_servers_not_enrichment(self):
        enrichment = get_enrichment_servers()
        macro_names = {"bank_of_england", "ecb", "eurostat", "oecd", "dbnomics"}
        for name in macro_names:
            assert name not in enrichment

    def test_get_servers_by_category_financial(self):
        financial = get_servers_by_category("financial")
        assert "sec_edgar" in financial
        assert "companies_house" in financial
        assert "fca_register" in financial

    def test_get_servers_by_category_regulatory(self):
        regulatory = get_servers_by_category("regulatory")
        assert "fca_register" in regulatory
        assert "gleif" in regulatory
        assert "patents" in regulatory

    def test_get_servers_by_category_design(self):
        design = get_servers_by_category("design")
        assert "cooper_hewitt" in design

    def test_get_server_existing(self):
        cap = get_server("hackernews")
        assert cap is not None
        assert cap.display_name == "Hacker News"

    def test_get_server_nonexistent(self):
        assert get_server("nonexistent") is None


# ═══════════════════════════════════════════════════════════════
# Adapter Selection (list applies_to)
# ═══════════════════════════════════════════════════════════════

class TestAdapterSelection:

    def test_cooper_hewitt_selected_for_product(self):
        ctx = {"type_slug": "product", "has_url": False}
        selected = select_adapters(ctx)
        names = [a["name"] for a in selected]
        assert "cooper_hewitt" in names

    def test_cooper_hewitt_selected_for_design(self):
        ctx = {"type_slug": "design", "has_url": False}
        selected = select_adapters(ctx)
        names = [a["name"] for a in selected]
        assert "cooper_hewitt" in names

    def test_cooper_hewitt_not_selected_for_company(self):
        ctx = {"type_slug": "company", "has_url": False}
        selected = select_adapters(ctx)
        names = [a["name"] for a in selected]
        assert "cooper_hewitt" not in names

    def test_fca_register_selected_for_uk_company(self, uk_company_context):
        selected = select_adapters(uk_company_context)
        names = [a["name"] for a in selected]
        assert "fca_register" in names

    def test_fca_register_not_selected_for_us_company(self, us_company_context):
        selected = select_adapters(us_company_context)
        names = [a["name"] for a in selected]
        assert "fca_register" not in names

    def test_wayback_requires_url(self):
        ctx = {"type_slug": "company", "has_url": False}
        selected = select_adapters(ctx)
        names = [a["name"] for a in selected]
        assert "wayback_machine" not in names

    def test_wayback_selected_with_url(self):
        ctx = {"type_slug": "company", "has_url": True}
        selected = select_adapters(ctx)
        names = [a["name"] for a in selected]
        assert "wayback_machine" in names

    def test_gleif_selected_for_any_company(self):
        ctx = {"type_slug": "company", "has_url": False}
        selected = select_adapters(ctx)
        names = [a["name"] for a in selected]
        assert "gleif" in names


# ═══════════════════════════════════════════════════════════════
# Scoring
# ═══════════════════════════════════════════════════════════════

class TestScoring:

    def test_score_higher_for_type_match(self):
        cap = get_server("fca_register")
        ctx_match = {"type_slug": "company", "country": "UK"}
        ctx_no_match = {"type_slug": "product", "country": "UK"}
        score_match = _score_server(cap, ctx_match)
        score_no_match = _score_server(cap, ctx_no_match)
        assert score_match > score_no_match

    def test_score_higher_with_intent_match(self):
        cap = get_server("fca_register")
        ctx = {"type_slug": "company", "country": "UK"}
        score_with_intent = _score_server(cap, ctx, intent="regulatory")
        score_no_intent = _score_server(cap, ctx, intent=None)
        assert score_with_intent > score_no_intent

    def test_score_penalty_for_missing_key(self):
        cap = get_server("companies_house")
        ctx = {"type_slug": "company", "country": "UK"}
        with patch.dict(os.environ, {"COMPANIES_HOUSE_API_KEY": ""}, clear=False):
            score_no_key = _score_server(cap, ctx)
        with patch.dict(os.environ, {"COMPANIES_HOUSE_API_KEY": "test123"}, clear=False):
            score_with_key = _score_server(cap, ctx)
        assert score_with_key > score_no_key

    def test_score_health_penalty(self):
        cap = get_server("hackernews")
        ctx = {"type_slug": "company"}
        health_ok = {"consecutive_failures": 0}
        health_bad = {"consecutive_failures": 3}
        score_ok = _score_server(cap, ctx, health=health_ok)
        score_bad = _score_server(cap, ctx, health=health_bad)
        assert score_ok > score_bad

    def test_score_health_penalty_capped(self):
        cap = get_server("hackernews")
        ctx = {"type_slug": "company"}
        health_very_bad = {"consecutive_failures": 100}
        # Should be capped at -60
        score = _score_server(cap, ctx, health=health_very_bad)
        score_3_failures = _score_server(cap, ctx, health={"consecutive_failures": 3})
        assert score == score_3_failures  # Both hit the -60 cap

    def test_universal_server_gets_small_bonus(self):
        cap = get_server("hackernews")  # applies_to="*"
        ctx = {"type_slug": "company"}
        score = _score_server(cap, ctx)
        # Base: 100 - 20 = 80, +5 for universal
        assert score == 85


# ═══════════════════════════════════════════════════════════════
# Health Tracking
# ═══════════════════════════════════════════════════════════════

class TestHealthTracking:

    @pytest.mark.db
    def test_record_health_success(self, mem_conn):
        _record_health(mem_conn, "hackernews", success=True)
        health = get_server_health(mem_conn, "hackernews")
        assert health["last_success"] is not None
        assert health["consecutive_failures"] == 0

    @pytest.mark.db
    def test_record_health_failure(self, mem_conn):
        _record_health(mem_conn, "hackernews", success=False)
        health = get_server_health(mem_conn, "hackernews")
        assert health["last_failure"] is not None
        assert health["consecutive_failures"] == 1

    @pytest.mark.db
    def test_consecutive_failures_increment(self, mem_conn):
        _record_health(mem_conn, "hackernews", success=False)
        _record_health(mem_conn, "hackernews", success=False)
        _record_health(mem_conn, "hackernews", success=False)
        health = get_server_health(mem_conn, "hackernews")
        assert health["consecutive_failures"] == 3

    @pytest.mark.db
    def test_success_resets_failures(self, mem_conn):
        _record_health(mem_conn, "hackernews", success=False)
        _record_health(mem_conn, "hackernews", success=False)
        _record_health(mem_conn, "hackernews", success=True)
        health = get_server_health(mem_conn, "hackernews")
        assert health["consecutive_failures"] == 0

    @pytest.mark.db
    def test_health_none_conn(self):
        health = get_server_health(None, "hackernews")
        assert health["consecutive_failures"] == 0

    @pytest.mark.db
    def test_get_all_server_health(self, mem_conn):
        _record_health(mem_conn, "hackernews", success=True)
        all_health = get_all_server_health(mem_conn)
        assert "hackernews" in all_health
        assert all_health["hackernews"]["consecutive_failures"] == 0


# ═══════════════════════════════════════════════════════════════
# Recommendation Engine
# ═══════════════════════════════════════════════════════════════

class TestRecommendations:

    def test_uk_company_gets_fca_and_ch(self, uk_company_context):
        recs = recommend_servers(uk_company_context)
        names = [r["name"] for r in recs]
        assert "fca_register" in names
        assert "companies_house" in names

    def test_us_company_gets_sec_not_fca(self, us_company_context):
        recs = recommend_servers(us_company_context)
        names = [r["name"] for r in recs]
        assert "sec_edgar" in names
        assert "fca_register" not in names

    def test_design_entity_gets_cooper_hewitt(self, design_entity_context):
        recs = recommend_servers(design_entity_context)
        names = [r["name"] for r in recs]
        assert "cooper_hewitt" in names

    def test_regulatory_intent_boosts_regulatory(self, uk_company_context):
        recs = recommend_servers(uk_company_context, intent="regulatory")
        # FCA and GLEIF should be in top 3
        top_3 = [r["name"] for r in recs[:3]]
        assert "fca_register" in top_3

    def test_max_servers_limits_output(self, uk_company_context):
        recs = recommend_servers(uk_company_context, max_servers=3)
        assert len(recs) <= 3

    def test_recommendations_sorted_by_score(self, uk_company_context):
        recs = recommend_servers(uk_company_context)
        scores = [r["score"] for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_each_recommendation_has_reason(self, uk_company_context):
        recs = recommend_servers(uk_company_context)
        for rec in recs:
            assert "reason" in rec
            assert len(rec["reason"]) > 0
