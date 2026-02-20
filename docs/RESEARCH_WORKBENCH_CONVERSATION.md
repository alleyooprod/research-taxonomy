# Research Workbench — Brainstorming Conversation Transcript

> **Session:** 10
> **Date:** 2026-02-20
> **Participants:** User (Sunny) + Claude
> **Purpose:** Brainstorm the evolution of the Research Taxonomy Library into a full Research Workbench
> **Outcome:** Vision defined, implementation plan created, Phase 1 ready to build

---

## Turn 1: User Opens the Brainstorm

**User:**

Ok I want to brainstorm now to understand how we can get to these outcomes on the app for me. Right now I can use this app to grow my understanding of a market. I can analyse its relationships at a basic level, and I can also look into the product set overall in a market too. This all feels good for a surface level understanding, but I want this to lead to a true product discovery and analysis. This means I need to be able to stay within the app and have a browser option to see these products either their website or the app being able to retrieve the mobile app screenshots directly. I also want to capture screenshots if needed. What are your considerations about this? Expand your thinking here and really consider all options, also question me and challenge me where needed

---

## Turn 2: Claude's Initial Analysis

**Claude:**

### In-App Browsing Options

**The core tension:** pywebview *is* a browser (WebKit on macOS). Embedding a "browser within a browser" has real constraints.

**Option 1 — iframe panel (split view):** Simplest technically. Add a right-side panel that loads a company's URL in an iframe. **Problem:** Many sites set `X-Frame-Options: DENY` or `Content-Security-Policy: frame-ancestors 'none'`. Healthtech companies (especially with patient portals) almost certainly do this. You'd get a blank frame for probably 40-60% of sites.

**Option 2 — pywebview secondary window:** `webview.create_window('Product View', url)` opens a real browser window. Full rendering, no iframe restrictions, cookies/JS all work. You lose the "stay in the app" feel — it's a separate window, not a panel. But you *could* position it as a side-by-side experience with window management.

**Option 3 — Headless capture + static archive:** Use Playwright/Puppeteer on the backend to capture full-page screenshots and even full HTML snapshots (like SingleFile or MHTML). You browse an *archived version* inside the app, not the live site. **Advantage:** You can annotate, compare over time, and it always works (no CORS/iframe issues). **Advantage:** Creates a point-in-time record — useful for competitive analysis.

**Option 4 — System browser with deep-link back:** Open in Safari/Chrome, but with a custom URL scheme (`taxonomy://capture?company=X`) that sends data back to the app. Lowest friction for browsing, but breaks the "stay in app" goal.

**Challenge to user:** When you say "stay within the app," what's the actual workflow you're imagining? Are you (a) Reading product pages while looking at your taxonomy data side-by-side? (b) Quickly checking what a company does, then coming back to categorize? (c) Doing deep product walkthroughs and capturing findings? Because (a) needs a split-pane, (b) is fine with a secondary window, and (c) might be better served by the archival approach.

### Mobile App Screenshots

**Challenge:** "Retrieve mobile app screenshots directly" sounds simple but is actually three very different problems.

**App Store marketing screenshots:** Scrape from Apple App Store / Google Play listing pages. Both have unofficial APIs. These are the polished marketing shots — useful for competitive positioning but not for deep product analysis. **Doable.**

**Actual app UI captures:** This requires running the app — emulators or physical devices. Services like Appetize.io, BrowserStack, or AWS Device Farm provide cloud-based device access. Massively more complex, expensive, and fragile.

**Product Hunt / G2 / Capterra screenshots:** Review platforms often have user-submitted screenshots that show the *real* product. Scraping these could give authentic UI captures without the emulator complexity.

**Challenge:** Are you analysing the *product experience* or the *product positioning*? App Store screenshots tell you how a company wants to be perceived. Actual UI captures tell you what the product really does.

### Screenshot Capture

**For evidence/archival:** Headless Playwright captures on the backend. You click "capture" on a company card, it snapshots their site, stores it with a timestamp. Build a timeline view.

**For annotation/analysis:** Capture a screenshot and import it as a background image in Excalidraw, then annotate on top. Creates a workflow: browse → capture → annotate → link to taxonomy.

**For comparison:** Side-by-side screenshot grids. Capture multiple products, lay them out, spot patterns.

### The Bigger Question

