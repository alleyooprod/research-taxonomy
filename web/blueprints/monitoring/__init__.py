"""Monitoring & Intelligence API — automated change detection for entities."""
from flask import Blueprint

monitoring_bp = Blueprint("monitoring", __name__)

from . import monitors    # noqa: E402, F401
from . import checks      # noqa: E402, F401
from . import feed        # noqa: E402, F401
from . import dashboard   # noqa: E402, F401
