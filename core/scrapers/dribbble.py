"""Dribbble scraper via public HTML scraping.

Dribbble (dribbble.com) has no public API — we scrape public search results
and shot detail pages. No authentication required for public shots.

Uses requests + BeautifulSoup for HTML parsing.

Extracts:
    - Shot metadata (title, designer, likes, views, tags)
    - Shot image URLs (full-size + thumbnail from cdn.dribbble.com)
    - Designer profile URL
    - Shot permalink URL

Usage:
    from core.scrapers.dribbble import search_shots, get_shot_details, download_shots

    results = search_shots("insurance app onboarding")
    details = get_shot_details(shot_id="12345678")
    capture_result = download_shots("fintech dashboard", project_id=1, entity_id=5, db=db)
"""
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from loguru import logger

from core.capture import (
    store_file, _generate_filename, CaptureResult,
)

DRIBBBLE_BASE = "https://dribbble.com"
DRIBBBLE_SEARCH_URL = "https://dribbble.com/search"
DRIBBBLE_SHOT_URL = "https://dribbble.com/shots"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds
_POLITE_DELAY = 0.5    # seconds between requests


@dataclass
class DribbbleShot:
    """Structured data from a Dribbble shot listing."""
    id: str
    title: str
    image_url: str = ""
    thumbnail_url: str = ""
    designer: str = ""
    designer_url: str = ""
    tags: list[str] = field(default_factory=list)
    likes: int = 0
    views: int = 0
    url: str = ""

    def to_dict(self):
        return asdict(self)


def _extract_image_url(img_tag) -> tuple[str, str]:
    """Extract full-size image URL and thumbnail URL from an img tag.

    Dribbble CDN images appear as:
        cdn.dribbble.com/userupload/.../file.png?resize=...
        cdn.dribbble.com/users/.../screenshots/...

    Returns:
        (image_url, thumbnail_url) — image_url is the full-size version,
        thumbnail_url is the smaller preview (or same as image_url).
    """
    if img_tag is None:
        return "", ""

    # Try srcset first (highest quality)
    srcset = img_tag.get("srcset", "")
    src = img_tag.get("src", "") or img_tag.get("data-src", "")

    # Normalise CDN URL — strip resize params and request a large version
    def _normalise(url: str) -> str:
        if not url or "cdn.dribbble.com" not in url:
            return url
        # Strip existing resize query string
        base = url.split("?")[0]
        return base

    # Parse srcset to get the largest descriptor
    full_url = ""
    if srcset:
        parts = [p.strip() for p in srcset.split(",") if p.strip()]
        # Each part is "<url> <Nw>" — pick the one with the largest width
        best_url, best_w = "", 0
        for part in parts:
            pieces = part.split()
            if len(pieces) >= 1:
                u = pieces[0]
                w = 0
                if len(pieces) >= 2:
                    m = re.match(r'(\d+)w', pieces[1])
                    if m:
                        w = int(m.group(1))
                if w > best_w:
                    best_w = w
                    best_url = u
        full_url = _normalise(best_url) if best_url else ""

    # Fallback to src
    thumb_url = _normalise(src) if src else ""

    if not full_url:
        full_url = thumb_url

    return full_url, thumb_url


def _parse_count(text: str) -> int:
    """Parse a human-readable count string like '1.2k' or '34,567' to int."""
    if not text:
        return 0
    text = text.strip().lower().replace(",", "")
    try:
        if text.endswith("k"):
            return int(float(text[:-1]) * 1000)
        if text.endswith("m"):
            return int(float(text[:-1]) * 1_000_000)
        return int(float(text))
    except (ValueError, IndexError):
        return 0