Browsing websites and capturing screenshots is still **observation**. What would actually move you from observation to analysis?
- **Feature extraction** from captured pages via AI
- **Positioning maps** on 2D canvas based on attributes
- **Change detection** — capture sites periodically, diff them
- **Pattern recognition** from structured data

The screenshots and browsing are **inputs**. What are the **outputs** you want?

### Suggested Priority Order
1. Headless site capture (Playwright backend) — high value, technically clean
2. App Store screenshot scraping — quick win, low complexity
3. Screenshot → Excalidraw annotation pipeline
4. Secondary pywebview window for live browsing
5. AI-powered feature extraction from captures

---

## Turn 3: User Provides Detailed Requirements

**User:**

Ok here are my thoughts:
1. With the app as it is, it needs extension so I can do more market-level product analysis (think about what additional research tools could help me compete with an IDC / Mintel / Oxford Economics etc. type of reporting) but that just requires the ability to browse the website to check what they do on top of scraping wider
2. For the real "product" work I need both website and app UIs captured (scraped from all sorts of websites that host the real customer journeys, not the App Store ones) to help me then analyse the full feature set and then build a feature-level view of every company's product. This can be done headless, in fact all capture can be headless as I want an archive in time which we can build on later. There are two aspects of this that are important, some are UI dependent, where seeing the journey leads to this being able to generate full journey maps, and second a customer product feature set (e.g. company a offers these 15 services vs company b offering 10, there is overlap of 4, at this pricepoint, therefore there is an x gap in the market at this price range
3. Having then access to scraped UIs, feature sets, and journeys at a point in time, I can also use this to track change over time, combine with future looking annoucements (eg. a separate feature that scrapes for any product roadmap annoucements that can then be used to create view/reports on where the market is heading). Considering all of this, what are your thoughts now? Where does this app feel stale to be able to support this, where would it need to change, where do you want to challenge me on my requests? Ask more questions of me if you need

---

## Turn 4: Claude Identifies Architectural Gaps and Challenges

**Claude:**

### Where the App Feels Stale

**The data model is the biggest bottleneck.** Right now a "company" is a card with a name, description, some tags, a category, and relationships. That's a taxonomy entry. What you're describing needs a company to be a *rich entity* with: a product catalogue, per-product feature inventories, pricing data, journey stages, temporal snapshots, and a library of captured artefacts.

The current SQLite schema can't hold any of this. It's not a refactor — it's a new data layer.

**The tab-based single-page UI will strain.** Product analysis at this depth needs dedicated workspace views — a feature comparison builder, a journey map viewer, a temporal diff view, a report composer.

**There's no concept of "time" in the app.** Everything is current state. No versioning, no snapshots.

### Challenges

**1. "Scraping real customer journeys"** — How are you getting access to these products? Most healthtech B2B products sit behind authentication. You'd need trial/demo accounts, sales demo recordings, user-submitted screenshots from review platforms, or public help centres.

**2. Competing with IDC/Mintel** — These firms have 100+ analysts, vendor briefings, survey panels, and financial data feeds. You can't replicate their data advantage. But you CAN build a personal research workbench that gives a solo researcher structural rigour. The edge is structure and methodology, not data volume.

**3. Feature extraction from UI screenshots** — AI can help but it's noisy. Help documentation and marketing pages are richer for feature inventories than UI captures. The capture priority should be: help docs & changelogs > marketing pages > product UI screenshots.

**4. Scale question** — How many companies? 20-50 (everything local, manual curation), 200-500 (need automation but manual curation still feasible), or 1000+ (data pipeline problem)? The architecture differs fundamentally for each.

### Proposed Architecture (5 Layers)

1. **Data model expansion** — Company → Product → Plan → Tier → Feature hierarchy + temporal versioning + artefact storage
2. **Capture engine** — Headless Playwright, App Store scrapers, UI gallery scrapers
3. **Extraction & structuring** — AI feature extraction, human review loop, journey classification
4. **Analysis views** — Feature comparison, gap analysis, journey maps, temporal diffs
5. **Reporting & synthesis** — Report templates, export formats, market monitoring

### Questions Back
1. What percentage of products have publicly accessible UIs vs. requiring accounts?
2. How many companies in a typical project?
3. Are analyses for yourself or deliverables for others?
4. If you could only build one layer, which changes your workflow most?
5. Is "company" the atomic unit, or do you think in terms of individual products?

---

## Turn 5: User Answers with Specific Detail

**User:**

Answers:
1. I'm looking at scrapable websites like mobbin, screenlane, refero, appshots, scrnshts, dribbble etc.. And where that fails yes you can then use the App store screen shots AND the main company website which usually has some amount of these. Note all companies will have UIs that I want to scrape
2. This taxonomy project for Olly will likely get too expansive so I'll focus it on market analysis generally and signals etc., in a new project let's say only focused on Health Insurance apps, I will not hold more than 50 companies. However the app should architecturally be built to work with up to a 1000 companies in a single project if needed. The volume is what is powerful to understand patterns in my opinion.
3. Mostly for me, but may be used in outputs for a small internal audience of senior stakeholders (c-suite and board)
4. Layer 4 I suspect has the biggest impact, but none of this can be done without Layer 1, I want this to be a definite direction as I want this app to really evolve
5. I need both layers, the company level which tells me what competition looks like, funding etc. then product (i.e. every specific service offered - e.g. if Health Insurance in the UK, that would mean all their plans, tiers within plans, all products and services with limits within each plan+tier). That is the requirement for me to be able to really conduct product/feature level analysis

---

## Turn 6: Claude Reframes as "Research Workbench"

**Claude:**

### The Reframe

What you're describing isn't a taxonomy tool with product analysis bolted on. It's a **research workbench** that happens to include taxonomy as one capability.

The app's core shouldn't be organized around "companies and their products." It should be organized around **research itself**.

Current mental model: `Project → Companies → [taxonomy, relationships, tags]`

What's needed:
```
Project
  ├── Research Schema (what entities exist, what attributes matter)
  ├── Evidence Library (everything captured)
  ├── Structured Data (extracted from evidence, human-validated)
  ├── Analysis (comparisons, gaps, patterns)
  └── Synthesis (reports, maps, narratives)
```

The company isn't the centre. The **research question** is.

### Schema Editor as First-Class Feature

When you create a project, you define (or select a template for) your entity schema. Each level has configurable attributes. The app doesn't know about insurance or design — it knows about **entities with attributes in hierarchies**.

### AI as Research Partner

AI should function like a research analyst: classifying captures, extracting features, cross-referencing sources, flagging contradictions, surfacing patterns, and generating hypotheses — not just a pipeline stage.

### Views Are Lenses, Not Tabs

Different "lenses" on the same data: taxonomy lens, competitive lens, product lens, design lens, temporal lens, signals lens. A project uses whichever lenses are relevant. Lenses activate based on available data.

### Challenges

**Volume argument:** 1000 companies × deep hierarchies = data curation problem. Who populates features for 1000 companies? Need "research depth tiers."

**Layer 4 without Layer 2/3:** A report is only as good as the data. If every company has standardised features, gap analysis becomes a SQL query. Layer 1 essentially IS Layer 4 if done right.

**Journey maps from galleries:** UI galleries show individual screens, rarely in flow order. Need AI to classify and sequence — semi-automated at best.

### Proposed Phases
1. Data model evolution (foundation)
2. Capture engine (collection)
3. Extraction & structuring (AI + human review)
4. Analysis views (lenses)
5. Reporting & synthesis (output)

### Remaining Questions
1. Should different "project types" have different defaults?
2. Who defines the canonical feature vocabulary?
3. How deep does pricing data need to go?
4. Ready to start planning Phase 1?

---

## Turn 7: User Refines Further, Challenges "Price as Entity"

**User:**

Answers and additional thoughts:
1. Yes this entity structure should be flexible per project but MUST be able to be amended if needed (although this should be rare).
2. For feature standardisation, let's go with the approach you mentioned earlier i.e. the boring documentation on the company's publicly available documentation likely grounds this scope (think IPIDs for insurance), so these MUST be used in tandem with scraped UI etc. to ground the LLMs generation of the feature set. Once done, any doubts the LLM has needs to be surfaced for me to then confirm
3. This just needs to be headline price and again here scraping wide and far with a show of sources will help drive value here. Price is not the right entity concept though as for a given project I might not even care about it. I might have a project just looking at design agencies where I'm more interested in scraping their websites to then do analysis on their design principles. In this sense there's almost no commercial analysis being done at all, but just a learning focused view on design theory in the market. I want this tool to build towards that as well
4. I want you to consider what I've said again and think about how else you can approach this

