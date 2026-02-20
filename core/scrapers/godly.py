"""Godly (godly.website) scraper — curated web design gallery.

Godly is a curated gallery of ~1,000+ notable web design sites. The site
is built with Next.js and embeds structured data in a ``__NEXT_DATA__``
JSON script tag, giving us clean access to site listings without needing
a formal API.

Extracts:
    - Site metadata (name, slug, URL, description, categories)
    - Image and video preview URLs
    - Source gallery URL

Usage:
    from core.scrapers.godly import browse_sites, search_sites, get_site_details, download_screenshots

    sites = browse_sites(page=1)
    results = search_sites("editorial")
    detail = get_site_details("linear")
    capture_result = download_screenshots("linear", project_id=1, entity_id=5, db=db)
"""
import json
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger

from core.capture import (
    store_file, _generate_filename, CaptureResult,
)

GODLY_BASE = "https://godly.website"
GODLY_IMAGES_BASE = "https://godly.website/images/raw"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds


@dataclass
class GodlySite:
    """Structured data from a Godly web design gallery listing."""
    id: str
    name: str
    slug: str = ""
    url: str = ""
    description: str = ""
    image_url: str = ""
    video_url: str = ""
    categories: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self):
        return asdict(self)


def _parse_site_node(node: dict) -> Optional[GodlySite]:
    """Parse a single site node from Godly's __NEXT_DATA__ JSON.

    Godly's Next.js data includes site entries under various key paths
    depending on page type. This parser handles the common shapes.

    Args:
        node: Dict representing a single site entry from Godly JSON

    Returns:
        GodlySite or None if the node cannot be parsed
    """
    # Godly uses different key shapes: some pages use "node", others embed directly
    site = node.get("node", node)

    site_id = str(site.get("id", "") or site.get("_id", "") or site.get("objectId", ""))
    name = site.get("name", "") or site.get("title", "")
    if not site_id or not name:
        return None

    slug = site.get("slug", "") or site.get("handle", "") or _slugify(name)
    url = site.get("url", "") or site.get("website", "") or site.get("link", "")
    description = site.get("description", "") or site.get("excerpt", "")

    # Image: Godly stores images at /images/raw/{uuid}.jpg
    image_url = ""
    raw_image = (
        site.get("image", {}) or
        site.get("screenshot", {}) or
        site.get("cover", {}) or {}
    )
    if isinstance(raw_image, dict):
        uuid = (
            raw_image.get("id", "") or
            raw_image.get("uuid", "") or
            raw_image.get("objectId", "") or
            raw_image.get("filename", "").replace(".jpg", "").replace(".png", "")
        )
        if uuid:
            image_url = f"{GODLY_IMAGES_BASE}/{uuid}.jpg"
    elif isinstance(raw_image, str) and raw_image:
        # Some entries store the URL directly
        if raw_image.startswith("http"):
            image_url = raw_image
        else:
            image_url = f"{GODLY_IMAGES_BASE}/{raw_image}"

    # Fallback: check top-level image fields
    if not image_url:
        for key in ("imageUrl", "image_url", "screenshotUrl", "thumbnail"):
            val = site.get(key, "")
            if val and isinstance(val, str):
                image_url = val if val.startswith("http") else f"{GODLY_BASE}/{val.lstrip('/')}"
                break

    # Video URL (optional — Godly sometimes has short preview clips)
    video_url = site.get("video", "") or site.get("videoUrl", "") or site.get("video_url", "")
    if video_url and isinstance(video_url, dict):
        video_url = video_url.get("url", "") or video_url.get("src", "")
    if not isinstance(video_url, str):
        video_url = ""

    # Categories
    categories = []
    raw_cats = site.get("categories", []) or site.get("tags", []) or []
    for cat in raw_cats:
        if isinstance(cat, str):
            categories.append(cat)
        elif isinstance(cat, dict):
            label = cat.get("name", "") or cat.get("label", "") or cat.get("title", "")
            if label:
                categories.append(label)

    source_url = f"{GODLY_BASE}/?website/{slug}" if slug else GODLY_BASE

    return GodlySite(
        id=site_id,
        name=name,
        slug=slug,
        url=url,
        description=description,
        image_url=image_url,
        video_url=video_url,
        categories=categories,
        source_url=source_url,
    )


