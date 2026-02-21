"""Tests for MCP enrichment orchestrator.

Covers:
- Context building from entity + attributes
- Adapter selection (type matching, conditions, filtering, priority)
- Staleness checking for attribute freshness
- Parser functions for all 7 data sources
- Full enrichment flow (single entity + batch)

Markers: enrichment, db
"""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from core.mcp_enrichment import (
    _parse_hackernews,
    _parse_news,
    _parse_wikipedia,
    _parse_domain_rank,
    _parse_patents,
    _parse_sec_edgar,
    _parse_companies_house,
    build_entity_context,
    select_adapters,
    check_staleness,
    enrich_entity,
    enrich_batch,
    _ADAPTERS,
)

pytestmark = [pytest.mark.enrichment, pytest.mark.db]


# ═══════════════════════════════════════════════════════════════
# Schema + Fixtures
# ═══════════════════════════════════════════════════════════════

ENRICHMENT_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company to research",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "URL", "slug": "url", "data_type": "url"},
                {"name": "Website", "slug": "website", "data_type": "url"},
                {"name": "Country", "slug": "country", "data_type": "text"},
                {"name": "HQ Country", "slug": "hq_country", "data_type": "text"},
            ],
        },
        {
            "name": "Product",
            "slug": "product",
            "description": "A product",
            "icon": "package",
            "parent_type": "company",
            "attributes": [
                {"name": "URL", "slug": "url", "data_type": "url"},
            ],
        },
    ],
}


@pytest.fixture
def enrichment_project(client):
    """Create a project with entity types for enrichment testing."""
    db = client.db
    pid = db.create_project(
        name="Enrichment Test",
        purpose="Testing MCP enrichment",
        entity_schema=ENRICHMENT_SCHEMA,
    )
    db.sync_entity_types(pid, ENRICHMENT_SCHEMA)
    return {"project_id": pid, "db": db, "client": client}


@pytest.fixture
def company_entity(enrichment_project):
    """Create a company entity with URL and country attributes."""
    db = enrichment_project["db"]
    pid = enrichment_project["project_id"]
    eid = db.create_entity(pid, "company", "Acme Corp")
    db.set_entity_attribute(eid, "website", "https://www.acme.com", source="manual")
    db.set_entity_attribute(eid, "country", "US", source="manual")
    return {"entity_id": eid, "project_id": pid, "db": db}


@pytest.fixture
def uk_company_entity(enrichment_project):
    """Create a UK company entity."""
    db = enrichment_project["db"]
    pid = enrichment_project["project_id"]
    eid = db.create_entity(pid, "company", "BritTech Ltd")
    db.set_entity_attribute(eid, "website", "https://brittech.co.uk", source="manual")
    db.set_entity_attribute(eid, "country", "UK", source="manual")
    return {"entity_id": eid, "project_id": pid, "db": db}


@pytest.fixture
def bare_entity(enrichment_project):
    """Create an entity with no attributes."""
    db = enrichment_project["db"]
    pid = enrichment_project["project_id"]
    eid = db.create_entity(pid, "company", "No Attrs Inc")
    return {"entity_id": eid, "project_id": pid, "db": db}


@pytest.fixture
def product_entity(enrichment_project):
    """Create a product entity (non-company type)."""
    db = enrichment_project["db"]
    pid = enrichment_project["project_id"]
    eid = db.create_entity(pid, "product", "Widget Pro")
    db.set_entity_attribute(eid, "url", "https://widget.pro", source="manual")
    return {"entity_id": eid, "project_id": pid, "db": db}


# ═══════════════════════════════════════════════════════════════
# Sample API Responses (used by mocks)
# ═══════════════════════════════════════════════════════════════

SAMPLE_HN = [
    {"title": "Acme Corp launches v2", "url": "https://acme.com/launch",
     "points": 342, "num_comments": 87, "story_id": "12345",
     "created_at": "2025-12-01T10:00:00Z",
     "story_url": "https://news.ycombinator.com/item?id=12345"},
    {"title": "Acme Corp acquires Beta", "url": "https://acme.com/acquire",
     "points": 128, "num_comments": 45, "story_id": "12346",
     "created_at": "2025-11-15T08:00:00Z",
     "story_url": "https://news.ycombinator.com/item?id=12346"},
]

