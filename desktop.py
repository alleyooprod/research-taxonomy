"""Desktop launcher -- opens the app in a native macOS window.

Features:
  - Full native menu bar (File, View, Help) with exports, tabs, and utilities
  - Window position/size/maximized persistence across launches
  - Loading splash with progress stages while Flask starts
  - Native macOS notifications for background events
  - Auto git-sync on close with configurable timeout
  - Database backup/restore via File menu
  - Dock badge for background job completions
  - Dock right-click menu via AppKit
  - System event handlers (sleep/wake, dark mode sync, network change)
  - Spotlight indexing via CoreSpotlight
  - Handoff support via NSUserActivity
  - Enhanced crash reporter with native dialog
  - Window focus/blur handling for background operation pausing
  - Graceful Flask shutdown on exit
  - Crash logging to ~/Library/Logs or data/logs
"""
import atexit
import json
import logging
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import webview
from webview.menu import Menu, MenuAction, MenuSeparator

from config import (
    WEB_HOST,
    WEB_PORT,
    DATA_DIR,
    APP_VERSION,
    BACKUP_DIR,
    load_app_settings,
)
from core.git_sync import sync_to_git
from web.app import create_app

logger = logging.getLogger(__name__)


# --- Enhanced Crash Handler ---


def _crash_handler(exc_type, exc_value, exc_tb):
    """Enhanced crash handler with native dialog and log saving."""
    import traceback

    crash_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    # Write crash log
    crash_dir = DATA_DIR / "logs"
    crash_dir.mkdir(parents=True, exist_ok=True)
    crash_file = crash_dir / f"crash_{int(time.time())}.log"
    try:
        with open(crash_file, "w") as f:
            f.write(f"Crash at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Version: {APP_VERSION}\n\n")
            f.write(crash_text)
    except Exception:
        pass

    # Try to show native alert
    try:
        from AppKit import NSAlert, NSApplication, NSCriticalAlertStyle

        NSApplication.sharedApplication()  # Ensure app is initialized
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Research Taxonomy Library has encountered an error")
        alert.setInformativeText_(
            f"The error has been logged to:\n{crash_file}\n\nThe application will now close."
        )
        alert.setAlertStyle_(NSCriticalAlertStyle)
        alert.addButtonWithTitle_("OK")
        alert.addButtonWithTitle_("View Log")
        response = alert.runModal()
        if response == 1001:  # "View Log" button
            subprocess.Popen(["open", str(crash_file)])
    except Exception:
        pass

    logger.critical("CRASH: %s", crash_text)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _crash_handler


# --- Startup Timing ---

_startup_t0 = time.monotonic()


def _log_timing(stage):
    """Log elapsed time since startup for diagnostics."""
    elapsed = time.monotonic() - _startup_t0
    logger.info("Startup [%.2fs] %s", elapsed, stage)


# --- Window State Persistence ---

_WINDOW_STATE_FILE = DATA_DIR / ".window_state.json"
_DEFAULT_STATE = {
    "x": None,
    "y": None,
    "width": 1440,
    "height": 900,
    "maximized": False,
}


def _load_window_state():
    """Load saved window position/size, or return defaults."""
    try:
        if _WINDOW_STATE_FILE.exists():
            state = json.loads(_WINDOW_STATE_FILE.read_text())
            merged = {**_DEFAULT_STATE, **state}
            try:
                from AppKit import NSScreen

                screens = NSScreen.screens()
                if screens and merged["x"] is not None and merged["y"] is not None:
                    visible = False
                    for screen in screens:
                        frame = screen.frame()
                        sx, sy = frame.origin.x, frame.origin.y
                        sw, sh = frame.size.width, frame.size.height
                        if (
                            merged["x"] < sx + sw
                            and merged["x"] + merged["width"] > sx
                            and merged["y"] < sy + sh
                            and merged["y"] + merged["height"] > sy
                        ):
                            visible = True
                            break
                    if not visible:
                        merged["x"] = None
                        merged["y"] = None
            except ImportError:
                pass
            # Validate numeric ranges to prevent extreme values
            merged["width"] = max(800, min(merged.get("width") or 1440, 5000))
            merged["height"] = max(600, min(merged.get("height") or 900, 3000))
            merged["x"] = max(-2000, min(merged.get("x") or 0, 10000)) if merged.get("x") is not None else None
            merged["y"] = max(-2000, min(merged.get("y") or 0, 10000)) if merged.get("y") is not None else None
            return merged
    except Exception:
        pass
    return _DEFAULT_STATE.copy()


