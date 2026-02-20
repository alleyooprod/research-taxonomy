"""Collect UI scraper — UI pattern shots aggregated from Dribbble.

Scrapes https://collectui.com (14,400+ shots organised by challenge/pattern).
Images are served from static.collectui.com; no official API exists.

Extracts:
    - Shot metadata (id, title, designer, challenge)
    - Full-size and thumbnail image URLs
    - Challenge (pattern category) listings

Usage:
    from core.scrapers.collectui import list_challenges, browse_challenge, download_shots

    challenges = list_challenges()
    shots = browse_challenge("login", page=1)
    capture_result = download_shots("login", project_id=1, entity_id=5, db=db, max_shots=10)
"""
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from bs4 import BeautifulSoup
from loguru import logger

from core.capture import (
    store_file, _generate_filename, CaptureResult,
)

COLLECTUI_BASE = "https://collectui.com"
COLLECTUI_CHALLENGES_URL = f"{COLLECTUI_BASE}/challenges"
COLLECTUI_STATIC = "https://static.collectui.com/shots"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds

# Well-known Collect UI challenge slugs (partial list — use list_challenges() for live data)
_KNOWN_CHALLENGES = [
    "button",
    "landing-page",
    "login",
    "sign-up",
    "dashboard",
    "profile",
    "settings",
    "checkout",
    "search",
    "onboarding",
    "home-screen",
    "calendar",
    "upload",
    "chart",
    "map",
    "pricing",
    "menu",
    "chat",
    "notification",
    "card",
    "form",
    "list",
    "video-player",
    "music-player",
    "timer",
]


@dataclass
class CollectUIShot:
    """Structured data for a single Collect UI shot."""
    id: str
    title: str
    image_url: str = ""
    thumbnail_url: str = ""
    challenge: str = ""
    designer: str = ""
    source_url: str = ""

    def to_dict(self):
        return asdict(self)


# ── Internal helpers ───────────────────────────────────────────


def _make_headers() -> dict:
    return {"User-Agent": _USER_AGENT}


def _slug_from_challenge(challenge_name: str) -> str:
    """Normalise a challenge name to the URL slug format used by Collect UI."""
    return challenge_name.strip().lower().replace(" ", "-")


def _parse_shot_container(container, challenge: str) -> Optional[CollectUIShot]:
    """Parse a single shot container element into a CollectUIShot.

    Collect UI shot containers typically look like:
        <div class="shot-container" data-id="12345">
            <a href="/shots/12345">
                <img src="...thumbnail..." data-src="...full...">
            </a>
            <div class="shot-info">
                <span class="designer">...</span>
            </div>
        </div>

    The shot ID is authoritative; ``static.collectui.com/shots/{id}/...`` hosts files.
    """
    # Resolve shot ID — from data attribute or href
    shot_id = (
        container.get("data-id", "")
        or container.get("id", "").lstrip("shot-")
    )

    link = container.find("a", href=re.compile(r"/shots?/\d+"))
    if not shot_id and link:
        m = re.search(r"/shots?/(\d+)", link.get("href", ""))
        if m:
            shot_id = m.group(1)

    if not shot_id:
        return None

    shot_id = str(shot_id)
    source_url = f"{COLLECTUI_BASE}/shots/{shot_id}"

    # Image URLs — prefer data-src (lazy-loaded full image) over src (thumbnail)
    thumbnail_url = ""
    image_url = ""
    img = container.find("img")
    if img:
        thumbnail_url = img.get("src", "")
        image_url = (
            img.get("data-src", "")
            or img.get("data-original", "")
            or img.get("data-lazy-src", "")
            or thumbnail_url
        )

    # If we have neither, try to construct from the static CDN pattern
    if not image_url and shot_id:
        image_url = f"{COLLECTUI_STATIC}/{shot_id}/large.png"
        thumbnail_url = thumbnail_url or f"{COLLECTUI_STATIC}/{shot_id}/small.png"

    # Title — from alt text, title attribute, or shot-title element
    title = ""
    title_el = container.find(class_=re.compile(r"shot-title|title|name"))
    if title_el:
        title = title_el.get_text(strip=True)
    if not title and img:
        title = img.get("alt", "").strip() or img.get("title", "").strip()
    if not title:
        title = f"{challenge.replace('-', ' ').title()} — shot {shot_id}"

    # Designer
    designer = ""
    designer_el = container.find(class_=re.compile(r"designer|author|user"))
    if designer_el:
        designer = designer_el.get_text(strip=True)
    if not designer:
        for a in container.find_all("a", href=re.compile(r"/designers?/|/users?/")):
            designer = a.get_text(strip=True)
            if designer:
                break

    return CollectUIShot(
        id=shot_id,
        title=title,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        challenge=challenge,
        designer=designer,
        source_url=source_url,
    )


