# Research Workbench — Implementation Plan

> **Status:** ALL PHASES COMPLETE — every item implemented, zero deferred. 1517 tests passing.
> **Created:** 2026-02-20 (Session 10)
> **Last Updated:** 2026-02-20 (Session 23)
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
| 894 pytest tests | ✅ Passing | 30 test files |
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
- [x] Migration path: existing companies become entities of type "Company" — zero data loss (`core/migration.py`, `POST /api/migrate/companies`, 17 tests)
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
- [x] File storage engine (actual file write/read to `evidence/` directory) — completed in Phase 2.1 (`core/capture.py`)
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
- [x] Backwards-compatible company API wrapper (`core/compat.py` + companies.py delegates to entities, `tests/test_compat.py`)
- [x] **Files:** `web/blueprints/entities.py` (300+ lines, 23 endpoints), `web/app.py` (blueprint registration)
- [x] **Tests:** 73 API tests in `tests/test_api_entities.py` (including 2 full workflow integration tests)

#### 1.6 Project Setup Flow (AI-Guided Interview)
- [x] New project creation flow with template selection
- [x] AI proposes schema based on research question description (`POST /api/schema/suggest`)
- [x] Back-and-forth refinement (AI challenges user choices) — `POST /api/schema/refine`, rule-based fallback, completeness scoring, apply suggestions via sync, iterate with feedback
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
- [x] Taxonomy matrix enhanced to show entities in category detail — handled by compat layer (`/api/companies` returns entities as company-format dicts)
- [x] AI Discovery enhanced to populate sub-entities — basic flow works via compat layer (`/api/companies/add` creates entities in entity-mode projects)
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
- [x] E2E Playwright tests for entity browser UI (`e2e/test_entity_browser.cjs`, 9 test groups)
- [x] E2E tests for project setup flow (`e2e/test_project_setup.cjs`, 8 test groups)
- [x] Migration tests: verify company→entity data integrity (`tests/test_migration.py`, 17 tests)

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
- [x] Dribbble scraper (`core/scrapers/dribbble.py`) — search shots, download images from cdn.dribbble.com
- [x] Scrnshts Club scraper (`core/scrapers/scrnshts.py`) — App Store screenshot gallery, WordPress search/browse/download
- [x] Collect UI scraper (`core/scrapers/collectui.py`) — 14,400+ UI pattern shots, challenge-based browse
- [x] Godly scraper (`core/scrapers/godly.py`) — curated web design gallery, JSON-hydrated Next.js
- [x] Siteinspire scraper (`core/scrapers/siteinspire.py`) — web design showcase, Cloudflare R2 images
- [x] One Page Love scraper (`core/scrapers/onepagelove.py`) — 8,900+ one-page sites, imgix CDN
- [x] SaaS Pages scraper (`core/scrapers/saaspages.py`) — SaaS landing page sections, Versoly CDN
- [x] Httpster scraper (`core/scrapers/httpster.py`) — 3,100+ curated web designs, WebP
- [x] Generic gallery API: `GET /api/scrape/gallery/sources`, `GET /api/scrape/gallery/<source>/search`, `POST /api/scrape/gallery/<source>/download`
- [x] All scrapers: polite 0.5s delay, User-Agent header, error handling, CaptureResult pattern
- [x] 32 tests in `tests/test_gallery_scrapers.py` (8 dataclass + 11 search/parse + 13 API endpoint)
- [x] Mobbin/Screenlane/Refero skipped — ToS prohibits scraping, paywalled, or signed URLs
- [x] **Files:** 8 scraper modules in `core/scrapers/`, `web/blueprints/capture.py` (gallery endpoints), `tests/test_gallery_scrapers.py`

#### 2.3 App Store Scraper
- [x] Apple App Store: search, details, screenshots, icon, metadata via iTunes Search API
- [x] Google Play Store: details, screenshots, icon via HTML scraping + BeautifulSoup
- [x] Auto-link to product entity (evidence records with source_name and metadata)
- [x] App metadata extraction for entity attributes (app_store_rating, play_store_id, etc.)
- [x] Partial failure handling (some screenshots fail but rest succeed)
- [x] API endpoints: search, details, screenshot download for both stores
- [x] **Files:** `core/scrapers/__init__.py`, `core/scrapers/appstore.py` (280+ lines), `core/scrapers/playstore.py` (300+ lines), `web/blueprints/capture.py` (scraper endpoints)
- [x] **Tests:** 27 scraper tests in `test_scrapers.py` (parsing, search, details, download, metadata, dataclasses), 15 API tests in `test_api_scrapers.py`

