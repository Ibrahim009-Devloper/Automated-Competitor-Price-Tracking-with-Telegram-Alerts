"""Shared HTTP client utility with retries, timeout, and browser user-agent."""

import logging
import time
from typing import Any, Dict, Optional
import requests

import random
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Standard browser User-Agent to avoid generic bot blocks
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class HttpError(Exception):
    """Exception raised when an HTTP request fails or returns an error status.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP response status code, if available.
        error_type: Classified error type (timeout, network, http_5xx, rate_limited,
                    blocked, not_found, parse_error, validation_failed).
        retry_after: Seconds specified by Retry-After header, if any.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_type: Optional[str] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after

        # Infer error_type if not explicitly passed
        if error_type:
            self.error_type = error_type
        elif status_code in (404, 410):
            self.error_type = "not_found"
        elif status_code in (401, 403):
            self.error_type = "blocked"
        elif status_code == 429:
            self.error_type = "rate_limited"
        elif status_code and 500 <= status_code < 600:
            self.error_type = "http_5xx"
        else:
            self.error_type = "network"


def is_captcha_challenge(response: requests.Response) -> bool:
    """Check if response body appears to contain a Cloudflare or captcha challenge.

    Args:
        response: requests.Response object.

    Returns:
        bool: True if captcha / challenge markers are detected.
    """
    if response is None:
        return False
    text = getattr(response, "text", "") or ""
    text_lower = text.lower()
    indicators = (
        "cf-challenge",
        "challenge-platform",
        "<title>just a moment...</title>",
        "attention required! | cloudflare",
        "recaptcha",
        "hcaptcha",
    )
    return any(ind in text_lower for ind in indicators)


def is_generic_redirect(original_url: str, final_url: str) -> bool:
    """Check whether a specific product URL was redirected to a homepage, search page, or generic landing page.

    Args:
        original_url: The URL that was requested.
        final_url: The URL where the response landed.

    Returns:
        bool: True if redirected to homepage, search page, or generic page instead of the product.
    """
    if not original_url or not final_url:
        return False
    orig_parsed = urlparse(original_url)
    final_parsed = urlparse(final_url)

    orig_path = orig_parsed.path.rstrip("/").lower()
    final_path = final_parsed.path.rstrip("/").lower()

    if orig_path == final_path:
        return False

    # Check if original was a product-like URL or non-root path
    is_product_like = any(ind in orig_path for ind in ("/products/", "/product/", "/items/", "/item/")) or (len(orig_path) > 1 and orig_path not in ("", "/"))

    if is_product_like:
        # Redirected to homepage
        if final_path in ("", "/", "/index.html", "/index.htm", "/index.php"):
            return True
        # Redirected to search page
        if "/search" in final_path or "search" in final_parsed.query:
            return True
        # Redirected to collections or generic 404/not-found landing page
        if final_path in ("/collections", "/collections/all") or any(ind in final_path for ind in ("/404", "not-found", "pages/404")):
            return True

    return False


def is_json_response(response: requests.Response) -> bool:
    """Validate that an HTTP response appears to contain valid JSON.

    Checks:
    - HTTP status is 2xx.
    - Content-Type header does not indicate HTML, media, or other non-JSON types.
    - Response body starts with '{' or '[' after stripping whitespace.

    Args:
        response: requests.Response object.

    Returns:
        bool: True if response appears to be valid JSON, False otherwise.
    """
    if response is None:
        return False

    status = getattr(response, "status_code", 0)
    if not (200 <= status < 300):
        return False

    headers = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("content-type", "")).lower()
    # Reject responses with explicit non-JSON content types
    non_json_indicators = ["text/html", "image/", "video/", "audio/", "application/pdf"]
    if any(ind in content_type for ind in non_json_indicators):
        return False

    body = getattr(response, "text", "")
    if not isinstance(body, str):
        return False

    stripped = body.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return False

    return True


def parse_json_safely(response: requests.Response) -> Optional[Any]:
    """Validate response and safely parse JSON body.

    Never blindly calls .json() on an unknown or non-JSON response.

    Args:
        response: requests.Response object.

    Returns:
        Parsed JSON data (dict or list), or None if response is invalid/non-JSON.
    """
    if not is_json_response(response):
        return None

    try:
        return response.json()
    except Exception as exc:
        logger.debug("Failed to decode JSON from response: %s", exc)
        return None


def http_get(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 20,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    backoff_seconds: Optional[float] = None,
) -> requests.Response:
    """Perform an HTTP GET request with retries, timeout, and standard headers.

    Implements:
    - Retries ONLY for transient failures (timeout, network, HTTP 5xx, HTTP 429 with Retry-After <= 60s).
    - Exponential backoff with random jitter.
    - Never retries for 404, 410, 401, 403, or captcha blocks.
    - Caps Retry-After wait at 60s (if greater, raises rate_limited HttpError).
    - Flags redirects from product pages to homepage/search pages as not_found errors.

    Args:
        url: Target URL to fetch.
        params: Optional query parameters dictionary.
        headers: Optional additional request headers.
        timeout: Request timeout in seconds (default 20).
        max_retries: Maximum number of retry attempts (default 3).
        initial_backoff: Base delay in seconds (backwards compatibility).
        backoff_seconds: Base backoff seconds (takes precedence over initial_backoff).

    Returns:
        requests.Response: Successful response object.

    Raises:
        HttpError: When the request fails, times out, or returns a 4xx/5xx error.
    """
    base_backoff = backoff_seconds if backoff_seconds is not None else initial_backoff
    request_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        request_headers.update(headers)

    last_error: Optional[HttpError] = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug("GET %s (attempt %d/%d)", url, attempt, max_retries)
            response = requests.get(
                url,
                params=params,
                headers=request_headers,
                timeout=timeout,
            )

            # Check for non-product redirect (e.g., redirected to homepage or search)
            history = getattr(response, "history", None)
            final_url = getattr(response, "url", "")
            if history and is_generic_redirect(url, final_url):
                raise HttpError(
                    f"Redirected from product URL to generic page: {final_url}",
                    status_code=302,
                    error_type="not_found",
                )

            # Check for 404/410: Confirmed absence, NEVER retry
            if response.status_code in (404, 410):
                raise HttpError(
                    f"HTTP {response.status_code} Not Found for URL: {url}",
                    status_code=response.status_code,
                    error_type="not_found",
                )

            # Check for 401/403 or Captcha block: NEVER retry
            if response.status_code in (401, 403) or is_captcha_challenge(response):
                raise HttpError(
                    f"HTTP {response.status_code} Blocked/Captcha for URL: {url}",
                    status_code=response.status_code if response.status_code != 200 else 403,
                    error_type="blocked",
                )

            # Check for 429 Rate Limit
            if response.status_code == 429:
                retry_header = response.headers.get("Retry-After")
                retry_seconds: Optional[int] = None
                if retry_header:
                    try:
                        retry_seconds = int(retry_header)
                    except ValueError:
                        retry_seconds = None

                # Rule 2: Cap the Retry-After wait at 60 seconds
                if retry_seconds is not None and retry_seconds > 60:
                    raise HttpError(
                        f"HTTP 429 Rate limited: Retry-After {retry_seconds}s exceeds 60s cap for {url}",
                        status_code=429,
                        error_type="rate_limited",
                        retry_after=retry_seconds,
                    )

                # Transient 429 within cap: sleep Retry-After or exponential backoff
                wait_sec = float(retry_seconds) if retry_seconds is not None else (base_backoff * (2 ** (attempt - 1)))
                if attempt < max_retries:
                    logger.warning(
                        "Rate limited on %s (attempt %d/%d). Sleeping %.1fs before retry...",
                        url,
                        attempt,
                        max_retries,
                        wait_sec,
                    )
                    time.sleep(wait_sec)
                    continue
                else:
                    raise HttpError(
                        f"HTTP 429 Rate limited after {max_retries} attempts for URL: {url}",
                        status_code=429,
                        error_type="rate_limited",
                    )

            # If client error (4xx) other than rate limit (429), don't keep retrying
            if 400 <= response.status_code < 500:
                raise HttpError(
                    f"HTTP {response.status_code} Client Error for URL: {url}",
                    status_code=response.status_code,
                    error_type="parse_error",
                )

            # If server error (5xx), trigger retry
            if 500 <= response.status_code < 600:
                raise HttpError(
                    f"HTTP {response.status_code} Server Error for URL: {url}",
                    status_code=response.status_code,
                    error_type="http_5xx",
                )

            response.raise_for_status()
            return response

        except HttpError as err:
            # Fatal client errors and non-retryable blocks are immediately raised
            if err.error_type in ("not_found", "blocked") or (
                err.error_type == "rate_limited" and err.retry_after and err.retry_after > 60
            ):
                raise
            last_error = err
        except requests.exceptions.Timeout:
            last_error = HttpError(
                f"Request timed out after {timeout}s: {url}",
                error_type="timeout",
            )
        except requests.exceptions.ConnectionError as err:
            last_error = HttpError(
                f"Connection failed to {url}: {err}",
                error_type="network",
            )
        except requests.exceptions.RequestException as err:
            status = getattr(err.response, "status_code", None)
            err_type = "http_5xx" if status and status >= 500 else "network"
            last_error = HttpError(
                f"HTTP request error: {err}",
                status_code=status,
                error_type=err_type,
            )

        # Retry with exponential backoff + random jitter for transient errors
        if attempt < max_retries:
            jitter = random.uniform(0.1, 0.5)
            wait_time = (base_backoff * (2 ** (attempt - 1))) + jitter
            logger.warning(
                "Request to %s failed (attempt %d/%d, type=%s): %s. Retrying in %.2fs...",
                url,
                attempt,
                max_retries,
                getattr(last_error, "error_type", "unknown"),
                last_error,
                wait_time,
            )
            time.sleep(wait_time)

    # If all retries exhausted
    raise last_error or HttpError(
        f"Failed to fetch {url} after {max_retries} attempts.",
        error_type="network",
    )
