# Feature Roadmap — Research Taxonomy Library

Updated 2026-02-20. Based on deep research of 50+ SaaS tools across 12 categories, plus 2026 competitive intelligence and AI landscape analysis.

---

## Current Feature Inventory (90+ features)

| Area | Count | Key Features |
|------|-------|-------------|
| Companies | 16 | List, detail, edit, star, relationship tracking, re-research, notes, events, versions, trash, duplicates, comparison, bulk select + bulk actions, quick-add API, pricing capture, social/relationship status |
| Taxonomy | 9 | Tree view, graph view (Cytoscape), AI review, apply changes, quality dashboard, change history, category color coding, scope notes + inclusion/exclusion criteria, drag-to-reorder |
| Market Map | 5 | Drag-drop kanban, geographic map (Leaflet), company comparison, auto-layout (Cytoscape compound nodes), PNG export |
| Research | 7 | AI market reports, deep dive (scoped LLM research), templates library, saved results, markdown/PDF export, AI diagrams (Mermaid), research dimensions (EAV) |
| Canvas | 8 | Excalidraw 0.18.0 workspace (replaced Fabric.js), drag-drop companies (bound-text cards), native drawing tools, AI diagram generation (5 templates: market landscape, tech stack, value chain, competitive, customer journey), auto-save, SVG/PNG/PDF export |
| Discovery | 3 | Feature landscape analysis, gap analysis (vs uploaded context), per-project feature toggle |
| Processing | 5 | AI discovery, URL triage, batch pipeline, recent batches, retry |
| Analytics | 3 | Dashboard charts, project statistics, configurable category matrix (2-axis: category/funding/geography/business_model/employees) |
| Navigation | 3 | Linked record navigation, breadcrumbs, category detail view |
| Filtering | 3 | Active filter chips, saved views, keyboard shortcut star (S) |
| Tags | 2 | Tag manager (rename/merge/delete), tag filtering |
| Export/Import | 6 | JSON, Markdown, CSV, Excel, PDF, CSV import |
| Sharing | 2 | Share links, read-only shared view |
| Notifications | 3 | In-app SSE panel, Slack integration, activity log |
| AI Chat | 2 | Data Q&A widget, find similar companies |
| Presentation | 2 | Full-screen slide mode from maps/reports, keyboard navigation + progress bar |
| UX | 4 | Keyboard shortcuts, shortcuts overlay, product tour, company count badges on tabs |
| Theme | 1 | Dark/light toggle with Material Symbols icons |
| Desktop | 5 | Native window, macOS menu, notifications, git sync, auto-backup |
| Security | 8 | CSRF (HMAC-SHA256), CSP (Flask-Talisman), SRI on CDN resources, API key Keychain storage, input validation, prompt injection hardening, host header validation, rate limiting |

---

## Competitive Landscape (Updated Feb 2026)

| Tool | Taxonomy | Discovery | AI Research | Map Viz | Enrichment | Canvas | Price |
|------|----------|-----------|-------------|---------|------------|--------|-------|
| CB Insights | Partial | Yes | No | **Best** | Partial | No | $50K+/yr |
| Crunchbase | No | **Best** | No | No | Partial | No | $5K+/yr |
| Tracxn | **Best** | Yes | No | Partial | Manual | No | $5K+/yr |
| PoolParty | **Best** | No | No | Partial | No | No | $50K+/yr |
| AlphaSense | No | No | **Best** (Generative Grid) | No | No | No | $20K+/yr |
| Perplexity | No | No | **Best** (Deep Research) | No | No | No | $200/yr |
| Clay | No | No | No | No | **Best** (150+ sources) | No | $1.8K+/yr |
| Notion | Partial | No | Yes (agents) | No | No | No | $96+/yr |
| Miro | No | No | No (Sidekicks) | No | No | **Best** | $96+/yr |
| Hebbia | No | No | Yes (FlashDocs) | No | No | No | Enterprise |
| **This App** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** (Excalidraw + AI Diagrams) | **Local/Free** |

**Key insight**: No single tool combines all six columns. Enterprise tools charge $5K-$50K+/year for partial coverage. This app is the only local-first, privacy-preserving tool that integrates the full research-to-deliverable pipeline. The competitive moat is *integration density* — every feature feeds every other feature.

### What Changed in 2026

