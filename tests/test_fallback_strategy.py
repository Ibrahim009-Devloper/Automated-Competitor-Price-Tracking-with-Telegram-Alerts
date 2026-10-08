"""Tests for multi-level fallback strategy and response validation."""

from datetime import datetime, timezone
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from monitor.adapters.shopify import ShopifyAdapter
from monitor.fallback import (
    extract_product_handle,
    fetch_with_fallback,
    get_store_origin,
    get_target_urls_for_site,
)
from monitor.models import FetchResult, Observation
from monitor.utils.http import is_json_response, parse_json_safely


# ==============================================================================
# 1. Response Validation Tests
# ==============================================================================

def test_is_json_response_and_parse_json_safely():
    """Verify that response validation strictly checks status, content-type, and body."""
    # 1. Valid JSON response
    valid_resp = requests.Response()
    valid_resp.status_code = 200
    valid_resp.headers = {"Content-Type": "application/json; charset=utf-8"}
    valid_resp._content = b'{"products": [{"id": "1", "title": "Serum"}]}'

    assert is_json_response(valid_resp) is True
    parsed = parse_json_safely(valid_resp)
    assert parsed == {"products": [{"id": "1", "title": "Serum"}]}

    # 2. Non-200 status (e.g. 404 or 500)
    err_resp = requests.Response()
    err_resp.status_code = 404
    err_resp.headers = {"Content-Type": "application/json"}
    err_resp._content = b'{"error": "Not found"}'
    assert is_json_response(err_resp) is False
    assert parse_json_safely(err_resp) is None

    # 3. HTML error page with 200 status (e.g. Cloudflare or custom 404)
    html_resp = requests.Response()
    html_resp.status_code = 200
    html_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    html_resp._content = b"<!DOCTYPE html><html><body>Error 404 Not Found</body></html>"
    assert is_json_response(html_resp) is False
    assert parse_json_safely(html_resp) is None

    # 4. Text response that is not JSON
    text_resp = requests.Response()
    text_resp.status_code = 200
    text_resp.headers = {"Content-Type": "text/plain"}
    text_resp._content = b"Unknown error occurred"
    assert is_json_response(text_resp) is False
    assert parse_json_safely(text_resp) is None


# ==============================================================================
# 2. Product Handle Extraction Tests
# ==============================================================================

def test_extract_product_handle_and_store_origin():
    """Test extracting handle and store origin from Shopify product URLs."""
    # YanyBeauty URL
    yany_url = "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum"
    assert extract_product_handle(yany_url) == "mango-breeze-refreshing-eye-serum"
    assert get_store_origin(yany_url) == "https://yanybeauty.co"

    # URL with variant and query params
    soko_url = "https://sokoglam.com/products/dermalogy-serum-rc?variant=45934865580101&currency=USD"
    assert extract_product_handle(soko_url) == "dermalogy-serum-rc"
    assert get_store_origin(soko_url) == "https://sokoglam.com"

    # Non-product URL
    assert extract_product_handle("https://yanybeauty.co/collections/all") is None


# ==============================================================================
# 3. Strategy 1: Normal Shopify Store (Existing /products.json Works)
# ==============================================================================

def test_normal_shopify_store_uses_existing_products_json(caplog):
    """Normal Shopify store where /products.json works succeeds on Strategy 1."""
    caplog.set_level(logging.INFO)
    site_config = {
        "name": "Normal Shopify Store",
        "adapter": "shopify",
        "base_url": "https://normalstore.com",
        "currency": "USD",
        "delay_seconds": [0.0, 0.0],
    }
    adapter = ShopifyAdapter(site_config)

    fake_resp = requests.Response()
    fake_resp.status_code = 200
    fake_resp.headers = {"Content-Type": "application/json"}
    fake_resp._content = b"""
    {
      "products": [
        {
          "id": 1001,
          "title": "Hydrating Toner",
          "handle": "hydrating-toner",
          "variants": [
            {
              "id": 2001,
              "title": "Default Title",
              "price": "24.00",
              "available": true
            }
          ]
        }
      ]
    }
    """

    with patch("monitor.adapters.shopify.http_get", return_value=fake_resp) as mock_get:
        result = adapter.fetch()

        # Strategy 1 succeeded
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.product_title == "Hydrating Toner"
        assert obs.price_cents == 2400
        assert obs.available is True
        assert obs.site == "Normal Shopify Store"
        assert len(result.errors) == 0

        # Checked that /products.json was called
        mock_get.assert_called_once()
        assert "products.json" in mock_get.call_args[0][0]

    # Verify logging contains 'Trying Shopify /products.json'
    assert any("Trying Shopify /products.json" in record.message for record in caplog.records)


# ==============================================================================
# 4. Strategy 2: YanyBeauty Handle-based Shopify JSON Fallback
# ==============================================================================

