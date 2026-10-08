"""Unit tests for ShopifyAdapter parsing without network calls."""

import json
from pathlib import Path
from datetime import datetime, timezone
import pytest

from monitor.adapters.shopify import ShopifyAdapter


@pytest.fixture
def sample_payload() -> dict:
    """Load sample Shopify products JSON fixture from disk."""
    fixture_path = Path(__file__).parent / "fixtures" / "products.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def adapter() -> ShopifyAdapter:
    """Instantiate a ShopifyAdapter configured for a demo store."""
    site_config = {
        "name": "K-Beauty Skincare",
        "adapter": "shopify",
        "base_url": "https://sokoglam.com",
        "currency": "USD",
        "delay_seconds": [0.0, 0.0],
    }
    return ShopifyAdapter(site_config)


def test_fixture_parsing_total_variants(adapter: ShopifyAdapter, sample_payload: dict):
    """Test that all variants across all products are extracted."""
    fixed_time = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
    observations = adapter.parse_products_data(sample_payload, fetched_at=fixed_time)

    # 3 products: 2 variants + 1 variant + 1 variant = 4 variants
    assert len(observations) == 4
    for obs in observations:
        assert obs.site == "K-Beauty Skincare"
        assert obs.currency == "USD"
        assert obs.fetched_at == fixed_time


def test_variant_ids_and_titles(adapter: ShopifyAdapter, sample_payload: dict):
    """Test that product and variant IDs and titles are correctly parsed as strings."""
    observations = adapter.parse_products_data(sample_payload)

    first = observations[0]
    assert first.product_id == "8316758818885"
    assert first.variant_id == "45934865580101"
    assert first.product_title == "Dermalogy Double Vita Spot Toning Serum (RC)"
    assert first.variant_title == "30ml / 1.01 fl oz"
    assert "dermalogy-double-vita-spot-toning-serum-rc" in first.url
    assert "variant=45934865580101" in first.url


def test_prices_extracted_correctly(adapter: ShopifyAdapter, sample_payload: dict):
    """Test that prices are accurately converted to integer cents."""
    observations = adapter.parse_products_data(sample_payload)

    # Variant 1: price "34.00" -> 3400 cents, compare_at "42.00" -> 4200 cents
    assert observations[0].price_cents == 3400
    assert observations[0].compare_at_cents == 4200

    # Variant 2: price "52.50" -> 5250 cents, compare_at null -> None
    assert observations[1].price_cents == 5250
    assert observations[1].compare_at_cents is None

    # Variant 3: price "18.00" -> 1800 cents, compare_at "22.50" -> 2250 cents
    assert observations[2].price_cents == 1800
    assert observations[2].compare_at_cents == 2250


def test_missing_price_is_none_never_zero(adapter: ShopifyAdapter, sample_payload: dict):
    """Rule requirement: if price is missing, adapter sets price_cents to None, never 0."""
    observations = adapter.parse_products_data(sample_payload)

    # Variant 4 has price: null
    sample_obs = observations[3]
    assert sample_obs.price_cents is None
    assert sample_obs.price_cents != 0
    assert sample_obs.compare_at_cents is None


def test_availability_extracted_correctly(adapter: ShopifyAdapter, sample_payload: dict):
    """Test that variant in-stock availability boolean is extracted accurately."""
    observations = adapter.parse_products_data(sample_payload)

    assert observations[0].available is True
    assert observations[1].available is False  # Out of stock variant
    assert observations[2].available is True
    assert observations[3].available is True


def test_empty_payload_handled_gracefully(adapter: ShopifyAdapter):
    """Test parsing empty or unexpected payload does not raise exceptions."""
    assert adapter.parse_products_data({}) == []
    assert adapter.parse_products_data({"products": []}) == []
    assert adapter.parse_products_data({"invalid_key": 123}) == []
