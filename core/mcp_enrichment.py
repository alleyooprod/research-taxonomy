"""MCP enrichment orchestrator — enrich entities from external data sources.

Coordinates enrichment across multiple MCP-backed data sources (Hacker News,
DuckDuckGo News, Wikipedia, Cloudflare Radar, PatentsView, SEC EDGAR, UK
Companies House).  Each source has an adapter that:

1. Determines whether it applies to a given entity (type + conditions)
2. Calls the corresponding ``mcp_client`` function
3. Parses the raw result into entity attributes

The ``enrich_entity`` function is the main entry-point: it loads entity
context, selects applicable adapters, fetches data, and writes attributes
back to the database with staleness checking.
"""

import json
import time
from datetime import datetime, timedelta, timezone

from loguru import logger


# ── Parser Functions ──────────────────────────────────────────


def _parse_hackernews(result):
    """Parse Hacker News search results into entity attributes."""
    if not result:
        return []
    return [
        {"attr_slug": "hn_mention_count", "value": str(len(result)), "confidence": 0.9},
        {"attr_slug": "hn_top_story_url", "value": result[0].get("story_url", ""), "confidence": 0.9},
        {"attr_slug": "hn_top_story_points", "value": str(result[0].get("points", 0)), "confidence": 0.9},
    ]


def _parse_news(result):
    """Parse DuckDuckGo news search results into entity attributes."""
    if not result:
        return []
    latest = result[0]
    return [
        {"attr_slug": "recent_news_count", "value": str(len(result)), "confidence": 0.8},
        {"attr_slug": "latest_news_title", "value": latest.get("title", ""), "confidence": 0.8},
        {"attr_slug": "latest_news_url", "value": latest.get("url", ""), "confidence": 0.8},
    ]


def _parse_wikipedia(result):
    """Parse Wikipedia summary into entity attributes."""
    if not result:
        return []
    extract = result.get("extract", "")
    # Truncate to 500 characters
    if len(extract) > 500:
        extract = extract[:500]
    return [
        {"attr_slug": "wikipedia_summary", "value": extract, "confidence": 0.95},
        {"attr_slug": "wikipedia_url", "value": result.get("url", ""), "confidence": 0.95},
    ]


def _parse_domain_rank(result):
    """Parse Cloudflare Radar domain ranking into entity attributes."""
    if not result:
        return []
    return [
        {"attr_slug": "domain_rank", "value": str(result.get("rank", 0)), "confidence": 0.9},
        {"attr_slug": "domain_category", "value": result.get("category", ""), "confidence": 0.85},
    ]


def _parse_patents(result):
    """Parse PatentsView patent search results into entity attributes."""
    if not result:
        return []
    latest = result[0]
    return [
        {"attr_slug": "patent_count", "value": str(len(result)), "confidence": 0.9},
        {"attr_slug": "latest_patent_title", "value": latest.get("title", ""), "confidence": 0.9},
        {"attr_slug": "latest_patent_date", "value": latest.get("grant_date", ""), "confidence": 0.9},
    ]


def _parse_sec_edgar(result):
    """Parse SEC EDGAR filing results into entity attributes."""
    if not result:
        return []
    latest = result[0]
    return [
        {"attr_slug": "sec_cik", "value": latest.get("cik", ""), "confidence": 0.95},
        {"attr_slug": "latest_filing_type", "value": latest.get("filing_type", ""), "confidence": 0.95},
        {"attr_slug": "latest_filing_date", "value": latest.get("filed_date", ""), "confidence": 0.95},
    ]


def _parse_companies_house(result):
    """Parse UK Companies House search results into entity attributes."""
    if not result:
        return []
    top = result[0]
    sic = top.get("sic_codes", [])
    sic_str = json.dumps(sic) if isinstance(sic, list) else str(sic)
    return [
        {"attr_slug": "company_number", "value": top.get("company_number", ""), "confidence": 0.95},
        {"attr_slug": "company_status", "value": top.get("status", ""), "confidence": 0.95},
        {"attr_slug": "date_of_creation", "value": top.get("date_of_creation", ""), "confidence": 0.95},
        {"attr_slug": "sic_codes", "value": sic_str, "confidence": 0.9},
    ]


