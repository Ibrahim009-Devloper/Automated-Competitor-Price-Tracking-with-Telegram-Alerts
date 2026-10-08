"""Unit tests for Playwright adapter bug fixes and the validation pipeline.

Validates:
1. HTTP 404 and error status codes produce NO Observation and record errors.
2. Redirects to generic/home/404 pages produce NO Observation and record errors.
3. Title deduplication safeguard cleans concatenated repeated titles.
4. Parsing real Soko Glam Dermalogy fixture extracts exact title and price ($34.00 -> 3400 cents).
5. Validation gate in monitor/validator.py rejects empty titles, non-positive prices, and suspicious price jumps.
6. Runner ignores invalid observations without creating price_checks, events, or alerts.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from monitor.adapters.playwright import PlaywrightAdapter, clean_and_deduplicate_title
from monitor.models import FetchResult, Observation
from monitor.runner import run_once
from monitor import storage
from monitor.validator import validate


@pytest.fixture
def playwright_config():
    return {
        "name": "Glow Beauty (Playwright)",
        "adapter": "playwright",
        "base_url": "https://sokoglam.com",
        "currency": "USD",
        "price_selector": ".price-item, .price-item--sale, .product-price, .price, [data-price]",
        "compare_price_selector": ".price-item--regular, .compare-price",
        "title_selector": "h1, .product-title, .product__title",
        "availability_selector": "[name='add'], .add-to-cart, button[type='submit']",
        "wait_for": ".price",
    }


# ==============================================================================
# 1. Title Extraction and De-duplication Tests (Bug 3 & Requirement 5)
# ==============================================================================

def test_clean_and_deduplicate_title_cases():
    """Verify title cleaning, space collapsing, and de-duplication safeguards."""
    # Exact duplicate without spaces
    dup1 = "Dermalogy Double Vita Spot Toning Serum (RC)Dermalogy Double Vita Spot Toning Serum (RC)"
    assert clean_and_deduplicate_title(dup1) == "Dermalogy Double Vita Spot Toning Serum (RC)"

    # Duplicate with space
    dup2 = "Dermalogy Double Vita Spot Toning Serum (RC) Dermalogy Double Vita Spot Toning Serum (RC)"
    assert clean_and_deduplicate_title(dup2) == "Dermalogy Double Vita Spot Toning Serum (RC)"

    # Duplicate with separator
    dup3 = "Glow Toner (RC) - Glow Toner (RC)"
    assert clean_and_deduplicate_title(dup3) == "Glow Toner (RC)"

    # Repeated whitespace collapsing
    messy = "   Neogen   Double    Vita    Serum   \n  "
    assert clean_and_deduplicate_title(messy) == "Neogen Double Vita Serum"

    # Normal single title remains unchanged
    normal = "Advanced Snail 96 Mucin Power Essence"
    assert clean_and_deduplicate_title(normal) == normal


def test_real_soko_glam_fixture_title_and_price(playwright_config):
    """Test parsing real Dermalogy product fixture:

    - Title must NOT be duplicated.
    - Price must NOT be N/A; it must be 3400 cents ($34.00).
    """
    adapter = PlaywrightAdapter(playwright_config)
    fixture_path = Path(__file__).parent / "fixtures" / "sample_jsonld_product.html"
    assert fixture_path.exists()
    html_text = fixture_path.read_text(encoding="utf-8")

    errors = []
    observations = adapter.parse_dom(
        html_text=html_text,
        page_url="https://sokoglam.com/products/dermalogy-double-vita-spot-toning-serum-rc",
        errors_out=errors,
    )

    assert len(observations) == 1
    obs = observations[0]

    # Bug 3 verification: title is clean and not duplicated
    assert obs.product_title == "Dermalogy Double Vita Spot Toning Serum (RC)"
    assert "Dermalogy Double Vita Spot Toning Serum (RC)Dermalogy" not in obs.product_title

    # Bug 2 verification: price extracted accurately, never N/A
    assert obs.price_cents == 3400
    assert obs.currency == "USD"
    assert obs.available is True


# ==============================================================================
# 2. HTTP 404 & >= 400 Error Handling Tests (Bug 1 & Requirement 1)
# ==============================================================================

@patch("monitor.adapters.playwright.sync_playwright")
def test_http_404_produces_no_observation(mock_sync_playwright, playwright_config):
    """A product page returning HTTP 404 produces NO Observation and records an error."""
    adapter = PlaywrightAdapter(playwright_config)
    adapter.load_target_urls = MagicMock(return_value=[
        {"url": "https://sokoglam.com/products/non-existent-product", "product_group": ""},
    ])

    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_sync_playwright.return_value.start.return_value = mock_pw
    mock_pw.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    mock_response = MagicMock()
    mock_response.status = 404
    mock_page.goto.return_value = mock_response

    result = adapter.fetch()

    # Must produce NO observations (Requirement 1)
    assert len(result.observations) == 0
    # Must record HTTP 404 error
    assert len(result.errors) == 1
    assert "HTTP 404 for https://sokoglam.com/products/non-existent-product" in result.errors[0]


@patch("monitor.adapters.playwright.sync_playwright")
def test_redirect_to_generic_home_or_404_page(mock_sync_playwright, playwright_config):
    """Detect redirects from a product URL to home / generic 404 and treat as error."""
    adapter = PlaywrightAdapter(playwright_config)
    adapter.load_target_urls = MagicMock(return_value=[
        {"url": "https://sokoglam.com/products/discontinued-serum", "product_group": ""},
    ])

    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_sync_playwright.return_value.start.return_value = mock_pw
    mock_pw.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    # Redirected to home page / collections
    mock_page.url = "https://sokoglam.com/"

    result = adapter.fetch()

    # Must produce NO observations
    assert len(result.observations) == 0
    # Must record redirect error
    assert any("Unexpected redirect" in err for err in result.errors)


# ==============================================================================
# 3. Observation Validation Gate Tests (Requirement 3)
# ==============================================================================

def test_validator_rejects_missing_or_invalid_fields():
    """Test monitor/validator.py rules for title, price, and variant_id."""
    now = datetime.now(timezone.utc)

    # 1. Missing title
    obs_no_title = Observation(
        site="Store", product_id="1", variant_id="v1",
        product_title="", variant_title="Default",
        price_cents=2000, compare_at_cents=None, currency="USD", available=True, url="http://x.com", fetched_at=now,
    )
    ok, reason = validate(obs_no_title)
    assert ok is False
    assert "title is empty" in reason.lower()

    # 2. Placeholder "Unknown Product"
    obs_unknown = Observation(
        site="Store", product_id="1", variant_id="v1",
        product_title="Unknown Product", variant_title="Default",
        price_cents=2000, compare_at_cents=None, currency="USD", available=True, url="http://x.com", fetched_at=now,
    )
    ok, reason = validate(obs_unknown)
    assert ok is False
    assert "title is empty" in reason.lower()

    # 3. Missing price (None)
    obs_no_price = Observation(
        site="Store", product_id="1", variant_id="v1",
        product_title="Valid Serum", variant_title="Default",
        price_cents=None, compare_at_cents=None, currency="USD", available=True, url="http://x.com", fetched_at=now,
    )
    ok, reason = validate(obs_no_price)
    assert ok is False
    assert "missing" in reason.lower()

    # 4. Zero or negative price
    obs_zero = Observation(
        site="Store", product_id="1", variant_id="v1",
        product_title="Valid Serum", variant_title="Default",
        price_cents=0, compare_at_cents=None, currency="USD", available=True, url="http://x.com", fetched_at=now,
    )
    ok, reason = validate(obs_zero)
    assert ok is False
    assert "<= 0" in reason

    # 5. Missing variant_id
    obs_no_var = Observation(
        site="Store", product_id="1", variant_id="",
        product_title="Valid Serum", variant_title="Default",
        price_cents=2000, compare_at_cents=None, currency="USD", available=True, url="http://x.com", fetched_at=now,
    )
    ok, reason = validate(obs_no_var)
    assert ok is False
    assert "variant id is missing" in reason.lower()

    # 6. Valid observation
    obs_valid = Observation(
        site="Store", product_id="1", variant_id="v1",
        product_title="Valid Serum", variant_title="Default",
        price_cents=2000, compare_at_cents=None, currency="USD", available=True, url="http://x.com", fetched_at=now,
    )
    ok, reason = validate(obs_valid)
    assert ok is True
    assert reason == ""


def test_validator_detects_suspicious_price_changes():
    """Test that suspicious price changes exceeding threshold are held for confirmation."""
    now = datetime.now(timezone.utc)
    obs_current = Observation(
        site="Store", product_id="1", variant_id="v1",
        product_title="Luxury Cream", variant_title="Default",
        price_cents=1000, compare_at_cents=None, currency="USD", available=True, url="http://x.com", fetched_at=now,
    )
    # Previous check was $100.00 (10000 cents), current is $10.00 (1000 cents) -> 90% drop!
    previous_check = {"price_cents": 10000, "variant_id": "v1"}

    # With threshold 80%: 90% change is flagged as suspicious
    ok, reason = validate(obs_current, previous=previous_check, suspicious_change_percent=80.0)
    assert ok is False
    assert "suspicious price change" in reason.lower()
    assert "held for confirmation" in reason.lower()

    # Normal 10% change should be accepted
    obs_normal = Observation(
        site="Store", product_id="1", variant_id="v1",
        product_title="Luxury Cream", variant_title="Default",
        price_cents=9000, compare_at_cents=None, currency="USD", available=True, url="http://x.com", fetched_at=now,
    )
    ok_normal, reason_normal = validate(obs_normal, previous=previous_check, suspicious_change_percent=80.0)
    assert ok_normal is True


# ==============================================================================
# 4. Runner Validation Gate Integration Tests (Requirement 4)
# ==============================================================================

def test_runner_never_saves_invalid_observations(tmp_path: Path):
    """Invalid observations are never written to variants, price_checks, or events."""
    db_file = tmp_path / "test.db"
    config_file = tmp_path / "sites.yaml"
    config_file.write_text(
        """
