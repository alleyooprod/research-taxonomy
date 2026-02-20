"""Tests for press release extractor — classification, extraction, routing.

Covers:
- Press release classification: keyword scoring, URL patterns, edge cases
- Press release prompt construction: entity name, content in prompt
- Press release extraction: mocked LLM, list field conversion, error handling
- Schema filtering: extract_for_schema with matching/non-matching attributes
- Classifier integration: routing, available extractors, forced extractor
- API: classify endpoint returns press_release type

Run: pytest tests/test_press_release_extractor.py -v
Markers: db, extraction
"""
import pytest
from unittest.mock import patch

from core.extractors import press_release
from core.extractors.classifier import (
    classify_content,
    extract_with_classification,
    get_available_extractors,
    CLASSIFICATION_THRESHOLD,
)

pytestmark = [pytest.mark.db, pytest.mark.extraction]


# ═══════════════════════════════════════════════════════════════
# Press Release Classification
# ═══════════════════════════════════════════════════════════════

class TestPressReleaseClassifier:
    """EXTR-PR-CLASS: Press release classification heuristics."""

    def test_press_release_high_confidence(self):
        content = """
        FOR IMMEDIATE RELEASE

        Acme Corp Announces Strategic Partnership with Beta Inc

        SAN FRANCISCO, CA — January 15, 2024 — Acme Corp, a leading provider
        of enterprise software, today announced a strategic partnership with
        Beta Inc to expand its AI-powered analytics platform.

        "This partnership represents a major milestone," said John Smith, CEO
        of Acme Corp. "Together we will deliver unprecedented value."

        About Acme Corp
        Acme Corp is a leading enterprise software company founded in 2018.

        Media Contact:
        Jane Doe, PR Manager
        press@acme.com
        """
        score = press_release.classify(content)
        assert score >= 0.6

    def test_product_announcement_high_confidence(self):
        content = """
        Press Release

        Acme Corp Launches Revolutionary New Product

        Acme Corp announced today the launch of its new AI-powered platform.
        The partnership with leading technology providers enables enterprise
        customers to transform their operations.

        About the Company
        Acme Corp is headquartered in San Francisco.

        Media Inquiries: press@acme.com
        """
        score = press_release.classify(content)
        assert score >= 0.5

    def test_blog_post_low_confidence(self):
        content = """
        This is a blog post about the future of artificial intelligence.
        Researchers at MIT have published a new paper on transformer architectures.
        The study examines scaling laws and their implications for language models.
        """
        score = press_release.classify(content)
        assert score < 0.3

    def test_marketing_page_low_confidence(self):
        content = """
        Get started with our platform today. Sign up for a free trial.
        Features include analytics, reporting, and integrations.
        Trusted by 500+ customers including Fortune 500 companies.
        Request a demo now.
        """
        score = press_release.classify(content)
        assert score < 0.3

    def test_empty_content_returns_zero(self):
        score = press_release.classify("")
        assert score == 0.0

    def test_none_content_returns_zero(self):
        score = press_release.classify(None)
        assert score == 0.0

    def test_url_press_pattern_boosts_score(self):
        content = "Company announces new product launch today."
        score_without = press_release.classify(content)
        score_with = press_release.classify(content, url="https://example.com/press/2024-release")
        assert score_with > score_without

    def test_url_news_pattern_boosts_score(self):
        content = "Company announces new product launch today."
        score_without = press_release.classify(content)
        score_with = press_release.classify(content, url="https://example.com/news/announcement")
        assert score_with > score_without

    def test_url_newsroom_pattern_boosts_score(self):
        content = "Company announces new product launch today."
        score_without = press_release.classify(content)
        score_with = press_release.classify(content, url="https://example.com/newsroom/latest")
        assert score_with > score_without

    def test_url_media_pattern_boosts_score(self):
        content = "Company announces new product launch today."
        score_without = press_release.classify(content)
        score_with = press_release.classify(content, url="https://example.com/media/releases")
        assert score_with > score_without

    def test_url_press_release_pattern_boosts_score(self):
        content = "Company announces new product launch today."
        score_without = press_release.classify(content)
        score_with = press_release.classify(content, url="https://example.com/press-release/123")
        assert score_with > score_without

    def test_url_bonus_is_0_2(self):
        # Minimal content so score comes mainly from URL bonus
        content = "Some general text without press release signals."
        score_without = press_release.classify(content)
        score_with = press_release.classify(content, url="https://example.com/press/latest")
        # URL bonus should be 0.2
        assert abs((score_with - score_without) - 0.2) < 0.01

    def test_acquisition_keywords_detected(self):
        content = """
        Press Release
        Acme Corp Announces Acquisition of Beta Inc
        Acme Corp today announced the acquisition of Beta Inc for $500 million.
        Media contact: press@acme.com
        About the company: Acme Corp is a leading provider.
        """
        score = press_release.classify(content)
        assert score >= 0.5

    def test_funding_announcement_detected(self):
        content = """
        For Immediate Release
        Acme Corp Announces $50 Million Series B Funding Round
        Acme Corp announced today it has raised $50 million in Series B funding.
        About Acme Corp
        Media Inquiries: press@acme.com
        """
        score = press_release.classify(content)
        assert score >= 0.5

    def test_no_url_no_bonus(self):
        content = "Company announces partnership today. For immediate release."
        score_no_url = press_release.classify(content, url=None)
        score_non_matching = press_release.classify(content, url="https://example.com/about")
        assert score_no_url == score_non_matching


