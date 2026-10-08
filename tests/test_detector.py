"""Unit tests for pure detect() change detection function."""

from datetime import datetime, timezone
import pytest

from monitor.detector import detect
from monitor.models import Observation


def make_obs(
    variant_id: str = "101",
    price_cents: int = 2500,
    available: bool = True,
    product_title: str = "Soothing Serum",
    variant_title: str = "50ml",
    site: str = "Demo Store",
) -> Observation:
    """Helper to construct an Observation for tests."""
    return Observation(
        site=site,
        product_id="1",
        variant_id=variant_id,
        product_title=product_title,
        variant_title=variant_title,
        price_cents=price_cents,
        compare_at_cents=None,
        currency="USD",
        available=available,
        url="https://demo.com/p",
        fetched_at=datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_detect_new_variant():
    """Test that previous=None produces a 'new_variant' event."""
    curr = make_obs(price_cents=3000, available=True)
    events = detect(previous=None, current=curr, min_change_cents=50)

    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "new_variant"
    assert ev["old_value"] is None
    assert ev["new_value"] == 3000
    assert ev["variant_id"] == 101


def test_detect_previous_none_explicit():
    """Requirement test: previous None returns 'new_variant'."""
    curr = make_obs(price_cents=1999)
    events = detect(previous=None, current=curr)
    assert len(events) == 1
    assert events[0]["event_type"] == "new_variant"


def test_detect_price_drop():
    """Test price drop equal or exceeding min_change_cents."""
    prev = {"price_cents": 3000, "available": 1}
    curr = make_obs(price_cents=2500)  # dropped by 500 cents ($5.00)

    events = detect(prev, curr, min_change_cents=100)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "price_drop"
    assert ev["old_value"] == 3000
    assert ev["new_value"] == 2500


def test_detect_price_increase():
    """Test price increase equal or exceeding min_change_cents."""
    prev = {"price_cents": 2000, "available": 1}
    curr = make_obs(price_cents=2600)  # increased by 600 cents ($6.00)

    events = detect(prev, curr, min_change_cents=50)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "price_increase"
    assert ev["old_value"] == 2000
    assert ev["new_value"] == 2600


def test_detect_change_smaller_than_threshold_ignored():
    """Test price change smaller than min_change_cents is ignored."""
    prev = {"price_cents": 2500, "available": 1}
    curr_drop = make_obs(price_cents=2480)  # dropped by 20 cents, threshold is 50
    curr_inc = make_obs(price_cents=2520)   # increased by 20 cents, threshold is 50

    assert detect(prev, curr_drop, min_change_cents=50) == []
    assert detect(prev, curr_inc, min_change_cents=50) == []


def test_detect_out_of_stock():
    """Test available 1 -> 0 produces 'out_of_stock' event."""
    prev = {"price_cents": 2500, "available": 1}
    curr = make_obs(price_cents=2500, available=False)

    events = detect(prev, curr, min_change_cents=0)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "out_of_stock"
    assert ev["old_value"] == 1
    assert ev["new_value"] == 0


def test_detect_back_in_stock():
    """Test available 0 -> 1 produces 'back_in_stock' event."""
    prev = {"price_cents": 2500, "available": 0}
    curr = make_obs(price_cents=2500, available=True)

    events = detect(prev, curr, min_change_cents=0)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "back_in_stock"
    assert ev["old_value"] == 0
    assert ev["new_value"] == 1


def test_detect_price_and_stock_change_together():
    """Test price change and stock change produce two separate events."""
    prev = {"price_cents": 3500, "available": 1}
    curr = make_obs(price_cents=2800, available=False)  # dropped price & went out of stock

    events = detect(prev, curr, min_change_cents=50)
    assert len(events) == 2

    types = [e["event_type"] for e in events]
    assert "price_drop" in types
    assert "out_of_stock" in types

    price_ev = next(e for e in events if e["event_type"] == "price_drop")
    assert price_ev["old_value"] == 3500
    assert price_ev["new_value"] == 2800

    stock_ev = next(e for e in events if e["event_type"] == "out_of_stock")
    assert stock_ev["old_value"] == 1
    assert stock_ev["new_value"] == 0


def test_detect_price_none():
    """Test that when price is None in previous or current, price comparison is skipped."""
    # 1. previous has price=None
    prev_none = {"price_cents": None, "available": 1}
    curr1 = make_obs(price_cents=2500, available=1)
    assert detect(prev_none, curr1, min_change_cents=0) == []

    # 2. current has price=None
    prev2 = {"price_cents": 2500, "available": 1}
    curr2 = make_obs(price_cents=None, available=1)
    assert detect(prev2, curr2, min_change_cents=0) == []

    # 3. current has price=None but stock changed (1 -> 0)
    curr3 = make_obs(price_cents=None, available=False)
    events = detect(prev2, curr3, min_change_cents=0)
    assert len(events) == 1
    assert events[0]["event_type"] == "out_of_stock"
