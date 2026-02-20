"""Tests for IPID (Insurance Product Information Document) extractor.

Covers:
- Classification heuristics (section headings, keywords, symbols, URLs)
- Extraction with mocked LLM (structured output, list conversion, error handling)
- Schema filtering (extract_for_schema)
- Classifier integration (routing, available extractors, forced mode)
- API endpoints (extractors list, classify routing)

Run: pytest tests/test_ipid_extractor.py -v
Markers: db, extraction
"""
import json
import pytest
from unittest.mock import patch

from core.extractors import ipid
from core.extractors.classifier import (
    classify_content,
    extract_with_classification,
    get_available_extractors,
    CLASSIFICATION_THRESHOLD,
)

pytestmark = [pytest.mark.db, pytest.mark.extraction]


# ═══════════════════════════════════════════════════════════════
# Sample IPID content for testing
# ═══════════════════════════════════════════════════════════════

SAMPLE_IPID_CONTENT = """
Insurance Product Information Document

Company: Acme Insurance Ltd
Product: Travel Plus Cover
Authorised by the Financial Conduct Authority (FCA)

What is this type of insurance?
This is a travel insurance policy that provides cover for unexpected events
that may occur before or during your trip.

What is insured?
✓ Cancellation and curtailment up to £5,000
✓ Medical expenses up to £10,000,000
✓ Personal belongings up to £2,000
✓ Personal liability up to £2,000,000
✓ Travel delay after 12 hours

What is not insured?
✗ Pre-existing medical conditions unless declared and accepted
✗ Travel to countries against FCO advice
✗ Claims arising from alcohol or drug abuse
✗ Adventure sports unless additional premium paid

Are there any restrictions on cover?
⚠ Maximum trip duration of 31 days
⚠ You must be a UK resident
⚠ Age limit applies (max 75 years)

Where am I covered?
Worldwide excluding countries against FCO travel advice.

What are my obligations?
You must take reasonable care to avoid loss or damage.
You must declare all pre-existing medical conditions.
You must report any claim within 30 days.

When and how do I pay?
You pay a single annual premium at the start of the policy.
Payment can be made by debit card, credit card, or bank transfer.

When does the cover start and end?
Cover starts on the date shown on your policy schedule and lasts for 12 months.
Each individual trip is covered from departure to return.

How do I cancel the contract?
You have 14 days from receipt of your policy to cancel for a full refund.
After 14 days, a pro-rata refund may be given minus administration fee.
"""

SAMPLE_NON_INSURANCE_CONTENT = """
Welcome to our blog about modern web development frameworks.
In this article, we compare React, Vue, and Angular for building
single-page applications. We discuss rendering performance,
developer experience, and ecosystem maturity.
"""


# ═══════════════════════════════════════════════════════════════
# Classification Tests
# ═══════════════════════════════════════════════════════════════

