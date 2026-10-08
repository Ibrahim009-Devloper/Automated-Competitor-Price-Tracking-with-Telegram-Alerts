"""Tests for newly added products handling, safe migrations, and CLI inspections.

These offline tests verify all aspects of handling new and updated target products:
1. When a new product/variant is added to targets, it gets a silent baseline (notified = 1)
   so chat isn't flooded with individual alerts, plus ONE grouped summary message is sent.
2. The summary message is skipped on the very first baseline run.
3. Second run with no changes sends nothing.
4. Removed target URLs are marked active = 0, never deleted, stopped from being fetched,
   and do NOT create out_of_stock events or appear in alerts.
5. Re-added URLs reactivate (active = 1) without a new_variant alert.
6. Duplicate URLs in targets.csv trigger a warning and are processed only once.
7. Failed first fetch / invalid observation creates no variant and doesn't send a team alert.
8. Safe database migration adds 'active' column to existing legacy databases.
9. Summary message caps list at 10 titles, then displays 'and N more'.
10. CLI --check-url displays product details without writing anything to the database.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from monitor.models import FetchResult, Observation
from monitor.notifier import build_new_variants_summary
from monitor.runner import check_single_url, run_once
from monitor import storage


def _create_sample_obs(
    variant_id: str,
    product_title: str,
    price_cents: int = 2500,
    site: str = "Test Store",
    url: str = "https://example.com/product-1",
    available: bool = True,
) -> Observation:
    """Helper to create a sample Observation model for testing."""
    return Observation(
        site=site,
        product_id="prod_100",
        variant_id=str(variant_id),
        product_title=product_title,
        variant_title="Standard Size",
        price_cents=price_cents,
        compare_at_cents=None,
        currency="USD",
        available=available,
        url=url,
        fetched_at=datetime.now(timezone.utc),
    )


# ==============================================================================
# Test 1: Safe Migration of Existing Database
# ==============================================================================

def test_safe_migration_adds_active_column(tmp_path: Path) -> None:
    """Verify that init_db() safely adds 'active' column to an existing database."""
    db_file = tmp_path / "legacy.db"

    # Step 1: Create a legacy database where 'variants' table does NOT have 'active' column
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE variants (
            variant_id TEXT PRIMARY KEY,
            product_id TEXT,
            product_title TEXT,
            variant_title TEXT,
            site TEXT,
            url TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    # Insert an existing legacy variant
    conn.execute(
        """
        INSERT INTO variants (variant_id, product_title, site)
        VALUES ('legacy_v1', 'Legacy Face Cream', 'Test Store');
        """
    )
    conn.commit()
    conn.close()

    # Step 2: Run init_db() on the existing database
    storage.init_db(str(db_file))
    conn2 = storage.get_connection(str(db_file))

    # Step 3: Check columns of variants table
    cur = conn2.cursor()
    cur.execute("PRAGMA table_info(variants);")
    columns = [col[1] for col in cur.fetchall()]
    assert "active" in columns, "The 'active' column should have been added via safe migration"

    # Step 4: Check that existing legacy row has active = 1 by default
    cur.execute("SELECT active FROM variants WHERE variant_id = 'legacy_v1';")
    row = cur.fetchone()
    assert row[0] == 1, "Existing legacy variant should default to active = 1"
    conn2.close()


# ==============================================================================
# Test 2: Silent Baseline for New Variants & Summary Message
# ==============================================================================

def test_new_product_silent_baseline_and_summary_message(tmp_path: Path) -> None:
    """When a new product URL is added later, create new_variant event with notified=1
    and send ONE grouped summary message instead of individual alerts.
    """
    db_path = str(tmp_path / "test.db")
    config_file = tmp_path / "sites.yaml"
    config_file.write_text(
        """
