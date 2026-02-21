"""Tests for FCA Register API wrapper in mcp_client.

Markers: enrichment, db
"""
import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from core.mcp_client import search_fca_register
from core.mcp_enrichment import _parse_fca_register

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


FCA_RESPONSE = {
    "Data": [
        {
            "FRN": "122702",
            "Organisation Name": "AVIVA INSURANCE LIMITED",
            "Status": "Authorised",
            "Organisation Type": "Insurer",
            "Status Effective Date": "2001-12-01",
        },
        {
            "FRN": "204503",
            "Organisation Name": "AVIVA HEALTH UK LIMITED",
            "Status": "Authorised",
            "Type": "Health Insurer",
        },
    ]
}


class TestSearchFCA:

    def test_empty_name_returns_empty(self):
        assert search_fca_register("") == []
        assert search_fca_register(None) == []

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_successful_search(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = FCA_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = search_fca_register("Aviva")
        assert result is not None
        assert len(result) == 2
        assert result[0]["frn"] == "122702"
        assert result[0]["name"] == "AVIVA INSURANCE LIMITED"
        assert result[0]["status"] == "Authorised"

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_no_results(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"Data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = search_fca_register("NonexistentCompany123")
        assert result == []

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_api_error_returns_none(self, mock_get):
        mock_get.side_effect = Exception("Connection error")
        result = search_fca_register("Aviva")
        assert result is None

    @patch("core.mcp_client.requests.get" if hasattr(__import__("core.mcp_client"), "requests") else "requests.get")
    def test_caching(self, mock_get, mem_conn):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = FCA_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result1 = search_fca_register("Aviva", conn=mem_conn)
        assert len(result1) == 2
        assert mock_get.call_count == 1

        result2 = search_fca_register("Aviva", conn=mem_conn)
        assert len(result2) == 2
        assert mock_get.call_count == 1


class TestParseFCA:

    def test_parse_empty(self):
        assert _parse_fca_register(None) == []
        assert _parse_fca_register([]) == []

    def test_parse_valid(self):
        result = _parse_fca_register([
            {"frn": "122702", "status": "Authorised", "type": "Insurer", "effective_date": "2001-12-01"}
        ])
        slugs = {a["attr_slug"] for a in result}
        assert "fca_frn" in slugs
        assert "fca_status" in slugs
        assert "fca_firm_type" in slugs

        frn = next(a for a in result if a["attr_slug"] == "fca_frn")
        assert frn["value"] == "122702"
        assert frn["confidence"] == 0.95
