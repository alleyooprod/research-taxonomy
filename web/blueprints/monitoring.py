"""Monitoring & Intelligence API — automated change detection for entities.

Provides endpoints for:
- Monitor CRUD: create, list, update, delete monitors on entity URLs
- Check execution: trigger individual or batch monitor checks
- Change detection: content hashing, diff generation, severity scoring
- Change feed: unified feed of detected changes across all monitors
- Feed management: mark read, dismiss, bulk operations
- Dashboard stats: monitor health, change frequency, unread counts
- Auto-setup: scan entity attributes for URLs and create monitors automatically
"""
import hashlib
import json
import re
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, current_app
from loguru import logger

monitoring_bp = Blueprint("monitoring", __name__)

# ── Constants ────────────────────────────────────────────────

_VALID_MONITOR_TYPES = {"website", "appstore", "playstore", "rss"}

_URL_ATTR_SLUGS = {
    "website", "url", "homepage", "website_url", "home_url",
    "landing_page", "store_url", "app_url", "product_url",
    "pricing_url", "blog_url", "docs_url",
}

_USER_AGENT = "ResearchWorkbench/1.0"
_REQUEST_TIMEOUT = 15  # seconds


# ── Lazy Table Creation ──────────────────────────────────────

_MONITORS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS monitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    monitor_type TEXT NOT NULL,
    target_url TEXT NOT NULL,
    check_interval_hours INTEGER DEFAULT 24,
    is_active INTEGER DEFAULT 1,
    last_checked_at TEXT,
    last_change_at TEXT,
    consecutive_errors INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_MONITOR_CHECKS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS monitor_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id INTEGER NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    content_hash TEXT,
    changes_detected INTEGER DEFAULT 0,
    change_summary TEXT,
    change_details TEXT,
    error TEXT,
    checked_at TEXT DEFAULT (datetime('now'))
)
"""

_CHANGE_FEED_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS change_feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    monitor_id INTEGER REFERENCES monitors(id) ON DELETE SET NULL,
    check_id INTEGER REFERENCES monitor_checks(id) ON DELETE SET NULL,
    change_type TEXT NOT NULL,
    severity TEXT DEFAULT 'info',
    title TEXT NOT NULL,
    description TEXT,
    details_json TEXT DEFAULT '{}',
    source_url TEXT,
    is_read INTEGER DEFAULT 0,
    is_dismissed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_TABLE_ENSURED = False


def _ensure_tables(conn):
    """Create monitoring tables if they don't exist yet."""
    global _TABLE_ENSURED
    if not _TABLE_ENSURED:
        conn.execute(_MONITORS_TABLE_SQL)
        conn.execute(_MONITOR_CHECKS_TABLE_SQL)
        conn.execute(_CHANGE_FEED_TABLE_SQL)
        _TABLE_ENSURED = True


# ── Shared Helpers ───────────────────────────────────────────

def _require_project_id():
    """Extract and validate project_id from query string.

    Returns (project_id, None) on success or (None, error_response) on failure.
    """
    pid = request.args.get("project_id", type=int)
    if not pid:
        return None, (jsonify({"error": "project_id is required"}), 400)
    return pid, None


def _now_iso():
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_monitor(row):
    """Convert a DB row to a monitor dict."""
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "entity_id": row["entity_id"],
        "monitor_type": row["monitor_type"],
        "target_url": row["target_url"],
        "check_interval_hours": row["check_interval_hours"],
        "is_active": bool(row["is_active"]),
        "last_checked_at": row["last_checked_at"],
        "last_change_at": row["last_change_at"],
        "consecutive_errors": row["consecutive_errors"],
        "created_at": row["created_at"],
    }


