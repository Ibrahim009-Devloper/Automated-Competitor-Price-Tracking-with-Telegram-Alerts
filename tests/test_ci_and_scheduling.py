"""Offline unit tests for GitHub Actions CI features, scheduling, exit codes, and timing safety."""

import io
import logging
import os
from pathlib import Path
import sys
import time
from unittest.mock import MagicMock, patch
import pytest
import yaml

from monitor.ci_check import run_ci_check
from monitor.models import FetchResult, Observation
from monitor.runner import run_once
from monitor import storage
from monitor.utils.logging_setup import SecretMaskingFilter, setup_logging


# =============================================================================
# 1. CI Guard Against Silent SQLite Fallback
# =============================================================================


def test_ci_guard_raises_error_when_database_url_missing(monkeypatch):
    """Verify that storage and runner fail fast in CI when DATABASE_URL is not provided."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is required in CI"):
        storage.get_storage(db_path=None)

    with pytest.raises(RuntimeError, match="DATABASE_URL is required in CI"):
        run_once(db_path=None)


def test_ci_guard_permits_explicit_db_path_in_tests(monkeypatch, tmp_path: Path):
    """Verify that offline unit tests passing an explicit SQLite db_path continue to work in CI."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    test_db = tmp_path / "ci_test.db"

    store = storage.get_storage(db_path=str(test_db))
    assert isinstance(store, storage.SqliteStorage)


# =============================================================================
# 2. Secret Masking in Logs
# =============================================================================


def test_secret_masking_filter_redacts_credentials_and_tokens():
    """Verify that SecretMaskingFilter masks database passwords and Telegram bot tokens."""
    # 1. Database URL password masking
    raw_db_log = "Connected to postgresql://postgres.myuser:SuperSecretPassword123@aws-0.pooler.supabase.com:6543/postgres"
    masked_db_log = SecretMaskingFilter.mask_text(raw_db_log)
    assert "SuperSecretPassword123" not in masked_db_log
    assert "postgresql://postgres.myuser:*****@aws-0.pooler.supabase.com:6543/postgres" in masked_db_log

    # 2. Telegram Bot Token masking
    raw_tg_log = "Dispatching alert using token 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_1234567 to chat"
    masked_tg_log = SecretMaskingFilter.mask_text(raw_tg_log)
    assert "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_1234567" not in masked_tg_log
    assert "*****:*****" in masked_tg_log

    # 3. Explicit password parameter masking
    raw_param_log = "Connecting with params: host=localhost&password=MyVerySecretPass&user=admin"
    masked_param_log = SecretMaskingFilter.mask_text(raw_param_log)
    assert "MyVerySecretPass" not in masked_param_log
    assert "password=*****" in masked_param_log


def test_secret_masking_applied_to_log_record(monkeypatch):
    """Verify that log records filtered by SecretMaskingFilter sanitize message strings."""
    secret_token = "987654321:abcdefghijklmnopqrstuvwxyz012345678"
    secret_db = "postgresql://user:mypassword@localhost:5432/db"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", secret_token)
    monkeypatch.setenv("DATABASE_URL", secret_db)

    mask_filter = SecretMaskingFilter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Error connecting to %s with token %s",
        args=(secret_db, secret_token),
        exc_info=None,
    )

    mask_filter.filter(record)
    formatted = record.msg % record.args
    assert "mypassword" not in formatted
    assert "987654321" not in formatted
    assert "*****" in formatted


# =============================================================================
# 3. Timing Safety (max_run_minutes and skipped_timeout)
# =============================================================================