#### 2.4 Document Capture
- [x] Download and store PDFs (IPIDs, regulatory docs, whitepapers)
- [x] Download and store HTML help documentation pages
- [x] Changelog page capture with diff detection — monitoring system (content hashing + diff) + changelog extractor (classify + parse) + re-capture trigger on major changes
- [x] **Files:** `core/capture.py` (capture_document function), `web/blueprints/capture.py` (document endpoint)
- [x] **Tests:** 6 document capture tests (mocked HTTP) in `test_capture.py`, 5 API tests in `test_api_capture.py`

#### 2.5 Manual Evidence Upload
- [x] API for uploading screenshots, documents, files directly (`POST /api/evidence/upload`)
- [x] File validation (extension whitelist, size limit 50MB, empty file check)
- [x] Evidence type auto-detection from file extension
- [x] Evidence file serving (`GET /api/evidence/<id>/file`)
- [x] Evidence file + record deletion (`DELETE /api/evidence/<id>/file`)
- [x] Evidence storage stats per project (`GET /api/evidence/stats`)
- [x] Drag-and-drop onto entity cards (frontend) — drop zone overlay on capture section + entity detail panel, entity auto-selection
- [x] Paste from clipboard (screenshot capture while using a product) — Ctrl/Cmd+V on Process/Companies tabs, auto-names as screenshot_YYYY-MM-DD_HHmmss.png
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
- [x] `POST /api/capture/bulk` endpoint — validates items, starts async background job via `web/async_jobs.py`
- [x] `_run_bulk_capture()` background worker — iterates URLs, calls `capture_website()`/`capture_document()`, writes progress via `write_result()`
- [x] `GET /api/capture/bulk/<job_id>` — polls job status (pending/running/complete) with progress counts
- [x] 10 tests in `tests/test_api_capture.py` — 6 validation + 4 mock-based (starts job, poll pending, poll complete, default type)
- [x] **Files:** `web/blueprints/capture.py` (3 new endpoints/functions), `tests/test_api_capture.py` (TestBulkCaptureAPI class)

#### 2.7 Capture UI
- [x] Evidence Capture sub-section in Process tab — stats, action bar, job list, bulk progress
- [x] `web/static/js/capture.js` (~300 lines) — `initCaptureUI()`, stats loading, single/bulk capture, upload, entity selector, poll loop
- [x] `web/static/css/capture.css` (~160 lines) — stats grid, action bar, job list, bulk progress bar, responsive
- [x] Updated `web/templates/index.html` — capture section HTML, CSS/JS includes
- [x] Updated `web/static/js/core.js` — calls `initCaptureUI()` when Process tab shown
- [x] Drag-and-drop upload onto entity cards — drop zone overlay, auto-links to entity on entity detail panel
- [x] Clipboard paste for screenshots — paste event listener, auto-generates timestamped filename
- [x] **Files:** `web/static/js/capture.js`, `web/static/css/capture.css`, `web/templates/index.html`, `web/static/js/core.js`

#### 2.8 Tests — Capture Engine
- [x] DB-layer tests: 64 tests in `tests/test_capture.py` (file storage, validation, upload, document capture, evidence by ID)
- [x] API-layer tests: 41 tests in `tests/test_api_capture.py` (upload, serve, delete, document capture, website capture, stats, jobs, integration, bulk capture)
- [x] `capture` marker added to `pytest.ini` for selective running (`pytest -m capture`)
- [x] All 447 original tests still pass after capture engine addition
- [x] **Total: 584 tests passing** (447 original + 64 capture DB + 31 capture API + 27 scraper DB + 15 scraper API)

---

### Phase 3: Extraction & Structuring
**Goal:** AI-powered extraction of structured data from captured evidence, with human validation.

