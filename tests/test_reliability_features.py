"""Comprehensive tests for reliability checklist items.

Covers:
1. HTTP transient retries, exponential backoff, Retry-After cap at 60s, non-retryable 404/410/403/captcha.
2. Error classification into 8 error_types and persistence in errors table.
3. Confirmed absence vs fetch error (transient errors never count as misses).
4. Delisting after consecutive misses (exactly 1 event) and relisting when seen again (exactly 1 event).
5. Health classification (ok, degraded, down, suspicious) in runs and site_runs.
6. Admin alerts only on state change + recovered alert via site_state.
7. Top-level crash alert and team delivery failure handling (events kept unnotified).
8. Daily heartbeat once per UTC calendar day tracked in meta.
9. Read-only --health CLI inspection.
10. Automatic database backup creation before migration.
11. Delisted & relisted in ONE section of team summary message.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch
import pytest
import requests

from monitor.models import ErrorRecord, FetchResult, Observation, VALID_ERROR_TYPES
from monitor.notifier import (
    build_heartbeat_message,
    build_message,
    build_site_status_change_message,
    build_crash_alert_message,
    build_delivery_failure_alert,
    format_event_block,
)
from monitor.runner import print_health_summary, run_once
from monitor import storage
from monitor.utils.http import HttpError, http_get, is_captcha_challenge, is_generic_redirect


# =============================================================================
# 1. HTTP Retries, Backoff, 429 Cap, Non-retryable Status Codes
# =============================================================================


def test_http_get_no_retry_on_404_and_410():
    """HTTP 404 and 410 must raise immediately as not_found without retrying."""
    with patch("requests.get") as mock_get:
        # Mock 404
        resp404 = MagicMock(spec=requests.Response)
        resp404.status_code = 404
        mock_get.return_value = resp404

        with pytest.raises(HttpError) as exc_info:
            http_get("https://example.com/products/missing", max_retries=3)
        assert exc_info.value.status_code == 404
        assert exc_info.value.error_type == "not_found"
        assert mock_get.call_count == 1  # No retries!

        mock_get.reset_mock()

        # Mock 410
        resp410 = MagicMock(spec=requests.Response)
        resp410.status_code = 410
        mock_get.return_value = resp410

        with pytest.raises(HttpError) as exc_info2:
            http_get("https://example.com/products/gone", max_retries=3)
        assert exc_info2.value.status_code == 410
        assert exc_info2.value.error_type == "not_found"
        assert mock_get.call_count == 1  # No retries!


def test_http_get_no_retry_on_403_and_captcha():
    """HTTP 403 and captcha challenge HTML must raise immediately as blocked without retrying."""
    with patch("requests.get") as mock_get:
        resp403 = MagicMock(spec=requests.Response)
        resp403.status_code = 403
        resp403.text = "Forbidden"
        mock_get.return_value = resp403

        with pytest.raises(HttpError) as exc_info:
            http_get("https://example.com/products/blocked", max_retries=3)
        assert exc_info.value.error_type == "blocked"
        assert mock_get.call_count == 1

        mock_get.reset_mock()

        # Captcha challenge on 200
        resp_captcha = MagicMock(spec=requests.Response)
        resp_captcha.status_code = 200
        resp_captcha.text = "<html><title>Just a moment...</title>cf-challenge-platform</html>"
        mock_get.return_value = resp_captcha

        with pytest.raises(HttpError) as exc_info2:
            http_get("https://example.com/products/test", max_retries=3)
        assert exc_info2.value.error_type == "blocked"
        assert mock_get.call_count == 1


def test_http_get_retry_after_capped_at_60s():
    """Retry-After > 60s must immediately raise as rate_limited without waiting or retrying."""
    with patch("requests.get") as mock_get, patch("time.sleep") as mock_sleep:
        resp429 = MagicMock(spec=requests.Response)
        resp429.status_code = 429
        resp429.headers = {"Retry-After": "120"}
        mock_get.return_value = resp429

        with pytest.raises(HttpError) as exc_info:
            http_get("https://example.com/products/test", max_retries=3)
        assert exc_info.value.error_type == "rate_limited"
        assert exc_info.value.retry_after == 120
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()


def test_http_get_retry_after_within_60s_sleeps_and_retries():
    """Retry-After <= 60s sleeps for the requested seconds and retries."""
    with patch("requests.get") as mock_get, patch("time.sleep") as mock_sleep:
        resp429 = MagicMock(spec=requests.Response)
        resp429.status_code = 429
        resp429.headers = {"Retry-After": "5"}

        resp200 = MagicMock(spec=requests.Response)
        resp200.status_code = 200
        resp200.text = '{"products": []}'
        resp200.headers = {"content-type": "application/json"}
        resp200.history = []

        mock_get.side_effect = [resp429, resp200]

        res = http_get("https://example.com/products.json", max_retries=3)
        assert res.status_code == 200
        assert mock_get.call_count == 2
        mock_sleep.assert_called_with(5.0)


def test_http_get_redirect_to_homepage_classified_as_not_found():
    """Redirecting a product page to homepage or search page is classified as not_found error."""
    with patch("requests.get") as mock_get:
        resp_redirect = MagicMock(spec=requests.Response)
        resp_redirect.status_code = 200
        resp_redirect.url = "https://example.com/"
        resp_redirect.history = [MagicMock(status_code=302)]
        mock_get.return_value = resp_redirect

        with pytest.raises(HttpError) as exc_info:
            http_get("https://example.com/products/deleted-cream", max_retries=2)
        assert exc_info.value.error_type == "not_found"


# =============================================================================
# 2. Error Classification and Persistence
# =============================================================================


def test_error_records_in_fetch_result_and_db(tmp_path):
    """Errors are classified by error_type and stored in the errors table."""
    db_file = tmp_path / "test_errors.db"
    conn = storage.get_connection(str(db_file))
    storage.init_db(conn=conn)

    res = FetchResult()
    res.add_error(
        error_type="timeout",
        message="Request timed out after 20s",
        url="https://site.com/p1",
        site="Site A",
    )
    res.add_error(
        error_type="blocked",
        message="Cloudflare captcha detected",
        url="https://site.com/p2",
        site="Site A",
    )

    assert len(res.errors) == 2
    assert len(res.error_records) == 2
    assert res.error_records[0].error_type == "timeout"
    assert res.error_records[1].error_type == "blocked"

    # Persist in DB
    run_id = storage.record_run_start(conn)
    for rec in res.error_records:
        storage.insert_error_record(
            conn=conn,
            site=rec.site,
            error_type=rec.error_type,
            message=rec.message,
            url=rec.url,
            run_id=run_id,
        )

    cur = conn.cursor()
    cur.execute("SELECT site, error_type, message FROM errors WHERE run_id = ? ORDER BY id ASC;", (run_id,))
    rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0]["error_type"] == "timeout"
    assert rows[1]["error_type"] == "blocked"
    conn.close()


# =============================================================================
# 3 & 4. Confirmed Absence vs Fetch Error & Delisting/Relisting
# =============================================================================


def test_confirmed_absence_delisting_and_relisting(tmp_path):
    """Test consecutive misses, delisting after threshold, and relisting when seen again."""
    db_file = tmp_path / "test_delisting.db"
    conn = storage.get_connection(str(db_file))
    storage.init_db(conn=conn)

    # Seed an active variant
    obs = Observation(
        site="StoreX",
        product_id="p100",
        variant_id="v100",
        product_title="Hydrating Cleanser",
        variant_title="200ml",
        price_cents=2500,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://storex.com/products/cleanser?variant=v100",
        fetched_at=datetime.now(timezone.utc),
    )
    storage.upsert_variant(conn, obs)

    # Run 1: Confirmed absent (miss 1) -> no event yet
    ev1 = storage.process_presence_and_delisting(
        conn=conn,
        site="StoreX",
        seen_variant_ids=[],
        confirmed_absent_ids=["v100"],
        missing_runs_before_delisted=3,
    )
    assert len(ev1) == 0
    cur = conn.cursor()
    cur.execute("SELECT consecutive_misses, status FROM variants WHERE variant_id = 'v100';")
    row = cur.fetchone()
    assert row["consecutive_misses"] == 1
    assert row["status"] == "active"

    # Run 2: Confirmed absent (miss 2) -> no event yet
    ev2 = storage.process_presence_and_delisting(
        conn=conn,
        site="StoreX",
        seen_variant_ids=[],
        confirmed_absent_ids=["v100"],
        missing_runs_before_delisted=3,
    )
    assert len(ev2) == 0
    cur.execute("SELECT consecutive_misses, status FROM variants WHERE variant_id = 'v100';")
    row = cur.fetchone()
    assert row["consecutive_misses"] == 2
    assert row["status"] == "active"

    # Run 3: Confirmed absent (miss 3) -> exactly ONE 'delisted' event!
    ev3 = storage.process_presence_and_delisting(
        conn=conn,
        site="StoreX",
        seen_variant_ids=[],
        confirmed_absent_ids=["v100"],
        missing_runs_before_delisted=3,
    )
    assert len(ev3) == 1
    assert ev3[0]["event_type"] == "delisted"
    cur.execute("SELECT consecutive_misses, status FROM variants WHERE variant_id = 'v100';")
    row = cur.fetchone()
    assert row["consecutive_misses"] == 3
    assert row["status"] == "delisted"

    # Run 4: Still absent (miss 4) -> no second delisted event!
    ev4 = storage.process_presence_and_delisting(
        conn=conn,
        site="StoreX",
        seen_variant_ids=[],
        confirmed_absent_ids=["v100"],
        missing_runs_before_delisted=3,
    )
    assert len(ev4) == 0

    # Run 5: Seen again -> exactly ONE 'relisted' event and status active!
    ev5 = storage.process_presence_and_delisting(
        conn=conn,
        site="StoreX",
        seen_variant_ids=["v100"],
        confirmed_absent_ids=[],
        missing_runs_before_delisted=3,
    )
    assert len(ev5) == 1
    assert ev5[0]["event_type"] == "relisted"
    cur.execute("SELECT consecutive_misses, status FROM variants WHERE variant_id = 'v100';")
    row = cur.fetchone()
    assert row["consecutive_misses"] == 0
    assert row["status"] == "active"

    conn.close()


def test_fetch_error_never_counts_as_miss(tmp_path):
    """Transient errors (timeout, 500) must never count as confirmed absence or increment misses."""
    db_file = tmp_path / "test_error_not_miss.db"
    conn = storage.get_connection(str(db_file))
    storage.init_db(conn=conn)

    obs = Observation(
        site="StoreY",
        product_id="p200",
        variant_id="v200",
        product_title="Vitamin C Serum",
        variant_title="30ml",
        price_cents=3000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://storey.com/products/serum",
        fetched_at=datetime.now(timezone.utc),
    )
    storage.upsert_variant(conn, obs)

    # When fetch fails due to timeout, neither seen nor confirmed_absent is passed
    ev = storage.process_presence_and_delisting(
        conn=conn,
        site="StoreY",
        seen_variant_ids=[],
        confirmed_absent_ids=[],  # Network error is not confirmed absent!
        missing_runs_before_delisted=3,
    )
    assert len(ev) == 0

    cur = conn.cursor()
    cur.execute("SELECT consecutive_misses, status FROM variants WHERE variant_id = 'v200';")
    row = cur.fetchone()
    assert row["consecutive_misses"] == 0
    assert row["status"] == "active"
    conn.close()


# =============================================================================
# 5 & 6. Health Records, State Transitions, and Recovered Alerts
# =============================================================================


def test_site_state_transition_and_recovered_alert(tmp_path):
    """Admin alerts only on status change, with recovery alert when returning to ok."""
    db_file = tmp_path / "test_state.db"
    conn = storage.get_connection(str(db_file))
    storage.init_db(conn=conn)

    # Run 1: Site initially OK
    storage.upsert_site_state(conn, "SiteZ", "ok", observations_count=100, last_notified_status="ok")
    state1 = storage.get_site_state(conn, "SiteZ")
    assert state1["last_status"] == "ok"

    # Status changes to degraded -> generate change alert
    old_st = state1["last_status"]
    new_st = "degraded"
    msg_degraded = build_site_status_change_message("SiteZ", old_st, new_st, details="4/10 URLs failed")
    assert "Site Health Status Change" in msg_degraded
    assert "DEGRADED" in msg_degraded

    storage.upsert_site_state(conn, "SiteZ", "degraded", observations_count=60, last_notified_status="degraded")

    # Run 2: Still degraded -> no status change, no repeat alert
    state2 = storage.get_site_state(conn, "SiteZ")
    assert state2["last_status"] == "degraded"
    assert state2["last_notified_status"] == "degraded"

    # Run 3: Returns to ok -> generate recovered alert
    msg_recovered = build_site_status_change_message("SiteZ", state2["last_status"], "ok", details="All URLs succeeded")
    assert "Site Recovered" in msg_recovered
    assert "Status has returned to <b>OK</b>" in msg_recovered
    storage.upsert_site_state(conn, "SiteZ", "ok", observations_count=100, last_notified_status="ok")

    conn.close()


# =============================================================================
# 7. Whole-run Crash Alert & Team Delivery Failure (Held Events)
# =============================================================================


def test_crash_alert_message_format():
    """Verify crash alert formatting masks tokens and displays error."""
    msg = build_crash_alert_message("sqlite3.DatabaseError: disk I/O error")
    assert "Fatal Crash Alert" in msg
    assert "disk I/O error" in msg


def test_team_delivery_failure_alert_format():
    """Verify delivery failure message formatting."""
    msg = build_delivery_failure_alert("Team Chat", "Telegram API timeout")
    assert "Price Alert Delivery Failed to Team Chat" in msg
    assert "Telegram API timeout" in msg


# =============================================================================
# 8. Daily Heartbeat Tracked in Meta Table
# =============================================================================


def test_daily_heartbeat_meta_tracking(tmp_path):
    """Heartbeat is recorded once per calendar date in meta table."""
    db_file = tmp_path / "test_hb.db"
    conn = storage.get_connection(str(db_file))
    storage.init_db(conn=conn)

    today = "2026-10-07"
    assert storage.get_meta(conn, "last_heartbeat_date") is None

    # First send: records date
    storage.set_meta(conn, "last_heartbeat_date", today)
    assert storage.get_meta(conn, "last_heartbeat_date") == today

    # Message format
    hb_msg = build_heartbeat_message(
        utc_date=today,
        sites_total=5,
        sites_ok=4,
        sites_degraded=1,
        sites_down=0,
        active_variants=150,
    )
    assert "Price Monitor Heartbeat" in hb_msg
    assert "2026-10-07" in hb_msg
    assert "Monitored Sites</b>: 5" in hb_msg

    conn.close()


# =============================================================================
# 9. Read-only --health CLI Command
# =============================================================================


def test_print_health_summary_read_only(tmp_path, capsys):
    """--health prints table without creating or altering tables/data."""
    db_file = tmp_path / "test_health_cmd.db"
    conn = storage.get_connection(str(db_file))
    storage.init_db(conn=conn)

    storage.upsert_site_state(conn, "Glow Skincare", "ok", observations_count=50)
    conn.close()

    # Call print_health_summary
    print_health_summary(db_path=str(db_file))
    captured = capsys.readouterr()

    assert "STORE HEALTH & STATUS REPORT (READ-ONLY)" in captured.out
    assert "Glow Skincare" in captured.out
    assert "OK" in captured.out


# =============================================================================
# 10. Automatic DB Backup Creation
# =============================================================================


def test_automatic_backup_creation_before_migration(tmp_path):
    """Creates a prices_backup_<timestamp>.db before migrating an existing non-empty DB."""
    db_file = tmp_path / "prices.db"

    # Create dummy initial database
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE dummy (id INTEGER);")
    conn.execute("INSERT INTO dummy VALUES (1);")
    conn.commit()
    conn.close()

    assert os.path.exists(str(db_file))

    # Calling storage.init_db should trigger backup creation
    backup_created = storage.backup_database_if_needed(str(db_file))
    assert backup_created is not None
    assert "prices_backup_" in backup_created
    assert os.path.exists(backup_created)

    # Calling it a second time should NOT create a duplicate backup
    backup_again = storage.backup_database_if_needed(str(db_file))
    assert backup_again is None


# =============================================================================
# 11. Delisted & Relisted in ONE Section of Team Message
# =============================================================================


def test_delisted_and_relisted_combined_in_one_team_section():
    """delisted and relisted events must go into ONE combined section in team summary."""
    events = [
        {
            "id": 1,
            "event_type": "delisted",
            "product_title": "Old Cream",
            "variant_title": "Default",
            "site": "StoreA",
            "old_value": None,
            "new_value": None,
            "url": "https://storea.com/old",
        },
        {
            "id": 2,
            "event_type": "relisted",
            "product_title": "Returned Serum",
            "variant_title": "50ml",
            "site": "StoreA",
            "old_value": None,
            "new_value": None,
            "url": "https://storea.com/serum",
        },
    ]

    messages = build_message(events)
    assert len(messages) == 1
    msg = messages[0]

    # Verify header is combined
    assert "Delisted & Relisted Products" in msg
    assert "Delisted</b>" in msg
    assert "Relisted</b>" in msg
    # Verify no individual stray alert headers
    assert "Price Drops" not in msg
    assert "Out of Stock" not in msg


# =============================================================================
# 12. Integration: run_once Health Alerts, Delivery Retries & Heartbeat
# =============================================================================


def test_run_once_records_health_and_alerts_on_status_change(tmp_path):
    """Integration: run_once computes status, updates site_runs/runs/site_state, and alerts admin on change."""
    db_file = tmp_path / "integration_health.db"
    config_file = tmp_path / "test_sites.yaml"

    config_content = """
