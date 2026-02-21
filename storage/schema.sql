-- Projects table: each research project has its own taxonomy
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    purpose TEXT,
    outcome TEXT,
    description TEXT,
    seed_categories TEXT,   -- JSON array of starting category names
    example_links TEXT,     -- JSON array of example URLs
    market_keywords TEXT,   -- JSON array of relevant keywords for triage
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1,
    features TEXT DEFAULT '{}',   -- JSON: {"discovery_enabled": true, "dimensions_enabled": true}
    entity_schema TEXT             -- JSON: research workbench entity schema definition
);

-- Categories table: the living taxonomy (scoped per project)
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id),
    description TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1,
    merged_into_id INTEGER REFERENCES categories(id),
    synonyms TEXT,
    color TEXT,
    scope_note TEXT,
    inclusion_criteria TEXT,
    exclusion_criteria TEXT,
    UNIQUE(project_id, name)
);

-- Companies table: the core data (scoped per project)
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    what TEXT,
    target TEXT,
    products TEXT,
    funding TEXT,
    geography TEXT,
    tam TEXT,
    category_id INTEGER REFERENCES categories(id),
    subcategory_id INTEGER REFERENCES categories(id),
    tags TEXT,  -- JSON array stored as text
    raw_research TEXT,  -- Full research output for re-classification
    source_url TEXT,  -- Original input URL before resolution
    processed_at TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    confidence_score REAL,
    logo_url TEXT,
    employee_range TEXT,
    founded_year INTEGER,
    funding_stage TEXT,
    total_funding_usd REAL,
    hq_city TEXT,
    hq_country TEXT,
    linkedin_url TEXT,
    last_verified_at TEXT,
    is_starred INTEGER DEFAULT 0,
    is_deleted INTEGER DEFAULT 0,
    deleted_at TEXT,
    status TEXT DEFAULT 'active',
    business_model TEXT,
    company_stage TEXT,
    primary_focus TEXT,
    relationship_status TEXT,  -- watching | to_reach_out | in_conversation | met | partner | not_relevant
    relationship_note TEXT,
    enrichment_status TEXT,    -- pending | enriching | enriched | failed
    -- Pricing fields
    pricing_model TEXT,        -- freemium | subscription | usage_based | per_seat | tiered | custom | one_time | marketplace
    pricing_b2c_low REAL,      -- monthly USD low end
    pricing_b2c_high REAL,     -- monthly USD high end
    pricing_b2b_low REAL,      -- per-seat/month USD low end
    pricing_b2b_high REAL,     -- per-seat/month USD high end
    has_free_tier INTEGER DEFAULT 0,
    revenue_model TEXT,        -- SaaS | hardware | services | hybrid | marketplace_commission | advertising
    pricing_tiers TEXT,        -- JSON: [{"name":"Basic","price":29,"features":["..."]}]
    pricing_notes TEXT,        -- free-text caveats
    UNIQUE(project_id, url)
);

-- Company sources: tracks all URLs used to research a company
CREATE TABLE IF NOT EXISTS company_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    source_type TEXT DEFAULT 'research',  -- research | manual | re-research
    added_at TEXT DEFAULT (datetime('now'))
);

-- Processing jobs: enables resumability
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    batch_id TEXT NOT NULL,
    url TEXT NOT NULL,
    source_url TEXT,
    status TEXT DEFAULT 'pending',  -- pending | resolving | researching | classifying | done | error
    error_message TEXT,
    attempts INTEGER DEFAULT 0,
    company_id INTEGER REFERENCES companies(id),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Taxonomy evolution log
CREATE TABLE IF NOT EXISTS taxonomy_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    change_type TEXT NOT NULL,  -- add | merge | split | rename | deactivate | move
    details TEXT NOT NULL,  -- JSON description
    reason TEXT,
    affected_category_ids TEXT,  -- JSON array
    created_at TEXT DEFAULT (datetime('now'))
);

-- Triage results: pre-validation before processing
CREATE TABLE IF NOT EXISTS triage_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    batch_id TEXT NOT NULL,
    original_url TEXT NOT NULL,
    resolved_url TEXT,
    status TEXT DEFAULT 'pending',  -- pending | valid | suspect | error
    reason TEXT,
    title TEXT,
    meta_description TEXT,
    scraped_text_preview TEXT,
    is_accessible INTEGER DEFAULT 0,
    user_action TEXT,  -- skip | replace | include | NULL
    replacement_url TEXT,
    user_comment TEXT,  -- User annotation on triage decision
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Company notes: user annotations that survive re-research
CREATE TABLE IF NOT EXISTS company_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    is_pinned INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Company versions: snapshot history for undo/restore
CREATE TABLE IF NOT EXISTS company_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    snapshot TEXT NOT NULL,  -- JSON of all company fields at that point
    change_description TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Company events: lifecycle tracking (acquired, shut down, funding round, etc.)