**Depends on:** Phase 1 (schema, entities), Phase 2 (evidence library populated)

#### 3.1 Feature Extraction Pipeline
- [x] AI analyses captured evidence (web pages, documents, screenshots) against project schema
- [x] Extracts structured attribute values for entities
- [x] Cross-references multiple sources for the same entity
- [x] Flags contradictions between sources (case-insensitive value comparison)
- [x] Confidence scoring: 0-1 scale, clamped and validated
- [x] DB tables: `extraction_jobs` (status tracking, cost/duration), `extraction_results` (per-attribute values with confidence/reasoning)
- [x] Review workflow: accept (writes to entity_attributes), reject, edit — per result or bulk
- [x] Review queue endpoint with joins across results/jobs/entities
- [x] Extraction stats endpoint (counts by status)
- [x] Background async extraction jobs with threading + Flask app context
- [x] Extract from evidence (reads HTML/text files), from URL (fetches + extracts), from raw content
- [x] Screenshot evidence returns (None, "image") — classified but not text-extracted
- [x] **Files:** `core/extraction.py` (350+ lines), `storage/repos/extraction.py` (ExtractionMixin, 300+ lines), `web/blueprints/extraction.py` (15+ API endpoints), `storage/schema.sql` (2 tables, 7 indexes)
- [x] **Tests:** 58 DB tests in `tests/test_extraction.py` + 38 API tests in `tests/test_api_extraction.py` = 96 tests

#### 3.2 Document-Specific Extractors
- [x] Product page extractor: heuristic classification (marketing keywords) + LLM extraction (company_name, tagline, features, social_proof, etc.)
- [x] Pricing page extractor: heuristic classification (pricing keywords, $, /month) + LLM extraction (plans, pricing_model, free tier/trial)
- [x] Generic fallback extractor: document_type, title, summary, key_facts, entities_mentioned
- [x] Auto-routing classifier: scores content against all extractors, routes to best match above threshold (0.4)
- [x] `extract_with_classification()` — classifies then extracts, supports forced extractor override
- [x] API endpoints: `POST /api/extract/classify` (classify + extract), `GET /api/extract/extractors` (list available)
- [x] IPID parser (standardised EU/UK insurance document format) — `core/extractors/ipid.py`, section heading detection, 14 extracted fields, registered in classifier, 29 tests
- [x] Changelog parser (`core/extractors/changelog.py` — classify + extract version/frequency/features/maturity, registered in classifier)
- [x] **Files:** `core/extractors/__init__.py`, `core/extractors/product_page.py`, `core/extractors/pricing_page.py`, `core/extractors/generic.py`, `core/extractors/classifier.py`
- [x] **Tests:** 27 tests in `tests/test_extractors.py` (classification, prompts, extraction with mocked LLM, API endpoints)

#### 3.3 Screenshot Classification
- [x] URL-based classification: regex patterns map URL paths to 16 journey stages (landing, onboarding, login, dashboard, listing, detail, settings, checkout, pricing, help, search, profile, notification, error, empty, other)
- [x] Filename-based classification: stage keyword matching in evidence filenames
- [x] Context-based classification: combines URL, filename, and page title metadata — highest confidence wins
- [x] LLM-based classification: structured output with journey_stage, confidence, ui_patterns, description
- [x] 12 UI patterns: form, table, chart, map, modal, navigation, card-grid, list, hero, empty-state, wizard, timeline
- [x] Journey sequence grouping: sorts by typical UX journey order, groups into named sequences
- [x] API endpoints: `POST /api/extract/classify-screenshot`, `GET /api/extract/screenshot-sequences`
- [x] **Files:** `core/extractors/screenshot.py` (336 lines)
- [x] **Tests:** 42 tests in `tests/test_screenshot_classifier.py` (URL, filename, context, LLM, sequences, constants, API)

