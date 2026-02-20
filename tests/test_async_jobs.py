"""Tests for the async job helper module."""
import json
import time
import pytest

from web.async_jobs import (
    make_job_id, start_async_job, write_result, poll_result, run_in_thread,
)
from config import DATA_DIR

pytestmark = [pytest.mark.async_jobs]


class TestMakeJobId:
    def test_returns_16_char_hex(self):
        jid = make_job_id()
        assert len(jid) == 16
        int(jid, 16)  # should not raise

    def test_unique(self):
        ids = {make_job_id() for _ in range(100)}
        assert len(ids) == 100


class TestWriteAndPoll:
    def test_poll_pending_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("web.async_jobs.DATA_DIR", tmp_path)
        result = poll_result("test", "abcdef0123456789")
        assert result == {"status": "pending"}

    def test_write_then_poll(self, tmp_path, monkeypatch):
        monkeypatch.setattr("web.async_jobs.DATA_DIR", tmp_path)
        write_result("test", "abc123", {"status": "complete", "value": 42})
        result = poll_result("test", "abc123")
        assert result["status"] == "complete"
        assert result["value"] == 42

    def test_pending_extra(self, tmp_path, monkeypatch):
        monkeypatch.setattr("web.async_jobs.DATA_DIR", tmp_path)
        result = poll_result("test", "abcdef0123456789", pending_extra={"hint": "wait"})
        assert result["status"] == "pending"
        assert result["hint"] == "wait"

    def test_rejects_invalid_job_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr("web.async_jobs.DATA_DIR", tmp_path)
        result = poll_result("test", "../etc/passwd")
        assert result["status"] == "error"
        assert "Invalid" in result["error"]

    def test_rejects_empty_job_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr("web.async_jobs.DATA_DIR", tmp_path)
        result = poll_result("test", "")
        assert result["status"] == "error"

    def test_rejects_non_hex_job_id(self, tmp_path, monkeypatch):
        monkeypatch.setattr("web.async_jobs.DATA_DIR", tmp_path)
        result = poll_result("test", "GGGG")
        assert result["status"] == "error"


class TestStartAsyncJob:
    def test_returns_job_id_and_runs_work(self, tmp_path, monkeypatch):
        monkeypatch.setattr("web.async_jobs.DATA_DIR", tmp_path)

        def worker(job_id, x, y):
            write_result("calc", job_id, {"status": "complete", "sum": x + y})

        jid = start_async_job("calc", worker, 3, 4)
        assert len(jid) == 16

        # Wait for thread to finish
        for _ in range(50):
            result = poll_result("calc", jid)
            if result["status"] != "pending":
                break
            time.sleep(0.05)

        assert result["status"] == "complete"
        assert result["sum"] == 7

    def test_safety_net_on_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr("web.async_jobs.DATA_DIR", tmp_path)

        def bad_worker(job_id):
            raise ValueError("boom")

        jid = start_async_job("fail", bad_worker)

        for _ in range(50):
            result = poll_result("fail", jid)
            if result["status"] != "pending":
                break
            time.sleep(0.05)

        assert result["status"] == "error"
        assert "boom" in result["error"]


class TestRunInThread:
    def test_runs_function(self):
        results = []

        def worker(val):
            results.append(val)

        run_in_thread(worker, 42)
        time.sleep(0.1)
        assert results == [42]
