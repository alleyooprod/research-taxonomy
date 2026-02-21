"""Settings API: share tokens, shared view, notifications, activity, SSE stream,
   app settings, backups, prerequisites, auto-update."""
import json
import logging
import queue
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from config import (
    APP_VERSION, DATA_DIR, BACKUP_DIR, DB_PATH, LOGS_DIR,
    load_app_settings, save_app_settings, check_prerequisites,
)
from web.notifications import sse_clients, _is_valid_slack_webhook

logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)


# --- Share Tokens ---

@settings_bp.route("/api/share-tokens", methods=["GET"])
def list_share_tokens():
    project_id = request.args.get("project_id", type=int)
    return jsonify(current_app.db.get_share_tokens(project_id))


@settings_bp.route("/api/share-tokens", methods=["POST"])
def create_share_token():
    db = current_app.db
    data = request.json
    project_id = data.get("project_id")
    label = data.get("label", "Shared link")
    token = db.create_share_token(project_id, label=label)
    if project_id:
        db.log_activity(project_id, "share_created",
                        f"Created share link: {label}", "project", project_id)
    return jsonify({"token": token, "url": f"/shared/{token}"})


@settings_bp.route("/api/share-tokens/<int:token_id>", methods=["DELETE"])
def revoke_share_token(token_id):
    current_app.db.revoke_share_token(token_id)
    return jsonify({"ok": True})


# --- Shared View (public) ---

@settings_bp.route("/shared/<token>")
def shared_view(token):
    db = current_app.db
    share = db.validate_share_token(token)
    if not share:
        return jsonify({"error": "Invalid or expired share link"}), 404
    project_id = share["project_id"]
    companies = db.get_companies(project_id=project_id)
    categories = db.get_category_stats(project_id=project_id)
    stats = db.get_stats(project_id=project_id)
    return jsonify({
        "project_id": project_id,
        "companies": companies,
        "categories": categories,
        "stats": stats,
        "label": share.get("label", "Shared view"),
        "read_only": True,
    })


# --- Activity Log ---

@settings_bp.route("/api/activity")
def get_activity():
    project_id = request.args.get("project_id", type=int)
    limit = min(max(request.args.get("limit", 50, type=int), 1), 500)
    offset = max(request.args.get("offset", 0, type=int), 0)
    return jsonify(current_app.db.get_activity(project_id, limit=limit, offset=offset))


# --- Notification Preferences ---

@settings_bp.route("/api/notification-prefs", methods=["GET"])
def get_notification_prefs():
    project_id = request.args.get("project_id", type=int)
    prefs = current_app.db.get_notification_prefs(project_id)
    return jsonify(prefs or {
        "slack_webhook_url": None, "notify_batch_complete": 1,
        "notify_taxonomy_change": 1, "notify_new_company": 0,
    })


@settings_bp.route("/api/notification-prefs", methods=["POST"])
def save_notification_prefs():
    data = request.json
    current_app.db.save_notification_prefs(
        project_id=data.get("project_id"),
        slack_webhook_url=data.get("slack_webhook_url"),
        notify_batch_complete=data.get("notify_batch_complete", 1),
        notify_taxonomy_change=data.get("notify_taxonomy_change", 1),
        notify_new_company=data.get("notify_new_company", 0),
    )
    return jsonify({"ok": True})


