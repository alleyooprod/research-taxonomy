"""Auto-commit and push to main after meaningful events."""
import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from config import BASE_DIR

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()


def _run_git(*args, timeout=30):
    """Run a git command in the project directory. Returns (ok, stdout)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning("git %s timed out", args[0])
        return False, ""
    except FileNotFoundError:
        logger.warning("git not found on PATH")
        return False, ""


def has_changes():
    """Check whether the working tree has uncommitted changes."""
    ok, output = _run_git("status", "--porcelain")
    return ok and bool(output)


def sync_to_git(message=None):
    """Stage all changes, commit, and push to origin main.

    This is safe to call from any thread — a lock prevents concurrent runs.
    Silently does nothing if there are no changes or git is unavailable.
    """
    if not _sync_lock.acquire(blocking=False):
        return  # another sync is already running

    try:
        if not has_changes():
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_msg = f"{message or 'Auto-save'} [{timestamp}]"

        # Stage everything
        ok, _ = _run_git("add", "-A")
        if not ok:
            logger.error("git add failed")
            return

        # Commit
        ok, _ = _run_git("commit", "-m", commit_msg)
        if not ok:
            logger.error("git commit failed")
            return

        # Push (non-blocking with longer timeout for slow networks)
        ok, _ = _run_git("push", "origin", "main", timeout=60)
        if not ok:
            logger.warning("git push failed — changes committed locally")

    except Exception:
        logger.exception("Unexpected error during git sync")
    finally:
        _sync_lock.release()


def sync_to_git_async(message=None):
    """Run sync_to_git in a background thread so it never blocks the UI."""
    thread = threading.Thread(
        target=sync_to_git,
        args=(message,),
        daemon=True,
    )
    thread.start()
