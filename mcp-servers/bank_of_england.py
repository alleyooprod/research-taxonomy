# CUSTOM MCP SERVER — replace with official package when available
from fastmcp import FastMCP
import requests
from datetime import datetime
import csv
import io

mcp = FastMCP("bank-of-england")

BOE_BASE_URL = "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"

COMMON_SERIES = {
    # Policy rates
    "IUDBEDR": "Bank Rate (official policy rate)",
    "IUDMNZC": "Monthly average Sterling Overnight Index Average (SONIA)",
    # Exchange rates
    "XUMAERD": "USD/GBP spot exchange rate",
    "XUMASER": "EUR/GBP spot exchange rate",
    "XUMAYES": "JPY/GBP spot exchange rate",
    # Inflation
    "LPMAUZI": "CPI annual rate (%)",
    "LPMB7WA": "RPI annual rate (%)",
    "LPMAVAA": "CPIH annual rate (%)",
    # Mortgage rates
    "IUMBV34": "Monthly average mortgage rate — 2yr fixed 75% LTV",
    "IUMBV37": "Monthly average mortgage rate — 5yr fixed 75% LTV",
    "CFMHSAX": "Monthly average Standard Variable Rate (SVR)",
    # Money supply
    "LPMAVAB": "M4 money supply annual growth (%)",
    # Gilt yields
    "IUDMNPY": "Monthly average yield on 2-year gilts",
    "IUDMNQY": "Monthly average yield on 5-year gilts",
    "IUDMNRY": "Monthly average yield on 10-year gilts",
    "IUDMNSY": "Monthly average yield on 20-year gilts",
    # Household lending
    "LPMB7WB": "Net mortgage lending (GBP millions)",
    "LPMB7WC": "Net consumer credit (GBP millions)",
}