sites:
  - name: "Test Store"
    adapter: "shopify"
    base_url: "https://example.com"
    currency: "USD"
        """,
        encoding="utf-8",
    )

    # 1. Establish initial baseline run with 1 product
    obs1 = _create_sample_obs("var_1", "Original Serum", price_cents=2000)
    mock_result_1 = FetchResult(observations=[obs1])

    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=mock_result_1), \
         patch("monitor.runner.send_message") as mock_send:
        # Run 1: Very first run (baseline). Price checks table starts empty.
        stats_1 = run_once(config_path=str(config_file), db_path=db_path)
        assert stats_1["is_baseline"] is True
        # Summary message must be skipped on the very first baseline run (Rule 2)
        mock_send.assert_not_called()

    # 2. Second run: A new product URL is added later (var_2) alongside var_1
    obs2 = _create_sample_obs("var_2", "Newly Added Moisturizer", price_cents=3500)
    mock_result_2 = FetchResult(observations=[obs1, obs2])

    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=mock_result_2), \
         patch("monitor.runner.send_message") as mock_send:
        stats_2 = run_once(config_path=str(config_file), db_path=db_path)

        assert stats_2["is_baseline"] is False
        assert stats_2["new_variants"] == 1

        # Check SQLite events table directly
        conn = storage.get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT variant_id, event_type, notified FROM events WHERE variant_id = 'var_2';")
        event_row = cur.fetchone()
        assert event_row is not None, "A new_variant event should be created"
        assert event_row[1] == "new_variant"
        # Rule 1: notified must be 1 so no individual alert is sent
        assert event_row[2] == 1, "The new_variant event must have notified=1 (silent baseline)"

        # Verify that get_unnotified_events does NOT return var_2
        unnotified = storage.get_unnotified_events(conn)
        assert len(unnotified) == 0, "No unnotified events should exist for the new product"
        conn.close()

        # Rule 2: The notifier must be called exactly ONCE for the summary message
        assert mock_send.call_count == 1
        summary_msg = mock_send.call_args[0][0]
        assert "New Products Added Summary" in summary_msg
        assert "Newly Added Moisturizer" in summary_msg
        assert "1 new product (1 variant)" in summary_msg
        assert "Monitoring starts from the next run" in summary_msg


# ==============================================================================
# Test 3: Second Run with No Changes Sends Nothing
# ==============================================================================

def test_second_run_with_no_changes_sends_nothing(tmp_path: Path) -> None:
    """When a subsequent run encounters no new products and no price changes, no message is sent."""
    db_path = str(tmp_path / "test.db")
    config_file = tmp_path / "sites.yaml"
    config_file.write_text(
        """
sites:
  - name: "Test Store"
    adapter: "shopify"
    base_url: "https://example.com"
    currency: "USD"
        """,
        encoding="utf-8",
    )

    obs1 = _create_sample_obs("var_1", "Original Serum", price_cents=2000)
    mock_result = FetchResult(observations=[obs1])

    # Run 1: Establish catalog & baseline
    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=mock_result), \
         patch("monitor.runner.send_message") as mock_send:
        stats_1 = run_once(config_path=str(config_file), db_path=db_path)
        assert stats_1["is_baseline"] is True
        mock_send.assert_not_called()

    # Run 2: Exact same product and price (no changes)
    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=mock_result), \
         patch("monitor.runner.send_message") as mock_send:
        stats_2 = run_once(config_path=str(config_file), db_path=db_path)
        assert stats_2["is_baseline"] is False
        assert stats_2["new_variants"] == 0
        assert stats_2["events_created"] == 0
        # Absolutely nothing should be sent to Telegram
        mock_send.assert_not_called()
        assert "Skipped" in stats_2["telegram_status"]


# ==============================================================================
# Test 4: Removed Target URL Deactivation & No Out of Stock Events
# ==============================================================================

def test_removed_url_deactivates_and_no_out_of_stock_event(tmp_path: Path) -> None:
    """Variants removed from targets.csv are set to active=0 and never trigger out_of_stock."""
    db_path = str(tmp_path / "test.db")
    storage.init_db(db_path)
    conn = storage.get_connection(db_path)

    # Insert two active variants
    obs_a = _create_sample_obs("var_a", "Keep Me Cream", url="https://store.com/keep-me")
    obs_b = _create_sample_obs("var_b", "Remove Me Cream", url="https://store.com/remove-me")
    storage.upsert_variant(conn, obs_a)
    storage.upsert_variant(conn, obs_b)
    storage.insert_price_check(conn, obs_a)
    storage.insert_price_check(conn, obs_b)

    # Now simulate removing var_b's URL from targets.csv so only var_a remains
    active_urls = ["https://store.com/keep-me"]
    deactivated = storage.deactivate_removed_variants(conn, "Test Store", active_urls)
    assert deactivated == 1, "Should have marked 1 variant as inactive"

    cur = conn.cursor()
    # Check active flags
    cur.execute("SELECT active FROM variants WHERE variant_id = 'var_a';")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT active FROM variants WHERE variant_id = 'var_b';")
    assert cur.fetchone()[0] == 0, "Removed variant must have active = 0"

    # Ensure price_checks were NOT deleted (Rule 3)
    cur.execute("SELECT COUNT(*) FROM price_checks WHERE variant_id = 'var_b';")
    assert cur.fetchone()[0] == 1, "Price checks must never be deleted"

    # Ensure active_only variant retrieval excludes removed variant
    active_ids = storage.get_variant_ids_for_site(conn, "Test Store", active_only=True)
    assert "var_a" in active_ids
    assert "var_b" not in active_ids

    # Ensure no events were created for var_b
    cur.execute("SELECT COUNT(*) FROM events WHERE variant_id = 'var_b';")
    assert cur.fetchone()[0] == 0, "Removed products must not create out_of_stock events"

    conn.close()


def test_removed_url_creates_no_events_and_is_no_longer_fetched(tmp_path: Path) -> None:
    """Full lifecycle: removing a target URL from targets.csv deactivates it and stops fetching."""
    db_path = str(tmp_path / "test.db")
    csv_file = tmp_path / "targets.csv"
    # Initially two products in targets.csv
    csv_file.write_text(
        "site,url,product_group,product_handle,variant_id,target_price_cents,notes\n"
        "K-Beauty Store,https://example.com/products/keep,serums,,,,keep this\n"
        "K-Beauty Store,https://example.com/products/remove,creams,,,,remove this\n",
        encoding="utf-8",
    )

    config_file = tmp_path / "sites.yaml"
    config_file.write_text(
        f"""
