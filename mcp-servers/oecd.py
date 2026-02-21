# CUSTOM MCP SERVER — replace with official package when available
from fastmcp import FastMCP
import requests

mcp = FastMCP("oecd")

BASE_URL = "https://sdmx.oecd.org/public/rest"
HEADERS = {"Accept": "application/vnd.sdmx.data+json; charset=utf-8; version=2"}
DATAFLOW_HEADERS = {"Accept": "application/vnd.sdmx.structure+json; charset=utf-8; version=2"}
TIMEOUT = 60

# ---------------------------------------------------------------------------
# Common dataset reference
# ---------------------------------------------------------------------------

COMMON_DATASETS = {
    # National accounts / GDP
    "OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_CAPITA,1.0": "Quarterly National Accounts — GDP expenditure per capita",
    "OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE1_EXPENDITURE,1.0": "Annual National Accounts — GDP expenditure approach",
    "OECD.SDD.NAD,DSD_NAAG@DF_NAAG_I,1.0": "Annual National Accounts — income approach",

    # Prices / Inflation
    "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0": "Consumer Prices (CPI) — all items",
    "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_HICP,1.0": "Harmonised Index of Consumer Prices (HICP)",

    # Labour market
    "OECD.SDD.TPS,DSD_LFS@DF_IALFS_INDIC,1.0": "Labour Force Statistics — indicators",
    "OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0": "Unemployment rate — monthly",
    "OECD.SDD.TPS,DSD_LFS@DF_IALFS_EMP_WAP_M,1.0": "Employment-population ratio — monthly",

    # Interest rates
    "OECD.SDD.SNAS,DSD_KEI@DF_KEI,1.0": "Key Economic Indicators (KEI) — broad macro",
    "OECD.SDD.TPS,DSD_MEI@DF_MEI,1.0": "Main Economic Indicators (MEI)",

    # Trade
    "OECD.SDD.TPS,DSD_BTDIXE@DF_BTDIXE_TOTAL,1.0": "International Trade in Goods — total",

    # Productivity
    "OECD.SDD.NAD,DSD_PDYGTH@DF_PDYGTH,1.0": "Productivity — GDP per hour worked growth",

    # Purchasing Power Parities
    "OECD.SDD.NAD,DSD_PPPGDP@DF_PPPGDP,1.0": "Purchasing Power Parities for GDP",

    # Insurance-specific
    "OECD.SDD.TPS,DSD_INSIND@DF_INSIND,1.0": "Insurance Indicators",

    # Housing
    "OECD.SDD.TPS,DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES,1.0": "Analytical House Price Indicators",
}


# ---------------------------------------------------------------------------
# SDMX-JSON parsing helpers
# ---------------------------------------------------------------------------

