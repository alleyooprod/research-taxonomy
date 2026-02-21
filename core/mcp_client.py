"""Direct API wrappers for public data sources behind configured MCP servers.

Each function calls the upstream API, normalises the result, and optionally
caches in SQLite.  Functions accept an optional ``conn`` parameter — if
provided the response is cached (and cache hits are returned on subsequent
calls within the TTL window).

Supported sources:
  - Hacker News (Algolia)
  - DuckDuckGo News (via duckduckgo_search)
  - Cloudflare Radar domain ranking
  - PatentsView (USPTO)
  - SEC EDGAR full-text search
  - UK Companies House
  - Wikipedia REST + search
"""
import json
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

from loguru import logger

# ── Constants ─────────────────────────────────────────────────

_REQUEST_TIMEOUT = 15
_USER_AGENT = "ResearchWorkbench/1.0"
_DEFAULT_TTL_HOURS = 24


# ── Lazy Cache Table Creation ─────────────────────────────────

_CACHE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mcp_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
"""

_CACHE_TABLE_ENSURED = False


def _ensure_cache_table(conn):
    """Create the mcp_cache table if it doesn't exist yet."""
    global _CACHE_TABLE_ENSURED
    if not _CACHE_TABLE_ENSURED:
        conn.execute(_CACHE_TABLE_SQL)
        conn.commit()
        _CACHE_TABLE_ENSURED = True


def _now_iso():
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(dt_str):
    """Parse an ISO-8601 datetime string."""
    # Handle both with and without Z suffix
    dt_str = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S%z")


# ── Cache Helpers ─────────────────────────────────────────────

def _cache_get(conn, key):
    """Return parsed JSON if cached entry exists and is not expired, else None."""
    _ensure_cache_table(conn)
    row = conn.execute(
        "SELECT data_json, expires_at FROM mcp_cache WHERE cache_key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    expires_at = _parse_iso(row["expires_at"] if hasattr(row, "keys") else row[1])
    now = datetime.now(timezone.utc)
    if now >= expires_at:
        return None
    data_json = row["data_json"] if hasattr(row, "keys") else row[0]
    return json.loads(data_json)


def _cache_set(conn, key, source, data, ttl_hours=_DEFAULT_TTL_HOURS):
    """Upsert a cache entry with the given TTL."""
    _ensure_cache_table(conn)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)
    conn.execute(
        """INSERT INTO mcp_cache (cache_key, source, data_json, fetched_at, expires_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(cache_key) DO UPDATE SET
               source = excluded.source,
               data_json = excluded.data_json,
               fetched_at = excluded.fetched_at,
               expires_at = excluded.expires_at""",
        (
            key,
            source,
            json.dumps(data),
            now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    conn.commit()


# ── 1. Hacker News (Algolia) ─────────────────────────────────

def search_hackernews(query, num_results=10, timeout=_REQUEST_TIMEOUT, conn=None):
    """Search Hacker News stories via the Algolia API.

    Returns list of dicts with keys: title, url, points, num_comments,
    story_id, created_at, story_url.  Returns None on error.
    """
    if not query:
        return []

    cache_key = f"hn:{query}:{num_results}"
    if conn is not None:
        try:
            cached = _cache_get(conn, cache_key)
            if cached is not None:
                return cached
        except Exception as exc:
            logger.warning("HN cache read failed: {}", exc)

    try:
        import requests as req_lib
        url = (
            "https://hn.algolia.com/api/v1/search"
            f"?query={urllib.parse.quote_plus(query)}"
            f"&tags=story&hitsPerPage={num_results}"
        )
        resp = req_lib.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Hacker News search failed: {}", exc)
        return None

    results = []
    for hit in data.get("hits", []):
        results.append({
            "title": hit.get("title", ""),
            "url": hit.get("url", ""),
            "points": hit.get("points", 0),
            "num_comments": hit.get("num_comments", 0),
            "story_id": str(hit.get("objectID", "")),
            "created_at": hit.get("created_at", ""),
            "story_url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
        })

    if conn is not None:
        try:
            _cache_set(conn, cache_key, "hackernews", results)
        except Exception as exc:
            logger.warning("HN cache write failed: {}", exc)

    return results


# ── 2. DuckDuckGo News ────────────────────────────────────────

def search_news(query, num_results=10, timeout=_REQUEST_TIMEOUT, conn=None):
    """Search news articles via DuckDuckGo.

    Returns list of dicts with keys: title, url, snippet, source,
    published_date.  Returns None on error.
    """
    if not query:
        return []

    cache_key = f"news:{query}:{num_results}"
    if conn is not None:
        try:
            cached = _cache_get(conn, cache_key)
            if cached is not None:
                return cached
        except Exception as exc:
            logger.warning("News cache read failed: {}", exc)

    try:
        from duckduckgo_search import DDGS
        raw_results = DDGS().news(query, max_results=num_results)
    except Exception as exc:
        logger.warning("DuckDuckGo news search failed: {}", exc)
        return None

    results = []
    for item in (raw_results or []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("body", ""),
            "source": item.get("source", ""),
            "published_date": item.get("date", ""),
        })

    if conn is not None:
        try:
            _cache_set(conn, cache_key, "duckduckgo_news", results)
        except Exception as exc:
            logger.warning("News cache write failed: {}", exc)

    return results


# ── 3. Cloudflare Radar Domain Ranking ────────────────────────

def get_domain_rank(domain, timeout=_REQUEST_TIMEOUT, conn=None):
    """Look up a domain's Cloudflare Radar popularity ranking.

    Requires CLOUDFLARE_API_TOKEN env var.
    Returns dict with keys: domain, rank, category.  Returns None on error
    or if the API token is not configured.
    """
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        logger.debug("CLOUDFLARE_API_TOKEN not set — skipping domain rank lookup")
        return None

    if not domain:
        return None

    cache_key = f"traffic:{domain}"
    if conn is not None:
        try:
            cached = _cache_get(conn, cache_key)
            if cached is not None:
                return cached
        except Exception as exc:
            logger.warning("Domain rank cache read failed: {}", exc)

    try:
        import requests as req_lib
        url = f"https://api.cloudflare.com/client/v4/radar/ranking/domain/{urllib.parse.quote(domain)}"
        resp = req_lib.get(
            url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": _USER_AGENT,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Cloudflare domain rank lookup failed for {}: {}", domain, exc)
        return None

    # Navigate the Cloudflare response structure
    try:
        result_data = data.get("result", {})
        details = result_data.get("details_0", result_data)
        top = details.get("top", [])
        rank_val = top[0].get("rank", 0) if top else details.get("rank", 0)
        categories = details.get("categories", [])
        category = categories[0].get("name", "") if categories else ""
    except (KeyError, IndexError, TypeError):
        rank_val = 0
        category = ""

    result = {
        "domain": domain,
        "rank": rank_val,
        "category": category,
    }

    if conn is not None:
        try:
            _cache_set(conn, cache_key, "cloudflare_radar", result)
        except Exception as exc:
            logger.warning("Domain rank cache write failed: {}", exc)

    return result


# ── 4. PatentsView (USPTO) ────────────────────────────────────

def search_patents(assignee, num_results=10, timeout=_REQUEST_TIMEOUT, conn=None):
    """Search USPTO patents by assignee organisation via PatentsView.

    Returns list of dicts with keys: patent_id, title, filing_date,
    grant_date, assignee, abstract.  Returns None on error.
    """
    if not assignee:
        return []

    cache_key = f"patent:{assignee}:{num_results}"
    if conn is not None:
        try:
            cached = _cache_get(conn, cache_key)
            if cached is not None:
                return cached
        except Exception as exc:
            logger.warning("Patent cache read failed: {}", exc)

    body = {
        "q": {"_contains": {"assignee_organization": assignee}},
        "f": [
            "patent_id", "patent_title", "patent_date", "patent_abstract",
            "assignee_organization", "inventor_first_name", "inventor_last_name",
        ],
        "o": {"page": 1, "per_page": num_results},
        "s": [{"patent_date": "desc"}],
    }

    try:
        import requests as req_lib
        resp = req_lib.post(
            "https://api.patentsview.org/patents/query",
            json=body,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("PatentsView search failed for {}: {}", assignee, exc)
        return None

    patents = data.get("patents") or []
    results = []
    for p in patents:
        results.append({
            "patent_id": p.get("patent_id", ""),
            "title": p.get("patent_title", ""),
            "filing_date": "",  # PatentsView returns grant date as patent_date
            "grant_date": p.get("patent_date", ""),
            "assignee": (p.get("assignees", [{}])[0].get("assignee_organization", "")
                         if p.get("assignees") else
                         p.get("assignee_organization", assignee)),
            "abstract": p.get("patent_abstract", ""),
        })

    if conn is not None:
        try:
            _cache_set(conn, cache_key, "patentsview", results)
        except Exception as exc:
            logger.warning("Patent cache write failed: {}", exc)

    return results


# ── 5. SEC EDGAR ──────────────────────────────────────────────

def search_sec_filings(company, filing_type="10-K", num_results=5,
                       timeout=_REQUEST_TIMEOUT, conn=None):
    """Search SEC EDGAR full-text search index.

    Returns list of dicts with keys: filing_type, filed_date, url,
    company_name, cik, accession_number.  Returns None on error.
    """
    if not company:
        return []

    cache_key = f"sec:{company}:{filing_type}:{num_results}"
    if conn is not None:
        try:
            cached = _cache_get(conn, cache_key)
            if cached is not None:
                return cached
        except Exception as exc:
            logger.warning("SEC cache read failed: {}", exc)

    try:
        import requests as req_lib
        url = (
            "https://efts.sec.gov/LATEST/search-index"
            f"?q={urllib.parse.quote_plus(company)}"
            f"&dateRange=custom&startdt=2020-01-01"
            f"&forms={urllib.parse.quote_plus(filing_type)}"
            f"&from=0&size={num_results}"
        )
        resp = req_lib.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("SEC EDGAR search failed for {}: {}", company, exc)
        return None

    hits = data.get("hits", {}).get("hits", [])
    results = []
    for hit in hits:
        src = hit.get("_source", {})
        accession = src.get("file_num", "") or src.get("accession_no", "")
        results.append({
            "filing_type": src.get("form_type", filing_type),
            "filed_date": src.get("file_date", ""),
            "url": src.get("file_url", ""),
            "company_name": src.get("display_names", [src.get("entity_name", company)])[0]
                if src.get("display_names") else src.get("entity_name", company),
            "cik": str(src.get("entity_id", "")),
            "accession_number": accession,
        })

    if conn is not None:
        try:
            _cache_set(conn, cache_key, "sec_edgar", results)
        except Exception as exc:
            logger.warning("SEC cache write failed: {}", exc)

    return results


# ── 6. UK Companies House ─────────────────────────────────────

def search_companies_house(name, timeout=_REQUEST_TIMEOUT, conn=None):
    """Search the UK Companies House register by company name.

    Requires COMPANIES_HOUSE_API_KEY env var.
    Returns list of dicts with keys: company_number, name, status,
    date_of_creation, sic_codes, address.  Returns None on error or if
    the API key is not configured.
    """
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not api_key:
        logger.debug("COMPANIES_HOUSE_API_KEY not set — skipping Companies House lookup")
        return None

    if not name:
        return []

    cache_key = f"ch:{name}"
    if conn is not None:
        try:
            cached = _cache_get(conn, cache_key)
            if cached is not None:
                return cached
        except Exception as exc:
            logger.warning("Companies House cache read failed: {}", exc)

    try:
        import requests as req_lib
        url = (
            "https://api.company-information.service.gov.uk/search/companies"
            f"?q={urllib.parse.quote_plus(name)}&items_per_page=5"
        )
        resp = req_lib.get(
            url,
            timeout=timeout,
            auth=(api_key, ""),
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Companies House search failed for {}: {}", name, exc)
        return None

    items = data.get("items", [])
    results = []
    for item in items:
        addr = item.get("address", {})
        addr_str = ", ".join(
            filter(None, [
                addr.get("address_line_1", ""),
                addr.get("locality", ""),
                addr.get("postal_code", ""),
            ])
        )
        results.append({
            "company_number": item.get("company_number", ""),
            "name": item.get("title", ""),
            "status": item.get("company_status", ""),
            "date_of_creation": item.get("date_of_creation", ""),
            "sic_codes": item.get("sic_codes", []),
            "address": addr_str,
        })

    if conn is not None:
        try:
            _cache_set(conn, cache_key, "companies_house", results)
        except Exception as exc:
            logger.warning("Companies House cache write failed: {}", exc)

    return results


# ── 7. Wikipedia ──────────────────────────────────────────────

def search_wikipedia(query, timeout=_REQUEST_TIMEOUT, conn=None):
    """Look up a Wikipedia article summary.

    First tries a direct page summary lookup.  If that returns a 404,
    falls back to the MediaWiki search API and fetches the top result.

    Returns dict with keys: title, extract, url, description.
    Returns None if nothing found or on error.
    """
    if not query:
        return None

    cache_key = f"wiki:{query}"
    if conn is not None:
        try:
            cached = _cache_get(conn, cache_key)
            if cached is not None:
                return cached
        except Exception as exc:
            logger.warning("Wikipedia cache read failed: {}", exc)

    import requests as req_lib
    headers = {"User-Agent": _USER_AGENT}

    # Attempt 1: direct summary lookup
    try:
        encoded = urllib.parse.quote(query.replace(" ", "_"), safe="")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        resp = req_lib.get(url, timeout=timeout, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            result = {
                "title": data.get("title", ""),
                "extract": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "description": data.get("description", ""),
            }
            if conn is not None:
                try:
                    _cache_set(conn, cache_key, "wikipedia", result)
                except Exception as exc:
                    logger.warning("Wikipedia cache write failed: {}", exc)
            return result
    except Exception as exc:
        logger.warning("Wikipedia direct lookup failed for {}: {}", query, exc)

    # Attempt 2: search API fallback
    try:
        search_url = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=query&list=search"
            f"&srsearch={urllib.parse.quote_plus(query)}"
            "&format=json&srlimit=1"
        )
        resp = req_lib.get(search_url, timeout=timeout, headers=headers)
        if resp.status_code != 200:
            return None
        search_data = resp.json()
        results = search_data.get("query", {}).get("search", [])
        if not results:
            return None

        # Fetch summary of the first search result
        title = results[0].get("title", "")
        encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        resp2 = req_lib.get(summary_url, timeout=timeout, headers=headers)
        if resp2.status_code != 200:
            return None
        data = resp2.json()
        result = {
            "title": data.get("title", ""),
            "extract": data.get("extract", ""),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "description": data.get("description", ""),
        }
        if conn is not None:
            try:
                _cache_set(conn, cache_key, "wikipedia", result)
            except Exception as exc:
                logger.warning("Wikipedia cache write failed: {}", exc)
        return result
    except Exception as exc:
        logger.warning("Wikipedia search fallback failed for {}: {}", query, exc)
        return None


# ── Utility ───────────────────────────────────────────────────

def list_available_sources():
    """Return metadata for all data sources with their availability status.

    Returns list of dicts with keys: name, description, available, needs_key.
    ``available`` is True when the source can be called right now (i.e. any
    required API key is present in the environment).
    """
    sources = [
        {
            "name": "hackernews",
            "description": "Hacker News stories via Algolia search API",
            "available": True,
            "needs_key": False,
        },
        {
            "name": "news",
            "description": "News articles via DuckDuckGo search",
            "available": True,
            "needs_key": False,
        },
        {
            "name": "cloudflare",
            "description": "Domain popularity ranking via Cloudflare Radar",
            "available": bool(os.environ.get("CLOUDFLARE_API_TOKEN")),
            "needs_key": True,
        },
        {
            "name": "patents",
            "description": "USPTO patent search via PatentsView",
            "available": True,
            "needs_key": False,
        },
        {
            "name": "sec_edgar",
            "description": "SEC EDGAR filings full-text search",
            "available": True,
            "needs_key": False,
        },
        {
            "name": "companies_house",
            "description": "UK Companies House company register",
            "available": bool(os.environ.get("COMPANIES_HOUSE_API_KEY")),
            "needs_key": True,
        },
        {
            "name": "wikipedia",
            "description": "Wikipedia article summaries and search",
            "available": True,
            "needs_key": False,
        },
    ]
    return sources
