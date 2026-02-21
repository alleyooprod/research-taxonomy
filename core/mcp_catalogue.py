"""MCP Server Capability Catalogue.

Single source of truth for all MCP-backed data sources available to the
enrichment pipeline.  Each entry describes a server's capabilities, cost
profile, entity-type relevance, and health status.

The enrichment orchestrator (``mcp_enrichment.py``) uses this catalogue
to make smart routing decisions — selecting the most relevant, cheapest,
and healthiest servers for a given entity context.

Design decisions:
- Python dict, not a database table: this is developer-managed config,
  not runtime data.  Easier to maintain, type-check, and test.
- Health tracking (dynamic) reuses the existing ``mcp_cache`` SQLite
  table with a ``health:{server_name}`` key pattern.
"""

from dataclasses import dataclass, field


@dataclass
class ServerCapability:
    """Describes a single MCP server's capabilities and metadata."""

    name: str                                   # Unique ID (matches adapter name)
    display_name: str                           # Human-readable
    description: str                            # What this server provides
    categories: list[str]                       # Domain tags
    cost_tier: str                              # "free" | "free_key" | "rate_limited"
    applies_to: str | list[str] = "*"           # Entity type slugs or "*"
    conditions: dict = field(default_factory=dict)  # Same pattern as _ADAPTERS
    provides: list[str] = field(default_factory=list)  # Capability tags
    priority: int = 20                          # Lower = higher precedence
    env_key: str | None = None                  # Env var for API key (if any)
    rate_limit_rpm: int = 0                     # Requests per minute (0 = unlimited)
    enrichment_capable: bool = True             # Has parser in enrichment pipeline


# ── Valid category values ────────────────────────────────────────

CATEGORIES = {
    "financial",
    "regulatory",
    "design",
    "macro",
    "news",
    "general",
    "search",
    "academic",
    "museum",
}

# ── Valid cost tier values ───────────────────────────────────────

COST_TIERS = {"free", "free_key", "rate_limited"}


# ── The Catalogue ────────────────────────────────────────────────