sites:
  - name: "K-Beauty Store"
    adapter: "jsonld"
    base_url: "https://example.com"
    currency: "USD"
    targets_path: "{str(csv_file).replace(chr(92), '/')}"
        """,
        encoding="utf-8",
    )

    obs_keep = _create_sample_obs(
        "var_keep", "Keep Cream", site="K-Beauty Store", url="https://example.com/products/keep"
    )
    obs_remove = _create_sample_obs(
        "var_remove", "Remove Cream", site="K-Beauty Store", url="https://example.com/products/remove"
    )

    # Run 1: Baseline with both products
    with patch("monitor.adapters.jsonld.JsonLdAdapter.fetch") as mock_fetch, \
         patch("monitor.runner.send_message") as mock_send:
        mock_fetch.return_value = FetchResult(observations=[obs_keep, obs_remove])
        run_once(config_path=str(config_file), db_path=db_path)
        mock_send.assert_not_called()

    # Verify both exist as active in DB
    conn = storage.get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT variant_id, active FROM variants;")
    rows = dict(cur.fetchall())
    assert rows.get("var_keep") == 1
    assert rows.get("var_remove") == 1
    conn.close()

    # Now remove var_remove's URL from targets.csv
    csv_file.write_text(
        "site,url,product_group,product_handle,variant_id,target_price_cents,notes\n"
        "K-Beauty Store,https://example.com/products/keep,serums,,,,keep this\n",
        encoding="utf-8",
    )

    # In Run 2, JsonLdAdapter loads target URLs from targets.csv so it only fetches the keep URL
    with patch("monitor.adapters.jsonld.JsonLdAdapter.fetch") as mock_fetch, \
         patch("monitor.runner.send_message") as mock_send:
        mock_fetch.return_value = FetchResult(observations=[obs_keep])
        stats = run_once(config_path=str(config_file), db_path=db_path)

        # Removed product must NOT create out_of_stock events and must NOT appear in alerts
        mock_send.assert_not_called()
        assert stats["events_created"] == 0

    conn = storage.get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT active FROM variants WHERE variant_id = 'var_remove';")
    assert cur.fetchone()[0] == 0, "Removed variant must be marked active = 0"

    # Ensure no events were created for var_remove
    cur.execute("SELECT COUNT(*) FROM events WHERE variant_id = 'var_remove';")
    assert cur.fetchone()[0] == 0, "Removed product must never create events"

    # Ensure historical price checks are kept (never deleted)
    cur.execute("SELECT COUNT(*) FROM price_checks WHERE variant_id = 'var_remove';")
    assert cur.fetchone()[0] == 1, "Price check history must be preserved"
    conn.close()


# ==============================================================================
# Test 5: Re-added URL Reactivates Without New Variant Alert
# ==============================================================================

def test_readded_url_reactivates_without_alert(tmp_path: Path) -> None:
    """When a removed URL is added back later, set active = 1 again without a new_variant alert."""
    db_path = str(tmp_path / "test.db")
    csv_file = tmp_path / "targets.csv"
    csv_file.write_text(
        "site,url,product_group,product_handle,variant_id,target_price_cents,notes\n"
        "K-Beauty Store,https://example.com/products/keep,serums,,,,keep\n",
        encoding="utf-8",
    )

    config_file = tmp_path / "sites.yaml"
    config_file.write_text(
        f"""