class TestIPIDClassifier:
    """EXTR-IPID-CLASS: IPID classification heuristics."""

    def test_ipid_content_high_confidence(self):
        """Full IPID content with all sections should score very high."""
        score = ipid.classify(SAMPLE_IPID_CONTENT)
        assert score >= 0.8

    def test_non_insurance_content_low_confidence(self):
        """Non-insurance content should score very low."""
        score = ipid.classify(SAMPLE_NON_INSURANCE_CONTENT)
        assert score < 0.2

    def test_empty_content_returns_zero(self):
        """Empty content returns 0.0."""
        assert ipid.classify("") == 0.0
        assert ipid.classify(None) == 0.0

    def test_section_heading_counting(self):
        """More section headings should increase the score."""
        few_sections = """
        What is insured?
        Some coverage details.
        What is not insured?
        Some exclusions.
        """
        many_sections = """
        What is this type of insurance?
        Description.
        What is insured?
        Coverage details.
        What is not insured?
        Exclusions.
        Are there any restrictions on cover?
        Restrictions.
        Where am I covered?
        Worldwide.
        What are my obligations?
        Obligations.
        When and how do I pay?
        Payment details.
        """
        score_few = ipid.classify(few_sections)
        score_many = ipid.classify(many_sections)
        assert score_many > score_few

    def test_url_pattern_bonus_ipid_path(self):
        """URL containing /ipid/ should add bonus."""
        content = "What is insured? What is not insured?"
        score_no_url = ipid.classify(content)
        score_with_url = ipid.classify(content, url="https://insurer.com/ipid/travel-cover")
        assert score_with_url > score_no_url

    def test_url_pattern_bonus_product_information(self):
        """URL with /product-information/ should add bonus."""
        content = "What is insured? What is not insured?"
        score_no_url = ipid.classify(content)
        score_with_url = ipid.classify(
            content, url="https://insurer.com/product-information/pet-cover"
        )
        assert score_with_url > score_no_url

    def test_url_pattern_bonus_ipid_dash(self):
        """URL with /ipid- prefix should add bonus."""
        content = "What is insured? What is not insured?"
        score_no_url = ipid.classify(content)
        score_with_url = ipid.classify(
            content, url="https://insurer.com/docs/ipid-home-2024.pdf"
        )
        assert score_with_url > score_no_url

    def test_symbol_detection_boost(self):
        """IPID symbols (checkmarks/crosses) should boost score."""
        content_no_symbols = """
        What is insured?
        Cover for medical expenses.
        What is not insured?
        Pre-existing conditions excluded.
        """
        content_with_symbols = """
        What is insured?
        ✓ Cover for medical expenses.
        ✓ Personal belongings.
        What is not insured?
        ✗ Pre-existing conditions excluded.
        ✗ Adventure sports.
        """
        score_no_sym = ipid.classify(content_no_symbols)
        score_with_sym = ipid.classify(content_with_symbols)
        assert score_with_sym >= score_no_sym

    def test_keyword_only_content_moderate_score(self):
        """Content with IPID keywords but no section headings gets moderate score."""
        content = """
        Insurance Product Information Document
        IPID - Policyholder guide
        This document is provided under the Insurance Distribution Directive.
        Underwritten by Acme Insurance. General insurance product.
        """
        score = ipid.classify(content)
        assert score >= 0.2  # Should get some score from keywords
        assert score < 0.8  # But not as high as full IPID with sections

    def test_score_capped_at_one(self):
        """Score should never exceed 1.0 even with all signals and URL bonus."""
        score = ipid.classify(
            SAMPLE_IPID_CONTENT,
            url="https://insurer.com/ipid/travel-cover",
        )
        assert score <= 1.0


# ═══════════════════════════════════════════════════════════════
# Prompt Tests
# ═══════════════════════════════════════════════════════════════

class TestIPIDPrompt:
    """EXTR-IPID-PROMPT: IPID prompt construction."""

    def test_prompt_includes_entity_name(self):
        prompt = ipid.build_prompt("content", "Acme Insurance")
        assert "Acme Insurance" in prompt
        assert "IPID" in prompt

    def test_prompt_without_entity(self):
        prompt = ipid.build_prompt("content")
        assert "Insurance Product Information Document" in prompt

    def test_prompt_includes_content(self):
        prompt = ipid.build_prompt("Test IPID content here")
        assert "Test IPID content here" in prompt


# ═══════════════════════════════════════════════════════════════
# Extraction Tests
# ═══════════════════════════════════════════════════════════════