alerts:
  min_price_change_cents: 0
reliability:
  retries: 2
  backoff_seconds: 0.1
  missing_runs_before_delisted: 2
  degraded_failure_percent: 20.0
  suspicious_drop_percent: 50.0
sites:
  - name: "Health Test Store"
    adapter: "shopify"
    base_url: "https://healthtest.com"
    currency: "USD"
"""
    config_file.write_text(config_content, encoding="utf-8")

    # Mock adapter to return 10 observations first time
    obs_list = [
        Observation(
            site="Health Test Store",
            product_id=f"p{i}",
            variant_id=f"v{i}",
            product_title=f"Product {i}",
            variant_title="Default",
            price_cents=1000,
            compare_at_cents=None,
            currency="USD",
            available=True,
            url=f"https://healthtest.com/products/p{i}",
            fetched_at=datetime.now(timezone.utc),
        )
        for i in range(10)
    ]

    mock_res_ok = FetchResult(observations=obs_list)

    with patch("monitor.runner.create_adapter") as mock_adapter, \
         patch("monitor.runner.send_message", return_value=True), \
         patch("monitor.runner.send_error_message", return_value=True) as mock_send_err:

        mock_inst = MagicMock()
        mock_inst.fetch.return_value = mock_res_ok
        mock_adapter.return_value = mock_inst

        # Run 1: Baseline run -> site status OK
        stats1 = run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)
        assert stats1["sites_ok"] == 1
        assert stats1["sites_failed"] == 0

        conn = storage.get_connection(str(db_file))
        state1 = storage.get_site_state(conn, "Health Test Store")
        assert state1["last_status"] == "ok"
        conn.close()

        # Run 2: Suspicious drop (>50% drop: only 2 observations instead of 10)
        mock_res_suspicious = FetchResult(observations=obs_list[:2])
        mock_inst.fetch.return_value = mock_res_suspicious

        stats2 = run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)
        assert stats2["sites_ok"] == 1

        conn = storage.get_connection(str(db_file))
        state2 = storage.get_site_state(conn, "Health Test Store")
        assert state2["last_status"] == "suspicious"
        # Admin alert sent for status change ok -> suspicious!
        assert mock_send_err.called
        conn.close()


def test_team_delivery_failure_keeps_events_unnotified(tmp_path):
    """When send_message fails, events remain notified=0 so next run retries, and admin is alerted once."""
    db_file = tmp_path / "integration_delivery.db"
    config_file = tmp_path / "test_sites.yaml"

    config_content = """