| Trend | Impact | Our Response |
|-------|--------|-------------|
| Deep Research everywhere (Perplexity, ChatGPT, Gemini, AlphaSense) | Multi-pass, cross-verified research is table stakes | Multi-pass research mode with confidence scoring |
| MCP adoption (97M+ monthly SDK downloads) | Tools that expose data via MCP join the AI ecosystem; those that don't become silos | MCP server for taxonomy/company data |
| AI agents replace single-shot prompts | Orchestrated multi-agent workflows, not monolithic AI calls | Specialist agents (researcher, classifier, enricher, monitor) |
| Multimodal AI (PDFs, screenshots, charts) | Users expect to drop any document and extract structured data | PDF/image ingestion for company research |
| Local-first AI via Ollama | Privacy-conscious users want optional offline AI | Local embedding search + optional Ollama classification |
| 22% annual data decay (ZoomInfo stat) | Static databases lose credibility; freshness is differentiator | Data freshness dashboard + automated re-research |

---

## Highest-Impact Recommendations

### THE BIG 5 — Features That Transform the Product

These aren't incremental improvements. Each one changes what the product fundamentally *is*.

---

#### 1. MCP Server: Make the App Part of the AI Ecosystem
**Impact**: Existential | **Effort**: Medium | **Timeline**: Immediate

**Why this is #1**: MCP is now an industry standard (Anthropic, OpenAI, Google, Microsoft). Tools that expose data via MCP become part of every user's AI workflow. Tools that don't become information silos. This is the single most strategically important feature.

**What it does**: Expose your taxonomy, company data, research findings, and dimensions as an MCP server. Users can query your research database from Claude Code, ChatGPT, Cursor, or any MCP client.

**MCP Resources to expose**:
- `taxonomy://project/{id}/categories` — full taxonomy tree
- `companies://project/{id}/search?q=...` — company search
- `research://project/{id}/reports` — saved research results
- `dimensions://project/{id}/{dimension}` — dimension data

**MCP Tools to expose**:
- `add_company(url, category)` — add company from any AI tool
- `research_company(url)` — trigger research pipeline
- `classify_company(name, description)` — get category suggestion
- `get_market_overview(category)` — structured category summary

**Why it matters for you**: You're already using Claude Code daily. Imagine asking Claude "What companies in my healthtech taxonomy are doing claims automation?" and getting answers from your own research database without opening the app.

**Inspired by**: Tana MCP exposure, Clay Claygent MCP, Notion API, 10,000+ MCP servers in ecosystem

---

#### 2. Deep Research Mode: Multi-Pass Investigation with Confidence
**Impact**: Very High | **Effort**: Medium | **Timeline**: Phase 1

**Why this matters**: Perplexity Deep Research runs 20-50 queries per report. ChatGPT Deep Research takes 5-30 minutes with cross-verification. AlphaSense's Deep Research automates analyst workflows. Single-pass company research is no longer sufficient — users expect depth.

**What it does**:
- **Plan phase**: LLM generates a research plan (5-8 steps) before execution. User reviews and can modify.
- **Multi-pass execution**: Research runs in stages — initial scan, targeted deep dives on gaps, cross-verification of claims.
- **Progressive streaming**: Results stream to the UI as they arrive via SSE. User can cancel mid-research.
- **Confidence scoring**: Each fact gets a confidence level (verified from multiple sources, single source, inferred). Displayed as color-coded indicators.
- **Source diversity metric**: Shows how many distinct sources contributed to the research.

**Architecture**: Extends `core/researcher.py` with a `DeepResearcher` class that orchestrates multi-pass research. Uses existing SSE infrastructure from discovery.js for streaming.

**Inspired by**: Perplexity Deep Research (Opus 4.5, 200+ sources), ChatGPT Deep Research (o3, MCP integration), Google Gemini Deep Research (Interactions API), AlphaSense Deep Research

---

#### 3. Multimodal Document Ingestion: Drop a PDF, Get Structured Data
**Impact**: Very High | **Effort**: Medium | **Timeline**: Phase 1

**Why this matters**: Market researchers constantly encounter competitor pitch decks, analyst reports, industry PDFs, and market map screenshots. Currently, extracting data from these is entirely manual. Claude, GPT-4o, and Gemini 3 all handle PDFs/images natively now.

