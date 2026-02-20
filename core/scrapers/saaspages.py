"""SaaS Pages scraper via web scraping.

SaaS Pages (saaspages.xyz) curates 1,200+ SaaS landing page section screenshots,
organised by block type (headers, pricing, CTAs, FAQs, testimonials, footers, etc.)
and by full site.

Images are served from the Versoly CDN:
    cdn.versoly.com/...

Uses requests + BeautifulSoup for HTML parsing.

Extracts:
    - Block/page metadata (name, URL, description, block_type)
    - Screenshot image URLs
    - Source page URL

Usage:
    from core.scrapers.saaspages import browse_blocks, browse_sites, get_site_details, download_screenshots

    results = browse_blocks("pricing")
    results = browse_blocks("headers", page=2)
    results = browse_sites()
    details = get_site_details("stripe")
    capture_result = download_screenshots("stripe", project_id=1, entity_id=5, db=db)
"""
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

SAAS_PAGES_BASE = "https://saaspages.xyz"

# Known block type slugs used in the /blocks/{block_type} URL pattern
BLOCK_TYPES = [
    "headers",
    "pricing",
    "cta",
    "faq",
    "testimonials",
    "footers",
    "features",
    "heros",
    "navigation",
]

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds


@dataclass
class SaaSPage:
    """Structured data from a SaaS Pages listing."""
    slug: str
    name: str
    url: str = ""
    description: str = ""
    image_url: str = ""
    block_type: str = ""
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
        logger.warning("SaaS Pages fetch failed for %s: %s", url, e)
        return None


def _parse_block_card(card, block_type: str = "") -> Optional[SaaSPage]:
    """Parse a single block screenshot card into a SaaSPage.

    SaaS Pages organises blocks as cards — each has a screenshot image,
    a label, and links to the source site and to the block detail page.
    """
    # Primary link — may point to a detail page or directly to the source
    link = card.find("a", href=True)
    if not link:
        return None

    href = link.get("href", "")
    if not href:
        return None

    source_url = href if href.startswith("http") else urljoin(SAAS_PAGES_BASE, href)

    # Slug — last path segment
    slug = source_url.rstrip("/").split("/")[-1] or ""
    if not slug:
        # Fall back to an img alt or heading text
        img = card.find("img")
        if img:
            slug = re.sub(r'[^a-z0-9-]', '', (img.get("alt", "") or "").lower().replace(" ", "-"))
        if not slug:
            return None

    # Name
    name = ""
    heading = card.find(["h2", "h3", "h4", "h5"])
    if heading:
        name = heading.get_text(strip=True)
    if not name:
        name = link.get_text(strip=True)
    if not name:
        img = card.find("img")
        if img:
            name = img.get("alt", "").strip()
    if not name:
        name = slug.replace("-", " ").title()

    # Screenshot image — prefer cdn.versoly.com assets
    image_url = ""
    for img in card.find_all("img"):
        src = (
            img.get("data-src", "")
            or img.get("data-lazy-src", "")
            or img.get("src", "")
        )
        if src:
            image_url = src
            break

    # Site URL (the actual SaaS product page, not the SaaS Pages entry)
    site_url = ""
    for a in card.find_all("a", href=True):
        a_href = a.get("href", "")
        if a_href.startswith("http") and "saaspages.xyz" not in a_href:
            site_url = a_href
            break

    return SaaSPage(
        slug=slug,
        name=name,
        url=site_url,
        description="",
        image_url=image_url,
        block_type=block_type,
        source_url=source_url,
    )


def browse_blocks(
    block_type: str,
    page: int = 1,
) -> list[SaaSPage]:
    """Browse SaaS Pages by block type (e.g. pricing, headers, cta).

    Args:
        block_type: One of the known block type slugs — "headers", "pricing",
                    "cta", "faq", "testimonials", "footers", "features",
                    "heros", "navigation"
        page: Page number for pagination (1-based)

    Returns:
        List of SaaSPage results
    """
    if page > 1:
        url = f"{SAAS_PAGES_BASE}/blocks/{block_type}?page={page}"
    else:
        url = f"{SAAS_PAGES_BASE}/blocks/{block_type}"

    time.sleep(0.5)
    soup = _fetch_page(url)
    if not soup:
        return []

    results = []

    # Block cards can be article, div, or li elements
    cards = (
        soup.find_all("article")
        or soup.find_all("div", class_=re.compile(r'\bcard\b|\bblock\b|\bsite\b'))
        or soup.find_all("li", class_=re.compile(r'\bcard\b|\bblock\b|\bsite\b'))
        or soup.find_all("div", class_=re.compile(r'\bitem\b'))
    )

    for card in cards:
        entry = _parse_block_card(card, block_type=block_type)
        if entry and entry.slug:
            results.append(entry)

    return results