SAMPLE_NEWS = [
    {"title": "Acme announces expansion", "url": "https://news.example.com/acme",
     "snippet": "Acme Corp today announced...", "source": "TechCrunch",
     "published_date": "2025-12-10"},
    {"title": "Acme raises Series D", "url": "https://news.example.com/acme-funding",
     "snippet": "The startup raised $100M...", "source": "Bloomberg",
     "published_date": "2025-12-05"},
]

SAMPLE_WIKI = {
    "title": "Acme Corporation",
    "extract": "Acme Corporation is a fictional company that appears in many cartoons." * 5,
    "url": "https://en.wikipedia.org/wiki/Acme_Corporation",
    "description": "Fictional company",
}

SAMPLE_DOMAIN_RANK = {
    "domain": "acme.com",
    "rank": 4521,
    "category": "Technology",
}

SAMPLE_PATENTS = [
    {"patent_id": "US-1234567-A", "title": "Method for widget assembly",
     "filing_date": "2024-01-15", "grant_date": "2025-06-10",
     "assignee": "Acme Corp", "abstract": "A method for..."},
    {"patent_id": "US-1234568-A", "title": "Improved widget design",
     "filing_date": "2023-09-20", "grant_date": "2025-03-01",
     "assignee": "Acme Corp", "abstract": "An improved design..."},
]

SAMPLE_SEC = [
    {"filing_type": "10-K", "filed_date": "2025-03-15",
     "url": "https://sec.gov/filing/123", "company_name": "Acme Corp",
     "cik": "0001234567", "accession_number": "0001234567-25-000001"},
]

SAMPLE_CH = [
    {"company_number": "12345678", "name": "BritTech Ltd",
     "status": "active", "date_of_creation": "2019-04-01",
     "sic_codes": ["62020", "62012"], "address": "10 Tech Lane, London, EC1 2AB"},
]


# ═══════════════════════════════════════════════════════════════
# Context Building Tests
# ═══════════════════════════════════════════════════════════════

class TestBuildContext:
    """Tests for build_entity_context()."""

    def test_build_context_with_url(self):
        """Entity with a website attribute has url and has_url set."""
        entity = {"id": 1, "name": "Acme", "type_slug": "company"}
        attrs = {
            "website": {"value": "https://acme.com", "source": "manual",
                        "confidence": None, "captured_at": "2025-01-01"},
        }
        ctx = build_entity_context(entity, attrs)
        assert ctx["url"] == "https://acme.com"
        assert ctx["has_url"] is True
        assert ctx["name"] == "Acme"
        assert ctx["type_slug"] == "company"
        assert ctx["entity_id"] == 1

    def test_build_context_with_country(self):
        """Entity with country attribute has country set."""
        entity = {"id": 2, "name": "BritCo", "type_slug": "company"}
        attrs = {
            "hq_country": {"value": "UK", "source": "manual",
                           "confidence": None, "captured_at": "2025-01-01"},
        }
        ctx = build_entity_context(entity, attrs)
        assert ctx["country"] == "UK"

    def test_build_context_minimal(self):
        """Entity with no attributes has defaults."""
        entity = {"id": 3, "name": "Bare Inc", "type_slug": "company"}
        ctx = build_entity_context(entity, {})
        assert ctx["url"] is None
        assert ctx["country"] is None
        assert ctx["has_url"] is False
        assert ctx["existing_attrs"] == set()

    def test_build_context_detects_has_url(self):
        """has_url is True when any URL-like attribute is set."""
        entity = {"id": 4, "name": "StoreCo", "type_slug": "product"}
        # Uses store_url slug
        attrs = {
            "store_url": {"value": "https://store.co/app", "source": "scrape",
                          "confidence": 0.8, "captured_at": "2025-06-01"},
        }
        ctx = build_entity_context(entity, attrs)
        assert ctx["has_url"] is True
        assert ctx["url"] == "https://store.co/app"

    def test_build_context_existing_attrs(self):
        """existing_attrs contains all attribute slugs."""
        entity = {"id": 5, "name": "Multi", "type_slug": "company"}
        attrs = {
            "url": {"value": "https://multi.io", "source": "manual",
                    "confidence": None, "captured_at": "2025-01-01"},
            "country": {"value": "DE", "source": "manual",
                        "confidence": None, "captured_at": "2025-01-01"},
            "founded": {"value": "2020", "source": "ai",
                        "confidence": 0.9, "captured_at": "2025-01-01"},
        }
        ctx = build_entity_context(entity, attrs)
        assert ctx["existing_attrs"] == {"url", "country", "founded"}


