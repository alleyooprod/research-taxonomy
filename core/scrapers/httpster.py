"""Httpster scraper via web scraping.

Httpster (httpster.net) curates 3,100+ web designs, updated regularly.
Uses requests + BeautifulSoup for HTML parsing.

Screenshot images follow the pattern:
    /assets/media/{code}/{domain}-{n}-{code}.webp

Extracts:
    - Site metadata (name, URL, description, categories)
    - Screenshot image URLs (WebP format)
    - Source page URL

Usage:
    from core.scrapers.httpster import browse_sites, search_sites, get_site_details, download_screenshots

    results = browse_sites()
    results = browse_sites(page=2)
    results = search_sites("portfolio")
    details = get_site_details("vitality-co-uk")
    capture_result = download_screenshots("vitality-co-uk", project_id=1, entity_id=5, db=db)
"""
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urljoin, quote_plus

import requests
from bs4 import BeautifulSoup
from loguru import logger

from core.capture import (
    store_file, _generate_filename, CaptureResult,
)

HTTPSTER_BASE = "https://httpster.net"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds


@dataclass
class HttpsterSite:
    """Structured data from an Httpster gallery listing."""
    slug: str
    name: str
    url: str = ""
    description: str = ""
    image_url: str = ""
    categories: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self):
        return asdict(self)


def _slugify_name(name: str) -> str:
    """Convert a site name to a filesystem-safe slug for filenames."""
    slug = re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-'))
    return slug[:80] or "site"


