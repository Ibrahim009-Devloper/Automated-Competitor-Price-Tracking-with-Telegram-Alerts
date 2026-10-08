# Graph Report - Shopify_skin_care_price_monitoring_bot  (2026-10-08)

## Corpus Check
- 37 files · ~64,277 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 2, .example 1, .csv 1)

## Summary
- 876 nodes · 2043 edges · 67 communities (28 shown, 39 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 81 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cf54fd75`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- FetchResult
- HttpError
- Pg8000ConnectionAdapter
- test_money.py
- test_detector.py
- test_blocked_403_stops_site_run
- GitHub Actions Automation & Scheduling
- Any
- validate
- test_ci_and_scheduling.py
- SqliteStorage
- PostgresStorage
- test_migration_script_dry_run_and_readonly
- sqlite3
- test_fallback_strategy.py
- test_run_once_second_run_detects_price_drop
- PlaywrightAdapter
- test_shopify_adapter.py
- format_iso_timestamp
- Observation
- runner.py
- get_unnotified_events
- parse_args
- jsonld.py
- storage.py
- JsonLdAdapter
- BaseStorage
- migrate_sqlite_to_postgres.py
- get_connection
- run_once
- models.py
- test_send_error_message_routes_to_error_bot
- test_storage_backends.py
- .mask_text
- sample_config
- test_http_404_produces_no_observation
- mask_database_url

## God Nodes (most connected - your core abstractions)
1. `Observation` - 74 edges
2. `run_once()` - 69 edges
3. `PostgresStorage` - 55 edges
4. `SqliteStorage` - 51 edges
5. `FetchResult` - 47 edges
6. `BaseStorage` - 43 edges
7. `JsonLdAdapter` - 30 edges
8. `PlaywrightAdapter` - 30 edges
9. `ShopifyAdapter` - 30 edges
10. `HttpError` - 30 edges

## Surprising Connections (you probably didn't know these)
- `3. Manual Run via `workflow_dispatch`` --references--> `main()`  [INFERRED]
  README.md → monitor/main.py
- `test_blocked_403_stops_site_run()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_adapter.py → monitor/adapters/playwright.py
- `test_captcha_stops_site_run()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_adapter.py → monitor/adapters/playwright.py
- `test_single_failing_url_does_not_stop_other_urls()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_adapter.py → monitor/adapters/playwright.py
- `test_http_404_produces_no_observation()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_validation_and_fixes.py → monitor/adapters/playwright.py

## Import Cycles
- None detected.

## Communities (67 total, 39 thin omitted)

### Community 0 - "FetchResult"
Cohesion: 0.09
Nodes (12): FetchResult, check_single_url(), _create_sample_obs(), test_build_new_variants_summary_cap_at_10(), test_check_single_url_offline(), test_failed_first_fetch_creates_no_variant(), test_new_product_silent_baseline_and_summary_message(), test_removed_url_creates_no_events_and_is_no_longer_fetched() (+4 more)

### Community 1 - "HttpError"
Cohesion: 0.11
Nodes (14): HttpError, test_all_strategies_fail_gracefully_without_crash(), fake_http_get(), test_yanybeauty_handle_based_shopify_json_fallback(), fake_http_get(), test_yanybeauty_jsonld_fallback(), fake_http_get(), test_yanybeauty_playwright_js_rendered_fallback() (+6 more)

### Community 3 - "test_money.py"
Cohesion: 0.06
Nodes (14): clean_and_deduplicate_title(), is_timed_out(), parse_price(), to_cents(), test_cents_to_str(), test_parse_price_locales(), test_to_cents_currency_and_separators(), test_to_cents_integers_and_floats() (+6 more)

### Community 4 - "test_detector.py"
Cohesion: 0.14
Nodes (11): detect(), make_obs(), test_detect_back_in_stock(), test_detect_change_smaller_than_threshold_ignored(), test_detect_new_variant(), test_detect_out_of_stock(), test_detect_previous_none_explicit(), test_detect_price_and_stock_change_together() (+3 more)

### Community 5 - "test_blocked_403_stops_site_run"
Cohesion: 0.29
Nodes (3): test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_single_failing_url_does_not_stop_other_urls()

### Community 6 - "GitHub Actions Automation & Scheduling"
Cohesion: 0.07
Nodes (28): 1. Create a Supabase Project, 1. Installation, 1. Private Repository Recommendation, 2. Configuration, 2. Configure GitHub Secrets, 2. Copy the "Session Pooler" Connection String, 3. Encode Special Characters in Your Password, 3. Manual Run via `workflow_dispatch` (+20 more)

### Community 7 - "Any"
Cohesion: 0.11
Nodes (4): DictRow, Pg8000DictCursor, record_run_finish(), record_site_run()

### Community 8 - "validate"
Cohesion: 0.29
Nodes (3): validate(), test_validator_detects_suspicious_price_changes(), test_validator_rejects_missing_or_invalid_fields()

### Community 11 - "test_ci_and_scheduling.py"
Cohesion: 0.06
Nodes (21): run_ci_check(), main(), send_error_message(), test_connection(), print_health_summary(), get_storage(), SecretMaskingFilter, setup_logging() (+13 more)

### Community 13 - "PostgresStorage"
Cohesion: 0.11
Nodes (3): PostgresStorage, to_bigint_id(), migrate_table()

### Community 14 - "test_migration_script_dry_run_and_readonly"
Cohesion: 0.20
Nodes (4): storage_backend(), test_get_storage_selects_backend(), test_migration_script_dry_run_and_readonly(), test_sqlite_file_locking()

### Community 15 - "sqlite3"
Cohesion: 0.18
Nodes (4): test_safe_migration_adds_active_column(), test_automatic_backup_creation_before_migration(), memory_db(), test_insert_event_and_get_unnotified()

### Community 16 - "test_fallback_strategy.py"
Cohesion: 0.13
Nodes (6): extract_product_handle(), fetch_with_fallback(), get_store_origin(), get_target_urls_for_site(), test_extract_product_handle_and_store_origin(), test_normal_shopify_store_uses_existing_products_json()

### Community 17 - "test_run_once_second_run_detects_price_drop"
Cohesion: 0.32
Nodes (3): test_run_once_baseline_creates_no_events(), test_run_once_handles_failing_site(), test_run_once_second_run_detects_price_drop()

### Community 18 - "PlaywrightAdapter"
Cohesion: 0.07
Nodes (11): SiteAdapter, create_adapter(), __getattr__(), PlaywrightAdapter, ShopifyAdapter, __getattr__(), test_missing_availability_is_none(), test_missing_price_never_guesses_zero() (+3 more)

### Community 19 - "test_shopify_adapter.py"
Cohesion: 0.11
Nodes (8): adapter(), sample_payload(), test_availability_extracted_correctly(), test_empty_payload_handled_gracefully(), test_fixture_parsing_total_variants(), test_missing_price_is_none_never_zero(), test_prices_extracted_correctly(), test_variant_ids_and_titles()

### Community 20 - "format_iso_timestamp"
Cohesion: 0.18
Nodes (4): format_iso_timestamp(), insert_error_record(), record_run_start(), set_meta()

### Community 21 - "Observation"
Cohesion: 0.18
Nodes (13): Observation, batch_insert_price_checks(), batch_upsert_variants(), deactivate_removed_variants(), get_last_check(), get_variant_ids_for_site(), insert_price_check(), is_price_checks_empty() (+5 more)

### Community 22 - "runner.py"
Cohesion: 0.07
Nodes (21): build_crash_alert_message(), build_delivery_failure_alert(), build_error_message(), build_heartbeat_message(), build_message(), build_new_variants_summary(), build_site_status_change_message(), escape_html() (+13 more)

### Community 23 - "get_unnotified_events"
Cohesion: 0.16
Nodes (7): get_meta(), get_unnotified_events(), test_dry_run_does_not_send_or_mark_notified(), test_runner_marks_notified_only_on_success(), test_send_message_failure_and_retries(), test_heartbeat_failed_send_does_not_mark_as_sent(), test_team_delivery_failure_keeps_events_unnotified()

### Community 25 - "jsonld.py"
Cohesion: 0.11
Nodes (8): http_get(), is_captcha_challenge(), is_generic_redirect(), is_json_response(), parse_json_safely(), test_is_json_response_and_parse_json_safely(), test_http_get_redirect_to_homepage_classified_as_not_found(), test_http_get_retry_after_within_60s_sleeps_and_retries()

### Community 26 - "storage.py"
Cohesion: 0.12
Nodes (9): backup_database_if_needed(), batch_insert_events(), get_latest_site_statuses(), get_site_latest_checks(), get_site_variant_ids(), insert_event(), is_variant_in_catalog(), mark_events_notified() (+1 more)

### Community 28 - "JsonLdAdapter"
Cohesion: 0.07
Nodes (12): JsonLdAdapter, sample_config(), sample_html_fixture(), test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_graph_and_array_extraction(), test_missing_price_never_guesses_zero(), test_multiple_variants_handling() (+4 more)

### Community 32 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.18
Nodes (6): get_postgres_row_count(), get_price_checks_timestamp_range(), get_readonly_sqlite_conn(), get_sqlite_row_count(), reset_identity_sequences(), run_migration()

### Community 34 - "get_connection"
Cohesion: 0.12
Nodes (13): get_connection(), get_site_state(), init_db(), upsert_site_state(), test_confirmed_absence_delisting_and_relisting(), test_daily_heartbeat_meta_tracking(), test_error_records_in_fetch_result_and_db(), test_fetch_error_never_counts_as_miss() (+5 more)

### Community 36 - "run_once"
Cohesion: 0.12
Nodes (9): create_adapter(), _get_active_target_urls_from_csv(), load_config(), _print_summary(), run_once(), test_workflow_yaml_structure_and_constraints(), test_team_delivery_failure_alerts_admin_once_and_recovers(), test_create_adapter() (+1 more)

### Community 39 - "test_storage_backends.py"
Cohesion: 0.15
Nodes (5): test_postgres_advisory_lock_mocked(), test_storage_contract_lifecycle(), test_to_bigint_id_non_numeric(), test_to_bigint_id_none(), test_to_bigint_id_numeric()

### Community 68 - "mask_database_url"
Cohesion: 0.15
Nodes (6): clean_database_url(), mask_database_url(), test_mask_database_url_no_password(), test_mask_database_url_none_or_empty(), test_mask_database_url_special_characters(), test_mask_database_url_standard()

## Knowledge Gaps
- **21 isolated node(s):** `Project Structure`, `1. Installation`, `2. Configuration`, `3. Telegram Setup & Preview`, `Exit Codes` (+16 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 374 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Observation` connect `Observation` to `FetchResult`, `HttpError`, `test_money.py`, `test_detector.py`, `validate`, `test_ci_and_scheduling.py`, `SqliteStorage`, `PostgresStorage`, `test_migration_script_dry_run_and_readonly`, `test_fallback_strategy.py`, `test_run_once_second_run_detects_price_drop`, `PlaywrightAdapter`, `runner.py`, `get_unnotified_events`, `jsonld.py`, `storage.py`, `._fetch_generic_products_json`, `JsonLdAdapter`, `BaseStorage`, `get_connection`, `run_once`, `models.py`, `test_storage_backends.py`, `.batch_insert_price_checks`, `.batch_upsert_variants`?**
  _High betweenness centrality (0.271) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `Observation` (e.g. with `JsonLdAdapter` and `PlaywrightAdapter`) actually correct?**
  _`Observation` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project Structure`, `1. Installation`, `2. Configuration` to the rest of the system?**
  _21 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `FetchResult` be split into smaller, more focused modules?**
  _Cohesion score 0.09009009009009009 - nodes in this community are weakly interconnected._
- **Why does `BaseStorage` connect `BaseStorage` to `test_ci_and_scheduling.py`, `SqliteStorage`, `PostgresStorage`, `Observation`, `storage.py`, `.process_presence_and_delisting`, `.find_active_variant_ids_by_url_substr`, `.init_db`, `test_storage_backends.py`, `.record_run_start`, `.record_site_run`, `.deactivate_removed_variants`, `.get_last_check`, `.get_latest_site_statuses`, `.get_meta`, `.get_unnotified_events`, `.insert_error_record`, `.batch_insert_events`, `.batch_insert_price_checks`, `.is_variant_in_catalog`, `.mark_events_notified`, `.is_price_checks_empty`, `.acquire_lock`, `.release_lock`, `.set_meta`, `.check_health`, `.batch_upsert_variants`, `.get_site_latest_checks`, `.record_run_finish`, `.upsert_site_state`, `.close`, `.get_site_state`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `PostgresStorage` (e.g. with `Observation` and `get_postgres_row_count()`) actually correct?**
  _`PostgresStorage` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Should `HttpError` be split into smaller, more focused modules?**
  _Cohesion score 0.11 - nodes in this community are weakly interconnected._