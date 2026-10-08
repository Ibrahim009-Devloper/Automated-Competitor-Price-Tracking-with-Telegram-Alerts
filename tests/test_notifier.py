"""Unit tests for Telegram notifier, message builder, HTML escaping, and retry/notification state."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from monitor.notifier import (
    build_message,
    escape_html,
    format_price_change,
    send_message,
    MAX_TELEGRAM_MESSAGE_LENGTH,
)
from monitor.models import FetchResult, Observation
from monitor.runner import run_once
from monitor import storage


def test_escape_html():
    """Test HTML escaping of special characters."""
    assert escape_html("Tom & Jerry") == "Tom &amp; Jerry"
    assert escape_html("Serum <50ml>") == "Serum &lt;50ml&gt;"
    assert escape_html('Brand "Glow"') == 'Brand "Glow"'
    assert escape_html(None) == ""


def test_format_price_change():
    """Test price change dollar and percentage formatting."""
    # Price drop ($34.00 -> $29.00 is a drop of 500 cents from 3400 = -14.7%)
    drop_str = format_price_change(3400, 2900)
    assert "$34.00" in drop_str
    assert "$29.00" in drop_str
    assert "(-14.7%)" in drop_str

    # Price increase ($20.00 -> $25.00 is an increase of 500 cents from 2000 = +25.0%)
    inc_str = format_price_change(2000, 2500)
    assert "$20.00" in inc_str
    assert "$25.00" in inc_str
    assert "(+25.0%)" in inc_str

    # None handling
    assert format_price_change(None, 2500) == "N/A → $25.00"


def test_build_message_grouping():
    """Test that build_message groups events by type with respective emojis."""
    events = [
        {
            "id": 1,
            "event_type": "price_drop",
            "product_title": "Cleanser & Toner",
            "variant_title": "150ml",
            "site": "K-Beauty Store",
            "old_value": 3000,
            "new_value": 2400,
            "url": "https://store.com/cleanser",
        },
        {
            "id": 2,
            "event_type": "price_increase",
            "product_title": "Night Cream",
            "variant_title": "Default Title",
            "site": "K-Beauty Store",
            "old_value": 4000,
            "new_value": 4500,
            "url": "https://store.com/cream",
        },
        {
            "id": 3,
            "event_type": "out_of_stock",
            "product_title": "Sun Gel SPF50",
            "variant_title": "50ml",
            "site": "K-Beauty Store",
            "old_value": 1,
            "new_value": 0,
            "url": "https://store.com/sungel",
        },
        {
            "id": 4,
            "event_type": "back_in_stock",
            "product_title": "Lip Mask",
            "variant_title": "Berry",
            "site": "K-Beauty Store",
            "old_value": 0,
            "new_value": 1,
            "url": "https://store.com/lipmask",
        },
        {
            "id": 5,
            "event_type": "new_variant",
            "product_title": "Peptide Essence",
            "variant_title": "100ml",
            "site": "K-Beauty Store",
            "old_value": None,
            "new_value": 2800,
            "url": "https://store.com/essence",
        },
    ]

    messages = build_message(events)
    assert len(messages) == 1
    msg = messages[0]

    # Verify grouping headers and emojis
    assert "📉 <b>Price Drops</b>" in msg
    assert "📈 <b>Price Increases</b>" in msg
    assert "❌ <b>Out of Stock</b>" in msg
    assert "✅ <b>Back in Stock</b>" in msg
    assert "🆕 <b>New Variants</b>" in msg

    # Verify HTML escaping
    assert "Cleanser &amp; Toner" in msg

    # Verify URL and percent formatting
    assert '<a href="https://store.com/cleanser">View Product</a>' in msg
    assert "(-20.0%)" in msg


def test_build_message_splitting_at_boundaries():
    """Test that build_message splits into multiple messages when exceeding 4000 characters."""
    # Generate 50 price drop events to exceed 4000 characters
    large_events = []
    for i in range(50):
        large_events.append(
            {
                "id": i,
                "event_type": "price_drop",
                "product_title": f"Super Long Skincare Product Title Number {i} With Extra Long Description",
                "variant_title": f"Size {i}00ml Extended Volume Edition",
                "site": "Luxury Skincare Boutique Store Online",
                "old_value": 5000 + i * 100,
                "new_value": 4000 + i * 100,
                "url": f"https://luxury-skincare-boutique.example.com/products/skincare-product-{i}?variant={i}001",
            }
        )

    messages = build_message(large_events)
    assert len(messages) > 1

    for msg in messages:
        assert len(msg) <= MAX_TELEGRAM_MESSAGE_LENGTH
        # Ensure splitting did not cut in the middle of a line or broken HTML tag
        assert msg.startswith("🔔 <b>Price Monitor Alert")


@patch("monitor.notifier.requests.post")
def test_send_message_success(mock_post):
    """Test send_message returns True when Telegram responds with ok=True."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"ok": True, "result": {"message_id": 123}}
    mock_post.return_value = mock_response

    result = send_message("Test Alert", token="dummy_token", chat_id="123456")
    assert result is True
    mock_post.assert_called_once()


@patch("monitor.notifier.requests.post")
def test_send_message_failure_and_retries(mock_post):
    """Test send_message retries on transient errors and returns False when exhausted."""
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_post.return_value = mock_response

    with patch("time.sleep"):  # Avoid sleeping during tests
        result = send_message("Test Alert", token="dummy_token", chat_id="123456", max_retries=3)

    assert result is False
    assert mock_post.call_count == 3