def _fetch_page(url: str) -> Optional[BeautifulSoup]:
    """Fetch a page and return a BeautifulSoup object, or None on error."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        logger.warning("Httpster fetch failed for %s: %s", url, e)
        return None


def _resolve_image_url(src: str) -> str:
    """Ensure an image src is absolute."""
    if not src:
        return ""
    if src.startswith("http"):
        return src
    if src.startswith("/"):
        return f"{HTTPSTER_BASE}{src}"
    return src


def _parse_site_card(card) -> Optional[HttpsterSite]:
    """Parse a single gallery card element into an HttpsterSite.

    Httpster uses article or div cards, each with:
    - A link to the detail page (/website/{slug}/)
    - A WebP screenshot image under /assets/media/...
    - Category tag links
    """
    # Primary link — points to /website/{slug}/
    link = None
    for a in card.find_all("a", href=True):
        href = a.get("href", "")
        if "/website/" in href:
            link = a
            break
    if not link:
        link = card.find("a", href=True)
    if not link:
        return None

    href = link.get("href", "")
    source_url = href if href.startswith("http") else urljoin(HTTPSTER_BASE, href)

    # Slug — last meaningful path segment
    path = source_url.rstrip("/")
    slug = path.split("/")[-1] or ""
    if not slug:
        return None

    # Name — heading or link text or derived from slug
    name = ""
    heading = card.find(["h2", "h3", "h4"])
    if heading:
        name = heading.get_text(strip=True)
    if not name:
        name = link.get_text(strip=True)
    if not name:
        name = slug.replace("-", " ").title()

    # Screenshot image — Httpster uses WebP assets
    # Pattern: /assets/media/{code}/{domain}-{n}-{code}.webp
    image_url = ""
    for img in card.find_all("img"):
        src = (
            img.get("data-src", "")
            or img.get("data-lazy-src", "")
            or img.get("src", "")
        )
        if src:
            image_url = _resolve_image_url(src)
            break

    # Site URL (the actual website being featured)
    site_url = ""
    for a in card.find_all("a", href=True):
        a_href = a.get("href", "")
        if a_href.startswith("http") and "httpster.net" not in a_href:
            site_url = a_href
            break

    # Categories — links to category filter pages
    categories = []
    for a in card.find_all("a", href=True):
        a_href = a.get("href", "")
        tag_text = a.get_text(strip=True)
        if (
            "/category/" in a_href
            or "/tag/" in a_href
            or "/type/" in a_href
        ) and tag_text:
            categories.append(tag_text)

    return HttpsterSite(
        slug=slug,
        name=name,
        url=site_url,
        description="",
        image_url=image_url,
        categories=categories,
        source_url=source_url,
    )


def browse_sites(page: int = 1) -> list[HttpsterSite]:
    """Browse the Httpster gallery.

    Httpster uses page-based pagination. The homepage shows the first page.

    Args:
        page: Page number (1-based)

    Returns:
        List of HttpsterSite results
    """
    if page > 1:
        url = f"{HTTPSTER_BASE}/page/{page}/"
    else:
        url = f"{HTTPSTER_BASE}/"

    time.sleep(0.5)
    soup = _fetch_page(url)
    if not soup:
        return []

    results = []

    # Gallery cards are typically article elements
    cards = (
        soup.find_all("article")
        or soup.find_all("div", class_=re.compile(r'\bsite\b|\bcard\b|\bitem\b'))
        or soup.find_all("li", class_=re.compile(r'\bsite\b|\bcard\b|\bitem\b'))
    )

    for card in cards:
        site = _parse_site_card(card)
        if site and site.slug:
            results.append(site)

    return results


def search_sites(query: str) -> list[HttpsterSite]:
    """Search or filter Httpster sites by keyword.

    Httpster may not have a dedicated search endpoint; this method attempts the
    search URL and, if unavailable, falls back to browsing the first page and
    filtering results client-side by name/description match.

    Args:
        query: Search term (e.g. "portfolio", "fintech", "dark")

    Returns:
        List of HttpsterSite results (may be filtered from browse results)
    """
    # Attempt search endpoint
    search_url = f"{HTTPSTER_BASE}/?s={quote_plus(query)}"
    time.sleep(0.5)
    soup = _fetch_page(search_url)

    results = []

    if soup:
        cards = (
            soup.find_all("article")
            or soup.find_all("div", class_=re.compile(r'\bsite\b|\bcard\b|\bitem\b'))
            or soup.find_all("li", class_=re.compile(r'\bsite\b|\bcard\b|\bitem\b'))
        )
        for card in cards:
            site = _parse_site_card(card)
            if site and site.slug:
                results.append(site)

    # If the search returned nothing, fall back to browse + client-side filter
    if not results:
        all_sites = browse_sites(page=1)
        query_lower = query.lower()
        for site in all_sites:
            if (
                query_lower in site.name.lower()
                or query_lower in site.description.lower()
                or any(query_lower in cat.lower() for cat in site.categories)
            ):
                results.append(site)

    return results


def get_site_details(slug: str) -> Optional[HttpsterSite]:
    """Scrape the detail page for a specific Httpster entry.

    Args:
        slug: The URL slug of the site (e.g. "vitality-co-uk")

    Returns:
        HttpsterSite with full details, or None if not found
    """
    url = f"{HTTPSTER_BASE}/website/{slug}/"

    time.sleep(0.5)
    soup = _fetch_page(url)
    if not soup:
        return None

    # Name
    name = ""
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text()
            # Format: "Site Name | Httpster"
            name = title_text.split("|")[0].strip() if "|" in title_text else title_text.strip()

    # Description — meta description or first descriptive paragraph
    description = ""
    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc:
        description = meta_desc.get("content", "")
    if not description:
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 40:
                description = text[:500]
                break

    # Screenshot — WebP assets follow the pattern:
    # /assets/media/{code}/{domain}-{n}-{code}.webp
    image_url = ""
    for img in soup.find_all("img"):
        src = (
            img.get("data-src", "")
            or img.get("data-lazy-src", "")
            or img.get("src", "")
        )
        if src and ("/assets/media/" in src or ".webp" in src.lower()):
            image_url = _resolve_image_url(src)
            break
    # Fallback to any image that is not a tiny icon
    if not image_url:
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and src.startswith(("http", "/")):
                # Skip obvious UI chrome / logos
                if not any(x in (src + img.get("alt", "")).lower() for x in [
                    "logo", "favicon", "avatar", "star", "icon"
                ]):
                    image_url = _resolve_image_url(src)
                    break

    # Site URL (the actual featured website)
    site_url = ""
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if href.startswith("http") and "httpster.net" not in href:
            if not any(d in href for d in [
                "twitter.com", "facebook.com", "instagram.com",
                "linkedin.com", "github.com",
            ]):
                site_url = href
                break

    # Categories
    categories = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        tag_text = a.get_text(strip=True)
        if (
            "/category/" in href
            or "/tag/" in href
            or "/type/" in href
        ) and tag_text:
            categories.append(tag_text)

    return HttpsterSite(
        slug=slug,
        name=name or slug.replace("-", " ").title(),
        url=site_url,
        description=description,
        image_url=image_url,
        categories=categories,
        source_url=url,
    )


def download_screenshots(
    slug: str,
    project_id: int,
    entity_id: int,
    db=None,
) -> CaptureResult:
    """Download the screenshot for an Httpster entry and store as evidence.

    Args:
        slug: Httpster site slug (e.g. "vitality-co-uk")
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
            url=f"{HTTPSTER_BASE}/website/{slug}/",
            error=f"Site '{slug}' not found on Httpster",
            duration_ms=int((time.time() - start) * 1000),
        )

    evidence_paths = []
    evidence_ids = []
    errors = []

    urls_to_download = []

    if site.image_url:
        urls_to_download.append((site.image_url, "httpster_screenshot", "screenshot"))

    for url, label, ev_type in urls_to_download:
        try:
            time.sleep(0.5)
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content

            # Httpster uses WebP; fall back based on Content-Type
            content_type = resp.headers.get("Content-Type", "")
            if ".webp" in url.lower() or "webp" in content_type:
                ext = ".webp"
            elif ".png" in url.lower() or "png" in content_type:
                ext = ".png"
            elif ".gif" in url.lower() or "gif" in content_type:
                ext = ".gif"
            else:
                ext = ".jpg"

            safe_name = _slugify_name(site.name)
            filename = _generate_filename(f"{safe_name}_{label}", ext)
            rel_path = store_file(project_id, entity_id, ev_type, content, filename)
            evidence_paths.append(rel_path)

            if db:
                ev_id = db.add_evidence(
                    entity_id=entity_id,
                    evidence_type=ev_type,
                    file_path=rel_path,
                    source_url=url,
                    source_name="Httpster",
                    metadata={
                        "slug": site.slug,
                        "site_name": site.name,
                        "site_url": site.url,
                        "categories": site.categories,
                        "label": label,
                        "file_size": len(content),
                    },
                )
                evidence_ids.append(ev_id)

        except Exception as e:
            errors.append(f"{label}: {e}")
            logger.debug("Failed to download %s: %s", url, e)

    metadata = {
        "slug": site.slug,
        "site_name": site.name,
        "site_url": site.url,
        "categories": site.categories,
        "screenshots_found": len(urls_to_download),
        "screenshots_downloaded": len(evidence_paths),
        "source_url": site.source_url,
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0,
        url=site.source_url or f"{HTTPSTER_BASE}/website/{slug}/",
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )


def get_site_metadata_for_entity(slug: str) -> dict:
    """Get site metadata formatted as entity attributes.

    Useful for populating entity attributes from Httpster data.

    Returns:
        Dict of attribute_slug -> value suitable for entity attribute updates
    """
    site = get_site_details(slug)
    if not site:
        return {}

    return {
        "httpster_slug": site.slug,
        "httpster_url": site.source_url,
        "site_url": site.url,
        "httpster_categories": ", ".join(site.categories),
        "httpster_description": site.description[:500],
    }
