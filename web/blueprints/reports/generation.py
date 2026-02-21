"""Report generation — structured and AI-enhanced."""
import json
from datetime import datetime, timezone

from flask import request, jsonify, current_app
from loguru import logger

from . import reports_bp
from ._shared import (
    _require_project_id, _now_iso, _ensure_table,
    _row_to_report, _REPORT_TABLE_SQL,
)

# ═══════════════════════════════════════════════════════════════
# Data Gathering — used by both structured and AI report generation
# ═══════════════════════════════════════════════════════════════

def _gather_market_overview(conn, project_id, entity_ids=None):
    """Gather data for a market overview report."""
    # Entity counts by type
    type_counts = conn.execute(
        """
        SELECT type_slug, COUNT(*) as count
        FROM entities
        WHERE project_id = ? AND is_deleted = 0
        GROUP BY type_slug
        ORDER BY count DESC
        """,
        (project_id,),
    ).fetchall()

    # Category distribution
    category_dist = conn.execute(
        """
        SELECT c.name as category_name, COUNT(e.id) as count
        FROM entities e
        LEFT JOIN categories c ON c.id = e.category_id
        WHERE e.project_id = ? AND e.is_deleted = 0
        GROUP BY e.category_id
        ORDER BY count DESC
        """,
        (project_id,),
    ).fetchall()

    # Top attributes across all entities (most common attr_slugs)
    top_attrs = conn.execute(
        """
        SELECT ea.attr_slug, COUNT(DISTINCT ea.entity_id) as entity_count
        FROM entity_attributes ea
        JOIN entities e ON e.id = ea.entity_id
        WHERE e.project_id = ? AND e.is_deleted = 0
        GROUP BY ea.attr_slug
        ORDER BY entity_count DESC
        LIMIT 20
        """,
        (project_id,),
    ).fetchall()

    # Total entity count
    total = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE project_id = ? AND is_deleted = 0",
        (project_id,),
    ).fetchone()[0]

    # Starred entities
    starred = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE project_id = ? AND is_deleted = 0 AND is_starred = 1",
        (project_id,),
    ).fetchone()[0]

    # Evidence count
    evidence_count = conn.execute(
        """
        SELECT COUNT(ev.id)
        FROM evidence ev
        JOIN entities e ON e.id = ev.entity_id
        WHERE e.project_id = ?
        """,
        (project_id,),
    ).fetchone()[0]

    # Entity list (for reference)
    entity_rows = conn.execute(
        """
        SELECT id, name, type_slug, status, is_starred
        FROM entities
        WHERE project_id = ? AND is_deleted = 0
        ORDER BY name COLLATE NOCASE
        """,
        (project_id,),
    ).fetchall()

    return {
        "total_entities": total,
        "starred_count": starred,
        "evidence_count": evidence_count,
        "types": [{"type_slug": r["type_slug"], "count": r["count"]} for r in type_counts],
        "categories": [
            {"name": r["category_name"] or "Uncategorised", "count": r["count"]}
            for r in category_dist
        ],
        "top_attributes": [
            {"attr_slug": r["attr_slug"], "entity_count": r["entity_count"]}
            for r in top_attrs
        ],
        "entities": [
            {
                "id": r["id"],
                "name": r["name"],
                "type_slug": r["type_slug"],
                "status": r["status"],
                "is_starred": bool(r["is_starred"]),
            }
            for r in entity_rows
        ],
    }


