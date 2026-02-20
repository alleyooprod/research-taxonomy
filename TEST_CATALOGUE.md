# Test Catalogue — Research Taxonomy Library

> **Last updated:** 2026-02-20
> **Total tests:** 266 pytest + 132 Playwright spec + 18 integration scripts = **416 tests**
> **Status:** All 266 pytest tests passing

---

## Quick Reference: Run Commands

```bash
# --- FULL SUITES ---
pytest tests/ -v                           # All 266 pytest tests (~17s)
npm run test:e2e                           # All Playwright spec tests
npm run test:e2e:headed                    # Playwright with browser visible

# --- BY FEATURE AREA (pytest markers) ---
pytest -m projects                         # Project management (15 tests)
pytest -m companies                        # Company CRUD, bulk, notes (42 tests)
pytest -m taxonomy                         # Taxonomy, categories, review (9 tests)
pytest -m canvas                           # Canvas workspace, diagrams (13 tests)
pytest -m data                             # Export, import, stats, tags (21 tests)
pytest -m processing                       # Batch processing, triage (11 tests)
pytest -m research                         # Research sessions, reports (13 tests)
pytest -m ai                               # AI discovery, chat, models (16 tests)
pytest -m discovery                        # Feature landscape, gaps (15 tests)
pytest -m dimensions                       # Custom dimensions CRUD (17 tests)
pytest -m settings                         # Settings, backups, logs (22 tests)
pytest -m static                           # Static files, health (16 tests)
pytest -m db                               # Database layer (18 tests)
pytest -m security                         # CSRF, soft-delete, atomicity (13 tests)
pytest -m async_jobs                       # Async job system (10 tests)

# --- BY SINGLE FILE ---
pytest tests/test_api_companies.py -v      # Just company API tests
pytest tests/test_api_settings.py -v       # Just settings tests

# --- SPECIFIC TEST ---
pytest tests/test_api_companies.py::TestNotes::test_add_note -v

# --- PLAYWRIGHT SPECIFIC ---
npx playwright test e2e/canvas.spec.js     # Just canvas e2e
npx playwright test --grep "bulk"          # Tests matching pattern

# --- INTEGRATION SCRIPTS (.cjs) ---
node e2e/test_canvas_fixes.cjs             # Canvas fixes verification
node e2e/test_diagram_generation.cjs       # AI diagram generation
node e2e/take_evidence.cjs                 # Screenshot all features
node e2e/take_ux_evidence.cjs              # Screenshot UX updates
```

---

## Pytest Test Files (266 tests)

### test_api_projects.py — `pytest -m projects` (15 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| PRJ-CREATE-01 | `TestCreateProject::test_create_minimal` | POST /api/projects with just name |
| PRJ-CREATE-02 | `TestCreateProject::test_create_with_all_fields` | All optional fields (purpose, outcome, seeds, etc.) |
| PRJ-CREATE-03 | `TestCreateProject::test_create_seeds_categories` | Categories auto-created from seed list |
| PRJ-CREATE-04 | `TestCreateProject::test_create_rejects_missing_name` | 400 on missing name |
| PRJ-CREATE-05 | `TestCreateProject::test_create_rejects_empty_name` | 400 on empty string name |
| PRJ-CREATE-06 | `TestCreateProject::test_create_multiple_projects` | Multiple projects coexist |
| PRJ-LIST-01 | `TestListProjects::test_list_empty` | GET /api/projects returns [] |
| PRJ-LIST-02 | `TestListProjects::test_list_returns_created_projects` | Created projects appear in list |
| PRJ-GET-01 | `TestGetProject::test_get_existing` | GET /api/projects/<id> returns project |
| PRJ-GET-02 | `TestGetProject::test_get_nonexistent` | 404 for invalid ID |
| PRJ-UPDATE-01 | `TestUpdateProject::test_update_purpose` | POST updates and persists |
| PRJ-UPDATE-02 | `TestUpdateProject::test_update_multiple_fields` | Multiple fields in one update |
| PRJ-FEAT-01 | `TestToggleFeature::test_toggle_feature` | Feature toggle returns updated features |
| PRJ-FEAT-02 | `TestToggleFeature::test_toggle_missing_feature_name` | 400 without feature name |
| PRJ-FEAT-03 | `TestToggleFeature::test_toggle_nonexistent_project` | 404 for invalid project |

