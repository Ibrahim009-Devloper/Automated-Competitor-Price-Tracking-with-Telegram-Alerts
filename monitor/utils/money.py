import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Union


def parse_price(
    text: Optional[Union[str, int, float, Decimal]],
    locale_hint: Optional[str] = None,
) -> Optional[int]:
    """Parse a price string or number with locale support into integer cents.

    Handles diverse global e-commerce price patterns:
        - "1.299,00 €"  -> 129900 (European: dot thousand, comma decimal)
        - "£1,299.00"   -> 129900 (UK/US: comma thousand, dot decimal)
        - "$1 299"      -> 129900 (Space thousand separator)
        - "1 299,50 €"  -> 129950 (Space thousand, comma decimal)
        - "29,99 €"     -> 2999   (Comma decimal)
        - "$29.99"      -> 2999   (Dot decimal)
        - 34.50         -> 3450   (Numeric float/int/Decimal)

    Args:
        text: Raw price text, number, or None.
        locale_hint: Optional locale string (e.g., 'de', 'eu', 'fr', 'en', 'EUR', 'USD')
                     to help disambiguate single-separator formats.

    Returns:
        Integer cents (e.g. 129900) or None if price cannot be parsed.
        Never returns 0 for missing or unparseable values.
    """
    if text is None:
        return None

    # If already a number or Decimal, convert directly
    if isinstance(text, (int, float, Decimal)):
        try:
            d = Decimal(str(text))
            return int((d * Decimal("100")).quantize(Decimal("1")))
        except (InvalidOperation, ValueError, TypeError):
            return None

    raw_str = str(text).strip()
    if not raw_str:
        return None

    # Replace non-breaking spaces (\xa0, etc.) with standard spaces
    normalized = re.sub(r"[\s\xa0\u202f]+", " ", raw_str).strip()

    # Strip currency symbols and letters (e.g. $, €, £, ¥, CHF, USD, EUR)
    # Keep only digits, dots, commas, minus sign, and spaces
    clean = re.sub(r"[^\d.,\- ]", "", normalized).strip()
    if not clean:
        return None

    # Determine if negative
    is_negative = clean.startswith("-")
    if is_negative:
        clean = clean[1:].strip()

    hint = (locale_hint or "").strip().lower()
    is_euro_hint = any(h in hint for h in ("de", "fr", "es", "it", "eu", "eur"))

    has_dot = "." in clean
    has_comma = "," in clean
    has_space = " " in clean

    if has_dot and has_comma:
        dot_idx = clean.rfind(".")
        comma_idx = clean.rfind(",")
        if dot_idx < comma_idx:
            # Format: "1.299,00" -> European (dot thousands, comma decimals)
            clean = clean.replace(" ", "").replace(".", "").replace(",", ".")
        else:
            # Format: "1,299.00" -> US/UK (comma thousands, dot decimals)
            clean = clean.replace(" ", "").replace(",", "")
    elif has_comma:
        # Only comma exists (e.g. "29,99" or "1 299,50" or "1,299")
        parts = clean.split(",")
        last_part = parts[-1].strip()
        # If followed by 2 decimals (e.g. "29,99"), or euro locale hint, comma is decimal
        if len(last_part) == 2 or is_euro_hint:
            clean = clean.replace(" ", "").replace(",", ".")
        elif len(last_part) == 3 and len(parts) > 1 and not is_euro_hint:
            # Format "1,299" in US/UK is thousand separator
            clean = clean.replace(" ", "").replace(",", "")
        else:
            clean = clean.replace(" ", "").replace(",", ".")
    elif has_dot:
        # Only dot exists (e.g. "29.99" or "1.299" with euro hint)
        parts = clean.split(".")
        last_part = parts[-1].strip()
        if len(last_part) == 3 and is_euro_hint:
            # "1.299" in German/EU format is thousands separator
            clean = clean.replace(" ", "").replace(".", "")
        else:
            clean = clean.replace(" ", "")
    else:
        # No dot or comma, only spaces or digits (e.g. "$1 299")
        clean = clean.replace(" ", "")

    try:
        d = Decimal(clean)
        cents = int((d * Decimal("100")).quantize(Decimal("1")))
        return -cents if is_negative else cents
    except (InvalidOperation, ValueError, TypeError):
        return None


def to_cents(price: Optional[Union[str, int, float, Decimal]]) -> Optional[int]:
    """Convert a price value to integer cents using Decimal to prevent floating point inaccuracies.

    Supported inputs include numeric strings (e.g., '236.00', '1299.5', '$19.99'),
    floats, ints, and Decimal objects. If price is None, empty, or cannot be parsed,
    returns None.

    Args:
        price: Price string, number, or None.

    Returns:
        Integer cents (e.g., 23600 for '236.00', 129950 for '1299.5') or None.
    """
    return parse_price(price)


def cents_to_str(cents: Optional[int], currency_symbol: str = "$") -> str:
    """Format integer cents into a display price string (e.g., 23600 -> '$236.00').

    Args:
        cents: Amount in cents, or None.
        currency_symbol: Prefix symbol for currency (default '$').

    Returns:
        Formatted price string or 'N/A' if cents is None.
    """
    if cents is None:
        return "N/A"
    dollars = Decimal(cents) / Decimal("100")
    return f"{currency_symbol}{dollars:.2f}"
