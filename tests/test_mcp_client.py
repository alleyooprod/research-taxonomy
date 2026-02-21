"""Tests for core.mcp_client — API wrappers and SQLite cache.

Markers: enrichment, db
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.mcp_client import (
    _cache_get,
    _cache_set,
    _ensure_cache_table,
    get_domain_rank,
    list_available_sources,
    search_companies_house,
    search_hackernews,
    search_news,
    search_patents,
    search_sec_filings,
    search_wikipedia,
    _CACHE_TABLE_ENSURED,
)


# ── Helpers ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_cache_flag():
    """Reset the module-level _CACHE_TABLE_ENSURED flag before each test."""
    import core.mcp_client as mod
    mod._CACHE_TABLE_ENSURED = False
    yield
    mod._CACHE_TABLE_ENSURED = False


@pytest.fixture
def mem_conn():
    """Provide an in-memory SQLite connection with row_factory."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ══════════════════════════════════════════════════════════════
# Cache tests
# ══════════════════════════════════════════════════════════════

class TestCacheTable:

    @pytest.mark.db
    @pytest.mark.enrichment
    def test_ensure_cache_table_creates_table(self, mem_conn):
        _ensure_cache_table(mem_conn)
        tables = [
            r[0] for r in mem_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "mcp_cache" in tables

    @pytest.mark.db
    @pytest.mark.enrichment
    def test_cache_set_and_get(self, mem_conn):
        _ensure_cache_table(mem_conn)
        _cache_set(mem_conn, "test_key", "test_source", {"foo": "bar"})
        result = _cache_get(mem_conn, "test_key")
        assert result == {"foo": "bar"}

    @pytest.mark.db
    @pytest.mark.enrichment
    def test_cache_get_expired(self, mem_conn):
        _ensure_cache_table(mem_conn)
        # Insert an entry that is already expired
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        mem_conn.execute(
            """INSERT INTO mcp_cache (cache_key, source, data_json, fetched_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "expired_key",
                "test",
                json.dumps({"val": 1}),
                (past - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                past.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        mem_conn.commit()
        result = _cache_get(mem_conn, "expired_key")
        assert result is None

    @pytest.mark.db
    @pytest.mark.enrichment
    def test_cache_set_upsert(self, mem_conn):
        _ensure_cache_table(mem_conn)
        _cache_set(mem_conn, "upsert_key", "src", {"v": 1})
        _cache_set(mem_conn, "upsert_key", "src", {"v": 2})
        result = _cache_get(mem_conn, "upsert_key")
        assert result == {"v": 2}
        # Only one row should exist
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM mcp_cache WHERE cache_key = ?", ("upsert_key",)
        ).fetchone()[0]
        assert count == 1

    @pytest.mark.db
    @pytest.mark.enrichment
    def test_cache_get_missing(self, mem_conn):
        _ensure_cache_table(mem_conn)
        result = _cache_get(mem_conn, "nonexistent_key")
        assert result is None


# ══════════════════════════════════════════════════════════════
# Hacker News tests
# ══════════════════════════════════════════════════════════════

class TestSearchHackerNews:

    @pytest.mark.enrichment
    @patch("requests.get")
    def test_search_hackernews_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "hits": [
                    {
                        "objectID": "12345",
                        "title": "Test Story",
                        "url": "https://example.com/story",
                        "points": 42,
                        "num_comments": 7,
                        "created_at": "2026-01-15T10:00:00Z",
                    }
                ]
            },
            raise_for_status=lambda: None,
        )
        result = search_hackernews("test query")
        assert result is not None
        assert len(result) == 1
        assert result[0]["title"] == "Test Story"
        assert result[0]["url"] == "https://example.com/story"
        assert result[0]["points"] == 42
        assert result[0]["num_comments"] == 7
        assert result[0]["story_id"] == "12345"
        assert result[0]["story_url"] == "https://news.ycombinator.com/item?id=12345"

    @pytest.mark.enrichment
    @patch("requests.get")
    def test_search_hackernews_empty(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"hits": []},
            raise_for_status=lambda: None,
        )
        result = search_hackernews("obscure nothing query")
        assert result == []

    @pytest.mark.enrichment
    @patch("requests.get")
    def test_search_hackernews_timeout(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")
        result = search_hackernews("test query")
        assert result is None

    @pytest.mark.enrichment
    @pytest.mark.db
    @patch("requests.get")
    def test_search_hackernews_cached(self, mock_get, mem_conn):
        """Second call for same query should return cached data without API call."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "hits": [
                    {
                        "objectID": "999",
                        "title": "Cached Story",
                        "url": "https://cached.com",
                        "points": 10,
                        "num_comments": 2,
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ]
            },
            raise_for_status=lambda: None,
        )
        # First call — hits API
        result1 = search_hackernews("cache test", conn=mem_conn)
        assert len(result1) == 1
        assert mock_get.call_count == 1

        # Second call — should use cache
        result2 = search_hackernews("cache test", conn=mem_conn)
        assert result2 == result1
        assert mock_get.call_count == 1  # no additional API call


