# Graph Report - Shopify_skin_care_price_monitoring_bot  (2026-10-07)

## Corpus Check
- 32 files · ~44,732 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: (none) 2, .example 1, .csv 1)

## Summary
- 461 nodes · 1073 edges · 21 communities (14 shown, 7 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 48 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Observation
- test_playwright_validation_and_fixes.py
- FetchResult
- test_money.py
- detect
- test_playwright_adapter.py
- Quickstart Guide
- ShopifyAdapter
- main.py
- runner.py
- JsonLdAdapter
- test_runner.py
- fallback.py
- test_fallback_strategy.py
- ._extract_page
- sample_config

## God Nodes (most connected - your core abstractions)
1. `Observation` - 45 edges
2. `run_once()` - 45 edges
3. `FetchResult` - 38 edges
4. `JsonLdAdapter` - 28 edges
5. `PlaywrightAdapter` - 28 edges
6. `ShopifyAdapter` - 28 edges
7. `HttpError` - 24 edges
8. `get_connection()` - 18 edges
9. `detect()` - 16 edges
10. `fetch_with_fallback()` - 16 edges

## Surprising Connections (you probably didn't know these)
- `test_blocked_403_stops_site_run()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_adapter.py → monitor/adapters/playwright.py
- `test_captcha_stops_site_run()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_adapter.py → monitor/adapters/playwright.py
- `test_single_failing_url_does_not_stop_other_urls()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_adapter.py → monitor/adapters/playwright.py
- `test_http_404_produces_no_observation()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_validation_and_fixes.py → monitor/adapters/playwright.py
- `test_redirect_to_generic_home_or_404_page()` --uses--> `PlaywrightAdapter`  [INFERRED]
  tests/test_playwright_validation_and_fixes.py → monitor/adapters/playwright.py

## Import Cycles
- None detected.

## Communities (21 total, 7 thin omitted)

### Community 0 - "Observation"
Cohesion: 0.06
Nodes (27): Observation, run_once(), deactivate_removed_variants(), get_connection(), get_last_check(), get_variant_ids_for_site(), init_db(), insert_event() (+19 more)

### Community 1 - "test_playwright_validation_and_fixes.py"
Cohesion: 0.10
Nodes (9): validate(), playwright_config(), test_failed_url_does_not_create_out_of_stock_event(), test_http_404_produces_no_observation(), test_real_soko_glam_fixture_title_and_price(), test_redirect_to_generic_home_or_404_page(), test_runner_never_saves_invalid_observations(), test_validator_detects_suspicious_price_changes() (+1 more)

### Community 2 - "FetchResult"
Cohesion: 0.17
Nodes (3): SiteAdapter, PlaywrightAdapter, FetchResult

### Community 3 - "test_money.py"
Cohesion: 0.11
Nodes (12): cents_to_str(), parse_price(), to_cents(), test_cents_to_str(), test_parse_price_locales(), test_to_cents_currency_and_separators(), test_to_cents_integers_and_floats(), test_to_cents_invalid_string() (+4 more)

### Community 4 - "detect"
Cohesion: 0.12
Nodes (11): detect(), make_obs(), test_detect_back_in_stock(), test_detect_change_smaller_than_threshold_ignored(), test_detect_new_variant(), test_detect_out_of_stock(), test_detect_previous_none_explicit(), test_detect_price_and_stock_change_together() (+3 more)

### Community 5 - "test_playwright_adapter.py"
Cohesion: 0.10
Nodes (9): sample_config(), sample_html_fixture(), test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_missing_availability_is_none(), test_missing_price_never_guesses_zero(), test_parse_real_fixture_offline(), test_single_failing_url_does_not_stop_other_urls() (+1 more)

### Community 6 - "Quickstart Guide"
Cohesion: 0.20
Nodes (9): 1. Installation, 2. Configuration, 3. Telegram Setup & Preview, 4. Running the Monitor, 5. Running the Tests, E-Commerce Price Monitoring Bot, Key Design Principles, Project Structure (+1 more)

### Community 8 - "ShopifyAdapter"
Cohesion: 0.06
Nodes (20): ShopifyAdapter, HttpError, test_all_strategies_fail_gracefully_without_crash(), fake_http_get(), test_yanybeauty_handle_based_shopify_json_fallback(), fake_http_get(), test_yanybeauty_jsonld_fallback(), fake_http_get() (+12 more)

### Community 11 - "main.py"
Cohesion: 0.17
Nodes (3): main(), parse_args(), setup_logging()

### Community 12 - "runner.py"
Cohesion: 0.07
Nodes (19): build_error_message(), build_message(), build_new_variants_summary(), escape_html(), format_event_block(), format_price_change(), send_error_message(), send_message() (+11 more)

### Community 13 - "JsonLdAdapter"
Cohesion: 0.11
Nodes (9): JsonLdAdapter, test_blocked_403_stops_site_run(), test_captcha_stops_site_run(), test_graph_and_array_extraction(), test_missing_price_never_guesses_zero(), test_multiple_variants_handling(), test_parse_real_fixture_offline(), test_single_failing_url_does_not_stop_other_urls() (+1 more)

### Community 15 - "test_runner.py"
Cohesion: 0.08
Nodes (12): check_single_url(), create_adapter(), load_config(), _print_summary(), get_unnotified_events(), test_dry_run_does_not_send_or_mark_notified(), test_runner_marks_notified_only_on_success(), test_create_adapter() (+4 more)

### Community 16 - "fallback.py"
Cohesion: 0.16
Nodes (5): extract_product_handle(), fetch_with_fallback(), get_store_origin(), get_target_urls_for_site(), test_extract_product_handle_and_store_origin()

### Community 18 - "test_fallback_strategy.py"
Cohesion: 0.19
Nodes (5): http_get(), is_json_response(), parse_json_safely(), test_is_json_response_and_parse_json_safely(), test_normal_shopify_store_uses_existing_products_json()

## Knowledge Gaps
- **7 isolated node(s):** `Project Structure`, `1. Installation`, `2. Configuration`, `3. Telegram Setup & Preview`, `4. Running the Monitor` (+2 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 218 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Observation` connect `Observation` to `test_playwright_validation_and_fixes.py`, `FetchResult`, `detect`, `test_playwright_adapter.py`, `.parse_html`, `ShopifyAdapter`, `runner.py`, `JsonLdAdapter`, `test_runner.py`, `fallback.py`, `test_fallback_strategy.py`, `._extract_page`?**
  _High betweenness centrality (0.192) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `Observation` (e.g. with `JsonLdAdapter` and `PlaywrightAdapter`) actually correct?**
  _`Observation` has 12 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Project Structure`, `1. Installation`, `2. Configuration` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Observation` be split into smaller, more focused modules?**
  _Cohesion score 0.059940059940059943 - nodes in this community are weakly interconnected._
- **Why does `FetchResult` connect `FetchResult` to `Observation`, `test_playwright_validation_and_fixes.py`, `test_playwright_adapter.py`, `ShopifyAdapter`, `runner.py`, `JsonLdAdapter`, `test_runner.py`, `fallback.py`, `test_fallback_strategy.py`, `._extract_page`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `FetchResult` (e.g. with `SiteAdapter` and `JsonLdAdapter`) actually correct?**
  _`FetchResult` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_playwright_validation_and_fixes.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10276679841897234 - nodes in this community are weakly interconnected._