def _parse_shot_card(card) -> Optional[DribbbleShot]:
    """Parse a single shot card element from Dribbble search results.

    Dribbble renders shot cards roughly as:
        <li class="shot-thumbnail ...">
          <div class="shot-thumbnail-container">
            <a href="/shots/12345678-title">
              <img src="..." srcset="..." alt="Title" />
            </a>
          </div>
          <a class="shot-title" href="/shots/12345678-title">Title</a>
          <a class="designer-name" href="/username">Designer</a>
        </li>
    """
    try:
        # Shot URL and ID from the first <a> linking to /shots/
        shot_url = ""
        shot_id = ""
        for a in card.find_all("a", href=True):
            href = a.get("href", "")
            m = re.match(r'/shots/(\d+)', href)
            if m:
                shot_id = m.group(1)
                shot_url = DRIBBBLE_BASE + href.split("?")[0]
                break

        if not shot_id:
            # Also try data-screenshot-id attribute on the card itself
            shot_id = card.get("data-screenshot-id", "")
            if not shot_id:
                return None

        # Image
        img = card.find("img")
        image_url, thumbnail_url = _extract_image_url(img)

        # Title — from img alt, then from a.shot-title link text
        title = ""
        if img:
            title = img.get("alt", "").strip()
        if not title:
            for a in card.find_all("a", href=True):
                href = a.get("href", "")
                if f"/shots/{shot_id}" in href:
                    t = a.get_text(strip=True)
                    if t:
                        title = t
                        break

        # Designer — look for a link to a profile (not /shots/)
        designer = ""
        designer_url = ""
        for a in card.find_all("a", href=True):
            href = a.get("href", "")
            # Profile links are /<username> — one path segment, no /shots/
            if re.match(r'^/[^/]+$', href) and "/shots" not in href:
                designer = a.get_text(strip=True)
                designer_url = DRIBBBLE_BASE + href
                break

        # Likes — look for aria-label="N likes" or class containing "like-count"
        likes = 0
        for el in card.find_all(attrs={"aria-label": True}):
            label = el.get("aria-label", "")
            m = re.search(r'([\d,.]+[km]?)\s+like', label, re.IGNORECASE)
            if m:
                likes = _parse_count(m.group(1))
                break
        if not likes:
            for el in card.find_all(class_=re.compile(r'like|heart|fav', re.I)):
                t = el.get_text(strip=True)
                if re.match(r'^[\d,.]+[km]?$', t, re.IGNORECASE):
                    likes = _parse_count(t)
                    break

        # Views — similar pattern
        views = 0
        for el in card.find_all(attrs={"aria-label": True}):
            label = el.get("aria-label", "")
            m = re.search(r'([\d,.]+[km]?)\s+view', label, re.IGNORECASE)
            if m:
                views = _parse_count(m.group(1))
                break

        return DribbbleShot(
            id=shot_id,
            title=title or f"Shot {shot_id}",
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            designer=designer,
            designer_url=designer_url,
            likes=likes,
            views=views,
            url=shot_url,
        )

    except Exception as e:
        logger.warning("Failed to parse Dribbble shot card: %s", e)
        return None


def search_shots(
    query: str,
    page: int = 1,
    per_page: int = 24,
) -> list[DribbbleShot]:
    """Search Dribbble for shots matching a query.

    Scrapes: https://dribbble.com/search/{query}?page={page}

    Args:
        query: Search query (e.g. "insurance app", "fintech dashboard")
        page: Page number (1-based)
        per_page: Not directly controllable via URL but included for interface parity;
                  Dribbble returns ~24 shots per page by default.

    Returns:
        List of DribbbleShot results (basic info — full images via get_shot_details)
    """
    # Dribbble search URL: /search/{encoded_query}?page=N
    encoded_query = quote(query, safe="")
    url = f"{DRIBBBLE_SEARCH_URL}/{encoded_query}"
    params: dict = {}
    if page > 1:
        params["page"] = page

    try:
        resp = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            logger.warning("Dribbble search returned 404 for query '%s'", query)
            return []
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Dribbble search failed for '%s': %s", query, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # Shot cards are in <li> elements — common class patterns include
    # "shot-thumbnail", "js-shot-thumbnail", or data-screenshot-id attr
    cards = soup.find_all("li", attrs={"data-screenshot-id": True})
    if not cards:
        # Fallback: any <li> with class containing "shot"
        cards = soup.find_all("li", class_=re.compile(r'shot', re.I))
    if not cards:
        # Broader fallback: any element with data-screenshot-id
        cards = soup.find_all(attrs={"data-screenshot-id": True})

    seen_ids: set[str] = set()
    for card in cards:
        shot = _parse_shot_card(card)
        if shot and shot.id not in seen_ids:
            seen_ids.add(shot.id)
            results.append(shot)
            if len(results) >= per_page:
                break

    return results


def get_shot_details(shot_id: str) -> Optional[DribbbleShot]:
    """Get detailed info for a specific Dribbble shot.

    Scrapes: https://dribbble.com/shots/{shot_id}

    Args:
        shot_id: Dribbble shot ID (numeric string, e.g. "12345678")

    Returns:
        DribbbleShot with full details, or None if not found
    """
    url = f"{DRIBBBLE_SHOT_URL}/{shot_id}"

    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Dribbble shot fetch failed for ID %s: %s", shot_id, e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Title — og:title is most reliable
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title:
        title = og_title.get("content", "").strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    # Full-size image — og:image gives CDN URL directly
    image_url = ""
    thumbnail_url = ""
    og_image = soup.find("meta", property="og:image")
    if og_image:
        image_url = og_image.get("content", "").strip()
        thumbnail_url = image_url

    # If og:image not found, look for the main shot image
    if not image_url:
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if src and "cdn.dribbble.com" in src:
                image_url, thumbnail_url = _extract_image_url(img)
                break

    # Designer — look for link to profile in shot header area
    designer = ""
    designer_url = ""
    # Try og:site_name author pattern or meta author
    for meta in soup.find_all("meta", attrs={"name": "author"}):
        designer = meta.get("content", "").strip()
        break
    # Also try structured links: <a href="/username"> in the shot header
    if not designer:
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if re.match(r'^/[^/]+$', href) and "/shots" not in href:
                t = a.get_text(strip=True)
                if t:
                    designer = t
                    designer_url = DRIBBBLE_BASE + href
                    break
    if designer and not designer_url:
        # Build designer URL from name if we got it from meta
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if re.match(r'^/[^/]+$', href):
                t = a.get_text(strip=True)
                if t.lower() == designer.lower():
                    designer_url = DRIBBBLE_BASE + href
                    break

    # Tags — Dribbble shows tags as links to /tags/<tag>
    tags: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/tags/" in href:
            tag_text = a.get_text(strip=True)
            if tag_text and tag_text not in tags:
                tags.append(tag_text)

    # Likes — look for aria-label or a visible count near a like/heart button
    likes = 0
    for el in soup.find_all(attrs={"aria-label": True}):
        label = el.get("aria-label", "")
        m = re.search(r'([\d,.]+[km]?)\s+like', label, re.IGNORECASE)
        if m:
            likes = _parse_count(m.group(1))
            break
    if not likes:
        for el in soup.find_all(class_=re.compile(r'like-count|heart-count|fav-count', re.I)):
            t = el.get_text(strip=True)
            if re.match(r'^[\d,.]+[km]?$', t, re.IGNORECASE):
                likes = _parse_count(t)
                break

    # Views — look for a view count element
    views = 0
    for el in soup.find_all(attrs={"aria-label": True}):
        label = el.get("aria-label", "")
        m = re.search(r'([\d,.]+[km]?)\s+view', label, re.IGNORECASE)
        if m:
            views = _parse_count(m.group(1))
            break

    return DribbbleShot(
        id=shot_id,
        title=title or f"Shot {shot_id}",
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        designer=designer,
        designer_url=designer_url,
        tags=tags,
        likes=likes,
        views=views,
        url=url,
    )


