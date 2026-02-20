"""Google Play Store scraper via web scraping.

Google Play has no public API — we scrape the web listing pages.
Uses requests + BeautifulSoup for HTML parsing.

Extracts:
    - App metadata (name, description, rating, installs, developer)
    - Screenshot URLs
    - Icon URL
    - Category, content rating

Usage:
    from core.scrapers.playstore import search_apps, get_app_details, download_screenshots

    results = search_apps("Vitality Health")
    details = get_app_details("com.vitality.mobile")
    capture_result = download_screenshots("com.vitality.mobile", project_id=1, entity_id=5, db=db)
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

PLAY_STORE_BASE = "https://play.google.com/store/apps/details"
PLAY_SEARCH_URL = "https://play.google.com/store/search"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15


@dataclass
class PlayStoreApp:
    """Structured data from a Google Play Store listing."""
    package_id: str
    name: str = ""
    developer: str = ""
    description: str = ""
    short_description: str = ""
    rating: float = 0.0
    rating_count: int = 0
    installs: str = ""
    price: str = "Free"
    content_rating: str = ""
    category: str = ""
    icon_url: str = ""
    screenshot_urls: list[str] = field(default_factory=list)
    store_url: str = ""
    version: str = ""
    updated: str = ""
    requires_android: str = ""

    def to_dict(self):
        return asdict(self)


def _extract_rating(soup: BeautifulSoup) -> float:
    """Extract rating from various Play Store page structures."""
    # Look for the rating text (e.g. "4.5")
    for tag in soup.find_all(["div", "span"]):
        text = tag.get_text(strip=True)
        if re.match(r'^\d\.\d$', text):
            try:
                val = float(text)
                if 0 <= val <= 5:
                    return val
            except ValueError:
                pass
    # Look in aria-label
    for tag in soup.find_all(attrs={"aria-label": True}):
        label = tag.get("aria-label", "")
        m = re.search(r'Rated\s+([\d.]+)', label)
        if m:
            return float(m.group(1))
    return 0.0


def _extract_screenshots(soup: BeautifulSoup) -> list[str]:
    """Extract screenshot image URLs from Play Store page."""
    urls = []
    # Screenshots are typically in img tags with srcset or data-src
    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        srcset = img.get("srcset", "")
        alt = img.get("alt", "").lower()

        # Filter for screenshots (not icon, not rating stars, etc.)
        if "screenshot" in alt or "screen" in alt:
            if src and "googleusercontent.com" in src:
                urls.append(src.split("=")[0] + "=w720")  # Request medium size
            continue

        # Check srcset for high-res images
        if srcset and "googleusercontent.com" in srcset:
            # Take the largest from srcset
            parts = srcset.split(",")
            for part in parts:
                url = part.strip().split(" ")[0]
                if url and "googleusercontent.com" in url:
                    urls.append(url.split("=")[0] + "=w720")
                    break

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def get_app_details(
    package_id: str,
    language: str = "en",
    country: str = "gb",
) -> Optional[PlayStoreApp]:
    """Get detailed info for a specific app by its package ID.

    Args:
        package_id: Android package ID (e.g. "com.vitality.mobile")
        language: Language code (default: "en")
        country: Country code (default: "gb")

    Returns:
        PlayStoreApp or None if not found
    """
    url = f"{PLAY_STORE_BASE}?id={package_id}&hl={language}&gl={country}"

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
        logger.warning("Play Store fetch failed for %s: %s", package_id, e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract app name from title tag
    title_tag = soup.find("title")
    name = ""
    if title_tag:
        title_text = title_tag.get_text()
        # Format: "AppName - Apps on Google Play"
        name = title_text.split(" - ")[0].strip() if " - " in title_text else title_text.strip()

    # Extract description
    description = ""
    desc_div = soup.find("div", {"data-g-id": "description"})
    if desc_div:
        description = desc_div.get_text(strip=True)
    else:
        # Fallback: look for meta description
        meta = soup.find("meta", {"name": "description"})
        if meta:
            description = meta.get("content", "")

    # Extract icon
    icon_url = ""
    for img in soup.find_all("img"):
        alt = img.get("alt", "").lower()
        if "icon" in alt or name.lower() in alt:
            icon_url = img.get("src", "") or img.get("data-src", "")
            if icon_url:
                break

    # Extract screenshots
    screenshot_urls = _extract_screenshots(soup)

    # Extract rating
    rating = _extract_rating(soup)

    # Extract developer
    developer = ""
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if "/store/apps/developer" in href:
            developer = a.get_text(strip=True)
            break

    return PlayStoreApp(
        package_id=package_id,
        name=name,
        developer=developer,
        description=description[:2000],  # Truncate long descriptions
        rating=rating,
        icon_url=icon_url,
        screenshot_urls=screenshot_urls,
        store_url=url,
    )


def search_apps(
    term: str,
    country: str = "gb",
    limit: int = 10,
) -> list[PlayStoreApp]:
    """Search Google Play Store for apps.

    Note: Google Play search is HTML-based and results may be limited.

    Args:
        term: Search query
        country: Country code
        limit: Max results

    Returns:
        List of PlayStoreApp with basic info (name, package_id, icon)
    """
    url = f"{PLAY_SEARCH_URL}?q={requests.utils.quote(term)}&c=apps&hl=en&gl={country}"

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Play Store search failed for '%s': %s", term, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # Find app links in search results
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/store/apps/details?id=" in href:
            # Extract package ID from URL
            pkg_match = re.search(r'id=([a-zA-Z0-9._]+)', href)
            if pkg_match:
                pkg_id = pkg_match.group(1)
                # Get the app name from link text or nearby elements
                name_text = a.get_text(strip=True) or ""
                if name_text and len(name_text) > 1 and pkg_id not in [r.package_id for r in results]:
                    results.append(PlayStoreApp(
                        package_id=pkg_id,
                        name=name_text[:200],
                        store_url=f"{PLAY_STORE_BASE}?id={pkg_id}",
                    ))
                    if len(results) >= limit:
                        break

    return results


def download_screenshots(
    package_id: str,
    project_id: int,
    entity_id: int,
    db=None,
    country: str = "gb",
    include_icon: bool = True,
) -> CaptureResult:
    """Download all screenshots for a Play Store app and store as evidence.

    Args:
        package_id: Android package ID
        project_id: Project to store evidence under
        entity_id: Entity to link evidence to
        db: Database instance (if provided, creates evidence records)
        country: Country code
        include_icon: Download the app icon

    Returns:
        CaptureResult with paths to all downloaded files
    """
    start = time.time()

    app = get_app_details(package_id, country=country)
    if not app:
        return CaptureResult(
            success=False,
            url=f"{PLAY_STORE_BASE}?id={package_id}",
            error=f"App {package_id} not found on Google Play",
            duration_ms=int((time.time() - start) * 1000),
        )

    evidence_paths = []
    evidence_ids = []
    errors = []

    urls_to_download = []

    # Screenshots
    for i, url in enumerate(app.screenshot_urls):
        urls_to_download.append((url, f"screenshot_{i+1}", "screenshot"))

    # App icon
    if include_icon and app.icon_url:
        urls_to_download.append((app.icon_url, "app_icon", "screenshot"))

    for url, label, ev_type in urls_to_download:
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content

            ext = ".webp"  # Play Store screenshots are typically WebP
            if "png" in resp.headers.get("Content-Type", ""):
                ext = ".png"
            elif "jpeg" in resp.headers.get("Content-Type", ""):
                ext = ".jpg"

            safe_name = re.sub(r'[^a-z0-9-]', '', app.name.lower().replace(' ', '-'))
            filename = _generate_filename(f"{safe_name}_{label}", ext)
            rel_path = store_file(project_id, entity_id, ev_type, content, filename)
            evidence_paths.append(rel_path)

            if db:
                ev_id = db.add_evidence(
                    entity_id=entity_id,
                    evidence_type=ev_type,
                    file_path=rel_path,
                    source_url=url,
                    source_name="Google Play Store",
                    metadata={
                        "package_id": app.package_id,
                        "app_name": app.name,
                        "label": label,
                        "file_size": len(content),
                    },
                )
                evidence_ids.append(ev_id)

        except Exception as e:
            errors.append(f"{label}: {e}")
            logger.debug("Failed to download %s: %s", url, e)

    metadata = {
        "package_id": app.package_id,
        "app_name": app.name,
        "developer": app.developer,
        "rating": app.rating,
        "screenshots_found": len(app.screenshot_urls),
        "screenshots_downloaded": len(evidence_paths),
        "store_url": app.store_url,
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0 or (not app.screenshot_urls and not errors),
        url=app.store_url,
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )


def get_app_metadata_for_entity(
    package_id: str,
    country: str = "gb",
) -> dict:
    """Get app metadata formatted as entity attributes.

    Returns:
        Dict of attribute_slug → value suitable for entity attribute updates
    """
    app = get_app_details(package_id, country=country)
    if not app:
        return {}

    return {
        "play_store_id": app.package_id,
        "play_store_url": app.store_url,
        "play_store_rating": app.rating,
        "play_store_developer": app.developer,
        "play_store_description": app.description[:500],
    }
