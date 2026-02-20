# Research Workbench — Implementation Plan

> **Status:** Phase 1 Complete — Full Entity System + Browser + View Compatibility
> **Created:** 2026-02-20 (Session 10)
> **Last Updated:** 2026-02-20 (Session 12)
> **Vision Doc:** `docs/RESEARCH_WORKBENCH_VISION.md`
> **Conversation Reference:** `docs/RESEARCH_WORKBENCH_CONVERSATION.md`

---

## Overview

Evolving the Research Taxonomy Library from a flat company taxonomy tool into a **personal research workbench** for structured market and product intelligence. The app should let a solo analyst conduct research at a depth that normally requires a team — competing not on data volume (like IDC/Mintel) but on **structure, methodology, and living evidence**.

**Core principle:** Evolve, don't rebuild. The existing Flask/pywebview app, design system, Excalidraw canvas, graph views, maps, AI integration, and tests are preserved. The data layer transforms underneath; the UI evolves progressively on top.

**Testing principle:** The comprehensive test suite is simultaneously updated with every implementation step. Every new feature gets both DB-layer and API-layer tests. All existing tests must continue to pass. Test count grows in lockstep with implementation.

---

## Current State (Built to Date — Sessions 1-9)

### Architecture
- **Backend:** Flask + Blueprints, Python 3.14, SQLite storage
- **Desktop:** pywebview (WebKit on macOS), `desktop.py` with dynamic port
- **Frontend:** Single-page HTML (`index.html`), vanilla JS, CSS design system ("The Instrument")
- **AI:** Claude CLI integration via `core/llm.py` with structured output support

### Working Features
| Feature | Status | Key Files |
|---|---|---|
| Project selection/management | ✅ Working | `projects.js`, blueprints |
| Company CRUD (add, edit, delete) | ✅ Working | `companies.js`, blueprints |
| AI Discovery (find companies via AI) | ✅ Working | `ai.js`, `ai.py` |
| Link-based URL scraping | ✅ Working | `ai.py` |
| Deep Research (AI enrichment) | ✅ Working | `ai.py`, `llm.py` |
| CSV Import/Export | ✅ Working | blueprints |
| Taxonomy Matrix | ✅ Working | `index.html` |
| Graph View (Cytoscape) | ✅ Working | `taxonomy.js` |
| Knowledge Graph (Cytoscape) | ✅ Working | `taxonomy.js` |
| Geographic Map (Leaflet) | ✅ Working | `maps.js` |
| Canvas (Excalidraw 0.18.0) | ✅ Working | `canvas.js` |
| AI Diagram Generation | ✅ Working | `diagram.js`, `canvas.py` |
| Tags, Categories, Relationships | ✅ Working | `companies.js`, blueprints |
| Bulk Actions | ✅ Working | `companies.js` |
| Design System (The Instrument) | ✅ Working | `base.css` + 12 CSS files |
| Tippy.js Tooltips | ✅ Working | `core.js` |
| Custom Prompt/Select Dialogs | ✅ Working | `core.js` |
| 401 pytest tests | ✅ Passing | 16 test files |
| 132 Playwright specs | ✅ Written | 24 spec files |
| Entity schema system | ✅ Working | `core/schema.py` |
| Entity CRUD + temporal attrs | ✅ Working | `storage/repos/entities.py` |
| Entity API (23 endpoints) | ✅ Working | `web/blueprints/entities.py` |

### Current Data Model (Flat)
```
Project
  └── Company (name, description, website, tags, category, relationships, location, metadata)
```
No product hierarchy. No temporal versioning. No evidence storage. No schema flexibility.

### Known Limitations
- Company is the only entity type — no products, plans, features
- No point-in-time snapshots — edits overwrite previous data
- No structured feature data — just free-text descriptions
- No screenshot/evidence storage
- Fixed tab navigation — all projects see the same views
- AI Discovery finds companies but doesn't populate sub-entities
- No reporting capability
- No monitoring/change detection

---

## Phase Breakdown

### Phase 1: Research Foundation (Data Model + Schema System)
**Goal:** Transform the flat company model into a flexible, hierarchical entity system with temporal awareness.

**Priority:** CRITICAL — everything else depends on this.

#### 1.1 Schema System
- [x] Design schema definition format (JSON-based, stored per project)
- [x] Schema defines: entity types, hierarchy relationships, attributes per type, attribute types (text, number, boolean, currency, enum, url, date, json, image_ref, tags)
- [x] Support both tree hierarchies (Company → Product → Plan → Tier → Feature) AND graph relationships (Product ↔ Design Principle)
- [x] Built-in templates: Market Analysis, Product Analysis, Design Research, blank
- [x] Schema stored in project metadata (`entity_schema` JSON field) + `entity_type_defs` table for query efficiency
- [x] Schema amendment API (add/modify entity types and attributes mid-project) — `POST /api/entity-types/sync`
- [x] Schema validation + normalization (slug generation, defaults, duplicate detection)
- [x] **Files:** `core/schema.py` (350+ lines), `web/blueprints/entities.py` (schema endpoints)
- [x] **Tests:** 10 schema validation + 4 normalization + 10 helper tests (DB), 4 schema template + 4 validation + 7 type API tests

#### 1.2 Entity Data Model
- [x] New database tables: `entity_type_defs`, `entity_relationship_defs`, `entities`, `entity_attributes`, `entity_relationships`, `entity_snapshots`, `evidence` (7 tables, 16 indexes)
- [x] Entity table: id, project_id, type_slug, name, slug, parent_entity_id, category_id, is_starred, is_deleted, status, confidence_score, tags, raw_research, source, created_at, updated_at
- [x] Attribute table: entity_id, attr_slug, value, source, confidence, captured_at, snapshot_id
- [x] Relationship table: from_entity_id, to_entity_id, relationship_type, metadata_json, UNIQUE constraint
- [x] Non-destructive migration: `_migrate_phase7_entities()` adds `entity_schema` to existing projects
- [ ] Migration path: existing companies become entities of type "Company" — zero data loss (deferred to Phase 1.8)
- [x] **Files:** `storage/schema.sql` (7 tables), `storage/repos/entities.py` (EntityMixin, 400+ lines), `storage/db.py` (migration + schema support)
- [x] **Tests:** 10 CRUD + 3 type def + 1 hierarchy tests (DB), 6 create + 9 read + 4 update + 6 delete API tests

#### 1.3 Temporal Versioning
- [x] Every attribute value is timestamped (`captured_at`)
- [x] Current value = most recent capture for that attribute (MAX(id) per attr_slug)
- [x] Historical values preserved — `GET /api/entities/<id>/attributes/<slug>/history`
- [x] Point-in-time query — `GET /api/entities/<id>/attributes/at?date=...`
- [x] Snapshot grouping: `entity_snapshots` table, `snapshot_id` FK on attributes
- [x] Confidence scoring per attribute value (0-1)
- [x] Source tracking per value (manual, ai, import, scrape)
- [x] **Files:** `storage/repos/entities.py` (temporal methods), `web/blueprints/entities.py` (temporal endpoints)
- [x] **Tests:** 7 temporal attribute tests (DB), 9 attribute API tests + 5 snapshot API tests

#### 1.4 Evidence Library
- [x] Database table: `evidence` (id, entity_id, evidence_type, file_path, source_url, source_name, metadata_json, captured_at)
- [x] Evidence linked to entities at any schema level
- [x] Evidence CRUD: add, list (with type/source filters), delete
- [x] Evidence count displayed on entity cards
- [ ] File storage engine (actual file write/read to `evidence/` directory) — deferred to Phase 2
- [x] **Files:** `storage/repos/entities.py` (evidence methods), `web/blueprints/entities.py` (evidence endpoints)
- [x] **Tests:** 5 evidence tests (DB), 8 evidence API tests

#### 1.5 API Layer Update
- [x] Full entity CRUD endpoints (alongside existing company endpoints)
- [x] Entity endpoints return attributes, child_count, evidence_count, type metadata
- [x] Schema template listing, validation, type sync, hierarchy endpoints
- [x] Relationship CRUD endpoints (create, list with direction filter, delete)
- [x] Evidence CRUD endpoints
- [x] Snapshot CRUD endpoints
- [x] Entity stats endpoint
- [x] Blueprint registered in `web/app.py`
- [ ] Backwards-compatible company API wrapper (existing company routes delegate to entity API) — deferred to Phase 1.8
- [x] **Files:** `web/blueprints/entities.py` (300+ lines, 23 endpoints), `web/app.py` (blueprint registration)
- [x] **Tests:** 73 API tests in `tests/test_api_entities.py` (including 2 full workflow integration tests)