**What it does**:
- Drop a PDF/image onto the Canvas or into the Research tab
- AI extracts structured company data: names, descriptions, funding, categories
- Preview extracted entities before committing to database
- For market map screenshots: identify companies and their category placements
- For pitch decks/annual reports: extract competitive landscape, pricing, product features

**Use cases**:
- "Here's a CB Insights market map screenshot — import all the companies"
- "Here's a competitor's pitch deck — extract their product positioning and pricing"
- "Here's an analyst report — pull out all the companies mentioned with their descriptions"

**Inspired by**: Mistral OCR 3, Claude vision capabilities, Heptabase PDF-to-canvas, NotebookLM source ingestion

---

#### 4. Canvas AI Agent: Select Companies, Ask Questions
**Impact**: Very High | **Effort**: Medium | **Timeline**: Phase 2

**Why this matters**: Miro's Sidekicks (October 2025) proved that AI-on-canvas is the future of visual analysis. But Miro's canvas is visual-only — the AI doesn't understand the data behind the sticky notes. Your canvas is *data-backed*. When a user selects companies on your Excalidraw canvas, the AI knows their full research profiles, categories, dimensions, and relationships. The Excalidraw rewrite (Session 6-7) provides a solid foundation — native drawing tools, proper text rendering, and a React-based API for programmatic element creation.

**What it does**:
- Select 2+ companies on canvas → AI action menu appears
- "Compare these companies" → generates comparison table, pins to canvas
- "What are the competitive dynamics here?" → generates analysis card
- "Summarize this cluster" → creates a category-level summary
- "Find companies similar to these" → discovers and suggests additions
- "Generate a report on this selection" → creates exportable market report

**Architecture**: Extends canvas.js with a floating AI action bar. Selected Excalidraw elements with `customData.companyId` feed into targeted prompts via `core/researcher.py`. Results render as new Excalidraw elements via `excalidrawAPI.updateScene()`.

**Inspired by**: Miro Sidekicks (AI agents on canvas), Miro Flows (multi-step AI workflows), FigJam AI

---

#### 5. Semantic Search: Find Companies by Meaning, Not Keywords
**Impact**: Very High | **Effort**: High | **Timeline**: Phase 2

**Why this matters**: AlphaSense's semantic search is their killer feature ($500M+ ARR). Your app currently uses fuzzy string matching (MiniSearch). Semantic search catches companies described differently but doing the same thing — "AI-powered claims processing" finds "automated adjudication platform."

**What it does**:
- Generate text embeddings for all company descriptions, research notes, and dimension values
- Run entirely locally via Ollama + nomic-embed-text on Apple Silicon (no cloud dependency)
- Natural language queries: "companies reducing insurance claims processing time with AI"
- "Find similar to [company]" uses embedding cosine similarity instead of tag matching
- Results ranked by semantic relevance with explanations

**Architecture**: sqlite-vss virtual table extension for SQLite. Background embedding job runs on new/updated companies. `core/search.py` module with `semantic_search()` and `find_similar()` functions.

**Why local matters**: Insurance/healthtech researchers handle sensitive competitive intelligence. Local embeddings mean proprietary research never leaves the device.

**Inspired by**: AlphaSense semantic search, Perplexity natural language search, Consensus claim-level search, Ollama + nomic-embed-text running at 28-35 tok/s on M3

---

## Full Feature Roadmap

### Phase 1: Next Sprint (Immediate)

| # | Feature | Impact | Effort | Description |
|---|---------|--------|--------|-------------|
| 1 | **MCP Server** | Existential | Medium | Expose taxonomy/company/research data as MCP server |
| 2 | **Deep Research Mode** | Very High | Medium | Multi-pass research with plan display, streaming, confidence scores |
| 3 | **Multimodal Ingestion** | Very High | Medium | Drop PDF/image, extract structured company data via vision AI |
| 4 | **Data Freshness Dashboard** | High | Low | Staleness indicators per company/category, prioritized re-research queue |
| 5 | **Company Scoring System** | High | Low | Composite score: completeness + relevance + funding momentum + category fit |
| 6 | **Inline LLM Field Suggestions** | High | Low | "AI suggest" button per field in edit mode, accept/edit/dismiss inline |
| QW | Column visibility toggle | Medium | Very Low | Show/hide columns in company table |
| QW | Export filtered results only | Medium | Very Low | Export respects current filter state |
| QW | Inline editing (double-click cell) | Medium | Low | Edit company fields directly in table view |
| QW | Confidence threshold slider | Medium | Very Low | Filter companies by AI confidence score |
| QW | URL deduplication on paste | Low | Very Low | Detect and warn about duplicate URLs during add |
| QW | Copy company data as JSON/Markdown | Low | Very Low | Right-click copy for sharing |

