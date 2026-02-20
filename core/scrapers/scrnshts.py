"""Scrnshts Club scraper — curated App Store screenshot design gallery.

Scrapes https://scrnshts.club (WordPress-based) for curated mobile app
screenshot designs. Images are served in WebP format from the WordPress
media library.

Extracts:
    - App listing metadata (name, description, category, slug)
    - Screenshot image URLs (WebP from wp-content/uploads/)
    - Category browsing (finance, productivity, lifestyle, etc.)

Usage:
    from core.scrapers.scrnshts import search_apps, browse_category, get_app_details, download_screenshots

    results = search_apps("banking")
    results = browse_category("finance", page=1)
    details = get_app_details("monzo-onboarding")
    capture_result = download_screenshots("monzo-onboarding", project_id=1, entity_id=5, db=db)
"""
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from loguru import logger

from core.capture import (
    store_file, _generate_filename, CaptureResult,
)

SCRNSHTS_BASE = "https://scrnshts.club"
SCRNSHTS_SEARCH_URL = f"{SCRNSHTS_BASE}/"
SCRNSHTS_CATEGORY_URL = f"{SCRNSHTS_BASE}/category"

# Available categories on scrnshts.club
SCRNSHTS_CATEGORIES = [
    "finance",
    "productivity",
    "lifestyle",
    "entertainment",
    "health-fitness",
    "shopping",
    "travel",
    "food-drink",
    "social",
    "utilities",
]

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds


@dataclass
class ScrnshotsApp:
    """Structured data from a Scrnshts Club listing."""
    slug: str
    name: str
    description: str = ""
    category: str = ""
    screenshot_urls: list[str] = field(default_factory=list)
    source_url: str = ""

    def to_dict(self):
        return asdict(self)


# ── Internal helpers ───────────────────────────────────────────


def _make_headers() -> dict:
    return {"User-Agent": _USER_AGENT}


def _extract_cards(soup: BeautifulSoup) -> list[ScrnshotsApp]:
    """Extract ScrnshotsApp entries from a WordPress listing page.

    WordPress post cards typically appear as <article> elements with
    class names like 'post', 'type-post', etc. Each card links to the
    individual post page and may contain a title and category.
    """
    apps = []

    # WordPress: articles with class containing 'post'
    articles = soup.find_all("article")
    if not articles:
        # Fallback: look for common card containers
        articles = soup.find_all("div", class_=re.compile(r"\bpost\b|\bcard\b|\bentry\b"))

    for article in articles:
        # Extract slug + source URL from the permalink
        link_tag = (
            article.find("a", rel="bookmark")
            or article.find("a", href=re.compile(r"scrnshts\.club/(?!category|page|wp-)")
        ))
        if not link_tag:
            # Broader fallback: any internal link that looks like a post
            link_tag = article.find("a", href=re.compile(r"scrnshts\.club/[a-z0-9-]+/?$"))

        source_url = ""
        slug = ""
        if link_tag:
            source_url = link_tag.get("href", "").strip().rstrip("/")
            # Slug is the last path component
            slug = source_url.rstrip("/").split("/")[-1]

        if not slug:
            continue

        # Title / name
        name = ""
        h2 = article.find(["h2", "h3", "h1"])
        if h2:
            name = h2.get_text(strip=True)
        elif link_tag:
            name = link_tag.get_text(strip=True)
        if not name:
            name = slug.replace("-", " ").title()

        # Description (excerpt or first paragraph)
        description = ""
        excerpt = article.find(class_=re.compile(r"excerpt|entry-summary|summary"))
        if excerpt:
            description = excerpt.get_text(strip=True)
        else:
            p = article.find("p")
            if p:
                description = p.get_text(strip=True)

        # Category — look for category links
        category = ""
        cat_link = article.find("a", href=re.compile(r"/category/"))
        if cat_link:
            category = cat_link.get_text(strip=True)
        else:
            # Try to derive from article CSS classes: "category-finance"
            classes = " ".join(article.get("class", []))
            m = re.search(r"category-([a-z0-9-]+)", classes)
            if m:
                category = m.group(1)

        # Preview screenshots from within the card (may be thumbnails)
        screenshot_urls = _extract_image_urls(article)

        apps.append(ScrnshotsApp(
            slug=slug,
            name=name,
            description=description,
            category=category,
            screenshot_urls=screenshot_urls,
            source_url=source_url or f"{SCRNSHTS_BASE}/{slug}/",
        ))

    return apps