SERVER_CATALOGUE: dict[str, ServerCapability] = {
    # ── Direct API wrappers (existing in mcp_client.py) ──────────
    "hackernews": ServerCapability(
        name="hackernews",
        display_name="Hacker News",
        description="Tech community mentions and discussion via Algolia",
        categories=["news", "general"],
        cost_tier="free",
        applies_to="*",
        provides=["community_mentions", "tech_sentiment"],
        priority=20,
    ),
    "news": ServerCapability(
        name="news",
        display_name="DuckDuckGo News",
        description="Recent news articles via DuckDuckGo",
        categories=["news"],
        cost_tier="free",
        applies_to="*",
        provides=["recent_news", "media_coverage"],
        priority=20,
    ),
    "wikipedia": ServerCapability(
        name="wikipedia",
        display_name="Wikipedia",
        description="Wikipedia article summaries and search",
        categories=["general"],
        cost_tier="free",
        applies_to="*",
        provides=["background_info", "entity_description"],
        priority=15,
    ),
    "domain_rank": ServerCapability(
        name="domain_rank",
        display_name="Cloudflare Radar",
        description="Domain popularity ranking",
        categories=["general"],
        cost_tier="free",
        applies_to="*",
        conditions={"has_url": True},
        provides=["domain_ranking", "web_traffic"],
        priority=10,
    ),
    "patents": ServerCapability(
        name="patents",
        display_name="USPTO PatentsView",
        description="Patent search by assignee organisation",
        categories=["regulatory"],
        cost_tier="free",
        applies_to="*",
        provides=["patent_portfolio", "innovation_data"],
        priority=15,
    ),
    "sec_edgar": ServerCapability(
        name="sec_edgar",
        display_name="SEC EDGAR",
        description="US public company filings (10-K, 10-Q, 8-K)",
        categories=["financial", "regulatory"],
        cost_tier="free",
        applies_to="company",
        conditions={"country": "US"},
        provides=["filings", "financial_data", "sec_cik"],
        priority=5,
    ),
    "companies_house": ServerCapability(
        name="companies_house",
        display_name="UK Companies House",
        description="UK company register — status, SIC codes, creation date",
        categories=["financial", "regulatory"],
        cost_tier="free_key",
        applies_to="company",
        conditions={"country": "UK"},
        provides=["company_registration", "sic_codes", "company_status"],
        priority=5,
        env_key="COMPANIES_HOUSE_API_KEY",
    ),

    # ── New enrichment-capable servers ────────────────────────────
    "wayback_machine": ServerCapability(
        name="wayback_machine",
        display_name="Wayback Machine",
        description="Internet Archive — historical website snapshots and domain age",
        categories=["general"],
        cost_tier="free",
        applies_to="*",
        conditions={"has_url": True},
        provides=["website_history", "historical_snapshots", "domain_age"],
        priority=15,
    ),
    "fca_register": ServerCapability(
        name="fca_register",
        display_name="FCA Register",
        description="UK Financial Conduct Authority — authorised firms and permissions",
        categories=["regulatory", "financial"],
        cost_tier="free",
        applies_to="company",
        conditions={"country": "UK"},
        provides=["fca_authorisation", "regulatory_status", "fca_permissions"],
        priority=5,
    ),
    "gleif": ServerCapability(
        name="gleif",
        display_name="GLEIF",
        description="Global Legal Entity Identifier Foundation — LEI lookup",
        categories=["financial", "regulatory"],
        cost_tier="free",
        applies_to="company",
        provides=["lei_code", "legal_entity_data", "parent_company"],
        priority=10,
        rate_limit_rpm=60,
    ),
    "cooper_hewitt": ServerCapability(
        name="cooper_hewitt",
        display_name="Cooper Hewitt Museum",
        description="Smithsonian Design Museum — 215K+ design objects",
        categories=["design", "museum"],
        cost_tier="free_key",
        applies_to=["product", "design"],
        provides=["design_objects", "design_history", "design_inspiration"],
        priority=25,
        env_key="COOPER_HEWITT_API_KEY",
    ),

    # ── Macro-context servers (catalogue-only, no entity attributes) ─
    "bank_of_england": ServerCapability(
        name="bank_of_england",
        display_name="Bank of England",
        description="UK monetary policy rates, gilt yields, inflation, mortgage rates",
        categories=["macro", "financial"],
        cost_tier="free",
        applies_to="*",
        conditions={"country": "UK"},
        provides=["interest_rates", "inflation", "monetary_policy"],
        priority=15,
        enrichment_capable=False,
    ),
    "ecb": ServerCapability(
        name="ecb",
        display_name="European Central Bank",
        description="ECB statistical data — exchange rates, interest rates, HICP",
        categories=["macro", "financial"],
        cost_tier="free",
        applies_to="*",
        provides=["exchange_rates", "ecb_rates", "inflation"],
        priority=15,
        enrichment_capable=False,
    ),
    "eurostat": ServerCapability(
        name="eurostat",
        display_name="Eurostat",
        description="EU-wide statistics — GDP, inflation, unemployment, trade",
        categories=["macro"],
        cost_tier="free",
        applies_to="*",
        provides=["gdp", "unemployment", "demographics", "trade_statistics"],
        priority=15,
        enrichment_capable=False,
    ),
    "oecd": ServerCapability(
        name="oecd",
        display_name="OECD",
        description="Cross-country economic indicators, insurance data, productivity",
        categories=["macro", "financial"],
        cost_tier="free",
        applies_to="*",
        provides=["insurance_indicators", "productivity", "macro_indicators"],
        priority=15,
        enrichment_capable=False,
    ),
    "dbnomics": ServerCapability(
        name="dbnomics",
        display_name="DBnomics",
        description="Aggregator of 80+ statistical providers (Eurostat, ECB, OECD, IMF)",
        categories=["macro"],
        cost_tier="free",
        applies_to="*",
        provides=["macro_aggregator", "cross_provider_search"],
        priority=25,
        enrichment_capable=False,
    ),
}


# ── Helpers ──────────────────────────────────────────────────────


def get_enrichment_servers():
    """Return only servers that have enrichment pipeline integration."""
    return {k: v for k, v in SERVER_CATALOGUE.items() if v.enrichment_capable}


def get_servers_by_category(category):
    """Return servers matching a given category."""
    return {k: v for k, v in SERVER_CATALOGUE.items() if category in v.categories}


def get_server(name):
    """Look up a single server by name."""
    return SERVER_CATALOGUE.get(name)