def _save_window_state(window):
    """Persist current window geometry and maximized state."""
    try:
        is_maximized = False
        try:
            from AppKit import NSApplication

            ns_app = NSApplication.sharedApplication()
            ns_window = ns_app.mainWindow()
            if ns_window:
                style_mask = ns_window.styleMask()
                # NSWindowStyleMaskFullScreen = 1 << 14
                is_maximized = bool(style_mask & (1 << 14))
        except (ImportError, Exception):
            pass

        state = {
            "x": window.x,
            "y": window.y,
            "width": window.width,
            "height": window.height,
            "maximized": is_maximized,
        }
        _WINDOW_STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


# --- Native macOS Notifications ---


def send_notification(title, message, sound=True):
    """Send macOS notification using native API (no osascript injection risk)."""
    try:
        from Foundation import NSUserNotification, NSUserNotificationCenter
        notification = NSUserNotification.alloc().init()
        notification.setTitle_(str(title)[:200])
        notification.setInformativeText_(str(message)[:500])
        if sound:
            notification.setSoundName_("default")
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        center.deliverNotification_(notification)
    except Exception:
        pass  # Silently fail if pyobjc not available


# --- Dock Badge ---


def set_dock_badge(count):
    """Set the Dock icon badge number (0 to clear)."""
    try:
        from AppKit import NSApplication

        app = NSApplication.sharedApplication()
        dock_tile = app.dockTile()
        dock_tile.setBadgeLabel_(str(count) if count > 0 else "")
    except Exception:
        pass


def bounce_dock():
    """Bounce the Dock icon to get attention."""
    try:
        from AppKit import NSApplication, NSInformationalRequest

        app = NSApplication.sharedApplication()
        app.requestUserAttention_(NSInformationalRequest)
    except Exception:
        pass


# --- Dock Menu (right-click on Dock icon) ---


def _setup_dock_menu():
    """Add a right-click dock menu via AppKit. Fails silently if unavailable."""
    try:
        from AppKit import NSApplication, NSMenu, NSMenuItem

        app = NSApplication.sharedApplication()
        dock_menu = NSMenu.alloc().initWithTitle_("Dock Menu")

        new_project_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "New Project", None, ""
        )
        dock_menu.addItem_(new_project_item)

        dock_menu.addItem_(NSMenuItem.separatorItem())

        # We attach the dock menu to the app delegate if one exists,
        # otherwise set it directly. pywebview may or may not have a delegate.
        delegate = app.delegate()
        if delegate and hasattr(delegate, "setDockMenu_"):
            delegate.setDockMenu_(dock_menu)
        else:
            # Store reference so it can be retrieved by applicationDockMenu_
            app._custom_dock_menu = dock_menu
            logger.debug("Dock menu created (delegate method unavailable, stored on app)")
    except ImportError:
        logger.debug("AppKit not available, skipping dock menu")
    except Exception as e:
        logger.debug("Dock menu setup failed: %s", e)


# --- System Event Handlers ---

_system_sleeping = False
_network_available = True
_dark_mode_observer = None
_sleep_observer = None
_wake_observer = None


