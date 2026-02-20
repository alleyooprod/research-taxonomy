"""Tests for funding round extractor — classification, extraction, routing.

Covers:
- Funding round classification: keyword scoring, URL patterns, money amounts
- Funding round extraction: mocked LLM, schema filtering, error handling
- Classifier integration: routing, available extractors, forced extractor
- API: /api/extract/classify with funding content, /api/extract/extractors

Run: pytest tests/test_funding_extractor.py -v
Markers: db, extraction
"""
import pytest
from unittest.mock import patch

from core.extractors import funding_round
from core.extractors.classifier import (
    classify_content,
    extract_with_classification,
    get_available_extractors,
    CLASSIFICATION_THRESHOLD,
)

pytestmark = [pytest.mark.db, pytest.mark.extraction]


# ═══════════════════════════════════════════════════════════════
# Funding Round Classification
# ═══════════════════════════════════════════════════════════════

class TestFundingRoundClassifier:
    """EXTR-FR-CLASS: Funding round classification heuristics."""

    def test_funding_announcement_high_confidence(self):
        content = """
        Acme Corp raises $50 million in Series B funding round led by
        Sequoia Capital. The round also saw participation from investors
        including Andreessen Horowitz and Tiger Global. The company
        plans to use the funding to expand its engineering team and
        accelerate product development. The round values the company
        at $500 million post-money valuation.
        """
        score = funding_round.classify(content)
        assert score >= 0.6

    def test_seed_round_announcement_high_confidence(self):
        content = """
        Startup XYZ announces $5M seed round funding.
        The seed round was led by Y Combinator, with participation
        from angel investors. Raised capital will be used
        to build the initial product. Pre-seed investors also
        participated in this round.
        """
        score = funding_round.classify(content)
        assert score >= 0.5

    def test_series_a_techcrunch_article(self):
        content = """
        HealthTech startup raises $20 million Series A round.
        The funding round was led by venture capital firm Kleiner Perkins.
        Other investors include General Catalyst and First Round Capital.
        The company has raised a total of $25 million to date.
        The valuation is reported at $100 million.
        """
        score = funding_round.classify(content)
        assert score >= 0.6

    def test_non_funding_article_low_confidence(self):
        content = """
        This is a blog post about the future of artificial intelligence.
        Researchers at MIT have published a new paper on transformer architectures.
        The study examines scaling laws and their implications for language models.
        """
        score = funding_round.classify(content)
        assert score < 0.3

    def test_marketing_page_low_confidence(self):
        content = """
        Get started with our platform today. Sign up for a free trial.
        Features include analytics, reporting, and integrations.
        Trusted by 500+ customers including Fortune 500 companies.
        Request a demo now.
        """
        score = funding_round.classify(content)
        assert score < 0.3

    def test_pricing_page_low_confidence(self):
        content = """
        Pricing: Basic $9/month, Pro $29/month, Enterprise custom.
        Free trial available. Billed annually save 20%.
        """
        score = funding_round.classify(content)
        assert score < 0.3

    def test_empty_content_returns_zero(self):
        score = funding_round.classify("")
        assert score == 0.0

    def test_none_content_returns_zero(self):
        score = funding_round.classify(None)
        assert score == 0.0

    def test_url_funding_pattern_boosts_score(self):
        content = "Company announces new investment round."
        score_without = funding_round.classify(content)
        score_with = funding_round.classify(content, url="https://example.com/funding/series-a")
        assert score_with > score_without

    def test_url_crunchbase_pattern_boosts_score(self):
        content = "Company announces new investment round."
        score_without = funding_round.classify(content)
        score_with = funding_round.classify(content, url="https://crunchbase.com/funding_round/123")
        assert score_with > score_without

    def test_url_techcrunch_pattern_boosts_score(self):
        content = "Company announces new investment round."
        score_without = funding_round.classify(content)
        score_with = funding_round.classify(content, url="https://techcrunch.com/2024/01/startup-raises")
        assert score_with > score_without

    def test_url_investment_pattern_boosts_score(self):
        content = "Company announces new investment round."
        score_without = funding_round.classify(content)
        score_with = funding_round.classify(content, url="https://example.com/investment/latest")
        assert score_with > score_without

    def test_money_amount_boosts_score(self):
        content_without = "The company made an announcement today."
        content_with = "The company raised $50 million in new capital."
        score_without = funding_round.classify(content_without)
        score_with = funding_round.classify(content_with)
        assert score_with > score_without

    def test_score_always_in_valid_range(self):
        # Even with all signals present, score should be capped at 1.0
        content = """
        Series A Series B Series C seed round pre-seed funding round
        raised raises $100 million billion valuation
        led by participated investors venture capital VC
        """
        score = funding_round.classify(
            content, url="https://crunchbase.com/funding"
        )
        assert 0.0 <= score <= 1.0


