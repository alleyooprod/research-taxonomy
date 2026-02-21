"""Tests for GLEIF API wrapper in mcp_client.

Markers: enrichment, db
"""
import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from core.mcp_client import search_gleif
from core.mcp_enrichment import _parse_gleif

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


GLEIF_RESPONSE = {
    "data": [
        {
            "id": "213800NWSHMHGWKJXO50",
            "attributes": {
                "lei": "213800NWSHMHGWKJXO50",
                "entity": {
                    "legalName": {"name": "AVIVA PLC"},
                    "jurisdiction": "GB",
                    "category": "GENERAL",
                    "status": "ACTIVE",
                    "legalAddress": {
                        "addressLines": ["St Helen's"],
                        "city": "London",
                        "country": "GB",
                        "postalCode": "EC3A 8EP",
                    },
                },
                "registration": {
                    "status": "ISSUED",
                    "initialRegistrationDate": "2012-11-29",
                    "lastUpdateDate": "2024-01-15",
                    "nextRenewalDate": "2025-01-29",
                },
            },
        }
    ]
}


class TestSearchGLEIF:

    def test_empty_name_returns_empty(self):
        assert search_gleif("") == []
        assert search_gleif(None) == []

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_successful_search(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = GLEIF_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = search_gleif("Aviva")
        assert result is not None
        assert len(result) == 1
        assert result[0]["lei"] == "213800NWSHMHGWKJXO50"
        assert result[0]["name"] == "AVIVA PLC"
        assert result[0]["jurisdiction"] == "GB"
        assert result[0]["status"] == "ISSUED"

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_no_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = search_gleif("NonexistentEntity123")
        assert result == []

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_api_error_returns_none(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        result = search_gleif("Aviva")
        assert result is None

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_caching(self, mock_get, mem_conn):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = GLEIF_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result1 = search_gleif("Aviva", conn=mem_conn)
        assert len(result1) == 1
        assert mock_get.call_count == 1

        result2 = search_gleif("Aviva", conn=mem_conn)
        assert len(result2) == 1
        assert mock_get.call_count == 1


class TestParseGLEIF:

    def test_parse_empty(self):
        assert _parse_gleif(None) == []
        assert _parse_gleif([]) == []

    def test_parse_valid(self):
        result = _parse_gleif([
            {"lei": "213800NWSHMHGWKJXO50", "status": "ISSUED", "jurisdiction": "GB"}
        ])
        slugs = {a["attr_slug"] for a in result}
        assert "lei_code" in slugs
        assert "lei_status" in slugs
        assert "legal_jurisdiction" in slugs

        lei = next(a for a in result if a["attr_slug"] == "lei_code")
        assert lei["value"] == "213800NWSHMHGWKJXO50"
        assert lei["confidence"] == 0.95
