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
    is_active INTEGER DEFAULT 1
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

-- Indexes
CREATE INDEX IF NOT EXISTS idx_categories_project ON categories(project_id);
CREATE INDEX IF NOT EXISTS idx_companies_url ON companies(url);
CREATE INDEX IF NOT EXISTS idx_companies_category ON companies(category_id);
CREATE INDEX IF NOT EXISTS idx_companies_project ON companies(project_id);
CREATE INDEX IF NOT EXISTS idx_sources_company ON company_sources(company_id);
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