sites:
  - name: "K-Beauty Store"
    adapter: "jsonld"
    base_url: "https://example.com"
    currency: "USD"
    targets_path: "{str(csv_file).replace(chr(92), '/')}"
        """,
        encoding="utf-8",
    )

    storage.init_db(db_path)
    conn = storage.get_connection(db_path)
    obs_readd = _create_sample_obs(
        "var_readd", "Re-added Toner", price_cents=2500, site="K-Beauty Store", url="https://example.com/products/readd"
    )
    obs_keep = _create_sample_obs(
        "var_keep", "Keep Serum", price_cents=3000, site="K-Beauty Store", url="https://example.com/products/keep"
    )
    storage.upsert_variant(conn, obs_keep)
    storage.upsert_variant(conn, obs_readd)
    storage.insert_price_check(conn, obs_keep)
    storage.insert_price_check(conn, obs_readd)
    # Mark var_readd as inactive (active = 0)
    conn.execute("UPDATE variants SET active = 0 WHERE variant_id = 'var_readd';")
    conn.commit()
    conn.close()

    # Now add var_readd back to targets.csv
    csv_file.write_text(
        "site,url,product_group,product_handle,variant_id,target_price_cents,notes\n"
        "K-Beauty Store,https://example.com/products/keep,serums,,,,keep\n"
        "K-Beauty Store,https://example.com/products/readd,toners,,,,readded\n",
        encoding="utf-8",
    )

    # Run monitor with both products
    with patch("monitor.adapters.jsonld.JsonLdAdapter.fetch") as mock_fetch, \
         patch("monitor.runner.send_message") as mock_send:
        mock_fetch.return_value = FetchResult(observations=[obs_keep, obs_readd])
        stats = run_once(config_path=str(config_file), db_path=db_path)

        # Rule 3: Re-added URL reactivates without a new_variant alert
        mock_send.assert_not_called()
        assert stats["new_variants"] == 0

    # Verify that in SQLite, active is restored to 1
    conn = storage.get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT active FROM variants WHERE variant_id = 'var_readd';")
    assert cur.fetchone()[0] == 1, "Re-added variant must be reactivated to active = 1"

    # Verify no new_variant event was created
    cur.execute("SELECT COUNT(*) FROM events WHERE variant_id = 'var_readd';")
    assert cur.fetchone()[0] == 0, "No new_variant event must be generated for re-added product"
    conn.close()


# ==============================================================================
# Test 6: Duplicate URL Warning and Single Processing
# ==============================================================================

def test_duplicate_url_warning_and_deduplication(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Duplicate URL in targets.csv logs a warning and is only loaded once."""
    csv_file = tmp_path / "targets.csv"
    csv_file.write_text(
        "site,url,product_group,product_handle,variant_id,target_price_cents,notes\n"
        "K-Beauty Store,https://example.com/products/serum,serums,,,,first entry\n"
        "K-Beauty Store,https://example.com/products/serum,serums,,,,duplicate entry\n"
        "K-Beauty Store,https://example.com/products/toner,toners,,,,distinct entry\n",
        encoding="utf-8",
    )

    from monitor.adapters.jsonld import JsonLdAdapter

    site_cfg = {
        "name": "K-Beauty Store",
        "adapter": "jsonld",
        "base_url": "https://example.com",
        "currency": "USD",
        "targets_path": str(csv_file),
    }

    adapter = JsonLdAdapter(site_cfg)

    with caplog.at_level(logging.WARNING):
        targets = adapter.load_target_urls()

    # Should have deduplicated the URL: exactly 2 targets returned
    assert len(targets) == 2
    urls = [t["url"] for t in targets]
    assert urls == [
        "https://example.com/products/serum",
        "https://example.com/products/toner",
    ]

    # Verify that a warning was logged (Rule 5)
    assert any("Duplicate URL found" in record.message for record in caplog.records)