def _parse_shots_from_page(soup: BeautifulSoup, challenge: str) -> list[CollectUIShot]:
    """Extract all shot cards from a challenge listing page."""
    shots = []

    # Primary: containers with class matching shot/item/card patterns
    containers = soup.find_all(
        ["div", "li", "article"],
        class_=re.compile(r"\bshot\b|\bitem\b|\bcard\b|\bthumb\b"),
    )

    # Fallback: look for anchor tags pointing to /shots/ with an img child
    if not containers:
        for a in soup.find_all("a", href=re.compile(r"/shots?/\d+")):
            if a.find("img"):
                containers.append(a.parent)

    seen_ids = set()
    for container in containers:
        shot = _parse_shot_container(container, challenge)
        if shot and shot.id not in seen_ids:
            seen_ids.add(shot.id)
            shots.append(shot)

    return shots


# ── Public API ─────────────────────────────────────────────────


def list_challenges() -> list[str]:
    """Return available challenge category slugs from the Collect UI challenges index.

    Attempts to scrape the live challenges page; falls back to the built-in
    ``_KNOWN_CHALLENGES`` list if the request fails.

    Returns:
        List of challenge slug strings (e.g. ["button", "login", "dashboard", ...])
    """
    try:
        resp = requests.get(
            COLLECTUI_CHALLENGES_URL,
            headers=_make_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Collect UI: failed to fetch challenges list: %s", e)
        return list(_KNOWN_CHALLENGES)

    soup = BeautifulSoup(resp.text, "html.parser")
    challenges = []

    # Challenge links: /challenges/{slug}
    for a in soup.find_all("a", href=re.compile(r"/challenges/[a-z0-9-]+")):
        href = a.get("href", "")
        m = re.search(r"/challenges/([a-z0-9-]+)", href)
        if m:
            slug = m.group(1)
            if slug not in challenges:
                challenges.append(slug)

    if not challenges:
        logger.debug("Collect UI: could not parse challenge list; using built-in fallback")
        return list(_KNOWN_CHALLENGES)

    return challenges


def browse_challenge(challenge_name: str, page: int = 1) -> list[CollectUIShot]:
    """Browse shots for a given Collect UI challenge category.

    Collect UI does not provide a search endpoint; browsing by challenge is the
    primary discovery mechanism.

    Args:
        challenge_name: Challenge slug or human-readable name
                        (e.g. "login", "Landing Page", "checkout")
        page: Page number (1-based). Collect UI uses ``?page={n}`` pagination.

    Returns:
        List of CollectUIShot entries found on that page.
    """
    slug = _slug_from_challenge(challenge_name)
    url = f"{COLLECTUI_CHALLENGES_URL}/{slug}"
    params = {}
    if page > 1:
        params["page"] = page

    try:
        resp = requests.get(
            url,
            params=params,
            headers=_make_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            logger.warning("Collect UI: challenge '%s' not found", slug)
            return []
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Collect UI browse failed ('%s', p%d): %s", slug, page, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    shots = _parse_shots_from_page(soup, challenge=slug)

    if not shots:
        logger.debug("Collect UI: no shots parsed for '%s' page %d", slug, page)

    return shots


def search_shots(query: str) -> list[CollectUIShot]:
    """Attempt to find shots matching a query by browsing the closest challenge category.

    Collect UI has no direct search endpoint. This function matches the query
    against known challenge slugs and returns results from the best-matching
    challenge. For open-ended queries, use browse_challenge() directly.

    Args:
        query: Search term (e.g. "login screen", "dashboard", "payment")

    Returns:
        List of CollectUIShot from the best-matching challenge, or empty list.
    """
    query_lower = query.lower().strip()
    challenges = list_challenges()

    # Try exact slug match first
    for ch in challenges:
        if ch == query_lower or ch == query_lower.replace(" ", "-"):
            return browse_challenge(ch)

    # Try substring match
    for ch in challenges:
        if query_lower in ch or ch in query_lower:
            return browse_challenge(ch)

    # No match found
    logger.debug(
        "Collect UI: no challenge matched query '%s'; use browse_challenge() directly", query
    )
    return []


def download_shots(
    challenge_name: str,
    project_id: int,
    entity_id: int,
    db=None,
    max_shots: int = 10,
) -> CaptureResult:
    """Download shots from a Collect UI challenge and store as evidence.

    Args:
        challenge_name: Challenge slug or human-readable name (e.g. "login")
        project_id: Project to store evidence under
        entity_id: Entity to link evidence to
        db: Database instance (if provided, creates evidence records)
        max_shots: Maximum number of shots to download (default: 10)

    Returns:
        CaptureResult with paths to all downloaded files
    """
    start = time.time()
    slug = _slug_from_challenge(challenge_name)

    shots = browse_challenge(slug)
    if not shots:
        return CaptureResult(
            success=False,
            url=f"{COLLECTUI_CHALLENGES_URL}/{slug}",
            error=f"No shots found for Collect UI challenge '{slug}'",
            duration_ms=int((time.time() - start) * 1000),
        )

    # Limit to requested number
    shots_to_download = shots[:max_shots]

    evidence_paths = []
    evidence_ids = []
    errors = []

    safe_challenge = re.sub(r'[^a-z0-9-]', '', slug)

    for i, shot in enumerate(shots_to_download):
        img_url = shot.image_url or shot.thumbnail_url
        if not img_url:
            errors.append(f"shot_{shot.id}: no image URL")
            continue

        try:
            time.sleep(0.5)  # Polite delay between requests

            resp = requests.get(
                img_url,
                headers=_make_headers(),
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content

            # Determine extension from URL or content-type
            ext = ".png"  # Collect UI shots are commonly PNG
            ct = resp.headers.get("Content-Type", "")
            if "jpeg" in ct or "jpg" in ct:
                ext = ".jpg"
            elif "webp" in ct:
                ext = ".webp"
            elif img_url.lower().endswith(".jpg") or img_url.lower().endswith(".jpeg"):
                ext = ".jpg"
            elif img_url.lower().endswith(".webp"):
                ext = ".webp"

            label = f"shot_{shot.id}"
            filename = _generate_filename(f"collectui_{safe_challenge}_{label}", ext)
            rel_path = store_file(project_id, entity_id, "screenshot", content, filename)
            evidence_paths.append(rel_path)

            if db:
                ev_id = db.add_evidence(
                    entity_id=entity_id,
                    evidence_type="screenshot",
                    file_path=rel_path,
                    source_url=img_url,
                    source_name="Collect UI",
                    metadata={
                        "shot_id": shot.id,
                        "title": shot.title,
                        "challenge": shot.challenge,
                        "designer": shot.designer,
                        "source_url": shot.source_url,
                        "label": label,
                        "file_size": len(content),
                    },
                )
                evidence_ids.append(ev_id)

        except Exception as e:
            errors.append(f"shot_{shot.id}: {e}")
            logger.debug("Failed to download %s: %s", img_url, e)

    metadata = {
        "challenge": slug,
        "shots_available": len(shots),
        "shots_attempted": len(shots_to_download),
        "shots_downloaded": len(evidence_paths),
        "source_url": f"{COLLECTUI_CHALLENGES_URL}/{slug}",
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0,
        url=f"{COLLECTUI_CHALLENGES_URL}/{slug}",
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )
