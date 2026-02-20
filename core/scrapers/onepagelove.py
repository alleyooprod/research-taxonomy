"""One Page Love scraper via web scraping.

One Page Love (onepagelove.com) showcases 8,900+ one-page websites and templates.
Uses requests + BeautifulSoup for HTML parsing — WordPress-based site.

Images are served from the imgix CDN:
    assets.onepagelove.com/...wp-content/uploads/...

Extracts:
    - Site metadata (name, URL, description, tags)
    - Gallery image / screenshot URLs
    - Source page URL

Usage:
    from core.scrapers.onepagelove import browse_sites, search_sites, get_site_details, download_screenshots

    results = browse_sites(page=1)
    results = browse_sites(category="portfolio")
    results = search_sites("insurance")
    details = get_site_details("vitality-health")
    capture_result = download_screenshots("vitality-health", project_id=1, entity_id=5, db=db)
"""
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from loguru import logger

from core.capture import (
    store_file, _generate_filename, CaptureResult,
)

ONE_PAGE_LOVE_BASE = "https://onepagelove.com"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds


@dataclass
class OnePageSite:
    """Structured data from a One Page Love gallery listing."""
    slug: str
    name: str
    url: str = ""
    description: str = ""
    image_url: str = ""
    tags: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self):
        return asdict(self)


def _slugify_name(name: str) -> str:
    """Convert a site name to a filesystem-safe slug for filenames."""
    slug = re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-'))
    return slug[:80] or "site"


def _parse_site_card(card) -> Optional[OnePageSite]:
    """Parse a single gallery card element into a OnePageSite.

    One Page Love uses article/div cards with the class 'site' or similar.
    Each card contains a link to the detail page, a thumbnail, and tag links.
    """
    # Locate the primary link — the one that points to the OPL detail page
    link = card.find("a", href=True)
    if not link:
        return None

    href = link.get("href", "")
    if not href:
        return None

    # Resolve to absolute URL
    source_url = href if href.startswith("http") else urljoin(ONE_PAGE_LOVE_BASE, href)

    # Slug is the last path segment of the OPL detail URL
    slug = source_url.rstrip("/").split("/")[-1] or ""
    if not slug:
        return None

    # Name — prefer h2/h3 heading inside the card, fall back to link text
    name = ""
    heading = card.find(["h2", "h3", "h4"])
    if heading:
        name = heading.get_text(strip=True)
    if not name:
        name = link.get_text(strip=True)
    if not name:
        name = slug.replace("-", " ").title()

    # Thumbnail image — imgix CDN asset
    image_url = ""
    img = card.find("img")
    if img:
        # Prefer data-src (lazy loading) then src
        image_url = (
            img.get("data-src", "")
            or img.get("data-lazy-src", "")
            or img.get("src", "")
        )
        # Strip query params to get the base URL; we'll request a reasonable size
        if image_url and "?" in image_url:
            image_url = image_url.split("?")[0]

    # Destination URL (the actual site being featured)
    site_url = ""
    for a in card.find_all("a", href=True):
        a_href = a.get("href", "")
        if a_href.startswith("http") and "onepagelove.com" not in a_href:
            site_url = a_href
            break

    # Tags — links inside the card that point to category/tag pages
    tags = []
    for a in card.find_all("a", href=True):
        a_href = a.get("href", "")
        tag_text = a.get_text(strip=True)
        if (
            "/tags/" in a_href
            or "/type/" in a_href
            or "/inspiration/" in a_href
        ) and tag_text:
            tags.append(tag_text)

    return OnePageSite(
        slug=slug,
        name=name,
        url=site_url,
        description="",
        image_url=image_url,
        tags=tags,
        source_url=source_url,
    )


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
        logger.warning("One Page Love fetch failed for %s: %s", url, e)
        return None


def browse_sites(
    page: int = 1,
    category: Optional[str] = None,
) -> list[OnePageSite]:
    """Browse the One Page Love gallery.

    Args:
        page: Page number (1-based)
        category: Optional category/inspiration slug (e.g. "portfolio", "agency",
                  "ecommerce"). When set, browses the inspiration sub-section.

    Returns:
        List of OnePageSite results from the gallery listing
    """
    if category:
        # Inspiration category pages: /inspiration/{category}/page/{n}
        if page > 1:
            url = f"{ONE_PAGE_LOVE_BASE}/inspiration/{category}/page/{page}/"
        else:
            url = f"{ONE_PAGE_LOVE_BASE}/inspiration/{category}/"
    else:
        # Main gallery paginated: /page/{n}
        if page > 1:
            url = f"{ONE_PAGE_LOVE_BASE}/page/{page}/"
        else:
            url = f"{ONE_PAGE_LOVE_BASE}/"

    time.sleep(0.5)
    soup = _fetch_page(url)
    if not soup:
        return []

    results = []

    # Gallery items are typically article elements or divs with class containing "site"
    # Try multiple selectors to be robust across site redesigns
    cards = (
        soup.find_all("article")
        or soup.find_all("div", class_=re.compile(r'\bsite\b'))
        or soup.find_all("li", class_=re.compile(r'\bsite\b'))
    )

    for card in cards:
        site = _parse_site_card(card)
        if site and site.slug:
            results.append(site)

    return results


def search_sites(query: str) -> list[OnePageSite]:
    """Search One Page Love for sites matching a query.

    Uses the WordPress search endpoint: /?s={query}

    Args:
        query: Search term (e.g. "portfolio", "fintech")

    Returns:
        List of OnePageSite results
    """
    url = f"{ONE_PAGE_LOVE_BASE}/?s={quote_plus(query)}"

    time.sleep(0.5)
    soup = _fetch_page(url)
    if not soup:
        return []

    results = []

    cards = (
        soup.find_all("article")
        or soup.find_all("div", class_=re.compile(r'\bsite\b'))
        or soup.find_all("li", class_=re.compile(r'\bsite\b'))
    )

    for card in cards:
        site = _parse_site_card(card)
        if site and site.slug:
            results.append(site)

    return results


def get_site_details(slug: str) -> Optional[OnePageSite]:
    """Scrape the detail page for a specific One Page Love entry.

    Args:
        slug: The URL slug of the site (e.g. "vitality-health")

    Returns:
        OnePageSite with full details, or None if not found
    """
    url = f"{ONE_PAGE_LOVE_BASE}/{slug}/"

    time.sleep(0.5)
    soup = _fetch_page(url)
    if not soup:
        return None

    # Name — page h1 or title tag
    name = ""
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text()
            # Format: "Site Name | One Page Love"
            name = title_text.split("|")[0].strip() if "|" in title_text else title_text.strip()

    # Description — meta description or first descriptive paragraph
    description = ""
    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc:
        description = meta_desc.get("content", "")
    if not description:
        # Look for an editorial description near the main content
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 50:
                description = text[:500]
                break

    # Primary screenshot / hero image
    image_url = ""
    # OPL hero images often have class like "screenshot", "preview", or sit in a
    # figure/section near the top of the article
    for img in soup.find_all("img"):
        src = (
            img.get("data-src", "")
            or img.get("data-lazy-src", "")
            or img.get("src", "")
        )
        if src and "assets.onepagelove.com" in src:
            image_url = src.split("?")[0]  # Strip imgix params
            break
    # Fallback: any image in the hero/article area
    if not image_url:
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and src.startswith("http") and "gravatar" not in src:
                image_url = src
                break

    # Site URL (the featured website, not the OPL page)
    site_url = ""
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if href.startswith("http") and "onepagelove.com" not in href:
            # Skip social/CDN links
            if not any(d in href for d in ["twitter.com", "facebook.com", "instagram.com"]):
                site_url = href
                break

    # Tags
    tags = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        tag_text = a.get_text(strip=True)
        if (
            "/tags/" in href
            or "/type/" in href
            or "/inspiration/" in href
        ) and tag_text:
            tags.append(tag_text)

    return OnePageSite(
        slug=slug,
        name=name or slug.replace("-", " ").title(),
        url=site_url,
        description=description,
        image_url=image_url,
        tags=tags,
        source_url=url,
    )


def download_screenshots(
    slug: str,
    project_id: int,
    entity_id: int,
    db=None,
) -> CaptureResult:
    """Download the gallery screenshot for a One Page Love entry and store as evidence.

    Args:
        slug: OPL site slug (e.g. "vitality-health")
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
            url=f"{ONE_PAGE_LOVE_BASE}/{slug}/",
            error=f"Site '{slug}' not found on One Page Love",
            duration_ms=int((time.time() - start) * 1000),
        )

    evidence_paths = []
    evidence_ids = []
    errors = []

    urls_to_download = []

    if site.image_url:
        urls_to_download.append((site.image_url, "gallery_screenshot", "screenshot"))

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

            # Determine extension from URL or Content-Type
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
                    source_name="One Page Love",
                    metadata={
                        "slug": site.slug,
                        "site_name": site.name,
                        "site_url": site.url,
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
        "tags": site.tags,
        "screenshots_found": len(urls_to_download),
        "screenshots_downloaded": len(evidence_paths),
        "source_url": site.source_url,
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0,
        url=site.source_url or f"{ONE_PAGE_LOVE_BASE}/{slug}/",
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )


def get_site_metadata_for_entity(slug: str) -> dict:
    """Get site metadata formatted as entity attributes.

    Useful for populating entity attributes from One Page Love data.

    Returns:
        Dict of attribute_slug -> value suitable for entity attribute updates
    """
    site = get_site_details(slug)
    if not site:
        return {}

    return {
        "onepagelove_slug": site.slug,
        "onepagelove_url": site.source_url,
        "site_url": site.url,
        "onepagelove_tags": ", ".join(site.tags),
        "onepagelove_description": site.description[:500],
    }