def test_yanybeauty_handle_based_shopify_json_fallback(caplog):
    """When generic /products.json fails on YanyBeauty, handle-based endpoint succeeds."""
    caplog.set_level(logging.INFO)
    yany_config = {
        "name": "yanybeuty",
        "adapter": "shopify",
        "base_url": "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum",
        "currency": "USD",
        "delay_seconds": [0.0, 0.0],
    }
    adapter = ShopifyAdapter(yany_config)

    # 1. Generic /products.json returns 404
    from monitor.utils.http import HttpError

    def fake_http_get(url, params=None, **kwargs):
        if url == "https://yanybeauty.co/products.json" and (params is None or "handle" not in params):
            raise HttpError("HTTP 404 Not Found for URL: https://yanybeauty.co/products.json", status_code=404)
        elif url == "https://yanybeauty.co/products.json" and params and params.get("handle") == "mango-breeze-refreshing-eye-serum":
            resp = requests.Response()
            resp.status_code = 200
            resp.headers = {"Content-Type": "application/json"}
            resp._content = b"""
            {
              "products": [
                {
                  "id": 5555,
                  "title": "Mango Breeze Refreshing Eye Serum",
                  "handle": "mango-breeze-refreshing-eye-serum",
                  "variants": [
                    {
                      "id": 9999,
                      "title": "15ml",
                      "price": "28.00",
                      "available": true
                    }
                  ]
                }
              ]
            }
            """
            return resp
        raise HttpError(f"Unexpected url {url}", status_code=404)

    with patch("monitor.fallback.http_get", side_effect=fake_http_get), \
         patch("monitor.adapters.shopify.http_get", side_effect=fake_http_get):
        result = adapter.fetch()

        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.product_title == "Mango Breeze Refreshing Eye Serum"
        assert obs.price_cents == 2800
        assert obs.available is True

    # Verify logs
    log_messages = [r.message for r in caplog.records]
    assert any("Trying Shopify /products.json" in m for m in log_messages)
    assert any("Generic Shopify JSON failed, trying handle-based endpoint" in m for m in log_messages)
    assert any("Handle-based Shopify JSON succeeded" in m for m in log_messages)


# ==============================================================================
# 5. Strategy 3: YanyBeauty JSON-LD Fallback
# ==============================================================================

def test_yanybeauty_jsonld_fallback(caplog):
    """When both generic and handle-based JSON fail, JSON-LD on product HTML succeeds."""
    caplog.set_level(logging.INFO)
    yany_config = {
        "name": "yanybeuty",
        "adapter": "shopify",
        "base_url": "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum",
        "currency": "USD",
        "delay_seconds": [0.0, 0.0],
    }
    adapter = ShopifyAdapter(yany_config)

    from monitor.utils.http import HttpError

    html_with_jsonld = """
    <!DOCTYPE html>
    <html>
    <head>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Mango Breeze Refreshing Eye Serum",
        "sku": "YB-MANGO-01",
        "offers": {
          "@type": "Offer",
          "price": "28.00",
          "priceCurrency": "USD",
          "availability": "https://schema.org/InStock",
          "url": "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum"
        }
      }
      </script>
    </head>
    <body><h1>Mango Breeze Refreshing Eye Serum</h1></body>
    </html>
    """

    def fake_http_get(url, params=None, **kwargs):
        if "products.json" in url:
            raise HttpError(f"HTTP 404 for {url}", status_code=404)
        if url == "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum":
            resp = requests.Response()
            resp.status_code = 200
            resp.headers = {"Content-Type": "text/html; charset=utf-8"}
            resp._content = html_with_jsonld.encode("utf-8")
            return resp
        raise HttpError(f"Unexpected URL: {url}", status_code=404)

    with patch("monitor.fallback.http_get", side_effect=fake_http_get), \
         patch("monitor.adapters.shopify.http_get", side_effect=fake_http_get):
        result = adapter.fetch()

        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.product_title == "Mango Breeze Refreshing Eye Serum"
        assert obs.price_cents == 2800
        assert obs.available is True

    log_messages = [r.message for r in caplog.records]
    assert any("Falling back to JSON-LD" in m for m in log_messages)
    assert any("JSON-LD extraction succeeded" in m for m in log_messages)


# ==============================================================================
# 6. Strategy 4: HTML/DOM Fallback (Static first, then Playwright)
# ==============================================================================