#### 3.4 Human Review Interface
- [x] Queue of AI-extracted data pending review — `GET /api/extract/queue/grouped` groups by entity
- [x] Per-entity review: expandable entity cards with results, confidence indicators, source info
- [x] Accept / edit / reject per attribute — `POST /api/extract/results/<id>/review`
- [x] Confidence indicators — high/medium/low with visual bars, distribution in stats
- [x] "Needs more evidence" flag — `POST /api/extract/results/<id>/flag`, query flagged results
- [x] Bulk review per-entity and bulk all — `POST /api/extract/results/bulk-review`
- [x] Enhanced extraction stats — confidence distribution, entities pending, needs evidence count
- [x] **Files:** `web/static/js/review.js` (~420 lines), `web/static/css/review.css` (~380 lines), `web/blueprints/extraction.py` (4 new endpoints), `storage/repos/extraction.py` (3 new methods + enhanced stats)
- [x] **Tests:** 21 DB tests in `tests/test_review.py` (grouped queue, needs evidence, enhanced stats), 24 API tests in `tests/test_api_review.py` (endpoints + full workflow)

#### 3.5 Feature Standardisation
- [x] Per-project canonical feature vocabulary — `canonical_features` + `feature_mappings` tables
- [x] AI proposes standard names — `POST /api/features/suggest` with Claude CLI structured output
- [x] User confirms or creates new canonical features — full CRUD API (14 endpoints)
- [x] Resolve raw values to canonical (exact match, case-insensitive, canonical name fallback)
- [x] Unmapped values detection — finds extracted values without mappings
- [x] Merge features — moves all mappings from source to target, deletes sources
- [x] Categories — distinct category listing + filtering
- [x] Vocabulary statistics per attr_slug
- [x] Frontend UI — feature cards with expand/collapse, mapping management, unmapped values, AI suggest, search, category filter
- [x] **Files:** `storage/repos/features.py` (~300 lines), `web/blueprints/features.py` (~355 lines), `web/static/js/features.js` (~540 lines), `web/static/css/features.css` (~380 lines), index.html (feature section in Review tab)
- [x] **Tests:** 30 DB tests in `tests/test_features.py` (CRUD, mappings, merge, resolve, unmapped, stats, categories), 28 API tests in `tests/test_api_features.py` (all endpoints + validation)

---

### Phase 4: Analysis Lenses
**Goal:** Analysis views that activate based on available structured data.

**Depends on:** Phase 1 (entity model), Phase 3 (structured data populated — though can work with manual data from Phase 1)

#### 4.1 Lens Framework ✅
- [x] Lens system: each lens has activation criteria (what data must exist)
- [x] Lenses show as available/unavailable in navigation based on project data
- [x] Unavailable lenses show hint: "Capture UI screenshots to activate the Design lens"
- [x] **Files:** `web/blueprints/lenses.py` (1,139 lines, 9 endpoints), `web/static/js/lenses.js` (1,093 lines), `web/static/css/lenses.css` (1,394 lines)
- [x] **Wiring:** Blueprint registered in `app.py`, Analysis tab in `index.html`, CSS/JS includes, `initLenses()` in `core.js`
- [x] **Tests:** `tests/test_lenses.py` — 41 tests (availability, competitive, product, design, temporal, edge cases)

#### 4.2 Competitive Lens ✅
- [x] Feature comparison matrix: entities × features grid with canonical vocabulary support
- [x] Gap analysis: features sorted by coverage %, horizontal coverage bars
- [x] Positioning map: 2D scatter on user-chosen attributes with normalized coordinates
- [x] **Activation:** 2+ entities with comparable feature data

#### 4.3 Product Lens ✅
- [x] Plan/tier comparison across companies (reuses feature matrix pattern)
- [x] Pricing landscape (headline prices, pricing model, free tier detection)
- [x] **Activation:** 2+ entities with pricing/plan/tier attributes

#### 4.4 Design Lens ✅
- [x] Evidence gallery per entity (grouped by evidence_type, lightbox viewer)
- [x] Journey map viewer (screenshots classified into journey stages, ordered by UX flow)
- [x] Pattern library (design principles extracted from captures) — `/api/lenses/design/patterns`, aggregates from extraction results + screenshot classifications + entity attributes, pattern cards with category filter
- [x] UX scoring / comparison — `/api/lenses/design/scoring`, 4 sub-scores (journey coverage, evidence depth, pattern diversity, attribute completeness), weighted composite, entity comparison bars
- [x] **Activation:** Entities with screenshot evidence