# ═══════════════════════════════════════════════════════════════
# Press Release Prompt
# ═══════════════════════════════════════════════════════════════

class TestPressReleasePrompt:
    """EXTR-PRESS-PROMPT: Press release prompt construction."""

    def test_prompt_includes_entity(self):
        prompt = press_release.build_prompt("content", "Acme Corp")
        assert "Acme Corp" in prompt
        assert "press release" in prompt.lower()

    def test_prompt_without_entity(self):
        prompt = press_release.build_prompt("content")
        assert "press release" in prompt.lower()
        assert "announcement" in prompt.lower()

    def test_prompt_includes_content(self):
        prompt = press_release.build_prompt("This is the press release text.")
        assert "This is the press release text." in prompt

    def test_prompt_mentions_required_fields(self):
        prompt = press_release.build_prompt("content")
        assert "headline" in prompt.lower()
        assert "publication date" in prompt.lower()
        assert "announcement" in prompt.lower()
        assert "quote" in prompt.lower()
        assert "contact" in prompt.lower()
        assert "implication" in prompt.lower()


# ═══════════════════════════════════════════════════════════════
# Press Release Extraction
# ═══════════════════════════════════════════════════════════════

class TestPressReleaseExtraction:
    """EXTR-PRESS-EXTRACT: Press release extraction with mocked LLM."""

    @patch("core.llm.run_cli")
    def test_successful_extraction(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "headline": "Acme Corp Announces Strategic Partnership",
                "date_published": "2024-01-15",
                "announcement_type": "partnership",
                "key_entities": ["Acme Corp", "Beta Inc"],
                "summary": "Acme Corp has formed a strategic partnership with Beta Inc to expand AI capabilities.",
                "quotes": [
                    {"speaker": "John Smith, CEO", "quote": "This is a transformative deal."},
                ],
                "contact_info": "Jane Doe, press@acme.com",
                "implications": "Strengthens Acme's position in the AI market.",
                "confidence": 0.95,
            },
        }

        result = press_release.extract("Press release content here", "Acme Corp")
        assert result is not None
        assert result["headline"] == "Acme Corp Announces Strategic Partnership"
        assert result["announcement_type"] == "partnership"
        assert result["date_published"] == "2024-01-15"
        assert result["_meta"]["extractor"] == "press_release"

    @patch("core.llm.run_cli")
    def test_key_entities_become_comma_separated(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.008,
            "duration_ms": 1200,
            "is_error": False,
            "structured_output": {
                "headline": "Big Announcement",
                "key_entities": ["Acme Corp", "Beta Inc", "Gamma AI"],
                "summary": "Multiple companies involved.",
                "quotes": [],
                "confidence": 0.9,
            },
        }

        result = press_release.extract("Press release content")
        assert result is not None
        assert result["key_entities"] == "Acme Corp, Beta Inc, Gamma AI"

    @patch("core.llm.run_cli")
    def test_quotes_become_formatted_string(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1400,
            "is_error": False,
            "structured_output": {
                "headline": "Product Launch",
                "summary": "New product launched.",
                "quotes": [
                    {"speaker": "John Smith, CEO", "quote": "This is groundbreaking."},
                    {"speaker": "Jane Doe, CTO", "quote": "The technology is ready."},
                ],
                "confidence": 0.85,
            },
        }

        result = press_release.extract("Press release content")
        assert result is not None
        assert 'John Smith, CEO: "This is groundbreaking."' in result["quotes"]
        assert 'Jane Doe, CTO: "The technology is ready."' in result["quotes"]
        assert "; " in result["quotes"]

    @patch("core.llm.run_cli")
    def test_llm_error_returns_none(self, mock_llm):
        mock_llm.return_value = {
            "result": "Error", "is_error": True, "cost_usd": 0, "duration_ms": 100,
            "structured_output": None,
        }
        result = press_release.extract("Content")
        assert result is None

    @patch("core.llm.run_cli")
    def test_exception_returns_none(self, mock_llm):
        mock_llm.side_effect = RuntimeError("No CLI")
        result = press_release.extract("Content")
        assert result is None

    @patch("core.llm.run_cli")
    def test_meta_includes_model_and_cost(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.015,
            "duration_ms": 2000,
            "is_error": False,
            "structured_output": {
                "headline": "Test",
                "summary": "Test summary.",
                "confidence": 0.7,
            },
        }

        result = press_release.extract("Content", model="haiku")
        assert result is not None
        assert result["_meta"]["extractor"] == "press_release"
        assert result["_meta"]["model"] == "haiku"
        assert result["_meta"]["cost_usd"] == 0.015

    @patch("core.llm.run_cli")
    def test_empty_quotes_list(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.005,
            "duration_ms": 800,
            "is_error": False,
            "structured_output": {
                "headline": "Short Release",
                "summary": "Brief announcement.",
                "quotes": [],
                "confidence": 0.6,
            },
        }

        result = press_release.extract("Content")
        assert result is not None
        assert result["quotes"] == ""

    @patch("core.llm.run_cli")
    def test_empty_content_extract(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.001,
            "duration_ms": 200,
            "is_error": False,
            "structured_output": {
                "confidence": 0.0,
                "summary": "",
            },
        }
        result = press_release.extract("")
        assert result is not None
        assert result["confidence"] == 0.0