def _row_to_check(row):
    """Convert a DB row to a check result dict."""
    change_details = {}
    if row["change_details"]:
        try:
            change_details = json.loads(row["change_details"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": row["id"],
        "monitor_id": row["monitor_id"],
        "status": row["status"],
        "content_hash": row["content_hash"],
        "changes_detected": bool(row["changes_detected"]),
        "change_summary": row["change_summary"],
        "change_details": change_details,
        "error": row["error"],
        "checked_at": row["checked_at"],
    }


def _row_to_feed_item(row):
    """Convert a DB row to a change feed item dict."""
    details = {}
    if row["details_json"]:
        try:
            details = json.loads(row["details_json"])
        except (json.JSONDecodeError, TypeError):
            pass
    result = {
        "id": row["id"],
        "project_id": row["project_id"],
        "entity_id": row["entity_id"],
        "monitor_id": row["monitor_id"],
        "check_id": row["check_id"],
        "change_type": row["change_type"],
        "severity": row["severity"],
        "title": row["title"],
        "description": row["description"],
        "details": details,
        "source_url": row["source_url"],
        "is_read": bool(row["is_read"]),
        "is_dismissed": bool(row["is_dismissed"]),
        "created_at": row["created_at"],
    }
    # Include entity_name if joined
    if "entity_name" in row.keys():
        result["entity_name"] = row["entity_name"]
    return result


def _validate_url(url):
    """Basic URL validation. Returns (cleaned_url, error_string_or_None)."""
    if not url or not isinstance(url, str):
        return None, "target_url is required"
    url = url.strip()
    if not url:
        return None, "target_url cannot be empty"
    # Allow app store IDs that aren't full URLs for appstore/playstore monitors
    if url.startswith(("http://", "https://")):
        return url, None
    # Could be a package ID or app ID — allow it
    return url, None


def _detect_monitor_type_from_url(url):
    """Heuristic: guess monitor type from URL patterns.

    Returns: monitor_type string or "website" as fallback.
    """
    url_lower = url.lower()
    if "apps.apple.com" in url_lower or "itunes.apple.com" in url_lower:
        return "appstore"
    if "play.google.com" in url_lower:
        return "playstore"
    # Common RSS/feed patterns
    if any(p in url_lower for p in ["/feed", "/rss", ".rss", ".atom", "/atom"]):
        return "rss"
    return "website"


def _score_severity(change_type, change_summary=None, details=None):
    """Determine severity from change_type and optional content analysis.

    Severity levels:
        info     — minor text changes, new blog post
        minor    — screenshot updates, description changes
        major    — pricing changes, new features, version updates
        critical — shutdown, acquisition, major pivot
    """
    severity_map = {
        "new_post": "info",
        "content_change": "minor",
        "screenshot_change": "minor",
        "new_version": "major",
        "price_change": "major",
        "funding": "major",
        "shutdown": "critical",
    }
    severity = severity_map.get(change_type, "info")

    # Upgrade severity based on content analysis if summary is provided
    if change_summary and severity == "minor":
        summary_lower = change_summary.lower()
        # Check for keywords that suggest higher severity
        major_keywords = [
            "pricing", "price", "plan", "tier", "cost",
            "version", "release", "update", "feature",
            "acquisition", "acquired", "merger",
        ]
        critical_keywords = [
            "shutdown", "shutting down", "end of life", "deprecated",
            "discontinue", "sunset", "closing",
        ]
        if any(kw in summary_lower for kw in critical_keywords):
            severity = "critical"
        elif any(kw in summary_lower for kw in major_keywords):
            severity = "major"

    return severity


def _trigger_recapture(conn, monitor, severity, feed_id):
    """Schedule a re-capture when a major/critical change is detected.

    Creates a 'recapture_queued' entry in the change feed so the user can see
    the action was triggered, and stores a capture_queue row (if the table
    exists) for the capture engine to pick up.
    """
    entity_id = monitor["entity_id"]
    target_url = monitor["target_url"]
    project_id = monitor["project_id"]

    # Check if capture_queue table exists (optional — only if capture engine installed)
    has_queue = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='capture_queue'"
    ).fetchone()

    if has_queue:
        # Avoid duplicate queue entries for the same URL + entity
        existing = conn.execute(
            """SELECT id FROM capture_queue
               WHERE entity_id = ? AND target_url = ? AND status = 'pending'""",
            (entity_id, target_url),
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO capture_queue
                   (project_id, entity_id, target_url, trigger_type, trigger_id, status, created_at)
                   VALUES (?, ?, ?, 'monitor_change', ?, 'pending', datetime('now'))""",
                (project_id, entity_id, target_url, feed_id),
            )

    # Log a feed entry noting the recapture was triggered
    conn.execute(
        """INSERT INTO change_feed
           (project_id, entity_id, monitor_id, change_type, severity,
            title, description, source_url, created_at)
           VALUES (?, ?, ?, 'recapture_queued', 'info', ?, ?, ?, datetime('now'))""",
        (
            project_id,
            entity_id,
            monitor["id"],
            f"Re-capture queued after {severity} change",
            f"Automatically triggered by {severity} change detection on {target_url}",
            target_url,
        ),
    )

    logger.info(
        "Re-capture triggered for entity %d, URL %s (severity=%s, feed=%d)",
        entity_id, target_url, severity, feed_id,
    )


# ── Check Logic ──────────────────────────────────────────────

def _check_error(msg):
    """Return a standardised error result dict."""
    return {
        "status": "error", "content_hash": None, "changes_detected": False,
        "change_summary": None, "change_details": None, "error": msg[:500],
    }


def _get_prev_check(conn, monitor_id):
    """Get the most recent successful check for a monitor."""
    return conn.execute(
        """SELECT content_hash, change_details FROM monitor_checks
           WHERE monitor_id = ? AND status = 'completed'
           ORDER BY checked_at DESC LIMIT 1""",
        (monitor_id,),
    ).fetchone()


def _hash_fingerprint(data):
    """SHA-256 hash of a JSON-serialisable fingerprint dict."""
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _md5_text(text):
    """MD5 hash of a text string (for sub-field comparison, not security)."""
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()


def _diff_app_fingerprint(old_details, new_fp, app_name, extra_fields=None):
    """Compare two app fingerprint dicts and return (diffs, change_type).

    Checks version, price, description_hash, screenshot_count, release_notes_hash,
    and any extra_fields provided.
    """
    diffs = []
    change_type = "content_change"

    if old_details.get("version") != new_fp.get("version"):
        diffs.append(f"Version: {old_details.get('version', '?')} -> {new_fp.get('version', '?')}")
        change_type = "new_version"

    old_price, new_price = old_details.get("price"), new_fp.get("price")
    if old_price is not None and str(old_price) != str(new_price):
        diffs.append(f"Price: {old_price} -> {new_price}")
        change_type = "price_change"

    if old_details.get("description_hash") != new_fp.get("description_hash"):
        diffs.append("Description updated")

    if old_details.get("screenshot_count") != new_fp.get("screenshot_count"):
        diffs.append(f"Screenshots: {old_details.get('screenshot_count', '?')} -> {new_fp.get('screenshot_count', '?')}")
        if change_type == "content_change":
            change_type = "screenshot_change"

    if old_details.get("release_notes_hash") != new_fp.get("release_notes_hash"):
        diffs.append("Release notes updated")

    for field in (extra_fields or []):
        if old_details.get(field) != new_fp.get(field):
            diffs.append(f"{field.title()}: {old_details.get(field, '?')} -> {new_fp.get(field, '?')}")

    summary = f"{app_name}: " + "; ".join(diffs) if diffs else None
    return summary, change_type


def _check_website(monitor, conn):
    """Fetch URL, compute content hash, compare with previous check."""
    import requests as req_lib

    target_url = monitor["target_url"]
    try:
        resp = req_lib.get(target_url, timeout=_REQUEST_TIMEOUT,
                           headers={"User-Agent": _USER_AGENT}, allow_redirects=True)
        resp.raise_for_status()
        content = resp.text
    except Exception as e:
        return _check_error(str(e))

    content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    prev = _get_prev_check(conn, monitor["id"])
    changes_detected = prev is not None and prev["content_hash"] != content_hash

    change_summary = None
    change_details = None
    if changes_detected:
        change_summary = f"Content changed at {target_url}"
        change_details = json.dumps({
            "previous_hash": prev["content_hash"],
            "new_hash": content_hash,
            "content_length": len(content),
        })

    return {
        "status": "completed", "content_hash": content_hash,
        "changes_detected": changes_detected, "change_summary": change_summary,
        "change_details": change_details, "error": None,
    }


def _check_appstore(monitor, conn):
    """Check App Store listing for changes via iTunes API."""
    from core.scrapers.appstore import get_app_details

    app_id = _extract_appstore_id(monitor["target_url"])
    if not app_id:
        return _check_error(f"Could not extract App Store ID from: {monitor['target_url']}")

    try:
        app = get_app_details(app_id)
    except Exception as e:
        return _check_error(f"App Store lookup failed: {e}")
    if not app:
        return _check_error(f"App not found in App Store (ID: {app_id})")

    d = app.to_dict()
    fp = {
        "name": d.get("name", ""), "version": d.get("version", ""),
        "price": d.get("price", 0), "rating": d.get("rating", 0),
        "rating_count": d.get("rating_count", 0),
        "description_hash": _md5_text(d.get("description", "")),
        "screenshot_count": len(d.get("screenshot_urls", [])),
        "release_notes_hash": _md5_text(d.get("release_notes", "")),
    }
    return _check_app_listing(monitor, conn, d.get("name", "app"), fp, "App Store")


def _check_playstore(monitor, conn):
    """Check Play Store listing for changes via web scraping."""
    from core.scrapers.playstore import get_app_details

    package_id = _extract_playstore_id(monitor["target_url"])
    if not package_id:
        return _check_error(f"Could not extract Play Store package ID from: {monitor['target_url']}")

    try:
        app = get_app_details(package_id)
    except Exception as e:
        return _check_error(f"Play Store lookup failed: {e}")
    if not app:
        return _check_error(f"App not found in Play Store (package: {package_id})")

    d = app.to_dict()
    fp = {
        "name": d.get("name", ""), "version": d.get("version", ""),
        "price": d.get("price", "Free"), "rating": d.get("rating", 0),
        "rating_count": d.get("rating_count", 0),
        "installs": d.get("installs", ""),
        "description_hash": _md5_text(d.get("description", "")),
        "screenshot_count": len(d.get("screenshot_urls", [])),
    }
    return _check_app_listing(monitor, conn, d.get("name", "app"), fp, "Play Store",
                              extra_fields=["installs"])


def _check_app_listing(monitor, conn, app_name, fingerprint, store_label, extra_fields=None):
    """Shared logic for App Store and Play Store checks."""
    content_hash = _hash_fingerprint(fingerprint)
    prev = _get_prev_check(conn, monitor["id"])
    changes_detected = prev is not None and prev["content_hash"] != content_hash

    change_summary = None
    change_type = "content_change"

    if changes_detected and prev and prev["change_details"]:
        try:
            old_details = json.loads(prev["change_details"])
        except (json.JSONDecodeError, TypeError):
            old_details = {}
        change_summary, change_type = _diff_app_fingerprint(
            old_details, fingerprint, app_name, extra_fields)
    elif changes_detected:
        change_summary = f"{store_label} listing changed for {app_name}"

    result = {
        "status": "completed", "content_hash": content_hash,
        "changes_detected": changes_detected, "change_summary": change_summary,
        "change_details": json.dumps(fingerprint), "error": None,
    }
    if changes_detected:
        result["_change_type"] = change_type
    return result


def _check_rss(monitor, conn):
    """Parse RSS/Atom feed and detect new entries since last check."""
    import requests as req_lib
    import xml.etree.ElementTree as ET

    target_url = monitor["target_url"]
    try:
        resp = req_lib.get(target_url, timeout=_REQUEST_TIMEOUT,
                           headers={"User-Agent": _USER_AGENT}, allow_redirects=True)
        resp.raise_for_status()
        content = resp.text
    except Exception as e:
        return _check_error(f"RSS fetch failed: {e}")

    # Parse feed entries
    entries = []
    try:
        root = ET.fromstring(content)
        # Handle RSS 2.0
        for item in root.iter("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pub_date_el = item.find("pubDate")
            guid_el = item.find("guid")
            entries.append({
                "title": title_el.text if title_el is not None else "",
                "link": link_el.text if link_el is not None else "",
                "pub_date": pub_date_el.text if pub_date_el is not None else "",
                "guid": guid_el.text if guid_el is not None else "",
            })
        # Handle Atom feeds if no RSS items found
        if not entries:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                updated_el = entry.find("atom:updated", ns)
                id_el = entry.find("atom:id", ns)
                link_href = ""
                if link_el is not None:
                    link_href = link_el.get("href", "")
                entries.append({
                    "title": title_el.text if title_el is not None else "",
                    "link": link_href,
                    "pub_date": updated_el.text if updated_el is not None else "",
                    "guid": id_el.text if id_el is not None else "",
                })
    except ET.ParseError as e:
        return _check_error(f"RSS parse failed: {e}")

    # Build a hash from the entry GUIDs/links to detect new entries
    entry_ids = []
    for entry in entries:
        eid = entry.get("guid") or entry.get("link") or entry.get("title", "")
        if eid:
            entry_ids.append(eid)

    content_hash = _hash_fingerprint(entry_ids[:50])
    prev = _get_prev_check(conn, monitor["id"])

    changes_detected = prev is not None and prev["content_hash"] != content_hash

    change_summary = None
    change_details_str = json.dumps({
        "entry_count": len(entries),
        "latest_entries": entries[:5],
    })

    if changes_detected and prev and prev["change_details"]:
        try:
            old_details = json.loads(prev["change_details"])
            old_entries = {
                e.get("guid") or e.get("link") or e.get("title", "")
                for e in old_details.get("latest_entries", [])
            }
        except (json.JSONDecodeError, TypeError):
            old_entries = set()

        new_entries = [
            e for e in entries
            if (e.get("guid") or e.get("link") or e.get("title", "")) not in old_entries
        ]
        if new_entries:
            titles = [e.get("title", "Untitled") for e in new_entries[:3]]
            change_summary = f"{len(new_entries)} new post(s): " + "; ".join(titles)
            change_details_str = json.dumps({
                "entry_count": len(entries),
                "new_entries": new_entries[:10],
                "latest_entries": entries[:5],
            })
        else:
            change_summary = "Feed content changed"
    elif changes_detected:
        change_summary = f"Feed updated with {len(entries)} entries"

    result = {
        "status": "completed",
        "content_hash": content_hash,
        "changes_detected": changes_detected,
        "change_summary": change_summary,
        "change_details": change_details_str,
        "error": None,
    }
    if changes_detected:
        result["_change_type"] = "new_post"
    return result


# Dispatcher for check functions by monitor type
_CHECK_HANDLERS = {
    "website": _check_website,
    "appstore": _check_appstore,
    "playstore": _check_playstore,
    "rss": _check_rss,
}


def _extract_appstore_id(target):
    """Extract numeric App Store ID from URL or raw ID string.

    Handles:
        - "123456789" (raw numeric ID)
        - "https://apps.apple.com/gb/app/vitality/id123456789"
        - "https://itunes.apple.com/lookup?id=123456789"

    Returns: int or None
    """
    if not target:
        return None

    # Try raw numeric
    target_stripped = target.strip()
    if target_stripped.isdigit():
        return int(target_stripped)

    # Try URL pattern: /id<digits>
    match = re.search(r'/id(\d+)', target)
    if match:
        return int(match.group(1))

    # Try query param pattern: id=<digits>
    match = re.search(r'[?&]id=(\d+)', target)
    if match:
        return int(match.group(1))

    return None


def _extract_playstore_id(target):
    """Extract Play Store package ID from URL or raw ID string.

    Handles:
        - "com.example.app" (raw package ID)
        - "https://play.google.com/store/apps/details?id=com.example.app"

    Returns: str or None
    """
    if not target:
        return None

    target_stripped = target.strip()

    # Try query param pattern: id=<package>
    match = re.search(r'[?&]id=([a-zA-Z0-9_.]+)', target)
    if match:
        return match.group(1)

    # Try raw package ID pattern (com.something.app)
    if re.match(r'^[a-zA-Z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)+$', target_stripped):
        return target_stripped

    return None


def _execute_check(monitor, conn):
    """Execute a single monitor check and persist results.

    Dispatches to the appropriate check handler based on monitor_type,
    creates the monitor_checks row, optionally creates a change_feed entry,
    and updates the monitor's last_checked_at / consecutive_errors.

    Args:
        monitor: dict with monitor row data
        conn: active database connection

    Returns:
        dict with the check result including check_id and feed_id (if created)
    """
    monitor_type = monitor["monitor_type"]
    handler = _CHECK_HANDLERS.get(monitor_type)

    if not handler:
        result = {
            "status": "error",
            "content_hash": None,
            "changes_detected": False,
            "change_summary": None,
            "change_details": None,
            "error": f"Unknown monitor type: {monitor_type}",
        }
    else:
        try:
            result = handler(monitor, conn)
        except Exception as e:
            logger.exception("Monitor check failed for monitor %d", monitor["id"])
            result = {
                "status": "error",
                "content_hash": None,
                "changes_detected": False,
                "change_summary": None,
                "change_details": None,
                "error": f"Check handler exception: {str(e)[:300]}",
            }

    now = _now_iso()

    # Insert check record
    cursor = conn.execute(
        """INSERT INTO monitor_checks
           (monitor_id, status, content_hash, changes_detected,
            change_summary, change_details, error, checked_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            monitor["id"],
            result["status"],
            result.get("content_hash"),
            1 if result.get("changes_detected") else 0,
            result.get("change_summary"),
            result.get("change_details"),
            result.get("error"),
            now,
        ),
    )
    check_id = cursor.lastrowid

    # Update monitor status
    if result["status"] == "error":
        conn.execute(
            """UPDATE monitors
               SET last_checked_at = ?,
                   consecutive_errors = consecutive_errors + 1
               WHERE id = ?""",
            (now, monitor["id"]),
        )
    else:
        update_fields = "last_checked_at = ?, consecutive_errors = 0"
        update_params = [now]
        if result.get("changes_detected"):
            update_fields += ", last_change_at = ?"
            update_params.append(now)
        update_params.append(monitor["id"])
        conn.execute(
            f"UPDATE monitors SET {update_fields} WHERE id = ?",
            update_params,
        )

    # Create change feed entry if changes detected
    feed_id = None
    if result.get("changes_detected"):
        change_type = result.get("_change_type", "content_change")
        severity = _score_severity(change_type, result.get("change_summary"))

        title = result.get("change_summary") or f"Change detected for {monitor['target_url']}"
        # Truncate title if too long
        if len(title) > 200:
            title = title[:197] + "..."

        cursor = conn.execute(
            """INSERT INTO change_feed
               (project_id, entity_id, monitor_id, check_id,
                change_type, severity, title, description,
                details_json, source_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                monitor["project_id"],
                monitor["entity_id"],
                monitor["id"],
                check_id,
                change_type,
                severity,
                title,
                result.get("change_summary"),
                result.get("change_details") or "{}",
                monitor["target_url"],
                now,
            ),
        )
        feed_id = cursor.lastrowid

        # Auto-trigger re-capture for major/critical changes
        if severity in ("major", "critical"):
            _trigger_recapture(conn, monitor, severity, feed_id)

    # Build response
    check_result = {
        "check_id": check_id,
        "monitor_id": monitor["id"],
        "status": result["status"],
        "content_hash": result.get("content_hash"),
        "changes_detected": bool(result.get("changes_detected")),
        "change_summary": result.get("change_summary"),
        "error": result.get("error"),
        "checked_at": now,
    }
    if feed_id:
        check_result["feed_id"] = feed_id
        check_result["recapture_triggered"] = severity in ("major", "critical")

    return check_result


# ═════════════════════════════════════════════════════════════
# 1. List Monitors
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors")
def list_monitors():
    """List all monitors for a project.

    Query params:
        project_id (required): Project ID
        entity_id (optional): Filter by entity
        monitor_type (optional): Filter by type (website|appstore|playstore|rss)
        is_active (optional): Filter by active status (1 or 0)

    Returns:
        List of monitor dicts with entity_name and last check info.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_id = request.args.get("entity_id", type=int)
    monitor_type = request.args.get("monitor_type")
    is_active = request.args.get("is_active", type=int)

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = """
            SELECT m.*, e.name as entity_name
            FROM monitors m
            JOIN entities e ON e.id = m.entity_id
            WHERE m.project_id = ?
        """
        params = [project_id]

        if entity_id is not None:
            query += " AND m.entity_id = ?"
            params.append(entity_id)
        if monitor_type:
            query += " AND m.monitor_type = ?"
            params.append(monitor_type)
        if is_active is not None:
            query += " AND m.is_active = ?"
            params.append(is_active)

        query += " ORDER BY m.created_at DESC"

        rows = conn.execute(query, params).fetchall()

    result = []
    for row in rows:
        monitor = _row_to_monitor(row)
        monitor["entity_name"] = row["entity_name"]
        result.append(monitor)

    return jsonify(result)


# ═════════════════════════════════════════════════════════════
# 2. Create Monitor
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors", methods=["POST"])
def create_monitor():
    """Create a new monitor for an entity.

    Request JSON:
        project_id (required): Project ID
        entity_id (required): Entity to monitor
        monitor_type (required): website | appstore | playstore | rss
        target_url (required): URL or identifier to monitor
        check_interval_hours (optional): Hours between checks (default: 24)

    Returns:
        Created monitor dict (201)
    """
    data = request.json or {}
    project_id = data.get("project_id")
    entity_id = data.get("entity_id")
    monitor_type = data.get("monitor_type")
    target_url = data.get("target_url", "").strip()
    check_interval = data.get("check_interval_hours", 24)

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    if not entity_id:
        return jsonify({"error": "entity_id is required"}), 400
    if not monitor_type:
        return jsonify({"error": "monitor_type is required"}), 400
    if monitor_type not in _VALID_MONITOR_TYPES:
        return jsonify({
            "error": f"Invalid monitor_type: {monitor_type}. "
                     f"Valid types: {sorted(_VALID_MONITOR_TYPES)}"
        }), 400

    target_url, url_err = _validate_url(target_url)
    if url_err:
        return jsonify({"error": url_err}), 400

    if not isinstance(check_interval, int) or check_interval < 1:
        return jsonify({"error": "check_interval_hours must be a positive integer"}), 400

    db = current_app.db

    # Validate entity exists and belongs to project
    with db._get_conn() as conn:
        _ensure_tables(conn)

        entity = conn.execute(
            "SELECT id, name FROM entities WHERE id = ? AND project_id = ? AND is_deleted = 0",
            (entity_id, project_id),
        ).fetchone()

        if not entity:
            return jsonify({"error": f"Entity {entity_id} not found in project {project_id}"}), 404

        # Check for duplicate monitor (same entity + URL + type)
        existing = conn.execute(
            """SELECT id FROM monitors
               WHERE entity_id = ? AND target_url = ? AND monitor_type = ?""",
            (entity_id, target_url, monitor_type),
        ).fetchone()

        if existing:
            return jsonify({
                "error": "A monitor already exists for this entity, URL, and type",
                "existing_id": existing["id"],
            }), 409

        cursor = conn.execute(
            """INSERT INTO monitors
               (project_id, entity_id, monitor_type, target_url,
                check_interval_hours, is_active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (project_id, entity_id, monitor_type, target_url, check_interval),
        )
        monitor_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

    monitor = _row_to_monitor(row)
    monitor["entity_name"] = entity["name"]

    logger.info(
        "Created %s monitor #%d for entity %d (%s)",
        monitor_type, monitor_id, entity_id, target_url,
    )
    return jsonify(monitor), 201


# ═════════════════════════════════════════════════════════════
# 3. Delete Monitor
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors/<int:monitor_id>", methods=["DELETE"])
def delete_monitor(monitor_id):
    """Delete a monitor and all its associated checks.

    Cascade delete will remove monitor_checks rows.
    Change feed entries will have monitor_id set to NULL (ON DELETE SET NULL).

    Returns:
        {deleted: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Monitor {monitor_id} not found"}), 404

        conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))

    logger.info("Deleted monitor #%d", monitor_id)
    return jsonify({"deleted": True, "id": monitor_id})


# ═════════════════════════════════════════════════════════════
# 4. Update Monitor
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors/<int:monitor_id>", methods=["PUT"])
def update_monitor(monitor_id):
    """Update a monitor's settings.

    Request JSON (all optional):
        is_active: bool — enable or disable the monitor
        check_interval_hours: int — adjust check frequency
        target_url: str — change the monitored URL

    Returns:
        Updated monitor dict
    """
    data = request.json or {}
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Monitor {monitor_id} not found"}), 404

        updates = []
        params = []

        if "is_active" in data:
            updates.append("is_active = ?")
            params.append(1 if data["is_active"] else 0)

        if "check_interval_hours" in data:
            interval = data["check_interval_hours"]
            if not isinstance(interval, int) or interval < 1:
                return jsonify({"error": "check_interval_hours must be a positive integer"}), 400
            updates.append("check_interval_hours = ?")
            params.append(interval)

        if "target_url" in data:
            new_url, url_err = _validate_url(data["target_url"])
            if url_err:
                return jsonify({"error": url_err}), 400
            updates.append("target_url = ?")
            params.append(new_url)

        if not updates:
            return jsonify({"error": "No valid fields to update"}), 400

        params.append(monitor_id)
        conn.execute(
            f"UPDATE monitors SET {', '.join(updates)} WHERE id = ?",
            params,
        )

        updated_row = conn.execute(
            """SELECT m.*, e.name as entity_name
               FROM monitors m
               JOIN entities e ON e.id = m.entity_id
               WHERE m.id = ?""",
            (monitor_id,),
        ).fetchone()

    monitor = _row_to_monitor(updated_row)
    monitor["entity_name"] = updated_row["entity_name"]

    logger.info("Updated monitor #%d: %s", monitor_id, ", ".join(updates))
    return jsonify(monitor)


# ═════════════════════════════════════════════════════════════
# 5. Trigger Single Check
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors/<int:monitor_id>/check", methods=["POST"])
def trigger_check(monitor_id):
    """Trigger an immediate check for a single monitor.

    Fetches current content, computes hash, compares with previous check,
    generates change summary, and optionally creates a change feed entry.

    Returns:
        Check result dict with changes if any.
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT * FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Monitor {monitor_id} not found"}), 404

        monitor = dict(row)
        result = _execute_check(monitor, conn)

    status_code = 200 if result["status"] != "error" else 422
    return jsonify(result), status_code


# ═════════════════════════════════════════════════════════════
# 6. Check All Due Monitors
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/check-all", methods=["POST"])
def check_all_monitors():
    """Check all monitors that are due for a check.

    Finds active monitors where last_checked_at is NULL or older than
    check_interval_hours, runs checks sequentially.

    Query params:
        project_id (required): Project ID

    Returns:
        Summary of checks performed and changes found.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Find due monitors: never checked or interval elapsed
        rows = conn.execute(
            """SELECT * FROM monitors
               WHERE project_id = ? AND is_active = 1
               AND (
                   last_checked_at IS NULL
                   OR datetime(last_checked_at, '+' || check_interval_hours || ' hours')
                       <= datetime('now')
               )
               ORDER BY last_checked_at ASC NULLS FIRST""",
            (project_id,),
        ).fetchall()

        total = len(rows)
        checked = 0
        changes_found = 0
        errors = 0
        results = []

        for row in rows:
            monitor = dict(row)
            try:
                check_result = _execute_check(monitor, conn)
                checked += 1
                if check_result.get("changes_detected"):
                    changes_found += 1
                if check_result.get("status") == "error":
                    errors += 1
                results.append({
                    "monitor_id": monitor["id"],
                    "target_url": monitor["target_url"],
                    "status": check_result["status"],
                    "changes_detected": check_result.get("changes_detected", False),
                    "change_summary": check_result.get("change_summary"),
                    "error": check_result.get("error"),
                })
            except Exception as e:
                checked += 1
                errors += 1
                results.append({
                    "monitor_id": monitor["id"],
                    "target_url": monitor["target_url"],
                    "status": "error",
                    "changes_detected": False,
                    "error": str(e)[:300],
                })
                logger.exception(
                    "Check-all failed for monitor %d (%s)",
                    monitor["id"], monitor["target_url"],
                )

    logger.info(
        "Check-all for project %d: %d/%d checked, %d changes, %d errors",
        project_id, checked, total, changes_found, errors,
    )

    return jsonify({
        "project_id": project_id,
        "total_due": total,
        "checked": checked,
        "changes_found": changes_found,
        "errors": errors,
        "results": results,
    })


# ═════════════════════════════════════════════════════════════
# 7. Change Feed
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/feed")
def get_feed():
    """Get the change feed for a project.

    Query params:
        project_id (required): Project ID
        entity_id (optional): Filter by entity
        change_type (optional): Filter by change type
        severity (optional): Filter by severity
        is_read (optional): Filter by read status (0 or 1)
        limit (optional): Max results (default: 50)
        offset (optional): Pagination offset (default: 0)

    Returns:
        List of change feed items, newest first.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    entity_id = request.args.get("entity_id", type=int)
    change_type = request.args.get("change_type")
    severity = request.args.get("severity")
    is_read = request.args.get("is_read", type=int)
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    # Clamp limit
    limit = max(1, min(limit, 200))

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        query = """
            SELECT cf.*, e.name as entity_name
            FROM change_feed cf
            JOIN entities e ON e.id = cf.entity_id
            WHERE cf.project_id = ? AND cf.is_dismissed = 0
        """
        params = [project_id]

        if entity_id is not None:
            query += " AND cf.entity_id = ?"
            params.append(entity_id)
        if change_type:
            query += " AND cf.change_type = ?"
            params.append(change_type)
        if severity:
            query += " AND cf.severity = ?"
            params.append(severity)
        if is_read is not None:
            query += " AND cf.is_read = ?"
            params.append(is_read)

        # Get total count for pagination
        count_query = query.replace(
            "SELECT cf.*, e.name as entity_name",
            "SELECT COUNT(*) as total",
        )
        total = conn.execute(count_query, params).fetchone()["total"]

        query += " ORDER BY cf.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

    items = [_row_to_feed_item(row) for row in rows]

    return jsonify({
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


# ═════════════════════════════════════════════════════════════
# 8. Mark Feed Item as Read
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/feed/<int:feed_id>/read", methods=["PUT"])
def mark_feed_read(feed_id):
    """Mark a single change feed item as read.

    Returns:
        {updated: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM change_feed WHERE id = ?", (feed_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Feed item {feed_id} not found"}), 404

        conn.execute(
            "UPDATE change_feed SET is_read = 1 WHERE id = ?", (feed_id,)
        )

    return jsonify({"updated": True, "id": feed_id})