def _setup_system_event_handlers():
    """Register observers for sleep/wake, dark mode changes, and network status."""
    global _sleep_observer, _wake_observer, _dark_mode_observer

    # --- Sleep/Wake Notifications ---
    try:
        from AppKit import NSWorkspace, NSNotificationCenter
        from Foundation import NSObject

        workspace = NSWorkspace.sharedWorkspace()
        nc = workspace.notificationCenter()

        class SleepWakeObserver(NSObject):
            def handleSleepNotification_(self, notification):
                global _system_sleeping
                _system_sleeping = True
                logger.info("System going to sleep -- pausing background operations")
                if _window_ref:
                    try:
                        _window_ref.evaluate_js(
                            "if(typeof onSystemSleep==='function') onSystemSleep()"
                        )
                    except Exception:
                        pass

            def handleWakeNotification_(self, notification):
                global _system_sleeping
                _system_sleeping = False
                logger.info("System woke up -- resuming background operations")
                if _window_ref:
                    try:
                        _window_ref.evaluate_js(
                            "if(typeof onSystemWake==='function') onSystemWake()"
                        )
                    except Exception:
                        pass

        observer = SleepWakeObserver.alloc().init()
        nc.addObserver_selector_name_object_(
            observer,
            "handleSleepNotification:",
            "NSWorkspaceWillSleepNotification",
            None,
        )
        nc.addObserver_selector_name_object_(
            observer,
            "handleWakeNotification:",
            "NSWorkspaceDidWakeNotification",
            None,
        )
        _sleep_observer = observer  # prevent GC
        _wake_observer = observer
        logger.debug("Sleep/wake observers registered")
    except ImportError:
        logger.debug("AppKit not available, skipping sleep/wake observers")
    except Exception as e:
        logger.debug("Sleep/wake observer setup failed: %s", e)

    # --- Dark Mode Change Detection ---
    try:
        from AppKit import NSDistributedNotificationCenter
        from Foundation import NSObject

        class DarkModeObserver(NSObject):
            def handleThemeChange_(self, notification):
                logger.debug("System appearance changed")
                if _window_ref:
                    try:
                        _window_ref.evaluate_js(
                            "if(typeof syncSystemTheme==='function') syncSystemTheme()"
                        )
                    except Exception:
                        pass

        dm_observer = DarkModeObserver.alloc().init()
        dnc = NSDistributedNotificationCenter.defaultCenter()
        dnc.addObserver_selector_name_object_(
            dm_observer,
            "handleThemeChange:",
            "AppleInterfaceThemeChangedNotification",
            None,
        )
        _dark_mode_observer = dm_observer  # prevent GC
        logger.debug("Dark mode observer registered")
    except ImportError:
        logger.debug("AppKit not available, skipping dark mode observer")
    except Exception as e:
        logger.debug("Dark mode observer setup failed: %s", e)


# --- Network Change Detection ---

_network_check_thread = None
_network_check_stop = threading.Event()


def _check_network_loop():
    """Periodically check network reachability and notify frontend."""
    global _network_available
    while not _network_check_stop.is_set():
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            new_state = True
        except OSError:
            new_state = False

        if new_state != _network_available:
            _network_available = new_state
            logger.info("Network state changed: %s", "available" if new_state else "unavailable")
            if _window_ref:
                try:
                    _window_ref.evaluate_js(
                        f"if(typeof onNetworkChange==='function') onNetworkChange({str(new_state).lower()})"
                    )
                except Exception:
                    pass

        _network_check_stop.wait(30)  # check every 30 seconds


def _start_network_monitor():
    """Start the network monitoring background thread."""
    global _network_check_thread
    _network_check_thread = threading.Thread(target=_check_network_loop, daemon=True)
    _network_check_thread.start()


def is_system_sleeping():
    """Check if the system is currently sleeping (for background job guards)."""
    return _system_sleeping


def is_network_available():
    """Check current network availability."""
    return _network_available


# --- Spotlight Indexing via CoreSpotlight ---


