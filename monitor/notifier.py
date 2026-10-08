"""Telegram notification client and message builder for price and stock events."""

from datetime import datetime, timezone
import html
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import requests

from monitor.utils.money import cents_to_str

logger = logging.getLogger(__name__)

# Telegram message length limit is 4096; safe boundary threshold is 4000
MAX_TELEGRAM_MESSAGE_LENGTH = 4000


def escape_html(text: Any) -> str:
    """Escape special HTML characters (&, <, >) to avoid Telegram parsing errors."""
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


def format_price_change(old_cents: Optional[int], new_cents: Optional[int]) -> str:
    """Format price change with human-readable dollars and percentage.

    Examples:
        3400, 2900 -> "$34.00 → $29.00 (-14.7%)"
        2000, 2500 -> "$20.00 → $25.00 (+25.0%)"
    """
    old_str = cents_to_str(old_cents)
    new_str = cents_to_str(new_cents)

    if old_cents is not None and new_cents is not None and old_cents > 0:
        pct = ((new_cents - old_cents) / old_cents) * 100.0
        sign = "+" if pct > 0 else ""
        return f"{old_str} → {new_str} ({sign}{pct:.1f}%)"
    return f"{old_str} → {new_str}"


def format_event_block(event: Dict[str, Any]) -> str:
    """Format a single event into a clean, compact HTML bullet block.

    Args:
        event: Event dictionary containing event_type, product_title, variant_title,
               site, old_value, new_value, url, etc.

    Returns:
        Formatted HTML string for the event.
    """
    event_type = event.get("event_type", "unknown")
    prod_title = escape_html(event.get("product_title", "Unknown Product"))
    var_title = escape_html(event.get("variant_title", ""))
    site_name = escape_html(event.get("site", "Store"))
    url = event.get("url", "")

    # Build title line: include variant title if it's not the generic 'Default Title'
    if var_title and var_title != "Default Title":
        title_line = f"• <b>{prod_title}</b> (<i>{var_title}</i>)"
    else:
        title_line = f"• <b>{prod_title}</b>"

    lines = [title_line, f"  🏢 Site: {site_name}"]

    # Format specific change detail based on event type
    old_val = event.get("old_value")
    new_val = event.get("new_value")

    if event_type in ("price_drop", "price_increase"):
        price_text = format_price_change(old_val, new_val)
        lines.append(f"  💰 Price: {price_text}")
    elif event_type == "out_of_stock":
        lines.append("  📦 Stock: In Stock → <b>Out of Stock</b>")
    elif event_type == "back_in_stock":
        lines.append("  📦 Stock: Out of Stock → <b>Back in Stock</b>")
    elif event_type == "new_variant":
        price_text = cents_to_str(new_val)
        lines.append(f"  ✨ Price: {price_text}")
    elif event_type == "delisted":
        lines.append("  ❌ Status: <b>Delisted</b> (absent from catalog)")
    elif event_type == "relisted":
        lines.append("  ✅ Status: <b>Relisted</b> (returned to catalog)")
    else:
        lines.append(f"  ℹ️ Change: {old_val} → {new_val}")

    if url:
        lines.append(f'  🔗 <a href="{url}">View Product</a>')

    return "\n".join(lines)