### test_api_companies.py — `pytest -m companies` (42 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| CMP-ADD-01 | `TestAddCompany::test_add_basic` | POST /api/companies/add creates company |
| CMP-ADD-02 | `TestAddCompany::test_add_with_name_only` | Name + URL sufficient |
| CMP-ADD-03 | `TestAddCompany::test_add_rejects_missing_url` | 400 without URL |
| CMP-ADD-04 | `TestAddCompany::test_add_rejects_missing_project_id` | 400 without project_id |
| CMP-LIST-01 | `TestListCompanies::test_list_empty` | Empty project returns [] |
| CMP-LIST-02 | `TestListCompanies::test_list_returns_created` | Companies appear after creation |
| CMP-LIST-03 | `TestListCompanies::test_list_search_filter` | ?search= filters by name |
| CMP-LIST-04 | `TestListCompanies::test_list_starred_filter` | ?starred=1 filters correctly |
| CMP-LIST-05 | `TestListCompanies::test_list_sort_by_name` | ?sort_by=name returns sorted |
| CMP-LIST-06 | `TestListCompanies::test_list_with_category_filter` | ?category_id= filters |
| CMP-GET-01 | `TestGetCompany::test_get_existing` | Returns company with notes + events |
| CMP-GET-02 | `TestGetCompany::test_get_nonexistent` | 404 for invalid ID |
| CMP-UPD-01 | `TestUpdateCompany::test_update_fields` | Updates what/target, persists |
| CMP-UPD-02 | `TestUpdateCompany::test_update_funding_fields` | Funding stage + amount |
| CMP-DEL-01 | `TestDeleteCompany::test_soft_delete` | Soft-deleted not in listing |
| CMP-DEL-02 | `TestDeleteCompany::test_deleted_appears_in_trash` | Appears in /api/trash |
| CMP-STAR-01 | `TestStarCompany::test_star_toggle` | Star on, star off |
| CMP-STAR-02 | `TestStarCompany::test_star_nonexistent` | 404 for invalid company |
| CMP-REL-01 | `TestRelationship::test_set_relationship` | Set watching + note |
| CMP-REL-02 | `TestRelationship::test_update_relationship_status` | All 6 statuses accepted |
| CMP-NOTE-01 | `TestNotes::test_add_note` | Add note returns ID |
| CMP-NOTE-02 | `TestNotes::test_list_notes` | Multiple notes returned |
| CMP-NOTE-03 | `TestNotes::test_update_note` | Update content |
| CMP-NOTE-04 | `TestNotes::test_delete_note` | Delete by ID |
| CMP-NOTE-05 | `TestNotes::test_pin_note` | Pin toggle |
| CMP-NOTE-06 | `TestNotes::test_add_empty_note_rejected` | 400 on empty content |
| CMP-EVT-01 | `TestEvents::test_add_event` | Add lifecycle event |
| CMP-EVT-02 | `TestEvents::test_list_events` | List events for company |
| CMP-EVT-03 | `TestEvents::test_delete_event` | Delete event by ID |
| CMP-EVT-04 | `TestEvents::test_add_event_missing_type_rejected` | 400 without event_type |
| CMP-VER-01 | `TestVersionHistory::test_list_versions` | Version list endpoint works |
| CMP-VER-02 | `TestVersionHistory::test_version_created_on_update` | Update creates version |
| CMP-TRASH-01 | `TestTrash::test_trash_empty` | Empty trash returns [] |
| CMP-TRASH-02 | `TestTrash::test_restore_from_trash` | Restore re-adds to listing |
| CMP-TRASH-03 | `TestTrash::test_permanent_delete` | Hard delete removes from trash |
| CMP-BULK-01 | `TestBulkActions::test_bulk_assign_category` | Assign category to N companies |
| CMP-BULK-02 | `TestBulkActions::test_bulk_add_tags` | Add tags to N companies |
| CMP-BULK-03 | `TestBulkActions::test_bulk_set_relationship` | Set relationship on N companies |
| CMP-BULK-04 | `TestBulkActions::test_bulk_delete` | Bulk soft-delete |
| CMP-BULK-05 | `TestBulkActions::test_bulk_no_ids_rejected` | 400 on empty IDs |
| CMP-BULK-06 | `TestBulkActions::test_bulk_invalid_action_rejected` | 400 on invalid action |
| CMP-CMP-01 | `TestCompare::test_compare_companies` | Compare returns N companies |
| CMP-DUP-01 | `TestDuplicates::test_duplicates_endpoint` | Duplicate detection works |
| CMP-MERGE-01 | `TestMerge::test_merge_companies` | Merge two companies |
| CMP-MERGE-02 | `TestMerge::test_merge_missing_ids_rejected` | 400 without both IDs |