---

## Turn 8: Claude Rethinks from Ground Up

**Claude:**

### The Core Abstraction: Research, Not Data Management

The key insight from the user's answers: this tool isn't about insurance, or healthtech, or even products. A project could be about design agencies where you're studying visual principles with zero commercial analysis. The *method* is the same — collect, structure, extract, analyse, report — but the *subject matter and schema* change completely.

### Schema Must Support Graphs, Not Just Trees

The design research use case reveals this: products exhibit design patterns, patterns appear across products. This is many-to-many, not parent-child. The schema system needs entity types with relationships between them.

### Evidence Library as Ground Truth

Everything captured goes into a timestamped evidence library. Every piece linked to entities and timestamped. Creates temporal dimension automatically.

### IPIDs and Equivalent Documents

Every regulated industry has standardised disclosure documents. Insurance has IPIDs. Finance has KIDs. Pharma has SmPCs. These are the most reliable source for feature extraction. The app should have "canonical document types" per project template.

### AI as Research Partner (Full Vision)

- During collection: classifies and groups captures, asks for review of uncertain items
- During extraction: cross-references sources, flags contradictions, shows confidence
- During analysis: surfaces patterns, proposes hypotheses
- During monitoring: detects changes, highlights diffs

### Lenses Activate Based on Data

Each lens has activation criteria. Unavailable lenses show as dimmed with hints about what data is needed to activate them. This provides implicit guidance for the research workflow.

### Mapping Current → Evolved

All existing features map cleanly:
- Project selection → Project (with schema + evidence library)
- Company list → Entity list (any entity type)
- Taxonomy matrix → Taxonomy lens
- Graph/KG → Relationship lens
- Map → Geographic lens
- Canvas → Synthesis workspace
- AI Discovery → Collection agent

### What's Genuinely New
- Schema editor
- Evidence library
- Extraction pipeline
- Product/feature analysis views
- Temporal tracking + diff views
- Report composer

---

## Turn 9: User Confirms Direction, Asks About Complete User Journey

**User:**

1. Both. Sometimes the visual diagramming helps — canvas can be play or formal output. Reports need both visual and traditional-document formats.
2. For schema amendment, the more important thing is having a short but clearly challenging back/forth process at project setup where the app helps define the right entity structure.
3. Less worried about source reconciliation — if deep diving a single company, will download the app and experience it directly. The app needs to surface 90% of the experience to guide where to focus attention.
4. Considered copying the entire app to a new repo and rebuilding from scratch, but that feels like overkill.
5. The Research Workbench is the right framing. I want to lean into that.

---

## Turn 10: Claude Recommends Evolve Over Rebuild, Proposes Phase 1

**Claude:**

### Don't Rebuild. Evolve.

What you have that carries forward: The Instrument design system, Flask + blueprints, Excalidraw integration, Cytoscape graphs, Leaflet maps, AI integration, 266 tests, pywebview shell.

What needs to change: database schema, API layer, navigation model, concept of "project."

That's a deep refactor of the data layer and progressive UI evolution — not a rewrite.

### Phase 1: The Research Foundation
1. Schema system (flexible entity hierarchy per project)
2. Entity data model (new DB tables, migration from flat companies)
3. Temporal versioning (timestamped attributes)
4. Evidence library (artefact storage)
5. API layer update (entity CRUD, backwards compatible)
6. Project setup flow (AI-guided interview)
7. Entity browser UI (drill-down hierarchy)
8. Existing view compatibility (matrix, graph, maps accept any entity type)
9. Tests (migrate + new coverage)

### Advanced Features (Phase 7)
- "So What?" Engine — proactive insight generation
- Hypothesis Tracking — state beliefs, track evidence for/against
- Research Playbooks — reusable methodologies
- Cross-Project Intelligence — detect overlapping entities
- Evidence Provenance Chains — every claim traceable to source

---

## Turn 11: User Asks About Non-Commercial Use Case + Report Generator

**User:**

A few more things:
1. How does this work for the design principles research question?
2. For Canvas + Document view, I want a report generator that pulls everything together automatically. Put in audience, questions, and it builds. Standard reports at the click of a button too.
3. Agree evolve is better.
4. What other extensions or push do you want to give this app?

