"""Tests for Extraction Pipeline — DB layer, extraction logic, contradiction detection.

Covers:
- ExtractionMixin: job CRUD, result CRUD, review workflow, bulk review, stats
- Extraction engine: prompt building, schema building, content extraction (mocked LLM)
- Evidence reading and extraction flow
- Contradiction detection

Run: pytest tests/test_extraction.py -v
Markers: db, extraction
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.extraction import (
    ExtractionResult,
    _build_extraction_prompt,
    _build_extraction_schema,
    _read_evidence_content,
    extract_from_content,
    detect_contradictions,
    clear_extraction_cache,
    MAX_CONTENT_LENGTH,
    DEFAULT_EXTRACTION_MODEL,
)

pytestmark = [pytest.mark.db, pytest.mark.extraction]


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

SAMPLE_SCHEMA = {
    "version": 1,
    "entity_types": [
        {
            "name": "Company",
            "slug": "company",
            "description": "A company entity",
            "icon": "building",
            "parent_type": None,
            "attributes": [
                {"name": "Description", "slug": "description", "data_type": "text"},
                {"name": "Website URL", "slug": "website_url", "data_type": "url"},
                {"name": "Founded Year", "slug": "founded_year", "data_type": "number"},
                {"name": "Employee Count", "slug": "employee_count", "data_type": "text"},
                {"name": "Headquarters", "slug": "headquarters", "data_type": "text"},
                {"name": "Pricing Model", "slug": "pricing_model", "data_type": "enum",
                 "enum_values": ["freemium", "subscription", "pay-per-use", "enterprise"]},
                {"name": "Has Free Tier", "slug": "has_free_tier", "data_type": "boolean"},
                {"name": "Tags", "slug": "tags", "data_type": "tags"},
            ],
        },
    ],
    "relationships": [],
}


@pytest.fixture
def extraction_project(tmp_path):
    """Create a DB with project, entity, and extraction-ready schema."""
    from storage.db import Database
    db = Database(db_path=tmp_path / "test.db")
    pid = db.create_project(
        name="Extraction Test Project",
        purpose="Testing extraction pipeline",
        entity_schema=SAMPLE_SCHEMA,
    )
    eid = db.create_entity(pid, "company", "Acme Corp")
    return {"db": db, "project_id": pid, "entity_id": eid}


@pytest.fixture
def extraction_with_evidence(extraction_project, tmp_path, monkeypatch):
    """Project with entity + a text evidence file."""
    import core.capture as capture_mod
    test_evidence_dir = tmp_path / "evidence"
    test_evidence_dir.mkdir()
    monkeypatch.setattr(capture_mod, "EVIDENCE_DIR", test_evidence_dir)

    db = extraction_project["db"]
    pid = extraction_project["project_id"]
    eid = extraction_project["entity_id"]

    # Create a text evidence file
    evidence_dir = test_evidence_dir / str(pid) / str(eid) / "page_archive"
    evidence_dir.mkdir(parents=True)
    html_file = evidence_dir / "acme_homepage.html"
    html_file.write_text("""
    <html><body>
    <h1>Acme Corp</h1>
    <p>We are a SaaS company founded in 2019 with 150 employees.</p>
    <p>Based in San Francisco, CA.</p>
    <p>Our pricing is freemium — start free, upgrade for more features.</p>
    <p>We provide enterprise solutions for supply chain management.</p>
    </body></html>
    """)

    relative_path = f"{pid}/{eid}/page_archive/acme_homepage.html"
    ev_id = db.add_evidence(
        entity_id=eid,
        evidence_type="page_archive",
        file_path=relative_path,
        source_url="https://acme.com",
        source_name="Website capture",
    )

    return {
        **extraction_project,
        "evidence_id": ev_id,
        "evidence_dir": test_evidence_dir,
    }


# ═══════════════════════════════════════════════════════════════
# ExtractionResult Dataclass
# ═══════════════════════════════════════════════════════════════

class TestExtractionResult:
    """EXT-RES: ExtractionResult dataclass tests."""

    def test_default_values(self):
        r = ExtractionResult(success=True, entity_id=1)
        assert r.success is True
        assert r.entity_id == 1
        assert r.extracted_attributes == []
        assert r.error is None
        assert r.cost_usd == 0.0
        assert r.duration_ms == 0

    def test_to_dict(self):
        r = ExtractionResult(
            success=True, entity_id=1,
            extracted_attributes=[{"attr_slug": "name", "value": "test"}],
            model="claude-sonnet-4-6",
            cost_usd=0.01,
        )
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["success"] is True
        assert len(d["extracted_attributes"]) == 1

    def test_error_result(self):
        r = ExtractionResult(success=False, entity_id=1, error="Something failed")
        assert r.success is False
        assert r.error == "Something failed"


# ═══════════════════════════════════════════════════════════════
# Prompt & Schema Building
# ═══════════════════════════════════════════════════════════════

class TestPromptBuilding:
    """EXT-PROMPT: Extraction prompt construction tests."""

    def test_basic_prompt(self):
        attrs = [
            {"name": "Description", "slug": "description", "data_type": "text"},
            {"name": "Founded", "slug": "founded", "data_type": "number"},
        ]
        prompt = _build_extraction_prompt(
            "Acme Corp", "Company", attrs, "Some content here"
        )
        assert "Acme Corp" in prompt
        assert "Company" in prompt
        assert "description" in prompt
        assert "founded" in prompt
        assert "Some content here" in prompt

    def test_enum_values_in_prompt(self):
        attrs = [
            {"name": "Model", "slug": "model", "data_type": "enum",
             "enum_values": ["free", "paid"]},
        ]
        prompt = _build_extraction_prompt("X", "Type", attrs, "Content")
        assert "free" in prompt
        assert "paid" in prompt
        assert "allowed values" in prompt

    def test_content_truncation(self):
        long_content = "x" * (MAX_CONTENT_LENGTH + 1000)
        attrs = [{"name": "A", "slug": "a", "data_type": "text"}]
        prompt = _build_extraction_prompt("X", "T", attrs, long_content)
        assert "[... content truncated ...]" in prompt

    def test_custom_source_description(self):
        attrs = [{"name": "A", "slug": "a", "data_type": "text"}]
        prompt = _build_extraction_prompt("X", "T", attrs, "C", "pricing page")
        assert "pricing page" in prompt

    def test_empty_attributes(self):
        prompt = _build_extraction_prompt("X", "T", [], "Content")
        assert "No specific attributes defined" in prompt


class TestSchemaBuilding:
    """EXT-SCHEMA: JSON schema for structured LLM output."""

    def test_schema_structure(self):
        attrs = [{"name": "A", "slug": "a", "data_type": "text"}]
        schema = _build_extraction_schema(attrs)
        assert schema["type"] == "object"
        assert "extracted_attributes" in schema["properties"]
        assert schema["properties"]["extracted_attributes"]["type"] == "array"

    def test_schema_item_properties(self):
        attrs = [{"name": "A", "slug": "a", "data_type": "text"}]
        schema = _build_extraction_schema(attrs)
        item = schema["properties"]["extracted_attributes"]["items"]
        assert "attr_slug" in item["properties"]
        assert "value" in item["properties"]
        assert "confidence" in item["properties"]
        assert "reasoning" in item["properties"]


# ═══════════════════════════════════════════════════════════════
# Evidence Reading
# ═══════════════════════════════════════════════════════════════

class TestEvidenceReading:
    """EXT-READ: Evidence file reading for extraction."""

    def test_read_html_evidence(self, extraction_with_evidence):
        db = extraction_with_evidence["db"]
        ev_id = extraction_with_evidence["evidence_id"]
        evidence = db.get_evidence_by_id(ev_id)

        content, content_type = _read_evidence_content(evidence)
        assert content is not None
        assert content_type == "text"
        assert "Acme Corp" in content

    def test_read_nonexistent_file(self):
        evidence = {
            "file_path": "999/999/page_archive/nonexistent.html",
            "evidence_type": "page_archive",
        }
        content, content_type = _read_evidence_content(evidence)
        assert content is None
        assert content_type is None

    def test_screenshot_returns_image_type(self, extraction_with_evidence):
        evidence = {
            "file_path": "1/1/screenshot/shot.png",
            "evidence_type": "screenshot",
        }
        content, content_type = _read_evidence_content(evidence)
        assert content is None
        assert content_type == "image"


# ═══════════════════════════════════════════════════════════════
# Content Extraction (Mocked LLM)
# ═══════════════════════════════════════════════════════════════

class TestContentExtraction:
    """EXT-CONTENT: extract_from_content with mocked LLM."""

    def setup_method(self):
        """Clear extraction cache before each test to avoid cross-test interference."""
        clear_extraction_cache()

    @patch("core.llm.run_cli")
    def test_successful_extraction(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.005,
            "duration_ms": 1500,
            "is_error": False,
            "structured_output": {
                "extracted_attributes": [
                    {
                        "attr_slug": "description",
                        "value": "Enterprise SaaS platform",
                        "confidence": 0.9,
                        "reasoning": "Stated on homepage",
                    },
                    {
                        "attr_slug": "founded_year",
                        "value": 2019,
                        "confidence": 0.95,
                        "reasoning": "Mentioned in About section",
                    },
                ],
                "entity_summary": "Acme is an enterprise SaaS company",
            },
        }

        attrs = SAMPLE_SCHEMA["entity_types"][0]["attributes"]
        result = extract_from_content(
            "Some HTML content", "Acme Corp", "Company", attrs
        )

        assert result.success is True
        assert len(result.extracted_attributes) == 2
        assert result.extracted_attributes[0]["attr_slug"] == "description"
        assert result.cost_usd == 0.005
        mock_llm.assert_called_once()

    @patch("core.llm.run_cli")
    def test_filters_unknown_attributes(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.003,
            "duration_ms": 1000,
            "is_error": False,
            "structured_output": {
                "extracted_attributes": [
                    {"attr_slug": "description", "value": "Test", "confidence": 0.8, "reasoning": "OK"},
                    {"attr_slug": "unknown_attr", "value": "Bad", "confidence": 0.5, "reasoning": "Hmm"},
                ],
            },
        }

        attrs = SAMPLE_SCHEMA["entity_types"][0]["attributes"]
        result = extract_from_content("Content", "X", "Company", attrs)

        assert result.success is True
        assert len(result.extracted_attributes) == 1
        assert result.extracted_attributes[0]["attr_slug"] == "description"

    @patch("core.llm.run_cli")
    def test_clamps_confidence(self, mock_llm):
        mock_llm.return_value = {
            "result": "",
            "cost_usd": 0.001,
            "duration_ms": 500,
            "is_error": False,
            "structured_output": {
                "extracted_attributes": [
                    {"attr_slug": "description", "value": "Test", "confidence": 1.5, "reasoning": "X"},
                    {"attr_slug": "headquarters", "value": "NY", "confidence": -0.3, "reasoning": "Y"},
                ],
            },
        }

        attrs = SAMPLE_SCHEMA["entity_types"][0]["attributes"]
        result = extract_from_content("Content", "X", "Company", attrs)

        assert result.extracted_attributes[0]["confidence"] == 1.0
        assert result.extracted_attributes[1]["confidence"] == 0.0

    @patch("core.llm.run_cli")
    def test_llm_error(self, mock_llm):
        mock_llm.return_value = {
            "result": "Error occurred",
            "cost_usd": 0.001,
            "duration_ms": 200,
            "is_error": True,
            "structured_output": None,
        }

        attrs = SAMPLE_SCHEMA["entity_types"][0]["attributes"]
        result = extract_from_content("Content", "X", "Company", attrs)

        assert result.success is False
        assert "Error occurred" in result.error

    @patch("core.llm.run_cli")
    def test_llm_exception(self, mock_llm):
        mock_llm.side_effect = RuntimeError("CLI not found")

        attrs = SAMPLE_SCHEMA["entity_types"][0]["attributes"]
        result = extract_from_content("Content", "X", "Company", attrs)

        assert result.success is False
        assert "CLI not found" in result.error

    def test_empty_content(self):
        attrs = SAMPLE_SCHEMA["entity_types"][0]["attributes"]
        result = extract_from_content("", "X", "Company", attrs)
        assert result.success is False
        assert "No content" in result.error

    def test_no_attributes(self):
        result = extract_from_content("Content", "X", "Company", [])
        assert result.success is False
        assert "No attributes" in result.error

    @patch("core.llm.run_cli")
    def test_no_structured_output_falls_back(self, mock_llm):
        mock_llm.return_value = {
            "result": '{"extracted_attributes": [{"attr_slug": "description", "value": "Test", "confidence": 0.7, "reasoning": "Found"}]}',
            "cost_usd": 0.002,
            "duration_ms": 800,
            "is_error": False,
            "structured_output": None,
        }

        attrs = SAMPLE_SCHEMA["entity_types"][0]["attributes"]
        result = extract_from_content("Content", "X", "Company", attrs)

        assert result.success is True
        assert len(result.extracted_attributes) == 1


# ═══════════════════════════════════════════════════════════════
# Extraction Job CRUD (DB Layer)
# ═══════════════════════════════════════════════════════════════

class TestExtractionJobCRUD:
    """EXT-JOB: Extraction job database operations."""

    def test_create_job(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid, source_type="evidence")
        assert job_id is not None
        assert isinstance(job_id, int)

    def test_get_job(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid, source_type="url", source_ref="https://example.com")
        job = db.get_extraction_job(job_id)

        assert job is not None
        assert job["project_id"] == pid
        assert job["entity_id"] == eid
        assert job["status"] == "pending"
        assert job["source_type"] == "url"
        assert job["source_ref"] == "https://example.com"

    def test_get_nonexistent_job(self, extraction_project):
        db = extraction_project["db"]
        assert db.get_extraction_job(99999) is None

    def test_update_job(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        db.update_extraction_job(
            job_id,
            status="completed",
            model="claude-sonnet-4-6",
            cost_usd=0.005,
            duration_ms=1500,
            result_count=3,
            completed_at="2026-02-20T12:00:00",
        )

        job = db.get_extraction_job(job_id)
        assert job["status"] == "completed"
        assert job["model"] == "claude-sonnet-4-6"
        assert job["cost_usd"] == 0.005
        assert job["duration_ms"] == 1500
        assert job["result_count"] == 3

    def test_list_jobs(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        db.create_extraction_job(pid, eid, source_type="evidence")
        db.create_extraction_job(pid, eid, source_type="url")

        jobs = db.get_extraction_jobs(project_id=pid)
        assert len(jobs) == 2

    def test_list_jobs_filter_status(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        j1 = db.create_extraction_job(pid, eid)
        j2 = db.create_extraction_job(pid, eid)
        db.update_extraction_job(j1, status="completed")

        completed = db.get_extraction_jobs(project_id=pid, status="completed")
        assert len(completed) == 1
        assert completed[0]["id"] == j1

    def test_delete_job(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        db.delete_extraction_job(job_id)
        assert db.get_extraction_job(job_id) is None


# ═══════════════════════════════════════════════════════════════
# Extraction Result CRUD (DB Layer)
# ═══════════════════════════════════════════════════════════════

class TestExtractionResultCRUD:
    """EXT-RESULT: Extraction result database operations."""

    def test_create_result(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        result_id = db.create_extraction_result(
            job_id, eid, "description", "A SaaS company",
            confidence=0.9, reasoning="Found on homepage",
        )
        assert result_id is not None

    def test_get_result(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        result_id = db.create_extraction_result(
            job_id, eid, "headquarters", "San Francisco",
            confidence=0.85, reasoning="About page",
        )

        result = db.get_extraction_result(result_id)
        assert result is not None
        assert result["attr_slug"] == "headquarters"
        assert result["extracted_value"] == "San Francisco"
        assert result["confidence"] == 0.85
        assert result["status"] == "pending"

    def test_create_result_serializes_dict(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        result_id = db.create_extraction_result(
            job_id, eid, "tags", ["saas", "enterprise"],
        )
        result = db.get_extraction_result(result_id)
        assert result["extracted_value"] == '["saas", "enterprise"]'

    def test_create_result_serializes_bool(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        result_id = db.create_extraction_result(
            job_id, eid, "has_free_tier", True,
        )
        result = db.get_extraction_result(result_id)
        assert result["extracted_value"] == "1"

    def test_batch_create_results(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        results = [
            {"attr_slug": "description", "value": "SaaS", "confidence": 0.9, "reasoning": "Homepage"},
            {"attr_slug": "headquarters", "value": "NYC", "confidence": 0.8, "reasoning": "About"},
            {"attr_slug": "founded_year", "value": 2019, "confidence": 0.95, "reasoning": "Footer"},
        ]

        ids = db.create_extraction_results_batch(job_id, eid, results)
        assert len(ids) == 3

        all_results = db.get_extraction_results(job_id=job_id)
        assert len(all_results) == 3

    def test_list_results_by_entity(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        db.create_extraction_result(job_id, eid, "description", "Test")
        db.create_extraction_result(job_id, eid, "headquarters", "NYC")

        results = db.get_extraction_results(entity_id=eid)
        assert len(results) == 2

    def test_list_results_by_status(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        r1 = db.create_extraction_result(job_id, eid, "description", "Test")
        r2 = db.create_extraction_result(job_id, eid, "headquarters", "NYC")
        db.review_extraction_result(r1, "accept")

        pending = db.get_extraction_results(entity_id=eid, status="pending")
        assert len(pending) == 1
        assert pending[0]["attr_slug"] == "headquarters"

    def test_list_results_by_attr_slug(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        db.create_extraction_result(job_id, eid, "description", "Test")
        db.create_extraction_result(job_id, eid, "headquarters", "NYC")

        results = db.get_extraction_results(entity_id=eid, attr_slug="description")
        assert len(results) == 1

    def test_cascade_delete_with_job(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        r_id = db.create_extraction_result(job_id, eid, "description", "Test")
        db.delete_extraction_job(job_id)

        assert db.get_extraction_result(r_id) is None


# ═══════════════════════════════════════════════════════════════
# Review Workflow
# ═══════════════════════════════════════════════════════════════

class TestReviewWorkflow:
    """EXT-REVIEW: Extraction result review workflow."""

    def test_accept_result(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        result_id = db.create_extraction_result(
            job_id, eid, "headquarters", "San Francisco",
            confidence=0.9,
        )

        success = db.review_extraction_result(result_id, "accept")
        assert success is True

        result = db.get_extraction_result(result_id)
        assert result["status"] == "accepted"
        assert result["reviewed_at"] is not None

        # Check that the value was written to entity attributes
        entity = db.get_entity(eid)
        assert entity["attributes"]["headquarters"]["value"] == "San Francisco"

    def test_reject_result(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        result_id = db.create_extraction_result(
            job_id, eid, "description", "Wrong description",
        )

        success = db.review_extraction_result(result_id, "reject")
        assert success is True

        result = db.get_extraction_result(result_id)
        assert result["status"] == "rejected"

        # Rejected value should NOT be in entity attributes
        entity = db.get_entity(eid)
        assert "description" not in entity["attributes"]

    def test_edit_result(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        result_id = db.create_extraction_result(
            job_id, eid, "headquarters", "San Fran",
        )

        success = db.review_extraction_result(result_id, "edit", "San Francisco, CA")
        assert success is True

        result = db.get_extraction_result(result_id)
        assert result["status"] == "edited"
        assert result["reviewed_value"] == "San Francisco, CA"

        # Edited value should be in entity attributes
        entity = db.get_entity(eid)
        assert entity["attributes"]["headquarters"]["value"] == "San Francisco, CA"

    def test_review_nonexistent_result(self, extraction_project):
        db = extraction_project["db"]
        success = db.review_extraction_result(99999, "accept")
        assert success is False

    def test_review_invalid_action(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        result_id = db.create_extraction_result(job_id, eid, "description", "Test")

        success = db.review_extraction_result(result_id, "invalid_action")
        assert success is False

    def test_bulk_accept(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        r1 = db.create_extraction_result(job_id, eid, "description", "SaaS platform")
        r2 = db.create_extraction_result(job_id, eid, "headquarters", "NYC")
        r3 = db.create_extraction_result(job_id, eid, "founded_year", "2020")

        count = db.bulk_review_extraction_results([r1, r2, r3], "accept")
        assert count == 3

        # All should be accepted
        for rid in [r1, r2, r3]:
            result = db.get_extraction_result(rid)
            assert result["status"] == "accepted"

        # All values should be in entity attributes
        entity = db.get_entity(eid)
        assert entity["attributes"]["description"]["value"] == "SaaS platform"
        assert entity["attributes"]["headquarters"]["value"] == "NYC"

    def test_bulk_reject(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        r1 = db.create_extraction_result(job_id, eid, "description", "Bad")
        r2 = db.create_extraction_result(job_id, eid, "headquarters", "Wrong")

        count = db.bulk_review_extraction_results([r1, r2], "reject")
        assert count == 2

    def test_bulk_skips_already_reviewed(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        r1 = db.create_extraction_result(job_id, eid, "description", "Test")
        r2 = db.create_extraction_result(job_id, eid, "headquarters", "NYC")

        # Accept r1 first
        db.review_extraction_result(r1, "accept")

        # Bulk accept both — r1 should be skipped
        count = db.bulk_review_extraction_results([r1, r2], "accept")
        assert count == 1

    def test_bulk_empty_ids(self, extraction_project):
        db = extraction_project["db"]
        count = db.bulk_review_extraction_results([], "accept")
        assert count == 0

    def test_bulk_invalid_action(self, extraction_project):
        db = extraction_project["db"]
        count = db.bulk_review_extraction_results([1, 2], "edit")
        assert count == 0


# ═══════════════════════════════════════════════════════════════
# Review Queue
# ═══════════════════════════════════════════════════════════════

class TestReviewQueue:
    """EXT-QUEUE: Extraction review queue."""

    def test_queue_returns_pending(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        db.create_extraction_result(job_id, eid, "description", "Test", confidence=0.9)
        db.create_extraction_result(job_id, eid, "headquarters", "NYC", confidence=0.7)

        queue = db.get_extraction_queue(pid)
        assert len(queue) == 2
        # Should be ordered by confidence DESC
        assert queue[0]["confidence"] >= queue[1]["confidence"]

    def test_queue_includes_entity_info(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        db.create_extraction_result(job_id, eid, "description", "Test")

        queue = db.get_extraction_queue(pid)
        assert len(queue) == 1
        assert queue[0]["entity_name"] == "Acme Corp"
        assert queue[0]["entity_type"] == "company"

    def test_queue_excludes_reviewed(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        r1 = db.create_extraction_result(job_id, eid, "description", "Test")
        r2 = db.create_extraction_result(job_id, eid, "headquarters", "NYC")
        db.review_extraction_result(r1, "accept")

        queue = db.get_extraction_queue(pid)
        assert len(queue) == 1
        assert queue[0]["attr_slug"] == "headquarters"

    def test_queue_empty_project(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        queue = db.get_extraction_queue(pid)
        assert queue == []


# ═══════════════════════════════════════════════════════════════
# Extraction Statistics
# ═══════════════════════════════════════════════════════════════

class TestExtractionStats:
    """EXT-STATS: Extraction statistics."""

    def test_empty_stats(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]

        stats = db.get_extraction_stats(pid)
        assert stats["total_jobs"] == 0
        assert stats["total_results"] == 0
        assert stats["pending_review"] == 0
        assert stats["total_cost_usd"] == 0.0

    def test_stats_with_data(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        j1 = db.create_extraction_job(pid, eid)
        db.update_extraction_job(j1, status="completed", cost_usd=0.005)
        j2 = db.create_extraction_job(pid, eid)
        db.update_extraction_job(j2, status="completed", cost_usd=0.003)

        db.create_extraction_result(j1, eid, "description", "Test")
        r2 = db.create_extraction_result(j1, eid, "headquarters", "NYC")
        db.create_extraction_result(j2, eid, "founded_year", "2020")
        db.review_extraction_result(r2, "accept")

        stats = db.get_extraction_stats(pid)
        assert stats["total_jobs"] == 2
        assert stats["total_results"] == 3
        assert stats["pending_review"] == 2
        assert stats["total_cost_usd"] == 0.008
        assert stats["jobs"]["completed"] == 2
        assert stats["results"]["pending"] == 2
        assert stats["results"]["accepted"] == 1


# ═══════════════════════════════════════════════════════════════
# Contradiction Detection
# ═══════════════════════════════════════════════════════════════

class TestContradictionDetection:
    """EXT-CONTRA: Detecting contradictions across extraction results."""

    def test_no_contradictions(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        db.create_extraction_result(job_id, eid, "description", "Same value")
        db.create_extraction_result(job_id, eid, "description", "Same value")

        contradictions = detect_contradictions(eid, db)
        assert len(contradictions) == 0

    def test_detects_contradictions(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        j1 = db.create_extraction_job(pid, eid)
        j2 = db.create_extraction_job(pid, eid)
        db.create_extraction_result(j1, eid, "headquarters", "San Francisco")
        db.create_extraction_result(j2, eid, "headquarters", "New York")

        contradictions = detect_contradictions(eid, db)
        assert len(contradictions) == 1
        assert contradictions[0]["attr_slug"] == "headquarters"
        assert len(contradictions[0]["values"]) == 2

    def test_no_results(self, extraction_project):
        db = extraction_project["db"]
        eid = extraction_project["entity_id"]
        contradictions = detect_contradictions(eid, db)
        assert contradictions == []

    def test_single_value_no_contradiction(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        job_id = db.create_extraction_job(pid, eid)
        db.create_extraction_result(job_id, eid, "description", "Unique value")

        contradictions = detect_contradictions(eid, db)
        assert len(contradictions) == 0

    def test_case_insensitive_matching(self, extraction_project):
        db = extraction_project["db"]
        pid = extraction_project["project_id"]
        eid = extraction_project["entity_id"]

        j1 = db.create_extraction_job(pid, eid)
        j2 = db.create_extraction_job(pid, eid)
        db.create_extraction_result(j1, eid, "headquarters", "San Francisco")
        db.create_extraction_result(j2, eid, "headquarters", "san francisco")

        # Same value, different case — should NOT be a contradiction
        contradictions = detect_contradictions(eid, db)
        assert len(contradictions) == 0
