# Graph Report - Shopify_skin_care_price_monitoring_bot  (2026-10-08)

## Corpus Check
- 37 files · ~64,224 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 2, .example 1, .csv 1)

## Summary
- 874 nodes · 2034 edges · 73 communities (31 shown, 42 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 78 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cf54fd75`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- FetchResult
- HttpError
- ._extract_page
- test_money.py
- test_detector.py
- playwright.py
- GitHub Actions Automation & Scheduling
- Pg8000DictCursor
- test_playwright_validation_and_fixes.py
- run_ci_check
- SqliteStorage
- PostgresStorage
- sqlite3
- test_fallback_strategy.py
- .fetch
- ShopifyAdapter
- test_shopify_adapter.py
- format_iso_timestamp
- Observation
- escape_html
- run_once
- main.py
- jsonld.py
- storage.py
- test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout
- JsonLdAdapter
- build_message
- pytest
- BaseStorage
- migrate_sqlite_to_postgres.py
- test_ci_and_scheduling.py
- get_connection
- test_runner.py
- ErrorRecord
- runner.py
- test_storage_backends.py
- setup_logging
- test_main_exits_nonzero_only_on_crash
- sample_config
- sample_config
- test_http_404_produces_no_observation
- mask_database_url
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

## Communities (73 total, 42 thin omitted)

### Community 0 - "FetchResult"
Cohesion: 0.16
Nodes (9): FetchResult, _create_sample_obs(), test_check_single_url_offline(), test_duplicate_url_warning_and_deduplication(), test_failed_first_fetch_creates_no_variant(), test_new_product_silent_baseline_and_summary_message(), test_readded_url_reactivates_without_alert(), test_removed_url_creates_no_events_and_is_no_longer_fetched() (+1 more)

### Community 1 - "HttpError"
Cohesion: 0.16
Nodes (11): HttpError, test_all_strategies_fail_gracefully_without_crash(), fake_http_get(), test_yanybeauty_handle_based_shopify_json_fallback(), fake_http_get(), test_yanybeauty_jsonld_fallback(), fake_http_get(), test_yanybeauty_playwright_js_rendered_fallback() (+3 more)

### Community 3 - "test_money.py"
Cohesion: 0.11
Nodes (10): parse_price(), to_cents(), test_parse_price_locales(), test_to_cents_currency_and_separators(), test_to_cents_integers_and_floats(), test_to_cents_invalid_string(), test_to_cents_none_and_empty(), test_to_cents_single_decimal() (+2 more)

### Community 4 - "test_detector.py"
Cohesion: 0.13
Nodes (11): detect(), make_obs(), test_detect_back_in_stock(), test_detect_change_smaller_than_threshold_ignored(), test_detect_new_variant(), test_detect_out_of_stock(), test_detect_previous_none_explicit(), test_detect_price_and_stock_change_together() (+3 more)

### Community 5 - "playwright.py"
Cohesion: 0.10
Nodes (7): test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_missing_availability_is_none(), test_missing_price_never_guesses_zero(), test_parse_real_fixture_offline(), test_single_failing_url_does_not_stop_other_urls(), test_variant_selector_handling()

### Community 6 - "GitHub Actions Automation & Scheduling"
Cohesion: 0.07
Nodes (28): 1. Create a Supabase Project, 1. Installation, 1. Private Repository Recommendation, 2. Configuration, 2. Configure GitHub Secrets, 2. Copy the "Session Pooler" Connection String, 3. Encode Special Characters in Your Password, 3. Manual Run via `workflow_dispatch` (+20 more)

### Community 7 - "Pg8000DictCursor"
Cohesion: 0.09
Nodes (3): DictRow, Pg8000ConnectionAdapter, Pg8000DictCursor

### Community 8 - "test_playwright_validation_and_fixes.py"
Cohesion: 0.12
Nodes (7): validate(), playwright_config(), test_failed_url_does_not_create_out_of_stock_event(), test_real_soko_glam_fixture_title_and_price(), test_runner_never_saves_invalid_observations(), test_validator_detects_suspicious_price_changes(), test_validator_rejects_missing_or_invalid_fields()

### Community 11 - "run_ci_check"
Cohesion: 0.17
Nodes (5): run_ci_check(), test_ci_check_fails_on_database_unreachable(), test_ci_check_fails_on_missing_env_vars(), test_ci_check_fails_on_missing_python_module(), test_ci_check_fails_on_playwright_launch_error()

### Community 15 - "sqlite3"
Cohesion: 0.22
Nodes (3): backup_database_if_needed(), test_automatic_backup_creation_before_migration(), memory_db()

### Community 16 - "test_fallback_strategy.py"
Cohesion: 0.17
Nodes (6): PlaywrightAdapter, extract_product_handle(), fetch_with_fallback(), get_store_origin(), get_target_urls_for_site(), test_extract_product_handle_and_store_origin()

### Community 18 - "ShopifyAdapter"
Cohesion: 0.09
Nodes (4): SiteAdapter, create_adapter(), __getattr__(), ShopifyAdapter

### Community 19 - "test_shopify_adapter.py"
Cohesion: 0.11
Nodes (8): adapter(), sample_payload(), test_availability_extracted_correctly(), test_empty_payload_handled_gracefully(), test_fixture_parsing_total_variants(), test_missing_price_is_none_never_zero(), test_prices_extracted_correctly(), test_variant_ids_and_titles()

### Community 21 - "Observation"
Cohesion: 0.15
Nodes (14): Observation, batch_insert_price_checks(), batch_upsert_variants(), deactivate_removed_variants(), get_last_check(), get_variant_ids_for_site(), insert_price_check(), is_price_checks_empty() (+6 more)

### Community 22 - "escape_html"
Cohesion: 0.12
Nodes (9): build_new_variants_summary(), escape_html(), format_event_block(), format_price_change(), cents_to_str(), test_cents_to_str(), test_build_new_variants_summary_cap_at_10(), test_escape_html() (+1 more)

### Community 23 - "run_once"
Cohesion: 0.10
Nodes (15): build_delivery_failure_alert(), build_heartbeat_message(), build_site_status_change_message(), _get_active_target_urls_from_csv(), run_once(), get_meta(), get_unnotified_events(), test_dry_run_does_not_send_or_mark_notified() (+7 more)

### Community 24 - "main.py"
Cohesion: 0.21
Nodes (5): main(), build_crash_alert_message(), check_single_url(), print_health_summary(), test_crash_alert_message_format()

### Community 25 - "jsonld.py"
Cohesion: 0.14
Nodes (7): http_get(), is_captcha_challenge(), is_generic_redirect(), is_json_response(), parse_json_safely(), test_is_json_response_and_parse_json_safely(), test_normal_shopify_store_uses_existing_products_json()

### Community 26 - "storage.py"
Cohesion: 0.11
Nodes (14): batch_insert_events(), find_active_variant_ids_by_url_substr(), get_latest_site_statuses(), get_site_latest_checks(), get_site_variant_ids(), insert_error_record(), insert_event(), is_variant_in_catalog() (+6 more)

### Community 27 - "test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout"
Cohesion: 0.29
Nodes (3): test_ci_check_success_when_all_components_healthy(), test_ci_guard_permits_explicit_db_path_in_tests(), test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout()

### Community 28 - "JsonLdAdapter"
Cohesion: 0.12
Nodes (9): JsonLdAdapter, test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_graph_and_array_extraction(), test_missing_price_never_guesses_zero(), test_multiple_variants_handling(), test_parse_real_fixture_offline(), test_single_failing_url_does_not_stop_other_urls() (+1 more)

### Community 29 - "build_message"
Cohesion: 0.25
Nodes (4): build_message(), test_build_message_grouping(), test_build_message_splitting_at_boundaries(), test_delisted_and_relisted_combined_in_one_team_section()

### Community 30 - "pytest"
Cohesion: 0.15
Nodes (6): test_ci_guard_raises_error_when_database_url_missing(), test_http_get_no_retry_on_403_and_captcha(), test_http_get_no_retry_on_404_and_410(), test_http_get_redirect_to_homepage_classified_as_not_found(), test_http_get_retry_after_capped_at_60s(), test_create_adapter()

### Community 32 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.11
Nodes (10): parse_args(), get_postgres_row_count(), get_price_checks_timestamp_range(), get_readonly_sqlite_conn(), get_sqlite_row_count(), migrate_table(), parse_args(), reset_identity_sequences() (+2 more)

### Community 34 - "get_connection"
Cohesion: 0.14
Nodes (12): get_connection(), get_site_state(), init_db(), set_meta(), upsert_site_state(), test_safe_migration_adds_active_column(), test_daily_heartbeat_meta_tracking(), test_fetch_error_never_counts_as_miss() (+4 more)

### Community 36 - "test_runner.py"
Cohesion: 0.12
Nodes (7): create_adapter(), load_config(), _print_summary(), test_load_config(), test_run_once_baseline_creates_no_events(), test_run_once_handles_failing_site(), test_run_once_second_run_detects_price_drop()

### Community 38 - "runner.py"
Cohesion: 0.14
Nodes (8): build_error_message(), send_error_message(), send_message(), test_connection(), test_build_error_message(), test_send_error_message_routes_to_error_bot(), test_send_message_failure_and_retries(), test_send_message_success()

### Community 39 - "test_storage_backends.py"
Cohesion: 0.11
Nodes (8): get_storage(), storage_backend(), test_get_storage_selects_backend(), test_postgres_advisory_lock_mocked(), test_sqlite_file_locking(), test_to_bigint_id_non_numeric(), test_to_bigint_id_none(), test_to_bigint_id_numeric()

### Community 40 - "setup_logging"
Cohesion: 0.16
Nodes (4): SecretMaskingFilter, setup_logging(), test_secret_masking_applied_to_log_record(), test_secret_masking_filter_redacts_credentials_and_tokens()

### Community 41 - "test_main_exits_nonzero_only_on_crash"
Cohesion: 0.29
Nodes (3): test_main_exits_nonzero_only_on_crash(), test_main_exits_zero_even_when_sites_failed(), test_main_exits_zero_on_advisory_lock()

### Community 68 - "mask_database_url"
Cohesion: 0.13
Nodes (6): clean_database_url(), mask_database_url(), test_mask_database_url_no_password(), test_mask_database_url_none_or_empty(), test_mask_database_url_special_characters(), test_mask_database_url_standard()

## Knowledge Gaps
- **21 isolated node(s):** `Project Structure`, `1. Installation`, `2. Configuration`, `3. Telegram Setup & Preview`, `Exit Codes` (+16 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 373 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **42 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Observation` connect `Observation` to `FetchResult`, `HttpError`, `._extract_page`, `test_detector.py`, `playwright.py`, `test_playwright_validation_and_fixes.py`, `SqliteStorage`, `PostgresStorage`, `.parse_html`, `test_fallback_strategy.py`, `.fetch`, `ShopifyAdapter`, `format_iso_timestamp`, `run_once`, `jsonld.py`, `storage.py`, `test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout`, `JsonLdAdapter`, `BaseStorage`, `migrate_sqlite_to_postgres.py`, `test_ci_and_scheduling.py`, `get_connection`, `test_runner.py`, `runner.py`, `test_storage_backends.py`, `.batch_insert_price_checks`, `.batch_upsert_variants`, `test_storage_contract_lifecycle`?**
  _High betweenness centrality (0.278) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `Observation` (e.g. with `JsonLdAdapter` and `PlaywrightAdapter`) actually correct?**
  _`Observation` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project Structure`, `1. Installation`, `2. Configuration` to the rest of the system?**
  _21 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `test_money.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1111111111111111 - nodes in this community are weakly interconnected._
- **Why does `BaseStorage` connect `BaseStorage` to `SqliteStorage`, `PostgresStorage`, `Observation`, `storage.py`, `test_storage_backends.py`, `.deactivate_removed_variants`, `.get_last_check`, `.get_latest_site_statuses`, `.get_meta`, `.get_unnotified_events`, `.transaction`, `.insert_error_record`, `.batch_insert_events`, `.batch_insert_price_checks`, `.is_variant_in_catalog`, `.mark_events_notified`, `.is_price_checks_empty`, `.acquire_lock`, `.release_lock`, `.set_meta`, `.check_health`, `.batch_upsert_variants`, `.get_site_latest_checks`, `.record_run_finish`, `.upsert_site_state`, `.close`, `.get_site_variant_ids`, `.get_variant_ids_for_site`, `.get_site_state`, `test_storage_contract_lifecycle`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `PostgresStorage` (e.g. with `Observation` and `get_postgres_row_count()`) actually correct?**
  _`PostgresStorage` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_detector.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1282051282051282 - nodes in this community are weakly interconnected._