def _parse_sdmx_json(data: dict) -> str:
    """Parse SDMX-JSON v2 response into a readable text table.

    SDMX-JSON stores observations in a compact form with dimension indices
    pointing into parallel arrays of dimension values.  This function
    reconstructs human-readable rows.
    """
    try:
        datasets = data.get("data", {}).get("dataSets", data.get("dataSets", []))
        structure = data.get("data", {}).get("structures", data.get("structure", {}))

        if not datasets:
            return "No datasets in response."

        # --- Resolve dimension labels -------------------------------------------
        # SDMX-JSON v2 puts dimensions under structure[0].dimensions or
        # structure.dimensions depending on the response shape.
        dims_container = None
        if isinstance(structure, list) and structure:
            dims_container = structure[0]
        elif isinstance(structure, dict):
            dims_container = structure
        else:
            dims_container = {}

        obs_dimensions = dims_container.get("dimensions", {}).get("observation", [])
        series_dimensions = dims_container.get("dimensions", {}).get("series", [])

        # Build value-lookup lists for each dimension
        def _dim_values(dim_obj: dict) -> list[str]:
            values = dim_obj.get("values", [])
            return [v.get("name", v.get("id", str(i))) for i, v in enumerate(values)]

        def _dim_ids(dim_obj: dict) -> list[str]:
            values = dim_obj.get("values", [])
            return [v.get("id", str(i)) for i, v in enumerate(values)]

        series_dim_names = [d.get("name", d.get("id", f"Dim{i}")) for i, d in enumerate(series_dimensions)]
        series_dim_vals = [_dim_values(d) for d in series_dimensions]
        obs_dim_names = [d.get("name", d.get("id", f"ObsDim{i}")) for i, d in enumerate(obs_dimensions)]
        obs_dim_vals = [_dim_values(d) for d in obs_dimensions]

        # --- Collect rows -------------------------------------------------------
        rows: list[dict[str, str]] = []
        ds = datasets[0]

        # Case 1: flat observations (no series grouping)
        if "observations" in ds and "series" not in ds:
            obs_map = ds["observations"]
            for obs_key, obs_val in obs_map.items():
                row: dict[str, str] = {}
                indices = [int(x) for x in obs_key.split(":")]
                for j, idx in enumerate(indices):
                    if j < len(obs_dim_names):
                        name = obs_dim_names[j]
                        val = obs_dim_vals[j][idx] if idx < len(obs_dim_vals[j]) else str(idx)
                        row[name] = val
                value = obs_val[0] if isinstance(obs_val, list) and obs_val else obs_val
                row["Value"] = str(value) if value is not None else ""
                rows.append(row)

        # Case 2: series → observations
        elif "series" in ds:
            series_map = ds["series"]
            for series_key, series_obj in series_map.items():
                s_indices = [int(x) for x in series_key.split(":")]
                series_labels: dict[str, str] = {}
                for j, idx in enumerate(s_indices):
                    if j < len(series_dim_names):
                        name = series_dim_names[j]
                        val = series_dim_vals[j][idx] if idx < len(series_dim_vals[j]) else str(idx)
                        series_labels[name] = val

                obs_map = series_obj.get("observations", {})
                for obs_key, obs_val in obs_map.items():
                    row = dict(series_labels)
                    o_indices = [int(x) for x in obs_key.split(":")]
                    for j, idx in enumerate(o_indices):
                        if j < len(obs_dim_names):
                            name = obs_dim_names[j]
                            val = obs_dim_vals[j][idx] if idx < len(obs_dim_vals[j]) else str(idx)
                            row[name] = val
                    value = obs_val[0] if isinstance(obs_val, list) and obs_val else obs_val
                    row["Value"] = str(value) if value is not None else ""
                    rows.append(row)

        if not rows:
            return "Response parsed but contained no observations."

        # --- Cap output ---------------------------------------------------------
        total = len(rows)
        truncated = False
        if total > 500:
            rows = rows[:500]
            truncated = True

        # --- Format as text table -----------------------------------------------
        columns = list(rows[0].keys())
        widths = {col: len(col) for col in columns}
        for row in rows:
            for col in columns:
                widths[col] = max(widths[col], len(row.get(col, "")))

        # Cap column width to avoid extremely wide output
        for col in widths:
            widths[col] = min(widths[col], 60)

        header = " | ".join(col.ljust(widths[col])[:widths[col]] for col in columns)
        sep = "-+-".join("-" * widths[col] for col in columns)
        lines = [header, sep]
        for row in rows:
            line = " | ".join(
                row.get(col, "").ljust(widths[col])[:widths[col]] for col in columns
            )
            lines.append(line)

        summary = f"Observations: {total}"
        if truncated:
            summary += f" (showing first 500)"

        return summary + "\n\n" + "\n".join(lines)

    except Exception as e:
        return f"Error parsing SDMX-JSON response: {e}"