# ══════════════════════════════════════════════════════════════
# DuckDuckGo News tests
# ══════════════════════════════════════════════════════════════

class TestSearchNews:

    @pytest.mark.enrichment
    @patch("duckduckgo_search.DDGS")
    def test_search_news_success(self, mock_ddgs_cls):
        mock_ddgs_cls.return_value.news.return_value = [
            {
                "title": "Breaking News",
                "url": "https://news.example.com/article",
                "body": "Something happened today.",
                "source": "Example News",
                "date": "2026-02-01",
            }
        ]
        result = search_news("test news")
        assert result is not None
        assert len(result) == 1
        assert result[0]["title"] == "Breaking News"
        assert result[0]["snippet"] == "Something happened today."
        assert result[0]["source"] == "Example News"
        assert result[0]["published_date"] == "2026-02-01"

    @pytest.mark.enrichment
    @patch("duckduckgo_search.DDGS")
    def test_search_news_error(self, mock_ddgs_cls):
        mock_ddgs_cls.return_value.news.side_effect = RuntimeError("Network error")
        result = search_news("failing query")
        assert result is None


# ══════════════════════════════════════════════════════════════
# Wikipedia tests
# ══════════════════════════════════════════════════════════════

class TestSearchWikipedia:

    @pytest.mark.enrichment
    @patch("requests.get")
    def test_search_wikipedia_direct_hit(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "title": "Python (programming language)",
                "extract": "Python is a high-level programming language.",
                "description": "General-purpose programming language",
                "content_urls": {
                    "desktop": {
                        "page": "https://en.wikipedia.org/wiki/Python_(programming_language)"
                    }
                },
            },
        )
        result = search_wikipedia("Python programming language")
        assert result is not None
        assert result["title"] == "Python (programming language)"
        assert "high-level" in result["extract"]
        assert result["url"].startswith("https://en.wikipedia.org")

    @pytest.mark.enrichment
    @patch("requests.get")
    def test_search_wikipedia_search_fallback(self, mock_get):
        """When direct lookup 404s, the search API fallback should work."""
        # First call: direct summary → 404
        # Second call: search API → result
        # Third call: summary of search result → success
        call_count = {"n": 0}

        def side_effect(url, **kwargs):
            call_count["n"] += 1
            mock_resp = MagicMock()
            if call_count["n"] == 1:
                # Direct summary returns 404
                mock_resp.status_code = 404
                return mock_resp
            elif call_count["n"] == 2:
                # Search API returns a result
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "query": {
                        "search": [{"title": "Flask (web framework)"}]
                    }
                }
                return mock_resp
            else:
                # Summary of search result
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "title": "Flask (web framework)",
                    "extract": "Flask is a micro web framework.",
                    "description": "Python web framework",
                    "content_urls": {
                        "desktop": {
                            "page": "https://en.wikipedia.org/wiki/Flask_(web_framework)"
                        }
                    },
                }
                return mock_resp

        mock_get.side_effect = side_effect
        result = search_wikipedia("Flask web framework")
        assert result is not None
        assert result["title"] == "Flask (web framework)"
        assert "micro web framework" in result["extract"]

    @pytest.mark.enrichment
    @patch("requests.get")
    def test_search_wikipedia_not_found(self, mock_get):
        """Both direct and search lookups fail — returns None."""
        def side_effect(url, **kwargs):
            mock_resp = MagicMock()
            if "rest_v1/page/summary" in url:
                mock_resp.status_code = 404
            else:
                # Search returns empty results
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"query": {"search": []}}
            return mock_resp

        mock_get.side_effect = side_effect
        result = search_wikipedia("xyzzy_nonexistent_article_12345")
        assert result is None


