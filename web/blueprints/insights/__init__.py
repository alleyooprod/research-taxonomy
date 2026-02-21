"""Insights & Hypothesis Tracking API — the "So What?" engine."""
from flask import Blueprint

insights_bp = Blueprint("insights", __name__)

from . import detectors    # noqa: E402, F401
from . import insights     # noqa: E402, F401
from . import hypotheses   # noqa: E402, F401
