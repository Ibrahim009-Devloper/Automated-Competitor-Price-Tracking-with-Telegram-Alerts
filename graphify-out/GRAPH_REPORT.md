# Graph Report - Shopify_skin_care_price_monitoring_bot  (2026-10-08)

## Corpus Check
- 37 files · ~63,649 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 2, .example 1, .csv 1)

## Summary
- 864 nodes · 2021 edges · 73 communities (31 shown, 42 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 74 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- _create_sample_obs
- HttpError
- parse_args
- test_money.py
- test_detector.py
- PlaywrightAdapter
- GitHub Actions Automation & Scheduling
- Pg8000DictCursor
- runner.py
- test_ci_and_scheduling.py
- SqliteStorage
- Any
- get_unnotified_events
- fetch_with_fallback
- ._extract_page
- FetchResult
- ShopifyAdapter
- to_bigint_id
- Observation
- escape_html
- get_meta
- create_adapter
- shopify.py
- storage.py
- get_storage
- test_jsonld_adapter.py
- process_presence_and_delisting
- test_reliability_features.py
- BaseStorage
- test_storage_backends.py
- test_failed_url_does_not_create_out_of_stock_event
- get_connection
- test_run_once_second_run_detects_price_drop
- ErrorRecord
- notifier.py
- storage_backend
- .mask_text
- test_duplicate_url_warning_and_deduplication
- test_http_404_produces_no_observation
- clean_database_url
- test_postgres_advisory_lock_mocked
- test_storage_contract_lifecycle

## God Nodes (most connected - your core abstractions)
1. `Observation` - 74 edges
2. `run_once()` - 69 edges
3. `PostgresStorage` - 55 edges
4. `SqliteStorage` - 51 edges
5. `FetchResult` - 47 edges
6. `BaseStorage` - 43 edges
7. `HttpError` - 30 edges
8. `JsonLdAdapter` - 28 edges
9. `PlaywrightAdapter` - 28 edges
10. `ShopifyAdapter` - 28 edges

## Surprising Connections (you probably didn't know these)
- `3. Manual Run via `workflow_dispatch`` --references--> `main()`  [INFERRED]
  README.md → monitor/main.py
- `test_blocked_403_stops_site_run()` --uses--> `JsonLdAdapter`  [INFERRED]
  tests/test_jsonld_adapter.py → monitor/adapters/jsonld.py
- `test_captcha_stops_site_run()` --uses--> `JsonLdAdapter`  [INFERRED]
  tests/test_jsonld_adapter.py → monitor/adapters/jsonld.py
- `test_single_failing_url_does_not_stop_other_urls()` --uses--> `JsonLdAdapter`  [INFERRED]
  tests/test_jsonld_adapter.py → monitor/adapters/jsonld.py
- `test_http_404_produces_no_observation()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_validation_and_fixes.py → monitor/adapters/playwright.py

## Import Cycles
- None detected.

## Communities (73 total, 42 thin omitted)

### Community 0 - "_create_sample_obs"
Cohesion: 0.19
Nodes (6): _create_sample_obs(), test_check_single_url_offline(), test_failed_first_fetch_creates_no_variant(), test_readded_url_reactivates_without_alert(), test_removed_url_creates_no_events_and_is_no_longer_fetched(), test_second_run_with_no_changes_sends_nothing()

### Community 1 - "HttpError"
Cohesion: 0.14
Nodes (12): HttpError, test_all_strategies_fail_gracefully_without_crash(), fake_http_get(), test_normal_shopify_store_uses_existing_products_json(), test_yanybeauty_handle_based_shopify_json_fallback(), fake_http_get(), test_yanybeauty_jsonld_fallback(), fake_http_get() (+4 more)

### Community 3 - "test_money.py"
Cohesion: 0.12
Nodes (11): parse_price(), to_cents(), test_cents_to_str(), test_parse_price_locales(), test_to_cents_currency_and_separators(), test_to_cents_integers_and_floats(), test_to_cents_invalid_string(), test_to_cents_none_and_empty() (+3 more)

### Community 4 - "test_detector.py"
Cohesion: 0.14
Nodes (11): detect(), make_obs(), test_detect_back_in_stock(), test_detect_change_smaller_than_threshold_ignored(), test_detect_new_variant(), test_detect_out_of_stock(), test_detect_previous_none_explicit(), test_detect_price_and_stock_change_together() (+3 more)

### Community 5 - "PlaywrightAdapter"
Cohesion: 0.09
Nodes (11): PlaywrightAdapter, sample_config(), sample_html_fixture(), test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_missing_availability_is_none(), test_missing_price_never_guesses_zero(), test_parse_real_fixture_offline() (+3 more)

### Community 6 - "GitHub Actions Automation & Scheduling"
Cohesion: 0.07
Nodes (28): 1. Create a Supabase Project, 1. Installation, 1. Private Repository Recommendation, 2. Configuration, 2. Configure GitHub Secrets, 2. Copy the "Session Pooler" Connection String, 3. Encode Special Characters in Your Password, 3. Manual Run via `workflow_dispatch` (+20 more)

### Community 7 - "Pg8000DictCursor"
Cohesion: 0.09
Nodes (3): DictRow, Pg8000ConnectionAdapter, Pg8000DictCursor

### Community 8 - "runner.py"
Cohesion: 0.11
Nodes (6): build_error_message(), validate(), test_build_error_message(), playwright_config(), test_validator_detects_suspicious_price_changes(), test_validator_rejects_missing_or_invalid_fields()

### Community 11 - "test_ci_and_scheduling.py"
Cohesion: 0.08
Nodes (13): run_ci_check(), main(), build_crash_alert_message(), SecretMaskingFilter, setup_logging(), test_ci_check_fails_on_database_unreachable(), test_ci_check_fails_on_missing_env_vars(), test_ci_check_fails_on_playwright_launch_error() (+5 more)

### Community 12 - "SqliteStorage"
Cohesion: 0.06
Nodes (5): backup_database_if_needed(), find_active_variant_ids_by_url_substr(), is_variant_in_catalog(), SqliteStorage, test_automatic_backup_creation_before_migration()

### Community 13 - "Any"
Cohesion: 0.10
Nodes (7): format_iso_timestamp(), insert_error_record(), PostgresStorage, record_run_finish(), record_run_start(), record_site_run(), set_meta()

### Community 15 - "get_unnotified_events"
Cohesion: 0.22
Nodes (5): get_unnotified_events(), test_new_product_silent_baseline_and_summary_message(), test_dry_run_does_not_send_or_mark_notified(), test_runner_marks_notified_only_on_success(), test_send_message_failure_and_retries()

### Community 16 - "fetch_with_fallback"
Cohesion: 0.15
Nodes (4): fetch_with_fallback(), get_store_origin(), get_target_urls_for_site(), test_extract_product_handle_and_store_origin()

### Community 18 - "FetchResult"
Cohesion: 0.12
Nodes (6): SiteAdapter, JsonLdAdapter, clean_and_deduplicate_title(), extract_product_handle(), FetchResult, test_clean_and_deduplicate_title_cases()

### Community 19 - "ShopifyAdapter"
Cohesion: 0.13
Nodes (9): ShopifyAdapter, adapter(), sample_payload(), test_availability_extracted_correctly(), test_empty_payload_handled_gracefully(), test_fixture_parsing_total_variants(), test_missing_price_is_none_never_zero(), test_prices_extracted_correctly() (+1 more)

### Community 20 - "to_bigint_id"
Cohesion: 0.13
Nodes (4): to_bigint_id(), test_to_bigint_id_non_numeric(), test_to_bigint_id_none(), test_to_bigint_id_numeric()

### Community 21 - "Observation"
Cohesion: 0.16
Nodes (13): Observation, batch_insert_price_checks(), batch_upsert_variants(), get_last_check(), get_variant_ids_for_site(), insert_price_check(), is_price_checks_empty(), upsert_variant() (+5 more)

### Community 22 - "escape_html"
Cohesion: 0.10
Nodes (10): build_delivery_failure_alert(), build_message(), build_new_variants_summary(), build_site_status_change_message(), escape_html(), format_event_block(), test_build_new_variants_summary_cap_at_10(), test_build_message_grouping() (+2 more)

### Community 23 - "get_meta"
Cohesion: 0.29
Nodes (4): get_meta(), test_heartbeat_failed_send_does_not_mark_as_sent(), test_team_delivery_failure_alerts_admin_once_and_recovers(), test_team_delivery_failure_keeps_events_unnotified()

### Community 24 - "create_adapter"
Cohesion: 0.10
Nodes (10): format_price_change(), check_single_url(), create_adapter(), load_config(), print_health_summary(), _print_summary(), cents_to_str(), test_format_price_change() (+2 more)

### Community 25 - "shopify.py"
Cohesion: 0.18
Nodes (6): http_get(), is_captcha_challenge(), is_generic_redirect(), is_json_response(), parse_json_safely(), test_is_json_response_and_parse_json_safely()

### Community 26 - "storage.py"
Cohesion: 0.15
Nodes (8): _get_active_target_urls_from_csv(), run_once(), batch_insert_events(), deactivate_removed_variants(), get_latest_site_statuses(), get_site_latest_checks(), get_site_variant_ids(), mark_events_notified()

### Community 27 - "get_storage"
Cohesion: 0.20
Nodes (5): get_storage(), test_ci_check_success_when_all_components_healthy(), test_ci_guard_permits_explicit_db_path_in_tests(), test_ci_guard_raises_error_when_database_url_missing(), test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout()

### Community 28 - "test_jsonld_adapter.py"
Cohesion: 0.09
Nodes (10): sample_config(), sample_html_fixture(), test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_graph_and_array_extraction(), test_missing_price_never_guesses_zero(), test_multiple_variants_handling(), test_parse_real_fixture_offline() (+2 more)

### Community 29 - "process_presence_and_delisting"
Cohesion: 0.25
Nodes (5): insert_event(), process_presence_and_delisting(), test_confirmed_absence_delisting_and_relisting(), test_fetch_error_never_counts_as_miss(), test_redirect_to_homepage_classified_as_error_not_miss()

### Community 30 - "test_reliability_features.py"
Cohesion: 0.12
Nodes (8): test_crash_alert_message_format(), test_delisted_and_relisted_combined_in_one_team_section(), test_http_get_no_retry_on_403_and_captcha(), test_http_get_no_retry_on_404_and_410(), test_http_get_redirect_to_homepage_classified_as_not_found(), test_http_get_retry_after_capped_at_60s(), test_http_get_retry_after_within_60s_sleeps_and_retries(), test_team_delivery_failure_alert_format()

### Community 32 - "test_storage_backends.py"
Cohesion: 0.10
Nodes (13): mask_database_url(), get_postgres_row_count(), get_price_checks_timestamp_range(), get_readonly_sqlite_conn(), get_sqlite_row_count(), migrate_table(), reset_identity_sequences(), run_migration() (+5 more)

### Community 34 - "get_connection"
Cohesion: 0.15
Nodes (11): get_connection(), get_site_state(), init_db(), upsert_site_state(), test_safe_migration_adds_active_column(), test_daily_heartbeat_meta_tracking(), test_error_records_in_fetch_result_and_db(), test_print_health_summary_read_only() (+3 more)

### Community 36 - "test_run_once_second_run_detects_price_drop"
Cohesion: 0.32
Nodes (3): test_run_once_baseline_creates_no_events(), test_run_once_handles_failing_site(), test_run_once_second_run_detects_price_drop()

### Community 38 - "notifier.py"
Cohesion: 0.17
Nodes (6): build_heartbeat_message(), send_error_message(), send_message(), test_connection(), test_send_error_message_routes_to_error_bot(), test_send_message_success()

### Community 39 - "storage_backend"
Cohesion: 0.25
Nodes (3): storage_backend(), test_get_storage_selects_backend(), test_sqlite_file_locking()

## Knowledge Gaps
- **21 isolated node(s):** `Project Structure`, `1. Installation`, `2. Configuration`, `3. Telegram Setup & Preview`, `Exit Codes` (+16 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 369 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **42 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Observation` connect `Observation` to `_create_sample_obs`, `HttpError`, `test_detector.py`, `PlaywrightAdapter`, `runner.py`, `test_ci_and_scheduling.py`, `SqliteStorage`, `Any`, `.parse_html`, `get_unnotified_events`, `fetch_with_fallback`, `._extract_page`, `FetchResult`, `ShopifyAdapter`, `to_bigint_id`, `get_meta`, `shopify.py`, `storage.py`, `get_storage`, `test_jsonld_adapter.py`, `process_presence_and_delisting`, `test_reliability_features.py`, `BaseStorage`, `test_storage_backends.py`, `test_failed_url_does_not_create_out_of_stock_event`, `get_connection`, `test_run_once_second_run_detects_price_drop`, `._fetch_generic_products_json`, `.batch_insert_price_checks`, `.batch_upsert_variants`, `test_storage_contract_lifecycle`?**
  _High betweenness centrality (0.272) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `Observation` (e.g. with `JsonLdAdapter` and `PlaywrightAdapter`) actually correct?**
  _`Observation` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project Structure`, `1. Installation`, `2. Configuration` to the rest of the system?**
  _21 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `HttpError` be split into smaller, more focused modules?**
  _Cohesion score 0.1422924901185771 - nodes in this community are weakly interconnected._
- **Why does `BaseStorage` connect `BaseStorage` to `SqliteStorage`, `Any`, `Observation`, `storage.py`, `get_storage`, `test_storage_backends.py`, `.deactivate_removed_variants`, `.find_active_variant_ids_by_url_substr`, `.get_last_check`, `.get_latest_site_statuses`, `.get_meta`, `.get_unnotified_events`, `.transaction`, `.init_db`, `.insert_error_record`, `.batch_insert_events`, `.batch_insert_price_checks`, `.is_variant_in_catalog`, `.mark_events_notified`, `.is_price_checks_empty`, `.record_site_run`, `.release_lock`, `.set_meta`, `.record_run_start`, `.batch_upsert_variants`, `.get_site_latest_checks`, `.record_run_finish`, `.upsert_site_state`, `datetime`, `.get_site_variant_ids`, `.get_variant_ids_for_site`, `test_storage_contract_lifecycle`?**
  _High betweenness centrality (0.127) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `PostgresStorage` (e.g. with `Observation` and `get_postgres_row_count()`) actually correct?**
  _`PostgresStorage` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_money.py` be split into smaller, more focused modules?**
  _Cohesion score 0.12 - nodes in this community are weakly interconnected._