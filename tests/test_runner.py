"""Unit tests for runner orchestrator."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from monitor.models import FetchResult, Observation
from monitor.runner import create_adapter, load_config, run_once
from monitor import storage


def test_load_config():
    """Test loading configuration from sites.yaml."""
    config_path = Path("config/sites.yaml")
    config = load_config(str(config_path))
    assert "sites" in config
    assert isinstance(config["sites"], list)
    assert len(config["sites"]) >= 1
    assert "alerts" in config


def test_create_adapter():
    """Test adapter factory instantiation and error on unknown adapter."""
    shopify_cfg = {"name": "Test", "adapter": "shopify", "base_url": "https://test.com"}
    adapter = create_adapter(shopify_cfg)
    assert adapter.site_name == "Test"

    invalid_cfg = {"name": "Test", "adapter": "unknown_platform"}
    with pytest.raises(ValueError, match="Unsupported adapter"):
        create_adapter(invalid_cfg)


@patch("monitor.runner.create_adapter")
def test_run_once_baseline_creates_no_events(mock_create_adapter, tmp_path: Path, capsys):
    """Test that first baseline run does not create any events and prints baseline notice."""
    db_file = tmp_path / "baseline_prices.db"

    obs1 = Observation(
        site="Soko Glam Skincare",
        product_id="11",
        variant_id="22",
        product_title="Soothing Cream",
        variant_title="50ml",
        price_cents=1500,
        compare_at_cents=2000,
        currency="USD",
        available=True,
        url="https://mock.com/products/cream?variant=22",
        fetched_at=datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc),
    )

    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = FetchResult(observations=[obs1], errors=[])
    mock_create_adapter.return_value = mock_adapter

    stats = run_once(
        config_path="config/sites.yaml",
        site_filter="Soko Glam",
        db_path=str(db_file),
    )

    captured = capsys.readouterr().out
    assert "Baseline run: no events created" in captured
    assert stats["is_baseline"] is True
    assert stats["events_created"] == 0
    assert len(stats["events"]) == 0
    assert stats["checks_saved"] == 1


@patch("monitor.runner.send_message")
@patch("monitor.runner.create_adapter")
def test_run_once_second_run_detects_price_drop(mock_create_adapter, mock_send, tmp_path: Path):
    """Test that a second run compares with previous check and creates price_drop event."""
    mock_send.return_value = False  # simulate pending notification
    db_file = tmp_path / "events_prices.db"

    # Run 1: Baseline
    obs_base = Observation(
        site="Soko Glam Skincare",
        product_id="11",
        variant_id="22",
        product_title="Soothing Cream",
        variant_title="50ml",
        price_cents=3000,
        compare_at_cents=3500,
        currency="USD",
        available=True,
        url="https://mock.com/products/cream?variant=22",
        fetched_at=datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = FetchResult(observations=[obs_base], errors=[])
    mock_create_adapter.return_value = mock_adapter

    stats1 = run_once(
        config_path="config/sites.yaml",
        site_filter="Soko Glam",
        db_path=str(db_file),
    )
    assert stats1["is_baseline"] is True

    # Run 2: Price dropped to $24.00 (600 cents drop >= 50 cents threshold in sites.yaml)
    obs_drop = Observation(
        site="Soko Glam Skincare",
        product_id="11",
        variant_id="22",
        product_title="Soothing Cream",
        variant_title="50ml",
        price_cents=2400,
        compare_at_cents=3500,
        currency="USD",
        available=True,
        url="https://mock.com/products/cream?variant=22",
        fetched_at=datetime(2026, 10, 7, 13, 0, 0, tzinfo=timezone.utc),
    )
    mock_adapter.fetch.return_value = FetchResult(observations=[obs_drop], errors=[])

    stats2 = run_once(
        config_path="config/sites.yaml",
        site_filter="Soko Glam",
        db_path=str(db_file),
    )

    assert stats2["is_baseline"] is False
    assert stats2["events_created"] == 1
    assert stats2["events"][0]["event_type"] == "price_drop"
    assert stats2["events"][0]["old_value"] == 3000
    assert stats2["events"][0]["new_value"] == 2400

    # Verify event stored in database
    conn = storage.get_connection(str(db_file))
    events = storage.get_unnotified_events(conn)
    conn.close()
    assert len(events) == 1
    assert events[0]["event_type"] == "price_drop"


@patch("monitor.runner.send_message")
@patch("monitor.runner.create_adapter")
def test_run_once_handles_failing_site(mock_create_adapter, mock_send, tmp_path: Path):
    """Test that a failing site increments sites_failed without crashing run_once."""
    db_file = tmp_path / "test_prices.db"

    mock_adapter = MagicMock()
    mock_adapter.fetch.side_effect = RuntimeError("Network crashed completely")
    mock_create_adapter.return_value = mock_adapter

    stats = run_once(
        config_path="config/sites.yaml",
        site_filter="Soko Glam",
        db_path=str(db_file),
    )

    assert stats["sites_total"] == 1
    assert stats["sites_ok"] == 0
    assert stats["sites_failed"] == 1
    assert len(stats["errors"]) == 1