def test_yanybeauty_static_html_dom_fallback(caplog):
    """When JSON-LD is missing, static HTML DOM selector succeeds without Playwright."""
    caplog.set_level(logging.INFO)
    yany_config = {
        "name": "yanybeuty",
        "adapter": "shopify",
        "base_url": "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum",
        "currency": "USD",
        "delay_seconds": [0.0, 0.0],
    }
    adapter = ShopifyAdapter(yany_config)

    from monitor.utils.http import HttpError

    html_plain = """
    <!DOCTYPE html>
    <html>
    <head><title>Mango Breeze</title></head>
    <body>
      <h1 class="product-title">Mango Breeze Refreshing Eye Serum</h1>
      <span class="price-item">$28.00</span>
      <button name="add">Add to Cart</button>
    </body>
    </html>
    """

    def fake_http_get(url, params=None, **kwargs):
        if "products.json" in url:
            raise HttpError(f"HTTP 404 for {url}", status_code=404)
        if url == "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum":
            resp = requests.Response()
            resp.status_code = 200
            resp.headers = {"Content-Type": "text/html; charset=utf-8"}
            resp._content = html_plain.encode("utf-8")
            return resp
        raise HttpError(f"Unexpected URL: {url}", status_code=404)

    with patch("monitor.fallback.http_get", side_effect=fake_http_get), \
         patch("monitor.adapters.shopify.http_get", side_effect=fake_http_get), \
         patch("monitor.adapters.playwright.PlaywrightAdapter.fetch_single_url") as mock_pw:
        result = adapter.fetch()

        # Should extract from static DOM without calling Playwright
        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.product_title == "Mango Breeze Refreshing Eye Serum"
        assert obs.price_cents == 2800
        mock_pw.assert_not_called()

    log_messages = [r.message for r in caplog.records]
    assert any("Falling back to HTML/Playwright" in m for m in log_messages)
    assert any("Static HTML/DOM extraction succeeded" in m for m in log_messages)


def test_yanybeauty_playwright_js_rendered_fallback(caplog):
    """When static HTML has no price, Playwright browser is invoked and succeeds."""
    caplog.set_level(logging.INFO)
    yany_config = {
        "name": "yanybeuty",
        "adapter": "shopify",
        "base_url": "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum",
        "currency": "USD",
        "delay_seconds": [0.0, 0.0],
    }
    adapter = ShopifyAdapter(yany_config)

    from monitor.utils.http import HttpError

    # Empty price container in static HTML (rendered via client JS)
    html_no_price = """
    <!DOCTYPE html>
    <html>
    <body>
      <h1 class="product-title">Mango Breeze Refreshing Eye Serum</h1>
      <span class="price-item"></span>
    </body>
    </html>
    """

    now = datetime.now(timezone.utc)
    pw_extracted_obs = [
        Observation(
            site="yanybeuty",
            product_id="mango-breeze",
            variant_id="var-1",
            product_title="Mango Breeze Refreshing Eye Serum",
            variant_title="Default Title",
            price_cents=2800,
            compare_at_cents=None,
            currency="USD",
            available=True,
            url="https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum",
            fetched_at=now,
        )
    ]

    def fake_http_get(url, params=None, **kwargs):
        if "products.json" in url:
            raise HttpError(f"HTTP 404 for {url}", status_code=404)
        if url == "https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum":
            resp = requests.Response()
            resp.status_code = 200
            resp.headers = {"Content-Type": "text/html; charset=utf-8"}
            resp._content = html_no_price.encode("utf-8")
            return resp
        raise HttpError(f"Unexpected URL: {url}", status_code=404)

    with patch("monitor.fallback.http_get", side_effect=fake_http_get), \
         patch("monitor.adapters.shopify.http_get", side_effect=fake_http_get), \
         patch("monitor.adapters.playwright.PlaywrightAdapter.fetch_single_url", return_value=pw_extracted_obs) as mock_pw:
        result = adapter.fetch()

        assert len(result.observations) == 1
        obs = result.observations[0]
        assert obs.price_cents == 2800
        mock_pw.assert_called_once()

    log_messages = [r.message for r in caplog.records]
    assert any("Playwright extraction succeeded" in m for m in log_messages)


# ==============================================================================
# 7. Strategy 5: Graceful Failure
# ==============================================================================

def test_all_strategies_fail_gracefully_without_crash(caplog):
    """When all 4 strategies fail, records error with attempted strategies and does not crash."""
    site_config = {
        "name": "Completely Broken Store",
        "adapter": "shopify",
        "base_url": "https://brokenstore.com/products/unreachable-item",
        "currency": "USD",
        "delay_seconds": [0.0, 0.0],
    }
    adapter = ShopifyAdapter(site_config)

    from monitor.utils.http import HttpError

    def fake_http_get(url, params=None, **kwargs):
        raise HttpError("Network connection failed", status_code=500)

    with patch("monitor.fallback.http_get", side_effect=fake_http_get), \
         patch("monitor.adapters.shopify.http_get", side_effect=fake_http_get), \
         patch("monitor.adapters.playwright.PlaywrightAdapter.fetch_single_url", return_value=[]):
        result = adapter.fetch()

        # Should not crash
        assert len(result.observations) == 0
        assert len(result.errors) >= 1
        assert "All price extraction strategies failed" in result.errors[0]
        assert "attempted:" in result.errors[0]

    log_messages = [r.message for r in caplog.records]
    assert any("All price extraction strategies failed" in m for m in log_messages)
