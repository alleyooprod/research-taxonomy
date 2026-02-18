"""Shared configuration for the Olly market taxonomy builder."""
import os
import secrets
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PROMPTS_DIR = BASE_DIR / "prompts"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "taxonomy.db"

# Processing
DEFAULT_WORKERS = 5
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
RESEARCH_MODEL = "claude-sonnet-4-5-20250929"

MODEL_CHOICES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
}
SUB_BATCH_SIZE = 5  # Auto-chunk batches larger than this
MAX_RETRIES = 3
RESEARCH_TIMEOUT = 300  # seconds per Claude CLI call (5 min)
RESEARCH_TIMEOUT_RETRIES = 2  # Auto-retry on timeout before giving up
CLASSIFY_TIMEOUT = 60
EVOLVE_TIMEOUT = 90

# Claude CLI
CLAUDE_BIN = "claude"
# Set CLAUDE_SKIP_PERMISSIONS=0 to disable --dangerously-skip-permissions
# (requires interactive permission grants for each Claude tool use)
_skip_permissions = os.environ.get("CLAUDE_SKIP_PERMISSIONS", "1") != "0"
CLAUDE_COMMON_FLAGS = [
    "--output-format", "json",
    *(["--dangerously-skip-permissions"] if _skip_permissions else []),
]

# Session secret generated per app instance (used for write-endpoint auth)
SESSION_SECRET = os.environ.get("APP_SESSION_SECRET", secrets.token_urlsafe(32))

# Taxonomy evolution thresholds
MIN_COMPANIES_FOR_NEW_CATEGORY = 3
MIN_COMPANIES_FOR_SPLIT = 8
MAX_COMPANIES_BEFORE_SPLIT = 20

# Web server
WEB_HOST = "127.0.0.1"
WEB_PORT = 5001

# Initial taxonomy categories (seeded into DB on first run)
# Covers full Olly market: Health, Insurance, HR/Benefits, Wearables, digital + physical
SEED_CATEGORIES = [
    "Diagnostics & Testing",
    "Mental Health",
    "Fitness & Recovery",
    "Nutrition & Gut Health",
    "Preventive Health & Longevity",
    "Digital Therapeutics",
    "Telehealth & Virtual Care",
    "Wearables & Monitoring",
    "Employee Benefits & EAP",
    "Health Insurance",
    "Clinical Infrastructure",
    "Wellness & Lifestyle",
    "HR & People Platforms",
    "Insurance Technology",
    "Physical Health Services",
]
