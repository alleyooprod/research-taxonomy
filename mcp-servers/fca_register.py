# CUSTOM MCP SERVER — replace with official package when available
"""FCA Register MCP server — UK Financial Conduct Authority.

Provides tools for searching authorised firms, getting firm details,
and checking regulated permissions.

API docs: https://register.fca.org.uk/Developer/s/
No authentication required.
"""
from fastmcp import FastMCP
import requests

mcp = FastMCP("fca-register")

FCA_BASE = "https://register.fca.org.uk/services/V0.1"
HEADERS = {"Accept": "application/json"}


def _safe_get(url, params=None, timeout=15):
    """Make a GET request with error handling."""
    resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
def fca_search_firms(query: str, limit: int = 10) -> str:
    """Search the FCA Register for authorised firms by name.

    The FCA (Financial Conduct Authority) regulates UK financial services firms
    including insurers, brokers, banks, and investment companies.

    Args:
        query: Firm name to search (e.g. "Aviva", "Admiral Group", "Lloyd's")
        limit: Maximum results to return (default 10)

    Returns:
        Table of firms with FRN (Firm Reference Number), name, status, and type.
    """
    data = _safe_get(f"{FCA_BASE}/Search", params={"q": query, "type": "firm"})

    results = data.get("Data", [])
    if not results:
        return f"No firms found matching '{query}' in the FCA Register."

    results = results[:limit]
    lines = [f"FCA Register: {len(results)} firms matching '{query}':\n"]
    lines.append(f"{'FRN':<12} {'Status':<14} {'Name'}")
    lines.append("-" * 70)

    for firm in results:
        frn = firm.get("FRN", "N/A")
        name = firm.get("Organisation Name", firm.get("Name", "N/A"))
        status = firm.get("Status", "N/A")
        lines.append(f"{frn:<12} {status:<14} {name}")

    return "\n".join(lines)


@mcp.tool()
def fca_get_firm(frn: str) -> str:
    """Get detailed information for a firm by its FRN (Firm Reference Number).

    Args:
        frn: FCA Firm Reference Number (e.g. "122702" for Aviva)

    Returns:
        Firm details: name, status, effective date, address, and regulators.
    """
    data = _safe_get(f"{FCA_BASE}/Firm/{frn}")

    firm = data.get("Data", [{}])
    if isinstance(firm, list):
        firm = firm[0] if firm else {}

    if not firm:
        return f"No firm found with FRN '{frn}'."

    lines = [
        f"FCA Firm Details (FRN: {frn}):",
        f"  Name:           {firm.get('Organisation Name', 'N/A')}",
        f"  Status:         {firm.get('Status', 'N/A')}",
        f"  Status Date:    {firm.get('Status Effective Date', 'N/A')}",
        f"  Type:           {firm.get('Organisation Type', 'N/A')}",
    ]

    # Address
    addr_parts = []
    for key in ["Address Line 1", "Address Line 2", "Town", "Postcode", "Country"]:
        val = firm.get(key, "")
        if val:
            addr_parts.append(val)
    if addr_parts:
        lines.append(f"  Address:        {', '.join(addr_parts)}")

    # Regulators
    regulators = firm.get("Regulators", [])
    if regulators:
        reg_names = [r.get("Name", "") for r in regulators if r.get("Name")]
        lines.append(f"  Regulators:     {', '.join(reg_names)}")

    # Names history
    names = data.get("Names", [])
    if names and len(names) > 1:
        lines.append(f"  Previous names: {len(names) - 1}")
        for n in names[:5]:
            ntype = n.get("Name Type", "")
            nval = n.get("Name", "")
            if nval:
                lines.append(f"    - {nval} ({ntype})")

    return "\n".join(lines)


@mcp.tool()
def fca_get_firm_permissions(frn: str) -> str:
    """Get the regulated permissions for a firm.

    Shows what activities the firm is authorised to perform under
    FCA/PRA regulation.

    Args:
        frn: FCA Firm Reference Number

    Returns:
        List of permissions with category, type, and effective date.
    """
    data = _safe_get(f"{FCA_BASE}/Firm/{frn}/Permissions")

    permissions = data.get("Data", [])
    if not permissions:
        return f"No permissions found for FRN '{frn}'."

    lines = [f"FCA Permissions for FRN {frn} ({len(permissions)} total):\n"]

    for perm in permissions[:30]:  # Cap at 30 to avoid huge output
        name = perm.get("Permission", perm.get("Regulated Activity", "N/A"))
        status = perm.get("Status", "")
        effective = perm.get("Effective Date", "")
        invest_type = perm.get("Investment Type", "")

        line = f"  - {name}"
        if status:
            line += f" [{status}]"
        if effective:
            line += f" (from {effective})"
        if invest_type:
            line += f" — {invest_type}"
        lines.append(line)

    if len(permissions) > 30:
        lines.append(f"\n  ... and {len(permissions) - 30} more permissions")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