def _parse_wayback(result):
    """Parse Wayback Machine results into entity attributes."""
    if not result:
        return []
    return [
        {"attr_slug": "wayback_first_capture", "value": result.get("first_capture", ""), "confidence": 0.95},
        {"attr_slug": "wayback_last_capture", "value": result.get("last_capture", ""), "confidence": 0.95},
        {"attr_slug": "wayback_snapshot_count", "value": str(result.get("total_snapshots", 0)), "confidence": 0.95},
    ]


def _parse_fca_register(result):
    """Parse FCA Register results into entity attributes."""
    if not result:
        return []
    top = result[0]
    return [
        {"attr_slug": "fca_frn", "value": top.get("frn", ""), "confidence": 0.95},
        {"attr_slug": "fca_status", "value": top.get("status", ""), "confidence": 0.95},
        {"attr_slug": "fca_firm_type", "value": top.get("type", ""), "confidence": 0.9},
        {"attr_slug": "fca_effective_date", "value": top.get("effective_date", ""), "confidence": 0.9},
    ]


def _parse_gleif(result):
    """Parse GLEIF results into entity attributes."""
    if not result:
        return []
    top = result[0]
    return [
        {"attr_slug": "lei_code", "value": top.get("lei", ""), "confidence": 0.95},
        {"attr_slug": "lei_status", "value": top.get("status", ""), "confidence": 0.95},
        {"attr_slug": "legal_jurisdiction", "value": top.get("jurisdiction", ""), "confidence": 0.9},
    ]


def _parse_cooper_hewitt(result):
    """Parse Cooper Hewitt Museum results into entity attributes."""
    if not result:
        return []
    titles = [obj.get("title", "") for obj in result[:3] if obj.get("title")]
    return [
        {"attr_slug": "related_design_objects", "value": json.dumps(titles), "confidence": 0.7},
    ]


# ── Adapter Registry ─────────────────────────────────────────

_ADAPTERS = [
    {
        "name": "hackernews",
        "description": "Hacker News mentions",
        "fn": "search_hackernews",
        "applies_to": "*",
        "conditions": {},
        "priority": 20,
        "parse": _parse_hackernews,
    },
    {
        "name": "news",
        "description": "Recent news articles",
        "fn": "search_news",
        "applies_to": "*",
        "conditions": {},
        "priority": 20,
        "parse": _parse_news,
    },
    {
        "name": "wikipedia",
        "description": "Wikipedia summary",
        "fn": "search_wikipedia",
        "applies_to": "*",
        "conditions": {},
        "priority": 15,
        "parse": _parse_wikipedia,
    },
    {
        "name": "domain_rank",
        "description": "Cloudflare Radar domain ranking",
        "fn": "get_domain_rank",
        "applies_to": "*",
        "conditions": {"has_url": True},
        "priority": 10,
        "parse": _parse_domain_rank,
    },
    {
        "name": "patents",
        "description": "USPTO patent search",
        "fn": "search_patents",
        "applies_to": "*",
        "conditions": {},
        "priority": 15,
        "parse": _parse_patents,
    },
    {
        "name": "sec_edgar",
        "description": "SEC EDGAR filings",
        "fn": "search_sec_filings",
        "applies_to": "company",
        "conditions": {"country": "US"},
        "priority": 5,
        "parse": _parse_sec_edgar,
    },
    {
        "name": "companies_house",
        "description": "UK Companies House register",
        "fn": "search_companies_house",
        "applies_to": "company",
        "conditions": {"country": "UK"},
        "priority": 5,
        "parse": _parse_companies_house,
    },
    {
        "name": "wayback_machine",
        "description": "Internet Archive historical snapshots",
        "fn": "search_wayback",
        "applies_to": "*",
        "conditions": {"has_url": True},
        "priority": 15,
        "parse": _parse_wayback,
    },
    {
        "name": "fca_register",
        "description": "UK Financial Conduct Authority register",
        "fn": "search_fca_register",
        "applies_to": "company",
        "conditions": {"country": "UK"},
        "priority": 5,
        "parse": _parse_fca_register,
    },
    {
        "name": "gleif",
        "description": "GLEIF Legal Entity Identifier lookup",
        "fn": "search_gleif",
        "applies_to": "company",
        "conditions": {},
        "priority": 10,
        "parse": _parse_gleif,
    },
    {
        "name": "cooper_hewitt",
        "description": "Cooper Hewitt Smithsonian Design Museum",
        "fn": "search_cooper_hewitt",
        "applies_to": ["product", "design"],
        "conditions": {},
        "priority": 25,
        "parse": _parse_cooper_hewitt,
    },
]


# ── URL attribute slugs we look for when building context ─────

_URL_SLUGS = {"website", "url", "homepage", "store_url"}
_COUNTRY_SLUGS = {"country", "hq_country", "headquarters_country"}


# ── Context & Selection ───────────────────────────────────────


def build_entity_context(entity, attributes):
    """Extract enrichment-relevant context from an entity and its attributes.

    Args:
        entity: dict from ``db.get_entity()``
        attributes: dict of ``{attr_slug: {value, source, confidence, captured_at}}``

    Returns:
        dict with keys: entity_id, name, type_slug, url, country, has_url,
        existing_attrs (set of attr_slug strings).
    """
    # Find URL from common attribute slugs
    url = None
    for slug in _URL_SLUGS:
        attr = attributes.get(slug)
        if attr and attr.get("value"):
            url = attr["value"]
            break

    # Find country from common attribute slugs
    country = None
    for slug in _COUNTRY_SLUGS:
        attr = attributes.get(slug)
        if attr and attr.get("value"):
            country = attr["value"]
            break

    return {
        "entity_id": entity.get("id"),
        "name": entity.get("name", ""),
        "type_slug": entity.get("type_slug", ""),
        "url": url,
        "country": country,
        "has_url": bool(url),
        "existing_attrs": set(attributes.keys()),
    }


def select_adapters(context, server_filter=None):
    """Select applicable adapters for the given entity context.

    Filters by:
    - ``applies_to`` matches ``type_slug`` (or ``"*"`` for any type)
    - All conditions are met (``has_url``, ``country``, etc.)
    - ``server_filter`` list (if provided, only adapters whose name is in the list)

    Returns:
        list of adapter dicts, sorted by priority ascending (lower = higher priority).
    """
    selected = []
    for adapter in _ADAPTERS:
        # Check type match (supports "*", single string, or list of strings)
        applies = adapter["applies_to"]
        type_slug = context.get("type_slug", "")
        if applies != "*":
            if isinstance(applies, list):
                if type_slug not in applies:
                    continue
            elif applies != type_slug:
                continue

        # Check conditions
        conditions_met = True
        for key, expected in adapter["conditions"].items():
            actual = context.get(key)
            if isinstance(expected, bool):
                if bool(actual) != expected:
                    conditions_met = False
                    break
            else:
                if actual != expected:
                    conditions_met = False
                    break
        if not conditions_met:
            continue

        # Check server filter
        if server_filter is not None and adapter["name"] not in server_filter:
            continue

        selected.append(adapter)

    # Sort by priority ascending (lower priority number = higher precedence)
    selected.sort(key=lambda a: a["priority"])
    return selected


def check_staleness(db, entity_id, attr_slug, max_age_hours=168):
    """Check whether an attribute is stale (older than ``max_age_hours``).

    Returns True if the attribute is missing or its ``captured_at`` timestamp
    is older than the threshold.  Returns False if the attribute is fresh.
    """
    entity = db.get_entity(entity_id)
    if not entity:
        return True

    attributes = entity.get("attributes", {})
    attr = attributes.get(attr_slug)
    if not attr:
        return True

    captured_at = attr.get("captured_at")
    if not captured_at:
        return True

    # Parse captured_at timestamp
    try:
        # Handle ISO format strings
        captured_at_str = captured_at.replace("Z", "+00:00")
        try:
            captured_dt = datetime.fromisoformat(captured_at_str)
        except ValueError:
            captured_dt = datetime.strptime(captured_at_str, "%Y-%m-%dT%H:%M:%S%z")

        # If no timezone info, assume UTC
        if captured_dt.tzinfo is None:
            captured_dt = captured_dt.replace(tzinfo=timezone.utc)

        threshold = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        return captured_dt < threshold
    except (ValueError, TypeError):
        # If we can't parse the timestamp, consider it stale
        return True


# ── Enrichment Orchestration ──────────────────────────────────


def _extract_domain(url):
    """Extract the domain from a URL for domain_rank lookups."""
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        # Strip www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain if domain else None
    except Exception:
        return None


def _call_adapter(adapter, context, conn):
    """Call an adapter's mcp_client function with the right arguments.

    Returns the raw result from the API call, or None on error.
    """
    import core.mcp_client as mcp_client

    fn_name = adapter["fn"]
    fn = getattr(mcp_client, fn_name, None)
    if fn is None:
        logger.error("Unknown mcp_client function: {}", fn_name)
        return None

    name = context.get("name", "")
    adapter_name = adapter["name"]

    try:
        if adapter_name == "domain_rank":
            domain = _extract_domain(context.get("url"))
            if not domain:
                return None
            result = fn(domain, conn=conn)
        elif adapter_name == "wayback_machine":
            url = context.get("url")
            if not url:
                return None
            result = fn(url, conn=conn)
        elif adapter_name in ("sec_edgar", "companies_house", "fca_register",
                              "gleif", "patents", "cooper_hewitt"):
            result = fn(name, conn=conn)
        else:
            # hackernews, news, wikipedia all take a query string
            result = fn(name, conn=conn)

        # Record health status
        _record_health(conn, adapter_name, success=result is not None)
        return result
    except Exception as exc:
        logger.warning("Adapter {} failed for entity {}: {}", adapter_name, name, exc)
        _record_health(conn, adapter_name, success=False)
        return None


def enrich_entity(entity_id, db, servers=None, max_age_hours=168):
    """Enrich a single entity from MCP data sources.

    Steps:
        1. Load entity + attributes from the database.
        2. Build context (name, type, URL, country).
        3. Select applicable adapters (optionally filtered by ``servers``).
        4. For each adapter, call the API, parse results, check staleness,
           and collect attributes to write.
        5. Create a snapshot for this enrichment batch.
        6. Write all attributes via ``db.set_entity_attributes()``.

    Args:
        entity_id: ID of the entity to enrich.
        db: Database instance.
        servers: Optional list of adapter names to restrict to.
        max_age_hours: Skip attributes fresher than this (default 168 = 7 days).

    Returns:
        dict with keys: entity_id, enriched_count, skipped_count,
        servers_used, errors, attributes.
    """
    summary = {
        "entity_id": entity_id,
        "enriched_count": 0,
        "skipped_count": 0,
        "servers_used": [],
        "errors": [],
        "attributes": [],
    }

    # Load entity
    entity = db.get_entity(entity_id)
    if not entity:
        summary["errors"].append({"server": "_system", "error": f"Entity {entity_id} not found"})
        return summary

    attributes = entity.get("attributes", {})
    context = build_entity_context(entity, attributes)

    # Select adapters
    adapters = select_adapters(context, server_filter=servers)
    if not adapters:
        logger.info("No applicable adapters for entity {} ({})", entity_id, entity.get("name"))
        return summary

    # Get a DB connection for caching
    conn = db._get_conn()
    try:
        # Collect all attributes to write
        attrs_to_write = {}
        confidence_map = {}

        for adapter in adapters:
            adapter_name = adapter["name"]
            try:
                raw_result = _call_adapter(adapter, context, conn)
                parsed = adapter["parse"](raw_result)
            except Exception as exc:
                logger.warning("Adapter {} error for entity {}: {}", adapter_name, entity_id, exc)
                summary["errors"].append({"server": adapter_name, "error": str(exc)})
                continue

            if not parsed:
                continue

            # Check staleness and collect fresh attributes
            adapter_attr_count = 0
            for attr_item in parsed:
                slug = attr_item["attr_slug"]
                value = attr_item["value"]
                conf = attr_item.get("confidence")

                # Skip if value is empty
                if not value and value != "0":
                    continue

                # Check staleness
                if not check_staleness(db, entity_id, slug, max_age_hours):
                    summary["skipped_count"] += 1
                    continue

                attrs_to_write[slug] = str(value)
                confidence_map[slug] = conf
                adapter_attr_count += 1
                summary["attributes"].append({
                    "attr_slug": slug,
                    "value": str(value),
                    "source": f"mcp:{adapter_name}",
                })

            if adapter_attr_count > 0:
                summary["servers_used"].append({
                    "name": adapter_name,
                    "attr_count": adapter_attr_count,
                })

        # Write all collected attributes
        if attrs_to_write:
            # Create snapshot for this enrichment batch
            project_id = entity.get("project_id")
            snapshot_id = db.create_snapshot(
                project_id,
                description=f"MCP enrichment for {entity.get('name', 'entity')}",
            )

            # Group by source for proper attribution
            source_groups = {}
            for attr_info in summary["attributes"]:
                source = attr_info["source"]
                slug = attr_info["attr_slug"]
                if source not in source_groups:
                    source_groups[source] = {}
                source_groups[source][slug] = attrs_to_write[slug]

            for source, attr_dict in source_groups.items():
                # Use the minimum confidence for this source group
                slugs_in_group = list(attr_dict.keys())
                conf_vals = [confidence_map.get(s) for s in slugs_in_group if confidence_map.get(s) is not None]
                conf = min(conf_vals) if conf_vals else None
                db.set_entity_attributes(
                    entity_id,
                    attr_dict,
                    source=source,
                    confidence=conf,
                    snapshot_id=snapshot_id,
                )

            summary["enriched_count"] = len(attrs_to_write)
            logger.info(
                "Enriched entity {} ({}) with {} attributes from {} sources",
                entity_id,
                entity.get("name"),
                summary["enriched_count"],
                len(summary["servers_used"]),
            )
    finally:
        conn.close()

    return summary


