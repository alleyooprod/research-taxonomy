# Research Workbench — Vision & Design Decisions

> **Created:** 2026-02-20 (Session 10 brainstorm)
> **Purpose:** Captures the "why" behind every major design decision, including directions we explored but rejected.

---

## The Vision

**One-line:** A personal research workbench that lets a solo analyst conduct structured market and product intelligence at a depth that normally requires a team.

**The reframe:** The app started as a healthtech company taxonomy tool. Through brainstorming in Session 10, we reframed it as a **domain-agnostic research workbench**. It's not about companies, or products, or insurance — it's about giving structure and methodology to any research question. Companies are just one entity type. The tool should work equally well for:

- UK health insurance product teardowns (Company → Product → Plan → Tier → Feature)
- Digital product design principles research (Product ↔ Design Principle, many-to-many)
- Competitive market analysis (Company → Market Signals → Funding → Strategy)
- Design agency portfolio analysis (Agency → Portfolio → Design Principles)

**The competitive positioning:** This doesn't compete with IDC/Mintel/Oxford Economics on data volume or proprietary access. Those firms have 100+ analysts, vendor briefings, survey panels, and enterprise clients. Instead, this offers something they structurally cannot: a **living, interactive research environment** rather than static PDF reports. Their reports age the moment they're published. This workbench evolves continuously as you research. The edge is structure + methodology + living evidence, not raw data volume.

---

## Key Decisions Made

### 1. Evolve, Don't Rebuild
**Decision:** Keep the existing codebase and evolve it progressively.

**Why:** The app has ~15 working features, a polished design system ("The Instrument"), Excalidraw integration (2 sessions of work), Cytoscape graph views, Leaflet maps, AI integration, and 266 passing tests. Rebuilding from scratch would mean months of re-implementing what already works. The things that need to change (data model, API layer, navigation) can be transformed underneath the working UI.

**What this means:** Flask stays. pywebview stays. Vanilla JS stays. SQLite stays. The data layer transforms; the UI evolves incrementally on top.

### 2. Flexible Entity Schema Per Project
**Decision:** Instead of a fixed Company data model, each project defines its own entity hierarchy with configurable attributes.

**Why:** Different research questions need different data structures. Insurance needs Company → Product → Plan → Tier → Feature. Design research needs Product ↔ Design Principle (graph, not tree). A flat market scan just needs Company. Hardcoding any of these limits the tool's applicability.

**Design detail:** The schema system supports both tree hierarchies (parent-child) AND graph relationships (many-to-many between entity types). This is critical for the design research use case where products and principles link in both directions.

**Amendability:** Schemas can be modified mid-project (adding new entity types or attributes), though this should be rare. The AI-guided setup is designed to get the schema right upfront through a challenging back-and-forth process.

### 3. AI-Guided Project Setup
**Decision:** New projects start with an AI interview that proposes and refines the entity schema based on the research question.

**Why:** Defining a data schema is a technical task. Researchers shouldn't need to think in database terms. The AI translates "I want to understand UK health insurance apps" into a concrete entity hierarchy, and challenges the user on whether they need each level of depth. This also ensures methodological rigour — the AI can suggest dimensions the user hasn't considered.

**Quick create option:** Users who want a flat Company list (current behaviour) can skip the interview entirely. No forced friction.

### 4. Evidence Library as First-Class Concept
**Decision:** All captured artefacts (screenshots, documents, page archives) are stored in a structured evidence library, linked to entities, and timestamped.