# ═══════════════════════════════════════════════════════════════
# Funding Round Prompt
# ═══════════════════════════════════════════════════════════════

class TestFundingRoundPrompt:
    """EXTR-FR-PROMPT: Funding round prompt construction."""

    def test_prompt_includes_entity(self):
        prompt = funding_round.build_prompt("content", "Acme Corp")
        assert "Acme Corp" in prompt
        assert "funding" in prompt.lower()

    def test_prompt_without_entity(self):
        prompt = funding_round.build_prompt("content")
        assert "funding" in prompt.lower()
        assert "investment" in prompt.lower()

    def test_prompt_includes_content(self):
        prompt = funding_round.build_prompt("The startup raised $10M", "TestCo")
        assert "The startup raised $10M" in prompt

    def test_prompt_instructs_round_types(self):
        prompt = funding_round.build_prompt("content")
        assert "pre_seed" in prompt
        assert "seed" in prompt
        assert "series_a" in prompt
        assert "series_b" in prompt
        assert "undisclosed" in prompt

    def test_prompt_instructs_iso_date(self):
        prompt = funding_round.build_prompt("content")
        assert "YYYY-MM-DD" in prompt


# ═══════════════════════════════════════════════════════════════
# Funding Round Extraction
# ═══════════════════════════════════════════════════════════════

class TestFundingRoundExtraction:
    """EXTR-FR-EXTRACT: Funding round extraction with mocked LLM."""

    @patch("core.llm.run_cli")
    def test_successful_extraction(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "company_name": "Acme Corp",
                "round_type": "series_b",
                "amount": "$50M",
                "amount_usd": 50000000,
                "valuation": "$500M",
                "lead_investors": ["Sequoia Capital"],
                "other_investors": ["Andreessen Horowitz", "Tiger Global"],
                "date_announced": "2024-01-15",
                "use_of_funds": "Expand engineering team and accelerate product development",
                "previous_funding": "Previously raised $15M in Series A",
                "summary": "Acme Corp raised $50M in Series B led by Sequoia Capital.",
                "confidence": 0.95,
            },
        }

        result = funding_round.extract("Funding article content", "Acme Corp")
        assert result is not None
        assert result["company_name"] == "Acme Corp"
        assert result["round_type"] == "series_b"
        assert result["amount"] == "$50M"
        assert result["amount_usd"] == 50000000
        assert result["_meta"]["extractor"] == "funding_round"

    @patch("core.llm.run_cli")
    def test_array_fields_become_comma_separated(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.008,
            "duration_ms": 1200,
            "is_error": False,
            "structured_output": {
                "company_name": "StartupXYZ",
                "round_type": "seed",
                "amount": "$5M",
                "amount_usd": 5000000,
                "lead_investors": ["Y Combinator", "Techstars"],
                "other_investors": ["Angel A", "Angel B", "Angel C"],
                "confidence": 0.9,
            },
        }

        result = funding_round.extract("Seed round content")
        assert result is not None
        assert result["lead_investors"] == "Y Combinator, Techstars"
        assert result["other_investors"] == "Angel A, Angel B, Angel C"

    @patch("core.llm.run_cli")
    def test_llm_error_returns_none(self, mock_llm):
        mock_llm.return_value = {
            "result": "Error", "is_error": True, "cost_usd": 0, "duration_ms": 100,
            "structured_output": None,
        }
        result = funding_round.extract("Content")
        assert result is None

    @patch("core.llm.run_cli")
    def test_exception_returns_none(self, mock_llm):
        mock_llm.side_effect = RuntimeError("No CLI")
        result = funding_round.extract("Content")
        assert result is None

    @patch("core.llm.run_cli")
    def test_no_structured_output_tries_json_repair(self, mock_llm):
        mock_llm.return_value = {
            "result": '{"company_name": "Test", "confidence": 0.5}',
            "cost_usd": 0.005,
            "duration_ms": 800,
            "is_error": False,
            "structured_output": None,
        }
        result = funding_round.extract("Content")
        # json_repair should parse the result string
        assert result is not None
        assert result["company_name"] == "Test"

    @patch("core.llm.run_cli")
    def test_meta_includes_model_and_cost(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.015,
            "duration_ms": 2000,
            "is_error": False,
            "structured_output": {
                "company_name": "TestCo",
                "round_type": "series_a",
                "confidence": 0.8,
            },
        }

        result = funding_round.extract("Content", model="claude-sonnet-4-6")
        assert result["_meta"]["extractor"] == "funding_round"
        assert result["_meta"]["model"] == "claude-sonnet-4-6"
        assert result["_meta"]["cost_usd"] == 0.015

    @patch("core.llm.run_cli")
    def test_empty_content_extract(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.001,
            "duration_ms": 200,
            "is_error": False,
            "structured_output": {
                "confidence": 0.0,
            },
        }
        result = funding_round.extract("")
        assert result is not None
        assert result["confidence"] == 0.0


