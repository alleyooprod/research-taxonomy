"""Apple App Store scraper via iTunes Search API.

Uses the public iTunes Search API (no authentication required):
    https://itunes.apple.com/search?term=...&entity=software

Extracts:
    - App metadata (name, description, rating, version, price, etc.)
    - Screenshot URLs (iPhone + iPad)
    - Icon artwork URLs
    - Developer info, genres, release notes

Usage:
    from core.scrapers.appstore import search_apps, get_app_details, download_screenshots

    results = search_apps("Vitality Health")
    details = get_app_details(app_id=123456)
    capture_result = download_screenshots(app_id=123456, project_id=1, entity_id=5, db=db)
"""
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import quote_plus

import requests
from loguru import logger

from core.capture import (
    store_file, _generate_filename, CaptureResult,
    evidence_path_relative, ALLOWED_EVIDENCE_TYPES,
)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 15  # seconds


@dataclass
class AppStoreApp:
    """Structured data from an App Store listing."""
    app_id: int
    name: str
    bundle_id: str = ""
    developer: str = ""
    developer_id: int = 0
    description: str = ""
    release_notes: str = ""
    version: str = ""
    price: float = 0.0
    currency: str = "USD"
    rating: float = 0.0
    rating_count: int = 0
    content_rating: str = ""
    genres: list[str] = field(default_factory=list)
    icon_url: str = ""
    icon_url_large: str = ""
    screenshot_urls: list[str] = field(default_factory=list)
    ipad_screenshot_urls: list[str] = field(default_factory=list)
    store_url: str = ""
    minimum_os: str = ""
    file_size_bytes: int = 0
    release_date: str = ""
    updated_date: str = ""
    supported_devices: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _parse_app_result(item: dict) -> AppStoreApp:
    """Parse a single iTunes API result into an AppStoreApp."""
    return AppStoreApp(
        app_id=item.get("trackId", 0),
        name=item.get("trackName", ""),
        bundle_id=item.get("bundleId", ""),
        developer=item.get("artistName", ""),
        developer_id=item.get("artistId", 0),
        description=item.get("description", ""),
        release_notes=item.get("releaseNotes", ""),
        version=item.get("version", ""),
        price=item.get("price", 0.0),
        currency=item.get("currency", "USD"),
        rating=item.get("averageUserRating", 0.0),
        rating_count=item.get("userRatingCount", 0),
        content_rating=item.get("contentAdvisoryRating", ""),
        genres=item.get("genres", []),
        icon_url=item.get("artworkUrl100", ""),
        icon_url_large=item.get("artworkUrl512", "")
                       or item.get("artworkUrl100", "").replace("100x100", "512x512"),
        screenshot_urls=item.get("screenshotUrls", []),
        ipad_screenshot_urls=item.get("ipadScreenshotUrls", []),
        store_url=item.get("trackViewUrl", ""),
        minimum_os=item.get("minimumOsVersion", ""),
        file_size_bytes=int(item.get("fileSizeBytes", 0) or 0),
        release_date=item.get("releaseDate", ""),
        updated_date=item.get("currentVersionReleaseDate", ""),
        supported_devices=item.get("supportedDevices", []),
    )