CREATE TABLE IF NOT EXISTS company_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,  -- funding_round | acquired | shut_down | launched | pivot | partnership
    description TEXT,
    event_date TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Map layouts: saved tile grid configurations per project
CREATE TABLE IF NOT EXISTS map_layouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL DEFAULT 'Default',
    layout_data TEXT NOT NULL,  -- JSON with category ordering, visibility, custom positions
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, name)
);

-- Saved views: named filter combinations per project
CREATE TABLE IF NOT EXISTS saved_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    filters TEXT NOT NULL,  -- JSON: {category_id, tags, geography, stage, search, starred, needs_enrichment}
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, name)
);

-- Share tokens: read-only project links for external viewers
CREATE TABLE IF NOT EXISTS share_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    token TEXT NOT NULL UNIQUE,
    label TEXT DEFAULT 'Shared link',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT
);

-- Activity log: project-scoped event feed
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    action TEXT NOT NULL,          -- company_added | company_edited | company_deleted | taxonomy_changed | batch_started | batch_completed | report_generated
    description TEXT,
    entity_type TEXT,              -- company | category | batch | report
    entity_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Notification preferences per project
CREATE TABLE IF NOT EXISTS notification_prefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    slack_webhook_url TEXT,
    notify_batch_complete INTEGER DEFAULT 1,
    notify_taxonomy_change INTEGER DEFAULT 1,
    notify_new_company INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id)
);

-- Saved market reports
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    report_id TEXT NOT NULL UNIQUE,  -- UUID fragment used for polling
    category_name TEXT NOT NULL,
    company_count INTEGER DEFAULT 0,
    model TEXT,
    markdown_content TEXT,           -- Full markdown report
    status TEXT DEFAULT 'pending',   -- pending | complete | error
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Research sessions: deep dive and open-ended research
CREATE TABLE IF NOT EXISTS research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL,
    scope_type TEXT NOT NULL,        -- 'project', 'category', 'company', 'custom'
    scope_id INTEGER,
    prompt TEXT NOT NULL DEFAULT '',
    context TEXT,
    result TEXT,
    model TEXT,
    status TEXT DEFAULT 'pending',   -- pending, running, completed, failed
    cost_usd REAL,
    duration_ms INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Research templates: user-editable prompt templates per project
CREATE TABLE IF NOT EXISTS research_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    prompt_template TEXT NOT NULL,
    scope_type TEXT DEFAULT 'project',  -- project | category | company
    is_default INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_templates_project ON research_templates(project_id);

-- Indexes (basic)
CREATE INDEX IF NOT EXISTS idx_categories_project ON categories(project_id);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
CREATE INDEX IF NOT EXISTS idx_companies_url ON companies(url);
CREATE INDEX IF NOT EXISTS idx_companies_category ON companies(category_id);
CREATE INDEX IF NOT EXISTS idx_companies_project ON companies(project_id);
CREATE INDEX IF NOT EXISTS idx_sources_company ON company_sources(company_id);
CREATE INDEX IF NOT EXISTS idx_sources_url ON company_sources(url);
CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_triage_batch ON triage_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_triage_status ON triage_results(status);
CREATE INDEX IF NOT EXISTS idx_triage_project ON triage_results(project_id);
CREATE INDEX IF NOT EXISTS idx_companies_starred ON companies(is_starred);
CREATE INDEX IF NOT EXISTS idx_notes_company ON company_notes(company_id);
CREATE INDEX IF NOT EXISTS idx_versions_company ON company_versions(company_id);
CREATE INDEX IF NOT EXISTS idx_events_company ON company_events(company_id);
CREATE INDEX IF NOT EXISTS idx_share_tokens_token ON share_tokens(token);
CREATE INDEX IF NOT EXISTS idx_share_tokens_project ON share_tokens(project_id);
CREATE INDEX IF NOT EXISTS idx_activity_project ON activity_log(project_id);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at);
CREATE INDEX IF NOT EXISTS idx_reports_project ON reports(project_id);
CREATE INDEX IF NOT EXISTS idx_reports_report_id ON reports(report_id);

CREATE INDEX IF NOT EXISTS idx_research_project ON research(project_id);

-- Canvases: visual workspaces for arranging companies and notes
CREATE TABLE IF NOT EXISTS canvases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    title TEXT NOT NULL DEFAULT 'Untitled Canvas',
    data TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_canvases_project ON canvases(project_id);

-- Research dimensions: EAV schema for dynamic company attributes
CREATE TABLE IF NOT EXISTS research_dimensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    data_type TEXT DEFAULT 'text',  -- text | number | boolean | enum | json
    enum_values TEXT,               -- JSON array for enum type
    source TEXT,                    -- ai_discovered | user_defined
    ai_prompt TEXT,                 -- prompt used to populate this dimension
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, slug)
);