### test_api_taxonomy.py — `pytest -m taxonomy` (9 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| TAX-LIST-01 | `TestGetTaxonomy::test_get_taxonomy` | Returns category list with stats |
| TAX-LIST-02 | `TestGetTaxonomy::test_taxonomy_returns_stats` | Categories have id + name |
| TAX-HIST-01 | `TestTaxonomyHistory::test_history_empty` | History endpoint works |
| TAX-CAT-01 | `TestGetCategory::test_get_category` | Returns category with companies |
| TAX-CAT-02 | `TestGetCategory::test_get_nonexistent_category` | 404 for invalid |
| TAX-COLOR-01 | `TestCategoryColor::test_set_color` | PUT color accepted |
| TAX-COLOR-02 | `TestCategoryColor::test_color_persists` | Color saved and retrievable |
| TAX-META-01 | `TestCategoryMetadata::test_set_metadata` | Scope notes saved |
| TAX-REVIEW-01 | `TestTaxonomyReviewApply::test_apply_empty_changes` | Empty changes returns 0 |
| TAX-QUALITY-01 | `TestTaxonomyQuality::test_quality_metrics` | Quality endpoint returns dict |

### test_api_canvas.py — `pytest -m canvas` (13 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| CVS-CREATE-01 | `TestCanvasCreate::test_create_canvas` | POST creates canvas |
| CVS-CREATE-02 | `TestCanvasCreate::test_create_canvas_default_title` | Default title accepted |
| CVS-LIST-01 | `TestCanvasList::test_list_empty` | Empty list returns [] |
| CVS-LIST-02 | `TestCanvasList::test_list_returns_created` | Created canvases appear |
| CVS-GET-01 | `TestCanvasGet::test_get_canvas` | Returns canvas by ID |
| CVS-GET-02 | `TestCanvasGet::test_get_nonexistent` | 404 for invalid |
| CVS-UPD-01 | `TestCanvasUpdate::test_update_title` | Title update persists |
| CVS-UPD-02 | `TestCanvasUpdate::test_update_data` | Excalidraw JSON saved |
| CVS-DEL-01 | `TestCanvasDelete::test_delete_canvas` | Delete removes from list |
| CVS-DIAG-01 | `TestDiagramGeneration::test_generate_diagram_missing_fields` | 400 without required fields |
| CVS-DIAG-02 | `TestDiagramGeneration::test_generate_diagram_missing_project_id` | 400 without project_id |
| CVS-DIAG-03 | `TestDiagramGeneration::test_generate_diagram_missing_categories` | 400 without category_ids |
| CVS-DIAG-04 | `TestDiagramGeneration::test_poll_nonexistent_diagram` | Polling handles invalid ID |

