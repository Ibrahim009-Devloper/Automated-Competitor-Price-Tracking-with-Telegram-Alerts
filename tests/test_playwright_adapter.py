"""Unit tests for the Playwright site adapter.

Tests run completely offline, validating HTML fixture parsing, variant options,
missing price handling, error boundaries, and access wall detection.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from monitor.adapters.playwright import PlaywrightAdapter
from monitor.models import FetchResult, Observation


@pytest.fixture
def sample_config():
    """Default test configuration for PlaywrightAdapter."""
    return {
        "name": "Glow Beauty (Playwright)",
        "adapter": "playwright",
        "base_url": "https://glowbeauty.com",
        "currency": "USD",
        "delay_seconds": [0.01, 0.02],
        "timeout": 10,
        "price_selector": ".price-item--sale, .price",
        "compare_price_selector": ".price-item--regular, .compare-price",
        "title_selector": "h1, .product__title",
        "availability_selector": "[name='add'], .add-to-cart",
        "wait_for": ".price",
    }


@pytest.fixture
def sample_html_fixture():
    """Read the sample Playwright HTML fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_playwright_product.html"
    assert fixture_path.exists(), "Sample Playwright fixture must exist"
    return fixture_path.read_text(encoding="utf-8")


def test_parse_real_fixture_offline(sample_config, sample_html_fixture):
    """Test offline parsing of rendered DOM fixture without browser launch (Rule 8)."""
    adapter = PlaywrightAdapter(sample_config)
    url = "https://glowbeauty.com/products/vitamin-c-serum"
    errors = []

    observations = adapter.parse_dom(
        html_text=sample_html_fixture,
        page_url=url,
        errors_out=errors,
    )

    assert len(observations) == 1
    obs = observations[0]
    assert obs.site == "Glow Beauty (Playwright)"
    assert obs.product_title == "Glow Vitamin C Serum"
    # Price $28.50 -> 2850 cents
    assert obs.price_cents == 2850
    # Compare at $35.00 -> 3500 cents
    assert obs.compare_at_cents == 3500
    assert obs.currency == "USD"
    assert obs.available is True
    assert len(errors) == 0


def test_variant_selector_handling(sample_config, sample_html_fixture):
    """Test extracting multiple variants when variant_selector is configured (Rule 7)."""
    cfg = dict(sample_config)
    cfg["variant_selector"] = "select[name='id'] option"
    adapter = PlaywrightAdapter(cfg)
    url = "https://glowbeauty.com/products/vitamin-c-serum"

    observations = adapter.parse_dom(
        html_text=sample_html_fixture,
        page_url=url,
    )

    assert len(observations) == 2
    # Variant 1: 30ml
    assert observations[0].variant_id == "var-30ml"
    assert "30ml" in observations[0].variant_title
    assert observations[0].price_cents == 2850

    # Variant 2: 50ml
    assert observations[1].variant_id == "var-50ml"
    assert "50ml" in observations[1].variant_title
    assert observations[1].price_cents == 4500


def test_missing_price_never_guesses_zero(sample_config):
    """Test that missing price selector sets price_cents to None, never 0 (Rule 2)."""
    adapter = PlaywrightAdapter(sample_config)
    html = """
    <html>
      <body>
        <h1 class="product__title">Sold Out Special</h1>
        <div class="no-price">Coming Soon</div>
        <button class="add-to-cart" disabled>Sold Out</button>
      </body>
    </html>
    """
    errors = []
    observations = adapter.parse_dom(
        html_text=html,
        page_url="https://glowbeauty.com/products/special",
        errors_out=errors,
    )

    assert len(observations) == 1
    assert observations[0].price_cents is None
    assert observations[0].available is False
    assert len(errors) == 1
    assert "Could not extract price" in errors[0]


def test_missing_availability_is_none(sample_config):
    """Test that missing availability selector sets available to None (Rule 2)."""
    adapter = PlaywrightAdapter(sample_config)
    html = """
    <html>
      <body>
        <h1 class="product__title">Mystery Product</h1>
        <span class="price">$19.99</span>
      </body>
    </html>
    """
    observations = adapter.parse_dom(
        html_text=html,
        page_url="https://glowbeauty.com/products/mystery",
    )
    assert len(observations) == 1
    assert observations[0].price_cents == 1999
    assert observations[0].available is None


@patch("monitor.adapters.playwright.sync_playwright")
def test_blocked_403_stops_site_run(mock_sync_playwright, sample_config):
    """Test that HTTP 403 stops further requests for that site (Rule 5)."""
    adapter = PlaywrightAdapter(sample_config)
    adapter.load_target_urls = MagicMock(return_value=[
        {"url": "https://glowbeauty.com/prod1", "product_group": ""},
        {"url": "https://glowbeauty.com/prod2", "product_group": ""},
    ])

    # Setup mock playwright browser & page
    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_sync_playwright.return_value.start.return_value = mock_pw
    mock_pw.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    # Simulate 403 response
    mock_response = MagicMock()
    mock_response.status = 403
    mock_page.goto.return_value = mock_response

    result = adapter.fetch()

    # Browser must close in finally block
    assert mock_browser.close.called
    # Must stop immediately after first 403 URL
    assert mock_page.goto.call_count == 1
    assert len(result.errors) == 1
    assert "blocked: HTTP 403" in result.errors[0]
    assert len(result.observations) == 0


@patch("monitor.adapters.playwright.sync_playwright")
def test_captcha_stops_site_run(mock_sync_playwright, sample_config):
    """Test that captcha detection stops further requests for that site (Rule 5)."""
    adapter = PlaywrightAdapter(sample_config)
    adapter.load_target_urls = MagicMock(return_value=[
        {"url": "https://glowbeauty.com/prod1", "product_group": ""},
        {"url": "https://glowbeauty.com/prod2", "product_group": ""},
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
    mock_page.content.return_value = "<html><title>Just a moment...</title><body>cf-challenge</body></html>"

    result = adapter.fetch()

    assert mock_browser.close.called
    assert mock_page.goto.call_count == 1
    assert len(result.errors) == 1
    assert "blocked: captcha challenge detected" in result.errors[0]
    assert len(result.observations) == 0


@patch("monitor.adapters.playwright.sync_playwright")
def test_single_failing_url_does_not_stop_other_urls(mock_sync_playwright, sample_config):
    """Test that a failure on one product continues with remaining products (Rule 6)."""
    adapter = PlaywrightAdapter(sample_config)
    adapter.load_target_urls = MagicMock(return_value=[
        {"url": "https://glowbeauty.com/prod1", "product_group": ""},
        {"url": "https://glowbeauty.com/prod2", "product_group": ""},
    ])

    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_sync_playwright.return_value.start.return_value = mock_pw
    mock_pw.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    # First page throws navigation error, second page succeeds
    from playwright.sync_api import Error as PlaywrightError
    mock_page.goto.side_effect = [
        PlaywrightError("Navigation timeout of 20000ms exceeded"),
        MagicMock(status=200),
    ]
    mock_page.content.return_value = """
    <html>
      <h1 class="product__title">Success Serum</h1>
      <span class="price">$22.00</span>
      <button class="add-to-cart">Add to Cart</button>
    </html>
    """

    result = adapter.fetch()

    assert mock_page.goto.call_count == 2
    assert len(result.errors) == 1
    assert "Navigation timeout" in result.errors[0]
    assert len(result.observations) == 1
    assert result.observations[0].product_title == "Success Serum"
    assert result.observations[0].price_cents == 2200