@settings_bp.route("/api/notification-prefs/test-slack", methods=["POST"])
def test_slack():
    data = request.json
    webhook_url = data.get("slack_webhook_url", "").strip()
    if not webhook_url:
        return jsonify({"error": "No webhook URL provided"}), 400
    if not _is_valid_slack_webhook(webhook_url):
        return jsonify({"error": "Invalid Slack webhook URL. Must be https://hooks.slack.com/services/..."}), 400
    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({"text": "Test notification from Research Taxonomy Library"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Slack webhook test failed for URL %s", webhook_url[:60])
        return jsonify({"error": "Slack webhook test failed. Verify the webhook URL is correct and accessible."}), 500


# --- App Settings ---

@settings_bp.route("/api/app-settings", methods=["GET"])
def get_app_settings():
    settings = load_app_settings()
    # Mask API key for frontend display
    if settings.get("anthropic_api_key"):
        key = settings["anthropic_api_key"]
        settings["anthropic_api_key_masked"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
    else:
        settings["anthropic_api_key_masked"] = ""
    settings.pop("anthropic_api_key", None)
    return jsonify(settings)


@settings_bp.route("/api/app-settings", methods=["POST"])
def update_app_settings():
    data = request.json
    settings = load_app_settings()
    allowed_keys = {
        "llm_backend", "anthropic_api_key", "default_model", "research_model",
        "git_sync_enabled", "git_remote_url", "auto_backup_enabled",
        "update_check_enabled",
    }
    updates = {key: data[key] for key in allowed_keys if key in data}

    _SETTINGS_VALIDATORS = {
        "llm_backend": lambda v: v in ("cli", "sdk"),
        "git_sync_enabled": lambda v: isinstance(v, bool),
        "auto_backup_enabled": lambda v: isinstance(v, bool),
        "update_check_enabled": lambda v: isinstance(v, bool),
        "git_remote_url": lambda v: isinstance(v, str) and len(v) < 500,
        "anthropic_api_key": lambda v: isinstance(v, str),
    }
    for key, value in list(updates.items()):
        validator = _SETTINGS_VALIDATORS.get(key)
        if validator and not validator(value):
            return jsonify({"error": f"Invalid value for {key}"}), 400

    settings.update(updates)
    save_app_settings(settings)
    return jsonify({"ok": True})


# --- Prerequisites Check ---

@settings_bp.route("/api/prerequisites")
def get_prerequisites():
    return jsonify(check_prerequisites())


# --- Database Backup & Restore ---

@settings_bp.route("/api/backups", methods=["GET"])
def list_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = []
    for f in sorted(BACKUP_DIR.glob("taxonomy_*.db"), reverse=True):
        stat = f.stat()
        backups.append({
            "filename": f.name,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return jsonify(backups)


@settings_bp.route("/api/backups", methods=["POST"])
def create_backup():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"taxonomy_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name
    try:
        shutil.copy2(str(DB_PATH), str(backup_path))
        size_mb = round(backup_path.stat().st_size / 1024 / 1024, 2)
        logger.info("Created backup: %s (%.2f MB)", backup_name, size_mb)
        return jsonify({
            "ok": True,
            "filename": backup_name,
            "size_mb": size_mb,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/backups/<filename>/restore", methods=["POST"])
def restore_backup(filename):
    # Validate filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        return jsonify({"error": "Backup not found"}), 404
    # Verify backup is a valid SQLite database
    import sqlite3 as _sqlite3
    try:
        _conn = _sqlite3.connect(str(backup_path))
        result = _conn.execute("PRAGMA integrity_check").fetchone()
        _conn.close()
        if result[0] != "ok":
            return jsonify({"error": "Backup file is corrupted"}), 400
    except Exception:
        return jsonify({"error": "Invalid backup file"}), 400

    try:
        # Create a safety backup of current DB before restoring
        safety = BACKUP_DIR / f"taxonomy_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(str(DB_PATH), str(safety))
        shutil.copy2(str(backup_path), str(DB_PATH))
        # Reinitialize DB connection
        from storage.db import Database
        current_app.db = Database()
        logger.info("Restored from backup: %s", filename)
        return jsonify({"ok": True, "restored_from": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@settings_bp.route("/api/backups/<filename>", methods=["DELETE"])
def delete_backup(filename):
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        return jsonify({"error": "Backup not found"}), 404
    backup_path.unlink()
    return jsonify({"ok": True})


# --- Auto-Update Check ---

_UPDATE_CHECK_URL = "https://api.github.com/repos/olly/taxonomy-library/releases/latest"


@settings_bp.route("/api/update-check")
def check_for_updates():
    try:
        req = urllib.request.Request(
            _UPDATE_CHECK_URL,
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "TaxonomyLibrary"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        latest = data.get("tag_name", "").lstrip("v")
        settings = load_app_settings()
        settings["last_update_check"] = datetime.now().isoformat()
        save_app_settings(settings)
        return jsonify({
            "current_version": APP_VERSION,
            "latest_version": latest,
            "update_available": latest and latest != APP_VERSION,
            "release_url": data.get("html_url", ""),
            "release_notes": data.get("body", ""),
        })
    except Exception:
        return jsonify({
            "current_version": APP_VERSION,
            "latest_version": None,
            "update_available": False,
            "error": "Could not check for updates",
        })


# --- Crash Logs ---

@settings_bp.route("/api/logs")
def get_logs():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_files = []
    for f in sorted(LOGS_DIR.glob("*.log"), reverse=True)[:10]:
        stat = f.stat()
        log_files.append({
            "filename": f.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return jsonify(log_files)


@settings_bp.route("/api/logs/<filename>")
def get_log_content(filename):
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    log_path = LOGS_DIR / filename
    if not log_path.exists():
        return jsonify({"error": "Log not found"}), 404
    # Return last 500 lines
    try:
        lines = log_path.read_text().splitlines()[-500:]
        return jsonify({"filename": filename, "content": "\n".join(lines)})
    except Exception as e:
        logger.exception("Failed to read log file %s", filename)
        return jsonify({"error": "Failed to read log file."}), 500


# --- SSE Stream ---

@settings_bp.route("/api/events/stream")
def sse_stream():
    project_id = request.args.get("project_id", type=int)
    if not project_id or project_id < 1:
        return "project_id required", 400

    # Verify the project exists to prevent arbitrary subscription
    project = current_app.db.get_project(project_id)
    if not project:
        return "project not found", 404

    q = queue.Queue()
    if project_id not in sse_clients:
        sse_clients[project_id] = []
    sse_clients[project_id].append(q)

    def generate():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            if project_id in sse_clients and q in sse_clients[project_id]:
                sse_clients[project_id].remove(q)

    return current_app.response_class(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