### test_api_data.py — `pytest -m data` (21 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| DATA-EXP-JSON-01 | `TestExportJSON::test_export_json` | JSON export returns data |
| DATA-EXP-JSON-02 | `TestExportJSON::test_export_json_includes_extra_tables` | Includes history, reports, views |
| DATA-EXP-CSV-01 | `TestExportCSV::test_export_csv` | CSV export succeeds |
| DATA-EXP-CSV-02 | `TestExportCSV::test_export_csv_with_companies` | CSV has header + rows |
| DATA-EXP-MD-01 | `TestExportMarkdown::test_export_md` | Markdown export succeeds |
| DATA-IMP-01 | `TestImportCSV::test_import_csv` | CSV import creates companies |
| DATA-IMP-02 | `TestImportCSV::test_import_csv_missing_file` | 400 without file |
| DATA-IMP-03 | `TestImportCSV::test_import_csv_missing_project` | 400 without project_id |
| DATA-STATS-01 | `TestStats::test_stats_empty_project` | Stats endpoint works |
| DATA-STATS-02 | `TestStats::test_stats_with_companies` | Stats with data |
| DATA-CHARTS-01 | `TestCharts::test_chart_data` | Chart data endpoint |
| DATA-FILTER-01 | `TestFilterOptions::test_filter_options` | Returns tags, geos, stages |
| DATA-TAG-01 | `TestTags::test_list_tags` | List tags endpoint |
| DATA-TAG-02 | `TestTags::test_rename_tag` | Rename across companies |
| DATA-TAG-03 | `TestTags::test_delete_tag` | Delete from all companies |
| DATA-TAG-04 | `TestTags::test_merge_tags` | Merge source into target |
| DATA-VIEW-01 | `TestSavedViews::test_list_views_empty` | Empty views list |
| DATA-VIEW-02 | `TestSavedViews::test_create_and_list_view` | Create + retrieve view |
| DATA-VIEW-03 | `TestSavedViews::test_delete_view` | Delete by ID |
| DATA-MAP-01 | `TestMapLayouts::test_list_layouts_empty` | Empty layouts list |
| DATA-MAP-02 | `TestMapLayouts::test_save_layout` | Save map position |

### test_api_processing.py — `pytest -m processing` (11 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| PROC-JOBS-01 | `TestListJobs::test_list_jobs_empty` | Empty jobs list |
| PROC-JOBS-02 | `TestListJobs::test_list_jobs_with_project_filter` | Filter by project |
| PROC-BATCH-01 | `TestGetBatch::test_get_nonexistent_batch` | Handles missing batch |
| PROC-START-01 | `TestProcessValidation::test_process_no_urls_rejected` | 400 without URLs |
| PROC-START-02 | `TestProcessValidation::test_process_empty_text_rejected` | 400 on empty text |
| PROC-TRIAGE-01 | `TestTriageValidation::test_triage_no_urls_rejected` | 400 without URLs |
| PROC-TRIAGE-02 | `TestTriageValidation::test_triage_empty_rejected` | 400 on empty |
| PROC-TRIAGE-03 | `TestTriageValidation::test_poll_triage_nonexistent` | Handles missing triage |
| PROC-RETRY-01 | `TestRetryValidation::test_retry_timeouts_nonexistent_batch` | 400 on missing batch |
| PROC-RETRY-02 | `TestRetryValidation::test_retry_errors_nonexistent_batch` | 400 on missing batch |

### test_api_research.py — `pytest -m research` (13 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| RES-START-01 | `TestResearchValidation::test_research_empty_prompt_rejected` | 400 on empty prompt |
| RES-START-02 | `TestResearchValidation::test_research_missing_prompt_rejected` | 400 without prompt |
| RES-LIST-01 | `TestResearchList::test_list_empty` | Empty research list |
| RES-GET-01 | `TestResearchGet::test_get_nonexistent` | 404 for invalid ID |
| RES-DEL-01 | `TestResearchDelete::test_delete_nonexistent` | Handles gracefully |
| RES-TPL-01 | `TestResearchTemplates::test_list_templates_auto_seeds` | Auto-seeds defaults |
| RES-TPL-02 | `TestResearchTemplates::test_create_template` | Custom template creation |
| RES-TPL-03 | `TestResearchTemplates::test_update_template` | Template update |
| RES-TPL-04 | `TestResearchTemplates::test_delete_template` | Template deletion |
| RES-RPT-01 | `TestReports::test_list_reports_empty` | Empty reports list |
| RES-RPT-02 | `TestReports::test_get_report_nonexistent` | 404 for invalid |
| RES-RPT-03 | `TestReports::test_delete_report_nonexistent` | Handles gracefully |
| RES-RPT-04 | `TestReports::test_export_report_nonexistent` | 404 for missing |
| RES-MKT-01 | `TestMarketReportValidation::test_market_report_missing_category` | 400 without category |

### test_api_ai.py — `pytest -m ai` (16 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| AI-MOD-01 | `TestAIModels::test_list_models` | Returns models dict |
| AI-SETUP-01 | `TestAISetupStatus::test_setup_status` | CLI/SDK/Gemini status |
| AI-DEF-01 | `TestAIDefaultModel::test_get_default_model` | Current default model |
| AI-DEF-02 | `TestAIDefaultModel::test_set_default_model` | Set model preference |
| AI-KEY-01 | `TestAISaveAPIKey::test_save_invalid_key_rejected` | 400 on invalid format |
| AI-TEST-01 | `TestAITestBackend::test_test_invalid_backend` | Invalid backend fails gracefully |
| AI-DISC-01 | `TestAIDiscoverValidation::test_discover_empty_query_rejected` | 400 on empty query |
| AI-DISC-02 | `TestAIDiscoverValidation::test_poll_discover_nonexistent` | Polling handles missing |
| AI-SIM-01 | `TestAIFindSimilarValidation::test_find_similar_missing_company_rejected` | 400 without company_id |
| AI-SIM-02 | `TestAIFindSimilarValidation::test_find_similar_nonexistent_company` | 404 for invalid company |
| AI-SIM-03 | `TestAIFindSimilarValidation::test_poll_similar_nonexistent` | Polling handles missing |
| AI-CHAT-01 | `TestAIChatValidation::test_chat_empty_question` | Handles empty question |
| AI-PRICE-01 | `TestAIPricingValidation::test_pricing_no_companies` | Handles no companies |
| AI-PRICE-02 | `TestAIPricingValidation::test_poll_pricing_nonexistent` | Polling handles missing |
| AI-RPT-01 | `TestAIMarketReportValidation::test_report_missing_category` | 400 without category |
| AI-RPT-02 | `TestAIMarketReportValidation::test_poll_report_nonexistent` | Polling handles missing |

### test_api_discovery.py — `pytest -m discovery` (15 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| DISC-CTX-01 | `TestContextsList::test_list_contexts_empty` | Empty context list |
| DISC-CTX-02 | `TestContextsList::test_list_contexts_missing_project` | 400 without project |
| DISC-CTX-03 | `TestContextUpload::test_upload_text_content` | Upload text context |
| DISC-CTX-04 | `TestContextUpload::test_upload_missing_content_rejected` | 400 without content |
| DISC-CTX-05 | `TestContextUpload::test_upload_missing_project_rejected` | 400 without project |
| DISC-CTX-06 | `TestContextGet::test_get_context` | Get by ID |
| DISC-CTX-07 | `TestContextGet::test_get_nonexistent` | 404 for invalid |
| DISC-CTX-08 | `TestContextDelete::test_delete_context` | Delete context |
| DISC-ANALYSIS-01 | `TestAnalysesList::test_list_analyses_empty` | Empty analysis list |
| DISC-ANALYSIS-02 | `TestAnalysesList::test_list_analyses_missing_project` | 400 without project |
| DISC-ANALYSIS-03 | `TestAnalysisGet::test_get_nonexistent` | 404 for invalid |
| DISC-ANALYSIS-04 | `TestAnalysisDelete::test_delete_nonexistent` | Handles gracefully |
| DISC-LAND-01 | `TestFeatureLandscapeValidation::test_landscape_missing_project` | 400 without project |
| DISC-LAND-02 | `TestFeatureLandscapeValidation::test_poll_landscape_nonexistent` | Polling handles missing |
| DISC-GAP-01 | `TestGapAnalysisValidation::test_gap_analysis_missing_project` | 400 without project |
| DISC-GAP-02 | `TestGapAnalysisValidation::test_poll_gap_nonexistent` | Polling handles missing |

