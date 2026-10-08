# Graph Report - Shopify_skin_care_price_monitoring_bot  (2026-10-08)

## Corpus Check
- 35 files · ~60,227 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 2, .example 1, .csv 1)

## Summary
- 812 nodes · 1904 edges · 67 communities (28 shown, 39 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 69 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- FetchResult
- HttpError
- migrate_sqlite_to_postgres.py
- test_money.py
- test_detector.py
- PlaywrightAdapter
- Supabase (PostgreSQL) Setup
- Pg8000DictCursor
- test_notifier.py
- main.py
- SqliteStorage
- PostgresStorage
- test_migration_script_dry_run_and_readonly
- get_unnotified_events
- test_fallback_strategy.py
- Pg8000ConnectionAdapter
- jsonld.py
- ShopifyAdapter
- test_storage_backends.py
- Observation
- notifier.py
- run_once
- runner.py
- parse_json_safely
- storage.py
- sample_config
- JsonLdAdapter
- sample_config
- test_reliability_features.py
- BaseStorage
- mask_database_url
- test_failed_url_does_not_create_out_of_stock_event
- get_connection
- test_run_once_second_run_detects_price_drop
- ErrorRecord
- send_message
- storage_backend
- sqlite3
- test_http_404_produces_no_observation

## God Nodes (most connected - your core abstractions)
1. `Observation` - 72 edges
2. `run_once()` - 63 edges
3. `PostgresStorage` - 55 edges
4. `SqliteStorage` - 51 edges
5. `FetchResult` - 45 edges
6. `BaseStorage` - 43 edges
7. `HttpError` - 30 edges
8. `JsonLdAdapter` - 28 edges
9. `PlaywrightAdapter` - 28 edges
10. `ShopifyAdapter` - 28 edges

## Surprising Connections (you probably didn't know these)
- `test_http_404_produces_no_observation()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_validation_and_fixes.py → monitor/adapters/playwright.py
- `test_redirect_to_generic_home_or_404_page()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_validation_and_fixes.py → monitor/adapters/playwright.py
- `test_dry_run_does_not_send_or_mark_notified()` --uses--> `Observation`  [INFERRED]
  tests/test_notifier.py → monitor/models.py
- `test_runner_marks_notified_only_on_success()` --uses--> `Observation`  [INFERRED]
  tests/test_notifier.py → monitor/models.py
- `test_run_once_baseline_creates_no_events()` --uses--> `Observation`  [INFERRED]
  tests/test_runner.py → monitor/models.py

## Import Cycles
- None detected.

## Communities (67 total, 39 thin omitted)

### Community 0 - "FetchResult"
Cohesion: 0.14
Nodes (9): FetchResult, _create_sample_obs(), test_check_single_url_offline(), test_duplicate_url_warning_and_deduplication(), test_failed_first_fetch_creates_no_variant(), test_new_product_silent_baseline_and_summary_message(), test_readded_url_reactivates_without_alert(), test_removed_url_creates_no_events_and_is_no_longer_fetched() (+1 more)

### Community 1 - "HttpError"
Cohesion: 0.16
Nodes (11): HttpError, test_all_strategies_fail_gracefully_without_crash(), fake_http_get(), test_yanybeauty_handle_based_shopify_json_fallback(), fake_http_get(), test_yanybeauty_jsonld_fallback(), fake_http_get(), test_yanybeauty_playwright_js_rendered_fallback() (+3 more)

### Community 2 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.16
Nodes (5): parse_args(), get_postgres_row_count(), parse_args(), reset_identity_sequences(), run_migration()

### Community 3 - "test_money.py"
Cohesion: 0.08
Nodes (11): parse_price(), to_cents(), test_cents_to_str(), test_parse_price_locales(), test_to_cents_currency_and_separators(), test_to_cents_integers_and_floats(), test_to_cents_invalid_string(), test_to_cents_none_and_empty() (+3 more)

### Community 4 - "test_detector.py"
Cohesion: 0.14
Nodes (11): detect(), make_obs(), test_detect_back_in_stock(), test_detect_change_smaller_than_threshold_ignored(), test_detect_new_variant(), test_detect_out_of_stock(), test_detect_previous_none_explicit(), test_detect_price_and_stock_change_together() (+3 more)

### Community 5 - "PlaywrightAdapter"
Cohesion: 0.08
Nodes (9): clean_and_deduplicate_title(), PlaywrightAdapter, test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_missing_availability_is_none(), test_missing_price_never_guesses_zero(), test_parse_real_fixture_offline(), test_single_failing_url_does_not_stop_other_urls() (+1 more)

### Community 6 - "Supabase (PostgreSQL) Setup"
Cohesion: 0.10
Nodes (19): 1. Create a Supabase Project, 1. Installation, 2. Configuration, 2. Copy the "Session Pooler" Connection String, 3. Encode Special Characters in Your Password, 3. Telegram Setup & Preview, 4. Configure `DATABASE_URL`, 4. Running the Monitor (+11 more)

### Community 8 - "test_notifier.py"
Cohesion: 0.07
Nodes (12): validate(), test_build_error_message(), test_build_message_grouping(), test_build_message_splitting_at_boundaries(), test_escape_html(), test_format_price_change(), test_send_error_message_routes_to_error_bot(), playwright_config() (+4 more)

### Community 11 - "main.py"
Cohesion: 0.14
Nodes (6): main(), build_crash_alert_message(), send_error_message(), test_connection(), get_storage(), setup_logging()

### Community 13 - "PostgresStorage"
Cohesion: 0.09
Nodes (4): format_iso_timestamp(), PostgresStorage, to_bigint_id(), migrate_table()

### Community 14 - "test_migration_script_dry_run_and_readonly"
Cohesion: 0.25
Nodes (4): get_price_checks_timestamp_range(), get_readonly_sqlite_conn(), get_sqlite_row_count(), test_migration_script_dry_run_and_readonly()

### Community 15 - "get_unnotified_events"
Cohesion: 0.28
Nodes (4): get_unnotified_events(), test_dry_run_does_not_send_or_mark_notified(), test_runner_marks_notified_only_on_success(), test_insert_event_and_get_unnotified()

### Community 16 - "test_fallback_strategy.py"
Cohesion: 0.16
Nodes (6): extract_product_handle(), fetch_with_fallback(), get_store_origin(), get_target_urls_for_site(), test_extract_product_handle_and_store_origin(), test_normal_shopify_store_uses_existing_products_json()

### Community 19 - "ShopifyAdapter"
Cohesion: 0.08
Nodes (9): ShopifyAdapter, adapter(), sample_payload(), test_availability_extracted_correctly(), test_empty_payload_handled_gracefully(), test_fixture_parsing_total_variants(), test_missing_price_is_none_never_zero(), test_prices_extracted_correctly() (+1 more)

### Community 20 - "test_storage_backends.py"
Cohesion: 0.15
Nodes (5): test_postgres_advisory_lock_mocked(), test_storage_contract_lifecycle(), test_to_bigint_id_non_numeric(), test_to_bigint_id_none(), test_to_bigint_id_numeric()

### Community 21 - "Observation"
Cohesion: 0.15
Nodes (13): Observation, batch_insert_price_checks(), batch_upsert_variants(), deactivate_removed_variants(), get_last_check(), get_variant_ids_for_site(), insert_price_check(), is_price_checks_empty() (+5 more)

### Community 22 - "notifier.py"
Cohesion: 0.14
Nodes (9): build_delivery_failure_alert(), build_error_message(), build_message(), build_new_variants_summary(), build_site_status_change_message(), escape_html(), format_event_block(), format_price_change() (+1 more)

### Community 23 - "run_once"
Cohesion: 0.16
Nodes (10): run_once(), get_meta(), get_site_state(), upsert_site_state(), test_daily_heartbeat_meta_tracking(), test_heartbeat_failed_send_does_not_mark_as_sent(), test_run_once_records_health_and_alerts_on_status_change(), test_site_state_transition_and_recovered_alert() (+2 more)

### Community 24 - "runner.py"
Cohesion: 0.12
Nodes (9): check_single_url(), create_adapter(), _get_active_target_urls_from_csv(), load_config(), print_health_summary(), _print_summary(), cents_to_str(), test_create_adapter() (+1 more)

### Community 25 - "parse_json_safely"
Cohesion: 0.24
Nodes (4): is_captcha_challenge(), is_json_response(), parse_json_safely(), test_is_json_response_and_parse_json_safely()

### Community 26 - "storage.py"
Cohesion: 0.13
Nodes (13): batch_insert_events(), find_active_variant_ids_by_url_substr(), get_latest_site_statuses(), get_site_latest_checks(), get_site_variant_ids(), insert_error_record(), insert_event(), is_variant_in_catalog() (+5 more)

### Community 28 - "JsonLdAdapter"
Cohesion: 0.08
Nodes (10): SiteAdapter, JsonLdAdapter, test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_graph_and_array_extraction(), test_missing_price_never_guesses_zero(), test_multiple_variants_handling(), test_parse_real_fixture_offline() (+2 more)

### Community 30 - "test_reliability_features.py"
Cohesion: 0.11
Nodes (9): build_heartbeat_message(), test_crash_alert_message_format(), test_delisted_and_relisted_combined_in_one_team_section(), test_http_get_no_retry_on_403_and_captcha(), test_http_get_no_retry_on_404_and_410(), test_http_get_redirect_to_homepage_classified_as_not_found(), test_http_get_retry_after_capped_at_60s(), test_http_get_retry_after_within_60s_sleeps_and_retries() (+1 more)

### Community 32 - "mask_database_url"
Cohesion: 0.15
Nodes (6): clean_database_url(), mask_database_url(), test_mask_database_url_no_password(), test_mask_database_url_none_or_empty(), test_mask_database_url_special_characters(), test_mask_database_url_standard()

### Community 34 - "get_connection"
Cohesion: 0.15
Nodes (10): get_connection(), init_db(), process_presence_and_delisting(), test_safe_migration_adds_active_column(), test_confirmed_absence_delisting_and_relisting(), test_error_records_in_fetch_result_and_db(), test_fetch_error_never_counts_as_miss(), test_print_health_summary_read_only() (+2 more)

### Community 36 - "test_run_once_second_run_detects_price_drop"
Cohesion: 0.32
Nodes (3): test_run_once_baseline_creates_no_events(), test_run_once_handles_failing_site(), test_run_once_second_run_detects_price_drop()

### Community 38 - "send_message"
Cohesion: 0.33
Nodes (3): send_message(), test_send_message_failure_and_retries(), test_send_message_success()

### Community 39 - "storage_backend"
Cohesion: 0.25
Nodes (3): storage_backend(), test_get_storage_selects_backend(), test_sqlite_file_locking()

## Knowledge Gaps
- **15 isolated node(s):** `Project Structure`, `1. Installation`, `2. Configuration`, `3. Telegram Setup & Preview`, `4. Running the Monitor` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 342 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Observation` connect `Observation` to `FetchResult`, `HttpError`, `test_money.py`, `test_detector.py`, `PlaywrightAdapter`, `test_notifier.py`, `SqliteStorage`, `PostgresStorage`, `test_migration_script_dry_run_and_readonly`, `get_unnotified_events`, `test_fallback_strategy.py`, `jsonld.py`, `ShopifyAdapter`, `test_storage_backends.py`, `run_once`, `runner.py`, `storage.py`, `JsonLdAdapter`, `test_reliability_features.py`, `BaseStorage`, `test_failed_url_does_not_create_out_of_stock_event`, `get_connection`, `test_run_once_second_run_detects_price_drop`, `.batch_insert_price_checks`, `.batch_upsert_variants`?**
  _High betweenness centrality (0.285) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `Observation` (e.g. with `JsonLdAdapter` and `PlaywrightAdapter`) actually correct?**
  _`Observation` has 17 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project Structure`, `1. Installation`, `2. Configuration` to the rest of the system?**
  _15 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `FetchResult` be split into smaller, more focused modules?**
  _Cohesion score 0.14 - nodes in this community are weakly interconnected._
- **Why does `BaseStorage` connect `BaseStorage` to `main.py`, `SqliteStorage`, `PostgresStorage`, `test_storage_backends.py`, `Observation`, `storage.py`, `.acquire_lock`, `.check_health`, `.close`, `.deactivate_removed_variants`, `.find_active_variant_ids_by_url_substr`, `.get_last_check`, `.get_latest_site_statuses`, `.get_meta`, `.get_site_state`, `.get_unnotified_events`, `.init_db`, `.insert_error_record`, `.batch_insert_events`, `.batch_insert_price_checks`, `.is_variant_in_catalog`, `.mark_events_notified`, `.is_price_checks_empty`, `.record_site_run`, `.release_lock`, `.set_meta`, `.record_run_start`, `.batch_upsert_variants`, `.get_site_latest_checks`, `.record_run_finish`, `.upsert_site_state`?**
  _High betweenness centrality (0.130) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `PostgresStorage` (e.g. with `Observation` and `get_postgres_row_count()`) actually correct?**
  _`PostgresStorage` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_money.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07936507936507936 - nodes in this community are weakly interconnected._