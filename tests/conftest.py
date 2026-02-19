"""Shared test fixtures."""
import pytest

from config import generate_csrf_token
from storage.db import Database
from web.app import create_app


@pytest.fixture
def tmp_db(tmp_path):
    """Create a fresh Database backed by a temp file."""
    db_path = tmp_path / "test.db"
    db = Database(db_path=db_path)
    return db


@pytest.fixture
def project_id(tmp_db):
    """Create a test project and return its id."""
    return tmp_db.create_project(
        name="Test Project",
        purpose="Testing",
        seed_categories=["Cat A", "Cat B", "Cat C"],
    )


@pytest.fixture
def app(tmp_path):
    """Create a Flask test app with a temp database."""
    application = create_app()
    application.db = Database(db_path=tmp_path / "test.db")
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    """Flask test client that auto-sends CSRF token on mutating requests."""

    class CSRFClient:
        def __init__(self, inner):
            self._inner = inner
            self._csrf = generate_csrf_token()

        def get(self, *args, **kwargs):
            return self._inner.get(*args, **kwargs)

        def post(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-CSRF-Token"] = self._csrf
            return self._inner.post(*args, headers=headers, **kwargs)

        def put(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-CSRF-Token"] = self._csrf
            return self._inner.put(*args, headers=headers, **kwargs)

        def delete(self, *args, **kwargs):
            headers = kwargs.pop("headers", {})
            headers["X-CSRF-Token"] = self._csrf
            return self._inner.delete(*args, headers=headers, **kwargs)

    return CSRFClient(app.test_client())
