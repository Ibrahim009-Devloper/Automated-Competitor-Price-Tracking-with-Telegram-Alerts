"""Data models for price monitoring."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Observation:
    """Represents a single price snapshot of a product variant at a point in time.

    Attributes:
        site: Identifier or friendly name of the store (e.g., 'Paula's Choice').
        product_id: Unique identifier of the product on the site.
        variant_id: Unique identifier of the specific variant/size/color.
        product_title: Full title of the product.
        variant_title: Title/name of the specific variant (e.g., '100ml', 'Default Title').
        price_cents: Current selling price in integer cents (e.g., 23600 for $236.00), or None if missing.
        compare_at_cents: Original or strikethrough price in integer cents, or None if not on sale.
        currency: Three-letter ISO currency code (e.g., 'USD').
        available: Boolean indicating if the variant is in stock.
        url: Full direct link to the product or variant page.
        fetched_at: UTC datetime when this observation was scraped.
    """

    site: str
    product_id: str
    variant_id: str
    product_title: str
    variant_title: str
    price_cents: Optional[int]
    compare_at_cents: Optional[int]
    currency: str
    available: bool
    url: str
    fetched_at: datetime


VALID_ERROR_TYPES = (
    "timeout",
    "network",
    "http_5xx",
    "rate_limited",
    "blocked",
    "not_found",
    "parse_error",
    "validation_failed",
)


@dataclass
class ErrorRecord:
    """Classified error record capturing failure type and context.

    Attributes:
        error_type: Classification string (timeout, network, http_5xx, rate_limited,
                    blocked, not_found, parse_error, validation_failed).
        message: Human-readable error description.
        url: URL that failed, if applicable.
        site: Store identifier, if applicable.
        timestamp: When the error occurred (UTC).
    """

    error_type: str
    message: str
    url: Optional[str] = None
    site: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class FetchResult:
    """Result returned by a SiteAdapter fetch operation.

    Attributes:
        observations: List of all valid Observation items collected.
        errors: List of human-readable error or warning messages encountered during the fetch.
        error_records: List of structured ErrorRecord items with classified error_type.
        confirmed_absent_variant_ids: Variant IDs confirmed absent (404/410 or missing from full catalog).
    """

    observations: List[Observation] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    error_records: List[ErrorRecord] = field(default_factory=list)
    confirmed_absent_variant_ids: List[str] = field(default_factory=list)
    is_full_catalog_fetch: bool = False

    def add_error(
        self,
        error_type: str,
        message: str,
        url: Optional[str] = None,
        site: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Helper to append an error to both legacy string errors and structured error_records."""
        if error_type not in VALID_ERROR_TYPES:
            # Fall back to parse_error or network if an unknown type is passed
            error_type = "parse_error"
        self.errors.append(message)
        self.error_records.append(
            ErrorRecord(
                error_type=error_type,
                message=message,
                url=url,
                site=site,
                timestamp=timestamp,
            )
        )