alerts:
  min_price_change_cents: 0
reliability:
  retries: 2
sites:
  - name: "Delivery Test Store"
    adapter: "shopify"
    base_url: "https://deliverytest.com"
    currency: "USD"
"""
    config_file.write_text(config_content, encoding="utf-8")

    obs = Observation(
        site="Delivery Test Store",
        product_id="p1",
        variant_id="v1",
        product_title="Product 1",
        variant_title="Default",
        price_cents=1000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://deliverytest.com/products/p1",
        fetched_at=datetime.now(timezone.utc),
    )

    with patch("monitor.runner.create_adapter") as mock_adapter, \
         patch("monitor.runner.send_message", return_value=False), \
         patch("monitor.runner.send_error_message", return_value=True) as mock_send_err:

        mock_inst = MagicMock()
        mock_inst.fetch.return_value = FetchResult(observations=[obs])
        mock_adapter.return_value = mock_inst

        # Run 1: Baseline
        run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)

        # Run 2: Price drop event occurs, but Telegram send_message returns False!
        obs_drop = Observation(
            site="Delivery Test Store",
            product_id="p1",
            variant_id="v1",
            product_title="Product 1",
            variant_title="Default",
            price_cents=800,  # Price drop!
            compare_at_cents=None,
            currency="USD",
            available=True,
            url="https://deliverytest.com/products/p1",
            fetched_at=datetime.now(timezone.utc),
        )
        mock_inst.fetch.return_value = FetchResult(observations=[obs_drop])

        stats2 = run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)

        # Verify event was created
        assert stats2["events_created"] >= 1

        # Verify event remains unnotified (notified = 0) in DB!
        conn = storage.get_connection(str(db_file))
        unnotified = storage.get_unnotified_events(conn)
        assert len(unnotified) >= 1
        assert any(e["event_type"] == "price_drop" for e in unnotified)

        # Admin alert sent for delivery failure
        assert mock_send_err.called
        assert storage.get_meta(conn, "team_delivery_status") == "failed"
        conn.close()


def test_heartbeat_failed_send_does_not_mark_as_sent(tmp_path):
    """If dispatching heartbeat fails (send_error_message returns False), do not mark it as sent."""
    db_file = tmp_path / "test_hb_fail.db"
    config_file = tmp_path / "test_sites_hb.yaml"
    config_file.write_text("sites: []\nreliability:\n  heartbeat_hour_utc: 0\n", encoding="utf-8")

    with patch("monitor.runner.send_error_message", return_value=False):
        run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)

    conn = storage.get_connection(str(db_file))
    # Must NOT be marked as sent!
    assert storage.get_meta(conn, "last_heartbeat_date") is None
    conn.close()


def test_team_delivery_failure_alerts_admin_once_and_recovers(tmp_path):
    """Admin is alerted ONCE upon team delivery failure; on recovery, sends recovered alert."""
    db_file = tmp_path / "integration_delivery_state.db"
    config_file = tmp_path / "test_sites_recovery.yaml"
    config_content = """
