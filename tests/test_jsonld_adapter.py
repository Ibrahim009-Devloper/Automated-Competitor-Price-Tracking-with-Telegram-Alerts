"""Unit tests for the JSON-LD Schema.org site adapter.

Tests run completely offline without network requests, validating fixture parsing,
variant handling, error boundaries, rate-limiting, and blocking detection.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from monitor.adapters.jsonld import JsonLdAdapter
from monitor.models import FetchResult, Observation
from monitor.utils.http import HttpError


@pytest.fixture
def sample_config():
    """Default test configuration for JsonLdAdapter."""
    return {
        "name": "K-Beauty Store (JSON-LD)",
        "adapter": "jsonld",
        "base_url": "https://sokoglam.com",
        "currency": "USD",
        "delay_seconds": [0.01, 0.02],
        "timeout": 10,
        "max_retries": 1,
        "jsonld_type": "Product",
        "offers_field": "offers",
        "price_field": "price",
        "currency_field": "priceCurrency",
        "availability_field": "availability",
    }


@pytest.fixture
def sample_html_fixture():
    """Read the real HTML fixture saved from Soko Glam product page."""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_jsonld_product.html"
    assert fixture_path.exists(), "Sample HTML fixture must exist"
    return fixture_path.read_text(encoding="utf-8")


def test_parse_real_fixture_offline(sample_config, sample_html_fixture):
    """Test parsing real offline HTML fixture without network (Rule 8)."""
    adapter = JsonLdAdapter(sample_config)
    url = "https://sokoglam.com/products/dermalogy-double-vita-spot-toning-serum-rc"
    errors = []

    observations = adapter.parse_html(
        html_text=sample_html_fixture,
        page_url=url,
        errors_out=errors,
    )

    assert len(observations) >= 1
    obs = observations[0]
    assert obs.site == "K-Beauty Store (JSON-LD)"
    assert "Dermalogy Double Vita Spot Toning Serum" in obs.product_title
    # Price is 34.00 USD -> 3400 cents (never float or 0)
    assert obs.price_cents == 3400
    assert obs.currency == "USD"
    assert obs.available is True
    assert "variant" in obs.url or obs.variant_id != ""


def test_multiple_variants_handling(sample_config):
    """Test that multiple offers in JSON-LD generate separate Observation per variant (Rule 7)."""
    adapter = JsonLdAdapter(sample_config)
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Multi-Size Cleanser",
          "offers": [
            {
              "@type": "Offer",
              "sku": "CLEAN-50ML",
              "name": "50ml Travel",
              "price": "14.50",
              "priceCurrency": "USD",
              "availability": "https://schema.org/InStock"
            },
            {
              "@type": "Offer",
              "sku": "CLEAN-200ML",
              "name": "200ml Full Size",
              "price": "28.00",
              "priceCurrency": "USD",
              "availability": "https://schema.org/OutOfStock"
            }
          ]
        }
        </script>
      </head>
      <body></body>
    </html>
    """
    observations = adapter.parse_html(html, "https://mock.com/product")
    assert len(observations) == 2

    # Variant 1
    assert observations[0].variant_id == "CLEAN-50ML"
    assert observations[0].variant_title == "50ml Travel"
    assert observations[0].price_cents == 1450
    assert observations[0].available is True

    # Variant 2
    assert observations[1].variant_id == "CLEAN-200ML"
    assert observations[1].variant_title == "200ml Full Size"
    assert observations[1].price_cents == 2800
    assert observations[1].available is False