### test_api_dimensions.py — `pytest -m dimensions` (17 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| DIM-LIST-01 | `TestDimensionsList::test_list_empty` | Empty dimensions list |
| DIM-LIST-02 | `TestDimensionsList::test_list_missing_project_rejected` | 400 without project |
| DIM-CREATE-01 | `TestDimensionCreate::test_create_text_dimension` | Create text type |
| DIM-CREATE-02 | `TestDimensionCreate::test_create_number_dimension` | Create number type |
| DIM-CREATE-03 | `TestDimensionCreate::test_create_enum_dimension` | Create enum type |
| DIM-CREATE-04 | `TestDimensionCreate::test_create_boolean_dimension` | Create boolean type |
| DIM-CREATE-05 | `TestDimensionCreate::test_create_missing_name_rejected` | 400 without name |
| DIM-CREATE-06 | `TestDimensionCreate::test_create_missing_project_rejected` | 400 without project |
| DIM-CREATE-07 | `TestDimensionCreate::test_create_invalid_data_type_rejected` | 400 on bad type |
| DIM-DEL-01 | `TestDimensionDelete::test_delete_dimension` | Delete by ID |
| DIM-VAL-01 | `TestDimensionValues::test_get_values_empty` | Empty values list |
| DIM-VAL-02 | `TestDimensionValues::test_set_value` | Set company value |
| DIM-VAL-03 | `TestDimensionValues::test_set_value_missing_company_rejected` | 400 without company |
| DIM-CMP-01 | `TestCompanyDimensions::test_get_company_dimensions` | Get company's dimensions |
| DIM-EXP-01 | `TestExploreValidation::test_explore_missing_project_rejected` | 400 without project |
| DIM-EXP-02 | `TestExploreValidation::test_poll_explore_nonexistent` | Polling handles missing |
| DIM-POP-01 | `TestPopulateValidation::test_populate_missing_project_rejected` | 400 without project |
| DIM-POP-02 | `TestPopulateValidation::test_poll_populate_nonexistent` | Polling handles missing |

