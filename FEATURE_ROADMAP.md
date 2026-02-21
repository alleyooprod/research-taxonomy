# Research Workbench — Feature Roadmap

> **Created:** 2026-02-21 (Session 29)
> **Replaces:** Previous feature roadmap (pre-workbench era, Feb 2026)
> **Basis:** Competitive landscape analysis of 30+ tools across 7 categories, full implementation plan review (Phases 1-7 + MCP + audit, all complete, 1700 tests), vision doc, original brainstorm transcript.
> **Guiding Principle:** Every feature must strengthen data quality. No report or insight should ever be generated from hallucinated or unverified data. The workbench's edge is *trustworthy depth*, not speed or volume.

---

## Current State Summary

**What's built (1700 tests, 29 sessions):**
- Flexible entity schema per project with AI-guided setup
- Evidence capture engine (8 gallery scrapers, app stores, headless Playwright, manual upload, drag-drop, clipboard paste)
- AI extraction pipeline with human review workflow and feature standardisation
- 6 analysis lenses (competitive, product, design, temporal, signals + framework) with data-driven activation
- Report generation (5 templates + AI custom + 4 export formats incl. PDF and Canvas composition)
- Monitoring (8 check types, change feed, severity scoring, re-capture triggers)
- Intelligence (insights engine, hypotheses, playbooks, cross-project intelligence)
- MCP integration (11 enrichment adapters, smart routing, health tracking, 16 server catalogue entries)
- Evidence provenance (8 endpoints, full chain tracing: attribute → extraction → evidence → URL)
- LLM cost tracking with project budgets
- esbuild bundling, loading skeletons, AbortController tab switching

**What competitors do that we don't (yet):**
- Multimodal screenshot extraction (Crayon, AlphaSense use vision AI on captured images)
- Natural language data querying ("ask your data" — every modern BI tool, 2025-2026 standard)
- Agentic autonomous research workflows (emerging in Crayon, Competely, RivalSense)
- Interactive/live HTML reports with embedded charts (Flourish, Datawrapper, Power BI)
- Scheduled monitoring with email-style digests (Crayon, Klue, Contify standard)
- Advanced market positioning visualisations (Magic Quadrant, radar/spider, bubble charts)
- Stakeholder read-only sharing (Dovetail, Klue, every SaaS CI tool)

**What nobody does that we should:**
- Evidence-grounded reports where every claim is provenance-verified before generation
- Data quality gates that prevent report generation from insufficiently validated data
- Source hierarchy scoring (regulatory doc > official website > marketing page > AI inference)
- Research completeness guidance tied to methodology playbooks
- Domain-specific playbook templates with pre-configured schemas, source types, and quality thresholds

---

## Design Principles for the Roadmap

1. **Trust over speed.** Never generate a report from unreviewed AI extractions. Never surface an insight without citing evidence. The user must be able to trust every number.
2. **Grounded AI, not generative AI.** AI reads YOUR evidence and extracts structured data. It does not invent data from general knowledge. Every AI output is tagged with source and confidence.
3. **Human confirms, AI proposes.** The review workflow is not optional — it's the quality gate. Unreviewed data is visually distinct from confirmed data throughout the app.
4. **Source hierarchy matters.** An IPID extract is worth more than a marketing page scrape. A human-confirmed value is worth more than an AI extraction. The system must track and display this.
5. **Completeness before analysis.** Don't show a feature matrix with 30% data and let the user think it's complete. Show exactly what's missing, what's stale, and what's unverified.
6. **Agents propose, humans approve.** Autonomous agents accelerate research but never write directly to trusted data. Everything goes through the review pipeline.

---

## Phase 8: Data Quality & Trust Foundation

> **Priority:** CRITICAL — this must come before any new analysis or AI features.
> **Rationale:** The app currently captures evidence and extracts data, but the boundary between "AI guessed this" and "human verified this from a regulatory document" is not surfaced prominently enough. Reports and insights can currently be generated from unreviewed extraction results. This phase makes data quality a first-class, visible, enforced concept throughout the app.

### 8.1 Source Quality Hierarchy

Every data point has a source. Not all sources are equal.

- Define a **source quality tier system** (stored per project, with sensible defaults):
  - **Tier 1 — Regulatory/Official** (confidence floor: 0.9): IPIDs, KIDs, SEC filings, Companies House, FCA register, official regulatory submissions
  - **Tier 2 — Primary** (confidence floor: 0.7): company's own website, help documentation, changelogs, press releases, app store listings
  - **Tier 3 — Secondary** (confidence floor: 0.5): third-party reviews (G2, Trustpilot), news articles, analyst reports, gallery screenshots
  - **Tier 4 — Inferred** (confidence floor: 0.3): AI extraction from screenshots, AI enrichment from MCP sources, cross-referenced but unconfirmed
  - **Tier 5 — Unverified** (confidence floor: 0.1): single-source AI extraction, no corroboration
- Auto-assign tier when evidence is captured based on source URL domain and evidence type
- Display tier badges on every attribute value throughout the UI
- **Anti-hallucination rule:** Tier 5 values are visually flagged with a warning and excluded from reports by default

### 8.2 Data Quality Dashboard

A dedicated view (accessible from any tab) showing research health at a glance.

- **Per-project quality score** (0-100) composed of:
  - **Completeness** — % of schema attributes populated across entities, weighted by attribute importance
  - **Freshness** — % of attributes updated within a configurable window (e.g. 90 days)
  - **Verification** — % of attributes that have been human-reviewed vs AI-only
  - **Source diversity** — % of attributes backed by 2+ independent sources
  - **Confidence distribution** — histogram of attribute confidence scores
- **Per-entity health cards** — at-a-glance completeness ring + stale/unverified/missing indicators
- **Stale data alerts** — highlight entities where evidence is older than a threshold, with one-click re-capture
- **"Research gaps" panel** — entities or attributes with zero or Tier 5-only data, prioritised by impact on analysis
- Visual distinction: green (verified, multi-source), amber (AI-extracted, single-source), red (missing or stale)

### 8.3 Quality Gates for Reports & Insights

Prevent the generation of reports or insights from insufficiently validated data.

- **Report generation pre-check:**
  - Scan all data that would feed the report
  - Calculate % verified, % stale, % missing
  - If below configurable thresholds (default: 60% verified, <20% stale), show a warning with specific gaps listed
  - User can override (with a "I acknowledge data gaps" confirmation), but reports generated with overrides are watermarked: *"Draft — contains unverified data"*
  - Quality score embedded in every exported report
- **Insight generation filtering:**
  - "So What?" engine only considers attributes with confidence >= 0.5 and source tier <= 3
  - Hypotheses generated from Tier 4-5 data are auto-tagged as "Low confidence — needs evidence"
  - Pattern detectors weight by source tier (a pattern seen in 3 Tier 1 sources is worth more than 10 Tier 5 sources)
- **Export metadata:**
  - Every exported report includes a "Data Quality Summary" section showing the quality score, source breakdown, and any overrides
  - PDF/HTML exports include a "Methodology" appendix listing all sources used, capture dates, and extraction methods

### 8.4 Multimodal Screenshot Extraction

Currently screenshots return `(None, "image")` and aren't text-extracted. This is the single biggest data gap — the app captures hundreds of screenshots but can't read them.

- **Vision-AI extraction from screenshot evidence:**
  - Send screenshot images to Claude's vision capabilities (multimodal input)
  - Extract: visible text, UI element labels, navigation items, pricing tables, feature lists, form fields
  - Structured output: attribute-value pairs mapped to project schema
  - Confidence scored based on OCR clarity and extraction certainty
- **Screenshot comparison:**
  - Visual diff between two captures of the same page (pixel-level + extracted-text diff)
  - Surface what changed between snapshots (pricing update? new feature? redesigned UI?)
- **Batch screenshot extraction:**
  - Queue all unextracted screenshot evidence for a project
  - Background processing with progress tracking
  - Results feed into the existing review queue — human confirms before data is trusted
- **Source tier:** Screenshot extractions default to Tier 4 (Inferred) until human-reviewed, then promote to Tier 3

### 8.5 Cross-Source Validation Engine

When multiple sources provide data for the same attribute, systematically check for agreement.

- **Auto-triangulation:** When 2+ sources exist for the same entity attribute:
  - Compare values (exact match, fuzzy match for text, numerical tolerance for numbers)
  - If sources agree: auto-boost confidence to min(0.9, highest_source_confidence + 0.1)
  - If sources conflict: flag as "Contradicted" with side-by-side comparison for human review
  - If only 1 source: flag as "Uncorroborated"
- **Contradiction dashboard:** Surface all conflicting data points, grouped by entity, with source details
- **Resolution workflow:** Human picks the correct value (or enters a new one), with mandatory source citation
- **Validation rules:** Per-attribute-type validation (e.g., price must be numeric, URL must resolve, date must parse)

---

## Phase 9: Conversational Research Interface

> **Priority:** HIGH — this is the "10x solo analyst" capability that no competitor offers well.
> **Rationale:** The app has rich structured data but the only way to query it is through pre-built views. A natural language interface lets the analyst ask questions of their own data without SQL knowledge, while maintaining the evidence-grounded principle. NL2SQL accuracy is now 96%+ for specialised models (2026).

### 9.1 "Ask Your Research" — Natural Language Query

A chat-like interface where the analyst can query their project data conversationally.

- **Natural Language to SQL:**
  - User types: "Which companies offer telemedicine but not mental health cover?"
  - System translates to SQL against the entity/attribute schema
  - Returns structured results with source citations for each data point
  - Every answer shows the generated query (collapsible) for transparency
- **Grounded responses only:**
  - The system ONLY answers from project data — never from general LLM knowledge
  - If the data doesn't exist: "I don't have data on X for 12 of 28 entities. Would you like to see which ones are missing?"
  - If the data is unverified: "This answer uses 3 AI-extracted values that haven't been reviewed yet. [Show unverified]"
  - Responses include confidence indicators per data point (same visual language as quality dashboard)