class TestIPIDExtraction:
    """EXTR-IPID-EXTRACT: IPID extraction with mocked LLM."""

    @patch("core.llm.run_cli")
    def test_successful_extraction(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.005,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "insurer_name": "Acme Insurance Ltd",
                "product_name": "Travel Plus Cover",
                "insurance_type": "travel",
                "what_is_insured": [
                    "Cancellation up to £5,000",
                    "Medical expenses up to £10,000,000",
                    "Personal belongings up to £2,000",
                ],
                "what_is_not_insured": [
                    "Pre-existing medical conditions",
                    "Travel against FCO advice",
                ],
                "restrictions": [
                    "Maximum trip duration 31 days",
                    "UK residents only",
                ],
                "geographic_coverage": "Worldwide",
                "obligations": "Declare pre-existing conditions",
                "payment_terms": "Single annual premium",
                "policy_period": "12 months from start date",
                "cancellation_terms": "14-day cooling off period",
                "excess_amount": "£100 per claim",
                "premium_indication": None,
                "regulatory_info": "FCA authorised",
                "confidence": 0.95,
            },
        }

        result = ipid.extract(SAMPLE_IPID_CONTENT, "Acme Insurance")
        assert result is not None
        assert result["insurer_name"] == "Acme Insurance Ltd"
        assert result["product_name"] == "Travel Plus Cover"
        assert result["insurance_type"] == "travel"
        assert result["_meta"]["extractor"] == "ipid"

    @patch("core.llm.run_cli")
    def test_list_to_semicolon_string_conversion(self, mock_llm):
        """List fields should be converted to semicolon-separated strings."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.004,
            "duration_ms": 1200,
            "is_error": False,
            "structured_output": {
                "what_is_insured": ["Medical", "Cancellation", "Baggage"],
                "what_is_not_insured": ["Pre-existing conditions", "FCO countries"],
                "restrictions": ["31-day max", "Age limit 75"],
                "confidence": 0.9,
            },
        }

        result = ipid.extract("Some IPID content")
        assert result is not None
        assert result["what_is_insured"] == "Medical; Cancellation; Baggage"
        assert result["what_is_not_insured"] == "Pre-existing conditions; FCO countries"
        assert result["restrictions"] == "31-day max; Age limit 75"

    @patch("core.llm.run_cli")
    def test_entity_name_in_prompt(self, mock_llm):
        """Entity name should appear in the prompt sent to LLM."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.003,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {"confidence": 0.8},
        }

        ipid.extract("Content", entity_name="Aviva Insurance")
        call_args = mock_llm.call_args
        prompt = call_args.kwargs.get("prompt", call_args[0][0] if call_args[0] else "")
        assert "Aviva Insurance" in prompt

    @patch("core.llm.run_cli")
    def test_llm_error_returns_none(self, mock_llm):
        mock_llm.return_value = {
            "result": "Error occurred",
            "is_error": True,
            "cost_usd": 0,
            "duration_ms": 100,
            "structured_output": None,
        }
        result = ipid.extract("Content")
        assert result is None

    @patch("core.llm.run_cli")
    def test_exception_returns_none(self, mock_llm):
        mock_llm.side_effect = RuntimeError("CLI not found")
        result = ipid.extract("Content")
        assert result is None

    @patch("core.llm.run_cli")
    def test_meta_field_present(self, mock_llm):
        """Result should contain _meta with extractor info."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.006,
            "duration_ms": 2000,
            "is_error": False,
            "structured_output": {
                "insurer_name": "Test Insurer",
                "confidence": 0.9,
            },
        }

        result = ipid.extract("IPID content")
        assert result is not None
        assert "_meta" in result
        assert result["_meta"]["extractor"] == "ipid"
        assert result["_meta"]["cost_usd"] == 0.006
        assert "duration_ms" in result["_meta"]
        assert "model" in result["_meta"]

    @patch("core.llm.run_cli")
    def test_empty_content_still_calls_llm(self, mock_llm):
        """Even empty content is passed to LLM (classification gates, not extract)."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.001,
            "duration_ms": 500,
            "is_error": False,
            "structured_output": {"confidence": 0.1},
        }

        result = ipid.extract("")
        assert result is not None  # LLM returned valid output
        mock_llm.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# Schema Filtering Tests
# ═══════════════════════════════════════════════════════════════