#### 1.6 Project Setup Flow (AI-Guided Interview)
- [x] New project creation flow with template selection
- [x] AI proposes schema based on research question description (`POST /api/schema/suggest`)
- [ ] Back-and-forth refinement (AI challenges user choices) — deferred to Phase 2+
- [x] Template selection as starting point (or blank) — 4 templates: blank, market_analysis, product_analysis, design_research
- [x] Schema preview panel in project creation form
- [x] "Quick create" option bypasses interview (blank Company schema, same as current)
- [x] All projects now get `entity_schema` on creation (default: blank company schema)
- [x] Custom schema validation + normalization on project create
- [x] **Files:** `web/app.py` (enhanced create_project), `web/static/js/projects.js` (template picker + AI suggest), `web/blueprints/entities.py` (suggest endpoint), `web/templates/index.html` (form), `web/static/layout.css` (template picker CSS)
- [x] **Tests:** 10 project template tests + 3 AI suggest tests (in `test_api_entities.py`)

#### 1.7 Entity Browser UI
- [x] Entity browser activates for multi-type schemas (single-type stays on company view)
- [x] Drill-down navigation: click entity → see its children → breadcrumb back
- [x] Breadcrumb navigation for hierarchy depth
- [x] Entity table with schema-driven columns (first 5 attributes + child count + evidence count)
- [x] Entity detail panel with full attribute display + source metadata
- [x] Create/edit entity modals with schema-driven form fields (all data types: text, number, boolean, enum, url, date, currency, tags)
- [x] Search across entity names
- [x] Bulk operations: star, unstar, delete (via `POST /api/entities/bulk`)
- [x] Entity type selector bar with count badges
- [x] **Files:** `web/static/js/entities.js` (new, 500+ lines), `web/templates/index.html` (entity browser section + companyViewWrapper), `web/static/layout.css` (entity browser CSS)
- [x] **Tests:** 12 entity browser query tests + 10 bulk operation tests (in `test_api_entities.py`)

#### 1.8 Existing View Compatibility
- [x] Entity graph endpoint (`GET /api/entity-graph`) returns nodes + edges for KG views (hierarchy + explicit relationships)
- [x] Entity locations endpoint (`GET /api/entity-locations`) returns entities with location data for map views
- [x] Stats bar shows entity type counts for schema-aware projects
- [x] All projects now get entity_schema on creation — backwards compatible
- [ ] Taxonomy matrix enhanced to show entities in category detail — deferred (categories work now, entity integration in Phase 2)
- [ ] AI Discovery enhanced to populate sub-entities — deferred to Phase 2
- [x] Canvas unchanged (still freeform) ✓
- [x] **Files:** `web/blueprints/entities.py` (graph + location endpoints), `web/static/js/core.js` (entity stats in header)
- [x] **Tests:** 6 graph view tests + 5 location tests + 2 schema retrieval tests (in `test_api_entities.py`)

#### 1.9 Tests — Simultaneous Test Development
> **Rule:** Every implementation step must include corresponding tests. Test suite grows in lockstep with features. All previous tests must continue to pass.

- [x] All 266 original tests still pass after entity system addition
- [x] DB-layer tests: 62 tests in `tests/test_entities.py` (schema, entity CRUD, temporal, relationships, evidence, snapshots, hierarchy)
- [x] API-layer tests: 119 tests in `tests/test_api_entities.py` (all endpoints, validation, error cases, workflows, template creation, bulk ops, graph, locations)
- [x] Integration tests: full product analysis workflow (5-level hierarchy) and design research workflow (many-to-many)
- [x] `entities` marker added to `pytest.ini` for selective running (`pytest -m entities`)
- [x] **Total: 447 tests passing** (266 original + 62 entity DB + 119 entity API)
- [x] Phase 1.6 tests: 10 project template + 3 AI suggest tests
- [x] Phase 1.7 tests: 12 entity browser query + 10 bulk operation tests
- [x] Phase 1.8 tests: 6 graph view + 5 location + 2 schema retrieval tests
- [ ] E2E Playwright tests for entity browser UI (Phase 2+)
- [ ] E2E tests for project setup flow (Phase 2+)
- [ ] Migration tests: verify company→entity data integrity (Phase 2+)