@patch("monitor.runner.send_error_message")
@patch("monitor.runner.create_adapter")
def test_max_run_minutes_stops_gracefully_and_marks_skipped_timeout(
    mock_create_adapter, mock_send_error, tmp_path: Path
):
    """Verify that when run exceeds max_run_minutes, runner stops, saves data, and marks remaining sites as skipped_timeout."""
    db_file = tmp_path / "timeout_test.db"

    # Multi-site configuration
    sites_yaml_content = """
reliability:
  max_run_minutes: 0.1  # 6 seconds

sites:
  - name: "Site Alpha"
    adapter: "shopify"
    base_url: "https://alpha.com"
  - name: "Site Beta"
    adapter: "shopify"
    base_url: "https://beta.com"
  - name: "Site Gamma"
    adapter: "shopify"
    base_url: "https://gamma.com"
"""
    cfg_path = tmp_path / "sites_timeout.yaml"
    cfg_path.write_text(sites_yaml_content, encoding="utf-8")

    from datetime import datetime, timezone

    # Mock adapter fetch for first site
    obs1 = Observation(
        site="Site Alpha",
        product_id="101",
        variant_id="201",
        product_title="Serum",
        variant_title="30ml",
        price_cents=2500,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://alpha.com/products/serum",
        fetched_at=datetime.now(timezone.utc),
    )
    mock_adapter = MagicMock()
    mock_adapter.fetch.return_value = FetchResult(observations=[obs1], errors=[])
    mock_create_adapter.return_value = mock_adapter

    # Mock clock: time.monotonic starts at 0, then after first site jumps to 100 seconds (past 6s limit)
    clock_values = [0.0, 1.0, 100.0, 105.0, 110.0, 115.0]
    with patch("time.monotonic", side_effect=clock_values):
        stats = run_once(
            config_path=str(cfg_path),
            db_path=str(db_file),
        )

    # Site Alpha completed
    assert stats["checks_saved"] == 1
    # Admin timeout alert dispatched once
    assert mock_send_error.call_count >= 1
    alert_args = mock_send_error.call_args_list[0][0][0]
    assert "Timeout Alert" in alert_args or "skipped_timeout" in alert_args

    # Check site_runs entries in database
    store = storage.get_storage(db_path=str(db_file))
    cur = store.get_connection().cursor()
    cur.execute("SELECT site, status FROM site_runs ORDER BY id ASC;")
    rows = cur.fetchall()
    site_statuses = {row[0]: row[1] for row in rows}

    assert site_statuses.get("Site Alpha") == "ok"
    assert site_statuses.get("Site Beta") == "skipped_timeout"
    assert site_statuses.get("Site Gamma") == "skipped_timeout"


# =============================================================================
# 4. Exit Code Behavior
# =============================================================================