# ==============================================================================
# Test 7: Failed First Fetch Creates No Variant
# ==============================================================================

def test_failed_first_fetch_creates_no_variant(tmp_path: Path) -> None:
    """If a URL fails validation or returns an error on first fetch, do not create any variant."""
    db_path = str(tmp_path / "test.db")
    config_file = tmp_path / "sites.yaml"
    config_file.write_text(
        """
sites:
  - name: "Test Store"
    adapter: "shopify"
    base_url: "https://example.com"
    currency: "USD"
        """,
        encoding="utf-8",
    )

    # Invalid observation: price is 0 and title is empty
    invalid_obs = _create_sample_obs(
        variant_id="bad_var",
        product_title="",
        price_cents=0,
    )
    result_with_invalid = FetchResult(
        observations=[invalid_obs],
        errors=["Network failure on first fetch of target URL"],
    )

    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=result_with_invalid), \
         patch("monitor.runner.send_message") as mock_team_send, \
         patch("monitor.runner.send_error_message") as mock_err_send:
        mock_err_send.return_value = True

        stats = run_once(config_path=str(config_file), db_path=db_path)

        # Rule 6: No variant created
        assert stats["new_variants"] == 0

        # Errors recorded in stats
        assert len(stats["errors"]) >= 1

        # Crucial: Team alert must NOT be sent for the error/invalid product
        mock_team_send.assert_not_called()

        # Check SQLite: absolutely no rows should exist in variants or price_checks
        conn = storage.get_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM variants WHERE variant_id = 'bad_var';")
        assert cur.fetchone()[0] == 0, "Failed observation must NOT create a variant"

        cur.execute("SELECT COUNT(*) FROM price_checks WHERE variant_id = 'bad_var';")
        assert cur.fetchone()[0] == 0, "Failed observation must NOT save a price check"

        cur.execute("SELECT COUNT(*) FROM events WHERE variant_id = 'bad_var';")
        assert cur.fetchone()[0] == 0, "Failed observation must NOT create any event"
        conn.close()


# ==============================================================================
# Test 8: Summary Message Cap at 10 Titles
# ==============================================================================

def test_build_new_variants_summary_cap_at_10() -> None:
    """Verify that build_new_variants_summary caps list at 10 titles and appends 'and N more'."""
    # Create 14 different products for the same store
    items: List[Dict[str, Any]] = []
    for i in range(1, 15):
        items.append({
            "site": "Beauty Store",
            "product_title": f"Product #{i:02d}",
            "variant_id": f"var_{i}",
        })

    summary = build_new_variants_summary(items)
    assert summary is not None

    # Should mention 14 new products (14 variants)
    assert "14 new products (14 variants)" in summary

    # Products 1 to 10 should be present
    for i in range(1, 11):
        assert f"Product #{i:02d}" in summary

    # Products 11 to 14 should NOT be in the individual bullet points
    assert "Product #11" not in summary
    assert "Product #14" not in summary

    # Should say 'and 4 more'
    assert "and 4 more" in summary


# ==============================================================================
# Test 9: CLI Single URL Check without Modifying Database
# ==============================================================================

def test_check_single_url_offline(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """check_single_url prints title, variants, prices, availability, errors without writing to DB."""
    config_file = tmp_path / "sites.yaml"
    config_file.write_text(
        """
sites:
  - name: "Offline Store"
    adapter: "shopify"
    base_url: "https://example.com"
    currency: "USD"
        """,
        encoding="utf-8",
    )

    sample_obs = _create_sample_obs(
        variant_id="inspect_999",
        product_title="Offline Hydrating Toner",
        price_cents=1850,
        available=True,
    )
    fake_result = FetchResult(
        observations=[sample_obs],
        errors=["Simulated minor warning"],
    )

    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=fake_result):
        check_single_url(
            url="https://example.com/products/toner",
            site_name="Offline Store",
            config_path=str(config_file),
        )

    captured = capsys.readouterr()
    output = captured.out

    # Check that output contains all required fields:
    # Title, variants, prices, availability, and errors
    assert "SINGLE URL INSPECTION (NO DATABASE CHANGES)" in output
    assert "Offline Hydrating Toner" in output
    assert "inspect_999" in output
    assert "$18.50" in output
    assert "In Stock" in output
    assert "Simulated minor warning" in output