# ═════════════════════════════════════════════════════════════
# 9. Dismiss Feed Item
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/feed/<int:feed_id>/dismiss", methods=["PUT"])
def dismiss_feed_item(feed_id):
    """Dismiss a change feed item (hides from default feed view).

    Returns:
        {updated: true, id: N}
    """
    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        row = conn.execute(
            "SELECT id FROM change_feed WHERE id = ?", (feed_id,)
        ).fetchone()

        if not row:
            return jsonify({"error": f"Feed item {feed_id} not found"}), 404

        conn.execute(
            "UPDATE change_feed SET is_dismissed = 1 WHERE id = ?", (feed_id,)
        )

    return jsonify({"updated": True, "id": feed_id})


# ═════════════════════════════════════════════════════════════
# 10. Mark All Feed Items as Read
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/feed/mark-all-read", methods=["POST"])
def mark_all_feed_read():
    """Mark all unread change feed items as read for a project.

    Query params:
        project_id (required): Project ID

    Returns:
        {updated: true, count: N}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        cursor = conn.execute(
            "UPDATE change_feed SET is_read = 1 WHERE project_id = ? AND is_read = 0",
            (project_id,),
        )
        count = cursor.rowcount

    logger.info("Marked %d feed items as read for project %d", count, project_id)
    return jsonify({"updated": True, "count": count})


# ═════════════════════════════════════════════════════════════
# 11. Dashboard Stats
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/stats")
def monitoring_stats():
    """Get monitoring dashboard statistics for a project.

    Query params:
        project_id (required): Project ID

    Returns:
        {
            total_monitors, active_monitors, inactive_monitors,
            monitors_with_errors,
            changes_this_week, changes_total,
            unread_count,
            by_type: {website: N, appstore: N, ...},
            by_severity: {info: N, minor: N, ...},
            recent_changes: [{title, severity, created_at, entity_name}, ...]
        }
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Monitor counts
        total_monitors = conn.execute(
            "SELECT COUNT(*) FROM monitors WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]

        active_monitors = conn.execute(
            "SELECT COUNT(*) FROM monitors WHERE project_id = ? AND is_active = 1",
            (project_id,),
        ).fetchone()[0]

        monitors_with_errors = conn.execute(
            "SELECT COUNT(*) FROM monitors WHERE project_id = ? AND consecutive_errors > 0",
            (project_id,),
        ).fetchone()[0]

        # By monitor type
        type_rows = conn.execute(
            """SELECT monitor_type, COUNT(*) as count
               FROM monitors WHERE project_id = ?
               GROUP BY monitor_type""",
            (project_id,),
        ).fetchall()
        by_type = {row["monitor_type"]: row["count"] for row in type_rows}

        # Change feed stats
        changes_total = conn.execute(
            "SELECT COUNT(*) FROM change_feed WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]

        changes_this_week = conn.execute(
            """SELECT COUNT(*) FROM change_feed
               WHERE project_id = ?
               AND created_at >= datetime('now', '-7 days')""",
            (project_id,),
        ).fetchone()[0]

        unread_count = conn.execute(
            """SELECT COUNT(*) FROM change_feed
               WHERE project_id = ? AND is_read = 0 AND is_dismissed = 0""",
            (project_id,),
        ).fetchone()[0]

        # By severity
        severity_rows = conn.execute(
            """SELECT severity, COUNT(*) as count
               FROM change_feed WHERE project_id = ?
               GROUP BY severity""",
            (project_id,),
        ).fetchall()
        by_severity = {row["severity"]: row["count"] for row in severity_rows}

        # Recent changes (last 5)
        recent_rows = conn.execute(
            """SELECT cf.title, cf.severity, cf.change_type,
                      cf.created_at, e.name as entity_name
               FROM change_feed cf
               JOIN entities e ON e.id = cf.entity_id
               WHERE cf.project_id = ? AND cf.is_dismissed = 0
               ORDER BY cf.created_at DESC
               LIMIT 5""",
            (project_id,),
        ).fetchall()

        recent_changes = [
            {
                "title": row["title"],
                "severity": row["severity"],
                "change_type": row["change_type"],
                "created_at": row["created_at"],
                "entity_name": row["entity_name"],
            }
            for row in recent_rows
        ]

    return jsonify({
        "total_monitors": total_monitors,
        "active_monitors": active_monitors,
        "inactive_monitors": total_monitors - active_monitors,
        "monitors_with_errors": monitors_with_errors,
        "changes_this_week": changes_this_week,
        "changes_total": changes_total,
        "unread_count": unread_count,
        "by_type": by_type,
        "by_severity": by_severity,
        "recent_changes": recent_changes,
    })


# ═════════════════════════════════════════════════════════════
# 12. Auto-Setup Monitors
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/auto-setup", methods=["POST"])
def auto_setup_monitors():
    """Auto-create monitors from entity URL attributes.

    Scans all entities in a project for URL-type attributes (website, url,
    homepage, store_url, etc.), detects the monitor type from the URL,
    and creates monitors for any that don't already exist.

    Query params:
        project_id (required): Project ID

    Request JSON (optional):
        check_interval_hours: int — interval for created monitors (default: 24)
        monitor_types: list — restrict to specific types (default: all)

    Returns:
        {created: N, skipped: N, monitors: [{id, entity_name, target_url, monitor_type}]}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    data = request.json or {}
    check_interval = data.get("check_interval_hours", 24)
    allowed_types = data.get("monitor_types")

    if allowed_types and not isinstance(allowed_types, list):
        return jsonify({"error": "monitor_types must be a list"}), 400

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        # Get all entities for this project
        entity_rows = conn.execute(
            """SELECT id, name FROM entities
               WHERE project_id = ? AND is_deleted = 0""",
            (project_id,),
        ).fetchall()

        entity_ids = [r["id"] for r in entity_rows]
        entity_names = {r["id"]: r["name"] for r in entity_rows}

        if not entity_ids:
            return jsonify({"created": 0, "skipped": 0, "monitors": []})

        # Find URL attributes for these entities
        placeholders = ",".join("?" * len(entity_ids))
        slug_placeholders = ",".join("?" * len(_URL_ATTR_SLUGS))

        attr_rows = conn.execute(
            f"""SELECT ea.entity_id, ea.attr_slug, ea.value
                FROM entity_attributes ea
                WHERE ea.entity_id IN ({placeholders})
                AND LOWER(ea.attr_slug) IN ({slug_placeholders})
                AND ea.id IN (
                    SELECT MAX(id) FROM entity_attributes
                    WHERE entity_id IN ({placeholders})
                    GROUP BY entity_id, attr_slug
                )""",
            list(entity_ids) + list(_URL_ATTR_SLUGS) + list(entity_ids),
        ).fetchall()

        # Also check for source URLs stored in entity source field
        source_rows = conn.execute(
            f"""SELECT id, source FROM entities
                WHERE id IN ({placeholders})
                AND source IS NOT NULL
                AND source LIKE 'http%'""",
            entity_ids,
        ).fetchall()

        # Collect candidate URLs
        candidates = []  # list of (entity_id, url)
        for row in attr_rows:
            val = (row["value"] or "").strip()
            if val and (val.startswith("http://") or val.startswith("https://")):
                candidates.append((row["entity_id"], val))

        for row in source_rows:
            source = (row["source"] or "").strip()
            if source:
                candidates.append((row["id"], source))

        # Get existing monitors for dedup
        existing_monitors = conn.execute(
            "SELECT entity_id, target_url FROM monitors WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        existing_set = {
            (row["entity_id"], row["target_url"]) for row in existing_monitors
        }

        created = 0
        skipped = 0
        created_monitors = []

        for entity_id, url in candidates:
            if (entity_id, url) in existing_set:
                skipped += 1
                continue

            monitor_type = _detect_monitor_type_from_url(url)
            if allowed_types and monitor_type not in allowed_types:
                skipped += 1
                continue

            cursor = conn.execute(
                """INSERT INTO monitors
                   (project_id, entity_id, monitor_type, target_url,
                    check_interval_hours, is_active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (project_id, entity_id, monitor_type, url, check_interval),
            )
            monitor_id = cursor.lastrowid
            existing_set.add((entity_id, url))
            created += 1
            created_monitors.append({
                "id": monitor_id,
                "entity_id": entity_id,
                "entity_name": entity_names.get(entity_id, ""),
                "target_url": url,
                "monitor_type": monitor_type,
            })

    logger.info(
        "Auto-setup for project %d: created %d monitors, skipped %d",
        project_id, created, skipped,
    )

    return jsonify({
        "created": created,
        "skipped": skipped,
        "monitors": created_monitors,
    })


# ═════════════════════════════════════════════════════════════
# Additional Endpoints
# ═════════════════════════════════════════════════════════════

@monitoring_bp.route("/api/monitoring/monitors/<int:monitor_id>/checks")
def list_monitor_checks(monitor_id):
    """List recent checks for a specific monitor.

    Query params:
        limit (optional): Max results (default: 20)
        offset (optional): Pagination offset (default: 0)

    Returns:
        List of check result dicts, newest first.
    """
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        monitor = conn.execute(
            "SELECT id FROM monitors WHERE id = ?", (monitor_id,)
        ).fetchone()

        if not monitor:
            return jsonify({"error": f"Monitor {monitor_id} not found"}), 404

        total = conn.execute(
            "SELECT COUNT(*) FROM monitor_checks WHERE monitor_id = ?",
            (monitor_id,),
        ).fetchone()[0]

        rows = conn.execute(
            """SELECT * FROM monitor_checks
               WHERE monitor_id = ?
               ORDER BY checked_at DESC
               LIMIT ? OFFSET ?""",
            (monitor_id, limit, offset),
        ).fetchall()

    checks = [_row_to_check(row) for row in rows]

    return jsonify({
        "monitor_id": monitor_id,
        "checks": checks,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@monitoring_bp.route("/api/monitoring/feed/unread-count")
def unread_count():
    """Get the count of unread, non-dismissed change feed items.

    Query params:
        project_id (required): Project ID

    Returns:
        {count: N}
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        _ensure_tables(conn)

        count = conn.execute(
            """SELECT COUNT(*) FROM change_feed
               WHERE project_id = ? AND is_read = 0 AND is_dismissed = 0""",
            (project_id,),
        ).fetchone()[0]

    return jsonify({"count": count})


def _bulk_update_feed(field, value):
    """Shared helper for bulk feed updates (read/dismiss)."""
    data = request.json or {}
    ids = data.get("ids", [])
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "ids must be a non-empty list"}), 400
    db = current_app.db
    with db._get_conn() as conn:
        _ensure_tables(conn)
        placeholders = ",".join("?" * len(ids))
        cursor = conn.execute(
            f"UPDATE change_feed SET {field} = ? WHERE id IN ({placeholders})",
            [value] + ids,
        )
    return jsonify({"updated": True, "count": cursor.rowcount})


@monitoring_bp.route("/api/monitoring/feed/bulk-dismiss", methods=["POST"])
def bulk_dismiss_feed():
    """Dismiss multiple feed items at once. Body: {ids: [int]}"""
    return _bulk_update_feed("is_dismissed", 1)


@monitoring_bp.route("/api/monitoring/feed/bulk-read", methods=["POST"])
def bulk_read_feed():
    """Mark multiple feed items as read at once. Body: {ids: [int]}"""
    return _bulk_update_feed("is_read", 1)


@monitoring_bp.route("/api/monitoring/entity/<int:entity_id>/summary")
def entity_monitoring_summary(entity_id):
    """Monitoring summary for a specific entity: monitors, recent changes, health."""
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db
    with db._get_conn() as conn:
        _ensure_tables(conn)

        entity = conn.execute(
            "SELECT id, name FROM entities WHERE id = ? AND project_id = ? AND is_deleted = 0",
            (entity_id, project_id),
        ).fetchone()
        if not entity:
            return jsonify({"error": f"Entity {entity_id} not found in project {project_id}"}), 404

        monitors = [_row_to_monitor(r) for r in conn.execute(
            "SELECT * FROM monitors WHERE entity_id = ? ORDER BY created_at DESC",
            (entity_id,),
        ).fetchall()]

        recent_changes = [_row_to_feed_item(r) for r in conn.execute(
            """SELECT cf.*, e.name as entity_name FROM change_feed cf
               JOIN entities e ON e.id = cf.entity_id
               WHERE cf.entity_id = ? AND cf.is_dismissed = 0
               ORDER BY cf.created_at DESC LIMIT 10""",
            (entity_id,),
        ).fetchall()]

    # Derive health status
    has_errors = any(m["consecutive_errors"] > 0 for m in monitors)
    last_check = max((m["last_checked_at"] for m in monitors if m["last_checked_at"]), default=None)
    if not monitors:
        health_status = "no_monitors"
    elif has_errors:
        health_status = "degraded"
    elif last_check is None:
        health_status = "pending"
    else:
        health_status = "healthy"

    return jsonify({
        "entity_id": entity_id, "entity_name": entity["name"],
        "monitors": monitors, "recent_changes": recent_changes,
        "health": {
            "status": health_status, "last_check": last_check,
            "monitor_count": len(monitors),
            "active_count": sum(1 for m in monitors if m["is_active"]),
            "error_count": sum(1 for m in monitors if m["consecutive_errors"] > 0),
        },
    })