def _index_to_spotlight(db_path):
    """Index projects and companies to macOS Spotlight via CoreSpotlight."""
    try:
        from CoreSpotlight import (
            CSSearchableIndex,
            CSSearchableItem,
            CSSearchableItemAttributeSet,
        )
        from CoreServices import kUTTypeText
        import sqlite3

        index = CSSearchableIndex.defaultSearchableIndex()
        items = []

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Index projects
        for row in conn.execute("SELECT id, name, description FROM projects"):
            attrs = CSSearchableItemAttributeSet.alloc().initWithItemContentType_(
                str(kUTTypeText)
            )
            attrs.setTitle_(row["name"])
            attrs.setContentDescription_(row["description"] or "")
            attrs.setKeywords_(["taxonomy", "research", "project"])
            item = CSSearchableItem.alloc().initWithUniqueIdentifier_domainIdentifier_attributeSet_(
                f"project:{row['id']}",
                "com.olly.taxonomy-library.projects",
                attrs,
            )
            items.append(item)

        # Index companies (top 500 most recently updated)
        for row in conn.execute("""
            SELECT c.id, c.name, c.description, c.url, p.name as project_name
            FROM companies c JOIN projects p ON c.project_id = p.id
            WHERE c.is_deleted = 0
            ORDER BY c.updated_at DESC LIMIT 500
        """):
            attrs = CSSearchableItemAttributeSet.alloc().initWithItemContentType_(
                str(kUTTypeText)
            )
            attrs.setTitle_(row["name"])
            attrs.setContentDescription_(row["description"] or "")
            attrs.setKeywords_(["company", row["project_name"] or "", "taxonomy"])
            if row["url"]:
                try:
                    from Foundation import NSURL

                    attrs.setURL_(NSURL.URLWithString_(row["url"]))
                except ImportError:
                    pass
            item = CSSearchableItem.alloc().initWithUniqueIdentifier_domainIdentifier_attributeSet_(
                f"company:{row['id']}",
                "com.olly.taxonomy-library.companies",
                attrs,
            )
            items.append(item)

        conn.close()

        if items:
            index.indexSearchableItems_completionHandler_(items, None)
            logger.info("Spotlight: indexed %d items", len(items))
    except ImportError:
        logger.debug("CoreSpotlight not available -- Spotlight indexing skipped")
    except Exception as e:
        logger.warning("Spotlight indexing failed: %s", e)


# --- Handoff Support via NSUserActivity ---

_current_activity = None


def _update_user_activity(activity_type, title, user_info=None):
    """Update NSUserActivity for Handoff support."""
    global _current_activity
    try:
        from Foundation import NSUserActivity

        if _current_activity:
            _current_activity.invalidate()

        activity = NSUserActivity.alloc().initWithActivityType_(
            f"com.olly.taxonomy-library.{activity_type}"
        )
        activity.setTitle_(title)
        activity.setEligibleForHandoff_(True)
        activity.setEligibleForSearch_(True)  # Also makes it searchable
        if user_info:
            activity.setUserInfo_(user_info)
        activity.becomeCurrent()
        _current_activity = activity
    except ImportError:
        pass
    except Exception as e:
        logger.debug("NSUserActivity update failed: %s", e)


# --- Loading Splash with Progress Stages ---