class TestIPIDSchemaFiltering:
    """EXTR-IPID-SCHEMA: extract_for_schema attribute filtering."""

    @patch("core.llm.run_cli")
    def test_filters_to_matching_attributes(self, mock_llm):
        """Only requested schema attributes should be returned."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.005,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "insurer_name": "Acme Insurance",
                "product_name": "Travel Plus",
                "insurance_type": "travel",
                "what_is_insured": ["Medical", "Baggage"],
                "geographic_coverage": "Worldwide",
                "confidence": 0.9,
            },
        }

        result = ipid.extract_for_schema(
            "IPID content",
            "Acme Insurance",
            schema_attributes=["insurer_name", "insurance_type"],
        )
        assert result is not None
        assert "insurer_name" in result
        assert "insurance_type" in result
        assert "product_name" not in result
        assert "what_is_insured" not in result
        assert "_meta" in result

    @patch("core.llm.run_cli")
    def test_non_matching_returns_none(self, mock_llm):
        """If no schema attributes match extracted data, return None."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.003,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "insurer_name": "Acme Insurance",
                "confidence": 0.9,
            },
        }

        result = ipid.extract_for_schema(
            "IPID content",
            "Acme Insurance",
            schema_attributes=["some_unrelated_field", "another_field"],
        )
        assert result is None

    @patch("core.llm.run_cli")
    def test_all_attributes_returned_when_all_match(self, mock_llm):
        """When all schema attributes match, all should be returned."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.005,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "insurer_name": "Test Insurer",
                "product_name": "Home Cover",
                "insurance_type": "home",
                "what_is_insured": ["Buildings", "Contents"],
                "what_is_not_insured": ["Wear and tear"],
                "restrictions": ["UK only"],
                "geographic_coverage": "United Kingdom",
                "obligations": "Report claims promptly",
                "payment_terms": "Monthly direct debit",
                "policy_period": "12 months",
                "cancellation_terms": "14-day cooling off",
                "excess_amount": "£250",
                "premium_indication": "From £15/month",
                "regulatory_info": "FCA regulated",
                "confidence": 0.95,
            },
        }

        all_slugs = list(ipid.ATTRIBUTE_SLUG_MAP.values())
        result = ipid.extract_for_schema(
            "IPID content", "Test Insurer", schema_attributes=all_slugs,
        )
        assert result is not None
        # All 14 attributes plus _meta
        for slug in all_slugs:
            assert slug in result, f"Missing attribute: {slug}"
        assert "_meta" in result

    @patch("core.llm.run_cli")
    def test_llm_failure_returns_none(self, mock_llm):
        """If LLM fails, extract_for_schema should return None."""
        mock_llm.side_effect = RuntimeError("No CLI")
        result = ipid.extract_for_schema(
            "Content", "Entity", schema_attributes=["insurer_name"],
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════
# Classifier Integration Tests
# ═══════════════════════════════════════════════════════════════

class TestIPIDClassifierIntegration:
    """EXTR-IPID-CLASSINT: Classifier routes IPID content correctly."""

    def test_classifier_routes_ipid_content(self):
        """Classifier should identify IPID content and route to ipid extractor."""
        extractor, name, confidence = classify_content(SAMPLE_IPID_CONTENT)
        assert name == "ipid"
        assert confidence >= CLASSIFICATION_THRESHOLD

    def test_ipid_in_available_extractors(self):
        """IPID should appear in the list of available extractors."""
        extractors = get_available_extractors()
        assert "ipid" in extractors

    @patch("core.llm.run_cli")
    def test_forced_ipid_extractor(self, mock_llm):
        """Forcing ipid extractor should work and set classification metadata."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.004,
            "duration_ms": 1200,
            "is_error": False,
            "structured_output": {
                "insurer_name": "Forced Insurance Co",
                "product_name": "Motor Cover",
                "insurance_type": "motor",
                "confidence": 0.85,
            },
        }

        result = extract_with_classification(
            "Some content", entity_name="Test",
            force_extractor="ipid",
        )
        assert result is not None
        assert result["_classification"]["extractor"] == "ipid"
        assert result["_classification"]["classification_confidence"] == 1.0


# ═══════════════════════════════════════════════════════════════
# API Endpoint Tests
# ═══════════════════════════════════════════════════════════════

class TestIPIDAPI:
    """EXTR-IPID-API: IPID extractor API endpoint tests."""

    @pytest.mark.api
    def test_extractors_list_includes_ipid(self, client):
        r = client.get("/api/extract/extractors")
        assert r.status_code == 200
        data = r.get_json()
        assert "extractors" in data
        assert "ipid" in data["extractors"]

    @pytest.mark.api
    @patch("core.llm.run_cli")
    def test_classify_endpoint_routes_ipid(self, mock_llm, client):
        """Classify endpoint should route IPID content to ipid extractor."""
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.005,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "insurer_name": "API Test Insurer",
                "product_name": "Travel Cover",
                "insurance_type": "travel",
                "what_is_insured": ["Medical", "Cancellation"],
                "what_is_not_insured": ["Pre-existing conditions"],
                "restrictions": ["31-day max"],
                "confidence": 0.95,
            },
        }

        r = client.post("/api/extract/classify", json={
            "content": SAMPLE_IPID_CONTENT,
            "entity_name": "Test Insurer",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["_classification"]["extractor"] == "ipid"
