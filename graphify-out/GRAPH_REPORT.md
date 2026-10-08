# Graph Report - Shopify_skin_care_price_monitoring_bot  (2026-10-08)

## Corpus Check
- 37 files · ~65,015 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 2, .example 1, .csv 1)

## Summary
- 885 nodes · 2063 edges · 68 communities (29 shown, 39 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 81 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `425ea179`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- _create_sample_obs
- HttpError
- test_reliability_features.py
- test_money.py
- test_detector.py
- PlaywrightAdapter
- GitHub Actions Automation & Scheduling
- Pg8000DictCursor
- test_ci_and_scheduling.py
- os
- SqliteStorage
- PostgresStorage
- pytest
- runner.py
- fallback.py
- test_run_once_second_run_detects_price_drop
- FetchResult
- test_shopify_adapter.py
- test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout
- test_notifier.py
- send_message
- main.py
- test_fallback_strategy.py
- storage.py
- test_jsonld_adapter.py
- sample_config
- BaseStorage
- migrate_sqlite_to_postgres.py
- Observation
- run_once
- ErrorRecord
- send_error_message
- to_bigint_id
- logging_setup.py
- sample_config
- test_storage_contract_lifecycle
- test_playwright_validation_and_fixes.py
- test_storage_backends.py

## God Nodes (most connected - your core abstractions)
1. `Observation` - 74 edges
2. `run_once()` - 70 edges
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

## Communities (68 total, 39 thin omitted)

### Community 0 - "_create_sample_obs"
Cohesion: 0.15
Nodes (7): _create_sample_obs(), test_check_single_url_offline(), test_duplicate_url_warning_and_deduplication(), test_failed_first_fetch_creates_no_variant(), test_new_product_silent_baseline_and_summary_message(), test_removed_url_creates_no_events_and_is_no_longer_fetched(), test_second_run_with_no_changes_sends_nothing()

### Community 1 - "HttpError"
Cohesion: 0.16
Nodes (11): HttpError, test_all_strategies_fail_gracefully_without_crash(), fake_http_get(), test_yanybeauty_handle_based_shopify_json_fallback(), fake_http_get(), test_yanybeauty_jsonld_fallback(), fake_http_get(), test_yanybeauty_playwright_js_rendered_fallback() (+3 more)

### Community 2 - "test_reliability_features.py"
Cohesion: 0.10
Nodes (11): build_delivery_failure_alert(), build_heartbeat_message(), get_meta(), test_crash_alert_message_format(), test_daily_heartbeat_meta_tracking(), test_delisted_and_relisted_combined_in_one_team_section(), test_heartbeat_failed_send_does_not_mark_as_sent(), test_http_get_retry_after_within_60s_sleeps_and_retries() (+3 more)

### Community 3 - "test_money.py"
Cohesion: 0.12
Nodes (11): parse_price(), to_cents(), test_cents_to_str(), test_parse_price_locales(), test_to_cents_currency_and_separators(), test_to_cents_integers_and_floats(), test_to_cents_invalid_string(), test_to_cents_none_and_empty() (+3 more)

### Community 4 - "test_detector.py"
Cohesion: 0.13
Nodes (10): make_obs(), test_detect_back_in_stock(), test_detect_change_smaller_than_threshold_ignored(), test_detect_new_variant(), test_detect_out_of_stock(), test_detect_previous_none_explicit(), test_detect_price_and_stock_change_together(), test_detect_price_drop() (+2 more)

### Community 5 - "PlaywrightAdapter"
Cohesion: 0.09
Nodes (9): PlaywrightAdapter, is_timed_out(), test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_missing_availability_is_none(), test_missing_price_never_guesses_zero(), test_parse_real_fixture_offline(), test_single_failing_url_does_not_stop_other_urls() (+1 more)

### Community 6 - "GitHub Actions Automation & Scheduling"
Cohesion: 0.07
Nodes (28): 1. Create a Supabase Project, 1. Installation, 1. Private Repository Recommendation, 2. Configuration, 2. Configure GitHub Secrets, 2. Copy the "Session Pooler" Connection String, 3. Encode Special Characters in Your Password, 3. Manual Run via `workflow_dispatch` (+20 more)

### Community 7 - "Pg8000DictCursor"
Cohesion: 0.09
Nodes (3): DictRow, Pg8000ConnectionAdapter, Pg8000DictCursor

### Community 8 - "test_ci_and_scheduling.py"
Cohesion: 0.12
Nodes (8): load_config(), test_ci_check_fails_on_missing_env_vars(), test_ci_check_fails_on_playwright_launch_error(), test_default_config_path_points_to_existing_file_from_different_working_dir(), test_load_config_empty_value_falls_back_to_default_absolute_path(), test_load_config_raises_clear_error_for_missing_file_and_directory(), test_requirements_covers_all_third_party_imports(), test_workflow_yaml_structure_and_constraints()

### Community 11 - "os"
Cohesion: 0.21
Nodes (4): run_ci_check(), get_storage(), test_ci_check_fails_on_database_unreachable(), test_ci_check_fails_on_missing_python_module()

### Community 14 - "pytest"
Cohesion: 0.12
Nodes (8): test_ci_guard_raises_error_when_database_url_missing(), test_main_exits_nonzero_only_on_crash(), test_main_exits_zero_even_when_sites_failed(), test_main_exits_zero_on_advisory_lock(), test_http_get_no_retry_on_403_and_captcha(), test_http_get_no_retry_on_404_and_410(), test_http_get_redirect_to_homepage_classified_as_not_found(), test_http_get_retry_after_capped_at_60s()

### Community 16 - "fallback.py"
Cohesion: 0.16
Nodes (5): extract_product_handle(), fetch_with_fallback(), get_store_origin(), get_target_urls_for_site(), test_extract_product_handle_and_store_origin()

### Community 17 - "test_run_once_second_run_detects_price_drop"
Cohesion: 0.32
Nodes (3): test_run_once_baseline_creates_no_events(), test_run_once_handles_failing_site(), test_run_once_second_run_detects_price_drop()

### Community 18 - "FetchResult"
Cohesion: 0.09
Nodes (7): SiteAdapter, create_adapter(), __getattr__(), JsonLdAdapter, ShopifyAdapter, FetchResult, __getattr__()

### Community 19 - "test_shopify_adapter.py"
Cohesion: 0.11
Nodes (8): adapter(), sample_payload(), test_availability_extracted_correctly(), test_empty_payload_handled_gracefully(), test_fixture_parsing_total_variants(), test_missing_price_is_none_never_zero(), test_prices_extracted_correctly(), test_variant_ids_and_titles()

### Community 21 - "test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout"
Cohesion: 0.22
Nodes (4): test_ci_check_success_when_all_components_healthy(), test_ci_guard_permits_explicit_db_path_in_tests(), test_ci_guard_raises_error_even_when_config_path_invalid_or_missing(), test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout()

### Community 22 - "test_notifier.py"
Cohesion: 0.10
Nodes (14): build_crash_alert_message(), build_error_message(), build_message(), build_new_variants_summary(), build_site_status_change_message(), escape_html(), format_event_block(), format_price_change() (+6 more)

### Community 23 - "send_message"
Cohesion: 0.16
Nodes (7): send_message(), get_unnotified_events(), test_dry_run_does_not_send_or_mark_notified(), test_runner_marks_notified_only_on_success(), test_send_message_failure_and_retries(), test_send_message_success(), test_team_delivery_failure_keeps_events_unnotified()

### Community 24 - "main.py"
Cohesion: 0.14
Nodes (6): main(), parse_args(), test_connection(), check_single_url(), print_health_summary(), parse_args()

### Community 25 - "test_fallback_strategy.py"
Cohesion: 0.15
Nodes (7): http_get(), is_captcha_challenge(), is_generic_redirect(), is_json_response(), parse_json_safely(), test_is_json_response_and_parse_json_safely(), test_normal_shopify_store_uses_existing_products_json()

### Community 26 - "storage.py"
Cohesion: 0.11
Nodes (17): backup_database_if_needed(), batch_insert_events(), batch_upsert_variants(), deactivate_removed_variants(), find_active_variant_ids_by_url_substr(), format_iso_timestamp(), get_latest_site_statuses(), get_site_latest_checks() (+9 more)

### Community 28 - "test_jsonld_adapter.py"
Cohesion: 0.12
Nodes (8): test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_graph_and_array_extraction(), test_missing_price_never_guesses_zero(), test_multiple_variants_handling(), test_parse_real_fixture_offline(), test_single_failing_url_does_not_stop_other_urls(), test_unknown_availability_is_none()

### Community 32 - "migrate_sqlite_to_postgres.py"
Cohesion: 0.14
Nodes (9): get_postgres_row_count(), get_price_checks_timestamp_range(), get_readonly_sqlite_conn(), get_sqlite_row_count(), migrate_table(), reset_identity_sequences(), run_migration(), test_automatic_backup_creation_before_migration() (+1 more)

### Community 34 - "Observation"
Cohesion: 0.06
Nodes (31): Observation, batch_insert_price_checks(), get_connection(), get_last_check(), get_site_state(), get_variant_ids_for_site(), init_db(), insert_price_check() (+23 more)

### Community 36 - "run_once"
Cohesion: 0.16
Nodes (6): detect(), create_adapter(), _get_active_target_urls_from_csv(), _print_summary(), run_once(), test_create_adapter()

### Community 39 - "to_bigint_id"
Cohesion: 0.17
Nodes (4): to_bigint_id(), test_to_bigint_id_non_numeric(), test_to_bigint_id_none(), test_to_bigint_id_numeric()

### Community 40 - "logging_setup.py"
Cohesion: 0.14
Nodes (4): SecretMaskingFilter, setup_logging(), test_secret_masking_applied_to_log_record(), test_secret_masking_filter_redacts_credentials_and_tokens()

### Community 63 - "test_playwright_validation_and_fixes.py"
Cohesion: 0.11
Nodes (6): clean_and_deduplicate_title(), playwright_config(), test_clean_and_deduplicate_title_cases(), test_http_404_produces_no_observation(), test_real_soko_glam_fixture_title_and_price(), test_redirect_to_generic_home_or_404_page()

### Community 68 - "test_storage_backends.py"
Cohesion: 0.10
Nodes (10): clean_database_url(), mask_database_url(), storage_backend(), test_get_storage_selects_backend(), test_mask_database_url_no_password(), test_mask_database_url_none_or_empty(), test_mask_database_url_special_characters(), test_mask_database_url_standard() (+2 more)

## Knowledge Gaps
- **21 isolated node(s):** `Project Structure`, `1. Installation`, `2. Configuration`, `3. Telegram Setup & Preview`, `Exit Codes` (+16 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 379 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Observation` connect `Observation` to `_create_sample_obs`, `HttpError`, `test_reliability_features.py`, `test_detector.py`, `PlaywrightAdapter`, `test_ci_and_scheduling.py`, `SqliteStorage`, `PostgresStorage`, `runner.py`, `fallback.py`, `test_run_once_second_run_detects_price_drop`, `FetchResult`, `.parse_html`, `test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout`, `test_notifier.py`, `send_message`, `test_fallback_strategy.py`, `storage.py`, `._fetch_generic_products_json`, `test_jsonld_adapter.py`, `BaseStorage`, `migrate_sqlite_to_postgres.py`, `run_once`, `to_bigint_id`, `test_storage_contract_lifecycle`, `.batch_insert_price_checks`, `.batch_upsert_variants`, `test_playwright_validation_and_fixes.py`, `test_storage_backends.py`?**
  _High betweenness centrality (0.268) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `Observation` (e.g. with `JsonLdAdapter` and `PlaywrightAdapter`) actually correct?**
  _`Observation` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project Structure`, `1. Installation`, `2. Configuration` to the rest of the system?**
  _21 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `_create_sample_obs` be split into smaller, more focused modules?**
  _Cohesion score 0.14705882352941177 - nodes in this community are weakly interconnected._
- **Why does `BaseStorage` connect `BaseStorage` to `os`, `SqliteStorage`, `PostgresStorage`, `storage.py`, `Observation`, `.transaction`, `.get_site_variant_ids`, `.get_variant_ids_for_site`, `.deactivate_removed_variants`, `.get_last_check`, `.get_latest_site_statuses`, `.get_meta`, `test_storage_contract_lifecycle`, `.get_unnotified_events`, `.insert_error_record`, `.batch_insert_events`, `.batch_insert_price_checks`, `.is_variant_in_catalog`, `.mark_events_notified`, `.is_price_checks_empty`, `.acquire_lock`, `.release_lock`, `.set_meta`, `.check_health`, `.batch_upsert_variants`, `.get_site_latest_checks`, `.record_run_finish`, `.upsert_site_state`, `.close`, `test_storage_backends.py`, `.get_site_state`?**
  _High betweenness centrality (0.124) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `PostgresStorage` (e.g. with `Observation` and `get_postgres_row_count()`) actually correct?**
  _`PostgresStorage` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_reliability_features.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10276679841897234 - nodes in this community are weakly interconnected._