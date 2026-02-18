"""Desktop launcher — opens the app in a native macOS window."""
import socket
import sys
import threading
import time

import webview

from config import WEB_HOST, WEB_PORT
from core.git_sync import sync_to_git
from web.app import create_app


def _find_free_port(preferred):
    """Return preferred port if available, otherwise find a free one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((WEB_HOST, preferred))
            return preferred
        except OSError:
            # Port in use — pick a random free one
            s.bind((WEB_HOST, 0))
            return s.getsockname()[1]


def _run_flask(app, port):
    """Run Flask in a background thread (no reloader in desktop mode)."""
    app.run(
        host=WEB_HOST,
        port=port,
        debug=False,
        use_reloader=False,
    )


def _on_closing():
    """Sync to git when the window closes."""
    sync_to_git("App closed — auto-save")
    return True  # allow close


def main():
    port = _find_free_port(WEB_PORT)
    flask_app = create_app()

    # Start Flask server
    server = threading.Thread(target=_run_flask, args=(flask_app, port), daemon=True)
    server.start()

    # Wait for Flask to be ready
    for _ in range(20):
        try:
            with socket.create_connection((WEB_HOST, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)

    # Open native window
    window = webview.create_window(
        title="Research Taxonomy Library",
        url=f"http://{WEB_HOST}:{port}",
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