def search_apps(
    term: str,
    country: str = "gb",
    limit: int = 10,
) -> list[AppStoreApp]:
    """Search the App Store for apps matching a term.

    Args:
        term: Search query (e.g. "Vitality Health", "Bupa")
        country: Two-letter country code (default: "gb" for UK)
        limit: Max results (1-200, default 10)

    Returns:
        List of AppStoreApp results
    """
    params = {
        "term": term,
        "country": country,
        "entity": "software",
        "limit": min(limit, 200),
    }

    try:
        resp = requests.get(
            ITUNES_SEARCH_URL,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("App Store search failed for '%s': %s", term, e)
        return []

    results = []
    for item in data.get("results", []):
        if item.get("kind") == "software" or item.get("wrapperType") == "software":
            results.append(_parse_app_result(item))

    return results


def get_app_details(
    app_id: int,
    country: str = "gb",
) -> Optional[AppStoreApp]:
    """Get detailed info for a specific app by its App Store ID.

    Args:
        app_id: iTunes track ID (numeric)
        country: Two-letter country code

    Returns:
        AppStoreApp or None if not found
    """
    params = {
        "id": app_id,
        "country": country,
        "entity": "software",
    }

    try:
        resp = requests.get(
            ITUNES_LOOKUP_URL,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("App Store lookup failed for ID %d: %s", app_id, e)
        return None

    results = data.get("results", [])
    if not results:
        return None

    return _parse_app_result(results[0])


def download_screenshots(
    app_id: int,
    project_id: int,
    entity_id: int,
    db=None,
    country: str = "gb",
    include_ipad: bool = False,
    include_icon: bool = True,
) -> CaptureResult:
    """Download all screenshots for an App Store app and store as evidence.

    Args:
        app_id: iTunes track ID
        project_id: Project to store evidence under
        entity_id: Entity to link evidence to
        db: Database instance (if provided, creates evidence records)
        country: Two-letter country code
        include_ipad: Also download iPad screenshots
        include_icon: Download the app icon

    Returns:
        CaptureResult with paths to all downloaded files
    """
    start = time.time()

    app = get_app_details(app_id, country=country)
    if not app:
        return CaptureResult(
            success=False,
            url=f"itunes://app/{app_id}",
            error=f"App {app_id} not found in App Store",
            duration_ms=int((time.time() - start) * 1000),
        )

    evidence_paths = []
    evidence_ids = []
    errors = []

    urls_to_download = []

    # iPhone screenshots
    for i, url in enumerate(app.screenshot_urls):
        urls_to_download.append((url, f"iphone_screenshot_{i+1}", "screenshot"))

    # iPad screenshots (optional)
    if include_ipad:
        for i, url in enumerate(app.ipad_screenshot_urls):
            urls_to_download.append((url, f"ipad_screenshot_{i+1}", "screenshot"))

    # App icon
    if include_icon and app.icon_url_large:
        urls_to_download.append((app.icon_url_large, "app_icon", "screenshot"))

    for url, label, ev_type in urls_to_download:
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content

            # Determine extension from URL or content-type
            ext = ".jpg"  # App Store screenshots are typically JPEG
            if ".png" in url.lower():
                ext = ".png"
            elif ".webp" in url.lower():
                ext = ".webp"

            filename = _generate_filename(
                f"{app.name.lower().replace(' ', '-')}_{label}", ext
            )
            rel_path = store_file(project_id, entity_id, ev_type, content, filename)
            evidence_paths.append(rel_path)

            if db:
                ev_id = db.add_evidence(
                    entity_id=entity_id,
                    evidence_type=ev_type,
                    file_path=rel_path,
                    source_url=url,
                    source_name="Apple App Store",
                    metadata={
                        "app_id": app.app_id,
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
        "app_id": app.app_id,
        "app_name": app.name,
        "developer": app.developer,
        "version": app.version,
        "rating": app.rating,
        "rating_count": app.rating_count,
        "screenshots_found": len(app.screenshot_urls),
        "screenshots_downloaded": len(evidence_paths),
        "store_url": app.store_url,
    }
    if errors:
        metadata["download_errors"] = errors

    return CaptureResult(
        success=len(evidence_paths) > 0,
        url=app.store_url or f"itunes://app/{app_id}",
        evidence_paths=evidence_paths,
        evidence_ids=evidence_ids,
        error="; ".join(errors) if errors and not evidence_paths else None,
        metadata=metadata,
        duration_ms=int((time.time() - start) * 1000),
    )


def get_app_metadata_for_entity(
    app_id: int,
    country: str = "gb",
) -> dict:
    """Get app metadata formatted as entity attributes.

    Useful for populating entity attributes from App Store data.

    Returns:
        Dict of attribute_slug → value suitable for entity attribute updates
    """
    app = get_app_details(app_id, country=country)
    if not app:
        return {}

    return {
        "app_store_id": str(app.app_id),
        "app_store_url": app.store_url,
        "app_store_rating": app.rating,
        "app_store_rating_count": app.rating_count,
        "app_store_version": app.version,
        "app_store_price": app.price,
        "app_store_developer": app.developer,
        "app_store_genres": ", ".join(app.genres),
        "app_store_content_rating": app.content_rating,
        "app_store_release_date": app.release_date,
        "app_store_updated": app.updated_date,
        "app_store_description": app.description[:500],  # Truncate for attribute
    }