### Phase 2: Near-Term (1-2 months)

| # | Feature | Impact | Effort | Description |
|---|---------|--------|--------|-------------|
| 7 | **Canvas AI Agent** | Very High | Medium | Select companies on canvas, get AI comparisons/analyses/reports |
| 8 | **Semantic Search** | Very High | High | Local embedding search via Ollama + sqlite-vss |
| 9 | **Category Playbook Pages** | High | Medium | Wiki-style battlecard per category: definition, stats, trends, risks, pinned companies |
| 10 | **Ad-Hoc Dimension Queries** | High | Medium | Type a question, get it answered across all companies in a category (Generative Grid-style) |
| 11 | **Auto-Generated Comparison Tables** | High | Medium | AI generates structured comparison across all companies in a category |
| 12 | **Thesis Builder** | High | Medium | Investment memo generator: market overview, competitive dynamics, white space, risks, winners |
| 13 | **Funding Round Timeline** | Medium | Medium | Cross-company swimlane timeline from company_events table |
| QW | Search within detail panel | Medium | Low | Cmd+F within side panel |
| QW | Batch progress notifications (non-desktop) | Medium | Low | Browser notification API for batch completions |

### Phase 3: Medium-Term (2-4 months)

| # | Feature | Impact | Effort | Description |
|---|---------|--------|--------|-------------|
| 14 | **Watchlist + Change Monitoring** | Very High | High | Mark companies as watched, periodic LLM web checks, alert on funding/pivots/shutdowns |
| 15 | **Cross-Project Portfolio Dashboard** | High | Medium | Overview across all projects: completion metrics, coverage gaps, company overlap detection |
| 16 | **Source Provenance Chain** | High | Medium | Per-field: which URL, which LLM, when, what prompt. Click any value for audit trail |
| 17 | **Snapshot & Diff** | High | Medium | Named point-in-time snapshots, structured diff: companies added/removed, category/funding changes |
| 18 | **Cohort Analysis View** | Medium | Medium | Select cohort by category/tag/stage, see aggregate stats: distributions, heat maps, common tags |
| 19 | **Multi-Axis Scatter Plot Builder** | Medium | Medium | Pick X/Y/size/color from company fields, interactive bubble chart |
| 20 | **AI Taxonomy Gap Finder** | Medium | Medium | AI analyzes company data to find missing categories, straddling companies, heterogeneous groups |
| 21 | **Research Session Branching** | Medium | Medium | Follow-up question chains forming a navigable research tree |

### Phase 4: Longer-Term (4-6 months)

| # | Feature | Impact | Effort | Description |
|---|---------|--------|--------|-------------|
| 22 | **MCP Client for Enrichment** | High | Medium | Consume external MCP servers for modular enrichment (Crunchbase, SEC filings, regulatory) |
| 23 | **Local LLM Fallback (Ollama)** | High | Medium | Optional offline AI for classification, tagging, basic enrichment via Ollama |
| 24 | **Research-to-Presentation Pipeline** | High | Medium | Generate branded slide decks from taxonomy research (Hebbia FlashDocs-style) |
| 25 | **Relationship Web Visualization** | Medium | Medium | Network graph: partnerships, acquisitions, shared investors. AI extracts from research |
| 26 | **Company Lifecycle State Machine** | Medium | Medium | Configurable states (Active/Acquired/Pivoted), transition logging, visual timeline |
| 27 | **Market Sizing Calculator** | Medium | Medium | Per-category TAM/SAM/SOM from aggregated funding + employee + web-searched market data |
| 28 | **Evidence Notebook** | Medium | Medium | Cross-company evidence cards with bidirectional linking, confidence levels, report citations |
| 29 | **Sankey Diagram Builder** | Low | Medium | Interactive flow diagrams: Funding Stage -> Category, Geography -> Business Model |
| 30 | **Taxonomy SKOS/JSON-LD Export** | Low | Low | Standard interchange format for enterprise taxonomy tools |

### Deferred / Revisit Later