#### 4.5 Temporal Lens ✅
- [x] Snapshot comparison: side-by-side attribute diff between two snapshots
- [x] Attribute change timeline per entity (vertical timeline with dot markers)
- [x] Market-level change summary: signals/summary endpoint aggregates changes by field, most active entities, severity breakdown, recent highlights across configurable time window
- [x] **Activation:** 2+ capture snapshots for any entity

#### 4.6 Signals Lens
- [x] Event timeline combining change feed, attribute updates, evidence captures
- [x] Per-entity activity summary with change/evidence/attribute counts
- [x] Weekly trend chart with stacked event buckets
- [x] Entity x event-type heatmap matrix
- [x] **Activation:** Monitoring configured (Phase 5) or entity attributes exist

#### 4.7 Existing Lenses (already built, enhanced)
- [x] Relationship lens detected in availability (always available when entities exist)
- [x] Geographic lens detected in availability (checks for location-type attributes)
- [x] Taxonomy lens = existing matrix view (works with entity types via existing tab)
- [x] Relationship lens = existing graph/KG views (works with entity model via existing tab)
- [x] Geographic lens = existing map view (works via existing tab)

---

### Phase 5: Reporting & Synthesis
**Goal:** Generate polished outputs from research data — both one-click standard reports and custom AI-authored reports.

**Depends on:** Phase 1 (data), Phase 4 (analysis views to pull from)

#### 5.1 Standard Report Templates
- [x] Market Overview: taxonomy breakdown, entity counts, key players
- [x] Competitive Landscape: feature matrix, positioning, gaps
- [x] Product Teardown: single-entity deep dive with all evidence
- [x] Design Pattern Library: observed principles with evidence
- [x] Change Report: temporal diffs and trends
- [x] Available/unavailable based on data completeness

#### 5.2 Custom Report Generator
- [x] Input: audience, questions to answer, tone/format preferences
- [x] AI drafts narrative from project's structured data + evidence
- [x] Every claim cites source evidence (provenance chain)
- [x] Draft review + edit before export
- [x] AI writes from YOUR data, not general knowledge — flags gaps

#### 5.3 Export Formats
- [x] Interactive HTML (standalone with inline CSS)
- [x] Markdown export
- [x] JSON export
- [x] PDF (traditional, formatted, printable) — via WeasyPrint (graceful fallback if not installed), `GET /api/synthesis/<id>/export?format=pdf`, styled A4 template
- [x] Canvas composition (report as Excalidraw workspace) — `?format=canvas` export, generates Excalidraw JSON with title block + sections, loads into Canvas tab via `loadCanvasFromReport()`, 8 tests

#### 5.4 Evidence Provenance
- [x] Attribute trace: full chain from attribute → extraction → evidence → URL
- [x] Entity provenance summary with per-attribute evidence status + coverage %
- [x] Reverse evidence map: evidence → supported attributes
- [x] Project-wide coverage stats + per-entity breakdown
- [x] Source URL inventory across project with entity/attribute counts
- [x] Provenance search: find attributes by value with chain info
- [x] Report claims: scan report sections for entity/attribute references with evidence links
- [x] Provenance stats: quick aggregate (total, backed, manual, sync, coverage %)
- [x] Intelligence tab "Provenance" sub-view with Coverage, Sources, Search views

---

### Phase 6: Intelligence & Monitoring
**Goal:** Keep research alive with automated change detection and market signals.

**Depends on:** Phase 2 (capture engine), Phase 1 (entity model)

#### 6.1 Website Change Detection
- [x] Periodic re-capture of tracked entity URLs
- [x] Content diff via SHA-256 hash comparison
- [x] Surface significant changes in project feed

#### 6.2 App Store Monitoring
- [x] Track version updates, new screenshots, rating changes via iTunes/Play Store scrapers
- [x] Fingerprint-based diff against previous snapshot

#### 6.3 News/Announcement Monitoring
- [x] RSS/Atom feed monitoring for tracked entities
- [x] New entry detection since last check
- [x] Press release detection — `core/extractors/press_release.py` (classify + extract headline/type/entities/quotes/implications), registered in classifier
- [x] Funding round detection — `core/extractors/funding_round.py` (classify + extract round_type/amount/investors/valuation), registered in classifier