alerts:
  min_price_change_cents: 50
  suspicious_change_percent: 80
sites:
  - name: "Test Store"
    adapter: "shopify"
    base_url: "https://example.com"
    currency: "USD"
        """,
        encoding="utf-8",
    )

    now = datetime.now(timezone.utc)
    # Produce an invalid observation (empty title and price None)
    invalid_obs = Observation(
        site="Test Store",
        product_id="invalid_1",
        variant_id="inv_v1",
        product_title="",
        variant_title="",
        price_cents=None,
        compare_at_cents=None,
        currency="USD",
        available=False,
        url="https://example.com/products/broken",
        fetched_at=now,
    )
    fake_result = FetchResult(observations=[invalid_obs], errors=["Scrape warning"])

    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=fake_result), \
         patch("monitor.runner.send_message") as mock_send, \
         patch("monitor.runner.send_error_message") as mock_send_err:

        stats = run_once(config_path=str(config_file), db_path=str(db_file))

        # Check stats: 0 variants saved
        assert stats["variants_seen"] == 0
        assert stats["checks_saved"] == 0
        assert stats["events_created"] == 0
        assert any("Invalid observation" in err for err in stats["errors"])

        # Database tables must remain completely empty
        conn = storage.get_connection(str(db_file))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM variants;")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM price_checks;")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM events;")
        assert cur.fetchone()[0] == 0
        conn.close()

        # No Telegram price alert sent for invalid observation
        mock_send.assert_not_called()


def test_failed_url_does_not_create_out_of_stock_event(tmp_path: Path):
    """When an existing product's URL fails in a subsequent run, it must NOT create out_of_stock events."""
    db_file = tmp_path / "test.db"
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

    now = datetime.now(timezone.utc)
    # Run 1: Product exists and is in stock
    valid_obs = Observation(
        site="Test Store",
        product_id="prod_1",
        variant_id="var_1",
        product_title="Original Cream",
        variant_title="50ml",
        price_cents=3000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://example.com/products/cream",
        fetched_at=now,
    )
    res_1 = FetchResult(observations=[valid_obs])

    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=res_1), \
         patch("monitor.runner.send_message"):
        run_once(config_path=str(config_file), db_path=str(db_file))

    # Run 2: The URL fails (returns HTTP 404 -> adapter produces 0 observations)
    res_2 = FetchResult(observations=[], errors=["HTTP 404 for https://example.com/products/cream"])

    with patch("monitor.runner.ShopifyAdapter.fetch", return_value=res_2), \
         patch("monitor.runner.send_message") as mock_price_send, \
         patch("monitor.runner.send_error_message") as mock_err_send:
        stats_2 = run_once(config_path=str(config_file), db_path=str(db_file))

        # Must NOT create out_of_stock events
        assert stats_2["events_created"] == 0
        assert len(stats_2["events"]) == 0

        # Check database events table
        conn = storage.get_connection(str(db_file))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM events WHERE event_type = 'out_of_stock';")
        assert cur.fetchone()[0] == 0
        conn.close()

        # Price alerts must not be sent
        mock_price_send.assert_not_called()