| Feature | Reason |
|---------|--------|
| Multi-User Collaboration | Very High complexity, architectural change. Revisit when user base justifies it |
| Automation Recipes | High complexity. Most value captured by simpler agent workflows |
| Customer Journey Mapping | Niche use case. Canvas + AI agent covers most of this |
| Source-Specific Importers | Low ROI vs improving generic CSV import with AI column mapping |
| Company Similarity Heatmap | Semantic search + find-similar covers this use case more naturally |
| Taxonomy Diff & Merge | Cross-Project Dashboard is a simpler first step |
| Brand Kit | Low priority for solo researcher workflow |

---

## Prioritization Framework

| Factor | Weight | Description |
|--------|--------|-------------|
| **Ecosystem Integration** | 30% | Does this make the app part of the AI tool ecosystem (MCP, agents, multimodal)? |
| **Research Workflow Impact** | 30% | How much does this reduce time from "I have a question" to "I have an answer"? |
| **Competitive Differentiation** | 20% | Does this create capabilities no competitor offers at any price? |
| **Implementation Leverage** | 20% | Does this unlock future features or compound existing ones? |

### Why This Order

**Phase 1 is about platform survival**: MCP integration is existential — without it, the app becomes an island as the AI ecosystem standardizes on MCP. Deep Research and Multimodal Ingestion match what Perplexity/ChatGPT/Gemini now offer. Data Freshness and Scoring make existing data more valuable without new features.

**Phase 2 is about unique differentiation**: Canvas AI Agent and Semantic Search create capabilities no competitor offers — data-backed visual AI analysis and meaning-based search across your private research. Playbook Pages and Thesis Builder transform the app from a research tool into a deliverable-generation engine.

**Phase 3 is about living intelligence**: Watchlist Monitoring turns the app from a point-in-time snapshot into a living intelligence system. Snapshot & Diff enables "what changed" reporting. Provenance makes every claim auditable.

**Phase 4 is about ecosystem depth**: MCP Client enables modular enrichment from any source. Local LLM preserves the privacy story. Presentation Pipeline completes the research-to-deliverable workflow.

---

## Sources (2026 Research)

### AI Research Tools
- Perplexity Deep Research — Opus 4.5, 20-50 queries/report, 200+ sources, literature reviews in <4 min
- ChatGPT Deep Research — o3, 5-30 min/query, MCP server integration, trusted site filtering
- Google Gemini Deep Research — Gemini 3, Interactions API, Workspace content integration
- Google NotebookLM — Gemini 3, Mind Maps, Data Tables, Web Research Agent, Video Overviews
- AlphaSense — $500M+ ARR, Generative Grid, Deep Research agent, Channel Checks (350+ tickers)
- Hebbia — $130M Series B at $700M valuation, acquired FlashDocs for slide generation
- Brightwave — Autonomous research agent fleets, $120B+ AUM customer base
- Elicit — 138M+ papers, 545K clinical trials, structured extraction, systematic review features

### Competitive Intelligence
- Crayon — Real-time monitoring, pricing intelligence, auto-evolving battlecards
- Klue — Acquired DoubleCheck for win-loss data, Beautiful Battlecards
- Contify — AI/NLP across 1M+ public sources, per-competitor dashboards
- CB Insights — AI-driven trend prediction, startup ranking (AI 100)
- Tracxn — 4.5M+ companies, Soonicorn tracking, sector newsletters
- PitchBook — 3M companies, 1.6M deals across VC/PE/M&A
- Dealroom — API-first, European/global ecosystem, market sizing tools

### Knowledge & Taxonomy
- PoolParty 2025 — AI Taxonomy Advisor (LLM-powered), multi-project inference, SPARQL expansion
- Semaphore — 3.1% market share (up from 1.6%), auto-classification
- Notion 3.2 — Autonomous AI Agents (20 min of work), multi-model support (GPT-5.2/Claude 4.5/Gemini 3)
- Tana — MCP exposure for AI tools, Smart Nodes, context tags
- Obsidian — Canvas mode, Copilot plugin, local-first + graph view

### Enrichment
- Clay — 150+ providers, Sculptor AI, Claygent MCP integration, intent signals
- Apollo — 275M+ contacts, combined enrichment + sales engagement
- ZoomInfo — 500M+ contacts, AI enrichment rules, real-time CRM sync
- Key stat: 22% annual accuracy decay across all major data providers

