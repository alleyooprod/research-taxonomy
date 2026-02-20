# Research Workbench — Implementation Plan

> **Status:** Planning Complete — Phase 1 Ready to Build
> **Created:** 2026-02-20 (Session 10)
> **Last Updated:** 2026-02-20
> **Vision Doc:** `docs/RESEARCH_WORKBENCH_VISION.md`
> **Conversation Reference:** `docs/RESEARCH_WORKBENCH_CONVERSATION.md`

---

## Overview

Evolving the Research Taxonomy Library from a flat company taxonomy tool into a **personal research workbench** for structured market and product intelligence. The app should let a solo analyst conduct research at a depth that normally requires a team — competing not on data volume (like IDC/Mintel) but on **structure, methodology, and living evidence**.

**Core principle:** Evolve, don't rebuild. The existing Flask/pywebview app, design system, Excalidraw canvas, graph views, maps, AI integration, and 266 tests are preserved. The data layer transforms underneath; the UI evolves progressively on top.

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
| 266 pytest tests | ✅ Passing | 14 test files |
| 132 Playwright specs | ✅ Written | 24 spec files |

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
- [ ] Design schema definition format (JSON-based, stored per project)
- [ ] Schema defines: entity types, hierarchy relationships, attributes per type, attribute types (text, number, boolean, currency, enum, url, image-ref)
- [ ] Support both tree hierarchies (Company → Product → Plan → Tier → Feature) AND graph relationships (Product ↔ Design Principle)
- [ ] Built-in templates: Market Analysis, Product Analysis, Design Research, blank
- [ ] Schema stored in project metadata (SQLite JSON field or separate table)
- [ ] Schema amendment API (add/modify entity types and attributes mid-project)
- [ ] **Files affected:** New `core/schema.py`, new `web/blueprints/schema.py`, `storage/` schema tables

#### 1.2 Entity Data Model
- [ ] New database tables: `entity_types`, `entities`, `entity_attributes`, `entity_relationships`
- [ ] Entity table: id, project_id, entity_type_id, parent_entity_id (nullable), name, created_at, updated_at
- [ ] Attribute table: entity_id, attribute_key, attribute_value, captured_at (temporal)
- [ ] Relationship table: from_entity_id, to_entity_id, relationship_type, created_at
- [ ] Migration path: existing companies become entities of type "Company" — zero data loss
- [ ] All existing company fields (name, description, website, location, tags, category) become attributes
- [ ] **Files affected:** `storage/` (new tables + migration), new `core/entities.py`

#### 1.3 Temporal Versioning
- [ ] Every attribute value is timestamped (`captured_at`)
- [ ] Current value = most recent capture for that attribute
- [ ] Historical values preserved — can query "what was this attribute on date X?"
- [ ] Snapshot grouping: a "capture session" groups multiple attribute updates
- [ ] **Files affected:** `storage/` (versioning logic), `core/entities.py`

#### 1.4 Evidence Library
- [ ] New `evidence/` directory in project storage for captured artefacts
- [ ] Database table: `evidence` (id, entity_id, type [screenshot/document/page_archive/other], source_url, source_name, file_path, captured_at, metadata_json)
- [ ] Evidence linked to entities at any schema level
- [ ] File storage: screenshots as PNG/JPG, documents as PDF, page archives as MHTML or HTML
- [ ] **Files affected:** `storage/` (new table), new `core/evidence.py`, new `web/blueprints/evidence.py`

#### 1.5 API Layer Update
- [ ] New entity CRUD endpoints (replace or augment company-specific endpoints)
- [ ] Entity endpoints are schema-aware (return attributes defined by project schema)
- [ ] Backwards-compatible: existing company API routes still work, internally mapped to entity API
- [ ] **Files affected:** New `web/blueprints/entities.py`, modify `web/blueprints/companies.py` (thin wrapper)

#### 1.6 Project Setup Flow (AI-Guided Interview)
- [ ] New project creation flow with guided interview
- [ ] AI proposes schema based on research question description
- [ ] Back-and-forth refinement (AI challenges user choices)
- [ ] Template selection as starting point (or blank)
- [ ] Final schema confirmation before project creation
- [ ] "Quick create" option bypasses interview (flat Company schema, same as current)
- [ ] **Files affected:** `web/static/js/projects.js`, `web/blueprints/projects.py`, `core/llm.py`

#### 1.7 Entity Browser UI
- [ ] Company list becomes entity browser — shows entities of current schema level
- [ ] Drill-down navigation: click Company → see its Products → click Product → see its Plans
- [ ] Breadcrumb navigation for hierarchy depth
- [ ] Entity cards show attributes from schema + evidence count + child entity count
- [ ] Existing search, filter, and bulk actions work across entity types
- [ ] **Files affected:** `web/static/js/companies.js` (major refactor → may rename to `entities.js`), `web/templates/index.html`, `web/static/css/companies.css`

#### 1.8 Existing View Compatibility
- [ ] Taxonomy matrix accepts any entity type (not just companies)
- [ ] Graph/KG views work with the new entity + relationship model
- [ ] Maps work for any entity with a location attribute
- [ ] Canvas unchanged (still freeform)
- [ ] AI Discovery enhanced to populate sub-entities when adding companies
- [ ] **Files affected:** `taxonomy.js`, `maps.js`, `ai.js`, `ai.py`

#### 1.9 Tests
- [ ] Migrate existing 266 tests to work with new entity model
- [ ] New tests for schema CRUD, entity CRUD, temporal queries, evidence storage
- [ ] E2E tests for project setup flow and entity browser
- [ ] Target: all existing tests pass + new coverage

---

### Phase 2: Capture Engine
**Goal:** Automated and manual evidence collection from web sources.

**Depends on:** Phase 1 (evidence library, entity model)

#### 2.1 Headless Website Capture
- [ ] Playwright-based backend service for full-page screenshots + HTML archival
- [ ] Input: URL + entity to link to
- [ ] Output: screenshot (PNG) + HTML snapshot stored in evidence library
- [ ] Support for: marketing pages, pricing pages, help docs, changelogs
- [ ] **Files affected:** New `core/capture.py`, new `web/blueprints/capture.py`

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
- [ ] Download and store PDFs (IPIDs, regulatory docs, whitepapers)
- [ ] Download and store HTML help documentation pages
- [ ] Changelog page capture with diff detection for future visits
- [ ] **Files affected:** `core/capture.py` (extended)

#### 2.5 Manual Evidence Upload
- [ ] UI for uploading screenshots, documents, files directly
- [ ] Drag-and-drop onto entity cards
- [ ] Paste from clipboard (screenshot capture while using a product)
- [ ] **Files affected:** `web/blueprints/evidence.py`, frontend JS

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
- [ ] **Files affected:** `ai.js` or new `capture.js`, `index.html`

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
1. Company API tests updated to use entity API internally
2. All 266 tests must pass after Phase 1
3. New test suites added per phase

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
| 11 | TBD | Phase 1 build begins | ⬜ Not started |

---

## Notes for Future Sessions

- **Always read this file first** before starting work
- **Update the Session Log** at the end of every session
- **Update task checkboxes** as items are completed
- **If a phase's scope changes**, update this document and note why in the session log
- **The vision doc** (`docs/RESEARCH_WORKBENCH_VISION.md`) has the full rationale — consult if you need to understand WHY a decision was made
- **The conversation transcript** (`docs/RESEARCH_WORKBENCH_CONVERSATION.md`) has the raw brainstorming — consult for detailed reasoning on specific design choices
