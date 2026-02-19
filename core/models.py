"""Pydantic models for all structured LLM outputs.

These models serve dual purposes:
  1. Instructor integration (SDK path) — used as response_model for
     automatic validation and retry on the Anthropic SDK path.
  2. Post-hoc validation — can validate dicts returned by CLI path via
     Model.model_validate(data).

All models are optional-import safe: the app works without pydantic installed,
falling back to the existing dict-based validation in each caller.
"""
from __future__ import annotations

try:
    from pydantic import BaseModel, Field, field_validator, model_validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    # Provide a no-op stub so the module can be imported without pydantic
    class BaseModel:  # type: ignore[no-redef]
        pass

    def Field(*a, **kw):  # type: ignore[no-redef]
        return None

    def field_validator(*a, **kw):  # type: ignore[no-redef]
        def _dec(fn):
            return fn
        return _dec

    def model_validator(*a, **kw):  # type: ignore[no-redef]
        def _dec(fn):
            return fn
        return _dec

from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _clamp_confidence(v: Any) -> Optional[float]:
    """Clamp a confidence value to [0, 1], returning None on bad input."""
    if v is None:
        return None
    try:
        return max(0.0, min(1.0, float(v)))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Pricing sub-models
# ---------------------------------------------------------------------------

class PricingTier(BaseModel):
    """A single visible pricing tier."""
    name: str
    price: float = Field(description="Monthly USD price")
    features: Optional[List[str]] = None


class PricingResearch(BaseModel):
    """Pricing-only research output (9 pricing columns)."""
    pricing_model: Optional[Literal[
        "freemium", "subscription", "usage_based", "per_seat",
        "tiered", "custom", "one_time", "marketplace",
    ]] = None
    pricing_b2c_low: Optional[float] = Field(None, description="Monthly USD low end for B2C")
    pricing_b2c_high: Optional[float] = Field(None, description="Monthly USD high end for B2C")
    pricing_b2b_low: Optional[float] = Field(None, description="Monthly per-seat USD low end for B2B")
    pricing_b2b_high: Optional[float] = Field(None, description="Monthly per-seat USD high end for B2B")
    has_free_tier: Optional[bool] = None
    revenue_model: Optional[Literal[
        "SaaS", "hardware", "services", "hybrid",
        "marketplace_commission", "advertising",
    ]] = None
    pricing_tiers: Optional[List[PricingTier]] = None
    pricing_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Company Research (full 35+ fields)
# ---------------------------------------------------------------------------

class CompanyResearch(BaseModel):
    """Full company research output — maps to the company_research.json schema
    and the 35 params accepted by upsert_company()."""

    # Core required fields
    name: str = Field(description="Exact company name")
    url: str = Field(description="Primary website URL")
    what: Optional[str] = Field(None, description="50-100 word value proposition")
    target: Optional[str] = Field(None, description="30-50 word target market")
    products: Optional[str] = Field(None, description="50-80 word product summary")
    funding: Optional[str] = Field(None, description="20-40 word funding info")
    geography: Optional[str] = Field(None, description="15-30 word geography")
    tam: Optional[str] = Field(None, description="40-60 word TAM estimate")

    # Firmographic fields
    employee_range: Optional[str] = Field(
        None,
        description="Estimated employee count range, e.g. '11-50', '51-200'",
    )
    founded_year: Optional[int] = None
    funding_stage: Optional[str] = Field(
        None,
        description="e.g. 'Seed', 'Series A', 'Series B', 'Series C+', 'Public', 'Bootstrapped'",
    )
    total_funding_usd: Optional[float] = Field(None, description="Total funding in USD")
    hq_city: Optional[str] = None
    hq_country: Optional[str] = None
    linkedin_url: Optional[str] = None

    # Pricing fields (embedded)
    pricing_model: Optional[Literal[
        "freemium", "subscription", "usage_based", "per_seat",
        "tiered", "custom", "one_time", "marketplace",
    ]] = None
    pricing_b2c_low: Optional[float] = None
    pricing_b2c_high: Optional[float] = None
    pricing_b2b_low: Optional[float] = None
    pricing_b2b_high: Optional[float] = None
    has_free_tier: Optional[bool] = None
    revenue_model: Optional[Literal[
        "SaaS", "hardware", "services", "hybrid",
        "marketplace_commission", "advertising",
    ]] = None
    pricing_tiers: Optional[List[PricingTier]] = None
    pricing_notes: Optional[str] = None

    # Tags and confidence
    tags: Optional[List[Literal[
        "competitor", "potential_partner", "adjacent_model",
        "infrastructure", "inspiration", "out_of_scope",
    ]]] = Field(default_factory=list)
    confidence: Optional[float] = Field(None, ge=0, le=1)

    if PYDANTIC_AVAILABLE:
        @field_validator("confidence", mode="before")
        @classmethod
        def clamp_confidence(cls, v):
            return _clamp_confidence(v)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class ClassificationResult(BaseModel):
    """Output of classify_company() — maps to company_classification.json."""
    skip: bool = False
    skip_reason: Optional[str] = None
    category: str = Field(description="Best matching category name from the taxonomy")
    is_new_category: bool = False
    subcategory: Optional[str] = Field(None, description="Specific subcategory name")
    classification_reasoning: Optional[str] = Field(
        None, description="Brief explanation of why this category was chosen",
    )
    confidence: Optional[float] = Field(None, ge=0, le=1)

    if PYDANTIC_AVAILABLE:
        @field_validator("confidence", mode="before")
        @classmethod
        def clamp_confidence(cls, v):
            return _clamp_confidence(v)