- **Pre-built question templates** per lens:
  - Competitive: "What features does [entity] have that [entity] doesn't?"
  - Product: "What's the average price across all plans?"
  - Temporal: "Which entities changed pricing in the last 30 days?"
  - Signals: "What are the top 5 most active entities this month?"
- **Follow-up context:** Maintains conversation context within a session so "And what about their pricing?" works after asking about a specific company
- **Anti-hallucination:** If the LLM generates a response not grounded in the SQL result, it's blocked. The system returns SQL results verbatim and only uses the LLM for natural language formatting of those results.

### 9.2 Smart Research Assistant

Beyond data querying — a proactive research partner that suggests next steps.

- **"What should I research next?":**
  - Analyses data completeness across entities and suggests the highest-impact capture/extraction targets
  - "You have pricing data for 22/28 entities. These 6 are missing: [...]. Capture their pricing pages?"
  - Prioritises by: gap impact on analysis, ease of capture (URL available?), staleness
- **Analysis suggestions:**
  - "You now have enough data to generate a Competitive Landscape report. Want to preview?"
  - "I notice 3 entities changed their pricing this week. View in Temporal lens?"
  - "Your hypothesis 'Digital-first insurers have lower premiums' now has 8 supporting and 2 contradicting data points. Review?"
- **Methodology guidance:**
  - For active playbook runs: "Step 3 is 'Extract features from captured pages.' You have 15 unextracted captures. Start extraction?"
  - Suggests which playbook to use based on project schema and data patterns
- **All suggestions grounded in data:** Every recommendation cites the specific data state that triggered it

### 9.3 Project Briefing (Template-Driven, Zero Hallucination)

One-click "brief me on this project" that generates a concise status report.

- Summarises: entity count, data completeness, recent changes, active monitors, pending review items
- Highlights: key findings, data quality issues, suggested actions
- **Template-driven with data fill** — NOT generative prose. A structured template with slots filled by SQL queries. Zero hallucination risk because no LLM generates claims.
- Refreshes on project open as an optional "morning briefing"
- Exportable as single-page HTML for quick sharing

---

## Phase 10: Advanced Visualisation & Analysis

> **Priority:** HIGH — the current lenses are functional but visually basic compared to what Flourish/Datawrapper/Tableau offer.
> **Rationale:** The competitive landscape analysis revealed that market positioning visualisations, radar charts, and interactive reports are table-stakes for CI tools. The app has the data — it needs richer ways to see it.

### 10.1 Market Positioning Maps (Enhanced)

Upgrade from basic 2D scatter to publication-quality positioning visualisations.

- **Magic Quadrant style:** 2×2 matrix with labelled quadrants (e.g., "Leaders / Challengers / Visionaries / Niche"), entities as positioned dots, quadrant labels configurable per project
- **Bubble chart:** Third dimension as bubble size (e.g., pricing, funding, employee count)
- **Radar/Spider chart:** Multi-attribute comparison for selected entities (5-8 dimensions), overlay multiple entities for quick comparison
- **Grouped bar chart:** Side-by-side attribute comparison across entities
- **All charts:**
  - Interactive (hover for details, click to drill into entity)
  - Exportable as SVG/PNG for reports
  - Show data quality indicators per data point (same visual language: solid = verified, hollow = extracted, dash = missing)
  - Only show data points with Tier 3 or better by default, with toggle to include lower tiers
- **Auto-positioning:** AI suggests axis assignments based on attribute types and data distribution

### 10.2 Interactive HTML Reports (Live Data)

Transform the current static HTML export into a self-contained interactive mini-app.

- **Embedded charts:** Positioning maps, feature matrices, and timelines render as interactive SVG/JS within the report — not static images
- **Filtering:** Report viewer can filter by entity, time range, attribute type
- **Drill-down:** Click an entity name to expand its detail card within the report
- **Evidence viewer:** Click a source citation to see the actual evidence (screenshot thumbnail, document excerpt) inline
- **Methodology section:** Auto-generated appendix showing data quality score, source list, capture dates, extraction methods, and any quality gate overrides
- **Self-contained:** Single HTML file with all CSS/JS inlined, works offline, shareable as email attachment
- **Responsive:** Renders well on desktop and tablet for stakeholder viewing
- **Trust indicators:** Every data point in the report shows its provenance tier. Readers can see at a glance what's verified vs. inferred.

### 10.3 Market Structure Detection

Auto-discover groupings and segments in the data without manual configuration.

- **Clustering:** K-means or hierarchical clustering on entity attributes to discover natural market segments
- **Segment naming:** AI proposes descriptive names for clusters based on their distinguishing attributes
- **Segment comparison:** Automatic cross-segment analysis (average pricing, feature coverage, evidence depth per segment)
- **Outlier detection:** Flag entities that don't fit any cluster cleanly
- **Dendrograms:** Visualise entity similarity as a tree structure
- **Quality guard:** Clustering excludes Tier 5 attributes and entities with <50% attribute completeness to prevent garbage segments from thin data

### 10.4 Trend Forecasting from Temporal Data

When sufficient temporal snapshots exist, project trends forward.