# ═══════════════════════════════════════════════════════════════
# Adapter Selection Tests
# ═══════════════════════════════════════════════════════════════

class TestSelectAdapters:
    """Tests for select_adapters()."""

    def test_select_all_adapters_for_generic_entity(self):
        """A company with URL and US country gets wildcard + US-specific adapters."""
        ctx = {
            "entity_id": 1, "name": "Acme", "type_slug": "company",
            "url": "https://acme.com", "country": "US",
            "has_url": True, "existing_attrs": set(),
        }
        adapters = select_adapters(ctx)
        names = [a["name"] for a in adapters]
        # All wildcard adapters + sec_edgar (US company)
        assert "hackernews" in names
        assert "news" in names
        assert "wikipedia" in names
        assert "domain_rank" in names
        assert "patents" in names
        assert "sec_edgar" in names
        # companies_house requires UK
        assert "companies_house" not in names

    def test_select_uk_company_adapters(self):
        """UK company gets companies_house but not sec_edgar."""
        ctx = {
            "entity_id": 2, "name": "BritCo", "type_slug": "company",
            "url": "https://britco.co.uk", "country": "UK",
            "has_url": True, "existing_attrs": set(),
        }
        adapters = select_adapters(ctx)
        names = [a["name"] for a in adapters]
        assert "companies_house" in names
        assert "sec_edgar" not in names

    def test_select_us_company_adapters(self):
        """US company gets sec_edgar but not companies_house."""
        ctx = {
            "entity_id": 3, "name": "USCorp", "type_slug": "company",
            "url": "https://uscorp.com", "country": "US",
            "has_url": True, "existing_attrs": set(),
        }
        adapters = select_adapters(ctx)
        names = [a["name"] for a in adapters]
        assert "sec_edgar" in names
        assert "companies_house" not in names

    def test_select_with_url_condition(self):
        """domain_rank requires has_url to be True."""
        ctx = {
            "entity_id": 4, "name": "Web Co", "type_slug": "company",
            "url": "https://web.co", "country": None,
            "has_url": True, "existing_attrs": set(),
        }
        adapters = select_adapters(ctx)
        names = [a["name"] for a in adapters]
        assert "domain_rank" in names

    def test_select_no_url_excludes_domain_rank(self):
        """domain_rank is excluded when entity has no URL."""
        ctx = {
            "entity_id": 5, "name": "NoWeb", "type_slug": "company",
            "url": None, "country": None,
            "has_url": False, "existing_attrs": set(),
        }
        adapters = select_adapters(ctx)
        names = [a["name"] for a in adapters]
        assert "domain_rank" not in names

    def test_select_with_server_filter(self):
        """Only specified servers are returned when filter is provided."""
        ctx = {
            "entity_id": 6, "name": "Filtered", "type_slug": "company",
            "url": "https://filtered.com", "country": "US",
            "has_url": True, "existing_attrs": set(),
        }
        adapters = select_adapters(ctx, server_filter=["wikipedia", "hackernews"])
        names = [a["name"] for a in adapters]
        assert set(names) == {"wikipedia", "hackernews"}

    def test_select_sorted_by_priority(self):
        """Adapters are sorted by priority ascending."""
        ctx = {
            "entity_id": 7, "name": "Sorted", "type_slug": "company",
            "url": "https://sorted.com", "country": "US",
            "has_url": True, "existing_attrs": set(),
        }
        adapters = select_adapters(ctx)
        priorities = [a["priority"] for a in adapters]
        assert priorities == sorted(priorities)

    def test_select_product_type_excludes_company_only(self):
        """Product type entity does not get company-specific adapters."""
        ctx = {
            "entity_id": 8, "name": "Widget", "type_slug": "product",
            "url": "https://widget.io", "country": "US",
            "has_url": True, "existing_attrs": set(),
        }
        adapters = select_adapters(ctx)
        names = [a["name"] for a in adapters]
        assert "sec_edgar" not in names
        assert "companies_house" not in names
        # Wildcard adapters still apply
        assert "hackernews" in names
        assert "wikipedia" in names