---

### Phase 2: Capture Engine
**Goal:** Automated and manual evidence collection from web sources.

**Depends on:** Phase 1 (evidence library, entity model)

#### 2.1 Headless Website Capture
- [x] Playwright-based backend service for full-page screenshots + HTML archival
- [x] Input: URL + entity to link to
- [x] Output: screenshot (PNG) + HTML snapshot stored in evidence library
- [x] Support for: marketing pages, pricing pages, help docs, changelogs
- [x] Configurable viewport, full-page vs viewport-only, optional HTML archival
- [x] Async capture support (background jobs with polling)
- [x] **Files:** `core/capture.py` (400+ lines), `web/blueprints/capture.py` (300+ lines)
- [x] **Tests:** 6 website capture API tests (mocked Playwright) in `test_api_capture.py`

#### 2.2 UI Gallery Scrapers
- [ ] Mobbin scraper: find app by name, download all available screenshots
- [ ] Screenlane scraper: same pattern
- [ ] Refero scraper: same pattern
- [ ] Appshots / Scrnshts / Dribbble: as needed
- [ ] Rate limiting and polite scraping (delays, user-agent, robots.txt respect)
- [ ] Results land in evidence library, linked to product entity
- [ ] **Files affected:** New `core/scrapers/` directory with per-source modules

#### 2.3 App Store Scraper
- [ ] Apple App Store: screenshots, description, rating, version history (via iTunes Search API)
- [ ] Google Play Store: screenshots, description, rating (scraping, no official API)
- [ ] Auto-link to product entity
- [ ] **Files affected:** `core/scrapers/appstore.py`, `core/scrapers/playstore.py`

#### 2.4 Document Capture
- [x] Download and store PDFs (IPIDs, regulatory docs, whitepapers)
- [x] Download and store HTML help documentation pages
- [ ] Changelog page capture with diff detection for future visits
- [x] **Files:** `core/capture.py` (capture_document function), `web/blueprints/capture.py` (document endpoint)
- [x] **Tests:** 6 document capture tests (mocked HTTP) in `test_capture.py`, 5 API tests in `test_api_capture.py`

#### 2.5 Manual Evidence Upload
- [x] API for uploading screenshots, documents, files directly (`POST /api/evidence/upload`)
- [x] File validation (extension whitelist, size limit 50MB, empty file check)
- [x] Evidence type auto-detection from file extension
- [x] Evidence file serving (`GET /api/evidence/<id>/file`)
- [x] Evidence file + record deletion (`DELETE /api/evidence/<id>/file`)
- [x] Evidence storage stats per project (`GET /api/evidence/stats`)
- [ ] Drag-and-drop onto entity cards (frontend) — deferred to 2.7
- [ ] Paste from clipboard (screenshot capture while using a product) — deferred to 2.7
- [x] **Files:** `core/capture.py` (store_upload, validate_upload), `web/blueprints/capture.py` (upload/serve/delete/stats)
- [x] **Tests:** 7 upload tests + 7 serve/delete tests + 3 stats tests + 1 integration test in `test_api_capture.py`; 7 store_upload tests in `test_capture.py`

#### 2.5a File Storage Engine
- [x] Evidence directory structure: `{DATA_DIR}/evidence/{project_id}/{entity_id}/{evidence_type}/{filename}`
- [x] Unique filename generation (timestamp + hash suffix)
- [x] File store, delete, exists, size utilities
- [x] Upload validation (extension whitelist, size limit, empty check)
- [x] Evidence type guessing from file extension
- [x] MIME type detection for serving
- [x] Empty directory cleanup on file deletion
- [x] `get_evidence_by_id` DB method added to `storage/repos/entities.py`
- [x] Upload limit increased to 50MB in Flask config
- [x] **Files:** `core/capture.py`, `storage/repos/entities.py` (new method), `web/app.py` (upload limit + blueprint)
- [x] **Tests:** 11 file storage tests + 6 validation tests + 7 type/MIME tests + 4 utility tests in `test_capture.py`

