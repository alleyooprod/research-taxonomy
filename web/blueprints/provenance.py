"""Evidence Provenance API — trace data points back to their source evidence.

Every extracted attribute, every report claim, and every insight should link
back to the evidence that supports it.  This module provides the API to trace,
query, and present these provenance chains.

All endpoints are read-only (GET) and operate over existing tables:
    entity_attributes, extraction_results, extraction_jobs, evidence, entities

Endpoints:
    GET /api/provenance/attribute/<id>                — Trace single attribute
    GET /api/provenance/entity/<id>                   — Entity provenance summary
    GET /api/provenance/entity/<id>/evidence          — Evidence -> attribute map
    GET /api/provenance/project/<id>/coverage          — Project coverage stats
    GET /api/provenance/project/<id>/sources           — All unique source URLs
    GET /api/provenance/search                         — Search attributes by value
    GET /api/provenance/report/<id>/claims             — Report claim -> evidence links
    GET /api/provenance/stats                          — Quick provenance stats
"""
import json

from flask import Blueprint, request, jsonify, current_app
from loguru import logger

from ._utils import (
    require_project_id as _require_project_id,
    parse_json_field as _parse_json_field,
)

provenance_bp = Blueprint("provenance", __name__)


# ── Helpers ──────────────────────────────────────────────────


