# CUSTOM MCP SERVER — replace with official package when available
from fastmcp import FastMCP
import requests
import csv
from io import StringIO

mcp = FastMCP("ecb")

BASE_URL = "https://data-api.ecb.europa.eu/service"
TIMEOUT = 30


@mcp.tool()
def ecb_get_series(
    dataflow: str,
    key: str,
    start_period: str = "",
    end_period: str = "",
) -> str:
    """Fetch a time series from the ECB Statistical Data Warehouse.

    Args:
        dataflow: Dataflow identifier, e.g. "EXR" for exchange rates,
                  "MIR" for MFI interest rates, "BSI" for balance sheet items,
                  "ICP" for HICP inflation, "FM" for financial markets.
        key: Dimension key for the series. Format depends on the dataflow.
             Examples:
               EXR: "D.USD.EUR.SP00.A" (daily USD/EUR spot rate)
               MIR: "M.U2.B.A2A.AM.R.A.2250.EUR.N" (lending rates)
               ICP: "M.U2.N.000000.4.ANR" (HICP euro area annual rate)
        start_period: Start date filter, e.g. "2023-01" or "2023-01-15". Optional.
        end_period: End date filter, e.g. "2024-12" or "2024-12-31". Optional.

    Returns:
        Formatted table of dates and values for the requested series.
    """
    url = f"{BASE_URL}/data/{dataflow}/{key}"
    params = {"detail": "dataonly", "format": "csvdata"}
    if start_period:
        params["startPeriod"] = start_period
    if end_period:
        params["endPeriod"] = end_period

    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        if status == 404:
            return (
                f"No data found for dataflow={dataflow}, key={key}. "
                "Check the dataflow and key format. Use ecb_search_dataflows() "
                "to find valid dataflows, or ecb_list_common_series() for examples."
            )
        return f"ECB API HTTP error {status}: {exc}"
    except requests.exceptions.RequestException as exc:
        return f"Request failed: {exc}"

    text = resp.text.strip()
    if not text:
        return "ECB returned an empty response. The series may not exist or has no data for the requested period."

    reader = csv.DictReader(StringIO(text))
    rows = list(reader)

    if not rows:
        return "No observations returned. Try broadening the date range or checking the key format."

    # Identify the date and value columns — ECB CSV uses TIME_PERIOD and OBS_VALUE
    date_col = None
    value_col = None
    for candidate in ("TIME_PERIOD", "PERIOD", "Date"):
        if candidate in rows[0]:
            date_col = candidate
            break
    for candidate in ("OBS_VALUE", "VALUE", "Value"):
        if candidate in rows[0]:
            value_col = candidate
            break

    if date_col is None or value_col is None:
        # Fallback: return raw column names and first few rows
        cols = list(rows[0].keys())
        lines = [f"Columns: {', '.join(cols)}"]
        for row in rows[:20]:
            lines.append("  |  ".join(row.get(c, "") for c in cols))
        if len(rows) > 20:
            lines.append(f"... ({len(rows)} rows total)")
        return "\n".join(lines)

    # Build a readable table
    title_col = None
    for candidate in ("TITLE", "TITLE_COMPL", "REF_AREA"):
        if candidate in rows[0]:
            title_col = candidate
            break

    header_parts = [f"Dataflow: {dataflow}", f"Key: {key}"]
    if title_col and rows[0].get(title_col):
        header_parts.append(f"Series: {rows[0][title_col]}")
    header_parts.append(f"Observations: {len(rows)}")

    lines = [" | ".join(header_parts), ""]
    lines.append(f"{'Date':<14} {'Value':>14}")
    lines.append("-" * 30)

    for row in rows:
        date = row.get(date_col, "")
        value = row.get(value_col, "")
        lines.append(f"{date:<14} {value:>14}")

    return "\n".join(lines)


