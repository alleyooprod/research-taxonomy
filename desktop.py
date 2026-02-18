"""Desktop launcher — opens the app in a native macOS window."""
import signal
import sys
import threading

import webview

from config import WEB_HOST, WEB_PORT
from core.git_sync import sync_to_git
from web.app import create_app

_flask_app = create_app()


def _run_flask():
    """Run Flask in a background thread (no reloader in desktop mode)."""
    _flask_app.run(
        host=WEB_HOST,
        port=WEB_PORT,
        debug=False,
        use_reloader=False,
    )


def _on_closing():
    """Sync to git when the window closes."""
    sync_to_git("App closed — auto-save")
    return True  # allow close


def main():
    # Start Flask server
    server = threading.Thread(target=_run_flask, daemon=True)
    server.start()

    # Give Flask a moment to bind
    import time
    time.sleep(0.8)

    # Open native window
    window = webview.create_window(
        title="Research Taxonomy Library",
        url=f"http://{WEB_HOST}:{WEB_PORT}",
        width=1440,
        height=900,
        min_size=(1024, 680),
    )
    window.events.closing += _on_closing

    webview.start()

    # Final sync on exit (belt-and-suspenders)
    sync_to_git("App closed — auto-save")


if __name__ == "__main__":
    main()
