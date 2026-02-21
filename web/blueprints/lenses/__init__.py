"""Analysis Lenses API — data aggregation for the Research Workbench lens system.

Provides endpoints for:
- Lens availability detection (which lenses are populated for a project)
- Competitive Lens: feature matrix, gap analysis, positioning scatter
- Product Lens: pricing landscape aggregation
- Design Lens: screenshot gallery and journey-stage grouping
- Temporal Lens: attribute change timeline and snapshot comparison
- Signals Lens: event timeline, activity summary, trends, and heatmap
"""
from flask import Blueprint

lenses_bp = Blueprint("lenses", __name__)

# Import route modules (must be after lenses_bp creation to avoid circular imports)
from . import availability  # noqa: E402, F401
from . import competitive   # noqa: E402, F401
from . import product       # noqa: E402, F401
from . import design        # noqa: E402, F401
from . import temporal      # noqa: E402, F401
from . import signals       # noqa: E402, F401
