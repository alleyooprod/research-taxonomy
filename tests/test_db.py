"""Tests for the database layer (projects, categories, companies, jobs)."""
import json
import pytest

pytestmark = [pytest.mark.db]


class TestProjects:
    def test_create_project(self, tmp_db):
        pid = tmp_db.create_project("My Project", purpose="Research",
                                     seed_categories=["Alpha", "Beta"])
        assert pid is not None
        project = tmp_db.get_project(pid)
        assert project["name"] == "My Project"
        assert project["slug"] == "my-project"

    def test_create_project_seeds_categories(self, tmp_db):
        pid = tmp_db.create_project("Seed Test",
                                     seed_categories=["X", "Y", "Z"])
        cats = tmp_db.get_categories(project_id=pid)
        names = {c["name"] for c in cats}
        assert {"X", "Y", "Z"} <= names

    def test_get_projects_list(self, tmp_db):
        tmp_db.create_project("P1")
        tmp_db.create_project("P2")
        projects = tmp_db.get_projects()
        assert len(projects) >= 2

    def test_update_project(self, tmp_db):
        pid = tmp_db.create_project("Update Me")
        tmp_db.update_project(pid, {"purpose": "New purpose"})
        project = tmp_db.get_project(pid)
        assert project["purpose"] == "New purpose"


class TestCategories:
    def test_add_and_get_category(self, tmp_db, project_id):
        cid = tmp_db.add_category("New Cat", project_id=project_id)
        assert cid is not None
        cat = tmp_db.get_category_by_name("New Cat", project_id=project_id)
        assert cat is not None
        assert cat["name"] == "New Cat"

    def test_rename_category(self, tmp_db, project_id):
        tmp_db.add_category("Old Name", project_id=project_id)
        result = tmp_db.rename_category("Old Name", "New Name",
                                         project_id=project_id)
        assert result is True
        assert tmp_db.get_category_by_name("New Name",
                                            project_id=project_id) is not None
        assert tmp_db.get_category_by_name("Old Name",
                                            project_id=project_id) is None

    def test_merge_categories(self, tmp_db, project_id):
        tmp_db.add_category("Source", project_id=project_id)
        tmp_db.add_category("Target", project_id=project_id)
        result = tmp_db.merge_categories("Source", "Target",
                                          project_id=project_id)
        assert result is True
        # Source should be inactive
        cats = tmp_db.get_categories(project_id=project_id, active_only=True)
        names = {c["name"] for c in cats}
        assert "Source" not in names

    def test_category_stats(self, tmp_db, project_id):
        stats = tmp_db.get_category_stats(project_id=project_id)
        assert isinstance(stats, list)
        assert len(stats) >= 3  # from seed categories


class TestCompanies:
    def _make(self, tmp_db, project_id, url, name, **extra):
        cats = tmp_db.get_categories(project_id=project_id)
        data = {"project_id": project_id, "url": url, "name": name,
                "category_id": cats[0]["id"], **extra}
        return tmp_db.upsert_company(data)

    def test_upsert_and_get_company(self, tmp_db, project_id):
        cid = self._make(tmp_db, project_id, "https://example.com",
                         "Example Inc", what="Does things", target="Everyone")
        assert cid is not None
        company = tmp_db.get_company(cid)
        assert company["name"] == "Example Inc"
        assert company["what"] == "Does things"

    def test_get_companies_with_search(self, tmp_db, project_id):
        self._make(tmp_db, project_id, "https://a.com", "Alpha Corp")
        self._make(tmp_db, project_id, "https://b.com", "Beta LLC")
        results = tmp_db.get_companies(project_id=project_id, search="Alpha")
        assert len(results) == 1
        assert results[0]["name"] == "Alpha Corp"

    def test_star_company(self, tmp_db, project_id):
        cid = self._make(tmp_db, project_id, "https://s.com", "Star Co")
        result = tmp_db.toggle_star(cid)
        assert result == 1
        result = tmp_db.toggle_star(cid)
        assert result == 0

    def test_delete_company(self, tmp_db, project_id):
        cid = self._make(tmp_db, project_id, "https://d.com", "Delete Me")
        tmp_db.delete_company(cid)
        # Default get_company now filters soft-deleted, so it returns None
        company = tmp_db.get_company(cid)
        assert company is None

        # With include_deleted=True we can still see it
        company = tmp_db.get_company(cid, include_deleted=True)
        assert company is not None
        assert company["is_deleted"] == 1

        # Should not appear in normal listing
        companies = tmp_db.get_companies(project_id=project_id)
        assert all(c["id"] != cid for c in companies)


class TestJobs:
    def test_create_and_get_jobs(self, tmp_db, project_id):
        batch_id = "test-batch"
        urls = [("https://a.com", "https://a.com"),
                ("https://b.com", "https://b.com")]
        tmp_db.create_jobs(batch_id, urls, project_id=project_id)

        pending = tmp_db.get_pending_jobs(batch_id)
        assert len(pending) == 2

    def test_batch_summary(self, tmp_db, project_id):
        batch_id = "sum-batch"
        urls = [("https://x.com", "https://x.com")]
        tmp_db.create_jobs(batch_id, urls, project_id=project_id)

        summary = tmp_db.get_batch_summary(batch_id)
        assert summary["total"] == 1
        assert summary["pending"] == 1

    def test_update_job_status(self, tmp_db, project_id):
        batch_id = "upd-batch"
        urls = [("https://u.com", "https://u.com")]
        tmp_db.create_jobs(batch_id, urls, project_id=project_id)

        jobs = tmp_db.get_pending_jobs(batch_id)
        tmp_db.update_job(jobs[0]["id"], "done")

        summary = tmp_db.get_batch_summary(batch_id)
        assert summary["done"] == 1
        assert summary["pending"] == 0


class TestTriage:
    def test_save_and_get_triage(self, tmp_db, project_id):
        batch_id = "triage-batch"
        results = [{
            "original_url": "https://t.com",
            "resolved_url": "https://t.com",
            "status": "valid",
            "reason": "OK",
            "title": "Test",
            "meta_description": "",
            "scraped_text_preview": "",
            "is_accessible": True,
        }]
        tmp_db.save_triage_results(batch_id, results, project_id=project_id)
        fetched = tmp_db.get_triage_results(batch_id)
        assert len(fetched) == 1
        assert fetched[0]["status"] == "valid"
