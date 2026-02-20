"""ExtractionMixin — DB operations for the extraction pipeline.

Manages extraction jobs (AI analysis requests) and extraction results
(individual attribute values pending human review).
"""
import json
from datetime import datetime


class ExtractionMixin:
    """Database methods for extraction jobs and results."""

    # ── Extraction Jobs ──────────────────────────────────────────

    def create_extraction_job(self, project_id, entity_id, source_type="evidence",
                              evidence_id=None, source_ref=None):
        """Create a new extraction job record.

        Returns: job_id (int)
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO extraction_jobs
                   (project_id, entity_id, evidence_id, source_type, source_ref, status)
                   VALUES (?, ?, ?, ?, ?, 'pending')""",
                (project_id, entity_id, evidence_id, source_type, source_ref),
            )
            return cursor.lastrowid

    def update_extraction_job(self, job_id, **fields):
        """Update extraction job fields (status, model, cost_usd, etc.)."""
        allowed = {
            "status", "model", "cost_usd", "duration_ms",
            "result_count", "error", "completed_at",
        }
        safe = {k: v for k, v in fields.items() if k in allowed}
        if not safe:
            return
        set_clause = ", ".join(f"{k} = ?" for k in safe)
        values = list(safe.values()) + [job_id]
        with self._get_conn() as conn:
            conn.execute(
                f"UPDATE extraction_jobs SET {set_clause} WHERE id = ?",
                values,
            )

    def get_extraction_job(self, job_id):
        """Get a single extraction job by ID. Returns dict or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM extraction_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_extraction_jobs(self, project_id=None, entity_id=None,
                            status=None, limit=50, offset=0):
        """List extraction jobs with optional filters.

        Returns: list[dict]
        """
        clauses = []
        params = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = " AND ".join(clauses) if clauses else "1=1"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM extraction_jobs
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_extraction_job(self, job_id):
        """Delete a job and its results (CASCADE)."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM extraction_jobs WHERE id = ?", (job_id,))

    # ── Extraction Results ───────────────────────────────────────

    def create_extraction_result(self, job_id, entity_id, attr_slug,
                                 extracted_value, confidence=0.5,
                                 reasoning=None, source_evidence_id=None):
        """Create a single extraction result (pending review).

        Returns: result_id (int)
        """
        # Serialize complex values
        if isinstance(extracted_value, (dict, list)):
            extracted_value = json.dumps(extracted_value)
        elif isinstance(extracted_value, bool):
            extracted_value = "1" if extracted_value else "0"
        elif extracted_value is not None:
            extracted_value = str(extracted_value)

        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO extraction_results
                   (job_id, entity_id, attr_slug, extracted_value, confidence,
                    reasoning, source_evidence_id, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (job_id, entity_id, attr_slug, extracted_value, confidence,
                 reasoning, source_evidence_id),
            )
            return cursor.lastrowid

    def create_extraction_results_batch(self, job_id, entity_id, results,
                                        source_evidence_id=None):
        """Create multiple extraction results in one transaction.

        Args:
            results: list of dicts with keys: attr_slug, value, confidence, reasoning

        Returns: list of result_ids
        """
        ids = []
        with self._get_conn() as conn:
            for r in results:
                value = r.get("value")
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                elif isinstance(value, bool):
                    value = "1" if value else "0"
                elif value is not None:
                    value = str(value)

                cursor = conn.execute(
                    """INSERT INTO extraction_results
                       (job_id, entity_id, attr_slug, extracted_value, confidence,
                        reasoning, source_evidence_id, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                    (job_id, entity_id, r["attr_slug"], value,
                     r.get("confidence", 0.5), r.get("reasoning"),
                     source_evidence_id),
                )
                ids.append(cursor.lastrowid)
        return ids

    def get_extraction_result(self, result_id):
        """Get a single extraction result by ID. Returns dict or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM extraction_results WHERE id = ?", (result_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_extraction_results(self, entity_id=None, job_id=None,
                               status=None, attr_slug=None,
                               limit=100, offset=0):
        """List extraction results with optional filters.

        Returns: list[dict]
        """
        clauses = []
        params = []
        if entity_id is not None:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if attr_slug is not None:
            clauses.append("attr_slug = ?")
            params.append(attr_slug)

        where = " AND ".join(clauses) if clauses else "1=1"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            rows = conn.execute(
                f"""SELECT * FROM extraction_results
                    WHERE {where}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_extraction_queue(self, project_id, limit=100, offset=0):
        """Get pending extraction results for a project (review queue).

        Joins with extraction_jobs to filter by project, returns results
        with job and entity context.

        Returns: list[dict]
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT er.*, ej.project_id, ej.source_type, ej.source_ref,
                          e.name AS entity_name, e.type_slug AS entity_type
                   FROM extraction_results er
                   JOIN extraction_jobs ej ON ej.id = er.job_id
                   JOIN entities e ON e.id = er.entity_id
                   WHERE ej.project_id = ? AND er.status = 'pending'
                   ORDER BY er.confidence DESC, er.created_at ASC
                   LIMIT ? OFFSET ?""",
                (project_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def review_extraction_result(self, result_id, action, edited_value=None):
        """Review an extraction result: accept, reject, or edit.

        Args:
            result_id: ID of the extraction result
            action: 'accept' | 'reject' | 'edit'
            edited_value: new value if action is 'edit'

        Returns: True if updated, False if not found
        """
        now = datetime.now().isoformat()

        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM extraction_results WHERE id = ?", (result_id,)
            ).fetchone()
            if not row:
                return False

            if action == "accept":
                conn.execute(
                    """UPDATE extraction_results
                       SET status = 'accepted', reviewed_at = ?
                       WHERE id = ?""",
                    (now, result_id),
                )
                # Write the accepted value to entity attributes
                self._apply_extraction_result(conn, dict(row))

            elif action == "reject":
                conn.execute(
                    """UPDATE extraction_results
                       SET status = 'rejected', reviewed_at = ?
                       WHERE id = ?""",
                    (now, result_id),
                )

            elif action == "edit":
                # Serialize edited value
                if isinstance(edited_value, (dict, list)):
                    edited_value = json.dumps(edited_value)
                elif isinstance(edited_value, bool):
                    edited_value = "1" if edited_value else "0"
                elif edited_value is not None:
                    edited_value = str(edited_value)

                conn.execute(
                    """UPDATE extraction_results
                       SET status = 'edited', reviewed_value = ?,
                           reviewed_at = ?
                       WHERE id = ?""",
                    (edited_value, now, result_id),
                )
                # Write the edited value to entity attributes
                result_dict = dict(row)
                result_dict["extracted_value"] = edited_value
                self._apply_extraction_result(conn, result_dict)

            else:
                return False

            return True

    def _apply_extraction_result(self, conn, result):
        """Write an accepted/edited extraction result to entity attributes.

        Uses the internal _set_attribute pattern to avoid nested connection deadlock.
        """
        entity_id = result["entity_id"]
        attr_slug = result["attr_slug"]
        value = result.get("reviewed_value") or result["extracted_value"]
        confidence = result.get("confidence", 0.5)

        # Use internal method to avoid nested connection
        conn.execute(
            """INSERT INTO entity_attributes
               (entity_id, attr_slug, value, source, confidence, captured_at)
               VALUES (?, ?, ?, 'extraction', ?, datetime('now'))""",
            (entity_id, attr_slug, value, confidence),
        )

    def bulk_review_extraction_results(self, result_ids, action):
        """Bulk accept or reject extraction results.

        Args:
            result_ids: list of result IDs
            action: 'accept' | 'reject'

        Returns: count of updated results
        """
        if not result_ids or action not in ("accept", "reject"):
            return 0

        now = datetime.now().isoformat()
        count = 0

        with self._get_conn() as conn:
            for rid in result_ids:
                row = conn.execute(
                    "SELECT * FROM extraction_results WHERE id = ? AND status = 'pending'",
                    (rid,),
                ).fetchone()
                if not row:
                    continue

                new_status = "accepted" if action == "accept" else "rejected"
                conn.execute(
                    """UPDATE extraction_results
                       SET status = ?, reviewed_at = ?
                       WHERE id = ?""",
                    (new_status, now, rid),
                )

                if action == "accept":
                    self._apply_extraction_result(conn, dict(row))

                count += 1

        return count

    def get_extraction_stats(self, project_id):
        """Get extraction statistics for a project.

        Returns: dict with counts by status, total jobs, etc.
        """
        with self._get_conn() as conn:
            # Job counts
            job_rows = conn.execute(
                """SELECT status, COUNT(*) as cnt
                   FROM extraction_jobs WHERE project_id = ?
                   GROUP BY status""",
                (project_id,),
            ).fetchall()
            jobs_by_status = {r["status"]: r["cnt"] for r in job_rows}

            # Result counts
            result_rows = conn.execute(
                """SELECT er.status, COUNT(*) as cnt
                   FROM extraction_results er
                   JOIN extraction_jobs ej ON ej.id = er.job_id
                   WHERE ej.project_id = ?
                   GROUP BY er.status""",
                (project_id,),
            ).fetchall()
            results_by_status = {r["status"]: r["cnt"] for r in result_rows}

            # Total cost
            cost_row = conn.execute(
                """SELECT COALESCE(SUM(cost_usd), 0) as total_cost
                   FROM extraction_jobs WHERE project_id = ?""",
                (project_id,),
            ).fetchone()

            return {
                "jobs": jobs_by_status,
                "results": results_by_status,
                "total_jobs": sum(jobs_by_status.values()),
                "total_results": sum(results_by_status.values()),
                "pending_review": results_by_status.get("pending", 0),
                "total_cost_usd": round(cost_row["total_cost"], 4),
            }
