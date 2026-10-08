"""Shopify store adapter using the public /products.json endpoint."""

from datetime import datetime, timezone
import json
import logging
import random
import time
from typing import Any, Dict, List, Optional, Tuple
import requests

from monitor.adapters.base import SiteAdapter
from monitor.models import FetchResult, Observation
from monitor.utils.http import HttpError, http_get, parse_json_safely
from monitor.utils.money import to_cents

logger = logging.getLogger(__name__)


class ShopifyAdapter(SiteAdapter):
    """Adapter to fetch and parse products from Shopify stores via /products.json."""

    PAGE_LIMIT: int = 250

    def parse_products_data(
        self, data: Dict[str, Any], fetched_at: Optional[datetime] = None
    ) -> List[Observation]:
        """Parse raw Shopify products JSON dictionary into a list of Observation models.

        Args:
            data: Parsed JSON payload containing a 'products' list.
            fetched_at: Timestamp to assign to observations (defaults to now in UTC).

        Returns:
            List[Observation]: Extracted variant observations.
        """
        if fetched_at is None:
            fetched_at = datetime.now(timezone.utc)

        observations: List[Observation] = []
        products = data.get("products")
        if products is None and "product" in data and isinstance(data["product"], dict):
            products = [data["product"]]
        elif not isinstance(products, list):
            return observations

        for product in products:
            if not isinstance(product, dict):
                continue

            product_id = str(product.get("id", ""))
            product_title = str(product.get("title", "")).strip()
            handle = product.get("handle", "")

            variants = product.get("variants", [])
            if not isinstance(variants, list):
                continue

            for variant in variants:
                if not isinstance(variant, dict):
                    continue

                variant_id = str(variant.get("id", ""))
                variant_title = str(variant.get("title", "")).strip()

                # Extract prices using Decimal-based converter; never guess 0 if missing
                price_val = variant.get("price")
                compare_val = variant.get("compare_at_price")

                price_cents = to_cents(price_val)
                compare_at_cents = to_cents(compare_val)

                available = bool(variant.get("available", False))

                # Construct direct variant URL
                if handle:
                    url = f"{self.base_url}/products/{handle}?variant={variant_id}"
                else:
                    url = f"{self.base_url}"

                obs = Observation(
                    site=self.site_name,
                    product_id=product_id,
                    variant_id=variant_id,
                    product_title=product_title,
                    variant_title=variant_title,
                    price_cents=price_cents,
                    compare_at_cents=compare_at_cents,
                    currency=self.currency,
                    available=available,
                    url=url,
                    fetched_at=fetched_at,
                )
                observations.append(obs)

        return observations

    def _fetch_generic_products_json(
        self, store_origin: str, run_timestamp: datetime
    ) -> Tuple[Optional[List[Observation]], Optional[str]]:
        """Attempt generic Shopify /products.json pagination.

        Validates HTTP status, Content-Type, and JSON format safely before parsing.

        Args:
            store_origin: Store base origin URL (e.g. 'https://sokoglam.com').
            run_timestamp: Run timestamp.

        Returns:
            Tuple of (observations_list, error_message).
            observations_list is None if page 1 failed or returned non-JSON / empty.
        """
        page = 1
        all_observations: List[Observation] = []
        endpoint = f"{store_origin}/products.json"

        while True:
            if page > 1 and self.delay_range[1] > 0:
                sleep_sec = random.uniform(self.delay_range[0], self.delay_range[1])
                logger.debug("Sleeping %.2fs between requests", sleep_sec)
                time.sleep(sleep_sec)

            params = {
                "limit": self.PAGE_LIMIT,
                "page": page,
            }

            try:
                response = http_get(endpoint, params=params)
            except HttpError as err:
                msg = f"[{self.site_name}] HTTP error on page {page}: {err}"
                logger.debug(msg)
                if page == 1:
                    return None, msg
                break
            except Exception as err:
                msg = f"[{self.site_name}] Request error on page {page}: {err}"
                logger.debug(msg)
                if page == 1:
                    return None, msg
                break

            # Response validation before calling .json()
            payload = parse_json_safely(response)
            if payload is None or not isinstance(payload, dict):
                msg = f"[{self.site_name}] Invalid or non-JSON response from {endpoint} on page {page}"
                logger.debug(msg)
                if page == 1:
                    return None, msg
                break

            products = payload.get("products", [])
            if not isinstance(products, list) or not products:
                if page == 1:
                    return None, f"[{self.site_name}] Empty products list on page 1"
                break

            page_observations = self.parse_products_data(payload, fetched_at=run_timestamp)
            all_observations.extend(page_observations)

            logger.info(
                "[%s] Page %d: fetched %d products (%d variants)",
                self.site_name,
                page,
                len(products),
                len(page_observations),
            )

            if len(products) < self.PAGE_LIMIT:
                break

            page += 1

        return all_observations, None

    def fetch(self) -> FetchResult:
        """Fetch all product observations using Shopify /products.json with multi-level fallback.

        Executes multi-level fallback strategy:
        1. Existing Shopify /products.json strategy
        2. Handle-based Shopify JSON (/products.json?handle=<handle>)
        3. JSON-LD fallback
        4. HTML/DOM fallback (static first, Playwright only if JS-rendered)
        5. Graceful failure

        Returns:
            FetchResult: Contains parsed observations and any warning/error messages.
        """
        from monitor.fallback import fetch_with_fallback
        return fetch_with_fallback(self)

    def load_target_urls(self) -> List[Dict[str, str]]:
        """Load target product URLs for this store from config or targets.csv.

        Returns:
            List of dictionaries with 'url' and 'product_group'.
        """
        from monitor.fallback import get_target_urls_for_site
        urls = get_target_urls_for_site(self.site_config, self.site_name, self.base_url)
        return [{"url": u, "product_group": ""} for u in urls]