def build_message(events: List[Dict[str, Any]]) -> List[str]:
    """Group all unnotified events of a run into summary message(s), grouped by type.

    Groups:
      1. Price Drops (📉)
      2. Price Increases (📈)
      3. Out of Stock (❌)
      4. Back in Stock (✅)
      5. New Variants (🆕)
      6. Delisted & Relisted Products (🔄) - combined in ONE section

    Splits messages at event boundaries if the formatted content exceeds 4000 characters.

    Args:
        events: List of event dictionaries from the run.

    Returns:
        List of HTML-formatted strings (each <= 4000 characters).
    """
    if not events:
        return []

    # Defined order of groups with respective emojis and headers
    SECTION_CONFIG = [
        ("price_drop", "📉 <b>Price Drops</b>"),
        ("price_increase", "📈 <b>Price Increases</b>"),
        ("out_of_stock", "❌ <b>Out of Stock</b>"),
        ("back_in_stock", "✅ <b>Back in Stock</b>"),
        ("new_variant", "🆕 <b>New Variants</b>"),
        ("delisted_relisted", "🔄 <b>Delisted & Relisted Products</b>"),
    ]

    # Map events into buckets
    grouped: Dict[str, List[Dict[str, Any]]] = {code: [] for code, _ in SECTION_CONFIG}
    others: List[Dict[str, Any]] = []

    for ev in events:
        etype = ev.get("event_type")
        if etype in ("delisted", "relisted"):
            grouped["delisted_relisted"].append(ev)
        elif etype in grouped:
            grouped[etype].append(ev)
        else:
            others.append(ev)

    # Build list of sections with formatted event blocks
    sections: List[tuple[str, List[str]]] = []
    for code, header in SECTION_CONFIG:
        ev_list = grouped[code]
        if ev_list:
            formatted_blocks = [format_event_block(e) for e in ev_list]
            sections.append((header, formatted_blocks))

    if others:
        formatted_blocks = [format_event_block(e) for e in others]
        sections.append(("ℹ️ <b>Other Events</b>", formatted_blocks))

    # Assemble into message chunks respecting the 4000-character boundary
    messages: List[str] = []
    current_lines: List[str] = ["🔔 <b>Price Monitor Alert</b>\n"]

    for header, blocks in sections:
        # Check if we need to start a section in current message
        section_header = f"\n{header}\n"

        for block in blocks:
            needed_text = ""
            if section_header and section_header not in "".join(current_lines):
                needed_text += section_header
            needed_text += f"{block}\n\n"

            current_len = len("".join(current_lines))
            if current_len + len(needed_text) > MAX_TELEGRAM_MESSAGE_LENGTH:
                # Flush current message and start a new part
                messages.append("".join(current_lines).strip())
                part_num = len(messages) + 1
                current_lines = [f"🔔 <b>Price Monitor Alert (Part {part_num})</b>\n"]
                if section_header:
                    current_lines.append(section_header)
                current_lines.append(f"{block}\n\n")
            else:
                if section_header and section_header not in "".join(current_lines):
                    current_lines.append(section_header)
                current_lines.append(f"{block}\n\n")

    if current_lines:
        messages.append("".join(current_lines).strip())

    return messages


def build_error_message(errors: List[str]) -> List[str]:
    """Group monitoring errors and warnings into summary alert message(s).

    Args:
        errors: List of error/warning strings encountered during a run.

    Returns:
        List of HTML-formatted strings (each <= 4000 characters).
    """
    if not errors:
        return []

    messages: List[str] = []
    current_lines: List[str] = ["⚠️ <b>Price Monitor Warning / Error Alert</b>\n\n"]

    for err in errors:
        escaped_err = escape_html(err)
        block = f"• <code>{escaped_err}</code>\n\n"
        current_len = len("".join(current_lines))
        if current_len + len(block) > MAX_TELEGRAM_MESSAGE_LENGTH:
            messages.append("".join(current_lines).strip())
            part_num = len(messages) + 1
            current_lines = [
                f"⚠️ <b>Price Monitor Warning / Error Alert (Part {part_num})</b>\n\n",
                block,
            ]
        else:
            current_lines.append(block)

    if current_lines:
        messages.append("".join(current_lines).strip())

    return messages


