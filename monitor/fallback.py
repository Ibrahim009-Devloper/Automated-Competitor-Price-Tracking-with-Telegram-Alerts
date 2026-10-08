"""Multi-level fallback strategy for e-commerce price extraction.

Provides an intelligent, resilient fallback layer for store monitoring:
1. Existing Shopify /products.json strategy (full catalog pagination)
2. Handle-based Shopify JSON (/products.json?handle=<handle> and /products/<handle>.json)
3. JSON-LD fallback (Schema.org structured data from static HTML)
4. HTML/DOM fallback (static HTML first, Playwright browser only if JS-rendered)
5. Graceful failure (records clear error without crashing the run)
"""

import csv
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from monitor.adapters.jsonld import JsonLdAdapter
from monitor.adapters.playwright import PlaywrightAdapter
from monitor.models import FetchResult, Observation
from monitor.utils.http import HttpError, http_get, parse_json_safely

logger = logging.getLogger(__name__)


def extract_product_handle(url: str) -> Optional[str]:
    """Extract product handle from a Shopify product URL.

    Examples:
        https://yanybeauty.co/products/mango-breeze-refreshing-eye-serum -> mango-breeze-refreshing-eye-serum
        https://sokoglam.com/products/serum-rc?variant=123 -> serum-rc

    Args:
        url: Full product URL or path.

    Returns:
        Product handle string or None if not found.
    """
    if not url:
        return None
    match = re.search(r"/products/([a-zA-Z0-9_\-]+)", url)
    if match:
        return match.group(1).strip()
    return None


def get_store_origin(url: str) -> str:
    """Extract store origin scheme and netloc from URL.

    Args:
        url: URL string (e.g. 'https://yanybeauty.co/products/eye-serum').

    Returns:
        Store origin string (e.g. 'https://yanybeauty.co').
    """
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return url.rstrip("/")


