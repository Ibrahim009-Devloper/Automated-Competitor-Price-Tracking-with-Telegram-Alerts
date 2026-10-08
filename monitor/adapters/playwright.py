"""Playwright browser scraping adapter for JavaScript-rendered product pages.

Uses headless Chromium via the Playwright sync API.
Per-site configuration specifies CSS selectors for price, availability, title,
and wait conditions so that store design changes require only YAML updates.
"""

import csv
from datetime import datetime, timezone
import logging
from pathlib import Path
import random
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, Page, sync_playwright

from monitor.adapters.base import SiteAdapter
from monitor.models import FetchResult, Observation
from monitor.utils.http import DEFAULT_USER_AGENT
from monitor.utils.money import parse_price

logger = logging.getLogger(__name__)


def clean_and_deduplicate_title(text: str) -> str:
    """Clean title text: strip whitespace, collapse repeated spaces, and de-duplicate.

    Safeguard (Requirement 5):
    - Strip whitespace, collapse repeated spaces.
    - If the text is the same string repeated twice, keep one copy.

    Args:
        text: Raw extracted title text.

    Returns:
        Cleaned, de-duplicated title string.
    """
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""

    # De-duplication safeguard:
    # 1. Exact repeat without space e.g. "Title(RC)Title(RC)"
    if len(cleaned) >= 6 and len(cleaned) % 2 == 0:
        half = len(cleaned) // 2
        if cleaned[:half] == cleaned[half:]:
            return cleaned[:half].strip()

    # 2. Exact repeat with space or separator e.g. "Title (RC) Title (RC)"
    m = re.match(r"^(.{3,}?)\s+(?:[-–—|]\s+)?\1$", cleaned)
    if m:
        return m.group(1).strip()

    # 3. Word-level split into two identical halves
    words = cleaned.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        h = len(words) // 2
        if words[:h] == words[h:]:
            return " ".join(words[:h])

    return cleaned


