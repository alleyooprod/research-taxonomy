"""Reports & Synthesis API — structured and AI-enhanced report generation.

Provides endpoints for:
- Report template availability detection
- Structured report generation from project data
- AI-enhanced narrative report generation via LLM
- Report CRUD (list, get, update, delete)
- Report export (HTML, JSON, Markdown, PDF)
"""
from flask import Blueprint

reports_bp = Blueprint("reports", __name__)

from . import templates   # noqa: E402, F401
from . import generation  # noqa: E402, F401
from . import crud        # noqa: E402, F401
from . import export      # noqa: E402, F401