### Canvas & Visualization
- Miro Canvas 25 — Sidekicks (AI agents on canvas), Flows (multi-step AI), MCP integration, Diagrams, Slides
- Flourish — 50+ templates, animated slideshows
- Datawrapper — Publication-ready, enhanced interactivity

### Emerging Technology
- MCP — 97M+ monthly SDK downloads, November 2025 spec (auth, async, governance), multi-agent collaboration
- Ollama — Mature on Apple Silicon, tool calling, MCP support, 28-35 tok/s on M3 Pro/Max
- Local embeddings — nomic-embed-text, mxbai-embed-large via Ollama (fully offline)
- Agentic AI — 40% of enterprise apps to embed agents by end of 2026 (Gartner), $7.8B -> $52B by 2030
- Hybrid research — Stanford/CMU: human-AI workflows deliver 68.7% better results than fully autonomous
- Claude for Chrome / Cowork — Browser agents for research automation
- Multimodal — Claude/GPT-4o/Gemini 3 handle PDFs/images natively; Mistral OCR 3 for document comprehension

---

## Appendix A: Feature Implementation Audit (Feb 2026)

Full codebase audit comparing roadmap items to actual implementation. Reference this when planning sprints.

### Previously Roadmapped Features — Now Built

| Feature | Where in Code | Notes |
|---------|--------------|-------|
| Category Color Coding | `taxonomy.js` (`updateCategoryColor()`), schema `color` column | Color pickers + dots in table/map/tree |
| Bulk Select + Bulk Actions | `companies.js` (`bulkSelection` set, floating action bar) | Checkbox column, assign/tag/relationship/delete |
| Linked Record Navigation | `core.js` (`navHistory` stack), breadcrumb bar | Category detail view, clickable entity links |
| Deep Dive Research | `web/blueprints/research.py`, `research.js` | Scoped LLM research with web search |
| Research Canvas | `canvas.js` (~300 lines), Excalidraw 0.18.0 workspace | Replaced Fabric.js. Native drawing tools, drag-drop companies (bound-text cards), auto-save, SVG/PNG/PDF export |
| Auto-Build Market Map | `taxonomy.js` (`renderTaxonomyGraph()`) | Cytoscape compound node layout |
| E2E Test Suite | `e2e/` (132 Playwright tests across 22+ spec files) | Auto-starts Flask on port 5099 |
| Taxonomy Scope Notes (N1) | `taxonomy.js` lines 68-82, schema `scope_note`/`inclusion_criteria`/`exclusion_criteria` | Toggle-able metadata panel |
| Research Question Library (N4) | `research_templates` table, `/api/research/templates` API | Scope types: project/category/company |
| Presentation Mode (#14) | `presentation.js`, `presentation.css` | Full-screen slides, keyboard nav, progress bar |
| Keyboard Shortcut for Star (QW3) | `keyboard.js` line 26: `if (e.key === 's')` | Calls `toggleStar()` |
| Company Count Badges (QW7) | Tab labels show counts: "Companies (42)" | In `core.js` tab rendering |
| Drag-to-Reorder Categories (QW9) | `core.js` Sortable.js: `.sortable-list` | With ghost class |
| Export Market Map as SVG (QW14) | `canvas.js` exports PNG/SVG/PDF | Plus presentation save as PDF |

### Features Built Since Roadmap (Not Previously Listed)

| Feature | Where in Code | Notes |
|---------|--------------|-------|
| Discovery Engine | `web/blueprints/discovery.py`, `discovery.js` (15KB) | Feature landscape + gap analysis vs uploaded context |
| Research Dimensions | `dimensions.py`, `research_dimensions` + `company_dimensions` tables | EAV pattern, AI explore/propose/accept/populate flow |
| AI Diagram Generation | `diagram.js` + `canvas.py` | LLM-generated Excalidraw diagrams with 5 templates (market landscape, tech stack, value chain, competitive, customer journey). Claude/Gemini structured output → Excalidraw elements. Replaced earlier Mermaid approach. |
| Pricing Capture | 9 columns on `companies` table (schema lines 77-86) | AI research auto-extracts; bulk fill missing in ai.py |
| Company Events | `company_events` table | event_type: funding_round, acquired, shut_down, launch, pivot, partnership |
| Settings Tab | `settings.js`, `app-settings.js` (11KB) | AI backend config, model selector, fix sections |
| Social/Relationship Tracking | `relationship_status` field, `social.py` repo | watching, to_reach_out, in_conversation, met, partner, not_relevant |
| Company Versions | `company_versions` table | Snapshot history for undo/restore on re-research |
| Category Matrix (2-axis) | `charts.js` (`renderCategoryMatrix()`) | Configurable rows/columns: category/funding/geography/business_model/employees |
| Security Hardening | `web/app.py`, `config.py`, all blueprints | CSRF HMAC, CSP, SRI, Keychain, input validation, prompt injection defense |

### Not Yet Built — Confirmed by Audit

| Feature | Status | Codebase Evidence |
|---------|--------|-------------------|
| Cross-Project Portfolio Dashboard | Not built | No cross-project aggregation endpoints |
| AI Research Plan Display + Streaming | Partial — polling exists, no plan display | SSE for batch/discovery; no plan preview UI |
| Waterfall Company Enrichment | Partial — single-path only | `enrichment_status` exists; no multi-source fallback |
| Auto-Generated Comparison Tables | Not built | Manual comparison (max 4) in maps.js only |
| Gallery View | Not built | No gallery card layout |
| Timeline View | Not built | No founding year/funding timeline |
| Smart Alerts & Change Detection | Not built | Notification system exists but no monitoring |
| Brand Kit | Not built | No logo upload or brand colors |
| Company Scoring System | Not built | `completeness` exists; no composite scoring |
| Automation Recipes | Not built | No trigger-action system |
| Multi-User Collaboration | Not built | Single-user only |
| AI-Powered Taxonomy Suggestions | Not built | No auto-clustering or category suggestions |
| Knowledge Graph (full) | Partial | Taxonomy graph exists; no inter-company relationship graph |
| Competitive Intelligence Feed | Not built | Activity log exists; no news/signal feed |
| Data Freshness Dashboard (N2) | Partial | `last_verified_at` field exists; no dashboard or staleness indicators |
| Inline LLM Field Suggestions (N3) | Not built | No per-field AI suggest buttons |
| Source-Specific Importers (N5) | Not built | Generic CSV only |
| Taxonomy SKOS/JSON-LD Export (N6) | Not built | JSON export only |
| Category Playbook Pages (N7) | Not built | No wiki-style pages |
| Funding Round Timeline (N8) | Not built | `company_events` table ready; no visualization |
| Source Provenance Chain (N9) | Not built | No per-field provenance tracking |
| Company Lifecycle State Machine (N10) | Partial | `status` field + `company_events` exist; no state machine UI |
| Market Sizing Calculator (N11) | Not built | No TAM/SAM/SOM calculator |
| AI Taxonomy Gap Finder (N12) | Partial | Gap analysis exists in discovery; not for taxonomy structure |
| Evidence Notebook (N13) | Not built | Company notes exist; no cross-company evidence cards |
| Cohort Analysis (N14) | Not built | No aggregate stats view |
| Research Session Branching (N15) | Not built | No follow-up chains |
| Snapshot & Diff (N16) | Not built | `company_versions` exists; no project-level snapshots |
| Relationship Web (N17) | Not built | No inter-company network graph |
| Thesis Builder (N18) | Not built | No investment memo generation |
| Multi-Axis Scatter Plot (N19) | Not built | Fixed category matrix only |
| Sankey Diagram (N20) | Not built | No Sankey flow visualization |
| Taxonomy Diff & Merge (N21) | Not built | No cross-project reconciliation |
| AI Field Extraction (N22) | Not built | Full re-research only |
| Semantic Search (N23) | Not built | Fuzzy string matching (MiniSearch) only |
| Watchlist + Monitoring (N24) | Not built | No watchlist or periodic checks |
| Company Similarity Heatmap (N25) | Not built | No NxN similarity scoring |

### Quick Wins Status

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| 1 | Bulk select + bulk actions | **Built** | `bulkSelection` set, floating action bar |
| 2 | Column visibility toggle | Not built | No column show/hide UI |
| 3 | Keyboard shortcut for star | **Built** | `keyboard.js` line 26 |
| 4 | Category color coding | **Built** | Color pickers, `updateCategoryColor()` |
| 5 | Export filtered results only | Partial | Export works but doesn't respect filter state |
| 6 | Inline editing (double-click cell) | Not built | No contenteditable or inline forms |
| 7 | Company count badges on tabs | **Built** | Tab labels show counts |
| 8 | Last-viewed breadcrumb | **Built** | `navHistory` stack |
| 9 | Drag-to-reorder categories | **Built** | Sortable.js |
| 10 | Confidence threshold slider | Not built | No slider filter |
| 11 | URL deduplication on paste | Not built | No dedup on input |
| 12 | Batch progress notifications | Partial | SSE exists; browser notification depends on permission |
| 13 | Search within detail panel | Not built | No side panel search |
| 14 | Export market map as SVG | **Built** | Canvas exports PNG/SVG/PDF |
| 15 | Copy company data as JSON/MD | Not built | No copy-to-clipboard |

---

## Appendix B: Competitive Intelligence Detail (Feb 2026)

### AI Research — State of the Art

**Perplexity Deep Research** (Feb 2026): Now runs on Opus 4.5 for Pro/Max. Performs 20-50 targeted queries per report drawing from 200+ sources. Literature reviews yield 100+ cited studies in <4 minutes. All advanced features consolidated under a single "+" menu. Key differentiator: multi-pass querying with automatic cross-verification and uncertainty notes.

**ChatGPT Deep Research** (Feb 2026): Powered by o3, takes 5-30 minutes per query. Can analyze uploaded files plus web sources. Connects to any MCP server. Can restrict web searches to trusted sites. Plus: 25 queries/month; Pro: 250.

**Google Gemini Deep Research**: Uses Gemini 3 Pro with multi-step reinforcement learning for search. Integrates with Google Workspace (emails, chats). Available via Interactions API for developer embedding. 46.4% on Humanity's Last Exam.

**AlphaSense**: Surpassed $500M ARR. Generative Grid (ask multiple questions across document sets in table format). Deep Research agent. Channel Checks (ground-level market intelligence via expert conversations, 350+ tickers). Financial Data integration merging quantitative + qualitative.

**Hebbia**: $130M Series B at $700M valuation. Acquired FlashDocs for slide deck generation. Serves 1/3 of largest asset managers. M&A deal analysis, due diligence, earnings call summarization.

**NotebookLM**: Gemini 3, interactive Mind Maps, Data Tables (exportable to Sheets), Video Overviews, Slide Decks, Web Research Agent.

### Competitive Intelligence Platforms

**Crayon**: Real-time web monitoring, pricing intelligence, auto-evolving sales battlecards. 2025 State of CI report: sellers face direct competition in 68% of deals but rate preparedness at only 3.8/10.

**Klue**: Acquired DoubleCheck for win-loss data and interview recordings.

**Contify**: AI/NLP across 1M+ public sources (websites, news, press releases, regulatory docs). Dedicated dashboards per competitor/customer/segment. Integrates with Slack, Teams, Salesforce, PowerBI.

**New entrants**: Signum.AI (signal monitoring), Veridion (continuously updated company APIs), RivalSense (affordable CI, 80+ sources), Competitors App (unified monitoring).

### Key Market Stats

- Enterprise CI tools: $20K-$100K+/year
- Data provider accuracy decay: 22% annually (ZoomInfo)
- MCP adoption: 97M+ monthly SDK downloads
- AI agent market: $7.8B (2025) -> $52B by 2030
- Hybrid human-AI workflows: 68.7% better results than fully autonomous (Stanford/CMU)
- Agentic AI: Gartner predicts 40% of enterprise apps to embed agents by end of 2026

### Pricing Tiers (What Competitors Charge)

| Tool | Annual Price | What You Get |
|------|-------------|--------------|
| CB Insights | $50,000+ | Market maps, trend prediction, startup ranking |
| AlphaSense | $20,000+ | Semantic search, document annotation, Generative Grid |
| Tracxn | $5,000+ | Company database, sector newsletters, deal flow |
| PitchBook | $20,000+ | 3M companies, deal data, investor profiles |
| Crunchbase Pro | $5,000+ | Company search, saved lists, alerts |
| Clay | $1,800+/yr | 150+ enrichment providers, Claygent AI |
| PoolParty | $50,000+ | Enterprise taxonomy management, SKOS |
| Perplexity Pro | $200/yr | Deep Research, model council, 600 queries/day |
| **This App** | **$0 (local)** | Taxonomy + Research + Map + Discovery + Canvas + Export |

**The gap**: No tool under $5,000/year combines taxonomy management, AI research, market visualization, and company enrichment. This app fills that gap as a local-first, free desktop tool.
