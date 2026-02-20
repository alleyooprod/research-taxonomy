"""Shared test fixtures for pytest suite.

Provides fixtures for:
- tmp_db: Fresh database instance per test
- project_id: Seeded project with 3 categories
- seeded_project: Project with categories AND companies pre-loaded
- app: Flask test app with isolated database
- client: CSRF-aware Flask test client
- raw_client: Flask test client WITHOUT CSRF (for security tests)
"""
import json
import pytest

from config import generate_csrf_token
from storage.db import Database
from web.app import create_app


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

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
def category_ids(tmp_db, project_id):
    """Return dict of {name: id} for all categories in the test project."""
    cats = tmp_db.get_categories(project_id=project_id)
    return {c["name"]: c["id"] for c in cats}


@pytest.fixture
def seeded_project(tmp_db, project_id, category_ids):
    """Project with categories AND sample companies pre-loaded.

    Returns dict with project_id, category_ids, company_ids.
    """
    companies = []
    sample_data = [
        {"url": "https://acme.com", "name": "Acme Corp",
         "what": "Enterprise SaaS platform", "target": "Large enterprises",
         "funding": "Series B", "funding_stage": "series_b",
         "geography": "North America", "hq_country": "US", "hq_city": "San Francisco",
         "employee_range": "51-200", "founded_year": 2018,
         "business_model": "b2b", "tags": json.dumps(["saas", "enterprise"])},
        {"url": "https://beta-health.com", "name": "Beta Health",
         "what": "Digital health monitoring", "target": "Patients",
         "funding": "Seed", "funding_stage": "seed",
         "geography": "Europe", "hq_country": "UK", "hq_city": "London",
         "employee_range": "11-50", "founded_year": 2021,
         "business_model": "b2c", "tags": json.dumps(["healthtech", "monitoring"])},
        {"url": "https://gamma-ai.com", "name": "Gamma AI",
         "what": "AI-powered diagnostics", "target": "Hospitals",
         "funding": "Series A", "funding_stage": "series_a",
         "geography": "North America", "hq_country": "US", "hq_city": "Boston",
         "employee_range": "11-50", "founded_year": 2020,
         "business_model": "b2b", "tags": json.dumps(["ai", "diagnostics"])},
        {"url": "https://delta-pharma.com", "name": "Delta Pharma",
         "what": "Drug discovery platform", "target": "Pharma companies",
         "funding": "Series C", "funding_stage": "growth",
         "geography": "Global", "hq_country": "US", "hq_city": "New York",
         "employee_range": "201-500", "founded_year": 2015,
         "business_model": "b2b", "tags": json.dumps(["pharma", "drug-discovery"])},
        {"url": "https://epsilon-fit.com", "name": "Epsilon Fitness",
         "what": "Consumer fitness app", "target": "Health-conscious consumers",
         "funding": "Bootstrapped", "funding_stage": "bootstrapped",
         "geography": "Global", "hq_country": "DE", "hq_city": "Berlin",
         "employee_range": "1-10", "founded_year": 2022,
         "business_model": "b2c", "tags": json.dumps(["fitness", "consumer"])},
    ]

    cat_names = list(category_ids.keys())
    for i, data in enumerate(sample_data):
        cat_name = cat_names[i % len(cat_names)]
        data["project_id"] = project_id
        data["category_id"] = category_ids[cat_name]
        cid = tmp_db.upsert_company(data)
        companies.append(cid)

    return {
        "project_id": project_id,
        "category_ids": category_ids,
        "company_ids": companies,
        "db": tmp_db,
    }


# ---------------------------------------------------------------------------
# Flask app fixtures
# ---------------------------------------------------------------------------

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
        def __init__(self, inner, flask_app):
            self._inner = inner
            self._app = flask_app
            self._csrf = generate_csrf_token()

        @property
        def db(self):
            return self._app.db

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

    return CSRFClient(app.test_client(), app)


@pytest.fixture
def raw_client(app):
    """Flask test client WITHOUT CSRF — for testing CSRF rejection."""
    return app.test_client()


# ---------------------------------------------------------------------------
# API helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api_project(client):
    """Create a project via the API and return its data.

    Returns dict with 'id', 'name', and the client for chaining.
    """
    r = client.post("/api/projects", json={
        "name": "API Test Project",
        "purpose": "Comprehensive API testing",
        "seed_categories": "Alpha\nBeta\nGamma",
    })
    data = r.get_json()
    return {"id": data["id"], "name": "API Test Project", "client": client}


@pytest.fixture
def api_project_with_companies(api_project):
    """Create a project with companies via API.

    Returns dict with project_id, company_ids, category info, and client.
    """
    client = api_project["client"]
    pid = api_project["id"]

    # Get taxonomy to find category IDs
    r = client.get(f"/api/taxonomy?project_id={pid}")
    cats = r.get_json()
    cat_id = cats[0]["id"] if cats else None

    company_ids = []
    for name, url in [
        ("Test Corp", "https://testcorp.com"),
        ("Demo Inc", "https://demo.com"),
        ("Sample Ltd", "https://sample.co.uk"),
    ]:
        r = client.post("/api/companies/add", json={
            "url": url, "name": name, "project_id": pid,
        })
        data = r.get_json()
        company_ids.append(data["id"])

        # Assign category
        if cat_id:
            client.post(f"/api/companies/{data['id']}", json={
                "category_id": cat_id, "project_id": pid,
            })

    return {
        "project_id": pid,
        "company_ids": company_ids,
        "category_id": cat_id,
        "categories": cats,
        "client": client,
    }
