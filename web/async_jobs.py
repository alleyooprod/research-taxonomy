"""Reusable helpers for the async-job-via-JSON-file pattern.

Many endpoints follow the same flow:
  1. Generate a short UUID
  2. Spawn a worker in a thread pool
  3. Write result to DATA_DIR / "{prefix}_{id}.json"
  4. A poll endpoint checks whether that file exists yet

This module centralises all of that boilerplate.
"""
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from config import DATA_DIR

logger = logging.getLogger(__name__)

# Shared thread pool with graceful shutdown support.
#
# NOTE: core/pipeline.py and web/blueprints/processing.py create their own
# short-lived ThreadPoolExecutors inside ``with`` blocks.  This is intentional:
#   - pipeline.py lives in core/ and may run outside the web app.
#   - processing._run_triage() already executes *inside* a thread from this
#     pool; submitting sub-work back to the same pool risks deadlock.
# Both scoped executors self-close after the ``with`` block completes.
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="async_job")


def make_job_id():
    """Generate a job identifier (16-char hex for brute-force resistance)."""
    return uuid.uuid4().hex[:16]


def start_async_job(prefix, work_fn, *args, **kwargs):
    """Submit *work_fn* to the thread pool and return the job id.

    *work_fn* receives ``(job_id, *args, **kwargs)`` and must call
    :func:`write_result` when finished.

    Returns the generated ``job_id`` (16-char hex string).
    """
    job_id = make_job_id()

    def _wrapper():
        try:
            work_fn(job_id, *args, **kwargs)
        except Exception as exc:
            logger.exception("Async job %s_%s failed", prefix, job_id)
            _ensure_result(prefix, job_id, {"status": "error", "error": str(exc)[:500]})

    _executor.submit(_wrapper)
    return job_id


def run_in_thread(fn, *args, **kwargs):
    """Fire-and-forget: run *fn* in the thread pool.

    Use this for jobs that poll via the database rather than JSON files.
    Unlike :func:`start_async_job`, this does NOT auto-generate an id
    or write a JSON result — the caller manages its own id/state.
    """
    def _wrapper():
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.exception("run_in_thread failed for %s", fn.__name__)

    _executor.submit(_wrapper)


def write_result(prefix, job_id, data):
    """Write *data* (dict) to the result file for this job (owner-only perms)."""
    path = DATA_DIR / f"{prefix}_{job_id}.json"
    path.write_text(json.dumps(data))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def poll_result(prefix, job_id, pending_extra=None):
    """Return the result dict, or ``{"status": "pending"}`` if not ready yet.

    *pending_extra* is an optional dict merged into the pending response.
    """
    # Validate job_id format to prevent path traversal
    if not job_id or not all(c in "0123456789abcdef" for c in job_id):
        return {"status": "error", "error": "Invalid job ID"}
    path = DATA_DIR / f"{prefix}_{job_id}.json"
    if not path.exists():
        resp = {"status": "pending"}
        if pending_extra:
            resp.update(pending_extra)
        return resp
    return json.loads(path.read_text())


def shutdown_pool(wait=True):
    """Gracefully shut down the thread pool. Called on app exit."""
    logger.info("Shutting down async job pool (wait=%s)", wait)
    _executor.shutdown(wait=wait)


# -- internal -----------------------------------------------------------------

def _ensure_result(prefix, job_id, data):
    """Write a result file only if one doesn't already exist."""
    path = DATA_DIR / f"{prefix}_{job_id}.json"
    if not path.exists():
        path.write_text(json.dumps(data))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