def _table_exists(conn, table_name):
    """Check whether a table exists in the current database."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


# ── 1. Trace Single Attribute ────────────────────────────────

@provenance_bp.route("/api/provenance/attribute/<int:attr_id>")
def trace_attribute(attr_id):
    """Trace a single entity attribute back to its source evidence.

    Returns the full chain:
        attribute -> extraction_result -> extraction_job -> evidence -> URL

    If source is 'manual', chain is ["attribute", "manual"].
    If source is 'sync', chain is ["attribute", "sync"].
    """
    db = current_app.db

    with db._get_conn() as conn:
        # 1. Look up the attribute
        attr_row = conn.execute(
            """SELECT id, entity_id, attr_slug, value, source,
                      confidence, captured_at, snapshot_id
               FROM entity_attributes WHERE id = ?""",
            (attr_id,),
        ).fetchone()

        if not attr_row:
            return jsonify({"error": f"Attribute {attr_id} not found"}), 404

        attr = dict(attr_row)
        result = {
            "attribute": attr,
            "extraction": None,
            "evidence": None,
            "chain": ["attribute"],
            "source_url": None,
        }

        source = attr.get("source", "manual")

        # Non-extraction sources — short chain
        if source != "extraction":
            result["chain"].append(source or "manual")
            return jsonify(result)

        # 2. Find matching extraction_result
        if not _table_exists(conn, "extraction_results"):
            result["chain"].append("extraction_missing")
            return jsonify(result)

        # Match by entity_id + attr_slug + value, closest in time to captured_at
        er_row = conn.execute(
            """SELECT er.id AS result_id, er.job_id, er.extracted_value,
                      er.confidence AS extraction_confidence,
                      er.status, er.reviewed_value, er.reasoning,
                      er.source_evidence_id, er.created_at AS extraction_created_at
               FROM extraction_results er
               WHERE er.entity_id = ? AND er.attr_slug = ?
                 AND er.status IN ('accepted', 'edited')
               ORDER BY ABS(
                   julianday(er.created_at) - julianday(?)
               ) ASC
               LIMIT 1""",
            (attr["entity_id"], attr["attr_slug"], attr["captured_at"]),
        ).fetchone()

        if not er_row:
            result["chain"].append("extraction")
            return jsonify(result)

        extraction = dict(er_row)

        # 3. Get the extraction_job for context
        job_row = None
        if _table_exists(conn, "extraction_jobs") and extraction.get("job_id"):
            job_row = conn.execute(
                """SELECT ej.id AS job_id, ej.evidence_id, ej.source_type,
                          ej.source_ref, ej.model,
                          ej.status AS job_status
                   FROM extraction_jobs ej
                   WHERE ej.id = ?""",
                (extraction["job_id"],),
            ).fetchone()

        extractor_type = None
        job_evidence_id = None
        if job_row:
            job_dict = dict(job_row)
            extractor_type = job_dict.get("source_type")
            job_evidence_id = job_dict.get("evidence_id")

        result["extraction"] = {
            "result_id": extraction["result_id"],
            "job_id": extraction["job_id"],
            "extractor_type": extractor_type,
            "extracted_value": extraction["extracted_value"],
            "status": extraction["status"],
        }
        result["chain"].append("extraction")

        # 4. Resolve evidence — prefer source_evidence_id on the result,
        #    then fall back to evidence_id on the job
        evidence_id = extraction.get("source_evidence_id") or job_evidence_id

        if evidence_id:
            ev_row = conn.execute(
                """SELECT id, evidence_type, file_path, source_url,
                          source_name, captured_at
                   FROM evidence WHERE id = ?""",
                (evidence_id,),
            ).fetchone()

            if ev_row:
                ev = dict(ev_row)
                result["evidence"] = {
                    "id": ev["id"],
                    "evidence_type": ev["evidence_type"],
                    "filename": ev.get("file_path", "").rsplit("/", 1)[-1] if ev.get("file_path") else None,
                    "original_url": ev.get("source_url"),
                    "captured_at": ev["captured_at"],
                }
                result["chain"].append("evidence")

                if ev.get("source_url"):
                    result["chain"].append("url")
                    result["source_url"] = ev["source_url"]

    return jsonify(result)


# ── 2. Entity Provenance Summary ─────────────────────────────

@provenance_bp.route("/api/provenance/entity/<int:entity_id>")
def entity_provenance(entity_id):
    """Get provenance summary for all current attributes of an entity.

    Returns coverage stats: how many attributes are backed by evidence,
    and a per-attribute provenance summary.
    """
    db = current_app.db

    with db._get_conn() as conn:
        # Verify entity exists
        entity_row = conn.execute(
            "SELECT id, name, type_slug, project_id FROM entities WHERE id = ? AND is_deleted = 0",
            (entity_id,),
        ).fetchone()

        if not entity_row:
            return jsonify({"error": f"Entity {entity_id} not found"}), 404

        entity_name = entity_row["name"]
        project_id = entity_row["project_id"]

        # Get current attributes (most recent per attr_slug)
        attr_rows = conn.execute(
            """SELECT ea.id, ea.attr_slug, ea.value, ea.source,
                      ea.confidence, ea.captured_at
               FROM entity_attributes ea
               WHERE ea.entity_id = ?
                 AND ea.id IN (
                     SELECT MAX(id) FROM entity_attributes
                     WHERE entity_id = ?
                     GROUP BY attr_slug
                 )
               ORDER BY ea.attr_slug""",
            (entity_id, entity_id),
        ).fetchall()

        has_extraction_tables = (
            _table_exists(conn, "extraction_results")
            and _table_exists(conn, "extraction_jobs")
        )

        attributes = []
        with_evidence = 0

        for attr in attr_rows:
            attr_dict = dict(attr)
            has_ev = False
            evidence_type = None
            source_url = None
            chain_length = 1  # at least the attribute itself

            if attr_dict["source"] == "extraction" and has_extraction_tables:
                # Try to find linked evidence via extraction chain
                er_row = conn.execute(
                    """SELECT er.source_evidence_id, ej.evidence_id AS job_evidence_id
                       FROM extraction_results er
                       JOIN extraction_jobs ej ON ej.id = er.job_id
                       WHERE er.entity_id = ? AND er.attr_slug = ?
                         AND er.status IN ('accepted', 'edited')
                       ORDER BY ABS(
                           julianday(er.created_at) - julianday(?)
                       ) ASC
                       LIMIT 1""",
                    (entity_id, attr_dict["attr_slug"], attr_dict["captured_at"]),
                ).fetchone()

                if er_row:
                    chain_length = 2  # attribute + extraction
                    ev_id = er_row["source_evidence_id"] or er_row["job_evidence_id"]
                    if ev_id:
                        ev = conn.execute(
                            "SELECT evidence_type, source_url FROM evidence WHERE id = ?",
                            (ev_id,),
                        ).fetchone()
                        if ev:
                            has_ev = True
                            evidence_type = ev["evidence_type"]
                            source_url = ev["source_url"]
                            chain_length = 4 if source_url else 3

            if has_ev:
                with_evidence += 1

            attributes.append({
                "attr_slug": attr_dict["attr_slug"],
                "value": attr_dict["value"],
                "source": attr_dict["source"],
                "has_evidence": has_ev,
                "evidence_type": evidence_type,
                "source_url": source_url,
                "chain_length": chain_length,
            })

        total = len(attributes)
        without_evidence = total - with_evidence
        coverage_pct = round(with_evidence / total * 100, 1) if total else 0.0

    return jsonify({
        "entity_id": entity_id,
        "entity_name": entity_name,
        "attributes": attributes,
        "coverage": {
            "total": total,
            "with_evidence": with_evidence,
            "without_evidence": without_evidence,
            "coverage_pct": coverage_pct,
        },
    })


# ── 3. Entity Evidence Map ───────────────────────────────────

@provenance_bp.route("/api/provenance/entity/<int:entity_id>/evidence")
def entity_evidence_map(entity_id):
    """Get all evidence for an entity with what attributes each piece supports.

    Builds a reverse map: for each evidence item, which entity attributes
    were extracted from it.
    """
    db = current_app.db

    with db._get_conn() as conn:
        entity_row = conn.execute(
            "SELECT id, name FROM entities WHERE id = ? AND is_deleted = 0",
            (entity_id,),
        ).fetchone()

        if not entity_row:
            return jsonify({"error": f"Entity {entity_id} not found"}), 404

        # Get all evidence for this entity
        ev_rows = conn.execute(
            """SELECT id, evidence_type, file_path, source_url,
                      source_name, captured_at
               FROM evidence WHERE entity_id = ?
               ORDER BY captured_at DESC""",
            (entity_id,),
        ).fetchall()

        has_extraction_tables = (
            _table_exists(conn, "extraction_results")
            and _table_exists(conn, "extraction_jobs")
        )

        evidence_list = []
        for ev in ev_rows:
            ev_dict = dict(ev)
            supported_attributes = []

            if has_extraction_tables:
                # Find extraction results that used this evidence
                # Match via source_evidence_id on results, or evidence_id on jobs
                attr_rows = conn.execute(
                    """SELECT DISTINCT er.attr_slug, er.extracted_value
                       FROM extraction_results er
                       LEFT JOIN extraction_jobs ej ON ej.id = er.job_id
                       WHERE er.entity_id = ?
                         AND er.status IN ('accepted', 'edited')
                         AND (er.source_evidence_id = ? OR ej.evidence_id = ?)""",
                    (entity_id, ev_dict["id"], ev_dict["id"]),
                ).fetchall()

                for ar in attr_rows:
                    supported_attributes.append({
                        "slug": ar["attr_slug"],
                        "value": ar["extracted_value"],
                    })

            filename = ev_dict.get("file_path", "").rsplit("/", 1)[-1] if ev_dict.get("file_path") else None

            evidence_list.append({
                "id": ev_dict["id"],
                "type": ev_dict["evidence_type"],
                "filename": filename,
                "url": ev_dict.get("source_url"),
                "captured_at": ev_dict["captured_at"],
                "supported_attributes": supported_attributes,
            })

    return jsonify({
        "entity_id": entity_id,
        "evidence": evidence_list,
    })


# ── 4. Project Coverage ──────────────────────────────────────

@provenance_bp.route("/api/provenance/project/<int:project_id>/coverage")
def project_coverage(project_id):
    """Get provenance coverage stats for the whole project.

    For each entity, reports how many attributes are backed by evidence.
    """
    db = current_app.db

    with db._get_conn() as conn:
        # Verify project
        proj = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not proj:
            return jsonify({"error": "Project not found"}), 404

        # All entities in project
        entity_rows = conn.execute(
            """SELECT id, name, type_slug
               FROM entities
               WHERE project_id = ? AND is_deleted = 0
               ORDER BY name COLLATE NOCASE""",
            (project_id,),
        ).fetchall()

        has_extraction_tables = (
            _table_exists(conn, "extraction_results")
            and _table_exists(conn, "extraction_jobs")
        )

        total_attributes = 0
        total_with_evidence = 0
        total_with_extraction = 0
        total_manual_only = 0
        entity_summaries = []

        for entity in entity_rows:
            eid = entity["id"]

            # Current attributes for this entity
            attr_rows = conn.execute(
                """SELECT ea.id, ea.attr_slug, ea.source, ea.captured_at
                   FROM entity_attributes ea
                   WHERE ea.entity_id = ?
                     AND ea.id IN (
                         SELECT MAX(id) FROM entity_attributes
                         WHERE entity_id = ?
                         GROUP BY attr_slug
                     )""",
                (eid, eid),
            ).fetchall()

            entity_total = len(attr_rows)
            entity_evidence = 0

            for attr in attr_rows:
                total_attributes += 1
                source = attr["source"] or "manual"

                if source == "extraction" and has_extraction_tables:
                    total_with_extraction += 1

                    # Check if this extraction links to evidence
                    ev_check = conn.execute(
                        """SELECT 1
                           FROM extraction_results er
                           LEFT JOIN extraction_jobs ej ON ej.id = er.job_id
                           WHERE er.entity_id = ? AND er.attr_slug = ?
                             AND er.status IN ('accepted', 'edited')
                             AND (er.source_evidence_id IS NOT NULL
                                  OR ej.evidence_id IS NOT NULL)
                           LIMIT 1""",
                        (eid, attr["attr_slug"]),
                    ).fetchone()

                    if ev_check:
                        entity_evidence += 1
                        total_with_evidence += 1
                    else:
                        # Extraction without evidence file
                        pass
                elif source == "manual":
                    total_manual_only += 1
                # Other sources (sync, ai, import, etc.) counted as non-evidence

            entity_pct = round(entity_evidence / entity_total * 100, 1) if entity_total else 0.0

            entity_summaries.append({
                "id": eid,
                "name": entity["name"],
                "total_attrs": entity_total,
                "evidence_backed": entity_evidence,
                "pct": entity_pct,
            })

        coverage_pct = round(total_with_evidence / total_attributes * 100, 1) if total_attributes else 0.0

    return jsonify({
        "project_id": project_id,
        "total_attributes": total_attributes,
        "with_evidence": total_with_evidence,
        "with_extraction": total_with_extraction,
        "manual_only": total_manual_only,
        "coverage_pct": coverage_pct,
        "entities": entity_summaries,
    })


# ── 5. Project Sources ───────────────────────────────────────

@provenance_bp.route("/api/provenance/project/<int:project_id>/sources")
def project_sources(project_id):
    """Get all unique source URLs across the project, grouped by entity.

    Returns every distinct source_url from evidence records linked to
    entities in this project, with counts and entity names.
    """
    db = current_app.db

    with db._get_conn() as conn:
        # Verify project
        proj = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not proj:
            return jsonify({"error": "Project not found"}), 404

        # All evidence for entities in this project, with source URLs
        rows = conn.execute(
            """SELECT ev.source_url, ev.evidence_type,
                      e.id AS entity_id, e.name AS entity_name
               FROM evidence ev
               JOIN entities e ON e.id = ev.entity_id
               WHERE e.project_id = ? AND e.is_deleted = 0
                 AND ev.source_url IS NOT NULL AND ev.source_url != ''
               ORDER BY ev.source_url""",
            (project_id,),
        ).fetchall()

        # Count attributes backed by evidence from each URL
        # Build a reverse map: evidence_id -> attr_count
        has_extraction_tables = (
            _table_exists(conn, "extraction_results")
            and _table_exists(conn, "extraction_jobs")
        )

        url_data = {}  # url -> {entity_set, attr_count, evidence_types}

        for row in rows:
            url = row["source_url"]
            if url not in url_data:
                url_data[url] = {
                    "entity_ids": set(),
                    "entity_names": set(),
                    "attribute_count": 0,
                    "evidence_types": set(),
                }
            url_data[url]["entity_ids"].add(row["entity_id"])
            url_data[url]["entity_names"].add(row["entity_name"])
            url_data[url]["evidence_types"].add(row["evidence_type"])

        # Count attributes per URL via extraction results
        if has_extraction_tables:
            attr_by_url = conn.execute(
                """SELECT ev.source_url, COUNT(DISTINCT er.attr_slug) AS attr_count
                   FROM extraction_results er
                   LEFT JOIN extraction_jobs ej ON ej.id = er.job_id
                   JOIN evidence ev ON ev.id = COALESCE(er.source_evidence_id, ej.evidence_id)
                   JOIN entities e ON e.id = er.entity_id
                   WHERE e.project_id = ? AND e.is_deleted = 0
                     AND er.status IN ('accepted', 'edited')
                     AND ev.source_url IS NOT NULL AND ev.source_url != ''
                   GROUP BY ev.source_url""",
                (project_id,),
            ).fetchall()

            for row in attr_by_url:
                url = row["source_url"]
                if url in url_data:
                    url_data[url]["attribute_count"] = row["attr_count"]

        # Build response
        sources = []
        for url, data in sorted(url_data.items()):
            sources.append({
                "url": url,
                "entity_count": len(data["entity_ids"]),
                "attribute_count": data["attribute_count"],
                "evidence_types": sorted(data["evidence_types"]),
                "entities": sorted(data["entity_names"]),
            })

    return jsonify({
        "project_id": project_id,
        "sources": sources,
        "total_sources": len(sources),
    })


# ── 6. Search Attributes by Value ────────────────────────────

@provenance_bp.route("/api/provenance/search")
def search_provenance():
    """Search for attributes matching a value, showing their provenance.

    Query params:
        project_id (required): Project scope
        q (required): Search term (matched against attribute values)
        attr_slug (optional): Limit to a specific attribute slug
        limit (optional): Max results (default: 50)
        offset (optional): Pagination offset (default: 0)
    """
    project_id, err = _require_project_id()
    if err:
        return err

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q (search term) is required"}), 400

    attr_slug = request.args.get("attr_slug")
    limit = request.args.get("limit", 50, type=int)
    offset = max(0, request.args.get("offset", 0, type=int))

    db = current_app.db

    with db._get_conn() as conn:
        # Build query
        conditions = [
            "e.project_id = ?",
            "e.is_deleted = 0",
            "ea.value LIKE ?",
        ]
        params = [project_id, f"%{q}%"]

        if attr_slug:
            conditions.append("ea.attr_slug = ?")
            params.append(attr_slug)

        where = " AND ".join(conditions)

        # Only pick current (most recent) attribute values
        rows = conn.execute(
            f"""SELECT ea.id AS attr_id, ea.entity_id, ea.attr_slug, ea.value,
                       ea.source, ea.confidence, ea.captured_at,
                       e.name AS entity_name
                FROM entity_attributes ea
                JOIN entities e ON e.id = ea.entity_id
                WHERE {where}
                  AND ea.id IN (
                      SELECT MAX(id) FROM entity_attributes
                      WHERE entity_id = ea.entity_id
                      GROUP BY entity_id, attr_slug
                  )
                ORDER BY e.name COLLATE NOCASE, ea.attr_slug
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        # Count total for pagination
        count_row = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM entity_attributes ea
                JOIN entities e ON e.id = ea.entity_id
                WHERE {where}
                  AND ea.id IN (
                      SELECT MAX(id) FROM entity_attributes
                      WHERE entity_id = ea.entity_id
                      GROUP BY entity_id, attr_slug
                  )""",
            params,
        ).fetchone()

        total = count_row["total"] if count_row else 0

        has_extraction_tables = (
            _table_exists(conn, "extraction_results")
            and _table_exists(conn, "extraction_jobs")
        )

        results = []
        for row in rows:
            evidence_url = None
            chain_length = 1

            if row["source"] == "extraction" and has_extraction_tables:
                chain_length = 2
                ev_row = conn.execute(
                    """SELECT ev.source_url
                       FROM extraction_results er
                       LEFT JOIN extraction_jobs ej ON ej.id = er.job_id
                       LEFT JOIN evidence ev ON ev.id = COALESCE(er.source_evidence_id, ej.evidence_id)
                       WHERE er.entity_id = ? AND er.attr_slug = ?
                         AND er.status IN ('accepted', 'edited')
                       ORDER BY ABS(
                           julianday(er.created_at) - julianday(?)
                       ) ASC
                       LIMIT 1""",
                    (row["entity_id"], row["attr_slug"], row["captured_at"]),
                ).fetchone()

                if ev_row and ev_row["source_url"]:
                    evidence_url = ev_row["source_url"]
                    chain_length = 4

            results.append({
                "entity_id": row["entity_id"],
                "entity_name": row["entity_name"],
                "attr_slug": row["attr_slug"],
                "value": row["value"],
                "source": row["source"],
                "evidence_url": evidence_url,
                "chain_length": chain_length,
            })

    return jsonify({
        "results": results,
        "total": total,
    })


# ── 7. Report Claims -> Evidence ─────────────────────────────

@provenance_bp.route("/api/provenance/report/<int:report_id>/claims")
def report_claims(report_id):
    """Map report sections to their evidence sources.

    Scans the report content for entity names and attribute values,
    then returns provenance links for each reference found.

    Query params:
        project_id (required): Project context for entity lookup
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        # Check for workbench_reports table
        if not _table_exists(conn, "workbench_reports"):
            return jsonify({"error": "Reports table not found"}), 404

        report_row = conn.execute(
            """SELECT id, title, content_json, project_id
               FROM workbench_reports WHERE id = ?""",
            (report_id,),
        ).fetchone()

        if not report_row:
            return jsonify({"error": f"Report {report_id} not found"}), 404

        # Parse report content
        content = _parse_json_field(report_row["content_json"])
        sections = content.get("sections", [])

        # Get all entity names for this project
        entity_rows = conn.execute(
            """SELECT id, name FROM entities
               WHERE project_id = ? AND is_deleted = 0""",
            (project_id,),
        ).fetchall()

        entity_lookup = {e["name"].lower(): e for e in entity_rows}
        entity_ids = {e["id"] for e in entity_rows}

        has_extraction_tables = (
            _table_exists(conn, "extraction_results")
            and _table_exists(conn, "extraction_jobs")
        )

        # For each section, find references to entities and their attributes
        claims = []

        for section in sections:
            heading = section.get("heading", "")
            section_content = section.get("content", "")
            full_text = f"{heading} {section_content}".lower()

            # Find entity names mentioned in section text
            referenced_entities = []
            referenced_values = []

            for entity_name_lower, entity in entity_lookup.items():
                if entity_name_lower in full_text:
                    referenced_entities.append(entity["name"])
                    eid = entity["id"]

                    # Get current attributes for this entity
                    attr_rows = conn.execute(
                        """SELECT ea.attr_slug, ea.value, ea.source, ea.captured_at
                           FROM entity_attributes ea
                           WHERE ea.entity_id = ?
                             AND ea.id IN (
                                 SELECT MAX(id) FROM entity_attributes
                                 WHERE entity_id = ?
                                 GROUP BY attr_slug
                             )""",
                        (eid, eid),
                    ).fetchall()

                    for attr in attr_rows:
                        attr_val = attr["value"] or ""
                        # Check if attribute value appears in section text
                        if attr_val and attr_val.lower() in full_text:
                            evidence_url = None

                            if attr["source"] == "extraction" and has_extraction_tables:
                                ev_row = conn.execute(
                                    """SELECT ev.source_url
                                       FROM extraction_results er
                                       LEFT JOIN extraction_jobs ej ON ej.id = er.job_id
                                       LEFT JOIN evidence ev ON ev.id = COALESCE(
                                           er.source_evidence_id, ej.evidence_id
                                       )
                                       WHERE er.entity_id = ? AND er.attr_slug = ?
                                         AND er.status IN ('accepted', 'edited')
                                       ORDER BY ABS(
                                           julianday(er.created_at) - julianday(?)
                                       ) ASC
                                       LIMIT 1""",
                                    (eid, attr["attr_slug"], attr["captured_at"]),
                                ).fetchone()

                                if ev_row:
                                    evidence_url = ev_row["source_url"]

                            referenced_values.append({
                                "entity": entity["name"],
                                "attr": attr["attr_slug"],
                                "value": attr_val,
                                "evidence_url": evidence_url,
                            })

            if referenced_entities or referenced_values:
                claims.append({
                    "section_title": heading,
                    "referenced_entities": sorted(set(referenced_entities)),
                    "referenced_values": referenced_values,
                })

    return jsonify({
        "report_id": report_id,
        "claims": claims,
    })