# ══════════════════════════════════════════════════════════════
# Patents tests
# ══════════════════════════════════════════════════════════════

class TestSearchPatents:

    @pytest.mark.enrichment
    @patch("requests.post")
    def test_search_patents_success(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "patents": [
                    {
                        "patent_id": "US-1234567-A",
                        "patent_title": "Method for doing things",
                        "patent_date": "2025-06-15",
                        "patent_abstract": "A method and system for...",
                        "assignees": [
                            {"assignee_organization": "Acme Corp"}
                        ],
                    }
                ]
            },
            raise_for_status=lambda: None,
        )
        result = search_patents("Acme Corp")
        assert result is not None
        assert len(result) == 1
        assert result[0]["patent_id"] == "US-1234567-A"
        assert result[0]["title"] == "Method for doing things"
        assert result[0]["grant_date"] == "2025-06-15"
        assert result[0]["assignee"] == "Acme Corp"

    @pytest.mark.enrichment
    @patch("requests.post")
    def test_search_patents_empty(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"patents": None},
            raise_for_status=lambda: None,
        )
        result = search_patents("Nonexistent Corp")
        assert result == []


# ══════════════════════════════════════════════════════════════
# SEC EDGAR tests
# ══════════════════════════════════════════════════════════════

class TestSearchSecFilings:

    @pytest.mark.enrichment
    @patch("requests.get")
    def test_search_sec_filings_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "hits": {
                    "hits": [
                        {
                            "_source": {
                                "form_type": "10-K",
                                "file_date": "2025-03-15",
                                "file_url": "https://sec.gov/filing/123",
                                "entity_name": "Apple Inc",
                                "entity_id": "320193",
                                "accession_no": "0000320193-25-000001",
                                "display_names": ["Apple Inc"],
                            }
                        }
                    ]
                }
            },
            raise_for_status=lambda: None,
        )
        result = search_sec_filings("Apple")
        assert result is not None
        assert len(result) == 1
        assert result[0]["filing_type"] == "10-K"
        assert result[0]["company_name"] == "Apple Inc"
        assert result[0]["cik"] == "320193"

    @pytest.mark.enrichment
    @patch("requests.get")
    def test_search_sec_filings_error(self, mock_get):
        mock_get.side_effect = ConnectionError("Network unreachable")
        result = search_sec_filings("Apple")
        assert result is None


# ══════════════════════════════════════════════════════════════
# Companies House tests
# ══════════════════════════════════════════════════════════════