def _slugify(text: str) -> str:
    """Generate a URL slug from a site name."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug)
    return slug.strip('-')


def _extract_next_data(html: str) -> dict:
    """Extract and parse the __NEXT_DATA__ JSON from a Next.js page.

    Args:
        html: Raw HTML string from the page response

    Returns:
        Parsed dict from __NEXT_DATA__, or empty dict on failure
    """
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not tag or not tag.string:
        return {}
    try:
        return json.loads(tag.string)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse __NEXT_DATA__ JSON: %s", e)
        return {}


def _extract_sites_from_next_data(data: dict) -> list[GodlySite]:
    """Walk the Next.js page props to find site listing arrays.

    Godly's data shape varies between the index, category, and search
    pages. This function performs a breadth-first search through the
    props tree looking for arrays of site-like dicts.

    Args:
        data: Parsed __NEXT_DATA__ dict

    Returns:
        List of GodlySite parsed from the data
    """
    results: list[GodlySite] = []

    # Navigate into pageProps — that's where Godly keeps its data
    props = data.get("props", {}).get("pageProps", {})

    # Common top-level keys Godly uses for its listings
    candidate_keys = [
        "websites", "sites", "items", "results", "data",
        "entries", "posts", "nodes",
    ]

    def _try_extract(obj):
        """Recursively search for site arrays inside obj."""
        if not isinstance(obj, dict):
            return
        for key, val in obj.items():
            if isinstance(val, list) and val:
                # Check if first element looks like a site entry
                first = val[0]
                if isinstance(first, dict):
                    # Heuristic: a site entry has 'name' or 'title' plus 'id' or 'slug'
                    first_inner = first.get("node", first)
                    has_id = any(k in first_inner for k in ("id", "_id", "objectId"))
                    has_name = any(k in first_inner for k in ("name", "title"))
                    if has_id and has_name:
                        for item in val:
                            parsed = _parse_site_node(item)
                            if parsed and parsed.id not in {s.id for s in results}:
                                results.append(parsed)
                        return  # Found the main listing — stop
            elif isinstance(val, dict):
                _try_extract(val)

    # Try direct known keys first
    for key in candidate_keys:
        val = props.get(key)
        if isinstance(val, list) and val:
            for item in val:
                parsed = _parse_site_node(item)
                if parsed and parsed.id not in {s.id for s in results}:
                    results.append(parsed)
            if results:
                break

    # Fall back to recursive search if nothing found yet
    if not results:
        _try_extract(props)

    return results


def browse_sites(page: int = 1) -> list[GodlySite]:
    """Browse the Godly gallery, returning a page of curated sites.

    Godly loads its data via Next.js server-side rendering — the full
    site list is embedded in the ``__NEXT_DATA__`` JSON block. Pagination
    is handled by the site's own page URL scheme.

    Args:
        page: Page number (1-based)

    Returns:
        List of GodlySite from the requested gallery page
    """
    url = GODLY_BASE if page <= 1 else f"{GODLY_BASE}/?page={page}"

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Godly browse failed (page=%d): %s", page, e)
        return []

    time.sleep(0.5)

    data = _extract_next_data(resp.text)
    if not data:
        logger.warning("Godly: no __NEXT_DATA__ found on page %d", page)
        return []

    return _extract_sites_from_next_data(data)


def search_sites(query: str) -> list[GodlySite]:
    """Search Godly for sites matching a query string.

    Godly does not expose a dedicated search API endpoint, so we fetch
    the browse listing and filter client-side by name and description.
    If the gallery is large, only the first page of results is searched.

    Args:
        query: Search term (matched against site name and description)

    Returns:
        Filtered list of GodlySite whose name or description match the query
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return []

    sites = browse_sites(page=1)
    time.sleep(0.5)

    matches = []
    for site in sites:
        if (
            query_lower in site.name.lower() or
            query_lower in site.description.lower() or
            any(query_lower in cat.lower() for cat in site.categories)
        ):
            matches.append(site)

    return matches


def get_site_details(slug: str) -> Optional[GodlySite]:
    """Get details for a specific Godly site by its slug.

    Fetches the per-site detail page at ``https://godly.website/?website/{slug}``
    and parses its ``__NEXT_DATA__`` for full metadata.

    Args:
        slug: Godly URL slug (e.g. "linear", "stripe")

    Returns:
        GodlySite with full metadata, or None if not found
    """
    url = f"{GODLY_BASE}/?website/{slug}"

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Godly detail fetch failed for slug '%s': %s", slug, e)
        return None

    time.sleep(0.5)

    data = _extract_next_data(resp.text)
    if not data:
        # Fall back to scraping Open Graph / meta tags
        return _scrape_site_from_meta(resp.text, slug)

    props = data.get("props", {}).get("pageProps", {})

    # On a detail page Godly typically puts the site under "website" or "site"
    for key in ("website", "site", "entry", "item", "post"):
        candidate = props.get(key)
        if isinstance(candidate, dict):
            parsed = _parse_site_node(candidate)
            if parsed:
                parsed.source_url = url
                return parsed

    # Try to extract from any site arrays (detail pages sometimes embed related)
    sites = _extract_sites_from_next_data(data)
    for site in sites:
        if site.slug == slug or site.source_url == url:
            return site

    return _scrape_site_from_meta(resp.text, slug)