### test_api_settings.py — `pytest -m settings` (22 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| SET-SHARE-01 | `TestShareTokensList::test_list_empty` | Empty share list |
| SET-SHARE-02 | `TestShareTokenCreate::test_create_share_token` | Create with label |
| SET-SHARE-03 | `TestShareTokenCreate::test_create_share_token_without_label` | Create without label |
| SET-SHARE-04 | `TestShareTokenDelete::test_delete_share_token` | Delete by ID |
| SET-SHARED-01 | `TestSharedView::test_shared_view` | Public view returns data |
| SET-SHARED-02 | `TestSharedView::test_shared_view_invalid_token` | 404 for invalid token |
| SET-ACT-01 | `TestActivityLog::test_activity_empty` | Empty activity log |
| SET-ACT-02 | `TestActivityLog::test_activity_with_limit` | Limit parameter works |
| SET-ACT-03 | `TestActivityLog::test_activity_with_offset` | Offset parameter works |
| SET-NOTIF-01 | `TestNotificationPrefs::test_get_prefs` | Get notification prefs |
| SET-NOTIF-02 | `TestNotificationPrefs::test_save_prefs` | Save notification toggles |
| SET-NOTIF-03 | `TestNotificationPrefs::test_test_slack_missing_url_rejected` | 400 without URL |
| SET-NOTIF-04 | `TestNotificationPrefs::test_test_slack_invalid_url_rejected` | 400 on invalid URL |
| SET-APP-01 | `TestAppSettings::test_get_settings` | Get app settings |
| SET-APP-02 | `TestAppSettings::test_save_settings` | Save settings |
| SET-PREREQ-01 | `TestPrerequisites::test_check_prerequisites` | Prerequisites check |
| SET-BACKUP-01 | `TestBackups::test_list_backups` | List backups |
| SET-BACKUP-02 | `TestBackups::test_create_backup` | Create backup file |
| SET-BACKUP-03 | `TestBackups::test_restore_nonexistent_rejected` | 404 on missing backup |
| SET-BACKUP-04 | `TestBackups::test_delete_nonexistent_rejected` | 404 on missing backup |
| SET-LOG-01 | `TestLogs::test_list_logs` | List log files |
| SET-LOG-02 | `TestLogs::test_get_nonexistent_log` | 404 on missing log |
| SET-UPDATE-01 | `TestUpdateCheck::test_update_check` | Version check response |

### test_api_static.py — `pytest -m static` (16 tests)
| ID | Test | What it verifies |
|----|------|-----------------|
| STATIC-IDX-01 | `TestIndexPage::test_index_returns_html` | Homepage renders |
| STATIC-IDX-02 | `TestIndexPage::test_index_contains_csrf_meta` | CSRF meta tag present |
| STATIC-IDX-03 | `TestIndexPage::test_index_contains_app_version` | Version in page |
| STATIC-HEALTH-01 | `TestHealthEndpoint::test_healthz` | Health check response |
| STATIC-FILE-01 | `TestStaticFiles::test_styles_css` | styles.css loads |
| STATIC-FILE-02 | `TestStaticFiles::test_base_css` | base.css has :root |
| STATIC-FILE-03 | `TestStaticFiles::test_core_js` | core.js loads |
| STATIC-FILE-04 | `TestStaticFiles::test_companies_js` | companies.js loads |
| STATIC-FILE-05 | `TestStaticFiles::test_taxonomy_js` | taxonomy.js loads |
| STATIC-FILE-06 | `TestStaticFiles::test_canvas_js` | canvas.js loads |
| STATIC-FILE-07 | `TestStaticFiles::test_maps_js` | maps.js loads |
| STATIC-FILE-08 | `TestStaticFiles::test_diagram_js` | diagram.js loads |
| STATIC-FILE-09 | `TestStaticFiles::test_projects_js` | projects.js loads |
| STATIC-FILE-10 | `TestStaticFiles::test_init_js` | init.js loads |
| STATIC-FILE-11 | `TestStaticFiles::test_ai_js` | ai.js loads |
| STATIC-FILE-12 | `TestStaticFiles::test_integrations_js` | integrations.js loads |

### test_db.py — `pytest -m db` (18 tests)
Database layer tests for projects, categories, companies, jobs, and triage.

### test_security.py — `pytest -m security` (13 tests)
CSRF tokens, soft-delete filtering, upsert atomicity, health endpoint, exports.

### test_async_jobs.py — `pytest -m async_jobs` (10 tests)
Job ID generation, write/poll lifecycle, async execution, error handling.

### test_routes.py — Legacy (9 tests)
Original route tests kept for backward compatibility. Covered by new test_api_*.py files.

---

## Playwright E2E Spec Files (132 tests, 24 files)

Run all: `npm run test:e2e`