class PlaywrightAdapter(SiteAdapter):
    """Scrapes JavaScript-rendered e-commerce product pages using headless Playwright."""

    def __init__(self, site_config: Dict[str, Any]) -> None:
        """Initialize Playwright adapter with CSS selectors and site settings.

        Args:
            site_config: Configuration dict with name, base_url, currency, selectors,
                         timeout, and delay settings.
        """
        super().__init__(site_config)

        # Selectors from config (Rule 9: never hardcoded in Python)
        self.price_selector: str = site_config.get(
            "price_selector", ".price-item, .price-item--sale, .product-price, .price, [data-price]"
        )
        self.title_selector: str = site_config.get(
            "title_selector", "h1, .product-title, .product__title"
        )
        self.availability_selector: str = site_config.get(
            "availability_selector", "[name='add'], .add-to-cart, button[type='submit']"
        )
        self.wait_for_selector: str = site_config.get(
            "wait_for", self.price_selector
        )
        self.variant_selector: Optional[str] = site_config.get(
            "variant_selector", None
        )
        self.compare_price_selector: Optional[str] = site_config.get(
            "compare_price_selector", ".price-item--regular, .compare-price, [data-compare-price]"
        )

        # Timeout in seconds (default 20s as specified in prompt)
        self.timeout_sec: float = float(site_config.get("timeout", 20))
        self.targets_path: str = site_config.get("targets_path", "config/targets.csv")

    def load_target_urls(self) -> List[Dict[str, str]]:
        """Load target product URLs for this store from config/targets.csv.

        Returns:
            List of dictionaries with 'url' and optional 'product_group'.
        """
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
                    if site_name.lower() == self.site_name.lower():
                        url = (row.get("url") or "").strip()
                        product_group = (row.get("product_group") or "").strip()

                        if not url and row.get("product_handle"):
                            handle = row["product_handle"].strip()
                            url = f"{self.base_url}/products/{handle}"

                        if url:
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

    def parse_dom(
        self,
        html_text: str,
        page_url: str,
        fetched_at: Optional[datetime] = None,
        errors_out: Optional[List[str]] = None,
    ) -> List[Observation]:
        """Parse rendered DOM HTML using configured CSS selectors (used for offline testing).

        Args:
            html_text: Rendered HTML of the page.
            page_url: Target product URL.
            fetched_at: Optional timestamp.
            errors_out: List to collect non-fatal errors.

        Returns:
            List[Observation]: Extracted observation objects.
        """
        if fetched_at is None:
            fetched_at = datetime.now(timezone.utc)

        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Title
        title_el = soup.select_one(self.title_selector)
        if title_el and title_el.name != "h1" and title_el.find("h1"):
            title_el = title_el.find("h1")
        raw_title = title_el.get_text(strip=True) if title_el else ""
        product_title = clean_and_deduplicate_title(raw_title)

        # Requirement 2: Remove default placeholders like "Unknown Product".
        # If title is missing, the observation is invalid and produces no observation.
        if not product_title:
            msg = f"Could not extract valid product title on {page_url}"
            if errors_out is not None:
                errors_out.append(msg)
            return []

        # 2. Variants if configured and present
        observations: List[Observation] = []
        variant_options = []
        if self.variant_selector:
            variant_options = soup.select(self.variant_selector)

        if variant_options:
            for idx, opt in enumerate(variant_options, 1):
                opt_text = opt.get_text(strip=True)
                opt_val = opt.get("value") or f"var-{idx}"

                # Try parsing price from variant option text (e.g., "50ml - $45.00")
                var_price_cents = None
                # First look for a currency-tagged price like $45.00, €45,00
                price_match = re.search(r"([$€£¥]\s*[\d., ]+)", opt_text)
                if price_match:
                    var_price_cents = parse_price(price_match.group(1), locale_hint=self.currency)
                else:
                    # Look for trailing decimal numbers like " - 45.00"
                    num_match = re.search(r"[\s\-–—]+([\d]+[.,]\d{2})", opt_text)
                    if num_match:
                        var_price_cents = parse_price(num_match.group(1), locale_hint=self.currency)
                    else:
                        var_price_cents = parse_price(opt_text, locale_hint=self.currency)

                if var_price_cents is None:
                    # Fallback to main price selector on page
                    for el in soup.select(self.price_selector):
                        txt = el.get_text(strip=True)
                        if not txt or not re.search(r"\d", txt):
                            continue
                        c = parse_price(txt, locale_hint=self.currency)
                        if c is None:
                            matches = re.findall(r"([$€£¥]\s*[\d., ]+)", txt)
                            for m in matches:
                                cand = parse_price(m, locale_hint=self.currency)
                                if cand is not None and cand > 0:
                                    c = cand
                                    break
                        if c is not None and c > 0:
                            var_price_cents = c
                            break

                obs = Observation(
                    site=self.site_name,
                    product_id=page_url,
                    variant_id=str(opt_val),
                    product_title=product_title,
                    variant_title=opt_text or f"Variant {idx}",
                    price_cents=var_price_cents,
                    compare_at_cents=None,
                    currency=self.currency,
                    available=True,
                    url=page_url,
                    fetched_at=fetched_at,
                )
                observations.append(obs)
            return observations

        # 3. Single product extraction
        price_cents = None
        price_raw = None
        for el in soup.select(self.price_selector):
            txt = el.get_text(strip=True)
            if not txt or not re.search(r"\d", txt):
                continue
            cents = parse_price(txt, locale_hint=self.currency)
            if cents is None:
                matches = re.findall(r"([$€£¥]\s*[\d., ]+)", txt)
                for m in matches:
                    cand = parse_price(m, locale_hint=self.currency)
                    if cand is not None and cand > 0:
                        cents = cand
                        break
            if cents is not None and cents > 0:
                price_cents = cents
                price_raw = txt
                break

        if price_cents is None:
            msg = f"Could not extract price using selector '{self.price_selector}' on {page_url}"
            if errors_out is not None:
                errors_out.append(msg)

        # 4. Compare-at price
        compare_at_cents = None
        if self.compare_price_selector:
            compare_el = soup.select_one(self.compare_price_selector)
            if compare_el:
                compare_at_cents = parse_price(
                    compare_el.get_text(strip=True), locale_hint=self.currency
                )

        # 5. Availability (Rule 2: Never guess)
        available: Optional[bool] = None
        if self.availability_selector:
            avail_candidates = soup.select(self.availability_selector)
            chosen_el = None
            for cand in avail_candidates:
                cand_classes = cand.get("class", [])
                if any("cart__checkout" in c for c in cand_classes):
                    continue
                chosen_el = cand
                break
            if not chosen_el and avail_candidates:
                chosen_el = avail_candidates[0]

            if chosen_el:
                btn_text = chosen_el.get_text(strip=True).lower()
                is_disabled = (
                    chosen_el.has_attr("disabled")
                    or "disabled" in chosen_el.get("class", [])
                    or "sold out" in btn_text
                    or "out of stock" in btn_text
                )
                available = not is_disabled
            else:
                available = None

        obs = Observation(
            site=self.site_name,
            product_id=page_url,
            variant_id=page_url,
            product_title=product_title,
            variant_title="Default Title",
            price_cents=price_cents,
            compare_at_cents=compare_at_cents,
            currency=self.currency,
            available=available,
            url=page_url,
            fetched_at=fetched_at,
        )
        return [obs]

    def _extract_page(
        self,
        page: Page,
        page_url: str,
        fetched_at: datetime,
        errors_out: List[str],
    ) -> List[Observation]:
        """Extract product observation from live Playwright page element handles.

        Args:
            page: Playwright Page object.
            page_url: Product URL.
            fetched_at: Timestamp.
            errors_out: Error output list.

        Returns:
            List[Observation]: Observations extracted.
        """
        # Requirement 6: Wait for price selector to appear
        try:
            page.wait_for_selector(
                self.price_selector,
                state="attached",
                timeout=min(10000, int(self.timeout_sec * 1000)),
            )
        except PlaywrightError:
            try:
                page.wait_for_selector(
                    self.wait_for_selector,
                    timeout=min(5000, int(self.timeout_sec * 1000)),
                )
            except PlaywrightError:
                pass

        # Wait until price element contains digits (client-side rendered)
        try:
            page.wait_for_function(
                """(selector) => {
                    const els = document.querySelectorAll(selector);
                    for (const el of els) {
                        const txt = el.innerText || el.textContent || '';
                        if (/[0-9]/.test(txt)) return true;
                    }
                    return false;
                }""",
                arg=self.price_selector,
                timeout=min(5000, int(self.timeout_sec * 1000)),
            )
        except Exception:
            pass

        # Requirement 5: Title extraction using locator(selector).first
        live_title = ""
        try:
            if hasattr(page, "locator"):
                title_loc = page.locator(self.title_selector)
                if hasattr(title_loc, "first"):
                    first_loc = title_loc.first
                    raw_t = first_loc.inner_text()
                    if isinstance(raw_t, str) and raw_t.strip():
                        live_title = clean_and_deduplicate_title(raw_t)
        except Exception:
            pass

        # Live price extraction from elements
        live_price_cents = None
        try:
            if hasattr(page, "locator"):
                loc = page.locator(self.price_selector)
                if hasattr(loc, "all"):
                    loc_all = loc.all()
                    if isinstance(loc_all, list):
                        for el in loc_all:
                            try:
                                txt = el.inner_text()
                                if not isinstance(txt, str) or not txt.strip() or not re.search(r"\d", txt):
                                    continue
                                cents = parse_price(txt.strip(), locale_hint=self.currency)
                                if cents is None:
                                    matches = re.findall(r"([$€£¥]\s*[\d., ]+)", txt)
                                    for m in matches:
                                        cand = parse_price(m, locale_hint=self.currency)
                                        if cand is not None and cand > 0:
                                            cents = cand
                                            break
                                if cents is not None and cents > 0:
                                    live_price_cents = cents
                                    break
                            except Exception:
                                continue
        except Exception:
            pass

        # Get full rendered HTML content and parse
        rendered_html = page.content()
        obs_list = self.parse_dom(
            html_text=rendered_html,
            page_url=page_url,
            fetched_at=fetched_at,
            errors_out=errors_out,
        )

        for obs in obs_list:
            if live_title and not obs.product_title:
                obs.product_title = live_title
            if live_price_cents is not None and obs.price_cents is None:
                obs.price_cents = live_price_cents

        return obs_list

    def fetch(self) -> FetchResult:
        """Fetch target product pages using Playwright with resource blocking.

        Lifecycle:
            - Launches one browser per run.
            - Opens a new page per product.
            - Blocks images, media, and fonts to save memory.
            - Closes everything in a finally block.
            - Stops on 403/429/captchas (Rule 5).
            - Continues on single product failure (Rule 6).

        Returns:
            FetchResult: Unified observation list and errors.
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
            "Starting Playwright fetch for '%s': %d product page(s) to process",
            self.site_name,
            len(targets),
        )

        # Reuse ONE browser per run (Prompt requirement)
        playwright_cm = sync_playwright()
        playwright_inst = playwright_cm.start()
        browser = None

        try:
            browser = playwright_inst.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )

            for idx, target_info in enumerate(targets):
                if getattr(self, "is_timed_out", None) and self.is_timed_out():
                    logger.warning("[%s] Max run time reached between URLs. Stopping further page fetches.", self.site_name)
                    result.errors.append("Timeout reached between URLs")
                    break

                url = target_info["url"]

                # Polite delay between requests with random jitter (Rule 4)
                if idx > 0 and self.delay_range[1] > 0:
                    base_sleep = random.uniform(self.delay_range[0], self.delay_range[1])
                    jitter = random.uniform(0.1, 0.4)
                    total_sleep = base_sleep + jitter
                    logger.debug("[%s] Sleeping %.2fs (with jitter) before next product", self.site_name, total_sleep)
                    time.sleep(total_sleep)

                # Open a new page per product (Prompt requirement)
                context = browser.new_context(user_agent=DEFAULT_USER_AGENT)
                page = context.new_page()

                try:
                    # Block images/fonts/media to save memory (Prompt requirement)
                    def block_heavy_resources(route):
                        if route.request.resource_type in ["image", "media", "font"]:
                            route.abort()
                        else:
                            route.continue_()

                    page.route("**/*", block_heavy_resources)

                    # Navigate to product page
                    timeout_ms = int(self.timeout_sec * 1000)
                    response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

                    # Requirement 1: After page.goto(), read response.status
                    if response is None:
                        err_msg = f"HTTP error (no response) for {url}"
                        logger.error("[%s] %s", self.site_name, err_msg)
                        result.errors.append(err_msg)
                        continue

                    if hasattr(response, "status"):
                        if response.status == 403:
                            err_msg = f"blocked: HTTP 403 on {url}"
                            logger.error("[%s] %s", self.site_name, err_msg)
                            result.add_error("blocked", err_msg, url=url, site=self.site_name)
                            break
                        elif response.status == 429:
                            err_msg = f"rate_limited: HTTP 429 on {url}"
                            logger.error("[%s] %s", self.site_name, err_msg)
                            result.add_error("rate_limited", err_msg, url=url, site=self.site_name)
                            break
                        elif response.status in (404, 410):
                            err_msg = f"HTTP {response.status} for {url}"
                            logger.warning("[%s] not_found: %s", self.site_name, err_msg)
                            result.add_error("not_found", err_msg, url=url, site=self.site_name)
                            result.confirmed_absent_variant_ids.append(url)
                            continue
                        elif response.status >= 500:
                            err_msg = f"http_5xx: HTTP {response.status} for {url}"
                            logger.error("[%s] %s", self.site_name, err_msg)
                            result.add_error("http_5xx", err_msg, url=url, site=self.site_name)
                            continue
                        elif response.status >= 400:
                            err_msg = f"parse_error: HTTP {response.status} for {url}"
                            logger.error("[%s] %s", self.site_name, err_msg)
                            result.add_error("parse_error", err_msg, url=url, site=self.site_name)
                            continue

                    # Requirement 1: Detect redirects to generic / home / search / 404 page
                    page_url_val = getattr(page, "url", None)
                    if isinstance(page_url_val, str) and page_url_val:
                        current_url = page_url_val
                        norm_orig = url.split("?")[0].rstrip("/").lower()
                        norm_curr = current_url.split("?")[0].rstrip("/").lower()
                        if norm_curr != norm_orig:
                            p_curr = urlparse(norm_curr)
                            is_bad_redirect = False
                            if p_curr.path in ("", "/", "/index.html", "/search") or "/search" in p_curr.path:
                                is_bad_redirect = True
                            elif any(ind in norm_curr for ind in ["/404", "not-found", "pages/404"]):
                                is_bad_redirect = True
                            elif "/products/" in norm_orig and "/products/" not in norm_curr:
                                is_bad_redirect = True

                            if is_bad_redirect:
                                err_msg = f"Unexpected redirect for {url} -> {current_url}"
                                logger.warning("[%s] %s", self.site_name, err_msg)
                                result.add_error("not_found", err_msg, url=url, site=self.site_name)
                                continue

                    # Check for captcha challenge in HTML content (Rule 5)
                    page_html_lower = page.content().lower()
                    if (
                        "cf-challenge" in page_html_lower
                        or "challenge-platform" in page_html_lower
                        or "<title>just a moment...</title>" in page_html_lower
                        or "attention required! | cloudflare" in page_html_lower
                    ):
                        err_msg = f"blocked: captcha challenge detected on {url}"
                        logger.error("[%s] %s", self.site_name, err_msg)
                        result.add_error("blocked", err_msg, url=url, site=self.site_name)
                        break

                    # Extract observations from page
                    page_errors: List[str] = []
                    observations = self._extract_page(
                        page=page,
                        page_url=url,
                        fetched_at=run_timestamp,
                        errors_out=page_errors,
                    )

                    if page_errors:
                        result.errors.extend(page_errors)

                    result.observations.extend(observations)
                    logger.info(
                        "[%s] Processed '%s': extracted %d observation(s)",
                        self.site_name,
                        url,
                        len(observations),
                    )

                except PlaywrightError as pw_err:
                    # Rule 6: One failing product URL must not stop the rest of that site
                    err_msg = f"Playwright error on {url}: {pw_err}"
                    logger.warning("[%s] %s", self.site_name, err_msg)
                    result.errors.append(err_msg)
                    continue

                except Exception as exc:
                    # Rule 6: Continue with remaining products
                    err_msg = f"Unexpected error on {url}: {exc}"
                    logger.exception("[%s] %s", self.site_name, err_msg)
                    result.errors.append(err_msg)
                    continue

                finally:
                    # Close page and context cleanly per product (Prompt requirement)
                    page.close()
                    context.close()

        finally:
            # Close everything in a finally block (Prompt requirement)
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            try:
                playwright_inst.stop()
            except Exception:
                pass

        logger.info(
            "Finished Playwright fetch for '%s': %d observations collected, %d errors",
            self.site_name,
            len(result.observations),
            len(result.errors),
        )
        return result

    def fetch_single_url(
        self, url: str, fetched_at: Optional[datetime] = None
    ) -> List[Observation]:
        """Fetch and extract a single product page using Playwright.

        Used by the fallback strategy when price is JavaScript-rendered and static HTML fails.

        Args:
            url: Target product URL.
            fetched_at: Timestamp.

        Returns:
            List of Observation items extracted from the page.
        """
        orig_urls = self.site_config.get("urls")
        self.site_config["urls"] = [url]
        try:
            res = self.fetch()
            return res.observations
        finally:
            if orig_urls is None:
                self.site_config.pop("urls", None)
            else:
                self.site_config["urls"] = orig_urls