_SPLASH_HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
    background: #1a1a1a;
    color: #e0dcd3;
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100vh;
    flex-direction: column;
    gap: 24px;
  }
  .title { font-size: 28px; font-weight: 600; letter-spacing: -0.5px; }
  .subtitle {
    font-size: 14px;
    color: #888;
    transition: opacity 0.3s ease;
  }
  .version { font-size: 11px; color: #555; margin-top: 4px; }
  .spinner {
    width: 32px; height: 32px;
    border: 3px solid #333;
    border-top-color: #bc6c5a;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  .progress-bar {
    width: 200px; height: 3px;
    background: #333;
    border-radius: 2px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: #bc6c5a;
    border-radius: 2px;
    width: 0%;
    transition: width 0.5s ease;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <div class="title">Research Taxonomy Library</div>
  <div class="spinner"></div>
  <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
  <div class="subtitle" id="splashStatus">Initializing...</div>
  <div class="version">v""" + APP_VERSION + """</div>
  <script>
    function updateSplash(msg, pct) {
      var el = document.getElementById('splashStatus');
      var fill = document.getElementById('progressFill');
      if (el) el.textContent = msg;
      if (fill) fill.style.width = pct + '%';
    }
  </script>
</body>
</html>
"""


# --- Menu Actions ---

_window_ref = None
_port_ref = None
_flask_app_ref = None


def _menu_new_project():
    if _window_ref:
        _window_ref.evaluate_js(
            "document.getElementById('createProjectBtn')?.click() || "
            "(typeof showCreateProjectModal==='function' && showCreateProjectModal())"
        )


def _menu_export_json():
    if _window_ref:
        _window_ref.evaluate_js(
            "safeFetch('/api/export/json?project_id=' + currentProjectId)"
            ".then(r => r.blob())"
            ".then(b => { const a = document.createElement('a'); "
            "a.href = URL.createObjectURL(b); a.download = 'taxonomy_data.json'; a.click(); })"
        )


def _menu_export_csv():
    if _window_ref:
        _window_ref.evaluate_js(
            "safeFetch('/api/export/csv?project_id=' + currentProjectId)"
            ".then(r => r.blob())"
            ".then(b => { const a = document.createElement('a'); "
            "a.href = URL.createObjectURL(b); a.download = 'taxonomy_export.csv'; a.click(); })"
        )


def _menu_export_excel():
    if _window_ref:
        _window_ref.evaluate_js(
            "safeFetch('/api/export/excel?project_id=' + currentProjectId)"
            ".then(r => r.blob())"
            ".then(b => { const a = document.createElement('a'); "
            "a.href = URL.createObjectURL(b); a.download = 'taxonomy_export.xlsx'; a.click(); })"
        )


def _menu_export_markdown():
    if _window_ref:
        _window_ref.evaluate_js(
            "safeFetch('/api/export/markdown?project_id=' + currentProjectId)"
            ".then(r => r.blob())"
            ".then(b => { const a = document.createElement('a'); "
            "a.href = URL.createObjectURL(b); a.download = 'taxonomy_export.md'; a.click(); })"
        )


def _menu_backup():
    if _window_ref:
        _window_ref.evaluate_js("createBackup()")


def _menu_git_sync():
    """Trigger git sync from menu (non-blocking)."""
    threading.Thread(target=sync_to_git, args=("Manual sync from menu",), daemon=True).start()
    if _window_ref:
        _window_ref.evaluate_js("showToast('Git sync started...', 'info')")


def _menu_settings():
    if _window_ref:
        _window_ref.evaluate_js("showTab('settings')")


def _menu_reload():
    if _window_ref:
        _window_ref.evaluate_js("location.reload()")


def _menu_toggle_theme():
    if _window_ref:
        _window_ref.evaluate_js("toggleTheme()")


def _menu_tab(tab_name):
    """Return a closure that switches to the named tab."""
    def action():
        if _window_ref:
            _window_ref.evaluate_js(f"showTab('{tab_name}')")
    return action


def _menu_shortcuts():
    if _window_ref:
        _window_ref.evaluate_js("toggleShortcutsOverlay()")


def _menu_tour():
    if _window_ref:
        _window_ref.evaluate_js("startProductTour()")


def _menu_view_logs():
    if _window_ref:
        _window_ref.evaluate_js("openLogViewer()")


def _menu_open_data_folder():
    """Open the data directory in Finder."""
    try:
        subprocess.Popen(["open", str(DATA_DIR)])
    except Exception:
        pass


def _menu_about():
    if _window_ref:
        _window_ref.evaluate_js("openAboutDialog()")


def _build_menus():
    """Build full native macOS menu bar."""
    file_menu = Menu(
        "File",
        [
            MenuAction("New Project", _menu_new_project),
            MenuSeparator(),
            MenuAction("Export JSON", _menu_export_json),
            MenuAction("Export CSV", _menu_export_csv),
            MenuAction("Export Excel", _menu_export_excel),
            MenuAction("Export Markdown", _menu_export_markdown),
            MenuSeparator(),
            MenuAction("Backup Database", _menu_backup),
            MenuAction("Sync to Git", _menu_git_sync),
            MenuSeparator(),
            MenuAction("Settings...", _menu_settings),
        ],
    )
    view_menu = Menu(
        "View",
        [
            MenuAction("Reload", _menu_reload),
            MenuSeparator(),
            MenuAction("Toggle Dark Mode", _menu_toggle_theme),
            MenuSeparator(),
            MenuAction("Companies Tab", _menu_tab("companies")),
            MenuAction("Taxonomy Tab", _menu_tab("taxonomy")),
            MenuAction("Map Tab", _menu_tab("map")),
            MenuAction("Research Tab", _menu_tab("reports")),
            MenuAction("Canvas Tab", _menu_tab("canvas")),
            MenuAction("Discovery Tab", _menu_tab("discovery")),
            MenuAction("Process Tab", _menu_tab("process")),
            MenuAction("Export Tab", _menu_tab("export")),
            MenuAction("Settings Tab", _menu_tab("settings")),
        ],
    )
    help_menu = Menu(
        "Help",
        [
            MenuAction("About Research Taxonomy Library", _menu_about),
            MenuSeparator(),
            MenuAction("View Logs", _menu_view_logs),
            MenuAction("Open Data Folder", _menu_open_data_folder),
            MenuSeparator(),
            MenuAction("Product Tour", _menu_tour),
            MenuAction("Keyboard Shortcuts", _menu_shortcuts),
        ],
    )
    return [file_menu, view_menu, help_menu]


# --- JS <-> Python API (exposed to frontend) ---


class DesktopAPI:
    """Methods callable from JS via window.pywebview.api.*"""

    def notify(self, title, message):
        send_notification(title, message)

    def sync_git(self, message="Manual sync"):
        # Sanitize: single line, limit length, strip control chars
        import re
        clean = re.sub(r'[\x00-\x1f\x7f]', '', str(message)).strip()[:200]
        if not clean:
            clean = "Manual sync"
        sync_to_git(clean)

    def set_badge(self, count):
        set_dock_badge(count)

    def bounce(self):
        bounce_dock()

    def get_version(self):
        return APP_VERSION

    def is_sleeping(self):
        """Check if the system is sleeping (for JS background job guards)."""
        return is_system_sleeping()

    def is_online(self):
        """Check network availability from JS."""
        return is_network_available()

    def open_data_folder(self):
        """Open the data directory in Finder."""
        _menu_open_data_folder()

    def update_activity(self, activity_type, title, info=None):
        """Called from JS when user navigates."""
        _ALLOWED_ACTIVITIES = {"viewing", "editing", "researching", "browsing"}
        if activity_type not in _ALLOWED_ACTIVITIES:
            return
        _update_user_activity(activity_type, str(title)[:100], None)

    def reindex_spotlight(self):
        """Trigger Spotlight re-indexing."""
        t = threading.Thread(
            target=_index_to_spotlight,
            args=(str(DATA_DIR / "taxonomy.db"),),
            daemon=True,
        )
        t.start()
        return True

    def on_focus_change(self, focused):
        """Called from JS when window gains/loses focus."""
        if not focused:
            logger.debug("Window lost focus -- background operations may be paused")
        else:
            logger.debug("Window gained focus")


# --- Server Helpers ---


def _find_free_port(preferred):
    """Return preferred port if available, otherwise find a free one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((WEB_HOST, preferred))
            return preferred
        except OSError:
            s.bind((WEB_HOST, 0))
            return s.getsockname()[1]


_flask_server_shutdown = threading.Event()


def _run_flask(app, port):
    """Run Flask in a background thread (no reloader in desktop mode).

    Uses werkzeug's server with a shutdown mechanism.
    """
    from werkzeug.serving import make_server

    server = make_server(WEB_HOST, port, app, threaded=True)
    app._werkzeug_server = server
    _log_timing("Flask server starting on port %d" % port)

    def serve():
        server.serve_forever()

    serve_thread = threading.Thread(target=serve, daemon=True)
    serve_thread.start()

    # Wait for shutdown signal
    _flask_server_shutdown.wait()
    logger.info("Shutting down Flask server...")
    server.shutdown()
    logger.info("Flask server stopped")


def _wait_for_server(host, port, retries=50, window=None):
    """Block until the Flask server accepts connections.

    Supports up to 50 retries (10 seconds) for slow machines.
    Optionally updates splash screen with progress.
    """
    for i in range(retries):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            # Update splash progress if window available
            if window and i % 5 == 0:
                pct = min(60 + int((i / retries) * 30), 90)
                try:
                    window.evaluate_js(f"updateSplash('Starting server...', {pct})")
                except Exception:
                    pass
            time.sleep(0.2)
    return False


# --- Auto-backup on startup ---


def _auto_backup_if_needed():
    """Create a daily auto-backup if enabled and none exists for today."""
    _log_timing("Checking auto-backup")
    settings = load_app_settings()
    if not settings.get("auto_backup_enabled", True):
        return
    from config import DB_PATH

    if not DB_PATH.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y%m%d")
    existing = list(BACKUP_DIR.glob(f"taxonomy_{today}_*.db"))
    if existing:
        return

    import sqlite3

    backup_name = f"taxonomy_{today}_auto.db"
    backup_path = str(BACKUP_DIR / backup_name)
    try:
        src = sqlite3.connect(str(DB_PATH))
        dst = sqlite3.connect(backup_path)
        src.backup(dst)
        dst.close()
        src.close()
        logger.info("Auto-backup created: %s", backup_name)
        # Clean up backups older than 30 days
        cutoff = time.time() - 30 * 86400
        for f in BACKUP_DIR.glob("taxonomy_*_auto.db"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("Auto-backup failed: %s", e)


# --- Temp File Cleanup ---


def _cleanup_temp_files():
    """Remove any temp files created during the session."""
    try:
        temp_dir = Path(tempfile.gettempdir())
        for pattern in ["rtl_export_*", "taxonomy_temp_*"]:
            for f in temp_dir.glob(pattern):
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass


# --- Graceful Shutdown ---


def _graceful_shutdown(window):
    """Full cleanup: save state, git-sync, stop Flask, clean temps."""
    # 1. Save window state
    if window:
        _save_window_state(window)

    # 2. Git sync (with configurable timeout)
    settings = load_app_settings()
    if settings.get("git_sync_enabled", True):
        git_timeout = settings.get("git_sync_timeout", 10)
        git_thread = threading.Thread(
            target=sync_to_git, args=("App closed -- auto-save",), daemon=True
        )
        git_thread.start()
        git_thread.join(timeout=git_timeout)
        if git_thread.is_alive():
            logger.warning("Git sync timed out after %ds, continuing shutdown", git_timeout)

    # 3. Signal Flask to stop
    _flask_server_shutdown.set()

    # 4. Clean up temp files
    _cleanup_temp_files()

    # 5. Stop network monitor
    _network_check_stop.set()

    logger.info("Graceful shutdown complete")


# --- Fullscreen Support ---


def _toggle_fullscreen():
    """Toggle macOS native fullscreen for the main window."""
    try:
        from AppKit import NSApplication

        app = NSApplication.sharedApplication()
        ns_window = app.mainWindow()
        if ns_window:
            ns_window.toggleFullScreen_(None)
    except ImportError:
        logger.debug("AppKit not available for fullscreen toggle")
    except Exception as e:
        logger.debug("Fullscreen toggle failed: %s", e)


def _restore_maximized_state(state):
    """If the window was previously maximized/fullscreen, restore that state."""
    if state.get("maximized", False):
        # Delay to let the window finish creating
        def _do_restore():
            time.sleep(1.5)
            _toggle_fullscreen()

        threading.Thread(target=_do_restore, daemon=True).start()


# --- Main ---


def _on_closing():
    """Save window state and perform graceful shutdown."""
    _graceful_shutdown(_window_ref)
    return True


def main():
    global _window_ref, _port_ref, _flask_app_ref

    _log_timing("Desktop main() started")

    port = _find_free_port(WEB_PORT)
    _port_ref = port
    flask_app = create_app()
    _flask_app_ref = flask_app

    _log_timing("Flask app created")

    # Auto-backup before starting
    _auto_backup_if_needed()
    _log_timing("Auto-backup check complete")

    # Start Flask server in background (with graceful shutdown support)
    server = threading.Thread(target=_run_flask, args=(flask_app, port), daemon=True)
    server.start()
    _log_timing("Flask server thread started")

    # Load saved window geometry
    state = _load_window_state()

    # Show splash while Flask starts
    api = DesktopAPI()
    window = webview.create_window(
        title="Research Taxonomy Library",
        html=_SPLASH_HTML,
        width=state["width"],
        height=state["height"],
        min_size=(1024, 680),
        x=state["x"],
        y=state["y"],
        js_api=api,
    )
    _window_ref = window
    window.events.closing += _on_closing

    # Register cleanup on process exit as a safety net
    atexit.register(lambda: _flask_server_shutdown.set())
    atexit.register(_cleanup_temp_files)

    _navigated = False

    def _on_loaded():
        nonlocal _navigated
        if _navigated:
            return

        # Update splash: initializing database
        try:
            window.evaluate_js("updateSplash('Initializing database...', 20)")
        except Exception:
            pass
        _log_timing("Splash shown, waiting for server")

        # Update splash: starting server
        try:
            window.evaluate_js("updateSplash('Starting server...', 40)")
        except Exception:
            pass

        if _wait_for_server(WEB_HOST, port, retries=50, window=window):
            _log_timing("Server is ready")
            # Update splash: loading UI
            try:
                window.evaluate_js("updateSplash('Loading UI...', 95)")
            except Exception:
                pass
            time.sleep(0.15)  # brief pause so user sees "Loading UI..."

            _navigated = True
            window.load_url(f"http://{WEB_HOST}:{port}")
            _log_timing("Navigated to app URL")

            # Setup system event handlers after app is loaded
            _setup_system_event_handlers()
            _start_network_monitor()
            _setup_dock_menu()
            _log_timing("System event handlers registered")

            # Spotlight indexing in background thread
            threading.Thread(
                target=_index_to_spotlight,
                args=(str(DATA_DIR / "taxonomy.db"),),
                daemon=True,
            ).start()
            _log_timing("Spotlight indexing started (background)")

            # Set initial user activity for Handoff
            _update_user_activity("viewing", "Research Taxonomy Library")
            _log_timing("Initial NSUserActivity set")

            # Inject focus/blur listener for background operation pausing
            try:
                window.evaluate_js("""
                    document.addEventListener('visibilitychange', function() {
                        if (typeof onWindowFocusChange === 'function') {
                            onWindowFocusChange(!document.hidden);
                        }
                    });
                """)
            except Exception:
                pass
            _log_timing("Focus/blur listener injected")

            # Restore fullscreen if previously maximized
            _restore_maximized_state(state)
        else:
            _navigated = True
            _log_timing("Server failed to start")
            window.load_html(
                "<html><body style='font-family:system-ui;display:flex;align-items:center;"
                "justify-content:center;height:100vh;color:#bc6c5a'>"
                "<h2>Failed to start server. Check the terminal for errors.</h2>"
                "</body></html>"
            )

    window.events.loaded += _on_loaded

    _log_timing("Starting pywebview event loop")
    webview.start(menu=_build_menus())


if __name__ == "__main__":
    main()