| File | Tests | Coverage |
|------|-------|----------|
| `accessibility.spec.js` | 6 | Skip link, ARIA roles, tabpanel, focus-visible |
| `bulk-actions.spec.js` | 6 | Select-all, bulk bar, assign, tags, delete (custom dialogs) |
| `canvas.spec.js` | 9 | Toolbar, CRUD, sidebar, search (Excalidraw, custom dialogs) |
| `capture_evidence.spec.js` | 7 | Bug fix screenshots (Excalidraw refs updated) |
| `category-colors.spec.js` | 6 | Color picker, persistence, company dots, map tiles |
| `company-detail.spec.js` | 7 | Detail panel, edit, star, notes, relationships |
| `crud.spec.js` | 2 | Project create via API and form |
| `dark-mode.spec.js` | 4 | Theme toggle, localStorage, CSS vars |
| `empty-states.spec.js` | 3 | Company/batch empty states |
| `exports.spec.js` | 5 | Export cards, links, share, CSV import |
| `filters.spec.js` | 6 | Search, starred, category, enrichment |
| `keyboard.spec.js` | 6 | Shortcuts: /, ?, Esc, numbers, D |
| `linked-navigation.spec.js` | 5 | Breadcrumbs, category links |
| `loading-states.spec.js` | 3 | Tab loading, rapid switching, console clean |
| `market-map.spec.js` | 6 | Market map, view toggles, Cytoscape, export |
| `modals.spec.js` | 4 | Shortcuts overlay, tag manager, focus trap |
| `navigation.spec.js` | 6 | Project select, tab switching, URL state |
| `processing.spec.js` | 6 | URL textarea, model select, workers, AI |
| `project-management.spec.js` | 6 | Selection screen, grid, project switch |
| `research.spec.js` | 9 | Mode toggle, category/scope select, templates |
| `responsive.spec.js` | 6 | Mobile/tablet/desktop/large viewports |
| `search-filter.spec.js` | 7 | Search, typing, dropdown, saved views |
| `taxonomy.spec.js` | 8 | Tree, graph (Cytoscape), analytics, review |

---

## Integration Scripts (.cjs) — 18 files

Run individually: `node e2e/<filename>`

| File | Purpose | Engine |
|------|---------|--------|
| `take_evidence.cjs` | Screenshot all fixed features | Chromium |
| `take_ux_evidence.cjs` | Screenshot UX updates (Session 8) | Chromium |
| `test_ai_discovery.cjs` | AI Discovery / Process tab | Chromium |
| `test_canvas.cjs` | Canvas tab comprehensive | Chromium |
| `test_canvas_fixes.cjs` | Canvas fixes (bound-text, templates) | Chromium |
| `test_companies.cjs` | Companies tab CRUD | Chromium |
| `test_diagram_generation.cjs` | AI diagram generation flow | Chromium |
| `test_diagram_webkit.cjs` | Diagram generation (WebKit) | WebKit |
| `test_excalidraw.cjs` | Excalidraw library load | Chromium |
| `test_excalidraw_full.cjs` | Full Excalidraw canvas flow | Chromium |
| `test_full_canvas_flow.cjs` | Complete canvas workflow | WebKit |
| `test_maps.cjs` | Map tab (Leaflet, markers) | Chromium |
| `test_navigation.cjs` | Tab navigation + responsive | Chromium |
| `test_projects.cjs` | Project management | Chromium |
| `test_prompt_dialog.cjs` | Custom prompt/select dialogs | Chromium |
| `test_settings.cjs` | Settings, export, dark mode | Chromium |
| `test_taxonomy_graphs.cjs` | Graph/KG/analytics views | Chromium |
| `test_webkit_canvas.cjs` | WebKit canvas creation | WebKit |

---

## Maintenance Rules

1. **When adding a new API endpoint**: Add tests to the corresponding `test_api_*.py` file
2. **When adding a new UI feature**: Add tests to the relevant `.spec.js` file
3. **When fixing a bug**: Add a regression test that would have caught it
4. **Run before committing**: `pytest tests/ -v` (17 seconds)
5. **Run e2e after UI changes**: `npm run test:e2e`
6. **Run specific area after targeted changes**: `pytest -m <marker>`
