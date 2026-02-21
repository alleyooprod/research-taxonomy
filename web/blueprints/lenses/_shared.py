"""Shared constants and helpers for the Analysis Lenses package."""

import json
from datetime import datetime, timedelta

from flask import request, jsonify, current_app
from loguru import logger

from .._utils import require_project_id as _require_project_id

_PRICING_SLUGS = {"price", "plan", "tier", "cost", "pricing", "subscription", "fee"}
_LOCATION_SLUGS = {"hq_city", "hq_country", "geography", "location", "city", "country", "address"}
_DESIGN_SLUGS = {"design", "pattern", "ui", "ux", "layout", "navigation", "color",
                 "typography", "interaction", "font", "theme", "style", "component",
                 "icon", "animation", "responsive"}

_PATTERN_CATEGORIES = [
    "layout", "navigation", "form", "data_display",
    "interaction", "typography", "color", "animation",
]

_UI_PATTERN_TO_CATEGORY = {
    "form": "form",
    "table": "data_display",
    "chart": "data_display",
    "map": "data_display",
    "modal": "interaction",
    "navigation": "navigation",
    "card-grid": "layout",
    "list": "layout",
    "hero": "layout",
    "empty-state": "interaction",
    "wizard": "interaction",
    "timeline": "data_display",
}

_STAGE_ORDER = {
    "landing": 0,
    "onboarding": 1,
    "login": 2,
    "dashboard": 3,
    "listing": 4,
    "detail": 5,
    "search": 6,
    "settings": 7,
    "checkout": 8,
    "pricing": 9,
    "profile": 10,
    "notification": 11,
    "help": 12,
    "error": 13,
    "empty": 14,
    "other": 99,
}

_FINANCIAL_SLUGS = {
    "annual_revenue", "revenue", "market_cap", "employee_count",
    "employees", "sec_cik", "company_number", "domain_rank",
    "hn_mention_count", "patent_count", "recent_news_count",
}


def _has_pricing_attr(attr_slug):
    """Return True if attr_slug contains any pricing-related keyword."""
    slug_lower = attr_slug.lower()
    return any(kw in slug_lower for kw in _PRICING_SLUGS)


def _has_design_attr(attr_slug):
    """Return True if attr_slug contains any design-related keyword."""
    slug_lower = attr_slug.lower()
    return any(kw in slug_lower for kw in _DESIGN_SLUGS)