@patch("monitor.main.run_once")
def test_main_exits_zero_even_when_sites_failed(mock_run_once):
    """Verify that python -m monitor.main exits 0 on normal completion even when some or all sites failed."""
    from monitor.main import main

    # Simulate all sites failed but normal completion
    mock_run_once.return_value = {
        "sites_total": 2,
        "sites_ok": 0,
        "sites_failed": 2,
        "errors": ["Site 1 timeout", "Site 2 500 error"],
    }

    with patch.object(sys, "argv", ["monitor.main"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0


@patch("monitor.main.run_once")
def test_main_exits_zero_on_advisory_lock(mock_run_once):
    """Verify that python -m monitor.main exits 0 when another run holds the advisory lock."""
    from monitor.main import main

    mock_run_once.return_value = {"status": "locked", "message": "another run in progress"}

    with patch.object(sys, "argv", ["monitor.main"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0


@patch("monitor.notifier.send_error_message")
@patch("monitor.main.run_once")
def test_main_exits_nonzero_only_on_crash(mock_run_once, mock_send_error):
    """Verify that python -m monitor.main exits non-zero (1) and dispatches crash alert on unhandled crash."""
    from monitor.main import main

    mock_run_once.side_effect = RuntimeError("Fatal hardware or network failure")

    with patch.object(sys, "argv", ["monitor.main"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
        assert mock_send_error.call_count == 1


# =============================================================================
# 5. Pre-flight CI Check (--ci-check)
# =============================================================================


def test_ci_check_success_when_all_components_healthy(monkeypatch, tmp_path: Path):
    """Verify that run_ci_check returns True when environment, DB, and Playwright succeed."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_1234567")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "987654321")

    # Mock DB storage check_health and Playwright
    with patch("monitor.storage.get_storage") as mock_get_storage:
        mock_store = MagicMock()
        mock_store.check_health.return_value = {"backend": "PostgreSQL", "latency_ms": 15.2}
        mock_get_storage.return_value = mock_store

        with patch("playwright.sync_api.sync_playwright") as mock_pw:
            mock_browser = MagicMock()
            mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser

            ok = run_ci_check()
            assert ok is True
            assert mock_browser.close.call_count == 1


def test_ci_check_fails_on_missing_env_vars(monkeypatch):
    """Verify that run_ci_check fails immediately if any required environment variable is missing."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "456")

    ok = run_ci_check()
    assert ok is False


def test_ci_check_fails_on_database_unreachable(monkeypatch):
    """Verify that run_ci_check returns False if database connection fails."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "456")

    with patch("monitor.storage.get_storage", side_effect=ConnectionError("Cannot reach Supabase host")):
        ok = run_ci_check()
        assert ok is False


def test_ci_check_fails_on_playwright_launch_error(monkeypatch):
    """Verify that run_ci_check returns False if Playwright Chromium cannot launch."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "456")

    with patch("monitor.storage.get_storage") as mock_get_storage:
        mock_store = MagicMock()
        mock_store.check_health.return_value = {"backend": "PostgreSQL", "latency_ms": 10.0}
        mock_get_storage.return_value = mock_store

        with patch("playwright.sync_api.sync_playwright", side_effect=RuntimeError("Browser executable not found")):
            ok = run_ci_check()
            assert ok is False


# =============================================================================
# 6. GitHub Actions Workflow YAML Verification
# =============================================================================


def test_workflow_yaml_structure_and_constraints():
    """Parse .github/workflows/monitor.yml and assert trigger, permissions, concurrency, and timeout constraints."""
    workflow_path = Path(".github/workflows/monitor.yml")
    assert workflow_path.exists(), ".github/workflows/monitor.yml must exist"

    content = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    # 1. Triggers
    triggers = parsed.get("on") or parsed.get(True)  # PyYAML might parse 'on' as True boolean
    assert triggers is not None, "Workflow triggers must be defined"
    schedule_list = triggers.get("schedule", [])
    assert len(schedule_list) >= 1
    cron_expr = schedule_list[0].get("cron")
    assert cron_expr == "17 2,8,14,20 * * *", f"Expected cron '17 2,8,14,20 * * *', got '{cron_expr}'"
    assert "workflow_dispatch" in triggers, "workflow_dispatch trigger must be defined"

    # 2. Permissions
    permissions = parsed.get("permissions", {})
    assert permissions == {"contents": "read"}, f"Expected contents: read, got {permissions}"

    # 3. Concurrency
    concurrency = parsed.get("concurrency", {})
    assert concurrency.get("group") == "price-monitor"
    assert concurrency.get("cancel-in-progress") is False

    # 4. Job configuration
    jobs = parsed.get("jobs", {})
    assert "monitor" in jobs
    monitor_job = jobs["monitor"]
    assert monitor_job.get("runs-on") == "ubuntu-latest"
    assert monitor_job.get("timeout-minutes") == 25

    # 5. Required steps validation
    steps = monitor_job.get("steps", [])
    step_runs = [s.get("run", "") for s in steps]
    step_uses = [s.get("uses", "") for s in steps]

    assert any("actions/checkout" in u for u in step_uses)
    assert any("actions/setup-python" in u for u in step_uses)
    assert any("DATABASE_URL is required in CI" in r for r in step_runs)
    assert any("requirements.txt" in r for r in step_runs)
    assert any("playwright install" in r for r in step_runs)
    assert any("monitor.main --ci-check" in r for r in step_runs)
    assert any("monitor.main" in r for r in step_runs)
    assert any("actions/upload-artifact" in u for u in step_uses)
