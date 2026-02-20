"""Siteinspire (siteinspire.com) scraper — curated web design showcase.

Siteinspire is a longstanding curated web design gallery. It uses an
ID-based URL scheme (``/website/{id}-{slug}``) and serves HTML pages
parsed with BeautifulSoup. There is no public API.

Extracts:
    - Site metadata (id, name, slug, URL, categories, styles, types)
    - Hero/preview image URLs (Cloudflare R2: r2.siteinspire.com)
    - Gallery listing pages with pagination

Usage:
    from core.scrapers.siteinspire import browse_sites, search_sites, get_site_details, download_screenshots

    sites = browse_sites(page=1)
    by_cat = browse_sites(page=1, category="ecommerce")
    results = search_sites("agency")
    detail = get_site_details(site_id=1234, slug="linear")
    capture_result = download_screenshots(1234, "linear", project_id=1, entity_id=5, db=db)
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

SITEINSPIRE_BASE = "https://www.siteinspire.com"
SITEINSPIRE_WEBSITES = f"{SITEINSPIRE_BASE}/websites"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds

# Siteinspire images live on Cloudflare R2
_R2_IMAGE_DOMAIN = "r2.siteinspire.com"


@dataclass
class SiteinspireSite:
    """Structured data from a Siteinspire web design listing."""
    id: int
    name: str
    slug: str = ""
    url: str = ""
    image_url: str = ""
    categories: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self):
        return asdict(self)


def _build_detail_url(site_id: int, slug: str) -> str:
    """Construct the Siteinspire detail page URL.

    Args:
        site_id: Numeric site ID
        slug: URL-safe site slug

    Returns:
        Full URL string, e.g. ``https://www.siteinspire.com/website/1234-linear``
    """
    return f"{SITEINSPIRE_BASE}/website/{site_id}-{slug}"


def _parse_image_url(img_tag) -> str:
    """Extract the best available image URL from an img element.

    Siteinspire images are on Cloudflare R2 and often use ``srcset``
    for responsive sizes. We prefer the ``srcset`` largest candidate
    but fall back to ``src`` or ``data-src``.

    Args:
        img_tag: BeautifulSoup Tag object for an <img> element

    Returns:
        Best image URL string, or empty string if none found
    """
    if img_tag is None:
        return ""

    # Try srcset first — pick the largest available resolution
    srcset = img_tag.get("srcset", "").strip()
    if srcset:
        # srcset format: "url1 400w, url2 800w, url3 1200w"
        candidates = []
        for part in srcset.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if len(tokens) >= 1:
                url = tokens[0]
                width = 0
                if len(tokens) >= 2 and tokens[1].endswith("w"):
                    try:
                        width = int(tokens[1][:-1])
                    except ValueError:
                        pass
                candidates.append((width, url))
        if candidates:
            # Sort by width descending; pick largest
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_url = candidates[0][1]
            if best_url:
                return best_url if best_url.startswith("http") else urljoin(SITEINSPIRE_BASE, best_url)

    # Fallback to src or data-src
    src = (
        img_tag.get("data-src", "").strip() or
        img_tag.get("src", "").strip()
    )
    if src and src.startswith("http"):
        return src
    if src:
        return urljoin(SITEINSPIRE_BASE, src)
    return ""


def _parse_listing_card(card) -> Optional[SiteinspireSite]:
    """Parse a single site card from a Siteinspire listing page.

    Siteinspire listing pages use article/div cards, each with an anchor
    linking to the detail page (``/website/{id}-{slug}``) and an img tag
    for the preview image.

    Args:
        card: BeautifulSoup Tag for the card container

    Returns:
        SiteinspireSite populated from the card HTML, or None on failure
    """
    # Find the link to the detail page — it encodes both id and slug
    link = card.find("a", href=re.compile(r'/website/\d+-'))
    if not link:
        # Some cards wrap the whole thing in a link
        if card.name == "a" and re.search(r'/website/\d+-', card.get("href", "")):
            link = card
        else:
            return None

    href = link.get("href", "")
    match = re.search(r'/website/(\d+)-([^/?#]+)', href)
    if not match:
        return None

    site_id = int(match.group(1))
    slug = match.group(2)

    # Site name: prefer the link text or a heading inside the card
    name = ""
    heading = card.find(["h1", "h2", "h3", "h4"])
    if heading:
        name = heading.get_text(strip=True)
    if not name:
        name_span = card.find("span", class_=re.compile(r'name|title', re.I))
        if name_span:
            name = name_span.get_text(strip=True)
    if not name:
        name = link.get_text(strip=True)
    if not name:
        name = slug.replace("-", " ").title()

    # Preview image
    img_tag = card.find("img")
    image_url = _parse_image_url(img_tag)

    # Ensure image URL is absolute
    if image_url and not image_url.startswith("http"):
        image_url = urljoin(SITEINSPIRE_BASE, image_url)

    source_url = _build_detail_url(site_id, slug)

    return SiteinspireSite(
        id=site_id,
        name=name,
        slug=slug,
        image_url=image_url,
        source_url=source_url,
    )


def browse_sites(
    page: int = 1,
    category: Optional[str] = None,
) -> list[SiteinspireSite]:
    """Browse the Siteinspire gallery, with optional category filtering.

    Fetches the HTML listing page and parses all site cards from it.

    Args:
        page: Page number (1-based)
        category: Optional category slug to filter by (e.g. "ecommerce",
                  "portfolio"). Browsing URL becomes
                  ``/websites/category/{category}/page/{page}``.

    Returns:
        List of SiteinspireSite from the requested page
    """
    if category:
        if page > 1:
            url = f"{SITEINSPIRE_WEBSITES}/category/{category}/page/{page}"
        else:
            url = f"{SITEINSPIRE_WEBSITES}/category/{category}"
    else:
        if page > 1:
            url = f"{SITEINSPIRE_WEBSITES}/page/{page}"
        else:
            url = SITEINSPIRE_WEBSITES

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Siteinspire browse failed (page=%d, category=%s): %s", page, category, e)
        return []

    time.sleep(0.5)

    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_listing_page(soup)


def _parse_listing_page(soup: BeautifulSoup) -> list[SiteinspireSite]:
    """Extract all site cards from a parsed Siteinspire listing page.

    Tries multiple selector strategies to handle any markup changes
    Siteinspire may deploy over time.

    Args:
        soup: Parsed BeautifulSoup document for a listing page

    Returns:
        List of SiteinspireSite parsed from the page
    """
    results: list[SiteinspireSite] = []
    seen_ids: set[int] = set()

    # Strategy 1: find all <a> tags with the /website/{id}-{slug} pattern
    # This is the most reliable selector across Siteinspire's markup versions
    for link in soup.find_all("a", href=re.compile(r'/website/\d+-')):
        match = re.search(r'/website/(\d+)-([^/?#]+)', link.get("href", ""))
        if not match:
            continue
        site_id = int(match.group(1))
        if site_id in seen_ids:
            continue
        seen_ids.add(site_id)

        slug = match.group(2)

        # Walk up to the card container (article, li, or div)
        card = link
        for _ in range(4):
            parent = card.parent
            if parent and parent.name in ("article", "li", "figure"):
                card = parent
                break
            if parent:
                card = parent

        parsed = _parse_listing_card(card)
        if parsed and parsed.id not in {s.id for s in results}:
            results.append(parsed)

    return results


def search_sites(query: str) -> list[SiteinspireSite]:
    """Search Siteinspire for sites matching a query.

    Attempts to use Siteinspire's search endpoint if available, then
    falls back to fetching the browse listing and filtering client-side.

    Args:
        query: Search term (e.g. "agency", "editorial", "dark")

    Returns:
        List of SiteinspireSite matching the query
    """
    query_lower = query.lower().strip()
    if not query_lower:
        return []

    # Try the search URL if Siteinspire exposes one
    search_url = f"{SITEINSPIRE_BASE}/search?q={quote_plus(query)}"
    try:
        resp = requests.get(
            search_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            results = _parse_listing_page(soup)
            if results:
                time.sleep(0.5)
                return results
    except Exception as e:
        logger.debug("Siteinspire search endpoint failed for '%s': %s", query, e)

    time.sleep(0.5)

    # Fallback: browse first page and filter by name/slug
    sites = browse_sites(page=1)
    matches = [
        s for s in sites
        if (
            query_lower in s.name.lower() or
            query_lower in s.slug.lower() or
            any(query_lower in cat.lower() for cat in s.categories + s.styles + s.types)
        )
    ]
    return matches


def get_site_details(
    site_id: int,
    slug: str,
) -> Optional[SiteinspireSite]:
    """Get detailed metadata for a specific Siteinspire site.

    Scrapes the individual site detail page at
    ``https://www.siteinspire.com/website/{id}-{slug}`` to extract
    categories, styles, types, and the full-resolution image URL.

    Args:
        site_id: Numeric Siteinspire site ID
        slug: URL slug (e.g. "linear-app")

    Returns:
        SiteinspireSite with full metadata, or None if not found
    """
    url = _build_detail_url(site_id, slug)

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
        logger.warning("Siteinspire detail fetch failed for %d-%s: %s", site_id, slug, e)
        return None

    time.sleep(0.5)

    soup = BeautifulSoup(resp.text, "html.parser")

    # --- Site name ---
    name = ""
    heading = soup.find("h1")
    if heading:
        name = heading.get_text(strip=True)
    if not name:
        title_tag = soup.find("title")
        if title_tag:
            raw = title_tag.get_text(strip=True)
            # Format: "Site Name | Siteinspire" or similar
            name = raw.split("|")[0].split("–")[0].split("-")[0].strip()
    if not name:
        name = slug.replace("-", " ").title()

    # --- External website URL ---
    site_url = ""
    # Look for an outbound link (not a siteinspire.com internal link)
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if href.startswith("http") and "siteinspire.com" not in href:
            # Likely the "Visit website" link on the detail page
            text = a.get_text(strip=True).lower()
            if any(kw in text for kw in ("visit", "website", "launch", "open", "view")):
                site_url = href
                break
    if not site_url:
        # Fallback: first external link that looks like a homepage
        for a in soup.find_all("a", href=re.compile(r'^https?://')):
            href = a.get("href", "")
            if "siteinspire.com" not in href and "siteinspire" not in href:
                site_url = href
                break

    # --- Preview image ---
    image_url = ""
    # Siteinspire detail pages have a hero image; look for R2 CDN images first
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "") or ""
        if _R2_IMAGE_DOMAIN in src or "cdn-cgi/image" in src:
            image_url = _parse_image_url(img)
            break
    if not image_url:
        # Any img with a reasonable srcset
        for img in soup.find_all("img"):
            if img.get("srcset"):
                image_url = _parse_image_url(img)
                if image_url:
                    break

    # --- Taxonomy tags: categories, styles, types ---
    categories: list[str] = []
    styles: list[str] = []
    types: list[str] = []

    # Siteinspire uses labelled tag groups; look for list items or tag links
    # grouped under headings like "Categories", "Styles", "Types"
    for section in soup.find_all(["section", "div", "aside"]):
        heading_el = section.find(["h2", "h3", "h4", "h5", "strong", "dt"])
        if not heading_el:
            continue
        label = heading_el.get_text(strip=True).lower()
        tags = [a.get_text(strip=True) for a in section.find_all("a") if a.get_text(strip=True)]
        if "categor" in label:
            categories.extend(tags)
        elif "style" in label:
            styles.extend(tags)
        elif "type" in label:
            types.extend(tags)

    # Fallback: look for definition-list pattern (<dt>/<dd>) common on older Siteinspire
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).lower()
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        tags = [a.get_text(strip=True) for a in dd.find_all("a")]
        if not tags:
            tags = [dd.get_text(strip=True)]
        tags = [t for t in tags if t]
        if "categor" in label:
            categories.extend(tags)
        elif "style" in label:
            styles.extend(tags)
        elif "type" in label:
            types.extend(tags)

    # Deduplicate while preserving order
    def _dedup(lst: list[str]) -> list[str]:
        seen: set[str] = set()
        out = []
        for item in lst:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    return SiteinspireSite(
        id=site_id,
        name=name,
        slug=slug,
        url=site_url,
        image_url=image_url,
        categories=_dedup(categories),
        styles=_dedup(styles),
        types=_dedup(types),
        source_url=url,
    )


def download_screenshots(
    site_id: int,
    slug: str,
    project_id: int,
    entity_id: int,
    db=None,
) -> CaptureResult:
    """Download the preview image for a Siteinspire site and store as evidence.

    Fetches the site's detail page, extracts the hero preview image URL
    (hosted on Cloudflare R2 at r2.siteinspire.com), and saves it as
    screenshot evidence for the given entity.

    Args:
        site_id: Numeric Siteinspire site ID
        slug: URL slug for the site (e.g. "linear-app")
        project_id: Project to store evidence under
        entity_id: Entity to link evidence to
        db: Database instance (if provided, creates evidence records)

    Returns:
        CaptureResult with paths to all downloaded files
    """
    start = time.time()

    site = get_site_details(site_id, slug)
    if not site:
        return CaptureResult(
            success=False,
            url=_build_detail_url(site_id, slug),
            error=f"Siteinspire site {site_id}-{slug} not found",
            duration_ms=int((time.time() - start) * 1000),
        )

    evidence_paths = []
    evidence_ids = []
    errors = []

    urls_to_download: list[tuple[str, str]] = []

    if site.image_url:
        urls_to_download.append((site.image_url, "screenshot_1"))

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

            # Determine file extension from content-type or URL
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
                    source_name="Siteinspire",
                    metadata={
                        "siteinspire_id": site.id,
                        "site_name": site.name,
                        "site_url": site.url,
                        "label": label,
                        "categories": site.categories,
                        "styles": site.styles,
                        "types": site.types,
                        "file_size": len(content),
                    },
                )
                evidence_ids.append(ev_id)

            time.sleep(0.5)

        except Exception as e:
            errors.append(f"{label}: {e}")
            logger.debug("Failed to download Siteinspire image %s: %s", url, e)

    metadata = {
        "siteinspire_id": site.id,
        "site_name": site.name,
        "site_url": site.url,
        "slug": site.slug,
        "categories": site.categories,
        "styles": site.styles,
        "types": site.types,
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


def get_site_metadata_for_entity(site_id: int, slug: str) -> dict:
    """Get Siteinspire metadata formatted as entity attributes.

    Useful for populating entity attributes from a Siteinspire listing.

    Args:
        site_id: Numeric Siteinspire site ID
        slug: URL slug for the site

    Returns:
        Dict of attribute_slug → value suitable for entity attribute updates
    """
    site = get_site_details(site_id, slug)
    if not site:
        return {}

    return {
        "siteinspire_id": str(site.id),
        "siteinspire_url": site.source_url,
        "website_url": site.url,
        "design_categories": ", ".join(site.categories),
        "design_styles": ", ".join(site.styles),
        "design_types": ", ".join(site.types),
    }