# ═══════════════════════════════════════════════════════════════
# Schema Filtering
# ═══════════════════════════════════════════════════════════════

class TestPressReleaseSchemaFiltering:
    """EXTR-PRESS-SCHEMA: Press release extract_for_schema tests."""

    @patch("core.llm.run_cli")
    def test_schema_filtering(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "headline": "Big Partnership Announced",
                "date_published": "2024-01-15",
                "announcement_type": "partnership",
                "key_entities": ["Acme Corp", "Beta Inc"],
                "summary": "Partnership between two companies.",
                "quotes": [
                    {"speaker": "CEO", "quote": "Great news."},
                ],
                "contact_info": "press@acme.com",
                "implications": "Major market impact.",
                "confidence": 0.9,
            },
        }

        result = press_release.extract_for_schema(
            "Press release content",
            "Acme Corp",
            schema_attributes=["headline", "announcement_type"],
        )
        assert result is not None
        assert "headline" in result
        assert "announcement_type" in result
        # Should NOT include unrequested attributes
        assert "summary" not in result
        assert "contact_info" not in result
        assert "implications" not in result
        assert "_meta" in result

    @patch("core.llm.run_cli")
    def test_schema_filtering_no_matching_attrs_returns_none(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "headline": "Test",
                "summary": "Test.",
                "confidence": 0.7,
            },
        }

        result = press_release.extract_for_schema(
            "Press release content",
            "Acme Corp",
            schema_attributes=["nonexistent_attribute"],
        )
        assert result is None

    @patch("core.llm.run_cli")
    def test_schema_filtering_all_attributes(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "headline": "Headline",
                "date_published": "2024-01-15",
                "announcement_type": "funding",
                "key_entities": ["Acme"],
                "summary": "Summary text.",
                "quotes": [{"speaker": "CEO", "quote": "Quote."}],
                "contact_info": "press@acme.com",
                "implications": "Big impact.",
                "confidence": 0.9,
            },
        }

        all_attrs = list(press_release.ATTRIBUTE_SLUG_MAP.values())
        result = press_release.extract_for_schema(
            "Content", "Acme", schema_attributes=all_attrs,
        )
        assert result is not None
        for slug in all_attrs:
            assert slug in result

    @patch("core.llm.run_cli")
    def test_schema_filtering_skips_empty_values(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "headline": "Test",
                "date_published": "",
                "summary": "A summary.",
                "confidence": 0.8,
            },
        }

        result = press_release.extract_for_schema(
            "Content", "Acme",
            schema_attributes=["headline", "date_published"],
        )
        assert result is not None
        assert "headline" in result
        # Empty date_published should be excluded
        assert "date_published" not in result

    @patch("core.llm.run_cli")
    def test_schema_filtering_extraction_failure_returns_none(self, mock_llm):
        mock_llm.side_effect = RuntimeError("No CLI")
        result = press_release.extract_for_schema(
            "Content", "Acme", schema_attributes=["headline"],
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════
# Classifier Integration
# ═══════════════════════════════════════════════════════════════

class TestPressReleaseClassifierIntegration:
    """EXTR-PRESS-ROUTE: Press release routing via classifier."""

    def test_press_release_content_routes_to_press_release(self):
        content = """
        FOR IMMEDIATE RELEASE

        Acme Corp Announces Strategic Acquisition of Beta Inc

        SAN FRANCISCO, CA — Acme Corp, a leading enterprise software company,
        today announced the acquisition of Beta Inc for $200 million.

        "This acquisition strengthens our position in the market," said the CEO.

        About Acme Corp
        Acme Corp was founded in 2018 and serves over 500 enterprise customers.

        Media Contact:
        Jane Doe, VP Communications
        press@acme.com
        Forward-looking statements apply.
        Investor Relations: ir@acme.com
        """
        extractor, name, confidence = classify_content(content)
        assert name == "press_release"
        assert confidence >= CLASSIFICATION_THRESHOLD

    def test_press_release_in_available_extractors(self):
        extractors = get_available_extractors()
        assert "press_release" in extractors

    @patch("core.llm.run_cli")
    def test_forced_press_release_extractor(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "headline": "Test Headline",
                "summary": "Test summary.",
                "announcement_type": "other",
                "confidence": 0.5,
            },
        }

        result = extract_with_classification(
            "Any content", force_extractor="press_release"
        )
        assert result is not None
        assert result["_classification"]["extractor"] == "press_release"
        assert result["_classification"]["classification_confidence"] == 1.0

    def test_non_press_content_does_not_route_to_press_release(self):
        content = """
        Get started with our platform today. Sign up for a free trial.
        Features include analytics, reporting, and integrations.
        How it works: connect your data, get insights.
        Trusted by 500+ customers. Request a demo.
        """
        extractor, name, confidence = classify_content(content)
        assert name != "press_release"


