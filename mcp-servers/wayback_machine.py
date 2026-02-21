# CUSTOM MCP SERVER — replace with official package when available
"""Wayback Machine MCP server — Internet Archive CDX API.

Provides tools for searching archived website snapshots, finding the
closest snapshot to a date, and getting domain history statistics.

API docs: https://archive.org/developers/wayback-cdx-server.html
No authentication required.
"""
from fastmcp import FastMCP
import requests

mcp = FastMCP("wayback-machine")

CDX_URL = "https://web.archive.org/cdx/search/cdx"
AVAIL_URL = "https://archive.org/wayback/available"


@mcp.tool()
def wayback_search(
    url: str,
    limit: int = 20,
    from_date: str = "",
    to_date: str = "",
) -> str:
    """Search the Wayback Machine for archived snapshots of a URL.

    Args:
        url: URL or domain to search (e.g. "acme.com" or "https://www.acme.com/pricing")
        limit: Maximum number of snapshots to return (default 20)
        from_date: Start date filter as YYYYMMDD (optional)
        to_date: End date filter as YYYYMMDD (optional)

    Returns:
        Table of archived snapshots with timestamp, HTTP status, and URL.
    """
    params = {
        "url": url,
        "output": "json",
        "limit": str(limit),
        "fl": "timestamp,original,statuscode,mimetype,length",
    }
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date

    resp = requests.get(CDX_URL, params=params, timeout=20)
    resp.raise_for_status()
    rows = resp.json()

    if not rows or len(rows) < 2:
        return f"No archived snapshots found for '{url}'."

    header = rows[0]
    data = rows[1:]

    lines = [f"Found {len(data)} snapshots for {url}:\n"]
    lines.append(f"{'Timestamp':<16} {'Status':<6} {'Type':<20} {'Size':<10} URL")
    lines.append("-" * 80)
    for row in data:
        rec = dict(zip(header, row))
        ts = rec.get("timestamp", "")
        # Format: YYYYMMDDHHMMSS -> YYYY-MM-DD HH:MM
        ts_fmt = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}" if len(ts) >= 12 else ts
        lines.append(
            f"{ts_fmt:<16} {rec.get('statuscode', '-'):<6} "
            f"{rec.get('mimetype', '-'):<20} {rec.get('length', '-'):<10} "
            f"{rec.get('original', '')}"
        )

    return "\n".join(lines)


@mcp.tool()
def wayback_get_snapshot(url: str, timestamp: str = "") -> str:
    """Get the closest archived snapshot of a URL.

    Args:
        url: The URL to look up
        timestamp: Optional target date as YYYYMMDD (default: most recent)

    Returns:
        Snapshot metadata with archive URL for viewing.
    """
    params = {"url": url}
    if timestamp:
        params["timestamp"] = timestamp

    resp = requests.get(AVAIL_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    snapshots = data.get("archived_snapshots", {})
    closest = snapshots.get("closest")

    if not closest:
        return f"No archived snapshot found for '{url}'."

    lines = [
        f"Closest snapshot for {url}:",
        f"  Available: {closest.get('available', False)}",
        f"  Timestamp: {closest.get('timestamp', 'N/A')}",
        f"  Status:    {closest.get('status', 'N/A')}",
        f"  URL:       {closest.get('url', 'N/A')}",
    ]
    return "\n".join(lines)


@mcp.tool()
def wayback_domain_history(domain: str) -> str:
    """Get summary statistics for a domain in the Wayback Machine.

    Args:
        domain: Domain name (e.g. "acme.com")

    Returns:
        First capture date, last capture date, total snapshots, years active.
    """
    # Use CDX with collapse=digest for unique snapshots, sorted by timestamp
    params = {
        "url": f"{domain}/*",
        "output": "json",
        "fl": "timestamp",
        "collapse": "timestamp:8",  # One per day
        "limit": "10000",
    }

    resp = requests.get(CDX_URL, params=params, timeout=30)
    resp.raise_for_status()
    rows = resp.json()

    if not rows or len(rows) < 2:
        return f"No archive history found for '{domain}'."

    data = rows[1:]  # Skip header
    timestamps = [r[0] for r in data if r]

    if not timestamps:
        return f"No archive history found for '{domain}'."

    first = timestamps[0]
    last = timestamps[-1]
    total = len(timestamps)

    first_fmt = f"{first[:4]}-{first[4:6]}-{first[6:8]}" if len(first) >= 8 else first
    last_fmt = f"{last[:4]}-{last[4:6]}-{last[6:8]}" if len(last) >= 8 else last

    try:
        years = int(last[:4]) - int(first[:4])
    except (ValueError, IndexError):
        years = "?"

    lines = [
        f"Wayback Machine history for {domain}:",
        f"  First capture: {first_fmt}",
        f"  Last capture:  {last_fmt}",
        f"  Total days captured: {total}",
        f"  Years active: {years}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
