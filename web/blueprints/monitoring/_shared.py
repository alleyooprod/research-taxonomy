"""Shared helpers, constants, check handlers, and DB schema for Monitoring."""
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import request, jsonify, current_app
from loguru import logger

from .._utils import (
    require_project_id as _require_project_id,
    now_iso as _now_iso,
    is_safe_url as _is_safe_url,
)

# ── Constants ────────────────────────────────────────────────

_VALID_MONITOR_TYPES = {
    "website", "appstore", "playstore", "rss",
    "hackernews", "news_search", "traffic", "patent",
}

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
        info     — minor text changes, new blog post, news mentions
        minor    — screenshot updates, description changes, traffic shifts
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
        "news_mention": "info",
        "news_article": "info",
        "traffic_change": "minor",
        "patent_filed": "info",
    }
    severity = severity_map.get(change_type, "info")

    # Upgrade severity based on content analysis if summary is provided
    if change_summary and severity in ("minor", "info"):
        summary_lower = change_summary.lower()
        # Check for keywords that suggest higher severity
        major_keywords = [
            "pricing", "price", "plan", "tier", "cost",
            "version", "release", "update", "feature",
            "acquisition", "acquired", "merger",
            "ipo", "bankrupt",
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


def _check_hackernews(monitor, conn):
    """Check Hacker News for mentions of the entity."""
    from core.mcp_client import search_hackernews

    entity_name = monitor["target_url"]
    try:
        stories = search_hackernews(entity_name, num_results=50, conn=conn)
    except Exception as e:
        return _check_error(f"Hacker News search failed: {e}")

    if stories is None:
        return _check_error("Hacker News search unavailable (API returned None)")

    # Build fingerprint from sorted story IDs
    story_ids = sorted({str(s.get("story_id", s.get("id", ""))) for s in stories if s})
    content_hash = hashlib.sha256(json.dumps(story_ids).encode()).hexdigest()

    prev = _get_prev_check(conn, monitor["id"])
    changes_detected = prev is not None and prev["content_hash"] != content_hash

    change_summary = None
    change_details = None
    custom_severity = None

    if changes_detected:
        # Determine which stories are new
        old_ids = set()
        if prev and prev["change_details"]:
            try:
                old_details = json.loads(prev["change_details"])
                old_ids = {
                    str(s.get("story_id", s.get("id", "")))
                    for s in old_details.get("stories", [])
                }
            except (json.JSONDecodeError, TypeError):
                pass

        current_ids = {str(s.get("story_id", s.get("id", ""))) for s in stories if s}
        new_ids = current_ids - old_ids
        new_stories = [
            s for s in stories
            if str(s.get("story_id", s.get("id", ""))) in new_ids
        ]
        new_count = len(new_stories)

        # Build summary with top story title
        top_title = ""
        if new_stories:
            top_title = f" — \"{new_stories[0].get('title', 'Untitled')}\""
        change_summary = f"{new_count} new Hacker News mention{'s' if new_count != 1 else ''}{top_title}"

        change_details = json.dumps({
            "stories": [s for s in stories[:10]],
            "new_count": new_count,
        })

        # Custom severity based on points
        max_points = max(
            (s.get("points", 0) or 0 for s in new_stories),
            default=0,
        )
        if max_points > 500:
            custom_severity = "critical"
        elif max_points > 100:
            custom_severity = "major"
    else:
        change_details = json.dumps({
            "stories": [s for s in stories[:10]],
            "new_count": 0,
        })

    result = {
        "status": "completed",
        "content_hash": content_hash,
        "changes_detected": changes_detected,
        "change_summary": change_summary,
        "change_details": change_details,
        "error": None,
    }
    if changes_detected:
        result["_change_type"] = "news_mention"
        if custom_severity:
            result["_severity_override"] = custom_severity
    return result


def _check_news_search(monitor, conn):
    """Check news sources for articles about the entity."""
    from core.mcp_client import search_news

    entity_name = monitor["target_url"]
    try:
        articles = search_news(entity_name, num_results=20, conn=conn)
    except Exception as e:
        return _check_error(f"News search failed: {e}")

    if articles is None:
        return _check_error("News search unavailable (API returned None)")

    # Build fingerprint from sorted article URLs
    article_urls = sorted({
        a.get("url", a.get("link", "")) for a in articles if a
    })
    content_hash = hashlib.sha256(json.dumps(article_urls).encode()).hexdigest()

    prev = _get_prev_check(conn, monitor["id"])
    changes_detected = prev is not None and prev["content_hash"] != content_hash

    change_summary = None
    change_details = None

    if changes_detected:
        # Determine which articles are new
        old_urls = set()
        if prev and prev["change_details"]:
            try:
                old_details = json.loads(prev["change_details"])
                old_urls = {
                    a.get("url", a.get("link", ""))
                    for a in old_details.get("articles", [])
                }
            except (json.JSONDecodeError, TypeError):
                pass

        current_urls = {a.get("url", a.get("link", "")) for a in articles if a}
        new_urls = current_urls - old_urls
        new_articles = [
            a for a in articles
            if a.get("url", a.get("link", "")) in new_urls
        ]
        new_count = len(new_articles)

        # Build summary with first new article title
        first_title = ""
        if new_articles:
            first_title = f" — \"{new_articles[0].get('title', 'Untitled')}\""
        change_summary = (
            f"{new_count} new news article{'s' if new_count != 1 else ''} "
            f"about {entity_name}{first_title}"
        )

        change_details = json.dumps({
            "articles": articles[:20],
            "new_count": new_count,
        })
    else:
        change_details = json.dumps({
            "articles": articles[:20],
            "new_count": 0,
        })

    result = {
        "status": "completed",
        "content_hash": content_hash,
        "changes_detected": changes_detected,
        "change_summary": change_summary,
        "change_details": change_details,
        "error": None,
    }
    if changes_detected:
        result["_change_type"] = "news_article"
    return result


def _check_traffic(monitor, conn):
    """Check domain traffic rank via Cloudflare Radar."""
    from core.mcp_client import get_domain_rank

    domain = monitor["target_url"]
    try:
        rank_data = get_domain_rank(domain, conn=conn)
    except Exception as e:
        return _check_error(f"Traffic rank lookup failed: {e}")

    if rank_data is None:
        return _check_error("Traffic rank unavailable (API returned None)")

    rank = rank_data.get("rank", 0)
    category = rank_data.get("category", "unknown")

    # Build fingerprint from rank + category
    fingerprint_str = f"{rank}:{category}"
    content_hash = hashlib.sha256(fingerprint_str.encode()).hexdigest()

    prev = _get_prev_check(conn, monitor["id"])
    changes_detected = prev is not None and prev["content_hash"] != content_hash

    change_summary = None
    change_details = None
    custom_severity = None

    if changes_detected:
        # Calculate rank difference from previous check
        prev_rank = None
        if prev and prev["change_details"]:
            try:
                old_details = json.loads(prev["change_details"])
                prev_rank = old_details.get("rank")
            except (json.JSONDecodeError, TypeError):
                pass

        change_pct = 0.0
        if prev_rank and prev_rank > 0 and rank > 0:
            change_pct = round(abs(rank - prev_rank) / prev_rank * 100, 1)

        if prev_rank is not None:
            change_summary = f"Domain rank changed: {prev_rank} -> {rank}"
        else:
            change_summary = f"Domain rank: {rank} (category: {category})"

        change_details = json.dumps({
            "rank": rank,
            "prev_rank": prev_rank,
            "category": category,
            "change_pct": change_pct,
        })

        # Custom severity based on rank swing percentage
        if change_pct > 80:
            custom_severity = "critical"
        elif change_pct > 50:
            custom_severity = "major"
    else:
        change_details = json.dumps({
            "rank": rank,
            "prev_rank": None,
            "category": category,
            "change_pct": 0.0,
        })

    result = {
        "status": "completed",
        "content_hash": content_hash,
        "changes_detected": changes_detected,
        "change_summary": change_summary,
        "change_details": change_details,
        "error": None,
    }
    if changes_detected:
        result["_change_type"] = "traffic_change"
        if custom_severity:
            result["_severity_override"] = custom_severity
    return result


def _check_patent(monitor, conn):
    """Check for new patent filings by the entity."""
    from core.mcp_client import search_patents

    entity_name = monitor["target_url"]
    try:
        patents = search_patents(entity_name, num_results=20, conn=conn)
    except Exception as e:
        return _check_error(f"Patent search failed: {e}")

    if patents is None:
        return _check_error("Patent search unavailable (API returned None)")

    # Build fingerprint from sorted patent IDs
    patent_ids = sorted({
        str(p.get("patent_id", p.get("id", ""))) for p in patents if p
    })
    content_hash = hashlib.sha256(json.dumps(patent_ids).encode()).hexdigest()

    prev = _get_prev_check(conn, monitor["id"])
    changes_detected = prev is not None and prev["content_hash"] != content_hash

    change_summary = None
    change_details = None

    if changes_detected:
        # Determine which patents are new
        old_ids = set()
        if prev and prev["change_details"]:
            try:
                old_details = json.loads(prev["change_details"])
                old_ids = {
                    str(p.get("patent_id", p.get("id", "")))
                    for p in old_details.get("patents", [])
                }
            except (json.JSONDecodeError, TypeError):
                pass

        current_ids = {str(p.get("patent_id", p.get("id", ""))) for p in patents if p}
        new_ids = current_ids - old_ids
        new_patents = [
            p for p in patents
            if str(p.get("patent_id", p.get("id", ""))) in new_ids
        ]
        new_count = len(new_patents)

        # Build summary with first new patent title
        first_title = ""
        if new_patents:
            first_title = f" — \"{new_patents[0].get('title', 'Untitled')}\""
        change_summary = (
            f"{new_count} new patent{'s' if new_count != 1 else ''} "
            f"filed by {entity_name}{first_title}"
        )

        change_details = json.dumps({
            "patents": patents[:20],
            "new_count": new_count,
        })
    else:
        change_details = json.dumps({
            "patents": patents[:20],
            "new_count": 0,
        })

    result = {
        "status": "completed",
        "content_hash": content_hash,
        "changes_detected": changes_detected,
        "change_summary": change_summary,
        "change_details": change_details,
        "error": None,
    }
    if changes_detected:
        result["_change_type"] = "patent_filed"
    return result


# Dispatcher for check functions by monitor type
_CHECK_HANDLERS = {
    "website": _check_website,
    "appstore": _check_appstore,
    "playstore": _check_playstore,
    "rss": _check_rss,
    "hackernews": _check_hackernews,
    "news_search": _check_news_search,
    "traffic": _check_traffic,
    "patent": _check_patent,
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
        # Allow handlers to override severity (e.g. hackernews points, traffic swing)
        if result.get("_severity_override"):
            severity = result["_severity_override"]

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