def get_target_urls_for_site(
    site_config: Dict[str, Any], site_name: str, base_url: str
) -> List[str]:
    """Collect target product URLs for a store from configuration and targets.csv.

    Sources:
    1. Direct 'urls' list in site_config.
    2. 'targets.csv' (or custom targets_path) rows matching site_name.
    3. 'base_url' if it directly points to a product path (/products/<handle>).

    Args:
        site_config: Store configuration dictionary.
        site_name: Store name.
        base_url: Configured store base URL.

    Returns:
        List of target product URL strings without duplicates.
    """
    urls: List[str] = []
    seen = set()

    def _add_url(u: str) -> None:
        clean = (u or "").strip()
        if clean:
            norm = clean.split("?")[0].rstrip("/").lower()
            if norm in seen:
                # Rule 5: Log a warning if duplicate URL encountered in targets
                logger.warning(
                    "[%s] Duplicate URL found: '%s'. Processing once.",
                    site_name,
                    clean,
                )
                return
            seen.add(norm)
            urls.append(clean)

    # 1. Direct URLs in config
    for u in site_config.get("urls", []):
        if isinstance(u, str):
            _add_url(u)

    # 2. targets.csv rows
    targets_path = site_config.get("targets_path", "config/targets.csv")
    csv_file = Path(targets_path)
    if csv_file.exists():
        try:
            with open(csv_file, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    s_name = (row.get("site") or "").strip()
                    if s_name.lower() == site_name.strip().lower():
                        u = (row.get("url") or "").strip()
                        if not u and row.get("product_handle"):
                            origin = get_store_origin(base_url)
                            u = f"{origin}/products/{row['product_handle'].strip()}"
                        if u:
                            _add_url(u)
        except Exception as exc:
            logger.debug("[%s] Error reading targets file %s: %s", site_name, csv_file, exc)

    # 3. base_url if it points to a specific product
    parsed = urlparse(base_url)
    if "/products/" in parsed.path:
        _add_url(base_url)

    return urls


def fetch_with_fallback(
    shopify_adapter: Any,
    run_timestamp: Optional[datetime] = None,
) -> FetchResult:
    """Execute the multi-level fallback strategy for a Shopify store adapter.

    Strategy order:
    1. Existing Shopify /products.json strategy
    2. Handle-based Shopify JSON (/products.json?handle=<handle>)
    3. JSON-LD fallback (<script type="application/ld+json">)
    4. HTML/DOM fallback (static HTML first, Playwright only if JS-rendered)
    5. Graceful failure (records clear error without crashing)

    Args:
        shopify_adapter: Instance of ShopifyAdapter.
        run_timestamp: Optional timestamp for observations.

    Returns:
        FetchResult: Collected observations and any non-fatal errors.
    """
    if run_timestamp is None:
        run_timestamp = datetime.now(timezone.utc)

    result = FetchResult()
    site_name = shopify_adapter.site_name
    site_config = shopify_adapter.site_config
    base_url = shopify_adapter.base_url
    store_origin = get_store_origin(base_url)

    # Find target URLs for fallback / direct monitoring
    target_urls = get_target_urls_for_site(site_config, site_name, base_url)

    # =========================================================================
    # Strategy 1: Existing Shopify /products.json strategy
    # =========================================================================
    # Skip store-wide catalog fetch when explicit direct URLs were requested (e.g. single URL inspection)
    has_explicit_direct_urls = bool(site_config.get("urls"))
    if not has_explicit_direct_urls:
        logger.info("[%s] Trying Shopify /products.json", site_name)

        generic_obs, generic_err = shopify_adapter._fetch_generic_products_json(
            store_origin=store_origin,
            run_timestamp=run_timestamp,
        )

        if generic_obs is not None and len(generic_obs) > 0:
            # Strategy 1 succeeded! Use existing parser results unchanged.
            result.observations.extend(generic_obs)
            result.is_full_catalog_fetch = True
            if generic_err:
                result.errors.append(generic_err)
            return result

        # Check if generic products.json failed due to rate limiting
        if generic_err and ("rate_limited" in generic_err.lower() or "429" in generic_err):
            err_msg = f"[{site_name}] Rate limited on products.json: {generic_err}"
            logger.error(err_msg)
            result.add_error("rate_limited", err_msg, site=site_name)
            return result

        # Generic /products.json failed or returned empty data
        logger.warning(
            "[%s] Generic Shopify JSON failed, trying handle-based endpoint",
            site_name,
        )
        if generic_err:
            logger.debug("[%s] Generic endpoint error: %s", site_name, generic_err)
    if not target_urls:
        err_msg = (
            f"[{site_name}] All price extraction strategies failed: "
            "generic /products.json failed and no target URLs configured for fallback"
        )
        logger.error(err_msg)
        result.errors.append(err_msg)
        return result

    # Process each target product through the fallback ladder
    for target_url in target_urls:
        attempted_strategies: List[str] = ["Shopify /products.json"]
        extracted_obs: List[Observation] = []

        # =====================================================================
        # Strategy 2: Handle-based Shopify JSON
        # =====================================================================
        handle = extract_product_handle(target_url)
        if handle:
            attempted_strategies.append("handle-based Shopify JSON")
            # Try /products.json?handle=<handle>
            handle_endpoint = f"{store_origin}/products.json"
            try:
                resp = http_get(
                    handle_endpoint,
                    params={"handle": handle},
                    timeout=15,
                    max_retries=2,
                )
                payload = parse_json_safely(resp)
                if payload and isinstance(payload, dict) and (payload.get("products") or payload.get("product")):
                    parsed = shopify_adapter.parse_products_data(payload, fetched_at=run_timestamp)
                    usable = [
                        o for o in parsed
                        if o.price_cents is not None and o.price_cents > 0 and o.product_title
                    ]
                    if usable:
                        logger.info(
                            "[%s] Handle-based Shopify JSON succeeded for %s",
                            site_name,
                            target_url,
                        )
                        extracted_obs = usable
            except Exception as exc:
                logger.debug("[%s] Handle endpoint failed on %s: %s", site_name, target_url, exc)

            # Secondary handle-based endpoint: /products/<handle>.json
            if not extracted_obs:
                single_endpoint = f"{store_origin}/products/{handle}.json"
                try:
                    resp = http_get(single_endpoint, timeout=15, max_retries=2)
                    payload = parse_json_safely(resp)
                    if payload and isinstance(payload, dict) and (payload.get("products") or payload.get("product")):
                        parsed = shopify_adapter.parse_products_data(payload, fetched_at=run_timestamp)
                        usable = [
                            o for o in parsed
                            if o.price_cents is not None and o.price_cents > 0 and o.product_title
                        ]
                        if usable:
                            logger.info(
                                "[%s] Handle-based Shopify JSON succeeded for %s",
                                site_name,
                                target_url,
                            )
                            extracted_obs = usable
                except Exception as exc:
                    logger.debug("[%s] Single handle endpoint failed on %s: %s", site_name, target_url, exc)

        if extracted_obs:
            result.observations.extend(extracted_obs)
            continue

        # =====================================================================
        # Strategy 3: JSON-LD fallback
        # =====================================================================
        logger.info("[%s] Falling back to JSON-LD for %s", site_name, target_url)
        attempted_strategies.append("JSON-LD")

        html_text = ""
        try:
            timeout_sec = int(site_config.get("timeout", 20))
            html_resp = http_get(target_url, timeout=timeout_sec, max_retries=2)
            if html_resp.status_code == 200:
                html_text = html_resp.text
        except HttpError as http_err:
            if http_err.status_code in (404, 410):
                result.confirmed_absent_variant_ids.append(target_url)
                result.add_error("not_found", f"Product page not found (HTTP {http_err.status_code}) on {target_url}", url=target_url, site=site_name)
                continue
            elif "Redirected" in str(http_err) or http_err.status_code in (301, 302, 303, 307, 308):
                # Redirect to generic page classified as error, NOT a miss
                err_msg = f"Redirect error on product URL: {http_err}"
                logger.warning("[%s] %s on %s", site_name, err_msg, target_url)
                result.add_error("not_found", err_msg, url=target_url, site=site_name)
                continue
            elif getattr(http_err, "error_type", None) == "rate_limited" or http_err.status_code == 429:
                err_msg = f"rate_limited on {target_url}: {http_err}"
                logger.error("[%s] %s", site_name, err_msg)
                result.add_error("rate_limited", err_msg, url=target_url, site=site_name)
                break
            elif getattr(http_err, "error_type", None) == "blocked" or http_err.status_code in (401, 403):
                err_msg = f"blocked on {target_url}: {http_err}"
                logger.error("[%s] %s", site_name, err_msg)
                result.add_error("blocked", err_msg, url=target_url, site=site_name)
                break
            logger.debug("[%s] HTTP GET HTML failed for %s: %s", site_name, target_url, http_err)
        except Exception as exc:
            logger.debug("[%s] HTTP GET HTML failed for %s: %s", site_name, target_url, exc)

        if html_text:
            try:
                jsonld_adapter = JsonLdAdapter(site_config)
                jsonld_obs = jsonld_adapter.parse_html(
                    html_text=html_text,
                    page_url=target_url,
                    fetched_at=run_timestamp,
                )
                usable_jsonld = [
                    o for o in jsonld_obs
                    if o.price_cents is not None
                    and o.price_cents > 0
                    and o.product_title
                    and o.product_title != "Unknown Product"
                ]
                if usable_jsonld:
                    logger.info("[%s] JSON-LD extraction succeeded for %s", site_name, target_url)
                    extracted_obs = usable_jsonld
            except Exception as exc:
                logger.debug("[%s] JSON-LD parsing error for %s: %s", site_name, target_url, exc)

        if extracted_obs:
            result.observations.extend(extracted_obs)
            continue

        # =====================================================================
        # Strategy 4: HTML/DOM fallback (static HTML first, Playwright only if JS-rendered)
        # =====================================================================
        logger.info("[%s] Falling back to HTML/Playwright for %s", site_name, target_url)
        attempted_strategies.append("HTML/DOM static")

        pw_adapter = PlaywrightAdapter(site_config)
        if html_text:
            try:
                dom_obs = pw_adapter.parse_dom(
                    html_text=html_text,
                    page_url=target_url,
                    fetched_at=run_timestamp,
                )
                usable_dom = [
                    o for o in dom_obs
                    if o.price_cents is not None
                    and o.price_cents > 0
                    and o.product_title
                    and o.product_title != "Unknown Product"
                ]
                if usable_dom:
                    logger.info("[%s] Static HTML/DOM extraction succeeded for %s", site_name, target_url)
                    extracted_obs = usable_dom
            except Exception as exc:
                logger.debug("[%s] Static DOM parse error for %s: %s", site_name, target_url, exc)

        if extracted_obs:
            result.observations.extend(extracted_obs)
            continue

        # Static HTML had no usable price -> clearly JavaScript-rendered
        attempted_strategies.append("Playwright")
        try:
            pw_obs = pw_adapter.fetch_single_url(target_url, fetched_at=run_timestamp)
            usable_pw = [
                o for o in pw_obs
                if o.price_cents is not None
                and o.price_cents > 0
                and o.product_title
                and o.product_title != "Unknown Product"
            ]
            if usable_pw:
                logger.info("[%s] Playwright extraction succeeded for %s", site_name, target_url)
                extracted_obs = usable_pw
        except Exception as exc:
            logger.warning("[%s] Playwright extraction failed for %s: %s", site_name, target_url, exc)

        if extracted_obs:
            result.observations.extend(extracted_obs)
            continue

        # =====================================================================
        # Strategy 5: Graceful failure
        # =====================================================================
        err_msg = (
            f"[{site_name}] All price extraction strategies failed for {target_url} "
            f"(attempted: {', '.join(attempted_strategies)})"
        )
        logger.error(err_msg)
        result.add_error("parse_error", err_msg, url=target_url, site=site_name)

    return result
