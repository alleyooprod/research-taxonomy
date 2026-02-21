# Research Workbench — Implementation Plan V2 (Agentic)

> **Status:** PLANNING — awaiting first implementation session.
> **Created:** 2026-02-21 (Session 30)
> **Foundation:** `IMPLEMENTATION_PLAN.md` (Phases 1-7 + MCP + Audit, all complete, 1700 tests)
> **Feature Roadmap:** `FEATURE_ROADMAP.md` (full vision, Phases 8-14)
> **Architecture Decisions:** `docs/AGENTIC_ARCHITECTURE.md`
> **Red-Team Analysis:** `docs/RED_TEAM_FINDINGS.md` (10 findings that shaped this plan)
> **Competitive Landscape:** `docs/COMPETITIVE_LANDSCAPE_2026.md`
> **Original Vision:** `docs/RESEARCH_WORKBENCH_VISION.md`

---

## Overview

This plan transforms the Research Workbench from a **human-orchestrated tool** into an **agent-orchestrated research environment**. The user defines the mission and reviews the output. The agent handles everything in between — discovery, capture, extraction, analysis, and report drafting.

**The shift:**
```
BEFORE: User initiates every step. Active time: 14-24 hours per 50-entity project.
AFTER:  User defines mission + reviews output. Active time: 2-3 hours.
```

**Architecture:** Hybrid Plan-and-Execute + Supervisor-Worker. See `docs/AGENTIC_ARCHITECTURE.md` for full rationale and rejected alternatives.

**Guiding principles (from red-team):**
1. Smart-sort review queue, not auto-accept (until calibrated with real data)
2. Three quality dimensions shown separately, not as composite score
3. Entity budgets to prevent scope creep
4. Pre-run cost estimates with budget caps
5. Sensible defaults for all configuration — progressive disclosure
6. Ship Phase 8 + 9 first, run against real project, iterate

**Testing principle (unchanged from V1):** Every implementation step includes corresponding DB + API tests. All 1700 existing tests continue to pass. Test count grows in lockstep.

---

## Current State (Built — Sessions 1-32)

- **1700 pytest tests passing** across 43+ test files
- **Phases 1-7 complete:** Entity schema, capture engine, extraction pipeline, review workflow, 6 analysis lenses, 5 report templates, monitoring (8 check types), intelligence (insights, hypotheses, playbooks, cross-project)
- **MCP integration:** 11 enrichment adapters, smart routing, 16 server catalogue entries
- **Red-team audit:** 108 original findings + 60 v2 findings addressed across 4 phases (Sessions 28-32)
- **Architecture:** Flask + Blueprints (split into packages), SQLite WAL, esbuild bundled JS/CSS, lazy tab rendering, event delegation
- **Session 32 additions:** defusedxml for XXE prevention, cost tracking on all 36 `run_cli()` calls, trapFocus on modals, `_conn()` context manager with commit/rollback, entity prompt cap (30 attrs + 500 chars), busy_timeout 10s, overlap scan caching
- **Key infrastructure for agent:** `core/capture.py`, `core/extraction.py`, 7 extractors, `core/mcp_client.py`, `core/mcp_enrichment.py`, `web/async_jobs.py`, `core/llm.py` with cost tracking

---

## Phase 8: Data Quality & Trust Foundation

**Goal:** Make data quality a first-class, visible, actionable concept. Every data point shows its trustworthiness. Quality gates prevent reports from unverified data.

**Priority:** CRITICAL — must precede agentic automation. The agent will generate large volumes of data; quality infrastructure must exist to assess it.

**Depends on:** Existing entity attributes, evidence library, extraction pipeline (all complete).

### 8.1 Source Quality Tier System
- [ ] Define 5-tier source quality hierarchy:
  - Tier 1 — Regulatory/Official (confidence floor 0.9): FCA register, IPIDs, SEC filings, Companies House
  - Tier 2 — Primary (confidence floor 0.7): company website, help docs, changelogs, press releases, app store
  - Tier 3 — Secondary (confidence floor 0.5): third-party reviews, news, analyst reports, gallery screenshots
  - Tier 4 — Inferred (confidence floor 0.3): AI extraction from screenshots, MCP enrichment, cross-referenced unconfirmed
  - Tier 5 — Unverified (confidence floor 0.1): single-source AI extraction, no corroboration
- [ ] `source_tier` column on `entity_attributes` table (integer 1-5, default 5)
- [ ] Auto-assign tier on evidence capture based on source URL domain patterns + evidence type
- [ ] Tier classification rules stored per project (with sensible defaults), configurable via API
- [ ] Tier display throughout UI: badge on every attribute value, colour-coded (T1 green → T5 red)
- [ ] API: `GET /api/quality/tiers` (list rules), `POST /api/quality/tiers` (update rules)
- [ ] **Files:** `core/quality.py` (new), `storage/repos/entities.py` (migration), `web/blueprints/quality.py` (new)
- [ ] **Tests:** tier assignment logic, auto-classification, API endpoints, migration preserves existing data