#### 2.6 Bulk Capture / Market Scan
- [ ] "Scan market" action: combine AI Discovery + scraping for all found companies
- [ ] Runs as background job with progress tracking
- [ ] Results flagged as "AI-populated, pending review"
- [ ] **Files affected:** `web/blueprints/capture.py`, `core/capture.py`, background job system

#### 2.7 Capture UI
- [ ] "Research Operations" section in AI Discovery tab (or new Capture tab)
- [ ] Shows active/completed scraping jobs
- [ ] Configure capture sources per project
- [ ] Manual capture trigger per entity
- [ ] Drag-and-drop upload onto entity cards
- [ ] Clipboard paste for screenshots
- [ ] **Files affected:** `ai.js` or new `capture.js`, `index.html`

#### 2.8 Tests — Capture Engine
- [x] DB-layer tests: 64 tests in `tests/test_capture.py` (file storage, validation, upload, document capture, evidence by ID)
- [x] API-layer tests: 31 tests in `tests/test_api_capture.py` (upload, serve, delete, document capture, website capture, stats, jobs, integration)
- [x] `capture` marker added to `pytest.ini` for selective running (`pytest -m capture`)
- [x] All 447 original tests still pass after capture engine addition
- [x] **Total: 542 tests passing** (447 original + 64 capture DB + 31 capture API)

---

### Phase 3: Extraction & Structuring
**Goal:** AI-powered extraction of structured data from captured evidence, with human validation.

**Depends on:** Phase 1 (schema, entities), Phase 2 (evidence library populated)

#### 3.1 Feature Extraction Pipeline
- [ ] AI analyses captured evidence (web pages, documents, screenshots) against project schema
- [ ] Extracts structured attribute values for entities
- [ ] Cross-references multiple sources for the same entity
- [ ] Flags contradictions between sources
- [ ] Confidence scoring: high / medium / needs-review
- [ ] **Files affected:** New `core/extraction.py`, `core/llm.py` (extended)

#### 3.2 Document-Specific Extractors
- [ ] IPID parser (standardised EU/UK insurance document format)
- [ ] Generic product page extractor (features, pricing, plans)
- [ ] Help documentation extractor (feature lists, capabilities)
- [ ] Changelog parser (new features, changes, dates)
- [ ] Extensible: add new document type extractors as needed
- [ ] **Files affected:** New `core/extractors/` directory

#### 3.3 Screenshot Classification
- [ ] AI classifies captured screenshots by journey stage (onboarding, dashboard, settings, checkout, etc.)
- [ ] Identifies UI patterns and design principles present
- [ ] Groups screens into likely sequences
- [ ] **Files affected:** `core/extraction.py`, `core/llm.py`

#### 3.4 Human Review Interface
- [ ] Queue of AI-extracted data pending review
- [ ] Per-entity review: see extracted attributes, source evidence side-by-side
- [ ] Accept / edit / reject per attribute
- [ ] Confidence indicators (AI certainty + source reliability)
- [ ] "Needs more evidence" flag → directs further capture
- [ ] **Files affected:** New frontend component, new blueprint endpoint

#### 3.5 Feature Standardisation
- [ ] Per-project canonical feature vocabulary
- [ ] AI proposes standard names when extracting (maps "mental health cover" and "mental health support" to same canonical feature)
- [ ] User confirms or creates new canonical features
- [ ] Enables cross-company comparison on the same feature dimension
- [ ] **Files affected:** Schema extension for canonical vocabularies

---

### Phase 4: Analysis Lenses
**Goal:** Analysis views that activate based on available structured data.

**Depends on:** Phase 1 (entity model), Phase 3 (structured data populated — though can work with manual data from Phase 1)

#### 4.1 Lens Framework
- [ ] Lens system: each lens has activation criteria (what data must exist)
- [ ] Lenses show as available/unavailable in navigation based on project data
- [ ] Unavailable lenses show hint: "Capture UI screenshots to activate the Design lens"
- [ ] **Files affected:** `core.js` (navigation), new `web/static/js/lenses.js`