# ═══════════════════════════════════════════════════════════════
# Staleness Tests
# ═══════════════════════════════════════════════════════════════

class TestStaleness:
    """Tests for check_staleness()."""

    def test_staleness_missing_attr(self, bare_entity):
        """Missing attribute is always stale."""
        db = bare_entity["db"]
        eid = bare_entity["entity_id"]
        assert check_staleness(db, eid, "nonexistent_attr") is True

    def test_staleness_fresh_attr(self, company_entity):
        """Recently set attribute is not stale."""
        db = company_entity["db"]
        eid = company_entity["entity_id"]
        # website was just set, should be fresh within default 168 hours
        assert check_staleness(db, eid, "website", max_age_hours=168) is False

    def test_staleness_old_attr(self, enrichment_project):
        """Attribute older than max_age is stale."""
        db = enrichment_project["db"]
        pid = enrichment_project["project_id"]
        eid = db.create_entity(pid, "company", "Old Corp")
        # Set an attribute with an old timestamp
        old_time = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
        db.set_entity_attribute(
            eid, "old_attr", "old_value",
            source="manual", captured_at=old_time,
        )
        assert check_staleness(db, eid, "old_attr", max_age_hours=168) is True

    def test_staleness_nonexistent_entity(self, enrichment_project):
        """Non-existent entity returns stale."""
        db = enrichment_project["db"]
        assert check_staleness(db, 999999, "anything") is True


# ═══════════════════════════════════════════════════════════════
# Parser Function Tests
# ═══════════════════════════════════════════════════════════════