CREATE TABLE IF NOT EXISTS company_dimensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    dimension_id INTEGER NOT NULL REFERENCES research_dimensions(id) ON DELETE CASCADE,
    value TEXT,
    confidence REAL,
    source TEXT,                    -- ai | manual
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(company_id, dimension_id)
);

-- Product discovery: context files and analyses
CREATE TABLE IF NOT EXISTS project_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    filename TEXT,
    content TEXT NOT NULL,
    context_type TEXT DEFAULT 'roadmap',  -- roadmap | feature_list | product_spec
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS discovery_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    analysis_type TEXT NOT NULL,    -- feature_landscape | gap_analysis | competitive_matrix
    title TEXT,
    parameters TEXT,                -- JSON config
    result TEXT,                    -- JSON result
    context_id INTEGER REFERENCES project_contexts(id) ON DELETE SET NULL,
    status TEXT DEFAULT 'pending',  -- pending | running | completed | failed
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dimensions_project ON research_dimensions(project_id);
CREATE INDEX IF NOT EXISTS idx_company_dimensions_company ON company_dimensions(company_id);
CREATE INDEX IF NOT EXISTS idx_company_dimensions_dimension ON company_dimensions(dimension_id);
CREATE INDEX IF NOT EXISTS idx_contexts_project ON project_contexts(project_id);
CREATE INDEX IF NOT EXISTS idx_analyses_project ON discovery_analyses(project_id);
CREATE INDEX IF NOT EXISTS idx_analyses_type ON discovery_analyses(analysis_type);

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(project_id, is_deleted, category_id);
CREATE INDEX IF NOT EXISTS idx_companies_subcategory ON companies(subcategory_id);
CREATE INDEX IF NOT EXISTS idx_jobs_batch_status ON jobs(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_notes_company_pinned ON company_notes(company_id, is_pinned);
CREATE INDEX IF NOT EXISTS idx_triage_batch_status ON triage_results(batch_id, status);

-- ═══════════════════════════════════════════════════════════════
-- RESEARCH WORKBENCH: Entity System (Phase 1)
-- ═══════════════════════════════════════════════════════════════

-- Entity type definitions: per-project schema for entity types
CREATE TABLE IF NOT EXISTS entity_type_defs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    icon TEXT DEFAULT 'circle',
    parent_type_slug TEXT,              -- slug of parent entity type (NULL for root types)
    attributes_json TEXT DEFAULT '[]',  -- JSON array of attribute definitions
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, slug)
);

-- Entity relationship definitions: named relationship types between entity types
CREATE TABLE IF NOT EXISTS entity_relationship_defs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    from_type_slug TEXT NOT NULL,
    to_type_slug TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, name)
);

-- Entities: the actual entity instances
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    type_slug TEXT NOT NULL,            -- references entity_type_defs.slug
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    parent_entity_id INTEGER REFERENCES entities(id),  -- hierarchy (Company > Product > Plan)
    category_id INTEGER REFERENCES categories(id),     -- taxonomy classification
    is_starred INTEGER DEFAULT 0,
    is_deleted INTEGER DEFAULT 0,
    deleted_at TEXT,
    status TEXT DEFAULT 'active',       -- active | draft | archived
    confidence_score REAL,
    tags TEXT,                          -- JSON array
    raw_research TEXT,                  -- full LLM output from research
    source TEXT DEFAULT 'manual',       -- manual | ai | import | migration
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Entity attributes: timestamped values for temporal versioning
-- Each row is a point-in-time value. Current = most recent per attr_slug.
CREATE TABLE IF NOT EXISTS entity_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    attr_slug TEXT NOT NULL,            -- references attribute slug from entity_type_defs
    value TEXT,                         -- all values stored as text (JSON for complex types)
    source TEXT DEFAULT 'manual',       -- manual | ai | import | scrape
    confidence REAL,                    -- 0.0 to 1.0
    captured_at TEXT DEFAULT (datetime('now')),  -- when this value was captured
    snapshot_id INTEGER REFERENCES entity_snapshots(id)  -- groups updates from same session
);

-- Entity relationships: many-to-many between entities (graph edges)
CREATE TABLE IF NOT EXISTS entity_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,    -- references entity_relationship_defs.name
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(from_entity_id, to_entity_id, relationship_type)
);

-- Entity snapshots: groups attribute updates from a single capture session
CREATE TABLE IF NOT EXISTS entity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    description TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Evidence: captured artefacts linked to entities
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,         -- screenshot | document | page_archive | video | other
    file_path TEXT NOT NULL,             -- path relative to project evidence directory
    source_url TEXT,                     -- original URL where captured
    source_name TEXT,                    -- human-readable source (Mobbin, App Store, etc.)
    metadata_json TEXT DEFAULT '{}',     -- additional metadata (dimensions, file size, etc.)
    captured_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for entity system
