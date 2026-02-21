# Custom MCP Servers

These are lightweight MCP servers built in-house to wrap public REST APIs that don't have official MCP server packages. They use [FastMCP](https://github.com/PrefectHQ/fastmcp) for minimal boilerplate.

**When official MCP servers become available for any of these APIs, switch to those and remove the custom version.**

## Servers

| File | API | Auth | Status |
|------|-----|------|--------|
| `bank_of_england.py` | [Bank of England IADB](https://www.bankofengland.co.uk/boeapps/database/) | None | CUSTOM — no official MCP exists |
| `eurostat.py` | [Eurostat API](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/) | None | CUSTOM — no official MCP exists |
| `ecb.py` | [ECB Statistical Data Warehouse](https://data.ecb.europa.eu/) | None | CUSTOM — no official MCP exists |
| `oecd.py` | [OECD SDMX API](https://data.oecd.org/api/) | None | CUSTOM — no official MCP exists |
| `dbnomics.py` | [DBnomics](https://db.nomics.world/) | None | CUSTOM — no official MCP exists |
| `cooper_hewitt.py` | [Cooper Hewitt Museum](https://collection.cooperhewitt.org/api/) | Free API key | CUSTOM — no official MCP exists |

## Dependencies

```bash
pip install fastmcp requests
```

Both are in the project's `requirements.txt`.

## Running

Each server runs as a standalone Python script via stdio transport:

```bash
python mcp-servers/bank_of_england.py
```

They're configured in `.mcp.json` and start automatically with Claude Code.

## API Keys Needed

- **Cooper Hewitt**: Register at https://collection.cooperhewitt.org/api/ → set `COOPER_HEWITT_API_KEY` env var in `.mcp.json`

## Switching to Official Servers

When an official MCP server package becomes available:

1. Install the official package (e.g. `npx -y bank-of-england-mcp`)
2. Update the entry in `.mcp.json` to use `npx`/`uvx` instead of `python`
3. Remove the corresponding `.py` file from this directory
4. Update this README
