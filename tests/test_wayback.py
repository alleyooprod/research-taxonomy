"""Tests for Wayback Machine API wrapper in mcp_client.

Markers: enrichment, db
"""
import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from core.mcp_client import search_wayback, _ensure_cache_table

pytestmark = [pytest.mark.enrichment, pytest.mark.db]


@pytest.fixture(autouse=True)
def _reset_cache_flag():
    import core.mcp_client as mod
    mod._CACHE_TABLE_ENSURED = False
    yield
    mod._CACHE_TABLE_ENSURED = False


@pytest.fixture
def mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


CDX_RESPONSE = [
    ["timestamp", "original", "statuscode", "mimetype", "length"],
    ["20200115120000", "https://www.acme.com/", "200", "text/html", "45000"],
    ["20210301080000", "https://www.acme.com/", "200", "text/html", "52000"],
    ["20220701150000", "https://www.acme.com/", "200", "text/html", "58000"],
]


class TestSearchWayback:

    def test_empty_query_returns_none(self):
        assert search_wayback("") is None
        assert search_wayback(None) is None

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_successful_search(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = CDX_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = search_wayback("https://www.acme.com")
        assert result is not None
        assert result["total_snapshots"] == 3
        assert result["first_capture"] == "2020-01-15"
        assert result["last_capture"] == "2022-07-01"
        assert len(result["snapshots"]) == 3

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_no_snapshots(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [["timestamp", "original", "statuscode", "mimetype", "length"]]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = search_wayback("https://www.nonexistent.com")
        assert result is not None
        assert result["total_snapshots"] == 0

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_api_error_returns_none(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        result = search_wayback("https://www.acme.com")
        assert result is None

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_caching(self, mock_get, mem_conn):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = CDX_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        # First call — hits API
        result1 = search_wayback("https://www.acme.com", conn=mem_conn)
        assert result1["total_snapshots"] == 3
        assert mock_get.call_count == 1

        # Second call — hits cache
        result2 = search_wayback("https://www.acme.com", conn=mem_conn)
        assert result2["total_snapshots"] == 3
        assert mock_get.call_count == 1  # No additional API call
