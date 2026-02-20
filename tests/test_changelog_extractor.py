"""Tests for changelog/release notes extractor — classification, extraction, routing.

Covers:
- Changelog classification: keyword scoring, URL patterns, version strings
- Changelog extraction: mocked LLM, schema filtering, error handling
- Classifier integration: routing, available extractors, forced extractor

Run: pytest tests/test_changelog_extractor.py -v
Markers: db, extraction
"""
import pytest
from unittest.mock import patch

from core.extractors import changelog
from core.extractors.classifier import (
    classify_content,
    extract_with_classification,
    get_available_extractors,
    CLASSIFICATION_THRESHOLD,
)

pytestmark = [pytest.mark.db, pytest.mark.extraction]


# ═══════════════════════════════════════════════════════════════
# Changelog Classification
# ═══════════════════════════════════════════════════════════════

class TestChangelogClassifier:
    """EXTR-CL-CLASS: Changelog page classification heuristics."""

    def test_changelog_page_high_confidence(self):
        content = """
        Changelog
        v2.5.0 — 2024-01-15
        New features: Dark mode, API v2 support.
        Improvements: Faster search, reduced memory usage.
        Bug fixes: Fixed login timeout, corrected CSV export.

        v2.4.0 — 2023-12-01
        New features: Webhook integrations.
        Breaking changes: Removed legacy auth endpoint.

        v2.3.1 — 2023-11-10
        Bug fixes: Hotfix for dashboard rendering.
        """
        score = changelog.classify(content)
        assert score >= 0.6

    def test_release_notes_page_high_confidence(self):
        content = """
        Release Notes
        What's New in version 3.0
        We're excited to announce major improvements and new features.
        Bug fixes and performance improvements across the board.
        Breaking changes: The v1 API has been deprecated.
        """
        score = changelog.classify(content)
        assert score >= 0.6

    def test_non_changelog_article_low_confidence(self):
        content = """
        This is a blog post about the future of artificial intelligence.
        Researchers at MIT have published a new paper on transformer architectures.
        The study examines scaling laws and their implications for language models.
        """
        score = changelog.classify(content)
        assert score < 0.3

    def test_marketing_page_low_confidence(self):
        content = """
        Get started with our platform today. Sign up for a free trial.
        Features include analytics, reporting, and integrations.
        Trusted by 500+ customers including Fortune 500 companies.
        Request a demo now.
        """
        score = changelog.classify(content)
        assert score < 0.3

    def test_empty_content_returns_zero(self):
        score = changelog.classify("")
        assert score == 0.0

    def test_none_content_returns_zero(self):
        score = changelog.classify(None)
        assert score == 0.0

    def test_url_changelog_pattern_boosts_score(self):
        content = "Product updates and version history."
        score_without = changelog.classify(content)
        score_with = changelog.classify(content, url="https://example.com/changelog")
        assert score_with > score_without

    def test_url_releases_pattern_boosts_score(self):
        content = "Product updates and version history."
        score_without = changelog.classify(content)
        score_with = changelog.classify(content, url="https://example.com/releases")
        assert score_with > score_without

    def test_multiple_version_strings_boost_score(self):
        # Content with version strings but minimal changelog keywords
        content_few = "Here is some generic text about the product."
        content_many = """
        v1.0.0 — Initial release.
        v1.1.0 — Added search.
        v1.2.0 — Added filters.
        v2.0.0 — Major rewrite.
        """
        score_few = changelog.classify(content_few)
        score_many = changelog.classify(content_many)
        # Multiple version strings should boost the score above content without them
        assert score_many > score_few

    def test_whats_new_heading(self):
        content = """
        What's New
        We added new features and improvements.
        Bug fixes for better stability.
        New features include dark mode and keyboard shortcuts.
        """
        score = changelog.classify(content)
        assert score >= 0.4


# ═══════════════════════════════════════════════════════════════
# Changelog Prompt
# ═══════════════════════════════════════════════════════════════

class TestChangelogPrompt:
    """EXTR-CL-PROMPT: Changelog prompt construction."""

    def test_prompt_includes_entity(self):
        prompt = changelog.build_prompt("content", "Acme Corp")
        assert "Acme Corp" in prompt
        assert "changelog" in prompt.lower()

    def test_prompt_without_entity(self):
        prompt = changelog.build_prompt("content")
        assert "changelog" in prompt.lower()
        assert "release" in prompt.lower()


# ═══════════════════════════════════════════════════════════════
# Changelog Extraction
# ═══════════════════════════════════════════════════════════════