# ═══════════════════════════════════════════════════════════════
# API Endpoints
# ═══════════════════════════════════════════════════════════════

class TestPressReleaseAPI:
    """EXTR-PRESS-API: Press release API endpoint tests."""

    @pytest.mark.api
    def test_press_release_in_extractors_list(self, client):
        r = client.get("/api/extract/extractors")
        assert r.status_code == 200
        data = r.get_json()
        assert "press_release" in data["extractors"]

    @pytest.mark.api
    @patch("core.llm.run_cli")
    def test_classify_routes_press_release(self, mock_llm, client):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1200,
            "is_error": False,
            "structured_output": {
                "headline": "Press Release Headline",
                "summary": "A press release summary.",
                "announcement_type": "product_launch",
                "confidence": 0.9,
            },
        }

        content = """
        FOR IMMEDIATE RELEASE
        Acme Corp Announces New Product Launch
        Acme Corp announced today the launch of its platform.
        About Acme Corp. Media Contact: press@acme.com
        Forward-looking statements. Investor relations.
        Partnership with leading providers. Media inquiries welcome.
        """
        r = client.post("/api/extract/classify", json={
            "content": content,
            "entity_name": "Acme Corp",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["_classification"]["extractor"] == "press_release"

    @pytest.mark.api
    @patch("core.llm.run_cli")
    def test_classify_forced_press_release(self, mock_llm, client):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.005,
            "duration_ms": 800,
            "is_error": False,
            "structured_output": {
                "headline": "Forced Classification",
                "summary": "Test.",
                "confidence": 0.5,
            },
        }

        r = client.post("/api/extract/classify", json={
            "content": "Some generic content",
            "force_extractor": "press_release",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["_classification"]["extractor"] == "press_release"
        assert data["_classification"]["classification_confidence"] == 1.0