- **Attribute trend lines:** Linear/polynomial fit on temporal attribute values (e.g., pricing trending up across market)
- **Change velocity:** Which entities are changing fastest? Which attributes are most volatile?
- **Market-level trends:** Aggregate trends across all entities (e.g., "average price increased 12% over 6 months")
- **Confidence bands:** Wide uncertainty bands, clearly labelled as "projection based on N data points over M months"
- **Anti-hallucination:** Forecasts explicitly labelled as *extrapolations*, never presented as facts. Minimum data threshold (5+ temporal snapshots from Tier 3+ sources) before any trend line is shown. Displayed with clear "PROJECTION" labels distinct from verified data.

---

## Phase 11: Agentic Research Workflows

> **Priority:** MEDIUM-HIGH — this is where the "solo analyst with the power of a team" vision comes alive.
> **Rationale:** AI agents capable of autonomous web browsing hit production in 2025 (Google Chrome auto-browse, OpenAI Atlas, Salesforce Agentforce). Competitor tools already auto-monitor. But none combine autonomous capture with structured extraction and human review gates. This phase builds on the existing capture engine and MCP integration.
> **Critical constraint:** Every agent action feeds through the existing review pipeline. Agents propose, humans confirm. No agent writes directly to trusted entity data.

### 11.1 Research Agent — Autonomous Entity Discovery

An AI agent that can find and populate entities without manual URL entry.

- **Input:** Research question or entity type (e.g., "Find all UK health insurance providers with a mobile app")
- **Agent workflow:**
  1. Searches via MCP sources (DuckDuckGo, Wikipedia, Companies House, FCA register, etc.)
  2. Identifies candidate entities with URLs, descriptions, and initial classification
  3. Deduplication check against existing entities (name similarity via Dice coefficient + URL domain match)
  4. Presents candidates for human approval (name, URL, confidence, source, reason for inclusion)
  5. On approval: creates entity, queues capture jobs for key pages
- **Human-in-the-loop:** Agent proposes, user confirms. Never auto-creates entities.
- **Batch discovery:** "Find 50 companies in UK health insurance" runs as background job with periodic candidate batches for review
- **Discovery log:** Full audit trail of what the agent searched, what it found, what it proposed, what was accepted/rejected

### 11.2 Research Agent — Autonomous Capture & Extraction

Once entities exist, an agent can autonomously capture and extract data to fill schema gaps.

- **Input:** Entity with URL + project schema + completeness gaps
- **Agent workflow:**
  1. Analyses entity's current attribute completeness
  2. Identifies which attributes are missing and what evidence types could fill them
  3. Visits entity's website(s) and discovers key pages:
     - Common URL patterns: `/pricing`, `/features`, `/plans`, `/about`, `/help`, `/changelog`, `/blog`
     - Sitemap.xml parsing
     - Link analysis from homepage
     - AI classification of discovered pages against project schema needs
  4. Captures each relevant page (screenshot + HTML archive)
  5. Extracts structured data against project schema
  6. Queues ALL extractions for human review (nothing auto-accepted)
- **Rate limiting:** Polite crawling (configurable delay, robots.txt respect, User-Agent identification)
- **Progress tracking:** Per-entity capture/extraction progress visible in Research tab
- **Quality reporting:** Agent reports what it couldn't find (e.g., "No pricing page found for [entity] — checked /pricing, /plans, /cost, sitemap")
- **Source tier:** All agent-captured evidence defaults to Tier 4 until human review

### 11.3 Research Agent — Market Scan

End-to-end automated market research combining discovery + capture + extraction.

- **Input:** Research question + schema template (or active playbook)
- **Agent workflow:**
  1. **Discover:** Find N entities matching the research question (Phase 11.1)
  2. **Capture:** For each approved entity, capture key pages (Phase 11.2)
  3. **Extract:** Run extraction pipeline on all captures
  4. **Report:** Generate completeness summary and queue review items
- **Checkpoints:** Agent pauses for human review at each stage transition (discovery → capture → extraction). User can adjust scope, reject entities, or redirect the agent.
- **Cost tracking:** Estimated and actual LLM costs shown per stage, with budget limits that pause the agent
- **Resume capability:** If interrupted, agent can resume from last checkpoint
- **Playbook integration:** If running within a playbook, agent auto-advances playbook steps as it completes each stage

### 11.4 Scheduled Research Automation

Combine monitoring with periodic re-research on a configurable schedule.

- **Scheduled re-capture:** Weekly/monthly full re-capture of all entity pages (or subset by entity type / staleness)
- **Scheduled extraction:** Re-extract from new captures, compare with previous values, flag changes
- **Change detection pipeline:**
  1. Capture new snapshot
  2. Diff against previous snapshot (content hash + extracted value comparison)
  3. If significant change detected: create change feed entry + re-extract + queue for review
  4. If major/critical: trigger re-capture of related pages (existing `_trigger_recapture`)
- **Digest generation:**
  - Daily/weekly summary rendered as HTML file (same interactive format as reports)
  - Accessible in-app notification centre and as local file
  - Configurable: which event types to include, minimum severity, which entities
- **Drift detection:** Alert when extracted values change beyond a configurable threshold (e.g., pricing changed >10%, feature added/removed)