### 8.2 Freshness Decay Model
- [ ] Per-attribute-type freshness half-lives (configurable per project, sensible defaults):
  - Company identity: 365 days
  - Pricing: 90 days (override: 365 for insurance)
  - Features/capabilities: 60 days
  - App store rating: 30 days
  - Employee count / funding: 120 days
  - Website content: 45 days
  - Regulatory status: 180 days
  - News / press: 14 days
- [ ] Freshness score: `e^(-0.693 × days_since_capture / half_life)` per attribute
- [ ] Freshness computed on read (not stored — always current)
- [ ] Staleness alerts: attributes below 0.5 freshness on high-relevance entities flagged
- [ ] Monitoring integration: when a check detects change, related attribute freshness drops to 0.3 immediately
- [ ] API: `GET /api/quality/freshness?project_id=N` (all attributes with freshness), `GET /api/quality/freshness/config` (half-lives), `POST /api/quality/freshness/config`
- [ ] **Files:** `core/quality.py` (freshness functions), `web/blueprints/quality.py` (endpoints)
- [ ] **Tests:** decay calculation, configurable half-lives, staleness detection, monitoring integration

### 8.3 Quality Dashboard
- [ ] Three separate quality dimension bars per entity (NOT composite score — red-team finding #2):
  - **Accuracy bar:** % of attributes human-reviewed × source tier weight
  - **Relevance bar:** entity tag weight (core=1.0, adjacent=0.6, peripheral=0.3) × attribute-feeds-analysis weight
  - **Freshness bar:** average freshness score across entity's attributes
- [ ] Per-entity health cards: three mini-bars + stale/unverified/missing counts
- [ ] Project-level summary: overall bars for each dimension, entity count by health status
- [ ] "Research gaps" panel: high-relevance missing attributes, prioritised by impact on active lenses
- [ ] Heatmap view: entities × quality dimensions colour matrix
- [ ] Visual language (The Instrument extension): solid dot (verified), hollow dot (extracted), dashed (inferred), empty dash (missing), timestamp icon (stale), split dot (contradicted)
- [ ] Quality section accessible from any tab (header widget or dedicated sub-view in Intelligence)
- [ ] **Files:** `web/static/js/quality.js` (new), `web/static/css/quality.css` (new), `web/blueprints/quality.py` (dashboard endpoints)
- [ ] **Tests:** dimension calculations, entity health aggregation, project rollup, gap prioritisation

### 8.4 Quality Gates for Reports & Insights
- [ ] Pre-report generation scan: check all data feeding the report template
- [ ] Calculate per-dimension status: % verified (accuracy), % high-relevance populated (relevance), % fresh (freshness)
- [ ] Configurable thresholds (defaults): accuracy ≥ 60% verified, freshness ≥ 50% fresh, relevance ≥ 70% populated
- [ ] Below threshold: warning with specific gaps listed + "Generate anyway" override
- [ ] Override → report watermarked: *"Draft — contains unverified data"* + quality summary section auto-appended
- [ ] Insight generation filtering: "So What?" engine only considers attributes with confidence ≥ 0.5 and source tier ≤ 3
- [ ] Export metadata: every exported report includes methodology appendix (sources, capture dates, quality status, overrides)
- [ ] **Files:** `core/quality.py` (gate logic), `web/blueprints/reports/` (pre-check integration), `web/blueprints/insights/` (filtering)
- [ ] **Tests:** gate pass/fail logic, threshold configuration, override watermarking, insight filtering

### 8.5 Multimodal Screenshot Extraction
- [ ] Vision-AI extraction from screenshot evidence (currently returns `(None, "image")`)
- [ ] Send screenshot images to Claude vision (multimodal input via `core/llm.py`)
- [ ] Extract: visible text, UI labels, navigation items, pricing tables, feature lists, form fields
- [ ] Structured output: attribute-value pairs mapped to project schema
- [ ] Confidence scored by extraction certainty (typically Tier 4 until reviewed)
- [ ] Batch screenshot extraction: queue all unextracted screenshots, background processing
- [ ] Results feed into existing review queue (smart-sorted)
- [ ] Screenshot comparison: visual diff between two captures of same page (content hash + extracted-text diff)
- [ ] **Files:** `core/extraction.py` (vision extraction path), `core/extractors/screenshot.py` (enhanced), `web/blueprints/extraction.py` (batch endpoint)
- [ ] **Tests:** vision extraction with mocked LLM, batch processing, comparison logic, review queue integration

### 8.6 Cross-Source Validation Engine
- [ ] When 2+ sources exist for same entity attribute: auto-compare values
- [ ] Exact match + fuzzy match (text) + numerical tolerance (numbers) + URL domain match (URLs)
- [ ] Sources agree → auto-boost confidence: `min(0.9, highest_confidence + 0.1)`
- [ ] Sources conflict → flag as "Contradicted" with side-by-side comparison
- [ ] Single source only → flag as "Uncorroborated"
- [ ] Contradiction dashboard: grouped by entity, source details, resolution workflow
- [ ] Resolution: human picks correct value with mandatory source citation
- [ ] Per-attribute-type validation rules (price must be numeric, URL must parse, date must parse)
- [ ] **Files:** `core/quality.py` (validation engine), `web/blueprints/quality.py` (contradiction endpoints)
- [ ] **Tests:** agreement detection, conflict detection, fuzzy matching, resolution workflow, validation rules

---

## Phase 9: Agentic Research Core

**Goal:** Autonomous multi-stage research execution. User defines mission, agent discovers → captures → extracts → analyses → reports. Human reviews flagged items and approves output.

**Priority:** CRITICAL — this is the core value proposition shift.

**Depends on:** Phase 8 (quality tiers, freshness, gates — the agent needs quality infrastructure to assess its own output).

**Architecture:** Hybrid Plan-and-Execute + Supervisor-Worker. See `docs/AGENTIC_ARCHITECTURE.md`.

### 9.1 Research Brief & Entity Tagging
- [ ] `research_briefs` DB table: project_id, version, question, scope_rules (JSON), entity_budget, amendments (JSON), created_at
- [ ] Research brief created on project creation (from research question + schema)
- [ ] Brief amendment API: `POST /api/projects/<id>/brief/amend` — add scope rules, adjust budget, record rationale
- [ ] Brief versioning: every amendment creates new version, all versions preserved
- [ ] Entity tags: `research_tag` column on `entities` table (enum: core, adjacent, benchmark, peripheral, archived)
- [ ] Tag filtering on all existing entity list/query endpoints
- [ ] Tag-aware lens computation: lenses respect tag filters (core-only by default, toggle to include adjacent)
- [ ] UI: tag selector on entity cards, filter bar in entity browser, tag badges in analysis views
- [ ] **Files:** `core/agent/brief.py` (new), `storage/repos/entities.py` (tag column), `web/blueprints/entities.py` (tag endpoints)
- [ ] **Tests:** brief CRUD, versioning, amendment, tag filtering, lens tag integration

### 9.2 Agent State Machine & Planner
- [ ] Agent states: IDLE → PLANNING → EXECUTING → CHECKPOINT → COMPLETED / FAILED
- [ ] `agent_runs` DB table: id, project_id, brief_version, plan (JSON), state, current_stage, progress (JSON), cost_total, started_at, completed_at
- [ ] Planner: LLM generates multi-stage plan from research brief + project schema + current data state
- [ ] Plan structure: ordered stages, each with type (discover/capture/extract/analyse/report), entity scope, estimated cost
- [ ] Re-planning: on scope amendment, planner generates delta plan (new work only, preserves completed stages)
- [ ] Checkpoint behaviour: agent pauses at configurable points (default: after discovery for entity confirmation)
- [ ] Cost estimation: pre-run estimate based on entity count × pages × model costs (from `docs/AGENTIC_ARCHITECTURE.md` cost model)
- [ ] Budget enforcement: agent pauses when cumulative cost reaches project budget cap
- [ ] API: `POST /api/agent/start` (initiate), `GET /api/agent/status` (poll), `POST /api/agent/approve-checkpoint`, `POST /api/agent/abort`
- [ ] **Files:** `core/agent/planner.py` (new), `core/agent/state.py` (new), `web/blueprints/agent.py` (new)
- [ ] **Tests:** state transitions, plan generation with mocked LLM, re-planning, cost estimation, budget enforcement

### 9.3 Supervisor & Worker Framework
- [ ] Supervisor: dispatches work items to a pool of concurrent workers
- [ ] Worker pool: configurable max concurrency (default 3 — red-team finding #5)
- [ ] Worker types: each wraps an existing Python function (NOT LLM-powered)
  - `CaptureWorker` → calls `capture_website()` / `capture_document()`
  - `ExtractWorker` → calls extraction pipeline
  - `DiscoverWorker` → calls MCP search + entity creation
  - `EnrichWorker` → calls MCP enrichment
  - `AnalyseWorker` → triggers lens computation
  - `ReportWorker` → triggers report generation
- [ ] Per-domain rate limiting: minimum 3s between requests to same domain
- [ ] Progress tracking: supervisor updates `agent_runs.progress` JSON with per-entity status
- [ ] Error handling: worker failure logged, entity marked as failed, supervisor continues with remaining entities
- [ ] Batch DB writes: workers collect results, write in single transaction per entity (red-team finding #9)
- [ ] **Files:** `core/agent/supervisor.py` (new), `core/agent/workers.py` (new)
- [ ] **Tests:** worker dispatch, concurrency limiting, rate limiting, error handling, progress tracking, batch writes

### 9.4 Discovery Workers
- [ ] Input: research brief scope rules + project schema
- [ ] MCP-powered search: DuckDuckGo, Brave, Companies House, FCA register, Wikipedia
- [ ] Query generation from brief: "UK EAP providers" → ["UK employee assistance programme providers", "EAP companies UK", ...]
- [ ] Candidate entity creation with metadata: name, URL, description, source, confidence
- [ ] Deduplication: Dice coefficient name similarity (existing) + URL domain match against current entities
- [ ] Auto-tagging: entities matching core scope rules → `core`, others → `adjacent` or `peripheral`
- [ ] Entity budget enforcement: stop discovery when budget reached
- [ ] Discovery checkpoint: present candidates for user confirmation (default) or auto-accept if matching definitive source (e.g., FCA register)
- [ ] Discovery log: full audit trail — what searched, what found, what proposed, what accepted/rejected
- [ ] **Files:** `core/agent/workers.py` (DiscoverWorker), `core/agent/discovery.py` (new — search + dedup logic)
- [ ] **Tests:** query generation, dedup, auto-tagging, budget enforcement, checkpoint behaviour

### 9.5 Capture Workers & Page Discovery
- [ ] Input: entity with URL + project schema (what attributes to fill)
- [ ] Page discovery per entity:
  - Check standard paths: `/pricing`, `/features`, `/plans`, `/about`, `/help`, `/changelog`, `/blog`, `/resources`, `/contact`
  - Parse `sitemap.xml` if available
  - Follow links from homepage, classify discovered pages by type (reuse extractor classifier)
  - AI page classification: is this page relevant to schema attributes?
- [ ] Capture each relevant page via existing `capture_website()` + `capture_document()`
- [ ] Per-domain rate limiting (3s minimum between requests to same domain)
- [ ] Capture quality check: verify captured page isn't empty/challenge page/cookie wall; retry with different strategy if failed
- [ ] Concurrency: max 3 simultaneous Playwright instances (red-team finding #5)
- [ ] Adaptive wait: DOM stability check rather than fixed timeout
- [ ] **Files:** `core/agent/workers.py` (CaptureWorker), `core/agent/page_discovery.py` (new)
- [ ] **Tests:** page discovery, sitemap parsing, standard path checking, quality validation, rate limiting

### 9.6 Extraction Workers & Smart-Sort Review
- [ ] Input: captured evidence for an entity + project schema
- [ ] Run extraction pipeline on all unextracted evidence (existing `core/extraction.py`)
- [ ] Model tiering: use Haiku for page classification, Sonnet for actual extraction (red-team finding #4)
- [ ] Results feed into review queue with smart-sort (NOT auto-accept — red-team finding #1):
  - Sort by: confidence ASC (ambiguous first), then by source tier DESC (low-quality sources first)
  - High-confidence items at bottom for quick bulk-confirm
  - Low-confidence / contradicted items at top with highlighted ambiguity
- [ ] Extraction completeness report per entity: which schema attributes filled, which still missing, which sources used
- [ ] Quality tier auto-assignment on extracted attributes (based on evidence source tier)
- [ ] **Files:** `core/agent/workers.py` (ExtractWorker), `web/blueprints/extraction.py` (smart-sort endpoint)
- [ ] **Tests:** extraction triggering, smart-sort ordering, completeness reporting, tier assignment

### 9.7 Whitepaper & Document Discovery
- [ ] New extractor: `core/extractors/whitepaper.py` (follows existing extractor pattern)
  - Classification: PDF format, methodology/summary sections, data tables, citations, author credentials
  - Extraction: title, authors, publication_date, executive_summary, key_findings (with page refs), data_points (metric + value + population), methodology, entities_mentioned
- [ ] Entity website document discovery: check `/resources`, `/reports`, `/research`, `/whitepapers`, `/insights`, `/case-studies`
- [ ] Market-wide search: queries derived from research brief, search via MCP (DuckDuckGo, Brave)
- [ ] Source filtering: prioritise government, consultancies, industry bodies, academic journals
- [ ] Citation list extraction: parse references from captured whitepapers, present to user for cherry-picking (NOT auto-following — red-team finding #8)
- [ ] Cross-reference extracted entity mentions against project entities (auto-link)
- [ ] Source tier auto-classification for documents (gov → T1, consultancy → T2, entity's own → T2-3)
- [ ] **Files:** `core/extractors/whitepaper.py` (new), `core/agent/document_discovery.py` (new)
- [ ] **Tests:** whitepaper classification, extraction with mocked LLM, citation parsing, source tier assignment

### 9.8 Market Scan — End-to-End Orchestration
- [ ] `POST /api/agent/market-scan`: combines discovery → capture → extract → analyse → report
- [ ] Planner generates full plan from research brief
- [ ] Stage 1 — Discover: run discovery workers, present candidates at checkpoint
- [ ] Stage 2 — Capture: parallel capture workers for all confirmed entities
- [ ] Stage 3 — Extract: parallel extraction workers, results into smart-sort review queue
- [ ] Stage 4 — Whitepaper: document discovery workers (entity sites + market search)
- [ ] Stage 5 — Analyse: auto-compute all activated lenses
- [ ] Stage 6 — Report: auto-draft standardised reports if quality gates pass
- [ ] Notification: "Your research is ready for review" (in-app, desktop notification if pywebview)
- [ ] Progress UI: real-time stage/entity progress in Research tab
- [ ] Resume capability: if interrupted, agent continues from last completed stage
- [ ] **Files:** `core/agent/market_scan.py` (new), `web/blueprints/agent.py` (scan endpoint + progress), `web/static/js/agent.js` (new)
- [ ] **Tests:** end-to-end flow with mocked workers, checkpoint flow, resume logic, notification

### 9.9 Scope Amendment & Agent Re-Planning
- [ ] User amends research brief mid-scan → agent re-plans
- [ ] Delta planning: only generate new work for amended scope, preserve completed work
- [ ] Agent-proposed scope expansion: during capture, agent detects references to out-of-scope entities
  - Proposes with evidence: "Found 3 mentions of Thanksben in captured pages. Add as adjacent?"
  - Shows cumulative cost of adding (red-team finding #3)
  - User confirms → entities created, queued for capture in current run
- [ ] Schema adaptation: if new entities have unmapped attributes, propose schema amendment via existing `POST /api/entity-types/sync`
- [ ] Entity budget enforcement on all expansion paths
- [ ] **Files:** `core/agent/planner.py` (re-plan logic), `core/agent/scope.py` (new — expansion detection + proposal)
- [ ] **Tests:** delta planning, scope proposal, budget enforcement, schema adaptation

### 9.10 Scheduled Automation
- [ ] Scheduled re-capture: configurable interval (weekly/monthly) per project
- [ ] Freshness-driven: only re-capture entities with attributes below freshness threshold
- [ ] Change detection: content hash diff against previous capture → re-extract only if changed
- [ ] Incremental cost: only process changed entities (~$5-15 vs $60 full scan)
- [ ] Digest generation: periodic summary as HTML file (same format as reports)
- [ ] Schedule storage: `agent_schedules` DB table (project_id, interval, last_run, next_run, config)
- [ ] Desktop notification on schedule completion (pywebview)
- [ ] **Files:** `core/agent/scheduler.py` (new), `web/blueprints/agent.py` (schedule endpoints)
- [ ] **Tests:** schedule CRUD, freshness-driven selection, change detection, incremental processing

### 9.11 Project Duplication
- [ ] `POST /api/projects/<id>/duplicate`: deep copy project for divergent research directions
- [ ] Copy: project metadata, schema, research brief, entities, attributes, extraction results (accepted only), hypotheses, canonical features
- [ ] Evidence records: copy DB rows referencing same physical files (no disk duplication)
- [ ] Reference counting: `evidence_file_refs` table tracks file_path → count; only delete from disk when count reaches 0
- [ ] Does NOT copy: monitors, pending review queue, reports, agent state (fresh start)
- [ ] User provides: new project name, optional amended research brief
- [ ] No lineage tracking (simple duplication, not forking — red-team finding #7)
- [ ] **Files:** `web/blueprints/entities.py` (duplicate endpoint), `storage/repos/entities.py` (deep copy logic), `core/capture.py` (ref counting)
- [ ] **Tests:** full duplication, evidence ref counting, schema independence, data isolation

---

## ⚑ SHIP & LEARN CHECKPOINT

> **After completing Phase 8 + 9:** Run the agent against a real research project (UK EAP market scan).
> Document: what worked, what broke, what was unnecessary, what was missing.
> Phases 10-14 below are planned but explicitly contingent on learnings from real usage.
> Update this plan based on empirical findings before proceeding.

---

## Phase 10: Conversational Research Interface

**Goal:** Query project data in natural language. "Ask your research" without SQL knowledge.

**Priority:** HIGH — the "10x solo analyst" capability.

**Depends on:** Phase 8 (quality indicators in query responses).

### 10.1 NL2SQL Query Interface
- [ ] Chat-like interface in Research tab
- [ ] User types natural language → system translates to SQL against entity/attribute schema
- [ ] Results returned with source citations per data point
- [ ] Generated SQL shown (collapsible) for transparency
- [ ] **Grounded responses only:** system answers ONLY from project data, never general LLM knowledge
- [ ] Missing data surfaced: "I don't have data on X for 12 of 28 entities"
- [ ] Unverified data flagged: "This answer uses 3 AI-extracted values that haven't been reviewed"
- [ ] Pre-built question templates per lens (competitive, product, temporal, signals)
- [ ] Follow-up context within session
- [ ] **Tests:** query translation, grounding enforcement, missing data detection, template questions

### 10.2 Smart Research Assistant
- [ ] "What should I research next?" — analyses completeness gaps, suggests highest-impact targets
- [ ] Analysis readiness suggestions: "You now have enough data for a Competitive Landscape report"
- [ ] Methodology guidance for active playbook runs
- [ ] All suggestions grounded in specific data state
- [ ] **Tests:** suggestion generation, completeness analysis, playbook integration

### 10.3 Project Briefing
- [ ] One-click "brief me on this project" — template-driven status report
- [ ] Summarises: entity count, data completeness, recent changes, pending review, quality status
- [ ] **Template-driven with SQL data fill — NOT generative prose** (zero hallucination risk)
- [ ] Optional "morning briefing" on project open
- [ ] Exportable as single-page HTML
- [ ] **Tests:** briefing generation, data fill accuracy, export

---

## Phase 11: Advanced Visualisation & Analysis

**Goal:** Publication-quality outputs for C-suite / board consumption.

**Priority:** HIGH — sets the bar for output quality alongside Flourish/Datawrapper.

**Depends on:** Existing lenses (Phase 4 complete), Phase 8 (quality indicators on charts).

### 11.1 Market Positioning Maps (Enhanced)
- [ ] Magic Quadrant style: 2×2 matrix with labelled quadrants, configurable labels
- [ ] Bubble chart: third dimension as bubble size (pricing, funding, employee count)
- [ ] Radar/Spider chart: multi-attribute comparison for selected entities (5-8 dimensions)
- [ ] All charts: interactive (hover/click), exportable as SVG/PNG, quality indicators per data point
- [ ] Data quality filter: show Tier 3+ by default, toggle to include lower tiers

### 11.2 Interactive HTML Reports
- [ ] Embedded charts render as interactive SVG/JS within export
- [ ] Filtering, drill-down, evidence viewer inline
- [ ] Self-contained single HTML file, works offline
- [ ] Trust indicators on every data point (provenance tier visible to readers)

### 11.3 Market Structure Detection
- [ ] Clustering on entity attributes to discover natural market segments
- [ ] AI-proposed segment names
- [ ] Quality guard: exclude Tier 5 and entities with <50% attribute completeness

---

## Phase 12: Workflow & Methodology Depth

**Goal:** Research rigour, repeatability, domain expertise.

**Priority:** MEDIUM.

**Depends on:** Phase 9 (agent runs playbook steps), Phase 8 (quality thresholds per playbook).

### 12.1 Domain-Specific Playbook Packs
- [ ] UK Insurance: schema, expected sources (FCA, IPIDs), quality expectations, extractor config, step sequence
- [ ] Fintech / Digital Banking: schema, sources (app stores, FCA/PRA, Crunchbase), quality thresholds
- [ ] Design Research: graph schema, gallery sources, screenshot requirements
- [ ] SaaS Competitive Analysis: schema, sources (G2, pricing pages, changelogs), quality thresholds
- [ ] Each pack: schema template, playbook steps, recommended MCP servers, quality thresholds, freshness half-life overrides

### 12.2 Research Completeness Guidance
- [ ] Per-playbook-step completeness tracker with progress bars
- [ ] Smart prioritisation: "These 5 entities would increase quality score most"
- [ ] Methodology warnings: block/watermark reports below playbook thresholds

### 12.3 Evidence Annotation
- [ ] Screenshot annotation: draw rectangles/arrows/text, link to entity attributes
- [ ] Document annotation: highlight text passages, link to attributes
- [ ] Annotations stored as JSON overlay, original evidence preserved
- [ ] Auto-promotes source tier from T4 to T2 when human-annotated

### 12.4 Project Duplication UI
- [ ] "Duplicate Project" modal with options (what to include, new name, amended brief)
- [ ] Fork relationships shown in project list
- [ ] One-click "View original" navigation

### 12.5 External Tool Imports
- [ ] Enhanced CSV/Excel: column mapping wizard with AI-assisted matching
- [ ] JSON/API import: define mapping schema, import from URL or file
- [ ] Imported data defaults to Tier 3 with "import" source tag

---

## Phase 13: Distribution & Stakeholder Access

**Goal:** Get research to stakeholders without them needing the app.

**Priority:** MEDIUM.

**Depends on:** Phase 11 (interactive reports).

### 13.1 Stakeholder Read-Only Bundles
- [ ] Export entire project as self-contained HTML bundle (data + UI + evidence thumbnails)
- [ ] Opens in any browser, no server needed
- [ ] Quality score and methodology section prominently displayed

### 13.2 Notification System
- [ ] In-app notification centre (bell icon, badge count)
- [ ] Notifications: monitoring alerts, agent checkpoints, schedule completions, quality threshold breaches
- [ ] Desktop notifications via pywebview (macOS native)

### 13.3 REST API
- [ ] Read-only API endpoints for external tool integration
- [ ] Simple API key auth configured in Settings
- [ ] OpenAPI spec auto-generated from Flask routes

---

## Phase 14: Platform Maturity & Scale

**Goal:** Performance at scale, extensibility, data portability.

**Priority:** LOW-MEDIUM.

### 14.1 Performance Optimisation
- [ ] Virtual scrolling for 500+ entity lists
- [ ] Lazy lens computation (on-demand, not on tab switch)
- [ ] Evidence thumbnail pre-generation

### 14.2 Keyboard-Driven Research
- [ ] Command palette: all actions via Cmd+K
- [ ] Review queue shortcuts: a/r/e for accept/reject/edit
- [ ] Vim-style navigation (optional)

### 14.3 Backup & Data Portability
- [ ] One-click project backup as zip (SQLite + evidence files + reports)
- [ ] Scheduled auto-backup
- [ ] Project import from backup zip

### 14.4 Plugin Architecture
- [ ] Custom extractors: drop Python modules into `extractors/`, auto-discovered
- [ ] Custom MCP servers: formalised `mcp-servers/` convention
- [ ] Custom report templates: Jinja2 in `report-templates/`
- [ ] Custom source tier rules per project

### 14.5 Semantic Search
- [ ] Local embeddings via Ollama + nomic-embed-text
- [ ] sqlite-vss for vector similarity
- [ ] Meaning-based search across all project data (not keyword)
- [ ] Privacy: all embeddings computed and stored locally

---

## Session Planning

### Phase 8 (Data Quality) — ~4 sessions
| Session | Scope | Estimated tests |
|---------|-------|-----------------|
| 32 | 8.1 Source tier system + 8.2 Freshness decay model | ~40 |
| 33 | 8.3 Quality dashboard (3 dimensions, entity cards, heatmap) | ~30 |
| 34 | 8.4 Quality gates + 8.5 Multimodal screenshot extraction | ~45 |
| 35 | 8.6 Cross-source validation + contradiction dashboard | ~35 |

### Phase 9 (Agentic Core) — ~5 sessions
| Session | Scope | Estimated tests |
|---------|-------|-----------------|
| 36 | 9.1 Research brief + entity tagging + 9.2 Agent state machine + planner | ~50 |
| 37 | 9.3 Supervisor/worker framework + 9.4 Discovery workers | ~45 |
| 38 | 9.5 Capture workers + page discovery + 9.6 Extraction workers + smart-sort | ~45 |
| 39 | 9.7 Whitepaper discovery + 9.8 Market scan end-to-end | ~40 |
| 40 | 9.9 Scope amendment + 9.10 Scheduled automation + 9.11 Project duplication | ~45 |

### ⚑ Ship & Learn Checkpoint (after Session 40)
Run against real project. Document findings. Update plan.

### Phases 10-14 — ~8 sessions (contingent on checkpoint learnings)
| Session | Scope |
|---------|-------|
| 41 | 10.1 NL2SQL query interface |
| 42 | 10.2-10.3 Smart assistant + project briefing |
| 43 | 11.1 Advanced charts (Magic Quadrant, bubble, radar) |
| 44 | 11.2 Interactive HTML reports |
| 45 | 12.1-12.2 Domain playbook packs + completeness guidance |
| 46 | 12.3-12.5 Annotation + duplication UI + imports |
| 47 | 13.1-13.3 Sharing + notifications + REST API |
| 48 | 14.1-14.5 Performance + keyboard + backup + plugins + search |

**Estimated total: ~17 sessions** for full roadmap, with a mandatory checkpoint after 9.

---

## Technical Decisions (V2)

### Agent Architecture
- **Hybrid Plan-and-Execute + Supervisor-Worker** — see `docs/AGENTIC_ARCHITECTURE.md`
- LLM for planning only; workers are plain Python functions wrapping existing infrastructure
- Max 3 concurrent Playwright workers; per-domain 3s rate limiting
- All new agent code in `core/agent/` package (planner.py, supervisor.py, workers.py, state.py, brief.py, etc.)

### Cost Management
- **Model tiering:** Haiku for classification (~$0.01/call), Sonnet for extraction (~$0.08/call)
- Pre-run cost estimates surfaced to user before every agent run
- Project budget caps enforced at agent level (pauses, doesn't crash)
- Existing `llm_calls` + `project_budgets` tables used for tracking

### Quality Architecture
- All quality logic in `core/quality.py` (new module)
- Quality blueprint: `web/blueprints/quality.py` (new)
- Source tier stored per-attribute (column on `entity_attributes`)
- Freshness computed on read (no stored column — always current from `captured_at`)
- Three dimensions always shown separately, never composited

### Database
- Stay with SQLite WAL — batch writes per worker mitigate concurrent write pressure
- New tables: `research_briefs`, `agent_runs`, `agent_schedules`, `evidence_file_refs`
- New columns: `entity_attributes.source_tier`, `entities.research_tag`
- All migrations non-destructive (add columns, add tables — never remove)

### Frontend
- Stay with vanilla JS + esbuild bundling
- New modules: `agent.js` (agent UI), `quality.js` (quality dashboard)
- Agent progress: polling-based (existing pattern), consider SSE if polling proves insufficient

---

## Risk Register

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| LLM confidence unreliable | CRITICAL | Smart-sort review, no auto-accept until calibrated | Designed |
| Cost blowout on large scans | CRITICAL | Pre-run estimates, budget caps, model tiering | Designed |
| Playwright failures at scale | HIGH | 3 worker limit, rate limiting, quality checks | Designed |
| Scope creep via agent proposals | HIGH | Entity budgets, explicit amendments, cost display | Designed |
| Quality score false precision | HIGH | Three separate bars, no composite | Designed |
| 18-month scope | HIGH | Ship after Phase 8+9, checkpoint, iterate | Planned |
| Configuration overload | MEDIUM-HIGH | Sensible defaults, progressive disclosure, playbook packs | Designed |
| SQLite write contention | MEDIUM | Batch writes, WAL mode, acceptable at <200 entities | Accepted |

---

## Document Map

| Document | Purpose | When to consult |
|----------|---------|----------------|
| `IMPLEMENTATION_PLAN.md` | V1 plan (Phases 1-7 + MCP + Audit, all complete) | Understanding what's built |
| `IMPLEMENTATION_PLAN_V2.md` | This file — V2 plan (Phases 8-14, agentic) | Guiding implementation |
| `FEATURE_ROADMAP.md` | Full vision (Phases 8-14 in detail) | Understanding the complete scope |
| `docs/AGENTIC_ARCHITECTURE.md` | Architecture decisions + rejected alternatives | Understanding WHY a pattern was chosen |
| `docs/RED_TEAM_FINDINGS.md` | 10 critical findings that shaped this plan | Understanding constraints and risks |
| `docs/COMPETITIVE_LANDSCAPE_2026.md` | Market research (30+ tools, 7 categories) | Understanding competitive positioning |
| `docs/RESEARCH_WORKBENCH_VISION.md` | Original vision + design principles | Understanding the foundational "why" |
| `docs/RESEARCH_WORKBENCH_CONVERSATION.md` | Session 10 brainstorm transcript | Understanding original design reasoning |

---

## Session Log

| Session | Date | Work Done | Status |
|---|---|---|---|
| 30 | 2026-02-21 | Competitive landscape research, feature roadmap, agentic architecture discussion, red-team analysis, V2 implementation plan creation. Created: `FEATURE_ROADMAP.md`, `docs/COMPETITIVE_LANDSCAPE_2026.md`, `docs/AGENTIC_ARCHITECTURE.md`, `docs/RED_TEAM_FINDINGS.md`, `IMPLEMENTATION_PLAN_V2.md` | ✅ Complete |

---

## Notes for Future Sessions

- **Always read `IMPLEMENTATION_PLAN_V2.md` first** before starting work on Phases 8+
- **Read `IMPLEMENTATION_PLAN.md`** if you need to understand existing infrastructure
- **Update the Session Log** at the end of every session
- **Update task checkboxes** as items are completed
- **Consult `docs/RED_TEAM_FINDINGS.md`** when making design decisions — the mitigations are deliberate
- **Consult `docs/AGENTIC_ARCHITECTURE.md`** for architecture rationale
- **After the Ship & Learn checkpoint (Session 40):** update this plan with empirical findings before proceeding to Phase 10+
