"""Change detection logic for price drops, increases, and stock status changes."""

from typing import Any, Dict, List, Optional, Union
from monitor.models import Observation


def detect(
    previous: Optional[Union[Dict[str, Any], Any]],
    current: Observation,
    min_change_cents: int = 0,
) -> List[Dict[str, Any]]:
    """Pure function that compares a previous price check with a current observation.

    Detects:
      1. 'new_variant'    : When previous is None.
      2. 'price_drop'     : When current price < previous price by at least min_change_cents.
      3. 'price_increase' : When current price > previous price by at least min_change_cents.
      4. 'out_of_stock'   : When availability drops from 1 (in stock) to 0 (out of stock).
      5. 'back_in_stock'  : When availability rises from 0 (out of stock) to 1 (in stock).

    Notes:
      - If price is None in either previous or current, price comparison is skipped.
      - A price change and a stock change in the same check produce separate events.
      - Never mutates input arguments.

    Args:
        previous: Previous price check record dictionary/Row (or None if first check).
        current: Current Observation object.
        min_change_cents: Minimum threshold in cents required to trigger price events (default: 0).

    Returns:
        List of event dictionaries with keys:
        variant_id, detected_at, event_type, old_value, new_value, product_title, variant_title, site.
    """
    # Safe ISO timestamp from current observation
    detected_at = (
        current.fetched_at.isoformat()
        if hasattr(current.fetched_at, "isoformat")
        else str(current.fetched_at)
    )

    # Clean variant_id as integer if purely digits, else string
    val_id = (
        int(current.variant_id)
        if str(current.variant_id).isdigit()
        else current.variant_id
    )

    # Case 1: First time we see this variant -> 'new_variant' event
    if previous is None:
        return [
            {
                "variant_id": val_id,
                "detected_at": detected_at,
                "event_type": "new_variant",
                "old_value": None,
                "new_value": current.price_cents,
                "product_title": current.product_title,
                "variant_title": current.variant_title,
                "site": current.site,
            }
        ]

    events: List[Dict[str, Any]] = []

    # Safely extract previous price and availability whether previous is dict or sqlite3.Row
    prev_price = (
        previous.get("price_cents")
        if isinstance(previous, dict)
        else previous["price_cents"]
    )
    prev_avail_val = (
        previous.get("available")
        if isinstance(previous, dict)
        else previous["available"]
    )
    prev_available = 1 if prev_avail_val else 0

    curr_price = current.price_cents
    curr_available = 1 if current.available else 0

    # -------------------------------------------------------------------------
    # 1. Price comparison
    # Rule: If price is None in either, skip price comparison.
    # -------------------------------------------------------------------------
    if prev_price is not None and curr_price is not None:
        price_diff = curr_price - prev_price

        if price_diff < 0:
            # Price decreased: check if it meets the minimum change threshold
            drop_amount = abs(price_diff)
            if drop_amount >= min_change_cents:
                events.append(
                    {
                        "variant_id": val_id,
                        "detected_at": detected_at,
                        "event_type": "price_drop",
                        "old_value": prev_price,
                        "new_value": curr_price,
                        "product_title": current.product_title,
                        "variant_title": current.variant_title,
                        "site": current.site,
                    }
                )
        elif price_diff > 0:
            # Price increased: check if it meets the minimum change threshold
            increase_amount = price_diff
            if increase_amount >= min_change_cents:
                events.append(
                    {
                        "variant_id": val_id,
                        "detected_at": detected_at,
                        "event_type": "price_increase",
                        "old_value": prev_price,
                        "new_value": curr_price,
                        "product_title": current.product_title,
                        "variant_title": current.variant_title,
                        "site": current.site,
                    }
                )

    # -------------------------------------------------------------------------
    # 2. Stock status comparison
    # Rule: 1 -> 0 is out_of_stock; 0 -> 1 is back_in_stock.
    # -------------------------------------------------------------------------
    if prev_available == 1 and curr_available == 0:
        events.append(
            {
                "variant_id": val_id,
                "detected_at": detected_at,
                "event_type": "out_of_stock",
                "old_value": 1,
                "new_value": 0,
                "product_title": current.product_title,
                "variant_title": current.variant_title,
                "site": current.site,
            }
        )
    elif prev_available == 0 and curr_available == 1:
        events.append(
            {
                "variant_id": val_id,
                "detected_at": detected_at,
                "event_type": "back_in_stock",
                "old_value": 0,
                "new_value": 1,
                "product_title": current.product_title,
                "variant_title": current.variant_title,
                "site": current.site,
            }
        )

    return events