### 11.5 Research Queue Manager

A unified view of all pending research work across the project.

- **Queue sources:** Manual captures, agent-proposed captures, scheduled re-captures, monitoring triggers, playbook steps, review items
- **Priority scoring:** Urgency (monitoring alert? playbook deadline? staleness?) × Impact (fills a data gap? high-value entity? completeness improvement?)
- **Batch execution:** Select multiple items and execute as a batch background job
- **Queue analytics:** Items processed per day, average time-to-review, backlog size, estimated time to clear
- **Auto-prioritisation:** Smart ordering based on quality dashboard gaps — "these 5 captures would increase your project quality score from 62 to 78"

---

## Phase 12: Workflow & Methodology Depth

> **Priority:** MEDIUM — these features improve research rigour and repeatability.
> **Rationale:** Current playbooks are generic templates. Domain-specific playbooks with pre-configured schemas, known data sources, and quality expectations would differentiate this tool from every generic CI platform.

### 12.1 Domain-Specific Playbook Packs

Pre-built research methodology packs for common research domains.

- **UK Insurance:**
  - Schema: Insurer → Product Line → Plan → Tier → Feature
  - Expected sources: FCA register (MCP), IPID documents, company websites, comparison sites
  - Quality expectations: Every plan must have IPID-sourced features (Tier 1), pricing from 2+ sources
  - Built-in extractor config: IPID parser auto-enabled, pricing page extractor tuned for insurance terms
  - Playbook steps: Register scan → Company websites → IPID collection → Feature extraction → Pricing capture → Review → Report
- **Fintech / Digital Banking:**
  - Schema: Company → Product → Feature → Pricing Tier
  - Expected sources: App stores, company websites, FCA/PRA register, Crunchbase (via MCP)
  - Quality expectations: App store data + website data for each product
- **Design Research:**
  - Schema: Product ↔ Design Principle (graph)
  - Expected sources: UI galleries (Mobbin, Dribbble, etc.), company websites, design blogs
  - Quality expectations: 10+ screenshot evidence per product, 3+ examples per principle
- **SaaS Competitive Analysis:**
  - Schema: Company → Product → Plan → Feature
  - Expected sources: G2/Capterra reviews, pricing pages, product changelogs, Crunchbase
  - Quality expectations: Pricing from direct source, features from help docs + marketing page
- Each pack includes: schema template, playbook steps, recommended MCP servers, quality thresholds, example report template, suggested entity count target

### 12.2 Research Completeness Guidance

Active guidance on what to research next, tied to methodology.

- **Completeness tracker per playbook step:**
  - "Step 2: Capture product pages — 34/50 entities captured, 16 remaining"
  - Progress bars per step, per entity type, per attribute group
- **Smart prioritisation:**
  - "These 5 entities have the least data — focus here for maximum impact on your competitive matrix"
  - "Your pricing analysis would be 90% complete if you captured pricing for these 3 companies"
  - Prioritised by: impact on quality score, ease of capture, staleness
- **Methodology warnings:**
  - "You're running a Competitive Landscape report but only 40% of entities have been through human review. Review 15 more to reach the recommended 60% threshold."
  - "Your design research has screenshots but no feature extraction — the Design lens will be limited"
  - Warnings block or watermark reports below threshold (Phase 8.3)

### 12.3 Evidence Annotation

Add annotations directly on captured evidence — linking observations to entity attributes.

- **Screenshot annotation:**
  - Draw rectangles/arrows/text overlay on captured screenshots
  - Each annotation linked to an entity attribute (e.g., highlight a price → links to pricing attribute)
  - Annotations stored as JSON overlay metadata, original evidence image preserved
- **Document annotation:**
  - Highlight text passages in captured HTML/PDF documents
  - Link highlights to entity attributes (e.g., highlight a feature description → links to feature attribute)
- **Annotation as evidence:**
  - Annotations serve as human-confirmed evidence for attribute values
  - Auto-promotes source tier from Tier 4 (Inferred) to Tier 2 (Primary) when human-annotated
  - This is a key quality improvement path: AI extracts → human annotates the evidence → trusted data
- **Annotation gallery:**
  - Browse all annotations across a project, filter by entity/attribute/date

### 12.4 Import from External Tools

Lower the barrier to adoption by importing existing research.

- **CSV/Excel enhanced import:**
  - Column mapping wizard with AI-assisted column-to-attribute matching
  - Preview + validation before import
  - Handles hierarchical data (parent entity column + child columns)
  - Imported data defaults to Tier 3 (Secondary) with "import" source tag
- **Airtable import:**
  - Connect via API key, select base + table
  - Map Airtable fields to entity attributes
  - Handles linked records as entity relationships
- **Notion database import:**
  - Connect via integration token, select database
  - Map Notion properties to entity attributes
  - Handles relations as entity relationships
- **JSON/API import:**
  - Define a JSON mapping schema
  - Import from URL or file
  - Useful for importing from other CI tools or custom data sources

---

## Phase 13: Distribution & Stakeholder Access

