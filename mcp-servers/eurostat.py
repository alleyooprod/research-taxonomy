# CUSTOM MCP SERVER — replace with official package when available
from fastmcp import FastMCP
import requests

mcp = FastMCP("eurostat")

_BASE_DATA = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
_BASE_SEARCH = "https://ec.europa.eu/eurostat/api/dissemination/catalogue/1.0/search"
_TIMEOUT = 30

_COMMON_DATASETS = [
    ("nama_10_gdp", "GDP and main components", "Annual GDP aggregates at current and constant prices, growth rates"),
    ("prc_hicp_manr", "HICP - monthly annual rate of change", "Harmonised consumer price inflation, monthly, year-over-year"),
    ("une_rt_m", "Unemployment rate - monthly", "Harmonised unemployment rate by sex, seasonally adjusted"),
    ("sts_inpr_m", "Industrial production - monthly", "Index of industrial production, monthly, seasonally adjusted"),
    ("demo_pjan", "Population on 1 January", "Population by age and sex on 1 January each year"),
    ("bop_c6_m", "Balance of payments - monthly", "Current account, goods, services, primary/secondary income"),
    ("prc_hicp_midx", "HICP - monthly index", "Harmonised index of consumer prices, monthly, 2015=100"),
    ("ei_bssi_m_r2", "Economic sentiment indicator - monthly", "Composite economic sentiment, confidence indicators"),
    ("tec00001", "GDP per capita in PPS", "GDP per capita in purchasing power standards, EU comparison"),
    ("tec00118", "Real GDP growth rate", "Real GDP growth rate as percentage change on previous year"),
    ("gov_10dd_edpt1", "Government deficit/surplus", "Government deficit(-) and surplus(+) as % of GDP"),
    ("gov_10q_ggnfa", "Government debt - quarterly", "Quarterly government debt, Maastricht definition"),
    ("earn_mw_cur", "Minimum wages", "Monthly minimum wages in EU member states, bi-annual"),
    ("tps00001", "Population on 1 January - total", "Total population on 1 January, simplified"),
    ("migr_imm1ctz", "Immigration by citizenship", "Immigration by age, sex, and citizenship"),
    ("nrg_bal_c", "Energy balance - complete", "Simplified energy balances in physical units"),
    ("env_air_gge", "Greenhouse gas emissions", "Greenhouse gas emissions by source sector, CO2-equivalent"),
    ("tour_occ_nim", "Tourism - nights spent", "Nights spent at tourist accommodation, monthly"),
    ("isoc_ci_in_h", "Internet access - households", "Households with internet access at home"),
    ("hlth_cd_asdr2", "Causes of death - standardised", "Causes of death, age-standardised death rate per 100,000"),
]