@patch("monitor.runner.create_adapter")
@patch("monitor.runner.send_message")
def test_runner_marks_notified_only_on_success(mock_send, mock_create_adapter, tmp_path: Path):
    """Test that runner marks events notified = 1 ONLY when Telegram succeeds, and 0 on failure."""
    db_file = tmp_path / "notify_test.db"

    # Step 1: Run baseline (no events)
    obs_base = Observation(
        site="Soko Glam Skincare",
        product_id="1",
        variant_id="101",
        product_title="Hydrating Toner",
        variant_title="200ml",
        price_cents=3000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://sokoglam.com/toner",
        fetched_at=datetime(2026, 10, 7, 10, 0, 0, tzinfo=timezone.utc),
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = FetchResult(observations=[obs_base], errors=[])
    mock_create_adapter.return_value = mock_adapter

    run_once(config_path="config/sites.yaml", site_filter="Soko Glam", db_path=str(db_file))

    # Step 2: Second run with price drop, but Telegram delivery FAILS
    obs_drop = Observation(
        site="Soko Glam Skincare",
        product_id="1",
        variant_id="101",
        product_title="Hydrating Toner",
        variant_title="200ml",
        price_cents=2000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://sokoglam.com/toner",
        fetched_at=datetime(2026, 10, 7, 11, 0, 0, tzinfo=timezone.utc),
    )
    mock_adapter.fetch.return_value = FetchResult(observations=[obs_drop], errors=[])
    mock_send.return_value = False  # Telegram send failed!

    run_once(config_path="config/sites.yaml", site_filter="Soko Glam", db_path=str(db_file))

    # Verify event is still NOTIFIED = 0 (kept for retry)
    conn = storage.get_connection(str(db_file))
    unnotified = storage.get_unnotified_events(conn)
    assert len(unnotified) == 1
    assert unnotified[0]["notified"] == 0

    # Step 3: Third run where Telegram SUCCEEDS
    mock_send.return_value = True

    # Same observation (no new change, but unnotified event from previous run gets sent)
    run_once(config_path="config/sites.yaml", site_filter="Soko Glam", db_path=str(db_file))

    # Verify event is now marked NOTIFIED = 1
    unnotified_after = storage.get_unnotified_events(conn)
    assert len(unnotified_after) == 0

    cur = conn.cursor()
    cur.execute("SELECT notified FROM events WHERE variant_id = 101;")
    assert cur.fetchone()["notified"] == 1
    conn.close()


@patch("monitor.runner.create_adapter")
@patch("monitor.runner.send_message")
def test_dry_run_does_not_send_or_mark_notified(mock_send, mock_create_adapter, tmp_path: Path, capsys):
    """Test --dry-run prints to console and leaves events notified = 0."""
    db_file = tmp_path / "dry_run_test.db"

    # Baseline
    obs_base = Observation(
        site="Soko Glam Skincare",
        product_id="1",
        variant_id="101",
        product_title="Hydrating Toner",
        variant_title="200ml",
        price_cents=3000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://sokoglam.com/toner",
        fetched_at=datetime(2026, 10, 7, 10, 0, 0, tzinfo=timezone.utc),
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = FetchResult(observations=[obs_base], errors=[])
    mock_create_adapter.return_value = mock_adapter

    run_once(config_path="config/sites.yaml", site_filter="Soko Glam", db_path=str(db_file))

    # Second run with price drop using dry_run=True
    obs_drop = Observation(
        site="Soko Glam Skincare",
        product_id="1",
        variant_id="101",
        product_title="Hydrating Toner",
        variant_title="200ml",
        price_cents=2200,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://sokoglam.com/toner",
        fetched_at=datetime(2026, 10, 7, 11, 0, 0, tzinfo=timezone.utc),
    )
    mock_adapter.fetch.return_value = FetchResult(observations=[obs_drop], errors=[])

    run_once(
        config_path="config/sites.yaml",
        site_filter="Soko Glam",
        db_path=str(db_file),
        dry_run=True,
    )

    # send_message must NOT have been called
    mock_send.assert_not_called()

    # Dry run message must be printed to console
    captured = capsys.readouterr().out
    assert "TELEGRAM NOTIFICATION (DRY RUN - NOT SENT)" in captured
    assert "Hydrating Toner" in captured

    # Event remains notified = 0 in database
    conn = storage.get_connection(str(db_file))
    unnotified = storage.get_unnotified_events(conn)
    conn.close()
    assert len(unnotified) == 1
    assert unnotified[0]["notified"] == 0


def test_build_error_message():
    """Test build_error_message formats and splits warning/error strings correctly."""
    from monitor.notifier import build_error_message

    assert build_error_message([]) == []

    errors = ["Connection timed out for site A", "HTTP 404 on page 2 for site B"]
    msgs = build_error_message(errors)
    assert len(msgs) == 1
    assert "Price Monitor Warning / Error Alert" in msgs[0]
    assert "Connection timed out" in msgs[0]
    assert "HTTP 404" in msgs[0]


def test_send_error_message_routes_to_error_bot(monkeypatch):
    """Test send_error_message uses TELEGRAM_ERROR_BOT_TOKEN and TELEGRAM_ERROR_CHAT_ID."""
    from monitor.notifier import send_error_message

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "price_token_123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "price_chat_123")
    monkeypatch.setenv("TELEGRAM_ERROR_BOT_TOKEN", "error_token_456")
    monkeypatch.setenv("TELEGRAM_ERROR_CHAT_ID", "error_chat_456")

    with patch("monitor.notifier.send_message") as mock_send:
        mock_send.return_value = True
        result = send_error_message("Sample error text")
        assert result is True
        mock_send.assert_called_once_with(
            text="Sample error text",
            token="error_token_456",
            chat_id="error_chat_456",
            timeout=20,
            max_retries=3,
        )