CREATE INDEX IF NOT EXISTS idx_entity_type_defs_project ON entity_type_defs(project_id);
CREATE INDEX IF NOT EXISTS idx_entity_rel_defs_project ON entity_relationship_defs(project_id);
CREATE INDEX IF NOT EXISTS idx_entities_project ON entities(project_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(project_id, type_slug);
CREATE INDEX IF NOT EXISTS idx_entities_parent ON entities(parent_entity_id);
CREATE INDEX IF NOT EXISTS idx_entities_category ON entities(category_id);
CREATE INDEX IF NOT EXISTS idx_entities_active ON entities(project_id, is_deleted, type_slug);
CREATE INDEX IF NOT EXISTS idx_entity_attrs_entity ON entity_attributes(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_attrs_slug ON entity_attributes(entity_id, attr_slug);
CREATE INDEX IF NOT EXISTS idx_entity_attrs_captured ON entity_attributes(entity_id, attr_slug, captured_at);
CREATE INDEX IF NOT EXISTS idx_entity_attrs_snapshot ON entity_attributes(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_entity_rels_from ON entity_relationships(from_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_rels_to ON entity_relationships(to_entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_snapshots_project ON entity_snapshots(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_entity ON evidence(entity_id);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(entity_id, evidence_type);

-- ═══════════════════════════════════════════════════════════════
-- RESEARCH WORKBENCH: Extraction System (Phase 3)
-- ═══════════════════════════════════════════════════════════════

-- Extraction jobs: track AI extraction requests against evidence
CREATE TABLE IF NOT EXISTS extraction_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',       -- pending | running | completed | failed
    source_type TEXT NOT NULL DEFAULT 'evidence',  -- evidence | url | text
    source_ref TEXT,                               -- URL or description of source
    model TEXT,                                    -- LLM model used
    cost_usd REAL DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    result_count INTEGER DEFAULT 0,                -- number of attributes extracted
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Extraction results: individual extracted attribute values pending review
CREATE TABLE IF NOT EXISTS extraction_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES extraction_jobs(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    attr_slug TEXT NOT NULL,
    extracted_value TEXT,
    confidence REAL DEFAULT 0.5,                   -- 0.0 to 1.0
    reasoning TEXT,                                -- AI's reasoning for this extraction
    source_evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',         -- pending | accepted | rejected | edited
    reviewed_value TEXT,                           -- user-edited value (if status=edited)
    reviewed_at TEXT,
    needs_evidence INTEGER DEFAULT 0,              -- 1 if flagged as needing more evidence
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for extraction system
CREATE INDEX IF NOT EXISTS idx_extraction_jobs_project ON extraction_jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_extraction_jobs_entity ON extraction_jobs(entity_id);
CREATE INDEX IF NOT EXISTS idx_extraction_jobs_status ON extraction_jobs(status);
CREATE INDEX IF NOT EXISTS idx_extraction_jobs_evidence ON extraction_jobs(evidence_id);
CREATE INDEX IF NOT EXISTS idx_extraction_results_job ON extraction_results(job_id);
CREATE INDEX IF NOT EXISTS idx_extraction_results_entity ON extraction_results(entity_id);
CREATE INDEX IF NOT EXISTS idx_extraction_results_status ON extraction_results(entity_id, status);
CREATE INDEX IF NOT EXISTS idx_extraction_results_attr ON extraction_results(entity_id, attr_slug);
CREATE INDEX IF NOT EXISTS idx_extraction_results_evidence ON extraction_results(source_evidence_id);

-- ═══════════════════════════════════════════════════════════
-- Feature Standardisation: Canonical vocabulary per project
-- ═══════════════════════════════════════════════════════════

-- Canonical features: the standard vocabulary for cross-entity comparison
CREATE TABLE IF NOT EXISTS canonical_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    attr_slug TEXT NOT NULL,                    -- which attribute this vocabulary covers (e.g. "features")
    canonical_name TEXT NOT NULL,               -- the standard name (e.g. "Mental Health Support")
    description TEXT,                           -- optional definition
    category TEXT,                              -- optional grouping (e.g. "Wellbeing", "Core Cover")
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, attr_slug, canonical_name)
);

-- Feature mappings: map extracted raw values to canonical names
CREATE TABLE IF NOT EXISTS feature_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_feature_id INTEGER NOT NULL REFERENCES canonical_features(id) ON DELETE CASCADE,
    raw_value TEXT NOT NULL,                    -- the extracted text (e.g. "mental health cover")
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(canonical_feature_id, raw_value)
);

CREATE INDEX IF NOT EXISTS idx_canonical_features_project ON canonical_features(project_id, attr_slug);
CREATE INDEX IF NOT EXISTS idx_feature_mappings_canonical ON feature_mappings(canonical_feature_id);
