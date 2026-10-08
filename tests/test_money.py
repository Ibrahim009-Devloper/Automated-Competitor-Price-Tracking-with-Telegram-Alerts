"""Unit tests for money conversion utility."""

import pytest
from decimal import Decimal
from monitor.utils.money import cents_to_str, parse_price, to_cents


def test_parse_price_locales():
    """Test parse_price with different global locale formats required by Rule 3."""
    # European dot thousand, comma decimal: "1.299,00 €"
    assert parse_price("1.299,00 €") == 129900
    assert parse_price("1.299,00 €", locale_hint="de") == 129900

    # UK/US pound with comma thousand: "£1,299.00"
    assert parse_price("£1,299.00") == 129900
    assert parse_price("£1,299.00", locale_hint="en") == 129900

    # Space thousand separator: "$1 299"
    assert parse_price("$1 299") == 129900
    assert parse_price("1 299,50 €") == 129950

    # Simple comma decimal
    assert parse_price("29,99 €") == 2999
    assert parse_price("29,99", locale_hint="fr") == 2999

    # Standard dot decimal
    assert parse_price("$29.99") == 2999
    assert parse_price("34.0") == 3400

    # None, empty, invalid
    assert parse_price(None) is None
    assert parse_price("") is None
    assert parse_price("Free") is None
    assert parse_price("unavailable") is None



def test_to_cents_standard_string():
    """Test standard price string conversion."""
    assert to_cents("236.00") == 23600
    assert to_cents("19.99") == 1999
    assert to_cents("0.99") == 99
    assert to_cents("0.05") == 5


def test_to_cents_single_decimal():
    """Test price strings with single decimal place."""
    assert to_cents("1299.5") == 129950
    assert to_cents("10.5") == 1050


def test_to_cents_integers_and_floats():
    """Test integer, float, and Decimal inputs."""
    assert to_cents(25) == 2500
    assert to_cents(25.5) == 2550
    assert to_cents(Decimal("14.95")) == 1495


def test_to_cents_currency_and_separators():
    """Test handling of dollar signs and comma thousand separators."""
    assert to_cents("$236.00") == 23600
    assert to_cents("$1,299.50") == 129950


def test_to_cents_zero():
    """Test zero price conversion."""
    assert to_cents("0") == 0
    assert to_cents("0.00") == 0
    assert to_cents(0) == 0


def test_to_cents_none_and_empty():
    """Test that None or empty inputs return None."""
    assert to_cents(None) is None
    assert to_cents("") is None
    assert to_cents("   ") is None


def test_to_cents_invalid_string():
    """Test that invalid non-numeric inputs return None instead of crashing."""
    assert to_cents("not_a_price") is None
    assert to_cents("abc") is None
    assert to_cents("$$$") is None


def test_cents_to_str():
    """Test formatting cents back to human-readable string."""
    assert cents_to_str(23600) == "$236.00"
    assert cents_to_str(129950) == "$1299.50"
    assert cents_to_str(99) == "$0.99"
    assert cents_to_str(None) == "N/A"
