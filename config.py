"""Shared configuration for the Olly market taxonomy builder."""
import json
import os
import secrets
import sys
from pathlib import Path

import keyring

# App version (checked by auto-update)
APP_VERSION = "1.1.0"
BUILD_DATE = "2026-02-19"

# Paths
BASE_DIR = Path(__file__).parent

# Data directory: use ~/Library/Application Support for bundled .app, else project-relative
_is_bundled = getattr(sys, "frozen", False)
if _is_bundled:
    _app_support = Path.home() / "Library" / "Application Support" / "Research Taxonomy Library"
    DATA_DIR = _app_support
else:
    DATA_DIR = BASE_DIR / "data"

# Ensure DATA_DIR exists with restricted permissions (owner-only access)
DATA_DIR.mkdir(parents=True, exist_ok=True)
try:
    os.chmod(DATA_DIR, 0o700)
except OSError:
    pass

PROMPTS_DIR = BASE_DIR / "prompts"
LOGS_DIR = DATA_DIR / "logs"
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "taxonomy.db"
APP_SETTINGS_FILE = DATA_DIR / ".app_settings.json"

# Processing
DEFAULT_WORKERS = 5
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
RESEARCH_MODEL = "claude-sonnet-4-5-20250929"

MODEL_CHOICES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
    "gemini-flash": "gemini-2.0-flash",
    "gemini-pro": "gemini-2.5-pro",
}
SUB_BATCH_SIZE = 5  # Auto-chunk batches larger than this
MAX_RETRIES = 3
RESEARCH_TIMEOUT = 600  # seconds per Claude CLI call (10 min)
RESEARCH_TIMEOUT_RETRIES = 2  # Auto-retry on timeout before giving up
CLASSIFY_TIMEOUT = 60
EVOLVE_TIMEOUT = 90

# Claude CLI
CLAUDE_BIN = "claude"
# Set CLAUDE_SKIP_PERMISSIONS=0 to disable --dangerously-skip-permissions
# (requires interactive permission grants for each Claude tool use)
_skip_permissions = os.environ.get("CLAUDE_SKIP_PERMISSIONS", "0") == "1"
CLAUDE_COMMON_FLAGS = [
    "--output-format", "json",
    *(["--dangerously-skip-permissions"] if _skip_permissions else []),
]

# Gemini CLI (via npx; auth: run `npx @google/gemini-cli` interactively once)
GEMINI_BIN = ["npx", "@google/gemini-cli"]
GEMINI_COMMON_FLAGS = [
    "--output-format", "json",
    "-y",  # auto-approve all tool use (yolo mode)
]

# Session secret generated per app instance (used for write-endpoint auth)
SESSION_SECRET = os.environ.get("APP_SESSION_SECRET", secrets.token_urlsafe(32))

# CSRF tokens: per-request tokens signed with SESSION_SECRET
import hmac, hashlib, time as _time

def generate_csrf_token():
    """Generate a per-request CSRF token with timestamp."""
    ts = str(int(_time.time()))
    sig = hmac.new(SESSION_SECRET.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{sig}"

def verify_csrf_token(token, max_age=86400):
    """Verify a CSRF token is valid and not expired (default 24h)."""
    if not token or "." not in token:
        return False
    ts_str, sig = token.rsplit(".", 1)
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if _time.time() - ts > max_age:
        return False
    expected = hmac.new(SESSION_SECRET.encode(), ts_str.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected)

# Rate limiting
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX_REQUESTS = {
    "ai": 10,       # AI endpoints per window
    "default": 120,  # General endpoints per window
    "read": 300,     # Read-only endpoints per window
}

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


# --- App Settings (persisted JSON) ---

_DEFAULT_APP_SETTINGS = {
    "llm_backend": "cli",        # "cli" or "sdk"
    "anthropic_api_key": "",
    "default_model": "claude-haiku-4-5-20251001",
    "research_model": "claude-sonnet-4-5-20250929",
    "git_sync_enabled": True,
    "git_remote_url": "",
    "auto_backup_enabled": True,
    "update_check_enabled": True,
    "last_update_check": None,
}


def load_app_settings():
    """Load app settings from JSON file, merging with defaults."""
    settings = _DEFAULT_APP_SETTINGS.copy()
    try:
        if APP_SETTINGS_FILE.exists():
            saved = json.loads(APP_SETTINGS_FILE.read_text())
            settings.update(saved)
    except Exception:
        pass
    return settings


def save_app_settings(settings):
    """Save app settings to JSON file."""
    APP_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    APP_SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


def get_api_key():
    """Get API key from Keychain, falling back to settings file."""
    key = keyring.get_password("Research Taxonomy Library", "anthropic_api_key")
    if not key:
        key = load_app_settings().get("anthropic_api_key", "")
        if key:
            # Migrate plaintext key to Keychain
            try:
                save_api_key(key)
            except Exception:
                pass
    return key


def save_api_key(key):
    """Save API key to Keychain."""
    keyring.set_password("Research Taxonomy Library", "anthropic_api_key", key)
    # Also update settings for backward compat
    settings = load_app_settings()
    settings["anthropic_api_key"] = ""  # Clear plaintext
    save_app_settings(settings)


def check_prerequisites():
    """Check system prerequisites and return status dict."""
    import shutil
    import subprocess

    results = {}

    # Claude CLI
    claude_path = shutil.which("claude")
    results["claude_cli"] = {
        "installed": claude_path is not None,
        "path": claude_path or "",
    }

    # Git
    git_path = shutil.which("git")
    git_remote = ""
    if git_path:
        try:
            r = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=BASE_DIR, capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                git_remote = r.stdout.strip()
        except Exception:
            pass
    results["git"] = {
        "installed": git_path is not None,
        "path": git_path or "",
        "remote_url": git_remote,
    }

    # Anthropic API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "") or get_api_key()
    results["anthropic_api_key"] = {
        "configured": bool(api_key),
    }

    # Node.js (for Gemini CLI)
    node_path = shutil.which("node")
    results["node"] = {
        "installed": node_path is not None,
        "path": node_path or "",
    }

    # Data directory
    results["data_dir"] = {
        "path": str(DATA_DIR),
        "exists": DATA_DIR.exists(),
        "is_bundled": _is_bundled,
    }

    results["app_version"] = APP_VERSION

    return results