class TestChangelogExtraction:
    """EXTR-CL-EXTRACT: Changelog extraction with mocked LLM."""

    @patch("core.llm.run_cli")
    def test_successful_extraction(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "latest_version": "2.5.0",
                "latest_release_date": "2024-01-15",
                "release_frequency": "monthly",
                "recent_features": ["Dark mode", "API v2"],
                "recent_improvements": ["Faster search"],
                "breaking_changes": [],
                "product_maturity": "growing",
                "total_releases_visible": 12,
                "confidence": 0.85,
            },
        }

        result = changelog.extract("Changelog content here", "Acme Corp")
        assert result is not None
        assert result["latest_version"] == "2.5.0"
        assert result["release_frequency"] == "monthly"
        assert result["product_maturity"] == "growing"
        assert result["_meta"]["extractor"] == "changelog"

    @patch("core.llm.run_cli")
    def test_array_fields_become_comma_separated(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.008,
            "duration_ms": 1200,
            "is_error": False,
            "structured_output": {
                "latest_version": "1.0.0",
                "recent_features": ["Feature A", "Feature B", "Feature C"],
                "recent_improvements": ["Speed boost", "Memory reduction"],
                "breaking_changes": ["Removed v1 API"],
                "confidence": 0.9,
            },
        }

        result = changelog.extract("Changelog content")
        assert result is not None
        assert result["recent_features"] == "Feature A, Feature B, Feature C"
        assert result["recent_improvements"] == "Speed boost, Memory reduction"
        assert result["breaking_changes"] == "Removed v1 API"

    @patch("core.llm.run_cli")
    def test_llm_error_returns_none(self, mock_llm):
        mock_llm.return_value = {
            "result": "Error", "is_error": True, "cost_usd": 0, "duration_ms": 100,
            "structured_output": None,
        }
        result = changelog.extract("Content")
        assert result is None

    @patch("core.llm.run_cli")
    def test_exception_returns_none(self, mock_llm):
        mock_llm.side_effect = RuntimeError("No CLI")
        result = changelog.extract("Content")
        assert result is None

    @patch("core.llm.run_cli")
    def test_schema_filtering(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "latest_version": "2.5.0",
                "latest_release_date": "2024-01-15",
                "release_frequency": "monthly",
                "recent_features": ["Dark mode"],
                "recent_improvements": ["Faster search"],
                "breaking_changes": [],
                "product_maturity": "growing",
                "total_releases_visible": 12,
                "confidence": 0.85,
            },
        }

        # Only request two attributes
        result = changelog.extract_for_schema(
            "Changelog content",
            "Acme Corp",
            schema_attributes=["latest_version", "release_frequency"],
        )
        assert result is not None
        assert "latest_version" in result
        assert "release_frequency" in result
        # Should NOT include unrequested attributes
        assert "product_maturity" not in result
        assert "recent_features" not in result
        assert "_meta" in result

    @patch("core.llm.run_cli")
    def test_schema_filtering_no_matching_attrs_returns_none(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "latest_version": "1.0.0",
                "confidence": 0.7,
            },
        }

        result = changelog.extract_for_schema(
            "Changelog content",
            "Acme Corp",
            schema_attributes=["nonexistent_attribute"],
        )
        assert result is None

    @patch("core.llm.run_cli")
    def test_empty_content_extract(self, mock_llm):
        # Even with empty content, the function passes it to LLM;
        # LLM decides confidence. Simulate a low-confidence response.
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.001,
            "duration_ms": 200,
            "is_error": False,
            "structured_output": {
                "confidence": 0.0,
            },
        }
        result = changelog.extract("")
        # Still returns a result (LLM responded), but confidence is 0
        assert result is not None
        assert result["confidence"] == 0.0


# ═══════════════════════════════════════════════════════════════
# Classifier Integration
# ═══════════════════════════════════════════════════════════════

class TestChangelogClassifierIntegration:
    """EXTR-CL-ROUTE: Changelog routing via classifier."""

    def test_changelog_content_routes_to_changelog(self):
        content = """
        Changelog
        v3.0.0 — 2024-02-01
        New features: SSO integration, role-based access control.
        Improvements: Dashboard load time reduced by 40%.
        Bug fixes: Fixed timezone display, corrected billing calculation.
        Breaking changes: Legacy API v1 endpoints removed.

        v2.9.0 — 2024-01-10
        New features: Webhook support.
        Improvements: Improved search relevance.

        v2.8.0 — 2023-12-15
        Bug fixes: Various stability improvements.
        """
        extractor, name, confidence = classify_content(content)
        assert name == "changelog"
        assert confidence >= CLASSIFICATION_THRESHOLD

    def test_changelog_in_available_extractors(self):
        extractors = get_available_extractors()
        assert "changelog" in extractors

    @patch("core.llm.run_cli")
    def test_forced_changelog_extractor(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.01,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "latest_version": "1.0.0",
                "release_frequency": "irregular",
                "recent_features": [],
                "recent_improvements": [],
                "breaking_changes": [],
                "product_maturity": "early-stage",
                "confidence": 0.5,
            },
        }

        result = extract_with_classification(
            "Any content", force_extractor="changelog"
        )
        assert result is not None
        assert result["_classification"]["extractor"] == "changelog"
        assert result["_classification"]["classification_confidence"] == 1.0