def _parse_jsonstat(data: dict) -> str:
    """Parse a JSON-stat 2.0 response into a readable table.

    JSON-stat structure:
      - id: ordered list of dimension names  e.g. ["geo", "time", "unit"]
      - size: list of dimension sizes          e.g. [2, 3, 1]
      - dimension: { dimName: { category: { index: {...}, label: {...} } } }
      - value: { "0": 1.5, "1": 2.3, ... } or [1.5, 2.3, ...]

    The flat value index maps to dimension coordinates via row-major order:
      flat_index = sum( coord[i] * product(size[i+1:]) )
    """
    dim_ids = data.get("id", [])
    sizes = data.get("size", [])
    dimensions = data.get("dimension", {})
    values = data.get("value", {})

    if not dim_ids or not sizes or not dimensions:
        return "No data dimensions found in response."

    # Build ordered label lists for each dimension.
    # category.index gives {label_key: position} and category.label gives {label_key: human_label}.
    dim_labels = []  # list of lists — each inner list is ordered labels for that dimension
    dim_keys = []    # list of lists — each inner list is ordered raw keys for that dimension
    for did in dim_ids:
        dim_info = dimensions.get(did, {})
        cat = dim_info.get("category", {})
        cat_index = cat.get("index", {})
        cat_label = cat.get("label", {})

        # cat_index can be a dict {key: position} or a list [key, ...]
        if isinstance(cat_index, list):
            ordered_keys = cat_index
        elif isinstance(cat_index, dict):
            ordered_keys = sorted(cat_index.keys(), key=lambda k: cat_index[k])
        else:
            ordered_keys = list(cat_label.keys()) if cat_label else []

        labels = [cat_label.get(k, k) for k in ordered_keys]
        dim_labels.append(labels)
        dim_keys.append(ordered_keys)

    # Compute strides for row-major indexing.
    strides = []
    stride = 1
    for s in reversed(sizes):
        strides.append(stride)
        stride *= s
    strides.reverse()

    # Enumerate all coordinate combinations and look up values.
    total = 1
    for s in sizes:
        total *= s

    # Cap output to avoid enormous tables.
    MAX_ROWS = 500
    if total > MAX_ROWS:
        note = f"\n(Showing first {MAX_ROWS} of {total} observations. Apply filters to narrow results.)\n"
    else:
        note = ""

    # Build header.
    header_parts = [d.upper() for d in dim_ids] + ["VALUE"]
    lines = [" | ".join(header_parts)]
    lines.append("-+-".join("-" * len(h) for h in header_parts))

    row_count = 0
    for flat_idx in range(total):
        if row_count >= MAX_ROWS:
            break

        # Decode flat index into per-dimension coordinates.
        coords = []
        remainder = flat_idx
        for i, s in enumerate(sizes):
            coord = remainder // strides[i]
            remainder %= strides[i]
            coords.append(coord)

        # Look up the value (may be missing).
        if isinstance(values, dict):
            val = values.get(str(flat_idx))
        elif isinstance(values, list):
            val = values[flat_idx] if flat_idx < len(values) else None
        else:
            val = None

        if val is None:
            val_str = ":"  # Eurostat convention for missing
        elif isinstance(val, float):
            val_str = f"{val:,.2f}" if val != int(val) else f"{int(val):,}"
        else:
            val_str = str(val)

        row_parts = []
        for i, coord in enumerate(coords):
            if coord < len(dim_labels[i]):
                row_parts.append(dim_labels[i][coord])
            else:
                row_parts.append(f"?{coord}")
        row_parts.append(val_str)

        lines.append(" | ".join(row_parts))
        row_count += 1

    label = data.get("label", "")
    updated = data.get("updated", "")
    source = data.get("source", "")
    meta_parts = []
    if label:
        meta_parts.append(f"Dataset: {label}")
    if source:
        meta_parts.append(f"Source: {source}")
    if updated:
        meta_parts.append(f"Last updated: {updated}")

    meta_str = "\n".join(meta_parts)
    table_str = "\n".join(lines)
    return f"{meta_str}\n\n{table_str}{note}"


@mcp.tool()
def eurostat_get_dataset(dataset_code: str, filters: str = "", lang: str = "EN") -> str:
    """Fetch a Eurostat dataset with optional dimension filters.

    Args:
        dataset_code: Eurostat dataset code, e.g. "prc_hicp_manr", "nama_10_gdp"
        filters: URL-style filter string for dimensions, e.g. "geo=DE&geo=FR&time=2023&time=2024".
                 Multiple values for the same dimension use repeated keys.
                 Common dimensions: geo (country), time (year/period), unit, age, sex, nace_r2.
        lang: Language code for labels (EN, FR, DE). Default EN.

    Returns:
        Formatted table of observations with resolved dimension labels.
    """
    dataset_code = dataset_code.strip()
    if not dataset_code:
        return "Error: dataset_code is required."

    url = f"{_BASE_DATA}/{dataset_code}"
    params = {"format": "JSON", "lang": lang.upper()}

    # Parse the filter string and add each key=value pair to params.
    if filters:
        for part in filters.split("&"):
            part = part.strip()
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or not value:
                continue
            # requests handles repeated keys when given a list of tuples,
            # but here we build manually for clarity.
            if key in params:
                existing = params[key]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    params[key] = [existing, value]
            else:
                params[key] = value

    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
    except requests.Timeout:
        return f"Error: Request timed out after {_TIMEOUT}s. Try adding filters to reduce data volume."
    except requests.ConnectionError:
        return "Error: Could not connect to Eurostat API. Check network connectivity."
    except requests.RequestException as e:
        return f"Error: Request failed — {e}"

    if resp.status_code == 404:
        return f"Error: Dataset '{dataset_code}' not found. Use eurostat_search_datasets to find valid codes."
    if resp.status_code == 400:
        return f"Error: Bad request — check filter dimensions. Response: {resp.text[:500]}"
    if resp.status_code != 200:
        return f"Error: Eurostat API returned HTTP {resp.status_code}. Response: {resp.text[:500]}"

    try:
        data = resp.json()
    except ValueError:
        return "Error: Could not parse JSON response from Eurostat."

    # JSON-stat 2.0 responses may be wrapped in a dataset envelope.
    # Some endpoints return {"version": "2.0", ...} directly; others wrap in a class key.
    if "class" in data and data.get("class") == "dataset":
        pass  # Already a flat dataset
    elif "id" not in data and len(data) == 1:
        # Might be wrapped: {"datasetCode": {...}}
        inner = next(iter(data.values()))
        if isinstance(inner, dict) and "id" in inner:
            data = inner

    if "id" not in data:
        return f"Error: Unexpected response structure. Keys: {list(data.keys())[:10]}"

    return _parse_jsonstat(data)