#### 6.4 Market Radar Dashboard
- [x] Unified change feed with filters (type, severity, read/unread)
- [x] Significance scoring (info/minor/major/critical)
- [x] Auto-setup monitors from entity URL attributes
- [x] Intelligence tab with stats bar, feed, monitor table
- [x] Trigger re-capture and re-extraction on major changes — `_trigger_recapture()` auto-queues capture on major/critical severity, adds feed entry

---

### Phase 7: Advanced Features
**Goal:** Higher-order intelligence capabilities.

**Depends on:** Phases 1-5 substantially complete

#### 7.1 "So What?" Engine
- [x] Proactive insight generation from structured data
- [x] Pattern detection across entities (feature trends, pricing patterns, design patterns)
- [x] Hypothesis suggestions based on data

#### 7.2 Hypothesis Tracking
- [x] State hypotheses about the market
- [x] Track supporting / contradicting evidence
- [x] Surface "insufficient data" areas to guide further research
- [x] Hypothesis dashboard with evidence weight

#### 7.3 Research Playbooks
- [x] Save reusable research methodologies
- [x] Apply playbook to new project → guided workflow
- [x] Improve playbooks based on experience

#### 7.4 Cross-Project Intelligence
- [x] Detect overlapping entities across projects
- [x] Carry forward/link entity data between projects
- [x] Cross-project pattern analysis

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
4. **Current total: 1480 tests** across 30+ test files — every feature has both DB-layer and API-layer tests

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
| 13 | 2026-02-20 | Phase 2.1/2.4/2.5/2.5a/2.3: Capture engine + scrapers — file storage, website capture, document download, manual upload, App Store + Play Store scrapers (137 new tests, 584 total) | ✅ Complete |
| 14 | 2026-02-20 | Phase 3.1/3.2/3.3: Extraction pipeline + document extractors + screenshot classification — extraction jobs/results DB, review workflow, product/pricing/generic extractors with auto-routing classifier, URL/filename/context/LLM screenshot classification, journey sequence grouping (165 new tests, 749 total) | ✅ Complete |
| 15 | 2026-02-20 | Phase 3.4/3.5: Human review interface + feature standardisation — grouped review queue, accept/reject/edit per attribute, confidence filtering, needs-evidence flagging, bulk review, canonical vocabulary CRUD, merge, resolve, unmapped detection, AI suggest, frontend for both (103 new tests, 852 total) | ✅ Complete |
| 16 | 2026-02-20 | Phase 2.6/2.7/2.2: Bulk capture + capture UI + 8 UI gallery scrapers (Dribbble, Scrnshts, CollectUI, Godly, Siteinspire, OnePageLove, SaaSPages, Httpster) — generic gallery API, 42 new tests, 894 total | ✅ Complete |
| 17 | 2026-02-20 | Phase 4.1-4.5: Analysis Lenses — lens framework, competitive (matrix/gaps/positioning), product (pricing), design (gallery/journey), temporal (timeline/compare), Analysis tab + full wiring, 41 new tests, 935 total | ✅ Complete |
| 18 | 2026-02-20 | Phase 5.1-5.3: Reporting & Synthesis — 5 report templates (market overview, competitive landscape, product teardown, design patterns, change report), AI-enhanced generation (mocked LLM), template availability detection, report CRUD, export (HTML/Markdown/JSON), `/api/synthesis` routes, frontend in Export tab, 33 new tests, 968 total | ✅ Complete |
| 18b | 2026-02-20 | Phase 6.1-6.4: Intelligence & Monitoring — monitors CRUD, 4 check types (website/appstore/playstore/RSS), change feed with severity scoring, auto-setup from entity URLs, dashboard stats, Intelligence tab, 33 new tests, 1001 total | ✅ Complete |
| 19 | 2026-02-20 | Phase 7.1-7.2: Insights & Hypothesis Tracking — 7 rule-based detectors (feature gaps, pricing outliers, sparse coverage, stale entities, feature clusters, duplicates, attribute coverage), AI-enhanced generation (mocked LLM), hypothesis CRUD with evidence tracking, directional weighted confidence scoring, 16 API endpoints at `/api/insights/*`, 3 DB tables (insights, hypotheses, hypothesis_evidence), Intelligence tab sub-navigation (Monitoring/Insights/Hypotheses), 1301-line JS + 1340-line CSS frontend, 50 new tests, 1051 total | ✅ Complete |
| 20 | 2026-02-20 | Phase 7.3-7.4: Research Playbooks + Cross-Project Intelligence — playbook CRUD with 4 built-in templates (Market Mapping, Product Teardown, Design Research, Competitive Intelligence), run lifecycle with step-by-step progress tracking, auto-complete, AI improvement suggestions, template seeding/protection; entity overlap detection (Dice coefficient + URL domain matching), manual/auto entity linking, attribute sync between linked entities, attribute diff comparison, 3 cross-project detectors (multi-project overlap, attribute divergence, coverage gaps), cross-project insights + stats; Intelligence tab sub-nav extended to 5 views (Monitoring/Insights/Hypotheses/Playbooks/Cross-Project), 1188-line + 696-line JS, 954-line + 693-line CSS frontends, 117 new tests, 1168 total | ✅ Complete |
| 21 | 2026-02-20 | Phase 4.6 + 5.4: Signals Lens + Evidence Provenance — signals lens with 4 views (timeline, activity, trends, heatmap) combining change_feed + entity_attributes + evidence data; provenance blueprint with 8 read-only endpoints (attribute trace, entity summary, evidence map, project coverage, project sources, search, report claims, stats), full chain tracing attribute→extraction→evidence→URL; signals integrated into Analysis tab lens system, provenance integrated as 6th Intelligence sub-view with Coverage/Sources/Search; 101 new tests (44 signals + 57 provenance), 1269 total | ✅ Complete |
| 22 | 2026-02-20 | Deferred items batch: Company→Entity migration (`core/migration.py`, 28-column field map, idempotent, dry-run, `POST /api/migrate/companies`); backwards-compatible company API wrapper (`core/compat.py` + companies.py delegates to entities for migrated projects); changelog extractor (`core/extractors/changelog.py`, classify + extract version/frequency/features/maturity); re-capture trigger on major/critical changes (`_trigger_recapture` in monitoring.py); taxonomy matrix + AI Discovery entity integration via compat layer; E2E Playwright tests (project setup + entity browser, 17 test groups); market-level change summary (5th signals sub-view); 87 new tests (17 migration + 48 compat + 22 changelog), 1356 total | ✅ Complete |
| 23 | 2026-02-20 | **ALL REMAINING DEFERRED ITEMS — PLAN COMPLETE**: **Drag-and-drop upload** (drop zone overlay on capture section + entity detail panel, auto-links to entity) + **Clipboard paste** (Ctrl/Cmd+V on Process/Companies tabs, timestamped filename); **PDF export** (WeasyPrint with graceful fallback, A4 styled template, `?format=pdf`, 7 tests); **Canvas composition** (report as Excalidraw workspace, `?format=canvas`, title block + sections, loads into Canvas tab, 8 tests); **Press release extractor** (`core/extractors/press_release.py`, 39 tests); **Funding round extractor** (`core/extractors/funding_round.py`, 38 tests); **IPID parser** (`core/extractors/ipid.py`, 14 fields, section heading detection, 29 tests); **Pattern library** (`/api/lenses/design/patterns`, 7 tests) + **UX scoring** (`/api/lenses/design/scoring`, 10 tests); **AI schema refinement** (`POST /api/schema/refine`, LLM + rule-based fallback, 23 tests); 161 new tests, 1517 total | ✅ Complete |

---

## Notes for Future Sessions

- **Always read this file first** before starting work
- **Update the Session Log** at the end of every session
- **Update task checkboxes** as items are completed
- **If a phase's scope changes**, update this document and note why in the session log
- **The vision doc** (`docs/RESEARCH_WORKBENCH_VISION.md`) has the full rationale — consult if you need to understand WHY a decision was made
- **The conversation transcript** (`docs/RESEARCH_WORKBENCH_CONVERSATION.md`) has the raw brainstorming — consult for detailed reasoning on specific design choices