class TestParsers:
    """Tests for individual parser functions."""

    def test_parse_hackernews(self):
        """HN parser extracts count, top URL, and top points."""
        result = _parse_hackernews(SAMPLE_HN)
        slugs = {r["attr_slug"]: r for r in result}
        assert "hn_mention_count" in slugs
        assert slugs["hn_mention_count"]["value"] == "2"
        assert slugs["hn_top_story_url"]["value"] == "https://news.ycombinator.com/item?id=12345"
        assert slugs["hn_top_story_points"]["value"] == "342"
        assert all(r["confidence"] == 0.9 for r in result)

    def test_parse_hackernews_empty(self):
        """Empty HN result returns empty list."""
        assert _parse_hackernews([]) == []
        assert _parse_hackernews(None) == []

    def test_parse_news(self):
        """News parser extracts count, latest title, latest URL."""
        result = _parse_news(SAMPLE_NEWS)
        slugs = {r["attr_slug"]: r for r in result}
        assert slugs["recent_news_count"]["value"] == "2"
        assert slugs["latest_news_title"]["value"] == "Acme announces expansion"
        assert slugs["latest_news_url"]["value"] == "https://news.example.com/acme"

    def test_parse_news_empty(self):
        """Empty news result returns empty list."""
        assert _parse_news([]) == []
        assert _parse_news(None) == []

    def test_parse_wikipedia(self):
        """Wikipedia parser extracts summary (truncated) and URL."""
        result = _parse_wikipedia(SAMPLE_WIKI)
        slugs = {r["attr_slug"]: r for r in result}
        assert "wikipedia_summary" in slugs
        assert "wikipedia_url" in slugs
        assert slugs["wikipedia_url"]["value"] == "https://en.wikipedia.org/wiki/Acme_Corporation"
        # Summary should be truncated to 500 chars
        assert len(slugs["wikipedia_summary"]["value"]) <= 500
        assert all(r["confidence"] == 0.95 for r in result)

    def test_parse_wikipedia_empty(self):
        """Empty wikipedia result returns empty list."""
        assert _parse_wikipedia(None) == []
        assert _parse_wikipedia({}) == []

    def test_parse_domain_rank(self):
        """Domain rank parser extracts rank and category."""
        result = _parse_domain_rank(SAMPLE_DOMAIN_RANK)
        slugs = {r["attr_slug"]: r for r in result}
        assert slugs["domain_rank"]["value"] == "4521"
        assert slugs["domain_category"]["value"] == "Technology"

    def test_parse_domain_rank_empty(self):
        """Empty domain rank result returns empty list."""
        assert _parse_domain_rank(None) == []

    def test_parse_patents(self):
        """Patents parser extracts count, latest title, latest date."""
        result = _parse_patents(SAMPLE_PATENTS)
        slugs = {r["attr_slug"]: r for r in result}
        assert slugs["patent_count"]["value"] == "2"
        assert slugs["latest_patent_title"]["value"] == "Method for widget assembly"
        assert slugs["latest_patent_date"]["value"] == "2025-06-10"

    def test_parse_patents_empty(self):
        """Empty patents result returns empty list."""
        assert _parse_patents([]) == []
        assert _parse_patents(None) == []

    def test_parse_sec_edgar(self):
        """SEC parser extracts CIK, filing type, filing date."""
        result = _parse_sec_edgar(SAMPLE_SEC)
        slugs = {r["attr_slug"]: r for r in result}
        assert slugs["sec_cik"]["value"] == "0001234567"
        assert slugs["latest_filing_type"]["value"] == "10-K"
        assert slugs["latest_filing_date"]["value"] == "2025-03-15"
        assert all(r["confidence"] == 0.95 for r in result)

    def test_parse_sec_edgar_empty(self):
        """Empty SEC result returns empty list."""
        assert _parse_sec_edgar([]) == []
        assert _parse_sec_edgar(None) == []

    def test_parse_companies_house(self):
        """Companies House parser extracts number, status, creation date, SIC codes."""
        result = _parse_companies_house(SAMPLE_CH)
        slugs = {r["attr_slug"]: r for r in result}
        assert slugs["company_number"]["value"] == "12345678"
        assert slugs["company_status"]["value"] == "active"
        assert slugs["date_of_creation"]["value"] == "2019-04-01"
        # sic_codes should be JSON-serialised list
        sic_val = slugs["sic_codes"]["value"]
        parsed_sic = json.loads(sic_val)
        assert parsed_sic == ["62020", "62012"]

    def test_parse_companies_house_empty(self):
        """Empty Companies House result returns empty list."""
        assert _parse_companies_house([]) == []
        assert _parse_companies_house(None) == []


# ═══════════════════════════════════════════════════════════════
# Full Enrichment Flow Tests
# ═══════════════════════════════════════════════════════════════