def build_new_variants_summary(new_variants: List[Dict[str, Any]]) -> Optional[str]:
    """Build ONE summary message for new variants added during a run (Rule 2).

    Grouped by site, displays:
      - number of new products
      - number of new variants
      - list of product titles capped at 10 titles, then 'and N more'.

    Args:
        new_variants: List of newly added variant dicts or observation objects.

    Returns:
        Optional[str]: HTML-formatted summary message, or None if list is empty.
    """
    if not new_variants:
        return None

    site_groups: Dict[str, Dict[str, Any]] = {}
    for var in new_variants:
        site = (
            var.get("site", "Store")
            if isinstance(var, dict)
            else getattr(var, "site", "Store")
        )
        title = (
            var.get("product_title", "Unknown Product")
            if isinstance(var, dict)
            else getattr(var, "product_title", "Unknown Product")
        )
        if site not in site_groups:
            site_groups[site] = {"titles": [], "variant_count": 0}

        site_groups[site]["variant_count"] += 1
        if title not in site_groups[site]["titles"]:
            site_groups[site]["titles"].append(title)

    lines = ["🆕 <b>New Products Added Summary</b>\n"]
    for site, data in site_groups.items():
        unique_titles = data["titles"]
        v_count = data["variant_count"]
        p_count = len(unique_titles)

        prod_text = f"{p_count} new product" if p_count == 1 else f"{p_count} new products"
        var_text = f"{v_count} variant" if v_count == 1 else f"{v_count} variants"

        lines.append(f"🏢 <b>{escape_html(site)}</b>: {prod_text} ({var_text})")

        # Cap at 10 titles, then 'and N more' (Rule 2)
        displayed_titles = unique_titles[:10]
        for t in displayed_titles:
            lines.append(f"  • {escape_html(t)}")

        if len(unique_titles) > 10:
            remaining = len(unique_titles) - 10
            lines.append(f"  • <i>and {remaining} more</i>")
        lines.append("")

    # Rule 2: Explicit note indicating that baseline is saved and monitoring begins on next cycle
    lines.append("<i>Monitoring starts from the next run.</i>")
    return "\n".join(lines).strip()


def send_message(
    text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = 20,
    max_retries: int = 3,
) -> bool:
    """Send an HTML-formatted message to Telegram via the Bot API sendMessage method.

    Retries up to 3 times with increasing backoff.
    Never hard-codes or logs the bot token.

    Args:
        text: HTML text payload to send.
        token: Telegram Bot token (defaults to TELEGRAM_BOT_TOKEN env var).
        chat_id: Target chat ID (defaults to TELEGRAM_CHAT_ID env var).
        timeout: Request timeout in seconds (default 20).
        max_retries: Maximum retry attempts for transient server/network errors (default 3).

    Returns:
        bool: True only if Telegram accepted and confirmed message delivery, False otherwise.
    """
    bot_token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    target_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not target_chat:
        logger.error(
            "Telegram notification aborted: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing."
        )
        return False

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, max_retries + 1):
        try:
            logger.debug("Sending Telegram message (attempt %d/%d)", attempt, max_retries)
            response = requests.post(
                api_url,
                json=payload,
                timeout=timeout,
            )

            # Check Telegram response
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    logger.info("Telegram message delivered successfully.")
                    return True
                else:
                    logger.error(
                        "Telegram API responded ok=False: %s", data.get("description")
                    )
            elif response.status_code == 429:
                # Rate limited: wait before retrying
                retry_after = int(response.headers.get("Retry-After", 2))
                logger.warning("Telegram rate limit reached. Waiting %ds...", retry_after)
                time.sleep(retry_after)
            elif 400 <= response.status_code < 500:
                err_desc = ""
                try:
                    err_desc = response.json().get("description", response.text)
                except Exception:
                    err_desc = response.text

                hint = ""
                if "chat not found" in err_desc.lower():
                    hint = " -> You must open https://t.me/Shopify_price_monitoring_bot and click START before the bot can message you!"

                logger.error(
                    "Telegram client error %d: %s%s",
                    response.status_code,
                    err_desc,
                    hint,
                )
                return False
            else:
                logger.warning(
                    "Telegram server error %d on attempt %d/%d",
                    response.status_code,
                    attempt,
                    max_retries,
                )

        except requests.exceptions.RequestException as exc:
            # Mask token in case URL or exception includes raw token
            err_msg = str(exc).replace(bot_token, "***")
            logger.warning(
                "Telegram request failed on attempt %d/%d: %s",
                attempt,
                max_retries,
                err_msg,
            )

        # Retry with increasing backoff
        if attempt < max_retries:
            wait_sec = attempt * 1.5
            time.sleep(wait_sec)

    logger.error("Failed to send Telegram message after %d attempts.", max_retries)
    return False


