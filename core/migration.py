"""Company → Entity migration utility.

Migrates existing company data from the flat `companies` table into the
entity system (entities + entity_attributes), preserving all data.

Usage:
    from core.migration import migrate_companies_to_entities
    stats = migrate_companies_to_entities(db, project_id)

Each company becomes an entity of type_slug="company" with its columns mapped
to entity_attributes. Evidence (company_sources) is migrated too.

The migration is idempotent — running it twice will not create duplicates.
"""
import json
from datetime import datetime

from loguru import logger


# Column → attribute slug mapping.
# Only columns that carry meaningful data are migrated.
# Structural/meta columns (id, slug, project_id, etc.) are handled separately.
_COMPANY_FIELD_MAP = {
    "url": "website",
    "what": "description",
    "target": "target_market",
    "products": "products",
    "funding": "funding",
    "geography": "geography",
    "tam": "tam",
    "logo_url": "logo_url",
    "employee_range": "employee_range",
    "founded_year": "founded_year",
    "funding_stage": "funding_stage",
    "total_funding_usd": "total_funding_usd",
    "hq_city": "hq_city",
    "hq_country": "hq_country",
    "linkedin_url": "linkedin_url",
    "business_model": "business_model",
    "company_stage": "company_stage",
    "primary_focus": "primary_focus",
    "pricing_model": "pricing_model",
    "pricing_b2c_low": "pricing_b2c_low",
    "pricing_b2c_high": "pricing_b2c_high",
    "pricing_b2b_low": "pricing_b2b_low",
    "pricing_b2b_high": "pricing_b2b_high",
    "has_free_tier": "has_free_tier",
    "revenue_model": "revenue_model",
    "pricing_tiers": "pricing_tiers",
    "pricing_notes": "pricing_notes",
    "relationship_status": "relationship_status",
    "relationship_note": "relationship_note",
}


def migrate_companies_to_entities(db, project_id, dry_run=False):
    """Migrate all companies in a project to the entity system.

    Args:
        db: Database instance
        project_id: Project to migrate
        dry_run: If True, count but don't actually write

    Returns:
        dict with migration stats: {
            companies_found, entities_created, attributes_created,
            evidence_migrated, skipped_already_migrated, errors
        }
    """
    stats = {
        "companies_found": 0,
        "entities_created": 0,
        "attributes_created": 0,
        "evidence_migrated": 0,
        "skipped_already_migrated": 0,
        "errors": [],
    }

    with db._get_conn() as conn:
        # 1. Check if companies table exists
        tbl = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='companies'"
        ).fetchone()
        if not tbl:
            logger.info("No companies table found — nothing to migrate")
            return stats

        # 2. Get all non-deleted companies for this project
        companies = conn.execute(
            """SELECT * FROM companies
               WHERE project_id = ? AND is_deleted = 0
               ORDER BY id""",
            (project_id,),
        ).fetchall()
        stats["companies_found"] = len(companies)

        if not companies:
            logger.info("No companies found for project %d", project_id)
            return stats

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for company in companies:
            c = dict(company)
            company_name = c["name"]
            company_slug = c.get("slug") or company_name.lower().replace(" ", "_")

            # 3. Check if already migrated (entity with same name + type_slug="company")
            existing = conn.execute(
                """SELECT id FROM entities
                   WHERE project_id = ? AND type_slug = 'company'
                     AND name = ? AND is_deleted = 0""",
                (project_id, company_name),
            ).fetchone()

            if existing:
                stats["skipped_already_migrated"] += 1
                continue

            if dry_run:
                stats["entities_created"] += 1
                # Count attributes that would be created
                for col, slug in _COMPANY_FIELD_MAP.items():
                    val = c.get(col)
                    if val is not None and str(val).strip():
                        stats["attributes_created"] += 1
                continue

            try:
                # 4. Create entity
                conn.execute(
                    """INSERT INTO entities
                       (project_id, type_slug, name, slug, category_id,
                        is_starred, status, confidence_score, tags,
                        raw_research, source, created_at, updated_at)
                       VALUES (?, 'company', ?, ?, ?, ?, ?, ?, ?, ?, 'migration', ?, ?)""",
                    (
                        project_id,
                        company_name,
                        company_slug,
                        c.get("category_id"),
                        c.get("is_starred", 0),
                        c.get("status", "active"),
                        c.get("confidence_score"),
                        c.get("tags"),
                        c.get("raw_research"),
                        c.get("updated_at") or now,
                        now,
                    ),
                )
                entity_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                stats["entities_created"] += 1

                # 5. Migrate columns to entity_attributes
                captured_at = c.get("updated_at") or c.get("processed_at") or now

                for col, attr_slug in _COMPANY_FIELD_MAP.items():
                    val = c.get(col)
                    if val is None:
                        continue
                    val_str = str(val).strip()
                    if not val_str:
                        continue

                    conn.execute(
                        """INSERT INTO entity_attributes
                           (entity_id, attr_slug, value, source, confidence, captured_at)
                           VALUES (?, ?, ?, 'migration', ?, ?)""",
                        (entity_id, attr_slug, val_str, c.get("confidence_score"), captured_at),
                    )
                    stats["attributes_created"] += 1

                # 6. Migrate company_sources → evidence
                sources = conn.execute(
                    """SELECT url, source_type, added_at FROM company_sources
                       WHERE company_id = ?""",
                    (c["id"],),
                ).fetchall()

                for src in sources:
                    # file_path is NOT NULL — use a migration placeholder
                    placeholder_path = f"migrated/{company_slug}/{src['source_type'] or 'research'}.url"
                    conn.execute(
                        """INSERT INTO evidence
                           (entity_id, evidence_type, file_path, source_url,
                            source_name, captured_at)
                           VALUES (?, 'page_archive', ?, ?, ?, ?)""",
                        (
                            entity_id,
                            placeholder_path,
                            src["url"],
                            src["source_type"] or "research",
                            src["added_at"] or now,
                        ),
                    )
                    stats["evidence_migrated"] += 1

                logger.debug(
                    "Migrated company '%s' (id=%d) → entity id=%d",
                    company_name, c["id"], entity_id,
                )

            except Exception as e:
                error_msg = f"Failed to migrate company '{company_name}' (id={c['id']}): {e}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)

        if not dry_run:
            conn.commit()

    logger.info(
        "Migration complete: %d companies → %d entities, %d attributes, %d evidence, %d skipped, %d errors",
        stats["companies_found"],
        stats["entities_created"],
        stats["attributes_created"],
        stats["evidence_migrated"],
        stats["skipped_already_migrated"],
        len(stats["errors"]),
    )

    return stats
