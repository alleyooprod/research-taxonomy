# CUSTOM MCP SERVER — replace with official package when available
from fastmcp import FastMCP
import requests

mcp = FastMCP("dbnomics")

BASE_URL = "https://api.db.nomics.world/v22"

TIMEOUT = 30

KEY_PROVIDERS = {
    "Eurostat": "European Commission statistical office — GDP, trade, demographics, etc.",
    "ECB": "European Central Bank — interest rates, money supply, exchange rates",
    "BOE": "Bank of England — UK monetary policy, gilt yields, lending",
    "OECD": "Organisation for Economic Co-operation and Development — cross-country indicators",
    "IMF": "International Monetary Fund — global economic outlook, balance of payments",
    "WB": "World Bank — development indicators, poverty, health, education",
    "BIS": "Bank for International Settlements — credit, property prices, exchange rates",
    "INSEE": "French National Institute of Statistics — French economic data",
    "Destatis": "German Federal Statistical Office — German economic data",
    "ONS": "UK Office for National Statistics — UK economic and social data",
}


def _get(endpoint: str, params: dict | None = None) -> dict:
    """Make a GET request to the DBnomics API and return parsed JSON."""
    url = f"{BASE_URL}/{endpoint}" if not endpoint.startswith("http") else endpoint
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format headers and rows as an aligned text table."""
    if not rows:
        return "No data."

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(val)))

    # Build table
    header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * w for w in widths)
    lines = [header_line, separator]
    for row in rows:
        line = " | ".join(str(val).ljust(widths[i]) for i, val in enumerate(row))
        lines.append(line)

    return "\n".join(lines)


@mcp.tool()
def dbnomics_search(query: str, limit: int = 20) -> str:
    """Search across all DBnomics providers for economic/statistical series.

    DBnomics aggregates data from 80+ providers including Eurostat, ECB, OECD,
    IMF, World Bank, Bank of England, BIS, and many national statistics offices.

    Args:
        query: Search terms (e.g. "UK GDP quarterly", "euro area inflation",
               "unemployment rate Germany"). Supports natural language.
        limit: Maximum number of results to return (default: 20, max: 100).

    Returns:
        List of matching series with their IDs, provider, dataset, and description.
        Use the series ID with dbnomics_get_series() to fetch the actual data.
    """
    limit = min(max(1, limit), 100)

    try:
        data = _get("search", params={"q": query, "limit": limit})
    except requests.exceptions.Timeout:
        return "Error: DBnomics search timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to DBnomics API. Check network connection."
    except requests.exceptions.HTTPError as e:
        return f"Error: DBnomics returned HTTP {e.response.status_code}: {e}"
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    results = data.get("results", [])
    num_found = data.get("num_found", 0)

    if not results:
        return f"No results found for '{query}'. Try broader search terms."

    lines = [
        f"DBnomics search: '{query}' — {num_found} total results, showing {len(results)}",
        "",
    ]

    for i, item in enumerate(results, 1):
        series_id = item.get("series_id", "")
        provider = item.get("provider_code", "")
        dataset = item.get("dataset_code", "")
        name = item.get("series_name") or item.get("name") or item.get("description", "")
        # Truncate long descriptions
        if len(name) > 120:
            name = name[:117] + "..."

        # Try to get the last value if available
        last_period = item.get("indexed_at", "")
        nb_obs = item.get("nb_matching_series", item.get("nb_series", ""))

        lines.append(f"  {i}. {series_id}")
        lines.append(f"     Provider: {provider} | Dataset: {dataset}")
        if name:
            lines.append(f"     {name}")
        if nb_obs:
            lines.append(f"     Observations: {nb_obs}")
        lines.append("")

    lines.append("Usage: dbnomics_get_series('provider/dataset/series')")
    return "\n".join(lines)


@mcp.tool()
def dbnomics_get_series(series_id: str, limit: int = 50) -> str:
    """Fetch time series data from DBnomics.

    Args:
        series_id: One or more series identifiers in "provider/dataset/series" format.
                   Examples:
                     Single: "BOE/IUDBEDR/M"
                     Multiple (comma-separated): "ECB/EXR/D.USD.EUR.SP00.A,ECB/EXR/D.GBP.EUR.SP00.A"
                   Find series IDs using dbnomics_search().
        limit: Maximum number of observations to return per series (default: 50).
               Most recent observations are returned first.

    Returns:
        Time series data formatted as a table with period and value columns.
    """
    limit = min(max(1, limit), 1000)
    series_id = series_id.strip()

    if not series_id:
        return "Error: No series_id provided."

    # Determine if single or multiple series
    ids = [s.strip() for s in series_id.split(",") if s.strip()]

    try:
        if len(ids) == 1:
            # Single series — use direct path
            parts = ids[0].split("/")
            if len(parts) < 3:
                return (
                    f"Error: Invalid series_id '{ids[0]}'. "
                    f"Expected format: 'provider/dataset/series' (e.g. 'BOE/IUDBEDR/M')."
                )
            provider = parts[0]
            dataset = parts[1]
            series_code = "/".join(parts[2:])  # Series code may contain slashes
            data = _get(f"series/{provider}/{dataset}/{series_code}", params={"limit": limit})
        else:
            # Multiple series — use series_ids parameter
            joined = ",".join(ids)
            data = _get("series", params={"series_ids": joined, "limit": limit})

    except requests.exceptions.Timeout:
        return "Error: DBnomics request timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to DBnomics API. Check network connection."
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 404:
            return f"Error: Series '{series_id}' not found. Check the ID or use dbnomics_search()."
        return f"Error: DBnomics returned HTTP {status}: {e}"
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    # Extract series docs
    series_list = data.get("series", {}).get("docs", [])
    if not series_list:
        return f"No data found for series '{series_id}'."

    output_parts = []

    for series_doc in series_list:
        s_id = series_doc.get("series_id", series_id)
        s_name = series_doc.get("series_name") or series_doc.get("name", "")
        provider_code = series_doc.get("provider_code", "")
        dataset_code = series_doc.get("dataset_code", "")
        frequency = series_doc.get("@frequency", series_doc.get("frequency", ""))

        periods = series_doc.get("period", [])
        values = series_doc.get("value", [])

        header_lines = [f"Series: {s_id}"]
        if s_name:
            header_lines.append(f"Name: {s_name}")
        if provider_code:
            provider_name = KEY_PROVIDERS.get(provider_code, provider_code)
            if provider_name != provider_code:
                header_lines.append(f"Provider: {provider_code} ({provider_name})")
            else:
                header_lines.append(f"Provider: {provider_code}")
        if frequency:
            header_lines.append(f"Frequency: {frequency}")
        header_lines.append(f"Observations: {len(periods)}")
        header_lines.append("")

        if periods and values:
            rows = []
            for period, value in zip(periods, values):
                val_str = str(value) if value is not None and value != "NA" else "N/A"
                rows.append([str(period), val_str])
            table = _format_table(["Period", "Value"], rows)
            header_lines.append(table)
        else:
            header_lines.append("No observations available.")

        output_parts.append("\n".join(header_lines))

    return "\n\n---\n\n".join(output_parts)


@mcp.tool()
def dbnomics_list_providers() -> str:
    """List all data providers available on DBnomics.

    DBnomics aggregates 80+ statistical providers including central banks,
    national statistics offices, and international organisations.

    Returns:
        Table of provider codes and names. Use the provider code with
        dbnomics_search_datasets() to explore a provider's datasets.
    """
    try:
        data = _get("providers")
    except requests.exceptions.Timeout:
        return "Error: DBnomics request timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to DBnomics API. Check network connection."
    except requests.exceptions.HTTPError as e:
        return f"Error: DBnomics returned HTTP {e.response.status_code}: {e}"
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    providers = data.get("providers", {}).get("docs", [])
    if not providers:
        return "No providers returned from DBnomics."

    # Sort alphabetically by code
    providers.sort(key=lambda p: p.get("code", "").upper())

    rows = []
    for p in providers:
        code = p.get("code", "")
        name = p.get("name", "")
        # Truncate long names
        if len(name) > 80:
            name = name[:77] + "..."
        region = p.get("region", "")
        nb_datasets = str(p.get("nb_datasets", ""))
        rows.append([code, name, region, nb_datasets])

    header = f"DBnomics Providers — {len(providers)} available\n\n"
    table = _format_table(["Code", "Name", "Region", "Datasets"], rows)

    footer = (
        "\n\nKey providers: "
        + ", ".join(KEY_PROVIDERS.keys())
        + "\nUsage: dbnomics_search_datasets('Eurostat') to browse datasets"
    )

    return header + table + footer


@mcp.tool()
def dbnomics_search_datasets(provider_code: str, query: str = "") -> str:
    """List or search datasets for a specific DBnomics provider.

    Args:
        provider_code: Provider code (e.g. "Eurostat", "ECB", "BOE", "OECD", "IMF", "WB").
                       Use dbnomics_list_providers() to see all codes.
        query: Optional search terms to filter datasets (e.g. "GDP", "inflation").
               If empty, returns the first datasets for the provider.

    Returns:
        Table of dataset codes, names, and number of series.
        Use the dataset code with dbnomics_search() for more specific series discovery.
    """
    provider_code = provider_code.strip()
    if not provider_code:
        return "Error: No provider_code given. Use dbnomics_list_providers() to see codes."

    params = {"limit": 50}
    if query.strip():
        params["q"] = query.strip()

    try:
        data = _get(f"datasets/{provider_code}", params=params)
    except requests.exceptions.Timeout:
        return "Error: DBnomics request timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to DBnomics API. Check network connection."
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        if status == 404:
            return (
                f"Error: Provider '{provider_code}' not found. "
                f"Use dbnomics_list_providers() to see valid codes."
            )
        return f"Error: DBnomics returned HTTP {status}: {e}"
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    datasets = data.get("datasets", {}).get("docs", [])
    num_found = data.get("datasets", {}).get("num_found", 0)

    if not datasets:
        if query:
            return f"No datasets found for provider '{provider_code}' matching '{query}'."
        return f"No datasets found for provider '{provider_code}'."

    rows = []
    for ds in datasets:
        code = ds.get("code", "")
        name = ds.get("name", "")
        if isinstance(name, dict):
            name = name.get("en", str(name))
        # Truncate long names
        if len(name) > 90:
            name = name[:87] + "..."
        nb_series = str(ds.get("nb_series", ""))
        rows.append([code, name, nb_series])

    search_note = f" matching '{query}'" if query else ""
    header = (
        f"Datasets for {provider_code}{search_note} — "
        f"{num_found} total, showing {len(datasets)}\n\n"
    )
    table = _format_table(["Dataset Code", "Name", "Series"], rows)

    footer = (
        f"\n\nUsage: dbnomics_search('{provider_code} <keyword>') to find specific series"
        f"\n       dbnomics_get_series('{provider_code}/<dataset>/<series>')"
    )

    return header + table + footer


if __name__ == "__main__":
    mcp.run(transport="stdio")