def _extract_image_urls(container) -> list[str]:
    """Extract WordPress-hosted WebP image URLs from a BeautifulSoup element."""
    urls = []
    for img in container.find_all("img"):
        # Check src, data-src, data-lazy-src
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            url = img.get(attr, "")
            if url and "scrnshts.club/wp-content/uploads/" in url:
                # Use the full-size URL: strip WordPress resize suffixes like -300x600
                clean = re.sub(r'-\d+x\d+(?=\.\w+$)', '', url)
                if clean not in urls:
                    urls.append(clean)
                break

        # Also check srcset for the highest-resolution variant
        srcset = img.get("srcset", "")
        if srcset and "scrnshts.club/wp-content/uploads/" in srcset:
            # Pick the last (largest) descriptor
            candidates = [
                part.strip().split(" ")[0]
                for part in srcset.split(",")
                if "scrnshts.club/wp-content/uploads/" in part
            ]
            if candidates:
                best = candidates[-1]
                clean = re.sub(r'-\d+x\d+(?=\.\w+$)', '', best)
                if clean not in urls:
                    urls.append(clean)

    return urls


# ── Public API ─────────────────────────────────────────────────


def search_apps(query: str) -> list[ScrnshotsApp]:
    """Search Scrnshts Club for screenshot sets matching a query.

    Uses WordPress native search: ``https://scrnshts.club/?s={query}``

    Args:
        query: Search term (e.g. "banking", "onboarding", "checkout")

    Returns:
        List of ScrnshotsApp results (screenshot_urls may be thumbnails only;
        call get_app_details(slug) for full resolution URLs).
    """
    url = f"{SCRNSHTS_SEARCH_URL}?s={quote_plus(query)}"

    try:
        resp = requests.get(
            url,
            headers=_make_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Scrnshts Club search failed for '%s': %s", query, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = _extract_cards(soup)

    if not results:
        logger.debug("Scrnshts Club: no results for '%s'", query)

    return results


def browse_category(category: str, page: int = 1) -> list[ScrnshotsApp]:
    """Browse a Scrnshts Club category archive.

    Args:
        category: Category slug (e.g. "finance", "productivity", "health-fitness").
                  See SCRNSHTS_CATEGORIES for the full list.
        page: Page number (1-based). WordPress pagination uses ``/page/{n}/``.

    Returns:
        List of ScrnshotsApp entries on that page.
    """
    if page <= 1:
        url = f"{SCRNSHTS_CATEGORY_URL}/{category}/"
    else:
        url = f"{SCRNSHTS_CATEGORY_URL}/{category}/page/{page}/"

    try:
        resp = requests.get(
            url,
            headers=_make_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            logger.warning("Scrnshts Club: category '%s' page %d not found", category, page)
            return []
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Scrnshts Club browse failed (%s, p%d): %s", category, page, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = _extract_cards(soup)

    # Ensure category is set on all results
    for app in results:
        if not app.category:
            app.category = category

    return results


def get_app_details(slug: str) -> Optional[ScrnshotsApp]:
    """Scrape an individual Scrnshts Club post page for full-resolution screenshots.

    Args:
        slug: URL slug of the post (e.g. "monzo-onboarding")

    Returns:
        ScrnshotsApp with full-resolution screenshot_urls, or None on failure.
    """
    url = f"{SCRNSHTS_BASE}/{slug}/"

    try:
        resp = requests.get(
            url,
            headers=_make_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            logger.warning("Scrnshts Club: post '%s' not found", slug)
            return None
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Scrnshts Club detail fetch failed for '%s': %s", slug, e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Title
    name = slug.replace("-", " ").title()
    h1 = soup.find("h1")
    if h1:
        name = h1.get_text(strip=True)
    else:
        title_tag = soup.find("title")
        if title_tag:
            raw = title_tag.get_text()
            # WordPress title format: "Post Name – Site Name"
            name = raw.split("–")[0].split("|")[0].strip()

    # Description — post body / entry-content
    description = ""
    content_div = soup.find(class_=re.compile(r"entry-content|post-content|article-content"))
    if content_div:
        # Use only the first paragraph to keep it concise
        p = content_div.find("p")
        if p:
            description = p.get_text(strip=True)

    # Category
    category = ""
    cat_link = soup.find("a", href=re.compile(r"/category/"), rel=lambda v: v and "tag" not in v)
    if cat_link:
        category = cat_link.get_text(strip=True)

    # Full-resolution screenshots — search the entire post body
    main = soup.find(class_=re.compile(r"entry-content|post-content")) or soup
    screenshot_urls = _extract_image_urls(main)

    # If no WP upload images found, try any <img> on the page whose src looks like WebP
    if not screenshot_urls:
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src.endswith(".webp") or ".webp" in src:
                if src not in screenshot_urls:
                    screenshot_urls.append(src)

    return ScrnshotsApp(
        slug=slug,
        name=name,
        description=description,
        category=category,
        screenshot_urls=screenshot_urls,
        source_url=url,
    )


def download_screenshots(
    slug: str,
    project_id: int,
    entity_id: int,
    db=None,
) -> CaptureResult:
    """Download full-resolution screenshots for a Scrnshts Club post and store as evidence.

    Args:
        slug: URL slug of the post (e.g. "monzo-onboarding")
        project_id: Project to store evidence under
        entity_id: Entity to link evidence to
        db: Database instance (if provided, creates evidence records)

    Returns:
        CaptureResult with paths to all downloaded files
    """
    start = time.time()

    app = get_app_details(slug)
    if not app:
        return CaptureResult(
            success=False,
            url=f"{SCRNSHTS_BASE}/{slug}/",
            error=f"Scrnshts Club post '{slug}' not found",
            duration_ms=int((time.time() - start) * 1000),
        )

    if not app.screenshot_urls:
        return CaptureResult(
            success=False,
            url=app.source_url,
            error=f"No screenshots found for '{slug}'",
            duration_ms=int((time.time() - start) * 1000),
        )

    evidence_paths = []
    evidence_ids = []
    errors = []

    safe_name = re.sub(r'[^a-z0-9-]', '', slug.lower().replace(' ', '-')) or "scrnshts"

    for i, img_url in enumerate(app.screenshot_urls):
        try:
            time.sleep(0.5)  # Polite delay between requests

            resp = requests.get(
                img_url,
                headers=_make_headers(),
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content

            # Scrnshts Club images are WebP; fall back to content-type check
            ext = ".webp"
            ct = resp.headers.get("Content-Type", "")
            if "jpeg" in ct or "jpg" in ct:
                ext = ".jpg"
            elif "png" in ct:
                ext = ".png"
            elif img_url.lower().endswith(".jpg") or img_url.lower().endswith(".jpeg"):
                ext = ".jpg"
            elif img_url.lower().endswith(".png"):
                ext = ".png"

            label = f"screenshot_{i + 1}"
            filename = _generate_filename(f"{safe_name}_{label}", ext)
            rel_path = store_file(project_id, entity_id, "screenshot", content, filename)
            evidence_paths.append(rel_path)

            if db:
                ev_id = db.add_evidence(
                    entity_id=entity_id,
                    evidence_type="screenshot",
                    file_path=rel_path,
                    source_url=img_url,
                    source_name="Scrnshts Club",
                    metadata={
                        "slug": app.slug,
                        "app_name": app.name,
                        "category": app.category,
                        "label": label,
                        "file_size": len(content),
                    },
                )
                evidence_ids.append(ev_id)

        except Exception as e:
            errors.append(f"screenshot_{i + 1}: {e}")
            logger.debug("Failed to download %s: %s", img_url, e)

    metadata = {
        "slug": app.slug,
        "app_name": app.name,
        "category": app.category,
        "source_url": app.source_url,
        "screenshots_found": len(app.screenshot_urls),
        "screenshots_downloaded": len(evidence_paths),
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0,
        url=app.source_url,
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )
