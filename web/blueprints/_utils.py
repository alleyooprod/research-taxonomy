"""Shared utility functions used across multiple blueprint modules."""

import ipaddress
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import jsonify, request


def require_project_id():
    """Extract and validate project_id from query string.

    Returns (project_id, None) on success or (None, error_response) on failure.
    """
    pid = request.args.get("project_id", type=int)
    if not pid:
        return None, (jsonify({"error": "project_id is required"}), 400)
    return pid, None


def now_iso():
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_json_field(raw, default=None):
    """Safely parse a JSON text field from a DB row."""
    if default is None:
        default = {}
    if not raw:
        return default
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return default


def is_safe_url(url: str) -> bool:
    """Reject URLs targeting private/internal networks (SSRF protection)."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname in ("localhost", "0.0.0.0"):
            return False
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            pass  # Not an IP, it's a hostname — allow
        return True
    except Exception:
        return False