class TestEnrichEntity:
    """Tests for enrich_entity() — full orchestration."""

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=SAMPLE_SEC)
    @patch("core.mcp_client.search_patents", return_value=SAMPLE_PATENTS)
    @patch("core.mcp_client.get_domain_rank", return_value=SAMPLE_DOMAIN_RANK)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=SAMPLE_NEWS)
    @patch("core.mcp_client.search_hackernews", return_value=SAMPLE_HN)
    def test_enrich_entity_success(self, mock_hn, mock_news, mock_wiki,
                                    mock_rank, mock_patents, mock_sec,
                                    mock_ch, mock_wayback, mock_fca,
                                    mock_gleif, mock_cooper, company_entity):
        """Successful enrichment writes attributes to the database."""
        db = company_entity["db"]
        eid = company_entity["entity_id"]

        result = enrich_entity(eid, db, max_age_hours=0)

        assert result["entity_id"] == eid
        assert result["enriched_count"] > 0
        assert len(result["servers_used"]) > 0
        assert len(result["attributes"]) > 0

        # Verify attributes were written to DB
        entity = db.get_entity(eid)
        attrs = entity["attributes"]
        assert "hn_mention_count" in attrs
        assert attrs["hn_mention_count"]["value"] == "2"
        assert "wikipedia_url" in attrs
        assert "domain_rank" in attrs
        assert attrs["domain_rank"]["value"] == "4521"

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=SAMPLE_SEC)
    @patch("core.mcp_client.search_patents", return_value=SAMPLE_PATENTS)
    @patch("core.mcp_client.get_domain_rank", return_value=SAMPLE_DOMAIN_RANK)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=SAMPLE_NEWS)
    @patch("core.mcp_client.search_hackernews", return_value=SAMPLE_HN)
    def test_enrich_entity_skips_fresh(self, mock_hn, mock_news, mock_wiki,
                                       mock_rank, mock_patents, mock_sec,
                                       mock_ch, mock_wayback, mock_fca,
                                       mock_gleif, mock_cooper, company_entity):
        """Fresh attributes are skipped (not overwritten)."""
        db = company_entity["db"]
        eid = company_entity["entity_id"]

        # Pre-set hn_mention_count as a recent attribute
        db.set_entity_attribute(eid, "hn_mention_count", "99", source="mcp:hackernews")

        # Enrich with default max_age_hours (168h) — the attribute we just set is fresh
        result = enrich_entity(eid, db, max_age_hours=168)

        assert result["skipped_count"] > 0

        # Verify hn_mention_count was NOT overwritten
        entity = db.get_entity(eid)
        attrs = entity["attributes"]
        assert attrs["hn_mention_count"]["value"] == "99"

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=None)
    @patch("core.mcp_client.search_patents", return_value=None)
    @patch("core.mcp_client.get_domain_rank", return_value=None)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=None)
    @patch("core.mcp_client.search_hackernews", return_value=None)
    def test_enrich_entity_handles_api_error(self, mock_hn, mock_news, mock_wiki,
                                              mock_rank, mock_patents, mock_sec,
                                              mock_ch, mock_wayback, mock_fca,
                                              mock_gleif, mock_cooper, company_entity):
        """When some APIs return None, others still succeed."""
        db = company_entity["db"]
        eid = company_entity["entity_id"]

        result = enrich_entity(eid, db, max_age_hours=0)

        # Wikipedia should still have succeeded
        assert result["enriched_count"] > 0
        entity = db.get_entity(eid)
        attrs = entity["attributes"]
        assert "wikipedia_url" in attrs

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=None)
    @patch("core.mcp_client.search_patents", return_value=None)
    @patch("core.mcp_client.get_domain_rank", return_value=None)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=None)
    @patch("core.mcp_client.search_hackernews", return_value=SAMPLE_HN)
    def test_enrich_entity_with_server_filter(self, mock_hn, mock_news, mock_wiki,
                                               mock_rank, mock_patents, mock_sec,
                                               mock_ch, mock_wayback, mock_fca,
                                               mock_gleif, mock_cooper, company_entity):
        """Only specified servers are called when filter is provided."""
        db = company_entity["db"]
        eid = company_entity["entity_id"]

        result = enrich_entity(eid, db, servers=["wikipedia", "hackernews"],
                               max_age_hours=0)

        # Only wikipedia and hackernews should have produced attributes
        server_names = [s["name"] for s in result["servers_used"]]
        for name in server_names:
            assert name in ("wikipedia", "hackernews")

        # Verify only those adapters' attributes are present
        entity = db.get_entity(eid)
        attrs = entity["attributes"]
        assert "wikipedia_url" in attrs
        assert "hn_mention_count" in attrs
        # domain_rank should NOT be present (was filtered out)
        assert "domain_rank" not in attrs

    def test_enrich_entity_not_found(self, enrichment_project):
        """Non-existent entity returns error in summary."""
        db = enrichment_project["db"]
        result = enrich_entity(999999, db)
        assert result["entity_id"] == 999999
        assert result["enriched_count"] == 0
        assert len(result["errors"]) > 0
        assert "not found" in result["errors"][0]["error"].lower()

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=None)
    @patch("core.mcp_client.search_patents", return_value=None)
    @patch("core.mcp_client.get_domain_rank", return_value=None)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=SAMPLE_NEWS)
    @patch("core.mcp_client.search_hackernews", return_value=SAMPLE_HN)
    def test_enrich_entity_creates_snapshot(self, mock_hn, mock_news, mock_wiki,
                                             mock_rank, mock_patents, mock_sec,
                                             mock_ch, mock_wayback, mock_fca,
                                             mock_gleif, mock_cooper, company_entity):
        """Enrichment creates a snapshot for the attribute batch."""
        db = company_entity["db"]
        eid = company_entity["entity_id"]
        pid = company_entity["project_id"]

        # Count snapshots before
        snapshots_before = db.get_snapshots(pid)

        result = enrich_entity(eid, db, max_age_hours=0)

        # Verify a snapshot was created
        snapshots_after = db.get_snapshots(pid)
        assert len(snapshots_after) > len(snapshots_before)
        # Latest snapshot should mention MCP enrichment
        latest = snapshots_after[0]
        assert "MCP enrichment" in latest.get("description", "")

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=SAMPLE_CH)
    @patch("core.mcp_client.search_sec_filings", return_value=None)
    @patch("core.mcp_client.search_patents", return_value=None)
    @patch("core.mcp_client.get_domain_rank", return_value=None)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=None)
    @patch("core.mcp_client.search_hackernews", return_value=None)
    def test_enrich_uk_company_gets_companies_house(self, mock_hn, mock_news,
                                                     mock_wiki, mock_rank,
                                                     mock_patents, mock_sec,
                                                     mock_ch, mock_wayback,
                                                     mock_fca, mock_gleif,
                                                     mock_cooper, uk_company_entity):
        """UK company gets enriched with Companies House data."""
        db = uk_company_entity["db"]
        eid = uk_company_entity["entity_id"]

        result = enrich_entity(eid, db, max_age_hours=0)

        entity = db.get_entity(eid)
        attrs = entity["attributes"]
        assert "company_number" in attrs
        assert attrs["company_number"]["value"] == "12345678"
        assert attrs["company_status"]["value"] == "active"

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=None)
    @patch("core.mcp_client.search_patents", return_value=None)
    @patch("core.mcp_client.get_domain_rank", return_value=None)
    @patch("core.mcp_client.search_wikipedia", return_value=None)
    @patch("core.mcp_client.search_news", return_value=None)
    @patch("core.mcp_client.search_hackernews", return_value=None)
    def test_enrich_entity_all_apis_return_none(self, mock_hn, mock_news,
                                                 mock_wiki, mock_rank,
                                                 mock_patents, mock_sec,
                                                 mock_ch, mock_wayback,
                                                 mock_fca, mock_gleif,
                                                 mock_cooper, company_entity):
        """When all APIs return None, enrichment count is zero."""
        db = company_entity["db"]
        eid = company_entity["entity_id"]

        result = enrich_entity(eid, db, max_age_hours=0)

        assert result["enriched_count"] == 0
        assert result["errors"] == []

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=None)
    @patch("core.mcp_client.search_patents", return_value=None)
    @patch("core.mcp_client.get_domain_rank", return_value=None)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=None)
    @patch("core.mcp_client.search_hackernews", return_value=None)
    def test_enrich_entity_source_format(self, mock_hn, mock_news, mock_wiki,
                                          mock_rank, mock_patents, mock_sec,
                                          mock_ch, mock_wayback, mock_fca,
                                          mock_gleif, mock_cooper,
                                          company_entity):
        """Attributes are written with source format 'mcp:{adapter_name}'."""
        db = company_entity["db"]
        eid = company_entity["entity_id"]

        result = enrich_entity(eid, db, max_age_hours=0)

        # Check source format in returned attributes
        for attr in result["attributes"]:
            assert attr["source"].startswith("mcp:")

        # Verify in DB
        entity = db.get_entity(eid)
        attrs = entity["attributes"]
        if "wikipedia_url" in attrs:
            assert attrs["wikipedia_url"]["source"] == "mcp:wikipedia"