def _convert_date(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD/MMM/YYYY format required by BoE API."""
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return dt.strftime("%d/%b/%Y")


def _parse_boe_csv(text: str) -> list[dict]:
    """Parse the CSV response from BoE IADB.

    The BoE CSV format typically has a header row with 'DATE' and series code
    columns. Rows contain the date and corresponding values.
    """
    # Strip any leading/trailing whitespace and BOM
    text = text.strip().lstrip("\ufeff")

    # Skip any blank lines at the start
    lines = text.splitlines()
    data_lines = []
    header_found = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if header_found:
                continue
            else:
                continue
        if not header_found and ("DATE" in stripped.upper() or stripped[0].isdigit()):
            header_found = True
        if header_found:
            data_lines.append(stripped)

    if not data_lines:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(data_lines)))
    rows = []
    for row in reader:
        cleaned = {}
        for key, value in row.items():
            if key is not None:
                cleaned[key.strip()] = value.strip() if value else ""
        rows.append(cleaned)
    return rows


def _format_table(rows: list[dict]) -> str:
    """Format parsed rows as an aligned text table."""
    if not rows:
        return "No data returned."

    columns = list(rows[0].keys())

    # Calculate column widths
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            val = row.get(col, "")
            widths[col] = max(widths[col], len(val))

    # Build header
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    separator = "-+-".join("-" * widths[col] for col in columns)

    # Build rows
    lines = [header, separator]
    for row in rows:
        line = " | ".join(row.get(col, "").ljust(widths[col]) for col in columns)
        lines.append(line)

    return "\n".join(lines)


@mcp.tool()
def boe_get_series(
    series_codes: str,
    start_date: str = "2020-01-01",
    end_date: str = "2025-12-31",
) -> str:
    """Fetch time series data from the Bank of England Statistical Interactive Database.

    Args:
        series_codes: Comma-separated BoE series codes (e.g. "IUDBEDR" for Bank Rate,
                      or "IUDBEDR,XUMAERD" for multiple series). Use boe_list_common_series()
                      to see available codes.
        start_date: Start date in YYYY-MM-DD format (default: 2020-01-01).
        end_date: End date in YYYY-MM-DD format (default: 2025-12-31).

    Returns:
        Formatted text table of the time series data, or an error message.
    """
    # Validate and convert dates
    try:
        api_start = _convert_date(start_date)
    except ValueError:
        return f"Error: Invalid start_date '{start_date}'. Use YYYY-MM-DD format."

    try:
        api_end = _convert_date(end_date)
    except ValueError:
        return f"Error: Invalid end_date '{end_date}'. Use YYYY-MM-DD format."

    # Clean up series codes
    codes = ",".join(c.strip().upper() for c in series_codes.split(",") if c.strip())
    if not codes:
        return "Error: No series codes provided."

    params = {
        "SeriesCodes": codes,
        "DateFrom": api_start,
        "DateTo": api_end,
        "csv.x": "1",
    }

    try:
        resp = requests.get(BOE_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return "Error: Request to Bank of England timed out after 30 seconds."
    except requests.exceptions.ConnectionError:
        return "Error: Could not connect to Bank of England database. Check network connection."
    except requests.exceptions.HTTPError as e:
        return f"Error: Bank of England returned HTTP {resp.status_code}: {e}"
    except requests.exceptions.RequestException as e:
        return f"Error: Request failed: {e}"

    content = resp.text

    # Check for error responses from BoE (they sometimes return HTML errors)
    if "<html" in content.lower()[:200]:
        if "not a valid" in content.lower() or "error" in content.lower():
            return (
                f"Error: The Bank of England rejected the request. Check that series "
                f"codes are valid: {codes}. Use boe_list_common_series() to see known codes."
            )
        return "Error: Received unexpected HTML response instead of CSV data."

    rows = _parse_boe_csv(content)

    if not rows:
        return (
            f"No data returned for series {codes} between {start_date} and {end_date}. "
            f"The series code may be invalid or no data exists for that date range."
        )

    # Add descriptions as a header note
    code_list = [c.strip() for c in codes.split(",")]
    descriptions = []
    for code in code_list:
        desc = COMMON_SERIES.get(code, "Unknown series")
        descriptions.append(f"  {code} = {desc}")

    header = f"Bank of England data: {start_date} to {end_date}\n"
    header += "Series:\n" + "\n".join(descriptions) + "\n"
    header += f"Rows: {len(rows)}\n\n"

    return header + _format_table(rows)


@mcp.tool()
def boe_list_common_series() -> str:
    """List commonly-used Bank of England statistical series codes.

    Returns a reference table of series codes covering policy rates, exchange rates,
    inflation measures, mortgage rates, money supply, gilt yields, and household lending.
    """
    categories = {
        "Policy Rates": ["IUDBEDR", "IUDMNZC"],
        "Exchange Rates": ["XUMAERD", "XUMASER", "XUMAYES"],
        "Inflation": ["LPMAUZI", "LPMB7WA", "LPMAVAA"],
        "Mortgage Rates": ["IUMBV34", "IUMBV37", "CFMHSAX"],
        "Money Supply": ["LPMAVAB"],
        "Gilt Yields": ["IUDMNPY", "IUDMNQY", "IUDMNRY", "IUDMNSY"],
        "Household Lending": ["LPMB7WB", "LPMB7WC"],
    }

    lines = ["Bank of England — Common Statistical Series Codes", "=" * 52, ""]

    for category, codes in categories.items():
        lines.append(f"{category}")
        lines.append("-" * len(category))
        for code in codes:
            desc = COMMON_SERIES.get(code, "")
            lines.append(f"  {code:10s}  {desc}")
        lines.append("")

    lines.append("Usage: boe_get_series('IUDBEDR', '2023-01-01', '2025-01-01')")
    lines.append("Multiple: boe_get_series('IUDBEDR,XUMAERD', '2023-01-01', '2025-01-01')")
    lines.append("")
    lines.append("Full database: https://www.bankofengland.co.uk/boeapps/database/")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