# ═══════════════════════════════════════════════════════════════
# Schema Filtering
# ═══════════════════════════════════════════════════════════════

class TestFundingRoundSchemaFiltering:
    """EXTR-FR-SCHEMA: Schema-aware extraction filtering."""

    @patch("core.llm.run_cli")
    def test_schema_filtering(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "company_name": "Acme Corp",
                "round_type": "series_b",
                "amount": "$50M",
                "amount_usd": 50000000,
                "valuation": "$500M",
                "lead_investors": ["Sequoia Capital"],
                "other_investors": ["Tiger Global"],
                "date_announced": "2024-01-15",
                "use_of_funds": "Expand team",
                "previous_funding": "$15M total",
                "summary": "Series B raise.",
                "confidence": 0.95,
            },
        }

        # Only request three attributes
        result = funding_round.extract_for_schema(
            "Funding content",
            "Acme Corp",
            schema_attributes=["round_type", "amount", "lead_investors"],
        )
        assert result is not None
        assert "round_type" in result
        assert "amount" in result
        assert "lead_investors" in result
        # Should NOT include unrequested attributes
        assert "valuation" not in result
        assert "company_name" not in result
        assert "use_of_funds" not in result
        assert "_meta" in result

    @patch("core.llm.run_cli")
    def test_schema_filtering_no_matching_attrs_returns_none(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "company_name": "Test",
                "confidence": 0.7,
            },
        }

        result = funding_round.extract_for_schema(
            "Funding content",
            "TestCo",
            schema_attributes=["nonexistent_attribute"],
        )
        assert result is None

    @patch("core.llm.run_cli")
    def test_schema_filtering_empty_schema_returns_none(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "company_name": "Test",
                "round_type": "seed",
                "confidence": 0.7,
            },
        }

        result = funding_round.extract_for_schema(
            "Funding content",
            "TestCo",
            schema_attributes=[],
        )
        assert result is None

    @patch("core.llm.run_cli")
    def test_schema_filtering_converts_values_to_strings(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "amount_usd": 50000000,
                "confidence": 0.8,
            },
        }

        result = funding_round.extract_for_schema(
            "Funding content",
            "TestCo",
            schema_attributes=["amount_usd"],
        )
        assert result is not None
        assert result["amount_usd"] == "50000000"
        assert isinstance(result["amount_usd"], str)

    @patch("core.llm.run_cli")
    def test_schema_filtering_skips_none_values(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "company_name": "Test",
                "valuation": None,
                "round_type": "seed",
                "confidence": 0.8,
            },
        }

        result = funding_round.extract_for_schema(
            "Funding content",
            "TestCo",
            schema_attributes=["company_name", "valuation", "round_type"],
        )
        assert result is not None
        assert "company_name" in result
        assert "round_type" in result
        assert "valuation" not in result  # None values should be skipped