def send_error_message(
    text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = 20,
    max_retries: int = 3,
) -> bool:
    """Send an error/warning message to the designated Telegram Error Alert Bot.

    Routes error messages to TELEGRAM_ERROR_BOT_TOKEN and TELEGRAM_ERROR_CHAT_ID,
    falling back to default TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID if not set.

    Args:
        text: HTML text payload to send.
        token: Telegram Bot token override.
        chat_id: Target chat ID override.
        timeout: Request timeout in seconds (default 20).
        max_retries: Maximum retry attempts for transient errors (default 3).

    Returns:
        bool: True only on confirmed delivery, False otherwise.
    """
    error_token = (
        token
        or os.getenv("TELEGRAM_ERROR_BOT_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
    )
    error_chat = (
        chat_id
        or os.getenv("TELEGRAM_ERROR_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
    )
    return send_message(
        text=text,
        token=error_token,
        chat_id=error_chat,
        timeout=timeout,
        max_retries=max_retries,
    )


def test_connection(
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Test Telegram bot credentials for Price Monitoring Bot and Error Bot.

    Returns:
        Tuple[bool, str]: (Success boolean, explanatory status message).
    """
    price_token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    price_chat = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not price_token:
        return False, "TELEGRAM_BOT_TOKEN is missing in .env"
    if not price_chat:
        return False, "TELEGRAM_CHAT_ID is missing in .env"

    results = []

    # 1. Test Price Monitoring Bot
    try:
        me_resp = requests.get(f"https://api.telegram.org/bot{price_token}/getMe", timeout=10)
        if me_resp.status_code != 200 or not me_resp.json().get("ok"):
            return False, f"Invalid Price Bot token: {me_resp.text}"
        price_bot_user = me_resp.json().get("result", {}).get("username", "bot")

        test_text = (
            "🤖 <b>Price Monitoring Bot - Connected</b>\n\n"
            "✅ All price drops, price increases, stock alerts, and new product summaries will be sent to this chat!"
        )
        p_resp = requests.post(
            f"https://api.telegram.org/bot{price_token}/sendMessage",
            json={"chat_id": price_chat, "text": test_text, "parse_mode": "HTML"},
            timeout=10,
        )
        p_data = p_resp.json()
        if p_resp.status_code == 200 and p_data.get("ok"):
            results.append(f"Price Bot (@{price_bot_user}) -> Chat {price_chat}: Connected successfully")
        else:
            return False, f"Price Bot delivery failed: {p_data.get('description', p_resp.text)}"
    except Exception as exc:
        return False, f"Price Bot connection failed: {exc}"

    # 2. Test Error Alert Bot (if configured)
    error_token = os.getenv("TELEGRAM_ERROR_BOT_TOKEN")
    error_chat = os.getenv("TELEGRAM_ERROR_CHAT_ID", price_chat)
    if error_token and error_token != price_token:
        try:
            me_resp2 = requests.get(f"https://api.telegram.org/bot{error_token}/getMe", timeout=10)
            if me_resp2.status_code == 200 and me_resp2.json().get("ok"):
                error_bot_user = me_resp2.json().get("result", {}).get("username", "bot")
                test_text2 = (
                    "⚠️ <b>Error & Warning Alert Bot - Connected</b>\n\n"
                    "✅ All site scraping errors, 403 blocks, and catalog warnings will be sent to this chat!"
                )
                e_resp = requests.post(
                    f"https://api.telegram.org/bot{error_token}/sendMessage",
                    json={"chat_id": error_chat, "text": test_text2, "parse_mode": "HTML"},
                    timeout=10,
                )
                e_data = e_resp.json()
                if e_resp.status_code == 200 and e_data.get("ok"):
                    results.append(f"Error Bot (@{error_bot_user}) -> Chat {error_chat}: Connected successfully")
                else:
                    results.append(f"Error Bot (@{error_bot_user}) warning: {e_data.get('description', e_resp.text)}")
        except Exception as exc:
            results.append(f"Error Bot connection warning: {exc}")

    return True, "\n".join(results)


def build_site_status_change_message(
    site: str,
    old_status: str,
    new_status: str,
    details: str = "",
) -> str:
    """Build an admin notification message when a site's health status changes.

    Sent ONLY on state change (e.g. ok -> degraded, ok -> down, degraded -> ok).
    Produces a 'Recovered' alert when status returns to ok.

    Args:
        site: Store name.
        old_status: Previous health status ('ok', 'degraded', 'down', 'suspicious').
        new_status: Current health status.
        details: Additional context (e.g. failure percentage, reason).

    Returns:
        Formatted HTML string for the admin alert.
    """
    escaped_site = escape_html(site)
    escaped_details = escape_html(details)

    if new_status == "ok":
        lines = [
            f"🟢 <b>Site Recovered: {escaped_site}</b>",
            "",
            f"Status has returned to <b>OK</b> (previously: <i>{old_status}</i>).",
        ]
        if escaped_details:
            lines.append(f"Details: {escaped_details}")
        return "\n".join(lines)
    else:
        status_emoji = "🔴" if new_status == "down" else "⚠️"
        lines = [
            f"{status_emoji} <b>Site Health Status Change: {escaped_site}</b>",
            "",
            f"Status changed from <b>{old_status}</b> ➔ <b>{new_status.upper()}</b>.",
        ]
        if escaped_details:
            lines.append(f"Context: {escaped_details}")
        return "\n".join(lines)


def build_heartbeat_message(
    utc_date: str,
    sites_total: int,
    sites_ok: int,
    sites_degraded: int,
    sites_down: int,
    active_variants: int = 0,
) -> str:
    """Build daily heartbeat status message for the admin chat.

    Dispatched once per calendar day at or after heartbeat_hour_utc.

    Args:
        utc_date: Current UTC date string (YYYY-MM-DD).
        sites_total: Total configured sites monitored.
        sites_ok: Sites currently in OK status.
        sites_degraded: Sites currently in degraded status.
        sites_down: Sites currently down.
        active_variants: Total active products/variants monitored in catalog.

    Returns:
        Formatted HTML heartbeat message.
    """
    return (
        f"💓 <b>Price Monitor Heartbeat</b> (UTC Date: <code>{utc_date}</code>)\n\n"
        f"• <b>Monitored Sites</b>: {sites_total}\n"
        f"  - ✅ OK: {sites_ok}\n"
        f"  - ⚠️ Degraded: {sites_degraded}\n"
        f"  - 🔴 Down: {sites_down}\n"
        f"• <b>Catalog Variants</b>: {active_variants} active\n"
        f"• <b>Status</b>: Monitoring service operational."
    )


def build_crash_alert_message(error_text: str) -> str:
    """Build an admin alert for a fatal unhandled crash of the entire run.

    Never exposes bot tokens or credentials.

    Args:
        error_text: Exception message or traceback.

    Returns:
        Formatted HTML message.
    """
    clean_err = escape_html(error_text)
    return (
        f"🚨 <b>Fatal Crash Alert: Price Monitor</b>\n\n"
        f"The monitoring run crashed unexpectedly:\n"
        f"<code>{clean_err[:3000]}</code>"
    )


def build_delivery_failure_alert(target_chat_name: str, error_text: str) -> str:
    """Build an admin alert when team message delivery fails.

    Args:
        target_chat_name: Identifier for the failing chat.
        error_text: Error message.

    Returns:
        Formatted HTML message.
    """
    clean_err = escape_html(error_text)
    return (
        f"⚠️ <b>Price Alert Delivery Failed to {escape_html(target_chat_name)}</b>\n\n"
        f"Team alerts could not be sent. Events will be held and retried next run.\n"
        f"Reason: <code>{clean_err[:1500]}</code>"
    )