def _scrape_site_from_meta(html: str, slug: str) -> Optional[GodlySite]:
    """Fallback: extract basic site data from Open Graph meta tags.

    Used when the ``__NEXT_DATA__`` block is absent or doesn't contain
    the expected data shape.

    Args:
        html: Raw HTML of the page
        slug: Known slug to use for constructing the result

    Returns:
        GodlySite populated from meta tags, or None if nothing useful found
    """
    soup = BeautifulSoup(html, "html.parser")

    def _meta(prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return tag.get("content", "").strip() if tag else ""

    title = _meta("og:title") or _meta("twitter:title")
    description = _meta("og:description") or _meta("twitter:description") or _meta("description")
    image_url = _meta("og:image") or _meta("twitter:image")

    if not title:
        tag = soup.find("title")
        title = tag.get_text(strip=True) if tag else ""

    if not title:
        return None

    return GodlySite(
        id=slug,
        name=title,
        slug=slug,
        description=description,
        image_url=image_url,
        source_url=f"{GODLY_BASE}/?website/{slug}",
    )


def download_screenshots(
    slug: str,
    project_id: int,
    entity_id: int,
    db=None,
) -> CaptureResult:
    """Download gallery images for a Godly site and store as evidence.

    Fetches the detail page for the given slug, then downloads the
    primary screenshot image (and video thumbnail if available).

    Args:
        slug: Godly URL slug (e.g. "linear", "stripe")
        project_id: Project to store evidence under
        entity_id: Entity to link evidence to
        db: Database instance (if provided, creates evidence records)

    Returns:
        CaptureResult with paths to all downloaded files
    """
    start = time.time()

    site = get_site_details(slug)
    if not site:
        return CaptureResult(
            success=False,
            url=f"{GODLY_BASE}/?website/{slug}",
            error=f"Godly site '{slug}' not found",
            duration_ms=int((time.time() - start) * 1000),
        )

    evidence_paths = []
    evidence_ids = []
    errors = []

    urls_to_download: list[tuple[str, str]] = []

    if site.image_url:
        urls_to_download.append((site.image_url, "screenshot_1"))
    if site.video_url:
        # Download the video thumbnail or first frame if it's an image URL
        if any(site.video_url.lower().endswith(ext) for ext in (".jpg", ".png", ".webp", ".jpeg")):
            urls_to_download.append((site.video_url, "video_thumbnail"))

    safe_name = re.sub(r'[^a-z0-9-]', '', site.name.lower().replace(' ', '-'))

    for url, label in urls_to_download:
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content

            # Determine file extension
            content_type = resp.headers.get("Content-Type", "")
            ext = ".jpg"
            if "png" in content_type or url.lower().endswith(".png"):
                ext = ".png"
            elif "webp" in content_type or url.lower().endswith(".webp"):
                ext = ".webp"

            filename = _generate_filename(f"{safe_name}_{label}", ext)
            rel_path = store_file(project_id, entity_id, "screenshot", content, filename)
            evidence_paths.append(rel_path)

            if db:
                ev_id = db.add_evidence(
                    entity_id=entity_id,
                    evidence_type="screenshot",
                    file_path=rel_path,
                    source_url=url,
                    source_name="Godly",
                    metadata={
                        "godly_id": site.id,
                        "site_name": site.name,
                        "site_url": site.url,
                        "label": label,
                        "file_size": len(content),
                    },
                )
                evidence_ids.append(ev_id)

            time.sleep(0.5)

        except Exception as e:
            errors.append(f"{label}: {e}")
            logger.debug("Failed to download Godly image %s: %s", url, e)

    metadata = {
        "godly_id": site.id,
        "site_name": site.name,
        "site_url": site.url,
        "slug": site.slug,
        "categories": site.categories,
        "screenshots_found": len(urls_to_download),
        "screenshots_downloaded": len(evidence_paths),
        "source_url": site.source_url,
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0,
        url=site.source_url,
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )


def get_site_metadata_for_entity(slug: str) -> dict:
    """Get Godly site metadata formatted as entity attributes.

    Useful for populating entity attributes from a Godly gallery entry.

    Args:
        slug: Godly URL slug

    Returns:
        Dict of attribute_slug → value suitable for entity attribute updates
    """
    site = get_site_details(slug)
    if not site:
        return {}

    return {
        "godly_slug": site.slug,
        "godly_url": site.source_url,
        "website_url": site.url,
        "design_categories": ", ".join(site.categories),
        "godly_description": site.description[:500],
    }