# ═══════════════════════════════════════════════════════════════
# Classifier Integration
# ═══════════════════════════════════════════════════════════════

class TestFundingRoundClassifierIntegration:
    """EXTR-FR-ROUTE: Funding round routing via classifier."""

    def test_funding_content_routes_to_funding_round(self):
        content = """
        HealthTech startup announces $50 million Series B funding round.
        The round was led by Sequoia Capital, with participation from
        Andreessen Horowitz and Tiger Global as investors. The company
        has raised a total of $65 million to date. The funding will be
        used to expand the engineering team and accelerate product development.
        The post-money valuation is reported at $500 million.
        """
        extractor, name, confidence = classify_content(content)
        assert name == "funding_round"
        assert confidence >= CLASSIFICATION_THRESHOLD

    def test_funding_round_in_available_extractors(self):
        extractors = get_available_extractors()
        assert "funding_round" in extractors

    @patch("core.llm.run_cli")
    def test_forced_funding_round_extractor(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "company_name": "TestCo",
                "round_type": "seed",
                "amount": "$5M",
                "amount_usd": 5000000,
                "lead_investors": [],
                "other_investors": [],
                "confidence": 0.7,
            },
        }

        result = extract_with_classification(
            "Any content", force_extractor="funding_round"
        )
        assert result is not None
        assert result["_classification"]["extractor"] == "funding_round"
        assert result["_classification"]["classification_confidence"] == 1.0

    def test_non_funding_content_does_not_route_to_funding(self):
        content = "This is a blog post about gardening techniques and soil health."
        extractor, name, confidence = classify_content(content)
        assert name != "funding_round"


# ═══════════════════════════════════════════════════════════════
# API Endpoints
# ═══════════════════════════════════════════════════════════════

class TestFundingRoundAPI:
    """EXTR-FR-API: Funding round API endpoint tests."""

    @pytest.mark.api
    def test_funding_round_in_extractors_list(self, client):
        r = client.get("/api/extract/extractors")
        assert r.status_code == 200
        data = r.get_json()
        assert "extractors" in data
        assert "funding_round" in data["extractors"]

    @pytest.mark.api
    @patch("core.llm.run_cli")
    def test_classify_endpoint_with_funding_content(self, mock_llm, client):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1200,
            "is_error": False,
            "structured_output": {
                "company_name": "FundedCo",
                "round_type": "series_a",
                "amount": "$20M",
                "amount_usd": 20000000,
                "lead_investors": ["Top VC"],
                "other_investors": [],
                "confidence": 0.9,
            },
        }

        content = """
        FundedCo raises $20 million in Series A funding round led by Top VC.
        Investors include several venture capital firms. The company
        has a valuation of $100 million. Previously raised seed funding.
        """
        r = client.post("/api/extract/classify", json={
            "content": content,
            "entity_name": "FundedCo",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert "_classification" in data

    @pytest.mark.api
    @patch("core.llm.run_cli")
    def test_classify_forced_funding_round(self, mock_llm, client):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "company_name": "AnyCompany",
                "round_type": "undisclosed",
                "confidence": 0.5,
            },
        }

        r = client.post("/api/extract/classify", json={
            "content": "Some content about a company.",
            "force_extractor": "funding_round",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["_classification"]["extractor"] == "funding_round"
        assert data["_classification"]["classification_confidence"] == 1.0