# ── Health Tracking ───────────────────────────────────────────


def _record_health(conn, server_name, success):
    """Record success/failure for a server in the cache table.

    Uses cache key ``health:{server_name}`` with a 30-day TTL.
    """
    if conn is None:
        return
    try:
        from core.mcp_client import _cache_get, _cache_set
        key = f"health:{server_name}"
        existing = _cache_get(conn, key)
        if existing is None:
            existing = {"last_success": None, "last_failure": None, "consecutive_failures": 0}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if success:
            existing["last_success"] = now
            existing["consecutive_failures"] = 0
        else:
            existing["last_failure"] = now
            existing["consecutive_failures"] = existing.get("consecutive_failures", 0) + 1
        _cache_set(conn, key, "health", existing, ttl_hours=720)
    except Exception as exc:
        logger.debug("Health tracking failed for {}: {}", server_name, exc)


def get_server_health(conn, server_name):
    """Read health status for a server from cache.

    Returns dict with keys: last_success, last_failure, consecutive_failures.
    """
    if conn is None:
        return {"last_success": None, "last_failure": None, "consecutive_failures": 0}
    try:
        from core.mcp_client import _cache_get
        result = _cache_get(conn, f"health:{server_name}")
        return result or {"last_success": None, "last_failure": None, "consecutive_failures": 0}
    except Exception:
        return {"last_success": None, "last_failure": None, "consecutive_failures": 0}


def get_all_server_health(conn):
    """Read health status for all servers in the catalogue.

    Returns dict mapping server_name to health dict.
    """
    try:
        from core.mcp_catalogue import SERVER_CATALOGUE
        return {name: get_server_health(conn, name) for name in SERVER_CATALOGUE}
    except ImportError:
        return {}


# ── Smart Routing ────────────────────────────────────────────


def _score_server(cap, context, intent=None, health=None):
    """Compute a relevance score for a server given entity context.

    Higher score = more relevant.

    Factors:
    - Base: ``100 - priority`` (lower priority number = higher score)
    - +20 if entity type matches ``applies_to``
    - +15 if ``intent`` matches one of the server's categories
    - +10 if any ``provides`` tag matches existing entity context hints
    - -10 if ``cost_tier`` is ``free_key`` and env key is not set
    - -20 per consecutive failure (health penalty, capped at -60)
    """
    import os

    score = 100 - cap.priority

    # Entity-type match bonus
    type_slug = context.get("type_slug", "")
    applies = cap.applies_to
    if applies == "*":
        score += 5  # Small bonus for universal applicability
    elif isinstance(applies, list):
        if type_slug in applies:
            score += 20
    elif applies == type_slug:
        score += 20

    # Intent match bonus
    if intent and intent in cap.categories:
        score += 15

    # Key availability penalty
    if cap.env_key and not os.environ.get(cap.env_key):
        score -= 10

    # Health penalty
    if health:
        failures = health.get("consecutive_failures", 0)
        score -= min(failures * 20, 60)

    return score