#### 4.2 Competitive Lens
- [ ] Feature comparison matrix: entities × features grid
- [ ] Gap analysis: features offered by few/no companies
- [ ] Positioning map: 2D scatter on user-chosen attributes
- [ ] **Activation:** 2+ entities with comparable feature data

#### 4.3 Product Lens
- [ ] Plan/tier comparison across companies
- [ ] Pricing landscape (headline prices across tiers/companies)
- [ ] Feature depth view (which companies go deepest on which features)
- [ ] **Activation:** 2+ entities with plan/tier/feature data

#### 4.4 Design Lens
- [ ] Evidence gallery per entity (all captured screenshots)
- [ ] Journey map viewer (ordered screen sequences)
- [ ] Pattern library (design principles extracted from captures)
- [ ] UX scoring / comparison
- [ ] **Activation:** Entities with classified UI captures

#### 4.5 Temporal Lens
- [ ] Side-by-side screenshot comparison (point A vs point B)
- [ ] Attribute change timeline per entity
- [ ] Market-level change summary (what shifted across all entities)
- [ ] **Activation:** 2+ capture snapshots for any entity

#### 4.6 Signals Lens
- [ ] News/announcement feed for tracked entities
- [ ] Funding round timeline
- [ ] Product launch/update timeline
- [ ] Market trend indicators
- [ ] **Activation:** Monitoring configured (Phase 5)

#### 4.7 Existing Lenses (already built, enhanced)
- [ ] Taxonomy lens = existing matrix view (enhanced for any entity type)
- [ ] Relationship lens = existing graph/KG views (enhanced for rich entity model)
- [ ] Geographic lens = existing map view (unchanged)

---

### Phase 5: Reporting & Synthesis
**Goal:** Generate polished outputs from research data — both one-click standard reports and custom AI-authored reports.

**Depends on:** Phase 1 (data), Phase 4 (analysis views to pull from)

#### 5.1 Standard Report Templates
- [ ] Market Overview: taxonomy breakdown, entity counts, key players
- [ ] Competitive Landscape: feature matrix, positioning, gaps
- [ ] Product Teardown: single-entity deep dive with all evidence
- [ ] Design Pattern Library: observed principles with evidence
- [ ] Change Report: temporal diffs and trends
- [ ] Available/unavailable based on data completeness

#### 5.2 Custom Report Generator
- [ ] Input: audience, questions to answer, tone/format preferences
- [ ] AI drafts narrative from project's structured data + evidence
- [ ] Every claim cites source evidence (provenance chain)
- [ ] Draft review + edit before export
- [ ] AI writes from YOUR data, not general knowledge — flags gaps

#### 5.3 Export Formats
- [ ] Interactive HTML microsite (stakeholders can click through, explore)
- [ ] PDF (traditional, formatted, printable)
- [ ] Canvas composition (report as Excalidraw workspace)

#### 5.4 Evidence Provenance
- [ ] Every data point in reports links to source evidence
- [ ] Claim → Analysis → Structured Data → Evidence → Source URL chain
- [ ] Clickable in interactive HTML exports

---

### Phase 6: Intelligence & Monitoring
**Goal:** Keep research alive with automated change detection and market signals.

**Depends on:** Phase 2 (capture engine), Phase 1 (entity model)

#### 6.1 Website Change Detection
- [ ] Periodic re-capture of tracked entity URLs
- [ ] Visual diff + content diff against previous capture
- [ ] Surface significant changes in project feed

#### 6.2 App Store Monitoring
- [ ] Track version updates, new screenshots, rating changes
- [ ] Diff against previous snapshot

#### 6.3 News/Announcement Monitoring
- [ ] RSS/news feed monitoring for tracked entities
- [ ] Press release detection
- [ ] Funding round detection

#### 6.4 Market Radar Dashboard
- [ ] Unified feed of all detected changes
- [ ] Significance scoring (routine update vs. major change)
- [ ] Trigger re-capture and re-extraction on major changes

---

### Phase 7: Advanced Features
**Goal:** Higher-order intelligence capabilities.

**Depends on:** Phases 1-5 substantially complete

#### 7.1 "So What?" Engine
- [ ] Proactive insight generation from structured data
- [ ] Pattern detection across entities (feature trends, pricing patterns, design patterns)
- [ ] Hypothesis suggestions based on data