# ---------------------------------------------------------------------------
# Taxonomy Evolution / Review
# ---------------------------------------------------------------------------

class TaxonomyChange(BaseModel):
    """A single proposed taxonomy change."""
    type: Literal["add", "merge", "split", "rename", "add_subcategory", "move"]
    reason: str = ""
    category_name: Optional[str] = Field(None, description="The category being changed or created")
    new_name: Optional[str] = Field(None, description="New name (for rename)")
    parent_category: Optional[str] = Field(None, description="Parent category (for add_subcategory)")
    merge_into: Optional[str] = Field(None, description="Target category (for merge)")
    split_into: Optional[List[str]] = Field(None, description="New categories (for split)")


class TaxonomyEvolution(BaseModel):
    """Output of evolve_taxonomy() and review_taxonomy() — maps to taxonomy_evolution.json."""
    analysis: str = Field(description="Overall assessment of the taxonomy state")
    changes: List[TaxonomyChange] = Field(default_factory=list)
    no_changes_needed: bool = False


# Alias for review_taxonomy which returns the same schema
TaxonomyReview = TaxonomyEvolution


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

class EnrichmentResult(BaseModel):
    """Output of run_enrichment() — arbitrary subset of company fields."""
    what: Optional[str] = None
    target: Optional[str] = None
    products: Optional[str] = None
    funding: Optional[str] = None
    geography: Optional[str] = None
    tam: Optional[str] = None
    employee_range: Optional[str] = None
    founded_year: Optional[int] = None
    funding_stage: Optional[str] = None
    total_funding_usd: Optional[float] = None
    hq_city: Optional[str] = None
    hq_country: Optional[str] = None
    linkedin_url: Optional[str] = None
    business_model: Optional[str] = None
    company_stage: Optional[str] = None
    primary_focus: Optional[str] = None
    tags: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Dimension Values
# ---------------------------------------------------------------------------

class DimensionValue(BaseModel):
    """A single dimension value for a company."""
    value: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0, le=1)

    if PYDANTIC_AVAILABLE:
        @field_validator("confidence", mode="before")
        @classmethod
        def clamp_confidence(cls, v):
            return _clamp_confidence(v)


class DimensionValues(BaseModel):
    """Batch dimension values: maps dimension_name -> value."""
    values: Dict[str, Optional[str]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class DiscoveredCompany(BaseModel):
    """A single company from a discover/find-similar call."""
    name: str
    url: str
    description: Optional[str] = None
    similarity: Optional[str] = None


class DiscoverResult(BaseModel):
    """Output of the discover endpoint."""
    companies: List[DiscoveredCompany] = Field(default_factory=list)


class FeatureLandscapeResult(BaseModel):
    """Output of feature landscape analysis."""
    markdown: Optional[str] = None
    features: Optional[List[Dict[str, Any]]] = None
    matrix: Optional[Dict[str, Any]] = None
    insights: Optional[List[str]] = None


class GapAnalysisResult(BaseModel):
    """Output of gap analysis."""
    markdown: Optional[str] = None
    gaps: Optional[List[Dict[str, Any]]] = None
    recommendations: Optional[List[str]] = None
    coverage_score: Optional[float] = None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatResponse(BaseModel):
    """AI chat reply."""
    answer: str = Field(description="The chat response text")


# ---------------------------------------------------------------------------
# Market Report
# ---------------------------------------------------------------------------

class MarketReport(BaseModel):
    """Market intelligence briefing output."""
    report: str = Field(description="Full markdown report content")
    category: Optional[str] = None
    company_count: Optional[int] = None


# ---------------------------------------------------------------------------
# Convenience: model registry for programmatic access
# ---------------------------------------------------------------------------

MODEL_REGISTRY = {
    "company_research": CompanyResearch,
    "classification": ClassificationResult,
    "taxonomy_evolution": TaxonomyEvolution,
    "taxonomy_review": TaxonomyReview,
    "pricing_research": PricingResearch,
    "enrichment": EnrichmentResult,
    "dimension_value": DimensionValue,
    "dimension_values": DimensionValues,
    "discover": DiscoverResult,
    "feature_landscape": FeatureLandscapeResult,
    "gap_analysis": GapAnalysisResult,
    "chat": ChatResponse,
    "market_report": MarketReport,
}