@mcp.tool()
def ecb_search_dataflows(query: str) -> str:
    """Search available ECB dataflows by keyword.

    Args:
        query: Keyword to filter dataflows, e.g. "exchange", "interest",
               "inflation", "money supply", "balance sheet".

    Returns:
        List of matching dataflow IDs and their descriptions.
    """
    url = f"{BASE_URL}/dataflow/ECB"
    headers = {"Accept": "application/json"}

    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        return f"Failed to fetch dataflow list: {exc}"

    try:
        data = resp.json()
    except ValueError:
        return "ECB returned non-JSON response for dataflow list."

    # Navigate the SDMX JSON structure to extract dataflow info
    dataflows = []
    try:
        structures = data.get("Structure", data)
        flow_list = (
            structures.get("Dataflows", {}).get("Dataflow", [])
            if isinstance(structures, dict)
            else []
        )
        if not flow_list:
            # Try alternate SDMX-JSON paths
            flow_list = (
                data.get("data", {}).get("dataflows", [])
                or data.get("Dataflow", [])
                or []
            )

        for flow in flow_list:
            flow_id = flow.get("id", flow.get("agencyID", ""))
            # Description can be nested in Name array or a simple string
            name_field = flow.get("Name", flow.get("name", ""))
            if isinstance(name_field, list):
                description = next(
                    (n.get("#text", n.get("value", "")) for n in name_field),
                    str(name_field),
                )
            elif isinstance(name_field, dict):
                description = name_field.get("#text", name_field.get("value", str(name_field)))
            else:
                description = str(name_field)

            dataflows.append((flow_id, description))
    except (KeyError, TypeError, AttributeError):
        # If JSON structure is unexpected, try a simpler flat scan
        raw = resp.text
        query_lower = query.lower()
        if query_lower in raw.lower():
            return (
                f"Found references to '{query}' in ECB dataflow catalogue, "
                "but could not parse structured results. "
                "Try ecb_list_common_series() for known series."
            )
        return f"No dataflows matching '{query}' found."

    if not dataflows:
        return (
            "Could not parse dataflow list from ECB API. "
            "Try ecb_list_common_series() for commonly-used series."
        )

    # Filter by query
    query_lower = query.lower()
    matches = [
        (fid, desc)
        for fid, desc in dataflows
        if query_lower in fid.lower() or query_lower in desc.lower()
    ]

    if not matches:
        return (
            f"No dataflows matching '{query}' among {len(dataflows)} available. "
            "Try broader terms like 'rate', 'price', 'money', or 'financial'."
        )

    lines = [f"ECB Dataflows matching '{query}' ({len(matches)} results):", ""]
    for fid, desc in matches[:40]:
        lines.append(f"  {fid:<12} {desc}")
    if len(matches) > 40:
        lines.append(f"  ... and {len(matches) - 40} more")

    return "\n".join(lines)


@mcp.tool()
def ecb_list_common_series() -> str:
    """List commonly-used ECB data series with their dataflow and key codes.

    Returns a reference table of popular ECB series that can be fetched
    with ecb_get_series().
    """
    series = [
        {
            "name": "EUR/USD exchange rate (daily spot)",
            "dataflow": "EXR",
            "key": "D.USD.EUR.SP00.A",
            "notes": "Freq=Daily, Currency=USD, Ref=EUR, Type=Spot, Series=Average",
        },
        {
            "name": "EUR/GBP exchange rate (daily spot)",
            "dataflow": "EXR",
            "key": "D.GBP.EUR.SP00.A",
            "notes": "Freq=Daily, Currency=GBP, Ref=EUR, Type=Spot, Series=Average",
        },
        {
            "name": "ECB deposit facility rate",
            "dataflow": "FM",
            "key": "B.U2.EUR.4F.KR.DFR.LEV",
            "notes": "Business/Euro area/EUR/Key rates/Deposit facility rate/Level",
        },
        {
            "name": "ECB main refinancing operations rate",
            "dataflow": "FM",
            "key": "B.U2.EUR.4F.KR.MRR_FR.LEV",
            "notes": "Business/Euro area/EUR/Key rates/Main refinancing fixed rate/Level",
        },
        {
            "name": "M3 money supply (euro area, annual growth rate)",
            "dataflow": "BSI",
            "key": "M.U2.Y.V.M30.X.1.U2.2300.Z01.A",
            "notes": "Monthly/Euro area/Outstanding amounts/M3/Annual growth rate",
        },
        {
            "name": "HICP — overall index (euro area, annual rate of change)",
            "dataflow": "ICP",
            "key": "M.U2.N.000000.4.ANR",
            "notes": "Monthly/Euro area/All-items HICP/Annual rate of change",
        },
    ]

    lines = ["Commonly-used ECB data series:", ""]
    lines.append(f"{'Name':<50} {'Dataflow':<10} {'Key'}")
    lines.append("-" * 90)

    for s in series:
        lines.append(f"{s['name']:<50} {s['dataflow']:<10} {s['key']}")
        lines.append(f"  Notes: {s['notes']}")
        lines.append("")

    lines.append("Usage: ecb_get_series(dataflow='EXR', key='D.USD.EUR.SP00.A', start_period='2024-01')")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