> **Priority:** MEDIUM — the user's primary audience is C-suite and board.
> **Rationale:** Currently the only way to share research is via exported files. A lightweight sharing mechanism (without full collaboration, which was explicitly rejected) would let stakeholders browse research interactively.

### 13.1 Stakeholder Read-Only Sharing

Share a project or report via a self-contained package — no server required, no cloud dependency.

- **Project snapshot export:**
  - Export entire project as a self-contained HTML bundle (data + interactive UI + evidence thumbnails)
  - Stakeholder opens in any browser, browses entities, views analysis lenses, reads reports
  - No server needed — single folder with index.html + assets
  - Data frozen at export time (point-in-time snapshot)
  - Quality score and methodology section prominently displayed
- **Report sharing (enhanced):**
  - Interactive HTML reports (Phase 10.2) serve as the primary sharing format
  - Include "Methodology" and "Data Quality" sections automatically
  - Trust indicators visible to stakeholders (they can see what's verified vs. inferred)
- **Password protection (optional):**
  - Encrypt the exported bundle with a passphrase
  - Stakeholder enters passphrase to view
- **Feedback collection:**
  - Include a simple "Comments" panel in shared reports
  - Comments saved in stakeholder's browser (localStorage)
  - Exportable as JSON to send back to the analyst

### 13.2 Notification System

In-app and local notification system for monitoring events and research milestones.

- **In-app notification centre:**
  - Bell icon with badge count in the header
  - Notifications for: monitoring alerts (by severity), scheduled capture completions, review queue growth, quality threshold breaches, playbook step completions, agent checkpoint requests
  - Read/unread state, mark all as read, filter by type
- **Local digest files:**
  - Daily/weekly summary written to a local HTML file (e.g., `digests/2026-02-21.html`)
  - Same interactive format as reports
  - Configurable: which event types, minimum severity, which entity types
  - One-click open from notification centre
- **Desktop notifications (pywebview):**
  - macOS native notifications for critical/major monitoring alerts and agent checkpoint requests
  - Configurable in Settings tab

### 13.3 REST API for External Integration

Expose a subset of the workbench's data via the local Flask API for external tools.

- **Read-only API endpoints:**
  - Entity listing with attribute data (JSON)
  - Evidence metadata (not files — metadata only)
  - Analysis results (lens data as JSON)
  - Report content (Markdown/JSON)
  - Quality scores per project/entity
- **Authentication:** Simple API key configured in Settings
- **Use cases:**
  - Feed data into external dashboards (Tableau, Power BI, Observable)
  - Connect to automation tools (n8n, Make, Zapier) for custom workflows
  - Build custom visualisations in D3.js from workbench data
- **OpenAPI spec:** Auto-generated from Flask routes

---

## Phase 14: Platform Maturity & Scale

> **Priority:** LOW-MEDIUM — quality-of-life improvements and performance at scale.
> **Rationale:** As the app handles larger projects (500+ entities with deep hierarchies), performance and usability need attention.

### 14.1 Performance Optimisation for Large Projects

- **Virtual scrolling:** Entity browser with 500+ entities needs virtualised list rendering
- **Lazy lens computation:** Only compute lens data when the lens is actually opened, not on tab switch
- **Incremental extraction:** Re-extract only changed evidence, skip unchanged
- **SQLite query optimisation:** EXPLAIN ANALYZE on hot paths, covering indexes where needed
- **Evidence thumbnail generation:** Pre-generate thumbnails for screenshot evidence to avoid loading full images in galleries and reports

### 14.2 Keyboard-Driven Research Workflow

- **Command palette enhancement:** All actions accessible via Cmd+K — fuzzy search across entities, evidence, reports, lenses, actions
- **Review queue shortcuts:** a/r/e for accept/reject/edit, Tab for next item, Shift+Tab for previous
- **Quick capture shortcut:** Global shortcut to capture current clipboard as evidence (even when app is backgrounded)
- **Vim-style navigation (optional):** j/k for list navigation, Enter to drill in, Escape to back

### 14.3 Backup & Data Portability

- **Automated project backup:**
  - One-click full project export (SQLite data + evidence files + reports) as zip archive
  - Scheduled auto-backup to a configured directory (daily/weekly)
- **Project import:**
  - Import a previously exported project zip into a fresh workbench install
  - Handles schema migration if the app version has changed
- **Data portability guarantee:** All data stored in open formats (SQLite, JSON, PNG/PDF files). Zero vendor lock-in. The data is yours.

### 14.4 Plugin / Extension Architecture

- **Custom extractors:** Drop Python modules into `extractors/` directory, auto-discovered and registered in classifier pipeline
- **Custom MCP servers:** Already partially supported — formalise with `mcp-servers/` convention, auto-registration, and health monitoring
- **Custom report templates:** Drop Jinja2 templates into `report-templates/` directory, available alongside built-in templates
- **Custom playbooks:** Import/export playbook definitions as JSON files for sharing between installations
- **Custom source tier rules:** Define URL domain → tier mappings per project for auto-classification

### 14.5 Semantic Search (Local Embeddings)

Meaning-based search across all project data, running entirely locally.

- **Local embedding generation:** Via Ollama + nomic-embed-text (or similar) on Apple Silicon — no cloud dependency
- **Embedding targets:** Entity names + descriptions, attribute values, evidence text content, report sections
- **sqlite-vss integration:** Vector similarity search as a SQLite virtual table
- **Use cases:**
  - "Companies doing claims automation" finds "automated adjudication platform" (semantic, not keyword)
  - "Find similar to [entity]" uses embedding cosine similarity across all attributes
  - Natural language search in evidence library
- **Privacy:** All embeddings computed and stored locally. Research data never leaves the device.
- **Quality integration:** Search results show quality tier indicators alongside relevance scores

---

## Priority Matrix

| Phase | Name | Priority | Depends On | Key Value |
|-------|------|----------|------------|-----------|
| **8** | Data Quality & Trust | CRITICAL | Existing infrastructure | Every analysis and report becomes provably trustworthy |
| **9** | Conversational Research | HIGH | Phase 8 (quality scoring) | 10x faster data exploration with zero hallucination risk |
| **10** | Advanced Visualisation | HIGH | Existing lenses | Publication-quality outputs for C-suite / board |
| **11** | Agentic Research | MEDIUM-HIGH | Phase 8 (quality gates) | Automate the capture→extract cycle with human oversight |
| **12** | Workflow & Methodology | MEDIUM | Existing playbooks | Research rigour, repeatability, domain expertise |
| **13** | Distribution & Sharing | MEDIUM | Phase 10 (interactive reports) | Get research to stakeholders without them needing the app |
| **14** | Platform Maturity | LOW-MEDIUM | All phases | Performance at scale, extensibility, data portability |

---

## Anti-Hallucination Architecture (Cross-Cutting Concern)

This is not a phase — it's an architectural principle enforced across ALL current and future features.

### The Trust Chain

```
Evidence (screenshot, document, URL capture)
  → Extraction (AI reads evidence, proposes structured values)
    → Review (human confirms, edits, or rejects)
      → Attribute (stored with source, confidence, tier, timestamp)
        → Analysis (only uses reviewed + high-confidence data)
          → Report (cites evidence for every claim, shows quality score)
```

**Every link in this chain must be traceable.** If a report says "Company X charges £29/month," the reader can click through to: the attribute → the extraction job → the evidence screenshot → the source URL. This chain already exists (Phase 5.4 provenance) — the roadmap strengthens it with quality gates and visual indicators.

### Rules Enforced Across All Phases

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | No report generation from unreviewed data without explicit override + watermark | Phase 8.3 quality gates |
| 2 | No insight generation from Tier 5 (unverified single-source AI) data | Phase 8.3 insight filtering |
| 3 | No trend forecasting from fewer than 5 temporal data points from Tier 3+ sources | Phase 10.4 minimum thresholds |
| 4 | No entity auto-creation by agents without human approval | Phase 11.1 human-in-the-loop |
| 5 | No attribute auto-promotion — AI extractions stay at their source tier until human-reviewed | Phase 8.1 tier system |
| 6 | Visible quality indicators on every data point everywhere in the UI | Phase 8.2 visual language |
| 7 | Methodology transparency in every export — sources, capture dates, quality score | Phase 8.3 export metadata |
| 8 | AI responses from NL query grounded only in SQL results, never general knowledge | Phase 9.1 grounding |
| 9 | Contradiction surfacing — when sources disagree, both are shown, never silently resolved | Phase 8.5 validation engine |
| 10 | Freshness warnings on data older than configurable threshold | Phase 8.2 staleness alerts |

### Data Quality Visual Language (The Instrument Extension)

| Indicator | Meaning | Visual Treatment |
|-----------|---------|------------------|
| Verified | Human-reviewed, multi-source confirmed | Solid dot, full opacity |
| Confirmed | Human-reviewed, single source | Solid dot, 80% opacity |
| Extracted | AI-extracted, pending review | Hollow dot, 60% opacity |
| Inferred | AI-inferred from indirect evidence | Dashed outline, 40% opacity |
| Missing | No data for this attribute | Empty cell with subtle dash |
| Stale | Data older than freshness threshold | Timestamp icon, muted colour |
| Contradicted | Multiple sources disagree | Split dot (two-tone) |

These indicators appear on: entity attribute values, feature matrix cells, chart data points, report claims, insight evidence citations, and positioning map entities.

---

## Relationship to Completed Implementation Plan

This roadmap is the **successor** to the original Implementation Plan (Phases 1-7 + MCP + Audit, all complete).

| Original Phase | Status | Roadmap Extension |
|----------------|--------|-------------------|
| Phase 1: Data Model + Schema | ✅ Complete | Phase 8 adds source quality tiers to attributes |
| Phase 2: Capture Engine | ✅ Complete | Phase 11 adds agentic capture automation |
| Phase 3: Extraction + Review | ✅ Complete | Phase 8.4 adds multimodal screenshot extraction |
| Phase 4: Analysis Lenses | ✅ Complete | Phase 10 adds advanced visualisation types |
| Phase 5: Reports + Provenance | ✅ Complete | Phase 8.3 adds quality gates; Phase 10.2 makes reports interactive |
| Phase 6: Monitoring | ✅ Complete | Phase 11.4 adds scheduled automation + digests |
| Phase 7: Intelligence | ✅ Complete | Phase 9 adds conversational querying |
| MCP Integration | ✅ Complete | Phase 11.1 uses MCP for agent-powered discovery |
| Red-Team Audit | ✅ Complete | Phase 14 continues platform maturity |

---

## Competitive Positioning After Roadmap

After implementing Phases 8-14, the Research Workbench would have capabilities that no single competitor offers:

| Capability | Crayon | Klue | AlphaSense | Competely | Airtable | Dovetail | **Research Workbench** |
|------------|--------|------|------------|-----------|----------|----------|----------------------|
| Evidence-grounded reports | Partial | No | Partial | No | No | No | **Full provenance chain + quality gates** |
| Data quality scoring | No | No | No | No | No | No | **Multi-dimensional (5 factors)** |
| Quality gate enforcement | No | No | No | No | No | No | **Pre-report validation** |
| Flexible entity schema | No | No | No | No | Yes | No | **AI-guided per project** |
| Multimodal extraction | Partial | No | Yes | Partial | No | No | **With human review gates** |
| Natural language query | No | No | Yes | No | No | No | **Grounded in YOUR data only** |
| Interactive HTML reports | No | No | No | No | No | No | **Self-contained with trust indicators** |
| Agentic research | Partial | No | Partial | Partial | No | No | **Full pipeline with checkpoints** |
| Domain-specific playbooks | No | No | No | No | Partial | No | **With source hierarchy + quality thresholds** |
| Cross-source validation | Partial | No | Yes | No | No | No | **Systematic triangulation** |
| Stakeholder sharing | Yes | Yes | Yes | No | Yes | Yes | **Self-contained bundles, no cloud** |
| Local-first / desktop | No | No | No | No | No | No | **All data on your machine** |
| Solo analyst optimised | No | No | No | Yes | Partial | No | **Core design principle** |
| Pricing | $20K+/yr | $15K+/yr | $10K+/yr | $99/mo | $20/mo | $29/mo | **Free (self-hosted)** |

---

## Sources

### Competitive Landscape (Researched 2026-02-21)
- [Crayon](https://www.crayon.co/) — Enterprise CI, $20-40K/yr, automated monitoring + battlecards
- [Klue](https://klue.com/) — Sales enablement CI, Compete Agent AI, custom enterprise pricing
- [AlphaSense](https://www.alpha-sense.com/) — Financial intelligence, $10-100K+/yr, semantic search + Smart Summaries
- [Contify](https://www.contify.com/) — AI market intelligence, 1M+ sources, custom pricing
- [Valona Intelligence](https://valonaintelligence.com/) — Global CI (fka M-Brain), custom pricing
- [Kompyte](https://www.kompyte.com/) — Acquired by Semrush 2014, competitor tracking
- [Competely](https://competely.ai/) — AI competitor analysis, $9-99/mo, 100+ data points
- [RivalSense](https://rivalsense.co/) — Founder-focused CI, 80+ sources, custom pricing
- [Browse AI](https://www.browse.ai/) — No-code web scraping, free-$249/mo
- [Mobbin](https://mobbin.com/) — UI design library, 300K+ screens, ~$130/yr
- [Dovetail](https://dovetail.com/) — User research repository, free-$29+/user/mo
- [Notably](https://www.notably.ai/) — Qualitative research, AI-powered coding
- [Airtable](https://www.airtable.com/) — Flexible database, competitive analysis templates
- [Notion](https://www.notion.com/) — Wiki/database, CI templates
- [Flourish](https://flourish.studio/) — Interactive data visualisation
- [Datawrapper](https://www.datawrapper.de/) — Chart/map/table creation
- [Prisync](https://prisync.com/) — E-commerce price monitoring, from $99/mo

### Market Data
- [Fortune Business Insights](https://www.fortunebusinessinsights.com/competitive-intelligence-tools-market-104522) — CI market: $0.56B (2024) → $1.62B (2033), 12.5% CAGR
- [CI Automation Playbook 2026](https://arisegtm.com/blog/competitive-intelligence-automation-2026-playbook) — CRAFT methodology
- [NL2SQL Guide](https://groundy.com/articles/natural-language-sql-ai-finally-making-databases/) — 96%+ accuracy on standard benchmarks
- [AI Agents 2025-2026](https://theconversation.com/ai-agents-arrived-in-2025-heres-what-happened-and-the-challenges-ahead-in-2026-272325)
- [Multimodal Data Extraction](https://www.veryfi.com/technology/multimodal-data-extraction-beyond-basic-ocr/) — VLMs for document understanding
- [Data Quality Scoring](https://lakefs.io/data-quality/data-quality-metrics/) — 6 core quality dimensions
- [AI Hallucination Mitigation](https://www.mdpi.com/2227-7390/13/5/856) — RAG reduces hallucinations 42-68%
- [Agentic Browser Landscape 2026](https://www.nohackspod.com/blog/agentic-browser-landscape-2026) — $4.5B → $76.8B by 2034