def recommend_servers(context, intent=None, max_servers=10, conn=None):
    """Score-based server recommendation using the catalogue.

    Goes beyond ``select_adapters()`` by scoring with catalogue metadata
    for ranking and token-cost-aware recommendations.

    Args:
        context: Entity context from ``build_entity_context()``.
        intent: Optional hint like ``"financial"``, ``"regulatory"``,
                ``"design"``, or ``"news"``.
        max_servers: Maximum number to recommend.
        conn: Optional DB connection for health lookups.

    Returns:
        list of dicts with ``name``, ``display_name``, ``description``,
        ``reason``, ``score``, ``cost_tier``, ``categories``.
    """
    # Get hard-filtered adapters
    adapters = select_adapters(context)
    adapter_names = {a["name"] for a in adapters}

    try:
        from core.mcp_catalogue import SERVER_CATALOGUE
    except ImportError:
        # Fallback: just return adapters without scoring
        return [
            {"name": a["name"], "description": a.get("description", ""),
             "score": 100 - a.get("priority", 20), "reason": "Applicable adapter"}
            for a in adapters[:max_servers]
        ]

    # Score each eligible adapter using catalogue metadata
    scored = []
    for name in adapter_names:
        cap = SERVER_CATALOGUE.get(name)
        if not cap:
            continue
        health = get_server_health(conn, name) if conn else None
        score = _score_server(cap, context, intent=intent, health=health)
        scored.append({
            "name": name,
            "display_name": cap.display_name,
            "description": cap.description,
            "score": score,
            "cost_tier": cap.cost_tier,
            "categories": cap.categories,
            "reason": _build_recommendation_reason(cap, context, intent),
        })

    # Sort by score descending
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:max_servers]


def _build_recommendation_reason(cap, context, intent=None):
    """Build a human-readable reason for recommending a server."""
    type_slug = context.get("type_slug", "")
    country = context.get("country", "")

    if cap.name == "fca_register" and country == "UK":
        return "UK company — FCA regulatory data available"
    if cap.name == "companies_house" and country == "UK":
        return "UK company — Companies House registration data"
    if cap.name == "sec_edgar" and country == "US":
        return "US company — SEC filings available"
    if cap.name == "gleif":
        return "Legal Entity Identifier (LEI) lookup for corporate identity"
    if cap.name == "wayback_machine":
        return "Website has URL — historical snapshots available"
    if cap.name == "cooper_hewitt" and type_slug in ("product", "design"):
        return "Design entity — related museum objects available"
    if intent and intent in cap.categories:
        return f"Matches research intent: {intent}"
    return cap.description


def enrich_batch(entity_ids, db, servers=None, max_age_hours=168, delay=1.0):
    """Enrich multiple entities sequentially with a delay between each.

    Args:
        entity_ids: List of entity IDs to enrich.
        db: Database instance.
        servers: Optional list of adapter names to restrict to.
        max_age_hours: Skip attributes fresher than this (default 168 = 7 days).
        delay: Seconds to sleep between entities (default 1.0).

    Returns:
        dict with keys: total, enriched, errors, results.
    """
    results = []
    enriched_count = 0
    error_count = 0

    for i, eid in enumerate(entity_ids):
        result = enrich_entity(eid, db, servers=servers, max_age_hours=max_age_hours)
        results.append(result)

        if result.get("enriched_count", 0) > 0:
            enriched_count += 1
        if result.get("errors"):
            error_count += 1

        # Sleep between entities (but not after the last one)
        if delay > 0 and i < len(entity_ids) - 1:
            time.sleep(delay)

    return {
        "total": len(entity_ids),
        "enriched": enriched_count,
        "errors": error_count,
        "results": results,
    }