#### 7.2 Hypothesis Tracking
- [ ] State hypotheses about the market
- [ ] Track supporting / contradicting evidence
- [ ] Surface "insufficient data" areas to guide further research
- [ ] Hypothesis dashboard with evidence weight

#### 7.3 Research Playbooks
- [ ] Save reusable research methodologies
- [ ] Apply playbook to new project → guided workflow
- [ ] Improve playbooks based on experience

#### 7.4 Cross-Project Intelligence
- [ ] Detect overlapping entities across projects
- [ ] Carry forward/link entity data between projects
- [ ] Cross-project pattern analysis

---

## Technical Decisions

### Database
- **Stay with SQLite** — handles 1000 entities × deep hierarchies fine with proper indexing
- Temporal data = timestamped attribute rows, not table-level versioning
- Evidence files stored on disk, referenced by path in DB
- JSON fields for flexible schema metadata

### Frontend
- **Stay with vanilla JS** — no framework migration
- New JS modules for new features (entities.js, lenses.js, capture.js, reports.js)
- Existing JS files evolve (companies.js → entities.js refactor)
- CSS design system (The Instrument) unchanged

### Backend
- **Stay with Flask + Blueprints**
- New blueprints for: entities, schema, evidence, capture, extraction, reports
- Existing blueprints preserved (companies becomes thin wrapper)
- Playwright added as backend dependency for capture engine

### AI Integration
- **Stay with Claude CLI** via `core/llm.py`
- Extended for: schema interview, feature extraction, screenshot classification, report generation, insight generation
- Structured output (JSON schema) patterns already established

---

## Migration Strategy

### Existing Projects
1. All existing companies become entities of type "Company" with default flat schema
2. All existing attributes (name, description, website, etc.) become entity attributes
3. All existing relationships become entity relationships
4. Zero data loss — existing projects work exactly as before
5. Users can optionally "upgrade" a project by defining a richer schema

### Existing Tests
1. All 266 original tests continue to pass unchanged
2. Company API remains fully functional — entity system runs alongside, not replacing
3. New test suites added with every implementation step — test count grows in lockstep
4. **Current total: 542 tests** (266 original + 62 entity DB + 119 entity API + 64 capture DB + 31 capture API)

---

## Session Log

| Session | Date | Work Done | Status |
|---|---|---|---|
| 1-3 | 2026-02 | Bug fixes #1-#8 | ✅ Complete |
| 4-5 | 2026-02 | Bug fixes #9-#12 | ✅ Complete |
| 6-7 | 2026-02 | Canvas rewrite (Excalidraw) | ✅ Complete |
| 8 | 2026-02 | UX/UI overhaul (design tokens, micro-interactions) | ✅ Complete |
| 9 | 2026-02 | Test architecture (266 pytest, 132 Playwright) | ✅ Complete |
| 10 | 2026-02-20 | Research Workbench brainstorm + planning | ✅ Complete |
| 11 | 2026-02-20 | Phase 1.1-1.5 + 1.9: Schema, entities, temporal, evidence, API, tests | ✅ Complete |
| 12 | 2026-02-20 | Phase 1.6-1.8: Project setup + entity browser + view compat (46 new tests, 447 total) | ✅ Complete |
| 13 | 2026-02-20 | Phase 2.1/2.4/2.5/2.5a: Capture engine core — file storage, website capture, document download, manual upload, evidence serve/delete/stats (95 new tests, 542 total) | ✅ Complete |
| 14 | TBD | Phase 2.2/2.3: Scrapers (UI galleries, app stores) | ⬜ Not started |
| 15 | TBD | Phase 2.6/2.7: Bulk capture + Capture UI | ⬜ Not started |

---

## Notes for Future Sessions

- **Always read this file first** before starting work
- **Update the Session Log** at the end of every session
- **Update task checkboxes** as items are completed
- **If a phase's scope changes**, update this document and note why in the session log
- **The vision doc** (`docs/RESEARCH_WORKBENCH_VISION.md`) has the full rationale — consult if you need to understand WHY a decision was made
- **The conversation transcript** (`docs/RESEARCH_WORKBENCH_CONVERSATION.md`) has the raw brainstorming — consult for detailed reasoning on specific design choices