**Why:** The evidence IS the research. Without it, analysis is unsubstantiated. Every claim in a report should be traceable to source evidence. The evidence library also enables temporal analysis (how has this product's website changed?) and the "90% experience" goal (enough visual evidence to understand a product without downloading it yourself).

### 5. Scraping Public UI Gallery Sites as Primary Source
**Decision:** Primary capture sources are Mobbin, Screenlane, Refero, Appshots, Scrnshts, Dribbble — public UI galleries. Secondary: App Store/Play Store. Tertiary: company websites.

**Why:** These galleries have already curated real product UIs. You're not trying to break into authenticated products — you're harvesting an existing ecosystem of captures. This is orders of magnitude simpler and more reliable than trying to scrape behind-auth product UIs.

### 6. Feature Extraction Grounded in Official Documentation
**Decision:** Feature standardisation uses publicly available canonical documents (IPIDs for insurance, KIDs for finance, etc.) as ground truth, cross-referenced with scraped UI and marketing content.

**Why:** AI extraction from screenshots is noisy. Marketing pages are aspirational. But regulatory/standardised documents (like IPIDs) are factual, structured, and comparable across companies. Using these as the grounding source for feature extraction produces reliable, defensible data. The AI cross-references other sources and surfaces contradictions for human review.

### 7. Lenses, Not Tabs
**Decision:** Analysis views are "lenses" that activate based on available data, rather than fixed tabs that are always visible.

**Why:** A design research project doesn't need a pricing analysis view. An insurance project doesn't need a design pattern library. Showing irrelevant views creates clutter and confusion. Lenses that activate based on data completeness ensure the UI matches the research — and they provide implicit guidance ("Capture UI screenshots to activate the Design lens" tells you what to do next).

### 8. Temporal Versioning via Timestamped Attributes
**Decision:** Every attribute value is timestamped. Current value = most recent. Historical values are preserved.

**Why:** Market research is inherently temporal. Products change, prices update, features launch. Without versioning, edits overwrite history. With timestamps on every attribute, you get temporal analysis "for free" — query any attribute at any point in time, diff between snapshots, track trends.

### 9. Reports: Both Visual (Canvas) and Traditional (Document)
**Decision:** Support both Excalidraw canvas compositions and traditional document-style reports as output formats.

**Why:** Sometimes spatial/visual thinking IS the output (a layered market stack, a journey flow, a positioning map). Sometimes you need a structured 10-page document for the board. The same underlying data should feed both. Interactive HTML export is the standout format — stakeholders get a mini research portal, not a static file.

### 10. Architecture for 1000 Companies, Workflow for 50
**Decision:** The data model and performance targets handle up to 1000 entities per project, but the UI and workflow are optimised for the realistic case of 50-100 deeply researched entities.

**Why:** Volume reveals patterns — the user wants to see across a broad market. But deep product teardowns for 1000 companies is unrealistic for a solo analyst. The app needs "research depth tiers" — some entities get full teardowns, some get surface scans, some are just "known to exist." The architecture handles scale; the workflow acknowledges human bandwidth.

---

## Directions NOT Taken (and Why)

### Rejected: Embedded Browser / iframe Panel
**What it was:** A split-pane view where the right side shows a live website in an iframe, so you can browse product sites without leaving the app.

**Why rejected:** Most websites set `X-Frame-Options: DENY` or CSP `frame-ancestors 'none'`. Healthtech/insurance companies with patient portals almost certainly do this. Testing suggested 40-60% of target sites would show a blank frame. The development effort for an unreliable feature isn't justified.

**What we did instead:** Headless capture (Playwright) archives pages as screenshots + HTML snapshots. You browse an archived version, which always works. For live browsing, pywebview can open a secondary window (`webview.create_window(url)`) — it's a real browser, no iframe restrictions. Not an embedded panel, but functional.

### Rejected: Scraping Authenticated Product UIs
**What it was:** Automating Playwright to navigate inside actual products (behind login walls) to capture real in-app screens.

**Why rejected:** Most B2B/healthtech products require accounts, often paid. Trial accounts vary in availability. Automating login flows is fragile and potentially violates ToS. The maintenance burden of keeping scrapers working across constantly-changing auth flows is enormous.

**What we did instead:** Scrape from public UI gallery sites (Mobbin, Screenlane, Refero) where real product UIs are already curated and publicly available. For deep dives, the user downloads and uses the product themselves, then manually uploads captures. The app surfaces the 90% — the user does the last 10% hands-on.

### Rejected: Full Rebuild in New Repository
**What it was:** Copying the codebase to a new repo and rearchitecting from scratch, using the existing code only as reference.

**Why rejected:** Too much working value to discard. The design system, Excalidraw integration, graph views, maps, AI pipeline, 266 tests — all of this would need to be rebuilt. The things that actually need changing (data model, API, navigation model) can be transformed within the existing codebase. Evolving is incremental (ship value at each phase) while rebuilding goes dark for weeks.

### Rejected: Price as a First-Class Entity
**What it was:** Making pricing a dedicated, structured entity type with its own data model (age-banded, postcode-dependent, excess levels for insurance).

**Why rejected:** Pricing depth is highly domain-specific and not universally needed. A design research project has no pricing at all. Even within insurance, deep pricing analysis (full age-banded matrices) requires data that's hard to scrape reliably. The user confirmed headline pricing is sufficient — this becomes just an attribute on a Plan or Tier entity, not its own entity type. Keeps the system generic.

### Rejected: Cloud-Based Mobile Device Emulation
**What it was:** Using services like Appetize.io, BrowserStack, or AWS Device Farm to run actual mobile apps in cloud emulators and capture screenshots programmatically.

**Why rejected:** Massively complex, expensive, and fragile. Requires app binaries (often not publicly available for B2B), account credentials, and per-minute billing. The ROI doesn't justify it when UI gallery sites already have thousands of curated mobile app screenshots. If you need the real experience, download the app yourself.

### Rejected: Notion/Obsidian-Style Document Workspace
**What it was:** Instead of tabs and views, organise everything as interconnected documents (like Notion). Each analysis, each entity, each report is a "page" in a workspace.

**Why rejected (for now):** This is a valid UX paradigm but would be a complete frontend rewrite. The current tab-based SPA with progressive enhancement (lenses) achieves similar flexibility without rearchitecting the UI from scratch. Could revisit in a future major version.

### Rejected: Real-Time Collaborative Access
**What it was:** Multiple users working in the same research project simultaneously.

**Why rejected:** The primary user is a solo analyst. The tool is personal. Collaboration needs are met by exporting reports (interactive HTML, PDF) for stakeholders to review. Adding real-time collaboration (WebSocket sync, conflict resolution, auth, permissions) would be massive complexity for minimal value in the solo-researcher use case.

### Rejected: Framework Migration (React/Vue/Svelte)
**What it was:** Migrating the frontend from vanilla JS to a modern framework for better component architecture.

**Why rejected:** The existing vanilla JS works. Excalidraw is already React (loaded via ESM). Adding a build system, bundler, and framework migration to an already-ambitious evolution plan would delay everything. The vanilla JS approach with module-per-feature (entities.js, lenses.js, capture.js) scales fine for this app's complexity.

---

## The User Journey (Complete)

### How existing features map to the new model:

| Today | Evolved |
|---|---|
| Create project (just a name) | Create project with AI-guided schema interview |
| Add company manually | Add entity at any schema level manually |
| AI Discovery (find companies) | AI Discovery (find entities, populate sub-entity tree) |
| Paste URL (scrape company) | Paste URL (scrape + extract data for entity tree) |
| Deep Research (enrich description) | Deep Research (populate schema attributes + evidence) |
| CSV Import | CSV Import mapped to schema fields at any level |
| Company list | Entity browser with drill-down hierarchy |
| Taxonomy matrix | Taxonomy lens (any entity type) |
| Graph / KG views | Relationship lens (richer entity model) |
| Geographic map | Geographic lens (unchanged) |
| Canvas (Excalidraw) | Synthesis workspace (drag in data + evidence) |
| AI Diagram generation | AI Diagram generation (from richer data) |
| — | Evidence gallery (new) |
| — | Feature comparison matrix (new) |
| — | Journey map viewer (new) |
| — | Temporal diff view (new) |
| — | One-click standard reports (new) |
| — | Custom AI-authored reports (new) |
| — | Market monitoring feed (new) |
| — | "So What?" proactive insights (new) |
| — | Hypothesis tracking (new) |
| — | Research playbooks (new) |
| — | Cross-project intelligence (new) |

### Day-in-the-life workflow:

1. **Morning:** Open project. Review monitoring alerts (pricing changes, new app versions, competitor news). Dismiss or investigate.
2. **Research session:** Find a new company via article. Paste URL → scraper extracts entity tree. Hit Deep Research to fill gaps. Confirm AI's feature extraction against IPID. 15 minutes per company.
3. **Analysis:** Open feature comparison matrix. 28 companies × 40 features. Spot a gap nobody serves. Pin the insight.
4. **Synthesis:** Drag gap analysis + competitor screenshots onto canvas. Annotate. This becomes part of the board update.
5. **Reporting:** Friday — generate Market Overview (one-click). Create custom report for board. AI drafts from your evidence. Review, export as interactive HTML.

---

## Design Principles for the Build

1. **Evolve incrementally** — every phase ships usable value. Don't batch.
2. **Backwards compatible** — existing projects work after every change. No forced migration.
3. **AI proposes, human confirms** — AI does the volume work, human retains judgment.
4. **Evidence-grounded** — every claim traceable to source. No unsupported assertions.
5. **Domain-agnostic** — the tool knows about research methodology, not about insurance or design. Domain knowledge lives in project schemas and templates.
6. **Simple over clever** — vanilla JS, SQLite, Flask. No premature abstractions. Add complexity only when the task demands it.
7. **The Instrument continues** — pure monochrome, zero ornament, no border-radius. The design system carries forward unchanged.