def _parse_dataflow_response(data: dict, query: str) -> str:
    """Parse SDMX-JSON dataflow structure response, filtering by keyword."""
    try:
        query_lower = query.lower()

        # Navigate the structure — can vary between API versions
        dataflows = []

        # v2: data.dataflows[]
        if "data" in data and "dataflows" in data["data"]:
            raw = data["data"]["dataflows"]
        elif "dataflows" in data:
            raw = data["dataflows"]
        # v2 structure message format
        elif "data" in data and "structures" in data["data"]:
            raw = data["data"].get("structures", [])
        else:
            raw = []

        for df in raw:
            df_id = df.get("id", "")
            agency = df.get("agencyID", df.get("agencyId", ""))
            version = df.get("version", "")

            # Names can be a dict {en: "..."} or a string
            names = df.get("names", df.get("name", {}))
            if isinstance(names, dict):
                name = names.get("en", names.get("EN", next(iter(names.values()), "")))
            elif isinstance(names, str):
                name = names
            else:
                name = str(names)

            # Descriptions can also be dict or string
            descs = df.get("descriptions", df.get("description", {}))
            if isinstance(descs, dict):
                desc = descs.get("en", descs.get("EN", next(iter(descs.values()), "")))
            elif isinstance(descs, str):
                desc = descs
            else:
                desc = ""

            # Build full dataflow identifier
            full_id = f"{agency},{df_id},{version}" if agency and version else df_id

            # Filter
            searchable = f"{df_id} {name} {desc}".lower()
            if query_lower and query_lower not in searchable:
                continue

            dataflows.append({
                "id": full_id,
                "name": name,
                "description": desc[:120] if desc else "",
            })

        if not dataflows:
            return f"No dataflows found matching '{query}'."

        # Sort by name
        dataflows.sort(key=lambda x: x["name"].lower())

        # Cap results
        total = len(dataflows)
        truncated = False
        if total > 100:
            dataflows = dataflows[:100]
            truncated = True

        lines = [f"OECD Dataflows matching '{query}' — {total} found", "=" * 60, ""]
        for df in dataflows:
            lines.append(f"  {df['id']}")
            lines.append(f"    {df['name']}")
            if df["description"] and df["description"] != df["name"]:
                lines.append(f"    {df['description']}")
            lines.append("")

        if truncated:
            lines.append(f"(showing first 100 of {total})")

        lines.append("")
        lines.append("Usage: oecd_get_data('<dataflow_id>', key='all', start_period='2020', end_period='2024')")

        return "\n".join(lines)

    except Exception as e:
        return f"Error parsing dataflow response: {e}"


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def oecd_get_data(
    dataflow_id: str,
    key: str = "all",
    start_period: str = "",
    end_period: str = "",
) -> str:
    """Fetch statistical data from the OECD SDMX API.

    Args:
        dataflow_id: Full dataflow identifier, e.g.
            "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0" for CPI data.
            Use oecd_search_dataflows() or oecd_list_common_datasets() to find IDs.
        key: Dimension filter for the data. Use "all" for all available data,
            or dot-separated dimension values to filter, e.g. "GBR+USA..GP.A"
            for UK and US annual GDP growth. The exact dimensions depend on
            the dataset — check the dataset structure if unsure.
        start_period: Start of date range, e.g. "2020" or "2020-Q1" or "2020-01".
        end_period: End of date range, e.g. "2024" or "2024-Q4" or "2024-12".

    Returns:
        Formatted text table of observations with dimension labels and values,
        or an error message.
    """
    if not dataflow_id.strip():
        return "Error: dataflow_id is required. Use oecd_list_common_datasets() to see options."

    # Build URL
    url = f"{BASE_URL}/data/{dataflow_id.strip()}/{key}"

    params = {}
    if start_period:
        params["startPeriod"] = start_period
    if end_period:
        params["endPeriod"] = end_period

    # Add dimensionAtObservation to get a simpler structure
    params["dimensionAtObservation"] = "AllDimensions"

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        return f"Error: Request timed out after {TIMEOUT} seconds. Try a narrower filter or date range."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to OECD SDMX API. Check network connection."
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    if resp.status_code == 404:
        return (
            f"Error: No data found for dataflow '{dataflow_id}' with key '{key}'. "
            f"The dataflow ID may be incorrect or no data matches the filter. "
            f"Use oecd_search_dataflows() to verify the dataflow exists."
        )
    if resp.status_code == 400:
        # SDMX APIs return 400 for invalid dimension filters
        try:
            err_body = resp.json()
            msg = err_body.get("errors", [{}])[0].get("message", resp.text[:300])
        except Exception:
            msg = resp.text[:300]
        return f"Error: Invalid request (HTTP 400). The key filter may be malformed.\nDetail: {msg}"
    if resp.status_code == 413:
        return (
            "Error: Response too large (HTTP 413). Narrow down the query by:\n"
            "  - Using a more specific key filter (e.g. 'GBR..GP.A' instead of 'all')\n"
            "  - Restricting the date range with start_period / end_period\n"
        )
    if resp.status_code != 200:
        return f"Error: OECD API returned HTTP {resp.status_code}.\n{resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return f"Error: Could not parse JSON response.\n{resp.text[:300]}"

    result = _parse_sdmx_json(data)

    header = f"OECD Data: {dataflow_id}\n"
    header += f"Filter: {key}"
    if start_period or end_period:
        header += f"  |  Period: {start_period or '...'} to {end_period or '...'}"
    header += "\n\n"

    return header + result