# ── 8. Quick Provenance Stats ────────────────────────────────

@provenance_bp.route("/api/provenance/stats")
def provenance_stats():
    """Quick provenance stats for a project.

    Query params:
        project_id (required): Project scope

    Returns counts of attributes by source type, evidence and source
    URL counts, and overall coverage percentage.
    """
    project_id, err = _require_project_id()
    if err:
        return err

    db = current_app.db

    with db._get_conn() as conn:
        proj = conn.execute(
            "SELECT id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not proj:
            return jsonify({"error": "Project not found"}), 404

        # Total current attributes (most recent per entity+slug)
        total_row = conn.execute(
            """SELECT COUNT(*) AS total
               FROM entity_attributes ea
               JOIN entities e ON e.id = ea.entity_id
               WHERE e.project_id = ? AND e.is_deleted = 0
                 AND ea.id IN (
                     SELECT MAX(id) FROM entity_attributes
                     WHERE entity_id = ea.entity_id
                     GROUP BY entity_id, attr_slug
                 )""",
            (project_id,),
        ).fetchone()
        total_attributes = total_row["total"] if total_row else 0

        # Breakdown by source
        source_rows = conn.execute(
            """SELECT ea.source, COUNT(*) AS cnt
               FROM entity_attributes ea
               JOIN entities e ON e.id = ea.entity_id
               WHERE e.project_id = ? AND e.is_deleted = 0
                 AND ea.id IN (
                     SELECT MAX(id) FROM entity_attributes
                     WHERE entity_id = ea.entity_id
                     GROUP BY entity_id, attr_slug
                 )
               GROUP BY ea.source""",
            (project_id,),
        ).fetchall()

        source_counts = {r["source"] or "manual": r["cnt"] for r in source_rows}
        extraction_backed = source_counts.get("extraction", 0)
        manual_only = source_counts.get("manual", 0)
        sync_only = source_counts.get("sync", 0)

        # Evidence-backed count (extraction attrs that actually have evidence)
        evidence_backed = 0
        has_extraction_tables = (
            _table_exists(conn, "extraction_results")
            and _table_exists(conn, "extraction_jobs")
        )

        if has_extraction_tables and extraction_backed > 0:
            ev_row = conn.execute(
                """SELECT COUNT(DISTINCT ea.id) AS cnt
                   FROM entity_attributes ea
                   JOIN entities e ON e.id = ea.entity_id
                   JOIN extraction_results er ON er.entity_id = ea.entity_id
                       AND er.attr_slug = ea.attr_slug
                       AND er.status IN ('accepted', 'edited')
                   LEFT JOIN extraction_jobs ej ON ej.id = er.job_id
                   WHERE e.project_id = ? AND e.is_deleted = 0
                     AND ea.source = 'extraction'
                     AND ea.id IN (
                         SELECT MAX(id) FROM entity_attributes
                         WHERE entity_id = ea.entity_id
                         GROUP BY entity_id, attr_slug
                     )
                     AND (er.source_evidence_id IS NOT NULL
                          OR ej.evidence_id IS NOT NULL)""",
                (project_id,),
            ).fetchone()
            evidence_backed = ev_row["cnt"] if ev_row else 0

        # Distinct source URLs
        source_count_row = conn.execute(
            """SELECT COUNT(DISTINCT ev.source_url) AS cnt
               FROM evidence ev
               JOIN entities e ON e.id = ev.entity_id
               WHERE e.project_id = ? AND e.is_deleted = 0
                 AND ev.source_url IS NOT NULL AND ev.source_url != ''""",
            (project_id,),
        ).fetchone()
        source_count = source_count_row["cnt"] if source_count_row else 0

        # Total evidence count
        evidence_count_row = conn.execute(
            """SELECT COUNT(ev.id) AS cnt
               FROM evidence ev
               JOIN entities e ON e.id = ev.entity_id
               WHERE e.project_id = ? AND e.is_deleted = 0""",
            (project_id,),
        ).fetchone()
        evidence_count = evidence_count_row["cnt"] if evidence_count_row else 0

        coverage_pct = round(evidence_backed / total_attributes * 100, 1) if total_attributes else 0.0

    return jsonify({
        "total_attributes": total_attributes,
        "evidence_backed": evidence_backed,
        "extraction_backed": extraction_backed,
        "manual_only": manual_only,
        "sync_only": sync_only,
        "coverage_pct": coverage_pct,
        "source_count": source_count,
        "evidence_count": evidence_count,
    })