def download_shots(
    query: str,
    project_id: int,
    entity_id: int,
    db=None,
    max_shots: int = 10,
) -> CaptureResult:
    """Search Dribbble and download shot images as evidence.

    Searches for shots matching the query, then downloads the images and
    stores them as evidence linked to the given entity.

    Args:
        query: Search query (e.g. "insurance app onboarding")
        project_id: Project to store evidence under
        entity_id: Entity to link evidence to
        db: Database instance (if provided, creates evidence records)
        max_shots: Maximum number of shots to download (default 10)

    Returns:
        CaptureResult with paths to all downloaded images
    """
    start = time.time()

    shots = search_shots(query, page=1, per_page=max_shots)
    if not shots:
        return CaptureResult(
            success=False,
            url=f"{DRIBBBLE_SEARCH_URL}/{quote(query, safe='')}",
            error=f"No Dribbble shots found for query: {query!r}",
            duration_ms=int((time.time() - start) * 1000),
        )

    # Limit to max_shots
    shots = shots[:max_shots]

    evidence_paths = []
    evidence_ids = []
    errors = []

    for shot in shots:
        # Polite delay between requests
        time.sleep(_POLITE_DELAY)

        image_url = shot.image_url or shot.thumbnail_url
        if not image_url:
            # Try to get full details if card had no image
            details = get_shot_details(shot.id)
            if details:
                image_url = details.image_url or details.thumbnail_url
                shot = details  # Use enriched data

        if not image_url:
            errors.append(f"shot_{shot.id}: no image URL found")
            continue

        try:
            resp = requests.get(
                image_url,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Referer": shot.url or DRIBBBLE_BASE,
                },
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content

            # Determine extension from URL or Content-Type header
            content_type = resp.headers.get("Content-Type", "")
            ext = ".png"  # Dribbble shots are typically PNG
            if ".jpg" in image_url.lower() or ".jpeg" in image_url.lower() or "jpeg" in content_type:
                ext = ".jpg"
            elif ".webp" in image_url.lower() or "webp" in content_type:
                ext = ".webp"
            elif ".gif" in image_url.lower() or "gif" in content_type:
                ext = ".gif"

            safe_title = re.sub(r'[^a-z0-9-]', '', shot.title.lower().replace(' ', '-'))[:50]
            label = f"dribbble_{shot.id}_{safe_title}" if safe_title else f"dribbble_{shot.id}"
            filename = _generate_filename(label, ext)
            rel_path = store_file(project_id, entity_id, "screenshot", content, filename)
            evidence_paths.append(rel_path)

            if db:
                ev_id = db.add_evidence(
                    entity_id=entity_id,
                    evidence_type="screenshot",
                    file_path=rel_path,
                    source_url=shot.url or image_url,
                    source_name="Dribbble",
                    metadata={
                        "shot_id": shot.id,
                        "title": shot.title,
                        "designer": shot.designer,
                        "designer_url": shot.designer_url,
                        "tags": shot.tags,
                        "likes": shot.likes,
                        "views": shot.views,
                        "image_url": image_url,
                        "search_query": query,
                        "file_size": len(content),
                    },
                )
                evidence_ids.append(ev_id)

        except Exception as e:
            errors.append(f"shot_{shot.id}: {e}")
            logger.debug("Failed to download Dribbble shot %s: %s", shot.id, e)

    metadata = {
        "search_query": query,
        "shots_found": len(shots),
        "shots_downloaded": len(evidence_paths),
        "search_url": f"{DRIBBBLE_SEARCH_URL}/{quote(query, safe='')}",
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0,
        url=f"{DRIBBBLE_SEARCH_URL}/{quote(query, safe='')}",
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )
