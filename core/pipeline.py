"""Orchestrator: manages the full processing pipeline with concurrency."""
import json
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from config import DEFAULT_WORKERS, DEFAULT_MODEL, MAX_RETRIES, SUB_BATCH_SIZE, RESEARCH_TIMEOUT_RETRIES
from core.classifier import build_taxonomy_tree_string, classify_company
from core.researcher import research_company
from core.taxonomy import evolve_taxonomy
from core.url_resolver import resolve_and_validate
from storage.db import Database
from storage.export import export_json, export_markdown


def _process_one_company(url, source_url, model, taxonomy_tree):
    """Process a single company: research + classify.

    This runs in a thread worker. The heavy lifting is done via subprocess
    calls to the Claude CLI, so threads are sufficient (I/O-bound work).
    Returns (url, result_dict) or (url, error_string).
    Automatically retries on timeout up to RESEARCH_TIMEOUT_RETRIES times.
    """
    last_error = None
    for attempt in range(1 + RESEARCH_TIMEOUT_RETRIES):
        try:
            # Stage 2: Deep research
            research = research_company(url, model=model)

            # Stage 3: Classification
            classification = classify_company(research, taxonomy_tree, model=model)

            return (url, {
                "research": research,
                "classification": classification,
                "source_url": source_url,
            })

        except subprocess.TimeoutExpired:
            last_error = f"Timeout: research exceeded time limit (attempt {attempt + 1}/{1 + RESEARCH_TIMEOUT_RETRIES})"
            if attempt < RESEARCH_TIMEOUT_RETRIES:
                continue  # retry
            return (url, last_error)

        except Exception as e:
            return (url, f"Error: {e}")