def _gather_competitive_landscape(conn, project_id, entity_ids=None):
    """Gather data for a competitive landscape report."""
    # Get entities (optionally filtered)
    if entity_ids:
        placeholders = ",".join("?" * len(entity_ids))
        entity_rows = conn.execute(
            f"""
            SELECT id, name, type_slug FROM entities
            WHERE project_id = ? AND is_deleted = 0 AND id IN ({placeholders})
            ORDER BY name COLLATE NOCASE
            """,
            [project_id] + entity_ids,
        ).fetchall()
    else:
        entity_rows = conn.execute(
            """
            SELECT id, name, type_slug FROM entities
            WHERE project_id = ? AND is_deleted = 0
            ORDER BY name COLLATE NOCASE
            """,
            (project_id,),
        ).fetchall()

    eids = [r["id"] for r in entity_rows]
    if not eids:
        return {"entities": [], "feature_matrix": {}, "attribute_coverage": [], "gaps": []}

    placeholders = ",".join("?" * len(eids))

    # All attributes for these entities (most recent per entity+slug)
    attr_rows = conn.execute(
        f"""
        SELECT ea.entity_id, ea.attr_slug, ea.value
        FROM entity_attributes ea
        WHERE ea.entity_id IN ({placeholders})
          AND ea.id IN (
              SELECT MAX(id) FROM entity_attributes
              WHERE entity_id IN ({placeholders})
              GROUP BY entity_id, attr_slug
          )
        """,
        eids + eids,
    ).fetchall()

    # Build per-entity attribute maps
    entity_attrs = {}  # entity_id -> {slug: value}
    all_slugs = set()
    for row in attr_rows:
        entity_attrs.setdefault(row["entity_id"], {})[row["attr_slug"]] = row["value"]
        all_slugs.add(row["attr_slug"])

    # Feature matrix: which entities have which attributes
    feature_matrix = {}
    for slug in sorted(all_slugs):
        feature_matrix[slug] = {}
        for r in entity_rows:
            val = entity_attrs.get(r["id"], {}).get(slug)
            feature_matrix[slug][str(r["id"])] = val

    # Attribute coverage: for each slug, how many entities have it
    coverage = []
    total = len(eids)
    for slug in sorted(all_slugs):
        count = sum(1 for eid in eids if entity_attrs.get(eid, {}).get(slug) is not None)
        coverage.append({
            "attr_slug": slug,
            "entity_count": count,
            "total_entities": total,
            "coverage_pct": round(count / total * 100, 1) if total else 0,
        })
    coverage.sort(key=lambda c: c["coverage_pct"])

    # Gaps: attributes where less than half the entities have data
    gaps = [c for c in coverage if c["coverage_pct"] < 50]

    return {
        "entities": [
            {"id": r["id"], "name": r["name"], "type_slug": r["type_slug"]}
            for r in entity_rows
        ],
        "feature_matrix": feature_matrix,
        "attribute_coverage": coverage,
        "gaps": gaps,
    }