class TestSearchCompaniesHouse:

    @pytest.mark.enrichment
    @patch.dict(os.environ, {"COMPANIES_HOUSE_API_KEY": "test-key-123"})
    @patch("requests.get")
    def test_search_companies_house_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "items": [
                    {
                        "company_number": "12345678",
                        "title": "EXAMPLE LTD",
                        "company_status": "active",
                        "date_of_creation": "2020-01-15",
                        "sic_codes": ["62012"],
                        "address": {
                            "address_line_1": "123 High Street",
                            "locality": "London",
                            "postal_code": "EC1A 1BB",
                        },
                    }
                ]
            },
            raise_for_status=lambda: None,
        )
        result = search_companies_house("Example Ltd")
        assert result is not None
        assert len(result) == 1
        assert result[0]["company_number"] == "12345678"
        assert result[0]["name"] == "EXAMPLE LTD"
        assert result[0]["status"] == "active"
        assert "123 High Street" in result[0]["address"]
        # Verify basic auth was used
        _, kwargs = mock_get.call_args
        assert kwargs["auth"] == ("test-key-123", "")

    @pytest.mark.enrichment
    def test_search_companies_house_no_key(self):
        """Without COMPANIES_HOUSE_API_KEY, should return None immediately."""
        # Ensure the env var is not set
        env = os.environ.copy()
        env.pop("COMPANIES_HOUSE_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = search_companies_house("Example Ltd")
            assert result is None


# ══════════════════════════════════════════════════════════════
# Domain Rank tests
# ══════════════════════════════════════════════════════════════

class TestGetDomainRank:

    @pytest.mark.enrichment
    @patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "cf-token-abc"})
    @patch("requests.get")
    def test_get_domain_rank_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "result": {
                    "details_0": {
                        "top": [{"rank": 150}],
                        "categories": [{"name": "Technology"}],
                    }
                }
            },
            raise_for_status=lambda: None,
        )
        result = get_domain_rank("example.com")
        assert result is not None
        assert result["domain"] == "example.com"
        assert result["rank"] == 150
        assert result["category"] == "Technology"
        # Verify bearer token was sent
        _, kwargs = mock_get.call_args
        assert "Bearer cf-token-abc" in kwargs["headers"]["Authorization"]

    @pytest.mark.enrichment
    def test_get_domain_rank_no_token(self):
        """Without CLOUDFLARE_API_TOKEN, should return None immediately."""
        env = os.environ.copy()
        env.pop("CLOUDFLARE_API_TOKEN", None)
        with patch.dict(os.environ, env, clear=True):
            result = get_domain_rank("example.com")
            assert result is None


# ══════════════════════════════════════════════════════════════
# Availability tests
# ══════════════════════════════════════════════════════════════

class TestListAvailableSources:

    @pytest.mark.enrichment
    def test_list_available_sources(self):
        sources = list_available_sources()
        assert len(sources) == 7
        names = {s["name"] for s in sources}
        assert names == {
            "hackernews", "news", "cloudflare", "patents",
            "sec_edgar", "companies_house", "wikipedia",
        }
        # All sources have required keys
        for s in sources:
            assert "name" in s
            assert "description" in s
            assert "available" in s
            assert "needs_key" in s

    @pytest.mark.enrichment
    @patch.dict(os.environ, {
        "CLOUDFLARE_API_TOKEN": "tok",
        "COMPANIES_HOUSE_API_KEY": "key",
    })
    def test_list_available_sources_with_keys(self):
        sources = list_available_sources()
        by_name = {s["name"]: s for s in sources}
        # Always-available sources
        assert by_name["hackernews"]["available"] is True
        assert by_name["news"]["available"] is True
        assert by_name["patents"]["available"] is True
        assert by_name["sec_edgar"]["available"] is True
        assert by_name["wikipedia"]["available"] is True
        # Key-dependent sources — should be available now
        assert by_name["cloudflare"]["available"] is True
        assert by_name["companies_house"]["available"] is True

    @pytest.mark.enrichment
    def test_list_available_sources_without_keys(self):
        """Without env vars, key-dependent sources should be unavailable."""
        env = os.environ.copy()
        env.pop("CLOUDFLARE_API_TOKEN", None)
        env.pop("COMPANIES_HOUSE_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            sources = list_available_sources()
            by_name = {s["name"]: s for s in sources}
            assert by_name["cloudflare"]["available"] is False
            assert by_name["companies_house"]["available"] is False
            assert by_name["cloudflare"]["needs_key"] is True
            assert by_name["companies_house"]["needs_key"] is True