# ═══════════════════════════════════════════════════════════════
# Batch Enrichment Tests
# ═══════════════════════════════════════════════════════════════

class TestEnrichBatch:
    """Tests for enrich_batch()."""

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=None)
    @patch("core.mcp_client.search_patents", return_value=None)
    @patch("core.mcp_client.get_domain_rank", return_value=None)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=None)
    @patch("core.mcp_client.search_hackernews", return_value=SAMPLE_HN)
    def test_enrich_batch(self, mock_hn, mock_news, mock_wiki, mock_rank,
                           mock_patents, mock_sec, mock_ch, mock_wayback,
                           mock_fca, mock_gleif, mock_cooper, enrichment_project):
        """Batch enrichment processes multiple entities."""
        db = enrichment_project["db"]
        pid = enrichment_project["project_id"]

        eid1 = db.create_entity(pid, "company", "Batch Co A")
        db.set_entity_attribute(eid1, "website", "https://batcha.com", source="manual")
        eid2 = db.create_entity(pid, "company", "Batch Co B")
        db.set_entity_attribute(eid2, "website", "https://batchb.com", source="manual")

        result = enrich_batch([eid1, eid2], db, max_age_hours=0, delay=0)

        assert result["total"] == 2
        assert result["enriched"] >= 1
        assert len(result["results"]) == 2

        # Both entities should have wikipedia and hn attributes
        for eid in [eid1, eid2]:
            entity = db.get_entity(eid)
            attrs = entity["attributes"]
            assert "wikipedia_url" in attrs

    def test_enrich_batch_empty_list(self, enrichment_project):
        """Batch enrichment with empty list returns zero counts."""
        db = enrichment_project["db"]
        result = enrich_batch([], db)
        assert result["total"] == 0
        assert result["enriched"] == 0
        assert result["errors"] == 0
        assert result["results"] == []

    @patch("core.mcp_client.search_cooper_hewitt", return_value=None)
    @patch("core.mcp_client.search_gleif", return_value=None)
    @patch("core.mcp_client.search_fca_register", return_value=None)
    @patch("core.mcp_client.search_wayback", return_value=None)
    @patch("core.mcp_client.search_companies_house", return_value=None)
    @patch("core.mcp_client.search_sec_filings", return_value=None)
    @patch("core.mcp_client.search_patents", return_value=None)
    @patch("core.mcp_client.get_domain_rank", return_value=None)
    @patch("core.mcp_client.search_wikipedia", return_value=SAMPLE_WIKI)
    @patch("core.mcp_client.search_news", return_value=None)
    @patch("core.mcp_client.search_hackernews", return_value=None)
    def test_enrich_batch_with_server_filter(self, mock_hn, mock_news, mock_wiki,
                                              mock_rank, mock_patents, mock_sec,
                                              mock_ch, mock_wayback, mock_fca,
                                              mock_gleif, mock_cooper, enrichment_project):
        """Batch enrichment respects server filter."""
        db = enrichment_project["db"]
        pid = enrichment_project["project_id"]
        eid = db.create_entity(pid, "company", "Filter Co")

        result = enrich_batch([eid], db, servers=["wikipedia"],
                              max_age_hours=0, delay=0)

        assert result["total"] == 1
        per_entity = result["results"][0]
        for attr in per_entity["attributes"]:
            assert attr["source"] == "mcp:wikipedia"