class Pipeline:
    def __init__(self, db=None, workers=DEFAULT_WORKERS, model=DEFAULT_MODEL, project_id=None):
        self.db = db or Database()
        self.workers = workers
        self.model = model
        self.project_id = project_id

    def run(self, urls, batch_id, force=False, dry_run=False):
        """Full pipeline: resolve -> sub-batch research+classify -> evolve -> export."""
        print(f"\n{'='*60}")
        print(f"  Batch {batch_id}: {len(urls)} URLs")
        print(f"  Model: {self.model} | Workers: {self.workers}")
        print(f"{'='*60}\n")

        # Stage 1: Resolve and validate URLs
        print("[1/4] Resolving and validating URLs...")
        resolved = []
        existing_urls = self.db.get_all_company_urls(project_id=self.project_id)

        for i, url in enumerate(urls, 1):
            result = resolve_and_validate(url)
            canonical = result["url"]

            if not force and canonical in existing_urls:
                print(f"  ({i}/{len(urls)}) SKIP (already exists): {canonical}")
                continue

            if result["status"] == "error":
                print(f"  ({i}/{len(urls)}) FAIL: {url} -> {result['reason']}")
                continue

            if result["status"] == "needs_review":
                print(f"  ({i}/{len(urls)}) WARN: {url} -> using as-is")

            resolved.append((result["source_url"], result["url"]))
            print(f"  ({i}/{len(urls)}) OK: {result['url']}")

        if not resolved:
            print("\nNo new URLs to process.")
            return

        print(f"\n  {len(resolved)} URLs ready for processing.")

        if dry_run:
            print("\n  DRY RUN - stopping before research.")
            return

        # Create jobs in DB
        self.db.create_jobs(batch_id, resolved, project_id=self.project_id)

        # Build taxonomy tree string for classification
        taxonomy_tree = build_taxonomy_tree_string(self.db, project_id=self.project_id)

        # Stage 2+3: Research + classify in sub-batches
        start_time = time.time()
        total_success = 0
        total_errors = 0

        if len(resolved) <= SUB_BATCH_SIZE:
            # Single batch
            s, e = self._process_sub_batch(resolved, batch_id, taxonomy_tree, 1, 1)
            total_success += s
            total_errors += e
        else:
            # Split into sub-batches of SUB_BATCH_SIZE
            sub_batches = [
                resolved[i : i + SUB_BATCH_SIZE]
                for i in range(0, len(resolved), SUB_BATCH_SIZE)
            ]
            total_sub = len(sub_batches)
            print(f"\n  Splitting {len(resolved)} URLs into {total_sub} sub-batches of {SUB_BATCH_SIZE}\n")

            for idx, sub_batch in enumerate(sub_batches, 1):
                s, e = self._process_sub_batch(
                    sub_batch, batch_id, taxonomy_tree, idx, total_sub
                )
                total_success += s
                total_errors += e

        elapsed = time.time() - start_time
        print(f"\n  Total: {total_success} OK, {total_errors} errors in {elapsed:.0f}s")

        # Stage 4: Taxonomy evolution
        if total_success > 0:
            print(f"\n[3/4] Evolving taxonomy...")
            changes = evolve_taxonomy(self.db, batch_id, model="claude-opus-4-6",
                                      project_id=self.project_id)
            if changes:
                print(f"  {len(changes)} taxonomy changes applied.")
            else:
                print(f"  No taxonomy changes.")

        # Stage 5: Export
        print(f"\n[4/4] Exporting data...")
        json_path = export_json(self.db, project_id=self.project_id)
        md_path = export_markdown(self.db, project_id=self.project_id)
        print(f"  JSON: {json_path}")
        print(f"  Markdown: {md_path}")

        # Summary
        stats = self.db.get_stats(project_id=self.project_id)
        print(f"\n{'='*60}")
        print(f"  DONE. Total companies: {stats['total_companies']}")
        print(f"  Total categories: {stats['total_categories']}")
        print(f"{'='*60}\n")

    def _process_sub_batch(self, resolved, batch_id, taxonomy_tree, sub_num, total_sub):
        """Process a single sub-batch of URLs through research+classify."""
        print(f"[2/4] Sub-batch {sub_num}/{total_sub}: {len(resolved)} URLs "
              f"({self.workers} workers)...")

        jobs = self.db.get_pending_jobs(batch_id)
        url_to_job = {j["url"]: j for j in jobs}
        success_count = 0
        error_count = 0

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {}
            for source_url, url in resolved:
                future = executor.submit(
                    _process_one_company, url, source_url, self.model, taxonomy_tree
                )
                futures[future] = url

            for future in as_completed(futures):
                url = futures[future]
                job = url_to_job.get(url)

                try:
                    result_url, result = future.result()

                    if isinstance(result, str) and result.startswith("Error:"):
                        error_count += 1
                        print(f"  FAIL: {url}")
                        print(f"        {result}")
                        if job:
                            self.db.update_job(job["id"], "error", error_message=result)
                    else:
                        classification = result.get("classification", {})
                        if classification.get("skip"):
                            name = result["research"].get("name", "Unknown")
                            reason = classification.get("skip_reason", "Out of scope")
                            print(f"  SKIP: {name} — {reason}")
                            if job:
                                self.db.update_job(
                                    job["id"], "done",
                                    error_message=f"Skipped: {reason}",
                                )
                            success_count += 1
                        else:
                            company_id = self._save_result(result)
                            success_count += 1
                            name = result["research"].get("name", "Unknown")
                            cat = classification.get("category", "?")
                            print(f"  OK: {name} -> {cat}")
                            if job:
                                self.db.update_job(job["id"], "done", company_id=company_id)

                except Exception as e:
                    error_count += 1
                    print(f"  FAIL: {url}")
                    print(f"        {e}")
                    if job:
                        self.db.update_job(job["id"], "error", error_message=str(e))

        print(f"  Sub-batch {sub_num}: {success_count} OK, {error_count} errors")
        return success_count, error_count

    def _save_result(self, result):
        """Save a research+classification result to the database."""
        research = result["research"]
        classification = result["classification"]

        # Resolve category ID
        cat_name = classification.get("category", "Uncategorized")
        is_new = classification.get("is_new_category", False)

        if is_new:
            self.db.add_category(cat_name, project_id=self.project_id)

        category = self.db.get_category_by_name(cat_name, project_id=self.project_id)
        category_id = category["id"] if category else None

        # Resolve subcategory
        sub_name = classification.get("subcategory")
        subcategory_id = None
        if sub_name and category_id:
            self.db.add_category(sub_name, parent_id=category_id, project_id=self.project_id)
            sub = self.db.get_category_by_name(sub_name, project_id=self.project_id)
            subcategory_id = sub["id"] if sub else None

        # Build company record
        company_data = {
            "project_id": self.project_id,
            "name": research.get("name", "Unknown"),
            "url": research.get("url", ""),
            "what": research.get("what"),
            "target": research.get("target"),
            "products": research.get("products"),
            "funding": research.get("funding"),
            "geography": research.get("geography"),
            "tam": research.get("tam"),
            "tags": research.get("tags", []),
            "category_id": category_id,
            "subcategory_id": subcategory_id,
            "confidence_score": classification.get("confidence", 0),
            "raw_research": json.dumps(research),
            "source_url": result.get("source_url"),
            # Firmographic fields from research
            "employee_range": research.get("employee_range"),
            "founded_year": research.get("founded_year"),
            "funding_stage": research.get("funding_stage"),
            "total_funding_usd": research.get("total_funding_usd"),
            "hq_city": research.get("hq_city"),
            "hq_country": research.get("hq_country"),
            "linkedin_url": research.get("linkedin_url"),
            # Pricing fields from research
            "pricing_model": research.get("pricing_model"),
            "pricing_b2c_low": research.get("pricing_b2c_low"),
            "pricing_b2c_high": research.get("pricing_b2c_high"),
            "pricing_b2b_low": research.get("pricing_b2b_low"),
            "pricing_b2b_high": research.get("pricing_b2b_high"),
            "has_free_tier": research.get("has_free_tier"),
            "revenue_model": research.get("revenue_model"),
            "pricing_tiers": research.get("pricing_tiers"),
            "pricing_notes": research.get("pricing_notes"),
        }

        company_id = self.db.upsert_company(company_data)

        # Track source URLs
        source_url = result.get("source_url")
        company_url = research.get("url", "")
        if company_url:
            self.db.add_company_source(company_id, company_url, "research")
        if source_url and source_url != company_url:
            self.db.add_company_source(company_id, source_url, "research")

        return company_id

    def resume(self, batch_id):
        """Resume processing for an incomplete batch."""
        pending = self.db.get_pending_jobs(batch_id)
        if not pending:
            print(f"No pending jobs for batch {batch_id}.")
            return

        print(f"Resuming batch {batch_id}: {len(pending)} remaining jobs")
        urls = [(j["source_url"] or j["url"], j["url"]) for j in pending]
        taxonomy_tree = build_taxonomy_tree_string(self.db, project_id=self.project_id)

        # Use sub-batching for resume too
        if len(urls) <= SUB_BATCH_SIZE:
            self._process_sub_batch(urls, batch_id, taxonomy_tree, 1, 1)
        else:
            sub_batches = [
                urls[i : i + SUB_BATCH_SIZE]
                for i in range(0, len(urls), SUB_BATCH_SIZE)
            ]
            for idx, sub in enumerate(sub_batches, 1):
                self._process_sub_batch(sub, batch_id, taxonomy_tree, idx, len(sub_batches))

        # Evolve + export
        evolve_taxonomy(self.db, batch_id, model="claude-opus-4-6",
                        project_id=self.project_id)
        export_json(self.db, project_id=self.project_id)
        export_markdown(self.db, project_id=self.project_id)

    def retry_failed(self, batch_id=None):
        """Retry all failed jobs."""
        failed = self.db.get_failed_jobs(batch_id)
        if not failed:
            print("No failed jobs to retry.")
            return

        failed_under_limit = [j for j in failed if j["attempts"] < MAX_RETRIES]
        if not failed_under_limit:
            print(f"All {len(failed)} failed jobs have exceeded max retries ({MAX_RETRIES}).")
            return

        print(f"Retrying {len(failed_under_limit)} failed jobs...")
        taxonomy_tree = build_taxonomy_tree_string(self.db)

        for job in failed_under_limit:
            url = job["url"]
            print(f"  Retrying: {url} (attempt {job['attempts'] + 1})")
            try:
                result_url, result = _process_one_company(
                    url, job["source_url"], self.model, taxonomy_tree
                )
                if isinstance(result, str) and result.startswith("Error:"):
                    self.db.update_job(job["id"], "error", error_message=result)
                    print(f"    FAIL: {result}")
                else:
                    company_id = self._save_result(result)
                    self.db.update_job(job["id"], "done", company_id=company_id)
                    print(f"    OK: {result['research'].get('name', 'Unknown')}")
            except Exception as e:
                self.db.update_job(job["id"], "error", error_message=str(e))
                print(f"    FAIL: {e}")

    def reclassify_all(self):
        """Re-classify all companies against the current taxonomy."""
        companies = self.db.get_companies(project_id=self.project_id)
        taxonomy_tree = build_taxonomy_tree_string(self.db, project_id=self.project_id)
        print(f"Re-classifying {len(companies)} companies...")

        for company in companies:
            try:
                raw = company.get("raw_research")
                if not raw:
                    print(f"  SKIP (no raw research): {company['name']}")
                    continue

                research = json.loads(raw)
                classification = classify_company(research, taxonomy_tree, model=self.model)

                cat_name = classification.get("category", "Uncategorized")
                if classification.get("is_new_category"):
                    self.db.add_category(cat_name, project_id=self.project_id)

                category = self.db.get_category_by_name(cat_name, project_id=self.project_id)
                category_id = category["id"] if category else None

                sub_name = classification.get("subcategory")
                subcategory_id = None
                if sub_name and category_id:
                    self.db.add_category(sub_name, parent_id=category_id, project_id=self.project_id)
                    sub = self.db.get_category_by_name(sub_name, project_id=self.project_id)
                    subcategory_id = sub["id"] if sub else None

                self.db.update_company(company["id"], {
                    "category_id": category_id,
                    "subcategory_id": subcategory_id,
                    "confidence_score": classification.get("confidence", 0),
                })
                print(f"  OK: {company['name']} -> {cat_name}")

            except Exception as e:
                print(f"  FAIL: {company['name']} -> {e}")

        export_json(self.db, project_id=self.project_id)
        export_markdown(self.db, project_id=self.project_id)
