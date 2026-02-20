"""Document-specific extractors for structured data from evidence.

Available extractors:
- product_page: Extract company/product info from marketing pages
- pricing_page: Extract pricing tiers, plans, and features
- changelog: Extract version history, release frequency, and maturity from changelogs
- press_release: Extract announcements, quotes, and implications from press releases
- funding_round: Extract funding round details from investment announcements
- generic: Generic HTML/text content extractor (fallback)

Each extractor provides:
- A specialized LLM prompt for its document type
- A structured output schema matching expected data
- A classification function to detect document type from content
"""