---

## Turn 12: Claude Walks Through Design Principles Use Case

**Claude:**

### Design Principles — Schema as Graph

The insurance project has a tree hierarchy. But "understand design principles of best-in-class digital product design" has a **graph** structure: Products ↔ Design Principles (many-to-many, linked through evidence).

The AI-guided setup would propose: "Two primary entity types: Products and Design Principles, linked through evidence captures. Browse by product or by principle."

Active lenses: Taxonomy, Design, Relationship, Temporal. No competitive or product/pricing lens — they stay hidden.

### Report Generator — Two Modes

**Standard reports (one-click):** Market Overview, Competitive Landscape, Product Teardown, Design Pattern Library, Change Report. Available/unavailable based on data completeness.

**Custom reports:** Input audience, questions, tone/format. AI drafts from YOUR data (not general knowledge). Every claim cites source evidence. Flags gaps in evidence.

**Export:** Interactive HTML microsite, PDF, Canvas composition.

### Further Extensions

- **"So What?" Engine:** Proactive pattern detection and insight surfacing from structured data
- **Hypothesis Tracking:** State beliefs, track supporting/contradicting evidence, surface "insufficient data" areas
- **Research Playbooks:** Reusable methodologies applied to new projects
- **Cross-Project Intelligence:** Detect overlapping entities, carry forward data
- **Evidence Provenance:** Every claim → analysis → data → evidence → source chain
- **Watchlist/Monitoring:** Track company websites, app stores, news for changes

---

## Turn 13: User Asks for Full User Journey Reassurance

**User:**

One more thing, the app right now has deep research, link based data scraping etc. I want reassurance that this fundamental feature isn't lost. For me this is how I will keep adding new companies to a given research project. Basically you need to show me and describe how the user journey will be for me using this app with all its features

---

## Turn 14: Claude Walks Through Complete User Journey

**Claude provided a comprehensive walkthrough of every feature, organized as:**

### Act 1: Project Setup
- AI-guided interview (new) with optional quick-create (preserves current simplicity)

### Act 2: Populating Research (all existing features preserved + enhanced)
- **AI Discovery** — same interaction, now also seeds sub-entities
- **Link-Based Scraping** — same URL input, now extracts product-level data too
- **Deep Research** — same button, now populates schema attributes + flags confidence issues
- **Manual Entry** — same flow, forms adapt to project schema
- **CSV Import** — same flow, column mapping now handles any schema level
- **Bulk Discovery + Scraping (new)** — "Market Scan" combines everything as background job

### Act 3: Working With Data (existing views enhanced)
- Entity list — same cards, now show evidence counts + drill-down
- Taxonomy matrix — same component, accepts any entity type
- Graph/KG — same Cytoscape, richer entity model
- Map — same Leaflet, unchanged
- Canvas — same Excalidraw, can now drag in structured data
- AI Discovery — same tab, gains "capture" section for scraping job management

### Act 4: Analysis (new, built on existing foundations)
- Feature comparison matrix
- Evidence gallery
- Journey maps
- Temporal diffs

### Act 5: Reporting (new)
- One-click standard reports
- Custom AI-authored reports
- Export: PDF, interactive HTML, canvas composition

### Act 6: Monitoring (new, background)
- Website change detection
- App Store monitoring
- News/announcement tracking

### Day-in-the-life summary
Morning monitoring → research session (15 min per company) → analysis (spot gaps) → synthesis (canvas) → reporting (Friday board update)

---

## Turn 15: User Confirms and Requests Documentation

**User:**

Ok great. Let's approach it this way. We need to create two files:
1. The implementation plan with comprehensive details
2. A full copy of this conversation so we don't lose context

Plus setup maintenance of the implementation plan as a memory file.

**Claude proposed three files:**
1. `IMPLEMENTATION_PLAN.md` — living document, project root
2. `docs/RESEARCH_WORKBENCH_VISION.md` — distilled vision + decisions
3. `docs/RESEARCH_WORKBENCH_CONVERSATION.md` — raw transcript

**User confirmed and added:** The distilled vision doc must include directions NOT taken and WHY.

---

## End of Brainstorming Session

**Outcome:** Full vision defined, three documentation files created, implementation plan ready for Phase 1 execution. Next session begins building Phase 1 (schema system + entity data model + project setup).