def _gather_product_teardown(conn, project_id, entity_ids=None):
    """Gather data for a product teardown report (single entity deep dive)."""
    # Pick the first entity with most attributes, or the first entity_id if given
    if entity_ids:
        target_id = entity_ids[0]
    else:
        row = conn.execute(
            """
            SELECT ea.entity_id, COUNT(DISTINCT ea.attr_slug) as attr_count
            FROM entity_attributes ea
            JOIN entities e ON e.id = ea.entity_id
            WHERE e.project_id = ? AND e.is_deleted = 0
            GROUP BY ea.entity_id
            ORDER BY attr_count DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if not row:
            return {"entity": None, "attributes": {}, "evidence": [], "extraction_results": []}
        target_id = row["entity_id"]

    # Entity details
    entity_row = conn.execute(
        """
        SELECT id, name, type_slug, status, is_starred, tags,
               source, confidence_score, created_at, updated_at
        FROM entities
        WHERE id = ? AND project_id = ? AND is_deleted = 0
        """,
        (target_id, project_id),
    ).fetchone()

    if not entity_row:
        return {"entity": None, "attributes": {}, "evidence": [], "extraction_results": []}

    # All current attributes
    attr_rows = conn.execute(
        """
        SELECT ea.attr_slug, ea.value, ea.source, ea.confidence, ea.captured_at
        FROM entity_attributes ea
        WHERE ea.entity_id = ?
          AND ea.id IN (
              SELECT MAX(id) FROM entity_attributes
              WHERE entity_id = ?
              GROUP BY attr_slug
          )
        ORDER BY ea.attr_slug
        """,
        (target_id, target_id),
    ).fetchall()

    attributes = {}
    for r in attr_rows:
        attributes[r["attr_slug"]] = {
            "value": r["value"],
            "source": r["source"],
            "confidence": r["confidence"],
            "captured_at": r["captured_at"],
        }

    # Evidence list
    evidence_rows = conn.execute(
        """
        SELECT id, evidence_type, file_path, source_url, source_name, captured_at
        FROM evidence
        WHERE entity_id = ?
        ORDER BY captured_at DESC
        """,
        (target_id,),
    ).fetchall()

    evidence = [
        {
            "id": r["id"],
            "type": r["evidence_type"],
            "file_path": r["file_path"],
            "source_url": r["source_url"],
            "source_name": r["source_name"],
            "captured_at": r["captured_at"],
        }
        for r in evidence_rows
    ]

    # Extraction results
    extraction_rows = conn.execute(
        """
        SELECT er.attr_slug, er.extracted_value, er.confidence, er.reasoning,
               er.status, er.reviewed_value
        FROM extraction_results er
        JOIN extraction_jobs ej ON ej.id = er.job_id
        WHERE er.entity_id = ?
        ORDER BY er.created_at DESC
        """,
        (target_id,),
    ).fetchall()

    extraction_results = [
        {
            "attr_slug": r["attr_slug"],
            "extracted_value": r["extracted_value"],
            "confidence": r["confidence"],
            "reasoning": r["reasoning"],
            "status": r["status"],
            "reviewed_value": r["reviewed_value"],
        }
        for r in extraction_rows
    ]

    tags = []
    if entity_row["tags"]:
        try:
            tags = json.loads(entity_row["tags"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "entity": {
            "id": entity_row["id"],
            "name": entity_row["name"],
            "type_slug": entity_row["type_slug"],
            "status": entity_row["status"],
            "is_starred": bool(entity_row["is_starred"]),
            "tags": tags,
            "source": entity_row["source"],
            "confidence_score": entity_row["confidence_score"],
            "created_at": entity_row["created_at"],
            "updated_at": entity_row["updated_at"],
        },
        "attributes": attributes,
        "attribute_count": len(attributes),
        "evidence": evidence,
        "evidence_count": len(evidence),
        "extraction_results": extraction_results,
    }


def _gather_design_patterns(conn, project_id, entity_ids=None):
    """Gather data for a design patterns report."""
    # Get all screenshot evidence grouped by entity and journey stage metadata
    if entity_ids:
        placeholders = ",".join("?" * len(entity_ids))
        evidence_rows = conn.execute(
            f"""
            SELECT ev.id, ev.entity_id, e.name as entity_name,
                   ev.file_path, ev.source_url, ev.source_name,
                   ev.metadata_json, ev.captured_at
            FROM evidence ev
            JOIN entities e ON e.id = ev.entity_id
            WHERE e.project_id = ? AND ev.evidence_type = 'screenshot'
              AND ev.entity_id IN ({placeholders})
            ORDER BY e.name, ev.captured_at
            """,
            [project_id] + entity_ids,
        ).fetchall()
    else:
        evidence_rows = conn.execute(
            """
            SELECT ev.id, ev.entity_id, e.name as entity_name,
                   ev.file_path, ev.source_url, ev.source_name,
                   ev.metadata_json, ev.captured_at
            FROM evidence ev
            JOIN entities e ON e.id = ev.entity_id
            WHERE e.project_id = ? AND ev.evidence_type = 'screenshot'
            ORDER BY e.name, ev.captured_at
            """,
            (project_id,),
        ).fetchall()

    # Classify screenshots by journey stage
    from core.extractors.screenshot import classify_by_context

    by_entity = {}  # entity_name -> [screenshot_info]
    by_stage = {}   # stage -> [screenshot_info]
    for row in evidence_rows:
        metadata = {}
        if row["metadata_json"]:
            try:
                metadata = json.loads(row["metadata_json"]) if isinstance(row["metadata_json"], str) else row["metadata_json"]
            except (json.JSONDecodeError, TypeError):
                pass

        filename = None
        if row["file_path"]:
            filename = row["file_path"].split("/")[-1]

        try:
            classification = classify_by_context(
                source_url=row["source_url"],
                filename=filename,
                source_name=row["source_name"],
                evidence_metadata=metadata,
            )
            stage = classification.journey_stage
            ui_patterns = classification.ui_patterns
        except Exception:
            stage = "other"
            ui_patterns = []

        entry = {
            "evidence_id": row["id"],
            "entity_id": row["entity_id"],
            "entity_name": row["entity_name"],
            "file_path": row["file_path"],
            "source_url": row["source_url"],
            "source_name": row["source_name"],
            "stage": stage,
            "ui_patterns": ui_patterns,
            "captured_at": row["captured_at"],
        }

        by_entity.setdefault(row["entity_name"], []).append(entry)
        by_stage.setdefault(stage, []).append(entry)

    entities_covered = list(by_entity.keys())
    stages_found = list(by_stage.keys())

    return {
        "total_screenshots": len(evidence_rows),
        "entities_covered": entities_covered,
        "entity_count": len(entities_covered),
        "stages_found": stages_found,
        "by_entity": {
            name: screenshots for name, screenshots in sorted(by_entity.items())
        },
        "by_stage": {
            stage: screenshots for stage, screenshots in sorted(by_stage.items())
        },
    }


def _gather_change_report(conn, project_id, entity_ids=None):
    """Gather data for a change report from entity snapshots."""
    # Get all snapshots for this project
    snapshot_rows = conn.execute(
        """
        SELECT es.id, es.description, es.created_at
        FROM entity_snapshots es
        WHERE es.project_id = ?
        ORDER BY es.created_at ASC
        """,
        (project_id,),
    ).fetchall()

    if not snapshot_rows:
        return {"snapshots": [], "entity_changes": {}, "summary": "No snapshots found."}

    snapshot_ids = [r["id"] for r in snapshot_rows]
    placeholders = ",".join("?" * len(snapshot_ids))

    # Get all attribute rows for these snapshots
    if entity_ids:
        eid_placeholders = ",".join("?" * len(entity_ids))
        attr_rows = conn.execute(
            f"""
            SELECT ea.entity_id, e.name as entity_name,
                   ea.attr_slug, ea.value, ea.snapshot_id, ea.captured_at
            FROM entity_attributes ea
            JOIN entities e ON e.id = ea.entity_id
            WHERE ea.snapshot_id IN ({placeholders})
              AND ea.entity_id IN ({eid_placeholders})
            ORDER BY ea.entity_id, ea.captured_at ASC
            """,
            snapshot_ids + entity_ids,
        ).fetchall()
    else:
        attr_rows = conn.execute(
            f"""
            SELECT ea.entity_id, e.name as entity_name,
                   ea.attr_slug, ea.value, ea.snapshot_id, ea.captured_at
            FROM entity_attributes ea
            JOIN entities e ON e.id = ea.entity_id
            WHERE ea.snapshot_id IN ({placeholders})
            ORDER BY ea.entity_id, ea.captured_at ASC
            """,
            snapshot_ids,
        ).fetchall()

    # Build per-entity timeline of changes
    entity_snapshots = {}  # entity_id -> {snapshot_id -> {slug: value}}
    entity_names = {}
    for row in attr_rows:
        eid = row["entity_id"]
        sid = row["snapshot_id"]
        entity_names[eid] = row["entity_name"]
        entity_snapshots.setdefault(eid, {}).setdefault(sid, {})[row["attr_slug"]] = row["value"]

    # Compute diffs per entity between consecutive snapshots
    entity_changes = {}
    for eid, snap_data in entity_snapshots.items():
        ename = entity_names[eid]
        # Order by snapshot_id position in snapshot_rows
        ordered_sids = [s["id"] for s in snapshot_rows if s["id"] in snap_data]
        changes = []
        prev_attrs = {}
        for sid in ordered_sids:
            current = snap_data[sid]
            diffs = {}
            all_slugs = set(prev_attrs.keys()) | set(current.keys())
            for slug in all_slugs:
                old_val = prev_attrs.get(slug)
                new_val = current.get(slug)
                if old_val != new_val:
                    diffs[slug] = {"old_value": old_val, "new_value": new_val}
            if diffs or not prev_attrs:
                snap_meta = next(
                    (s for s in snapshot_rows if s["id"] == sid), None
                )
                changes.append({
                    "snapshot_id": sid,
                    "captured_at": snap_meta["created_at"] if snap_meta else None,
                    "description": snap_meta["description"] if snap_meta else "",
                    "attributes": current,
                    "changes": diffs,
                })
            prev_attrs = {**prev_attrs, **current}
        entity_changes[ename] = changes

    return {
        "snapshots": [
            {
                "id": r["id"],
                "description": r["description"],
                "created_at": r["created_at"],
            }
            for r in snapshot_rows
        ],
        "snapshot_count": len(snapshot_rows),
        "entity_changes": entity_changes,
        "entities_tracked": len(entity_changes),
    }


# ── Report section builders ──────────────────────────────────

def _build_market_overview_sections(data):
    """Build structured sections for a market overview report."""
    sections = []

    # Summary section
    summary_lines = [
        f"Total entities: {data['total_entities']}",
        f"Starred: {data['starred_count']}",
        f"Evidence items: {data['evidence_count']}",
    ]
    sections.append({
        "heading": "Summary",
        "content": "\n".join(summary_lines),
        "data": {
            "total_entities": data["total_entities"],
            "starred_count": data["starred_count"],
            "evidence_count": data["evidence_count"],
        },
        "evidence_refs": [],
    })

    # Entity types breakdown
    type_lines = [f"- {t['type_slug']}: {t['count']}" for t in data["types"]]
    sections.append({
        "heading": "Entity Types",
        "content": "\n".join(type_lines) if type_lines else "No entity types found.",
        "data": {"types": data["types"]},
        "evidence_refs": [],
    })

    # Category distribution
    cat_lines = [f"- {c['name']}: {c['count']}" for c in data["categories"]]
    sections.append({
        "heading": "Category Distribution",
        "content": "\n".join(cat_lines) if cat_lines else "No categories assigned.",
        "data": {"categories": data["categories"]},
        "evidence_refs": [],
    })

    # Top attributes
    attr_lines = [
        f"- {a['attr_slug']}: tracked across {a['entity_count']} entities"
        for a in data["top_attributes"][:10]
    ]
    sections.append({
        "heading": "Most Common Attributes",
        "content": "\n".join(attr_lines) if attr_lines else "No attributes found.",
        "data": {"top_attributes": data["top_attributes"][:10]},
        "evidence_refs": [],
    })

    # Entity listing
    entity_lines = [
        f"- {e['name']} ({e['type_slug']}){' *' if e['is_starred'] else ''}"
        for e in data["entities"]
    ]
    sections.append({
        "heading": "Entity Listing",
        "content": "\n".join(entity_lines) if entity_lines else "No entities.",
        "data": {"entities": data["entities"]},
        "evidence_refs": [],
    })

    return sections


def _build_competitive_landscape_sections(data):
    """Build structured sections for a competitive landscape report."""
    sections = []
    entities = data["entities"]

    if not entities:
        sections.append({
            "heading": "No Data",
            "content": "No entities with comparable attributes found.",
            "data": {},
            "evidence_refs": [],
        })
        return sections

    # Entity overview
    entity_lines = [f"- {e['name']} ({e['type_slug']})" for e in entities]
    sections.append({
        "heading": "Entities Compared",
        "content": "\n".join(entity_lines),
        "data": {"entity_count": len(entities)},
        "evidence_refs": [],
    })

    # Attribute coverage
    coverage = data["attribute_coverage"]
    coverage_lines = [
        f"- {c['attr_slug']}: {c['entity_count']}/{c['total_entities']} ({c['coverage_pct']}%)"
        for c in coverage
    ]
    sections.append({
        "heading": "Attribute Coverage",
        "content": "\n".join(coverage_lines) if coverage_lines else "No attributes tracked.",
        "data": {"coverage": coverage},
        "evidence_refs": [],
    })

    # Feature matrix summary
    matrix = data["feature_matrix"]
    eid_to_name = {str(e["id"]): e["name"] for e in entities}
    matrix_lines = []
    for slug, values in matrix.items():
        entity_vals = []
        for eid_str, val in values.items():
            name = eid_to_name.get(eid_str, eid_str)
            display_val = val if val is not None else "(missing)"
            # Truncate long values
            if isinstance(display_val, str) and len(display_val) > 80:
                display_val = display_val[:77] + "..."
            entity_vals.append(f"  - {name}: {display_val}")
        matrix_lines.append(f"{slug}:")
        matrix_lines.extend(entity_vals)
    sections.append({
        "heading": "Feature Matrix",
        "content": "\n".join(matrix_lines) if matrix_lines else "No feature data.",
        "data": {"feature_matrix": matrix},
        "evidence_refs": [],
    })

    # Gaps
    gaps = data["gaps"]
    if gaps:
        gap_lines = [
            f"- {g['attr_slug']}: only {g['entity_count']}/{g['total_entities']} entities ({g['coverage_pct']}%)"
            for g in gaps
        ]
        sections.append({
            "heading": "Data Gaps",
            "content": (
                "The following attributes have less than 50% coverage:\n"
                + "\n".join(gap_lines)
            ),
            "data": {"gaps": gaps},
            "evidence_refs": [],
        })

    return sections


def _build_product_teardown_sections(data):
    """Build structured sections for a product teardown report."""
    sections = []
    entity = data.get("entity")

    if not entity:
        sections.append({
            "heading": "No Data",
            "content": "No entity with sufficient attributes found for teardown.",
            "data": {},
            "evidence_refs": [],
        })
        return sections

    # Entity overview
    overview_lines = [
        f"Name: {entity['name']}",
        f"Type: {entity['type_slug']}",
        f"Status: {entity['status']}",
        f"Source: {entity['source']}",
        f"Created: {entity['created_at']}",
    ]
    if entity.get("tags"):
        overview_lines.append(f"Tags: {', '.join(entity['tags'])}")
    if entity.get("confidence_score") is not None:
        overview_lines.append(f"Confidence: {entity['confidence_score']}")
    sections.append({
        "heading": f"Entity: {entity['name']}",
        "content": "\n".join(overview_lines),
        "data": {"entity": entity},
        "evidence_refs": [],
    })

    # Attributes
    attributes = data["attributes"]
    attr_lines = []
    for slug, attr in sorted(attributes.items()):
        val = attr["value"]
        if isinstance(val, str) and len(val) > 120:
            val = val[:117] + "..."
        attr_lines.append(f"- {slug}: {val} (source: {attr['source']}, confidence: {attr['confidence']})")
    sections.append({
        "heading": "Attributes",
        "content": (
            f"{data['attribute_count']} attributes recorded:\n" +
            "\n".join(attr_lines)
        ) if attr_lines else "No attributes recorded.",
        "data": {"attributes": attributes},
        "evidence_refs": [],
    })

    # Evidence
    evidence = data["evidence"]
    evidence_refs = [e["id"] for e in evidence]
    ev_lines = [
        f"- [{e['type']}] {e['source_name'] or e['source_url'] or e['file_path']} ({e['captured_at']})"
        for e in evidence
    ]
    sections.append({
        "heading": "Evidence",
        "content": (
            f"{data['evidence_count']} evidence items:\n" +
            "\n".join(ev_lines)
        ) if ev_lines else "No evidence captured.",
        "data": {"evidence_count": data["evidence_count"]},
        "evidence_refs": evidence_refs,
    })

    # Extraction results
    extraction = data["extraction_results"]
    if extraction:
        ext_lines = []
        for r in extraction:
            status_marker = {"accepted": "+", "rejected": "x", "edited": "~", "pending": "?"}.get(r["status"], "?")
            ext_lines.append(
                f"[{status_marker}] {r['attr_slug']}: {r['extracted_value']} "
                f"(confidence: {r['confidence']}, status: {r['status']})"
            )
        sections.append({
            "heading": "Extraction Results",
            "content": "\n".join(ext_lines),
            "data": {"extraction_results": extraction},
            "evidence_refs": [],
        })

    # Data completeness assessment
    type_slug = entity["type_slug"]
    sections.append({
        "heading": "Data Completeness",
        "content": (
            f"Entity type: {type_slug}\n"
            f"Attributes filled: {data['attribute_count']}\n"
            f"Evidence items: {data['evidence_count']}\n"
            f"Extraction results: {len(extraction)}"
        ),
        "data": {
            "attribute_count": data["attribute_count"],
            "evidence_count": data["evidence_count"],
            "extraction_count": len(extraction),
        },
        "evidence_refs": [],
    })

    return sections


def _build_design_patterns_sections(data):
    """Build structured sections for a design patterns report."""
    sections = []

    if data["total_screenshots"] == 0:
        sections.append({
            "heading": "No Data",
            "content": "No screenshot evidence found.",
            "data": {},
            "evidence_refs": [],
        })
        return sections

    # Overview
    sections.append({
        "heading": "Overview",
        "content": (
            f"Total screenshots: {data['total_screenshots']}\n"
            f"Entities covered: {data['entity_count']}\n"
            f"Journey stages identified: {', '.join(data['stages_found'])}"
        ),
        "data": {
            "total_screenshots": data["total_screenshots"],
            "entity_count": data["entity_count"],
            "stages_found": data["stages_found"],
        },
        "evidence_refs": [],
    })

    # By journey stage
    for stage, screenshots in sorted(data["by_stage"].items()):
        evidence_refs = [s["evidence_id"] for s in screenshots]
        stage_lines = []
        for s in screenshots:
            ui = f" [{', '.join(s['ui_patterns'])}]" if s["ui_patterns"] else ""
            stage_lines.append(
                f"- {s['entity_name']}: {s['source_url'] or s['file_path']}{ui}"
            )
        sections.append({
            "heading": f"Stage: {stage.title()} ({len(screenshots)} screenshots)",
            "content": "\n".join(stage_lines),
            "data": {"stage": stage, "count": len(screenshots)},
            "evidence_refs": evidence_refs,
        })

    # Cross-entity comparison by stage
    comparison_lines = []
    for stage, screenshots in sorted(data["by_stage"].items()):
        entities_in_stage = sorted(set(s["entity_name"] for s in screenshots))
        comparison_lines.append(f"- {stage}: {', '.join(entities_in_stage)}")
    sections.append({
        "heading": "Cross-Entity Stage Coverage",
        "content": "\n".join(comparison_lines),
        "data": {"by_stage_entities": {
            stage: sorted(set(s["entity_name"] for s in shots))
            for stage, shots in data["by_stage"].items()
        }},
        "evidence_refs": [],
    })

    return sections


def _build_change_report_sections(data):
    """Build structured sections for a change report."""
    sections = []

    if not data["snapshots"]:
        sections.append({
            "heading": "No Data",
            "content": "No snapshots found for this project.",
            "data": {},
            "evidence_refs": [],
        })
        return sections

    # Overview
    sections.append({
        "heading": "Overview",
        "content": (
            f"Total snapshots: {data['snapshot_count']}\n"
            f"Entities tracked: {data['entities_tracked']}"
        ),
        "data": {
            "snapshot_count": data["snapshot_count"],
            "entities_tracked": data["entities_tracked"],
        },
        "evidence_refs": [],
    })

    # Snapshot timeline
    snap_lines = [
        f"- Snapshot #{s['id']}: {s['created_at']}"
        + (f" — {s['description']}" if s["description"] else "")
        for s in data["snapshots"]
    ]
    sections.append({
        "heading": "Snapshot Timeline",
        "content": "\n".join(snap_lines),
        "data": {"snapshots": data["snapshots"]},
        "evidence_refs": [],
    })

    # Per-entity changes
    for entity_name, changes in sorted(data["entity_changes"].items()):
        change_lines = []
        for c in changes:
            if c["changes"]:
                for slug, diff in c["changes"].items():
                    old = diff["old_value"] or "(none)"
                    new = diff["new_value"] or "(none)"
                    change_lines.append(
                        f"  [{c['captured_at']}] {slug}: {old} -> {new}"
                    )
        if change_lines:
            sections.append({
                "heading": f"Changes: {entity_name}",
                "content": "\n".join(change_lines),
                "data": {"entity_name": entity_name, "change_count": len(change_lines)},
                "evidence_refs": [],
            })

    return sections


# Dispatcher: template slug -> (gather_fn, build_sections_fn)
_TEMPLATE_HANDLERS = {
    "market_overview": (_gather_market_overview, _build_market_overview_sections),
    "competitive_landscape": (_gather_competitive_landscape, _build_competitive_landscape_sections),
    "product_teardown": (_gather_product_teardown, _build_product_teardown_sections),
    "design_patterns": (_gather_design_patterns, _build_design_patterns_sections),
    "change_report": (_gather_change_report, _build_change_report_sections),
}


# ═══════════════════════════════════════════════════════════════
# Generate Report (structured, no AI)
# ═══════════════════════════════════════════════════════════════

@reports_bp.route("/api/synthesis/generate", methods=["POST"])
def generate_report():
    """Generate a structured report from project data.

    Body: {project_id, template, entity_ids: optional, options: optional}

    Returns: the full report object.
    """
    data = request.json or {}
    project_id = data.get("project_id")
    template = data.get("template")
    entity_ids = data.get("entity_ids")
    options = data.get("options", {})

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    if not template:
        return jsonify({"error": "template is required"}), 400
    if template not in _TEMPLATE_HANDLERS:
        return jsonify({"error": f"Unknown template: {template}. Valid: {list(_TEMPLATE_HANDLERS.keys())}"}), 400

    gather_fn, build_fn = _TEMPLATE_HANDLERS[template]
    db = current_app.db

    # Verify project exists
    with db._get_conn() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return jsonify({"error": "Project not found"}), 404

    with db._get_conn() as conn:
        _ensure_table(conn)

        # Gather data
        gathered = gather_fn(conn, project_id, entity_ids)

    # Build sections
    sections = build_fn(gathered)

    # Determine title
    template_name = next(
        (t["name"] for t in _TEMPLATES if t["slug"] == template), template
    )
    title = options.get("title") or f"{template_name} Report"

    now = _now_iso()
    content_json = json.dumps({"sections": sections, "gathered_data": gathered})
    metadata_json = json.dumps({
        "entity_ids": entity_ids,
        "options": options,
        "template_slug": template,
    })

    # Store
    with db._get_conn() as conn:
        _ensure_table(conn)
        cursor = conn.execute(
            """
            INSERT INTO workbench_reports
                (project_id, template, title, content_json, generated_at, is_ai_generated, metadata_json)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (project_id, template, title, content_json, now, metadata_json),
        )
        report_id = cursor.lastrowid

    report = {
        "id": report_id,
        "project_id": project_id,
        "template": template,
        "title": title,
        "sections": sections,
        "generated_at": now,
        "updated_at": None,
        "is_ai_generated": False,
        "metadata": {
            "entity_ids": entity_ids,
            "options": options,
            "template_slug": template,
        },
    }

    logger.info("Generated %s report #%d for project %d", template, report_id, project_id)
    return jsonify(report), 201


