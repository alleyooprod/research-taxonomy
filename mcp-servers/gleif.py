# CUSTOM MCP SERVER — replace with official package when available
"""GLEIF MCP server — Global Legal Entity Identifier Foundation.

Provides tools for searching LEI (Legal Entity Identifier) codes,
getting entity details, and navigating parent relationships.

API docs: https://www.gleif.org/en/lei-data/gleif-api
No authentication required. Rate limit: 60 requests/minute.
"""
from fastmcp import FastMCP
import requests

mcp = FastMCP("gleif")

GLEIF_BASE = "https://api.gleif.org/api/v1"
HEADERS = {"Accept": "application/vnd.api+json"}


def _safe_get(url, params=None, timeout=15):
    """Make a GET request with error handling."""
    resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _extract_entity(record):
    """Extract key fields from a GLEIF lei-record."""
    attrs = record.get("attributes", {})
    entity = attrs.get("entity", {})
    reg = attrs.get("registration", {})

    legal_name = entity.get("legalName", {}).get("name", "N/A")
    jurisdiction = entity.get("jurisdiction", "N/A")
    category = entity.get("category", "N/A")
    status = entity.get("status", "N/A")
    lei = attrs.get("lei", record.get("id", "N/A"))

    # Address
    legal_addr = entity.get("legalAddress", {})
    addr_parts = []
    for key in ["addressLines", "city", "region", "country", "postalCode"]:
        val = legal_addr.get(key)
        if val:
            if isinstance(val, list):
                addr_parts.extend(val)
            else:
                addr_parts.append(str(val))
    address = ", ".join(addr_parts) if addr_parts else "N/A"

    # Registration
    reg_status = reg.get("status", "N/A")
    initial_reg = reg.get("initialRegistrationDate", "N/A")
    last_update = reg.get("lastUpdateDate", "N/A")
    next_renewal = reg.get("nextRenewalDate", "N/A")

    return {
        "lei": lei,
        "name": legal_name,
        "jurisdiction": jurisdiction,
        "category": category,
        "entity_status": status,
        "address": address,
        "reg_status": reg_status,
        "initial_reg": initial_reg,
        "last_update": last_update,
        "next_renewal": next_renewal,
    }


@mcp.tool()
def gleif_search_lei(query: str, limit: int = 10) -> str:
    """Search for Legal Entity Identifiers (LEIs) by entity name.

    LEIs are 20-character codes that uniquely identify legal entities
    participating in financial transactions worldwide.

    Args:
        query: Entity name to search (e.g. "Aviva", "Allianz", "Lloyd's")
        limit: Maximum results to return (default 10)

    Returns:
        Table of entities with LEI code, name, jurisdiction, and status.
    """
    data = _safe_get(
        f"{GLEIF_BASE}/lei-records",
        params={"filter[fulltext]": query, "page[size]": str(limit)},
    )

    records = data.get("data", [])
    if not records:
        return f"No LEI records found for '{query}'."

    lines = [f"GLEIF: {len(records)} entities matching '{query}':\n"]
    lines.append(f"{'LEI':<22} {'Status':<10} {'Jurisdiction':<6} Name")
    lines.append("-" * 80)

    for rec in records:
        info = _extract_entity(rec)
        lines.append(
            f"{info['lei']:<22} {info['entity_status']:<10} "
            f"{info['jurisdiction']:<6} {info['name']}"
        )

    return "\n".join(lines)


@mcp.tool()
def gleif_get_entity(lei: str) -> str:
    """Get detailed entity information by LEI code.

    Args:
        lei: 20-character LEI code (e.g. "213800NWSHMHGWKJXO50")

    Returns:
        Full entity details: legal name, jurisdiction, address, registration
        authority, category, and renewal status.
    """
    data = _safe_get(f"{GLEIF_BASE}/lei-records/{lei}")

    record = data.get("data")
    if not record:
        return f"No entity found for LEI '{lei}'."

    info = _extract_entity(record)

    lines = [
        f"GLEIF Entity Details (LEI: {info['lei']}):",
        f"  Legal Name:     {info['name']}",
        f"  Jurisdiction:   {info['jurisdiction']}",
        f"  Category:       {info['category']}",
        f"  Entity Status:  {info['entity_status']}",
        f"  Address:        {info['address']}",
        f"  Reg. Status:    {info['reg_status']}",
        f"  First Reg:      {info['initial_reg']}",
        f"  Last Update:    {info['last_update']}",
        f"  Next Renewal:   {info['next_renewal']}",
    ]
    return "\n".join(lines)


@mcp.tool()
def gleif_get_parents(lei: str) -> str:
    """Get the parent relationship chain for an entity.

    Shows direct and ultimate parent entities, useful for understanding
    corporate group structures.

    Args:
        lei: 20-character LEI code

    Returns:
        Direct and ultimate parent entities with their LEI, name,
        and relationship type.
    """
    lines = [f"Parent relationships for LEI {lei}:\n"]

    # Direct parent
    try:
        data = _safe_get(f"{GLEIF_BASE}/lei-records/{lei}/direct-parent")
        parent = data.get("data")
        if parent:
            info = _extract_entity(parent)
            lines.append(f"  Direct Parent:")
            lines.append(f"    LEI:  {info['lei']}")
            lines.append(f"    Name: {info['name']}")
            lines.append(f"    Jurisdiction: {info['jurisdiction']}")
        else:
            lines.append("  Direct Parent: None reported")
    except requests.exceptions.HTTPError:
        lines.append("  Direct Parent: Not available")

    # Ultimate parent
    try:
        data = _safe_get(f"{GLEIF_BASE}/lei-records/{lei}/ultimate-parent")
        parent = data.get("data")
        if parent:
            info = _extract_entity(parent)
            lines.append(f"\n  Ultimate Parent:")
            lines.append(f"    LEI:  {info['lei']}")
            lines.append(f"    Name: {info['name']}")
            lines.append(f"    Jurisdiction: {info['jurisdiction']}")
        else:
            lines.append("\n  Ultimate Parent: None reported (may be self)")
    except requests.exceptions.HTTPError:
        lines.append("\n  Ultimate Parent: Not available")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