def test_missing_price_never_guesses_zero(sample_config):
    """Test that missing price results in None, never 0, and records an error (Rule 2)."""
    adapter = JsonLdAdapter(sample_config)
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Mystery Cream",
          "offers": {
            "@type": "Offer",
            "price": "Call for price",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
    </html>
    """
    errors = []
    observations = adapter.parse_html(html, "https://mock.com/product", errors_out=errors)
    assert len(observations) == 1
    # Must be None, never 0
    assert observations[0].price_cents is None
    assert len(errors) == 1
    assert "Could not parse price" in errors[0]


def test_unknown_availability_is_none(sample_config):
    """Test that ambiguous availability is None (never guessed) per Rule 2."""
    adapter = JsonLdAdapter(sample_config)
    assert adapter.parse_availability("https://schema.org/InStock") is True
    assert adapter.parse_availability("https://schema.org/OutOfStock") is False
    assert adapter.parse_availability("https://schema.org/SoldOut") is False
    assert adapter.parse_availability("UnknownAvailabilityStatus") is None
    assert adapter.parse_availability(None) is None


def test_graph_and_array_extraction(sample_config):
    """Test extracting Product nested inside @graph and mixed types."""
    adapter = JsonLdAdapter(sample_config)
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@graph": [
            {"@type": "Organization", "name": "Beauty Co"},
            {
              "@type": "Product",
              "name": "Graph Serum",
              "offers": {
                "price": "39.99",
                "availability": "InStock"
              }
            }
          ]
        }
        </script>
      </head>
    </html>
    """
    observations = adapter.parse_html(html, "https://mock.com/serum")
    assert len(observations) == 1
    assert observations[0].product_title == "Graph Serum"
    assert observations[0].price_cents == 3999
    assert observations[0].available is True


@patch("monitor.adapters.jsonld.http_get")
def test_blocked_403_stops_site_run(mock_http_get, sample_config):
    """Test that HTTP 403 stops further requests for that site and records clear error (Rule 5)."""
    adapter = JsonLdAdapter(sample_config)
    adapter.load_target_urls = MagicMock(return_value=[
        {"url": "https://sokoglam.com/prod1", "product_group": ""},
        {"url": "https://sokoglam.com/prod2", "product_group": ""},
    ])

    mock_http_get.side_effect = HttpError("Forbidden", status_code=403)

    result = adapter.fetch()
    # Must stop immediately: only 1 request attempt
    assert mock_http_get.call_count == 1
    assert len(result.errors) == 1
    assert "blocked: HTTP 403" in result.errors[0]
    assert len(result.observations) == 0


@patch("monitor.adapters.jsonld.http_get")
def test_captcha_stops_site_run(mock_http_get, sample_config):
    """Test that captcha detection stops further requests for that site (Rule 5)."""
    adapter = JsonLdAdapter(sample_config)
    adapter.load_target_urls = MagicMock(return_value=[
        {"url": "https://sokoglam.com/prod1", "product_group": ""},
        {"url": "https://sokoglam.com/prod2", "product_group": ""},
    ])

    mock_resp = MagicMock()
    mock_resp.text = "<html><head><title>Just a moment...</title></head><body>cf-challenge</body></html>"
    mock_http_get.return_value = mock_resp

    result = adapter.fetch()
    assert mock_http_get.call_count == 1
    assert len(result.errors) == 1
    assert "blocked: captcha challenge detected" in result.errors[0]
    assert len(result.observations) == 0


@patch("monitor.adapters.jsonld.http_get")
def test_single_failing_url_does_not_stop_other_urls(mock_http_get, sample_config):
    """Test that one failing product URL continues with remaining URLs (Rule 6)."""
    adapter = JsonLdAdapter(sample_config)
    adapter.load_target_urls = MagicMock(return_value=[
        {"url": "https://sokoglam.com/prod1", "product_group": ""},
        {"url": "https://sokoglam.com/prod2", "product_group": ""},
    ])

    mock_resp_ok = MagicMock()
    mock_resp_ok.text = """
    <script type="application/ld+json">
    {"@type": "Product", "name": "Prod 2", "offers": {"price": "19.00", "availability": "InStock"}}
    </script>
    """

    # First URL fails with 404, second URL succeeds
    mock_http_get.side_effect = [
        HttpError("HTTP 404 Not Found", status_code=404),
        mock_resp_ok,
    ]

    result = adapter.fetch()
    assert mock_http_get.call_count == 2
    assert len(result.errors) == 1
    assert "HTTP 404" in result.errors[0]
    assert len(result.observations) == 1
    assert result.observations[0].product_title == "Prod 2"