# ═══════════════════════════════════════════════════════════════
# Generate AI-Enhanced Report
# ═══════════════════════════════════════════════════════════════

@reports_bp.route("/api/synthesis/generate-ai", methods=["POST"])
def generate_ai_report():
    """Generate an AI-enhanced narrative report from project data.

    Body: {project_id, template, entity_ids: optional, audience: optional, questions: optional}

    Returns: the full report object with AI-written narrative.
    """
    data = request.json or {}
    project_id = data.get("project_id")
    template = data.get("template")
    entity_ids = data.get("entity_ids")
    audience = data.get("audience", "product and research teams")
    questions = data.get("questions", [])

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400
    if not template:
        return jsonify({"error": "template is required"}), 400
    if template not in _TEMPLATE_HANDLERS:
        return jsonify({"error": f"Unknown template: {template}. Valid: {list(_TEMPLATE_HANDLERS.keys())}"}), 400

    gather_fn, _ = _TEMPLATE_HANDLERS[template]
    db = current_app.db

    # Gather data
    with db._get_conn() as conn:
        _ensure_table(conn)
        gathered = gather_fn(conn, project_id, entity_ids)

    # Get project info for context
    with db._get_conn() as conn:
        project_row = conn.execute(
            "SELECT name, purpose, description FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()

    project_name = project_row["name"] if project_row else f"Project {project_id}"
    project_purpose = project_row["purpose"] if project_row else ""
    project_description = project_row["description"] if project_row else ""

    # Build the LLM prompt
    template_name = next(
        (t["name"] for t in _TEMPLATES if t["slug"] == template), template
    )
    template_desc = next(
        (t["description"] for t in _TEMPLATES if t["slug"] == template), ""
    )

    questions_block = ""
    if questions:
        questions_block = (
            "\n\nSPECIFIC QUESTIONS TO ADDRESS:\n"
            + "\n".join(f"- {q}" for q in questions)
        )

    prompt = f"""You are a research analyst writing a {template_name} report.

PROJECT: {project_name}
{f"PURPOSE: {project_purpose}" if project_purpose else ""}
{f"DESCRIPTION: {project_description}" if project_description else ""}
AUDIENCE: {audience}
REPORT TYPE: {template_name} — {template_desc}

DATA (structured research data from the project):
{json.dumps(gathered, separators=(',', ':'), default=str)}
{questions_block}

INSTRUCTIONS:
1. Write a professional, narrative report from the provided data ONLY.
2. Do NOT use general knowledge or make assumptions beyond what the data shows.
3. Cite specific entities and their attributes by name when making claims.
4. Flag any gaps where data is insufficient or missing.
5. Structure the report with clear section headings.
6. Be concise but thorough — highlight patterns, outliers, and actionable insights.
7. If attribute values seem contradictory or unusual, note them.
8. Write for the specified audience.

FORMAT: Return a JSON object with this structure:
{{
    "title": "Report title",
    "sections": [
        {{
            "heading": "Section heading",
            "content": "Narrative text for this section"
        }}
    ]
}}

Return ONLY the JSON object, no markdown fences or extra text."""

    # Call LLM
    try:
        from core.llm import run_cli
        model = data.get("model", "claude-haiku-4-5-20251001")
        llm_result = run_cli(prompt, model=model, timeout=120, json_schema=_REPORT_SCHEMA)
    except Exception as e:
        logger.error("LLM call failed for AI report generation: %s", e)
        return jsonify({"error": f"AI generation failed: {str(e)}"}), 500

    # Parse LLM response — json_schema should guarantee structured output
    raw_text = llm_result.get("result", "")
    structured = llm_result.get("structured_output")

    ai_sections = []
    ai_title = f"{template_name} Report"

    parsed = None
    if structured and isinstance(structured, dict):
        parsed = structured
    else:
        # Fallback: parse from raw text (strip markdown fences if present)
        try:
            text = raw_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            parsed = json.loads(text.strip())
        except (json.JSONDecodeError, TypeError):
            parsed = None

    if parsed and isinstance(parsed, dict):
        ai_title = parsed.get("title", ai_title)
        for s in parsed.get("sections", []):
            ai_sections.append({
                "heading": s.get("heading", ""),
                "content": s.get("content", ""),
                "data": {},
                "evidence_refs": [],
            })

    if not ai_sections:
        # Final fallback: use raw text as a single section
        ai_sections.append({
            "heading": template_name,
            "content": raw_text or "Report generation produced no content.",
            "data": {},
            "evidence_refs": [],
        })

    now = _now_iso()
    content_json = json.dumps({"sections": ai_sections, "gathered_data": gathered})
    metadata_json = json.dumps({
        "entity_ids": entity_ids,
        "audience": audience,
        "questions": questions,
        "template_slug": template,
        "model": model,
        "cost_usd": llm_result.get("cost_usd", 0),
        "duration_ms": llm_result.get("duration_ms", 0),
    })

    # Store
    with db._get_conn() as conn:
        _ensure_table(conn)
        cursor = conn.execute(
            """
            INSERT INTO workbench_reports
                (project_id, template, title, content_json, generated_at, is_ai_generated, metadata_json)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (project_id, template, ai_title, content_json, now, metadata_json),
        )
        report_id = cursor.lastrowid

    report = {
        "id": report_id,
        "project_id": project_id,
        "template": template,
        "title": ai_title,
        "sections": ai_sections,
        "generated_at": now,
        "updated_at": None,
        "is_ai_generated": True,
        "metadata": {
            "entity_ids": entity_ids,
            "audience": audience,
            "questions": questions,
            "template_slug": template,
            "model": model,
            "cost_usd": llm_result.get("cost_usd", 0),
            "duration_ms": llm_result.get("duration_ms", 0),
        },
    }

    logger.info(
        "Generated AI %s report #%d for project %d (model=%s, cost=$%.4f)",
        template, report_id, project_id, model, llm_result.get("cost_usd", 0),
    )
    return jsonify(report), 201


