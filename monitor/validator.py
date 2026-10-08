"""Observation validator for the price monitoring pipeline.

Validates that extracted product observations meet quality thresholds before
they are saved to the database or evaluated for change events and alerts.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from monitor.models import Observation

logger = logging.getLogger(__name__)


def validate(
    observation: Observation,
    previous: Optional[Dict[str, Any]] = None,
    suspicious_change_percent: Optional[float] = None,
) -> Tuple[bool, str]:
    """Validate an observation against data completeness and sanity rules.

    An Observation is INVALID if:
      1. Product title is empty or placeholder ('Unknown Product').
      2. price_cents is None or <= 0.
      3. variant_id is missing or empty string.
      4. Price changed by more than the configured suspicious_change_percent
         compared with the previous check (held for confirmation).

    Args:
        observation: The freshly scraped Observation model.
        previous: Optional previous price_check record (dict or object) for this variant.
        suspicious_change_percent: Optional percentage threshold (e.g., 80.0) above which
                                   a price jump is deemed suspicious.

    Returns:
        Tuple[bool, str]: (True, "") if observation is valid,
                          (False, reason) if invalid.
    """
    # 1. Title validation
    title = (observation.product_title or "").strip()
    if not title or title.lower() == "unknown product":
        return False, "Product title is empty"

    # 2. Variant ID validation
    variant_id = str(observation.variant_id or "").strip()
    if not variant_id:
        return False, "Variant ID is missing"

    # 3. Price validation (never None or <= 0)
    if observation.price_cents is None:
        return False, "Price is missing (None)"
    if observation.price_cents <= 0:
        return False, f"Price is invalid ({observation.price_cents} <= 0)"

    # 4. Suspicious price change validation
    if (
        previous is not None
        and suspicious_change_percent is not None
        and suspicious_change_percent > 0
    ):
        prev_cents = (
            previous.get("price_cents")
            if isinstance(previous, dict)
            else getattr(previous, "price_cents", None)
        )
        if prev_cents is not None and prev_cents > 0:
            diff = abs(observation.price_cents - prev_cents)
            change_pct = (diff / prev_cents) * 100.0
            if change_pct > suspicious_change_percent:
                return (
                    False,
                    f"Suspicious price change of {change_pct:.1f}% exceeds threshold of {suspicious_change_percent}% (held for confirmation)",
                )

    return True, ""