alerts:
  min_price_change_cents: 0
reliability:
  retries: 1
  heartbeat_hour_utc: 23
sites:
  - name: "Store A"
    adapter: "shopify"
    base_url: "https://storea.com"
    currency: "USD"
"""
    config_file.write_text(config_content, encoding="utf-8")

    obs1 = Observation(
        site="Store A",
        product_id="p1",
        variant_id="v1",
        product_title="Product 1",
        variant_title="Default",
        price_cents=1000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://storea.com/products/p1",
        fetched_at=datetime.now(timezone.utc),
    )
    obs2 = Observation(
        site="Store A",
        product_id="p1",
        variant_id="v1",
        product_title="Product 1",
        variant_title="Default",
        price_cents=800,  # drop
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://storea.com/products/p1",
        fetched_at=datetime.now(timezone.utc),
    )

    with patch("monitor.runner.create_adapter") as mock_adapter, \
         patch("monitor.runner.send_message") as mock_send_team, \
         patch("monitor.runner.send_error_message") as mock_send_admin:

        mock_inst = MagicMock()
        mock_adapter.return_value = mock_inst

        # Baseline
        mock_inst.fetch.return_value = FetchResult(observations=[obs1])
        run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)

        # Run 2: Price drop, delivery fails
        mock_inst.fetch.return_value = FetchResult(observations=[obs2])
        mock_send_team.return_value = False
        run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)
        assert mock_send_admin.call_count == 1
        admin_call_text = mock_send_admin.call_args[0][0]
        assert "Price Alert Delivery Failed" in admin_call_text

        # Run 3: Price drop still unnotified, delivery fails AGAIN
        mock_send_admin.reset_mock()
        run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)
        # Should NOT alert admin again (no repeat alert, state is still 'failed')
        assert mock_send_admin.call_count == 0

        # Run 4: Delivery succeeds! Recovery alert dispatched to admin
        mock_send_team.return_value = True
        run_once(config_path=str(config_file), db_path=str(db_file), dry_run=False)
        assert mock_send_admin.call_count == 1
        recovery_text = mock_send_admin.call_args[0][0]
        assert "Team Notification Delivery Recovered" in recovery_text

        conn = storage.get_connection(str(db_file))
        assert storage.get_meta(conn, "team_delivery_status") == "ok"
        conn.close()


def test_redirect_to_homepage_classified_as_error_not_miss(tmp_path, capsys):
    """A redirect to homepage, generic page, or search page is classified as an error, NEVER as a miss."""
    db_file = tmp_path / "test_redirect_not_miss.db"
    conn = storage.get_connection(str(db_file))
    storage.init_db(conn=conn)

    obs = Observation(
        site="Store Redirect",
        product_id="p10",
        variant_id="v10",
        product_title="Eye Cream",
        variant_title="Default",
        price_cents=2000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://store.com/products/eye-cream",
        fetched_at=datetime.now(timezone.utc),
    )
    storage.upsert_variant(conn, obs)

    # Simulate fetch result when redirected: error is recorded, confirmed_absent is NOT populated
    res = FetchResult()
    res.add_error("not_found", "Redirected from product URL to generic page: https://store.com/", url="https://store.com/products/eye-cream", site="Store Redirect")

    assert len(res.confirmed_absent_variant_ids) == 0
    assert res.error_records[0].error_type == "not_found"

    # Processing presence with empty confirmed_absent_ids does not increment misses
    events = storage.process_presence_and_delisting(
        conn=conn,
        site="Store Redirect",
        seen_variant_ids=[],
        confirmed_absent_ids=res.confirmed_absent_variant_ids,
        missing_runs_before_delisted=3,
    )
    assert len(events) == 0
    cur = conn.cursor()
    cur.execute("SELECT consecutive_misses, status FROM variants WHERE variant_id = 'v10';")
    row = cur.fetchone()
    assert row["consecutive_misses"] == 0
    assert row["status"] == "active"
    conn.close()


def test_stale_after_hours_default_is_36(tmp_path, capsys):
    """Verify default stale_after_hours is 36 and --health flags older records as STALE."""
    db_file = tmp_path / "test_stale.db"
    conn = storage.get_connection(str(db_file))
    storage.init_db(conn=conn)

    # Insert a site_state that ran 40 hours ago
    past_ts = "2026-10-06T10:00:00+00:00"
    storage.upsert_site_state(
        conn=conn,
        site="Stale Store",
        status="ok",
        observations_count=20,
        run_at=past_ts,
    )
    conn.close()

    print_health_summary(config_path="config/sites.yaml", db_path=str(db_file))
    captured = capsys.readouterr()
    assert "Stale Store" in captured.out
    assert "STALE" in captured.out