@mcp.tool()
def oecd_search_dataflows(query: str) -> str:
    """Search available OECD dataflows (datasets) by keyword.

    The OECD publishes thousands of statistical datasets. This tool searches
    dataflow names and descriptions to help you find the right dataset ID
    to use with oecd_get_data().

    Args:
        query: Keyword to search for, e.g. "insurance", "GDP", "unemployment",
            "housing", "inflation", "trade", "health", "education", "tax".

    Returns:
        List of matching dataflows with their full IDs, names, and descriptions.
    """
    if not query.strip():
        return "Error: query is required. Provide a keyword like 'GDP', 'insurance', 'unemployment'."

    url = f"{BASE_URL}/dataflow/OECD"

    try:
        resp = requests.get(url, headers=DATAFLOW_HEADERS, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        return f"Error: Request timed out after {TIMEOUT} seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to OECD SDMX API. Check network connection."
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    if resp.status_code != 200:
        return f"Error: OECD API returned HTTP {resp.status_code}.\n{resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return f"Error: Could not parse JSON response.\n{resp.text[:300]}"

    return _parse_dataflow_response(data, query.strip())


@mcp.tool()
def oecd_list_common_datasets() -> str:
    """List commonly-used OECD statistical datasets with their dataflow IDs.

    Returns a curated reference of popular OECD datasets covering GDP,
    inflation, unemployment, trade, interest rates, productivity,
    purchasing power parities, insurance, and housing prices.

    Use these dataflow IDs with oecd_get_data() to fetch data.
    """
    categories = {
        "National Accounts / GDP": [
            "OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_CAPITA,1.0",
            "OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE1_EXPENDITURE,1.0",
            "OECD.SDD.NAD,DSD_NAAG@DF_NAAG_I,1.0",
        ],
        "Prices / Inflation": [
            "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0",
            "OECD.SDD.TPS,DSD_PRICES@DF_PRICES_HICP,1.0",
        ],
        "Labour Market": [
            "OECD.SDD.TPS,DSD_LFS@DF_IALFS_INDIC,1.0",
            "OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0",
            "OECD.SDD.TPS,DSD_LFS@DF_IALFS_EMP_WAP_M,1.0",
        ],
        "Macro Indicators": [
            "OECD.SDD.SNAS,DSD_KEI@DF_KEI,1.0",
            "OECD.SDD.TPS,DSD_MEI@DF_MEI,1.0",
        ],
        "International Trade": [
            "OECD.SDD.TPS,DSD_BTDIXE@DF_BTDIXE_TOTAL,1.0",
        ],
        "Productivity": [
            "OECD.SDD.NAD,DSD_PDYGTH@DF_PDYGTH,1.0",
        ],
        "Purchasing Power Parities": [
            "OECD.SDD.NAD,DSD_PPPGDP@DF_PPPGDP,1.0",
        ],
        "Insurance": [
            "OECD.SDD.TPS,DSD_INSIND@DF_INSIND,1.0",
        ],
        "Housing": [
            "OECD.SDD.TPS,DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES,1.0",
        ],
    }

    lines = [
        "OECD — Common Statistical Datasets",
        "=" * 52,
        "",
        "These dataflow IDs can be used with oecd_get_data().",
        "",
    ]

    for category, ids in categories.items():
        lines.append(category)
        lines.append("-" * len(category))
        for df_id in ids:
            desc = COMMON_DATASETS.get(df_id, "")
            lines.append(f"  {desc}")
            lines.append(f"    ID: {df_id}")
        lines.append("")

    lines.append("Examples:")
    lines.append("  oecd_get_data('OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0', 'GBR+USA.CPI', '2020', '2024')")
    lines.append("  oecd_get_data('OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0', 'GBR', '2023', '2024')")
    lines.append("  oecd_get_data('OECD.SDD.TPS,DSD_INSIND@DF_INSIND,1.0', 'GBR+DEU+FRA', '2015', '2023')")
    lines.append("")
    lines.append("Key filter syntax:")
    lines.append("  'all'                  — all data (may be large, add date range)")
    lines.append("  'GBR'                  — United Kingdom only")
    lines.append("  'GBR+USA+DEU'          — multiple countries")
    lines.append("  'GBR..GP.A'            — UK, all measures, growth prev period, annual")
    lines.append("  Dots separate dimensions; + separates values within a dimension")
    lines.append("")
    lines.append("Country codes: 3-letter ISO (GBR, USA, DEU, FRA, JPN, CAN, ITA, AUS, ...)")
    lines.append("               OECD = OECD aggregate, EA20 = Euro area, G7M = G7")
    lines.append("")
    lines.append("To discover other datasets: oecd_search_dataflows('keyword')")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