@mcp.tool()
def eurostat_search_datasets(query: str) -> str:
    """Search the Eurostat dataset catalogue by keyword.

    Args:
        query: Search terms, e.g. "GDP growth", "unemployment rate", "inflation HICP"

    Returns:
        List of matching datasets with code, title, and description (top 20).
    """
    query = query.strip()
    if not query:
        return "Error: query is required."

    url = _BASE_SEARCH
    params = {
        "searchText": query,
        "lang": "EN",
    }

    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
    except requests.Timeout:
        return f"Error: Search timed out after {_TIMEOUT}s."
    except requests.ConnectionError:
        return "Error: Could not connect to Eurostat catalogue API."
    except requests.RequestException as e:
        return f"Error: Request failed — {e}"

    if resp.status_code != 200:
        return f"Error: Eurostat catalogue returned HTTP {resp.status_code}. {resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return "Error: Could not parse JSON response from catalogue."

    # The catalogue response structure varies. Common shapes:
    # 1. {"datasetList": [{"code": ..., "title": ..., "description": ...}, ...]}
    # 2. {"results": [...]}
    # 3. Direct list
    datasets = []
    if isinstance(data, list):
        datasets = data
    elif isinstance(data, dict):
        for key in ("datasetList", "results", "items", "datasets"):
            if key in data:
                candidate = data[key]
                if isinstance(candidate, list):
                    datasets = candidate
                    break
        if not datasets:
            # Try top-level if it looks like a single-result wrapper
            if "code" in data:
                datasets = [data]

    if not datasets:
        return f"No datasets found for '{query}'. Try broader search terms."

    # Limit to 20.
    datasets = datasets[:20]

    lines = [f"Eurostat datasets matching '{query}' ({len(datasets)} shown):\n"]
    for i, ds in enumerate(datasets, 1):
        code = ds.get("code", ds.get("id", "?"))
        title = ds.get("title", ds.get("name", ""))
        # Title may be a dict with language keys.
        if isinstance(title, dict):
            title = title.get("en", title.get("EN", next(iter(title.values()), "")))
        description = ds.get("description", ds.get("shortDescription", ""))
        if isinstance(description, dict):
            description = description.get("en", description.get("EN", next(iter(description.values()), "")))
        if description and len(description) > 200:
            description = description[:200] + "..."

        lines.append(f"{i:2d}. [{code}] {title}")
        if description:
            lines.append(f"    {description}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def eurostat_list_common_datasets() -> str:
    """List commonly-used Eurostat dataset codes with descriptions.

    Returns a curated reference of popular datasets covering GDP, inflation,
    unemployment, trade, population, industry, energy, and more.
    """
    lines = ["Commonly-used Eurostat datasets:\n"]
    # Group by broad category.
    categories = {
        "Economy & National Accounts": [
            "nama_10_gdp", "tec00001", "tec00118",
        ],
        "Prices & Inflation": [
            "prc_hicp_manr", "prc_hicp_midx",
        ],
        "Labour Market": [
            "une_rt_m", "earn_mw_cur",
        ],
        "Industry & Production": [
            "sts_inpr_m",
        ],
        "Trade & Balance of Payments": [
            "bop_c6_m",
        ],
        "Government Finance": [
            "gov_10dd_edpt1", "gov_10q_ggnfa",
        ],
        "Population & Migration": [
            "demo_pjan", "tps00001", "migr_imm1ctz",
        ],
        "Business Confidence": [
            "ei_bssi_m_r2",
        ],
        "Energy & Environment": [
            "nrg_bal_c", "env_air_gge",
        ],
        "Tourism": [
            "tour_occ_nim",
        ],
        "Digital & Society": [
            "isoc_ci_in_h",
        ],
        "Health": [
            "hlth_cd_asdr2",
        ],
    }

    lookup = {code: (code, title, desc) for code, title, desc in _COMMON_DATASETS}

    for category, codes in categories.items():
        lines.append(f"  {category}:")
        for code in codes:
            if code in lookup:
                _, title, desc = lookup[code]
                lines.append(f"    {code:25s} {title}")
                lines.append(f"    {'':25s} {desc}")
            else:
                lines.append(f"    {code}")
        lines.append("")

    lines.append("Usage: eurostat_get_dataset(dataset_code, filters)")
    lines.append('Example: eurostat_get_dataset("une_rt_m", "geo=DE&geo=FR&time=2024M01&time=2024M06")')
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