def browse_sites(page: int = 1) -> list[SaaSPage]:
    """Browse all curated SaaS sites on SaaS Pages.

    Args:
        page: Page number for pagination (1-based)

    Returns:
        List of SaaSPage results
    """
    if page > 1:
        url = f"{SAAS_PAGES_BASE}/sites?page={page}"
    else:
        url = f"{SAAS_PAGES_BASE}/sites"

    time.sleep(0.5)
    soup = _fetch_page(url)
    if not soup:
        return []

    results = []

    cards = (
        soup.find_all("article")
        or soup.find_all("div", class_=re.compile(r'\bcard\b|\bsite\b'))
        or soup.find_all("li", class_=re.compile(r'\bcard\b|\bsite\b'))
        or soup.find_all("div", class_=re.compile(r'\bitem\b'))
    )

    for card in cards:
        entry = _parse_block_card(card, block_type="")
        if entry and entry.slug:
            results.append(entry)

    return results


def get_site_details(slug: str) -> Optional[SaaSPage]:
    """Scrape the detail page for a specific SaaS Pages site entry.

    Args:
        slug: The URL slug of the site (e.g. "stripe", "linear", "notion")

    Returns:
        SaaSPage with full details, or None if not found
    """
    url = f"{SAAS_PAGES_BASE}/sites/{slug}"

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
            name = title_text.split("|")[0].split("-")[0].strip()

    # Description — meta description or first substantive paragraph
    description = ""
    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc:
        description = meta_desc.get("content", "")
    if not description:
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) > 50:
                description = text[:500]
                break

    # Primary screenshot image (cdn.versoly.com)
    image_url = ""
    for img in soup.find_all("img"):
        src = (
            img.get("data-src", "")
            or img.get("data-lazy-src", "")
            or img.get("src", "")
        )
        if src and "cdn.versoly.com" in src:
            image_url = src
            break
    # Fallback to any substantial image
    if not image_url:
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and src.startswith("http") and not any(
                x in src for x in ["logo", "favicon", "avatar", "icon"]
            ):
                image_url = src
                break

    # Site URL (the actual SaaS product, not the SaaS Pages entry)
    site_url = ""
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if href.startswith("http") and "saaspages.xyz" not in href:
            if not any(d in href for d in [
                "twitter.com", "facebook.com", "instagram.com",
                "linkedin.com", "github.com",
            ]):
                site_url = href
                break

    # Block type — try to infer from breadcrumbs or heading context
    block_type = ""
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/blocks/" in href:
            block_type = href.rstrip("/").split("/blocks/")[-1].split("/")[0]
            break

    return SaaSPage(
        slug=slug,
        name=name or slug.replace("-", " ").title(),
        url=site_url,
        description=description,
        image_url=image_url,
        block_type=block_type,
        source_url=url,
    )


def download_screenshots(
    slug: str,
    project_id: int,
    entity_id: int,
    db=None,
) -> CaptureResult:
    """Download the screenshot for a SaaS Pages entry and store as evidence.

    Args:
        slug: SaaS Pages site slug (e.g. "stripe", "linear")
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
            url=f"{SAAS_PAGES_BASE}/sites/{slug}",
            error=f"Site '{slug}' not found on SaaS Pages",
            duration_ms=int((time.time() - start) * 1000),
        )

    evidence_paths = []
    evidence_ids = []
    errors = []

    urls_to_download = []

    if site.image_url:
        urls_to_download.append((site.image_url, "saas_screenshot", "screenshot"))

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
                    source_name="SaaS Pages",
                    metadata={
                        "slug": site.slug,
                        "site_name": site.name,
                        "site_url": site.url,
                        "block_type": site.block_type,
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
        "block_type": site.block_type,
        "screenshots_found": len(urls_to_download),
        "screenshots_downloaded": len(evidence_paths),
        "source_url": site.source_url,
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0,
        url=site.source_url or f"{SAAS_PAGES_BASE}/sites/{slug}",
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )


def get_site_metadata_for_entity(slug: str) -> dict:
    """Get site metadata formatted as entity attributes.

    Useful for populating entity attributes from SaaS Pages data.

    Returns:
        Dict of attribute_slug -> value suitable for entity attribute updates
    """
    site = get_site_details(slug)
    if not site:
        return {}

    return {
        "saaspages_slug": site.slug,
        "saaspages_url": site.source_url,
        "saaspages_block_type": site.block_type,
        "site_url": site.url,
        "saaspages_description": site.description[:500],
    }
