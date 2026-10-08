"""JSON-LD Schema.org product page adapter.

This adapter fetches individual product pages via HTTP requests, parses Schema.org
JSON-LD (<script type="application/ld+json">) structured data, and converts
Product and Offer objects into unified Observation models.
"""

import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import random
import re
import time
from typing import Any, Dict, Generator, List, Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from monitor.adapters.base import SiteAdapter
from monitor.models import FetchResult, Observation
from monitor.utils.http import HttpError, http_get
from monitor.utils.money import parse_price

logger = logging.getLogger(__name__)


class JsonLdAdapter(SiteAdapter):
    """Adapter for e-commerce stores that expose Schema.org JSON-LD on product pages."""

    def __init__(self, site_config: Dict[str, Any]) -> None:
        """Initialize JSON-LD adapter with settings from sites.yaml.

        Args:
            site_config: Configuration dict containing site settings, targets path,
                         and configurable JSON-LD field names / selectors.
        """
        super().__init__(site_config)

        # Configurable field names from sites.yaml (never hardcoded, Rule 9)
        self.jsonld_type: str = site_config.get("jsonld_type", "Product")
        self.offers_field: str = site_config.get("offers_field", "offers")
        self.price_field: str = site_config.get("price_field", "price")
        self.currency_field: str = site_config.get("currency_field", "priceCurrency")
        self.availability_field: str = site_config.get("availability_field", "availability")

        # HTTP request settings
        self.timeout: int = int(site_config.get("timeout", 20))
        self.max_retries: int = int(site_config.get("max_retries", 3))
        self.targets_path: str = site_config.get("targets_path", "config/targets.csv")

    def load_target_urls(self) -> List[Dict[str, str]]:
        """Load target product URLs for this store from config/targets.csv.

        Returns:
            List of dictionaries containing 'url' and optional 'product_group'.
        """
        # If URLs are provided directly in site_config, allow that as an option
        direct_urls = self.site_config.get("urls", [])
        if direct_urls:
            return [{"url": u, "product_group": ""} for u in direct_urls]

        csv_file = Path(self.targets_path)
        if not csv_file.exists():
            logger.warning("Targets file not found: %s", csv_file)
            return []

        targets: List[Dict[str, str]] = []
        seen_urls = set()
        try:
            with open(csv_file, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    site_name = (row.get("site") or "").strip()
                    # Match site name against current adapter site
                    if site_name.lower() == self.site_name.lower():
                        url = (row.get("url") or "").strip()
                        product_group = (row.get("product_group") or "").strip()

                        # Fallback: if url empty but product_handle provided, construct standard url
                        if not url and row.get("product_handle"):
                            handle = row["product_handle"].strip()
                            url = f"{self.base_url}/products/{handle}"

                        if url:
                            # Handle relative URLs
                            if url.startswith("/"):
                                url = f"{self.base_url}{url}"

                            # Requirement 5: Log a warning if the same URL appears twice and process once
                            normalized_url = url.split("?")[0].rstrip("/").lower()
                            if normalized_url in seen_urls:
                                logger.warning(
                                    "[%s] Duplicate URL found in %s: '%s'. Processing once.",
                                    self.site_name,
                                    csv_file,
                                    url,
                                )
                                continue

                            seen_urls.add(normalized_url)
                            targets.append({"url": url, "product_group": product_group})
        except Exception as exc:
            logger.error("Error reading targets from %s: %s", csv_file, exc)

        return targets

    def _find_products(self, obj: Any) -> Generator[Dict[str, Any], None, None]:
        """Recursively scan JSON-LD data to find all objects of type 'Product'.

        Handles dicts, lists, @graph arrays, and multiple @type declarations.

        Args:
            obj: Parsed JSON object (dict, list, or scalar).

        Yields:
            Dict[str, Any]: Dictionary representing a Product object.
        """
        if isinstance(obj, dict):
            type_val = obj.get("@type")
            is_product = False
            target_type = self.jsonld_type.lower()

            if isinstance(type_val, str) and type_val.lower() == target_type:
                is_product = True
            elif isinstance(type_val, list) and any(
                isinstance(t, str) and t.lower() == target_type for t in type_val
            ):
                is_product = True

            if is_product:
                yield obj

            # Recursively explore nested structures (such as @graph or arrays)
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    yield from self._find_products(value)

        elif isinstance(obj, list):
            for item in obj:
                yield from self._find_products(item)

    def parse_availability(self, availability_raw: Any) -> Optional[bool]:
        """Convert Schema.org availability URL or string to boolean.

        Examples:
            'https://schema.org/InStock' -> True
            'https://schema.org/OutOfStock' -> False
            'https://schema.org/SoldOut' -> False
            'InStock' -> True
            None / unknown -> None (Rule 2: Never guess)

        Args:
            availability_raw: Raw availability string or URL.

        Returns:
            Optional[bool]: True for available, False for out of stock, None if cannot be determined.
        """
        if not availability_raw:
            return None

        val = str(availability_raw).strip()
        if "InStock" in val or "PreOrder" in val or "InStoreOnly" in val:
            return True
        elif "OutOfStock" in val or "SoldOut" in val or "Discontinued" in val:
            return False
        return None

    def parse_html(
        self,
        html_text: str,
        page_url: str,
        fetched_at: Optional[datetime] = None,
        errors_out: Optional[List[str]] = None,
    ) -> List[Observation]:
        """Parse HTML string, extract JSON-LD, and build unified Observation models.

        Args:
            html_text: Raw HTML string of the product page.
            page_url: URL of the page being parsed.
            fetched_at: Optional timestamp (defaults to current UTC time).
            errors_out: Optional list to append non-fatal parsing errors/warnings to.

        Returns:
            List[Observation]: List of product/variant observations extracted from JSON-LD.
        """
        if fetched_at is None:
            fetched_at = datetime.now(timezone.utc)

        soup = BeautifulSoup(html_text, "html.parser")
        script_tags = soup.find_all("script", type="application/ld+json")

        if not script_tags:
            msg = f"No <script type='application/ld+json'> tags found on {page_url}"
            if errors_out is not None:
                errors_out.append(msg)
            return []

        products_found: List[Dict[str, Any]] = []
        for tag in script_tags:
            tag_content = tag.string or tag.get_text() or ""
            if not tag_content.strip():
                continue
            try:
                data = json.loads(tag_content)
                for prod in self._find_products(data):
                    products_found.append(prod)
            except json.JSONDecodeError:
                # Silently skip malformed JSON blocks that may be third-party analytics
                continue

        if not products_found:
            msg = f"No JSON-LD '{self.jsonld_type}' object found on {page_url}"
            if errors_out is not None:
                errors_out.append(msg)
            return []

        observations: List[Observation] = []

        for prod in products_found:
            product_title = str(prod.get("name") or prod.get("title") or "").strip()
            if not product_title:
                product_title = "Unknown Product"

            # Derive product ID from SKU, productID, @id, or URL
            product_id = str(
                prod.get("sku")
                or prod.get("productID")
                or prod.get("@id")
                or page_url
            ).strip()

            # Extract raw offers using configured field name
            offers_raw = prod.get(self.offers_field)
            offers_list: List[Dict[str, Any]] = []

            if isinstance(offers_raw, list):
                offers_list = [o for o in offers_raw if isinstance(o, dict)]
            elif isinstance(offers_raw, dict):
                # Handle AggregateOffer which may wrap a list of offers
                if offers_raw.get("@type") == "AggregateOffer" and isinstance(
                    offers_raw.get("offers"), list
                ):
                    offers_list = [o for o in offers_raw["offers"] if isinstance(o, dict)]
                else:
                    offers_list = [offers_raw]

            # If no offers are provided, record missing data per Rule 2
            if not offers_list:
                msg = f"No offers found for product '{product_title}' on {page_url}"
                if errors_out is not None:
                    errors_out.append(msg)
                obs = Observation(
                    site=self.site_name,
                    product_id=product_id,
                    variant_id=product_id,
                    product_title=product_title,
                    variant_title="Default Title",
                    price_cents=None,
                    compare_at_cents=None,
                    currency=self.currency,
                    available=None,
                    url=page_url,
                    fetched_at=fetched_at,
                )
                observations.append(obs)
                continue

            # Variant handling: produce one Observation per offer/variant (Rule 7)
            for idx, offer in enumerate(offers_list, 1):
                # Read price using configured field name; fallback to lowPrice for aggregate
                raw_price = offer.get(self.price_field)
                if raw_price is None and offer.get("lowPrice") is not None:
                    raw_price = offer.get("lowPrice")

                # Parse price with locale awareness (Rule 3)
                price_cents = parse_price(raw_price, locale_hint=self.currency)

                # Never store 0 for a missing price (Rule 2)
                if price_cents is None and raw_price is not None:
                    msg = f"Could not parse price '{raw_price}' for '{product_title}' on {page_url}"
                    if errors_out is not None:
                        errors_out.append(msg)

                # Read currency from offer or fallback to site config
                offer_currency = offer.get(self.currency_field) or self.currency

                # Read availability
                raw_avail = offer.get(self.availability_field)
                available = self.parse_availability(raw_avail)

                # Variant ID extraction (from SKU, @id, variant query param, or offer URL)
                offer_url = offer.get("url") or page_url
                if offer_url.startswith("/"):
                    offer_url = f"{self.base_url}{offer_url}"

                variant_id: str = ""
                # Check for query param 'variant=...'
                parsed_url = urlparse(offer_url)
                qs = parse_qs(parsed_url.query)
                if "variant" in qs and qs["variant"]:
                    variant_id = qs["variant"][0]
                elif offer.get("sku"):
                    variant_id = str(offer.get("sku"))
                elif offer.get("@id"):
                    # Check if @id contains a variant identifier
                    raw_id = str(offer.get("@id"))
                    match = re.search(r"variant[=_](\d+)", raw_id)
                    if match:
                        variant_id = match.group(1)
                    else:
                        variant_id = raw_id
                else:
                    variant_id = f"{product_id}-{idx}" if len(offers_list) > 1 else product_id

                # Variant title
                variant_title = str(
                    offer.get("name")
                    or offer.get("title")
                    or (f"Variant {idx}" if len(offers_list) > 1 else "Default Title")
                ).strip()

                # Optional compare-at price
                compare_raw = (
                    offer.get("priceSpecification", {}).get("price")
                    if isinstance(offer.get("priceSpecification"), dict)
                    else offer.get("highPrice")
                )
                compare_at_cents = parse_price(compare_raw, locale_hint=self.currency)

                obs = Observation(
                    site=self.site_name,
                    product_id=product_id,
                    variant_id=str(variant_id),
                    product_title=product_title,
                    variant_title=variant_title,
                    price_cents=price_cents,
                    compare_at_cents=compare_at_cents,
                    currency=offer_currency,
                    available=available,
                    url=offer_url,
                    fetched_at=fetched_at,
                )
                observations.append(obs)

        return observations

    def fetch(self) -> FetchResult:
        """Fetch all configured target product pages and extract observations.

        Respects rate-limiting delays with random jitter (Rule 4).
        Stops on 403/429/captchas (Rule 5).
        Continues past single-page errors (Rule 6).

        Returns:
            FetchResult: Unified observation list and any errors encountered.
        """
        result = FetchResult()
        targets = self.load_target_urls()

        if not targets:
            logger.warning(
                "[%s] No target URLs found in %s for site '%s'",
                self.site_name,
                self.targets_path,
                self.site_name,
            )
            return result

        run_timestamp = datetime.now(timezone.utc)
        logger.info(
            "Starting JSON-LD fetch for '%s': %d product page(s) to process",
            self.site_name,
            len(targets),
        )

        for idx, target_info in enumerate(targets):
            url = target_info["url"]

            # Throttle between page requests with random jitter (Rule 4)
            if idx > 0 and self.delay_range[1] > 0:
                base_sleep = random.uniform(self.delay_range[0], self.delay_range[1])
                jitter = random.uniform(0.1, 0.5)
                total_sleep = base_sleep + jitter
                logger.debug("[%s] Sleeping %.2fs (with jitter) before next URL", self.site_name, total_sleep)
                time.sleep(total_sleep)

            try:
                response = http_get(
                    url=url,
                    timeout=self.timeout,
                    max_retries=self.max_retries,
                    headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
                )

                # Check for captcha or bot challenge blocks in HTML (Rule 5)
                html_lower = response.text.lower()
                if (
                    "cf-challenge" in html_lower
                    or "challenge-platform" in html_lower
                    or "<title>just a moment...</title>" in html_lower
                    or "attention required! | cloudflare" in html_lower
                ):
                    block_err = f"blocked: captcha challenge detected on {url}"
                    logger.error("[%s] %s", self.site_name, block_err)
                    result.add_error("blocked", block_err, url=url, site=self.site_name)
                    # Stop requesting that site for this run (Rule 5)
                    break

                page_errors: List[str] = []
                observations = self.parse_html(
                    html_text=response.text,
                    page_url=url,
                    fetched_at=run_timestamp,
                    errors_out=page_errors,
                )

                if page_errors:
                    for pe in page_errors:
                        result.add_error("parse_error", pe, url=url, site=self.site_name)

                result.observations.extend(observations)
                logger.info(
                    "[%s] Processed '%s': extracted %d observation(s)",
                    self.site_name,
                    url,
                    len(observations),
                )

            except HttpError as http_err:
                # Rule 1: 404/410 is confirmed absence
                if http_err.status_code in (404, 410):
                    err_msg = f"not_found: HTTP {http_err.status_code} on {url}"
                    logger.warning("[%s] %s", self.site_name, err_msg)
                    result.add_error("not_found", err_msg, url=url, site=self.site_name)
                    result.confirmed_absent_variant_ids.append(url)
                    continue
                # Rule 5: If blocked by 403 or 429, stop requesting that site for this run
                elif http_err.status_code in (401, 403) or getattr(http_err, "error_type", None) == "blocked":
                    err_msg = f"blocked: HTTP {http_err.status_code} on {url}"
                    logger.error("[%s] %s", self.site_name, err_msg)
                    result.add_error("blocked", err_msg, url=url, site=self.site_name)
                    break
                elif http_err.status_code == 429 or getattr(http_err, "error_type", None) == "rate_limited":
                    err_msg = f"rate_limited: HTTP 429 on {url}"
                    logger.error("[%s] %s", self.site_name, err_msg)
                    result.add_error("rate_limited", err_msg, url=url, site=self.site_name)
                    break
                else:
                    # Rule 6: One failing product URL must not stop the rest of that site
                    err_type = getattr(http_err, "error_type", "network")
                    err_msg = f"Failed to fetch {url}: {http_err}"
                    logger.warning("[%s] %s", self.site_name, err_msg)
                    result.add_error(err_type, err_msg, url=url, site=self.site_name)
                    continue

            except Exception as exc:
                # Rule 6: Continue with other URLs on unexpected single-product exceptions
                err_msg = f"Error processing {url}: {exc}"
                logger.exception("[%s] %s", self.site_name, err_msg)
                result.add_error("parse_error", err_msg, url=url, site=self.site_name)
                continue

        logger.info(
            "Finished JSON-LD fetch for '%s': %d observations collected, %d errors",
            self.site_name,
            len(result.observations),
            len(result.errors),
        )
        return result
