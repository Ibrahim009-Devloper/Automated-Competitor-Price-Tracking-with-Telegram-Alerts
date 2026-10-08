"""Orchestrator to run monitoring cycles across configured e-commerce sites."""

import csv
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import yaml

from monitor.adapters import create_adapter as _create_adapter
from monitor.adapters.base import SiteAdapter
from monitor.detector import detect
from monitor.models import FetchResult
from monitor.notifier import (
    build_delivery_failure_alert,
    build_error_message,
    build_heartbeat_message,
    build_message,
    build_new_variants_summary,
    build_site_status_change_message,
    escape_html,
    send_error_message,
    send_message,
)
from monitor import storage
from monitor.utils.money import cents_to_str
from monitor.validator import validate

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.getenv("CONFIG_PATH", "config/sites.yaml")


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load and parse sites and alerts configuration from YAML file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Dict[str, Any]: Parsed configuration dictionary.

    Raises:
        FileNotFoundError: If configuration file does not exist.
        yaml.YAMLError: If YAML content cannot be parsed.
    """
    path = Path(config_path or DEFAULT_CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path.resolve()}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data


def _get_active_target_urls_from_csv(
    site_name: str, targets_path: str = "config/targets.csv"
) -> List[str]:
    """Read target URLs for a store from targets.csv if available.

    Args:
        site_name: Store name to filter targets for.
        targets_path: Path to targets CSV file.

    Returns:
        List of target URL strings.
    """
    path = Path(targets_path)
    if not path.exists():
        return []

    active_urls: List[str] = []
    seen = set()
    try:
        with open(path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                s_name = (row.get("site") or "").strip()
                if s_name.lower() == site_name.strip().lower():
                    url = (row.get("url") or "").strip()
                    if url:
                        norm = url.split("?")[0].rstrip("/").lower()
                        if norm in seen:
                            logger.warning(
                                "[%s] Duplicate URL found in %s: '%s'. Processing once.",
                                site_name,
                                targets_path,
                                url,
                            )
                            continue
                        seen.add(norm)
                        active_urls.append(url)
    except Exception as exc:
        logger.error("Error reading targets from %s: %s", path, exc)

    return active_urls


def create_adapter(site_config: Dict[str, Any]) -> SiteAdapter:
    """Factory to instantiate the appropriate SiteAdapter subclass lazily."""
    return _create_adapter(site_config)


def run_once(
    config_path: Optional[str] = None,
    site_filter: Optional[str] = None,
    db_path: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute a single price monitoring cycle across configured sites.

    1. Checks if price_checks is empty to establish baseline (creates no events).
    2. Loads alerts thresholds and reliability configuration.
    3. Fetches stores, classifies errors, records health (runs, site_runs, errors),
       evaluates confirmed absence and delisted/relisted events.
    4. Dispatches state-change admin alerts and daily heartbeat.
    5. Dispatches Telegram notifications for unnotified events.

    Args:
        config_path: Optional path to sites.yaml.
        site_filter: Optional store name filter (case-insensitive substring match).
        db_path: Optional path to prices.db SQLite database.
        dry_run: If True, prints notifications to console instead of sending.

    Returns:
        Dict[str, Any]: Run statistics dictionary including detected events.
    """
    config = load_config(config_path)
    sites: List[Dict[str, Any]] = config.get("sites", [])

    # Read min price change threshold (default: 0)
    alerts_cfg = config.get("alerts", {})
    min_change_cents = int(alerts_cfg.get("min_price_change_cents", 0))
    suspicious_change_percent = float(alerts_cfg.get("suspicious_change_percent", 80.0))

    # Reliability configuration with safe defaults
    rel_cfg = config.get("reliability", {})
    retries = int(rel_cfg.get("retries", 3))
    backoff_seconds = float(rel_cfg.get("backoff_seconds", 1.0))
    missing_runs_before_delisted = int(rel_cfg.get("missing_runs_before_delisted", 3))
    degraded_failure_percent = float(rel_cfg.get("degraded_failure_percent", 20.0))
    suspicious_drop_percent = float(rel_cfg.get("suspicious_drop_percent", 50.0))
    heartbeat_hour_utc = int(rel_cfg.get("heartbeat_hour_utc", 8))

    # Timing safety: max_run_minutes (default: 20)
    env_max_minutes = os.getenv("MAX_RUN_MINUTES")
    if env_max_minutes:
        try:
            max_run_minutes = float(env_max_minutes)
        except ValueError:
            max_run_minutes = 20.0
    else:
        max_run_minutes = float(rel_cfg.get("max_run_minutes") or config.get("max_run_minutes") or 20.0)
    max_run_seconds = max_run_minutes * 60.0
    run_start_time = time.monotonic()

    def is_timed_out() -> bool:
        return (time.monotonic() - run_start_time) >= max_run_seconds

    if site_filter:
        filter_lower = site_filter.strip().lower()
        sites = [
            s for s in sites
            if filter_lower in s.get("name", "").lower()
        ]
        if not sites:
            logger.warning("No sites matched filter '%s'. Exiting run.", site_filter)

    # CI Guard: Never silently fall back to SQLite when running in CI
    is_ci = os.getenv("CI", "").strip().lower() in ("true", "1", "yes") or bool(os.getenv("GITHUB_ACTIONS"))
    if is_ci and not os.getenv("DATABASE_URL") and not db_path:
        raise RuntimeError("DATABASE_URL is required in CI (SQLite does not persist in Actions)")

    # Initialize database backend (Postgres if DATABASE_URL set, else SQLite)
    try:
        db_store = storage.get_storage(db_path=db_path)
        db_store.init_db()
    except Exception as db_err:
        err_msg = f"Database initialization failed: {db_err}"
        logger.error(err_msg)
        try:
            send_error_message(f"🚨 <b>Database Failure Alert:</b>\n<code>{escape_html(err_msg)}</code>")
        except Exception:
            pass
        raise

    # Concurrency control: prevent overlapping runs (Postgres advisory lock / SQLite lockfile)
    if not db_store.acquire_lock():
        logger.info("another run in progress")
        print("another run in progress")
        return {"status": "locked", "message": "another run in progress"}

    conn = db_store

    # Baseline check - if price_checks is empty, do not create any events
    is_baseline = storage.is_price_checks_empty(conn)
    if is_baseline:
        print("Baseline run: no events created")
        logger.info("Baseline run: price_checks is empty. No events will be created.")

    # Record start of run in runs table
    run_id = storage.record_run_start(conn)

    stats: Dict[str, Any] = {
        "sites_total": len(sites),
        "sites_ok": 0,
        "sites_failed": 0,
        "variants_seen": 0,
        "new_variants": 0,
        "checks_saved": 0,
        "events_created": 0,
        "events": [],
        "newly_added_variants": [],
        "is_baseline": is_baseline,
        "telegram_status": "Not run",
        "errors": [],
    }

    try:
        for site_idx, site_cfg in enumerate(sites):
            # Timing safety check before starting site
            if is_timed_out():
                logger.warning(
                    "Price monitor reached max_run_minutes limit (%.1f mins). Stopping gracefully.",
                    max_run_minutes,
                )
                for rem_cfg in sites[site_idx:]:
                    rem_name = rem_cfg.get("name", "Unnamed Site")
                    storage.record_site_run(
                        conn=conn,
                        run_id=run_id,
                        site=rem_name,
                        status="skipped_timeout",
                        urls_total=0,
                        urls_failed=0,
                        observations_count=0,
                        prev_observations_count=0,
                        error_summary=f"Skipped due to run timeout limit ({max_run_minutes:.0f}m)",
                    )
                timeout_alert = (
                    f"⏱️ <b>Price Monitor Timeout Alert</b>\n"
                    f"Run reached the <b>{max_run_minutes:.0f} minute</b> time limit.\n"
                    f"The runner stopped gracefully. Remaining {len(sites) - site_idx} site(s) were marked as <code>skipped_timeout</code>."
                )
                if not dry_run:
                    try:
                        send_error_message(timeout_alert)
                    except Exception as alert_err:
                        logger.warning("Could not send timeout alert to admin: %s", alert_err)
                else:
                    logger.info("Dry-run: Timeout alert: %s", timeout_alert)
                break

            site_name = site_cfg.get("name", "Unnamed Site")
            logger.info("--- Processing site: %s ---", site_name)

            # Apply defaults to site config
            site_cfg_merged = dict(site_cfg)
            site_cfg_merged.setdefault("max_retries", retries)
            site_cfg_merged.setdefault("backoff_seconds", backoff_seconds)

            try:
                adapter = create_adapter(site_cfg_merged)
                if hasattr(adapter, "is_timed_out"):
                    adapter.is_timed_out = is_timed_out
                fetch_result: FetchResult = adapter.fetch()

                if fetch_result.errors:
                    stats["errors"].extend(fetch_result.errors)

                # Persist classified errors to the errors table
                for err_rec in getattr(fetch_result, "error_records", []):
                    storage.insert_error_record(
                        conn=conn,
                        site=site_name,
                        error_type=err_rec.error_type,
                        message=err_rec.message,
                        url=err_rec.url,
                        run_id=run_id,
                    )

                # Deactivate variants whose URLs were removed from targets.csv
                active_urls = []
                if hasattr(adapter, "load_target_urls"):
                    try:
                        active_targets = adapter.load_target_urls()
                        active_urls = [t["url"] for t in active_targets if t.get("url")]
                    except Exception as err:
                        logger.warning("Error checking active targets for '%s': %s", site_name, err)
                else:
                    active_urls = _get_active_target_urls_from_csv(
                        site_name, site_cfg.get("targets_path", "config/targets.csv")
                    )

                if active_urls:
                    storage.deactivate_removed_variants(conn, site_name, active_urls)

                # Determine active variant IDs recorded in DB for this site
                existing_db_variants = set(
                    storage.get_variant_ids_for_site(conn, site_name, active_only=True)
                )
                current_fetched_ids = {str(obs.variant_id) for obs in fetch_result.observations}

                # Rule 1 & 3: Identify confirmed absences
                confirmed_absent_ids = set()
                adapter_name = site_cfg.get("adapter", "").strip().lower()

                # Case A: Successful Shopify /products.json catalog fetch that returned products
                is_full_catalog = getattr(fetch_result, "is_full_catalog_fetch", False)
                # Successful products.json fetch: valid JSON, non-empty list, no fetch errors
                if adapter_name == "shopify" and (is_full_catalog or (not site_cfg.get("urls") and not fetch_result.errors)) and len(fetch_result.observations) > 0:
                    confirmed_absent_ids = existing_db_variants - current_fetched_ids
                else:
                    # Case B: Confirmed absent URLs (404/410 on product page)
                    absent_refs = getattr(fetch_result, "confirmed_absent_variant_ids", [])
                    for aref in absent_refs:
                        if aref in existing_db_variants:
                            confirmed_absent_ids.add(aref)
                            # Match variants by URL substring
                            for vid in storage.find_active_variant_ids_by_url_substr(conn, site_name, aref):
                                confirmed_absent_ids.add(vid)

                # Process delisting and relisting (only outside baseline)
                site_delist_events: List[Dict[str, Any]] = []
                if not is_baseline:
                    site_delist_events = storage.process_presence_and_delisting(
                        conn=conn,
                        site=site_name,
                        seen_variant_ids=list(current_fetched_ids),
                        confirmed_absent_ids=list(confirmed_absent_ids),
                        missing_runs_before_delisted=missing_runs_before_delisted,
                        fetched_at=datetime.now(timezone.utc),
                    )

                # Persist observations & events for this site in a single transaction
                site_variants_seen = 0
                site_new_variants = 0
                site_checks_saved = 0
                site_events_created = len(site_delist_events)
                stats["events"].extend(site_delist_events)

                with conn:
                    # Pre-load catalog and previous checks for this site in single fast queries
                    if is_baseline:
                        site_catalog_vids = set()
                        site_last_checks = {}
                    else:
                        site_catalog_vids = storage.get_site_variant_ids(conn, site_name)
                        site_last_checks = storage.get_site_latest_checks(conn, site_name)

                    valid_observations = []
                    events_to_create = []

                    for obs in fetch_result.observations:
                        vid_str = str(obs.variant_id)
                        prev_check = site_last_checks.get(vid_str)

                        # Validation gate
                        ok, reason = validate(
                            observation=obs,
                            previous=prev_check,
                            suspicious_change_percent=suspicious_change_percent,
                        )
                        if not ok:
                            err_msg = f"Invalid observation for {obs.url or obs.variant_id}: {reason}"
                            logger.error("[%s] %s", site_name, err_msg)
                            stats["errors"].append(err_msg)
                            storage.insert_error_record(
                                conn=conn,
                                site=site_name,
                                error_type="validation_failed",
                                message=err_msg,
                                url=obs.url,
                                run_id=run_id,
                            )
                            continue

                        valid_observations.append(obs)
                        was_in_catalog = vid_str in site_catalog_vids

                        if not was_in_catalog:
                            site_new_variants += 1
                            site_catalog_vids.add(vid_str)
                            if not is_baseline:
                                stats["newly_added_variants"].append(obs)

                        # Detect events if not a baseline run
                        if not is_baseline:
                            if not was_in_catalog:
                                # First time seen: silent baseline
                                iso_ts = (
                                    obs.fetched_at.isoformat()
                                    if hasattr(obs.fetched_at, "isoformat")
                                    else str(obs.fetched_at)
                                )
                                val_id = (
                                    int(obs.variant_id)
                                    if str(obs.variant_id).isdigit()
                                    else obs.variant_id
                                )
                                ev_dict = {
                                    "variant_id": val_id,
                                    "detected_at": iso_ts,
                                    "event_type": "new_variant",
                                    "old_value": None,
                                    "new_value": obs.price_cents,
                                    "product_title": obs.product_title,
                                    "variant_title": obs.variant_title,
                                    "site": obs.site,
                                    "notified": 1,
                                }
                                events_to_create.append(ev_dict)
                                stats["events"].append(ev_dict)
                                site_events_created += 1
                            else:
                                detected_events = detect(
                                    previous=prev_check,
                                    current=obs,
                                    min_change_cents=min_change_cents,
                                )
                                for ev in detected_events:
                                    events_to_create.append(ev)
                                    stats["events"].append(ev)
                                    site_events_created += 1

                    # Batch persist valid observations, checks, and events in fast multi-row operations
                    if valid_observations:
                        storage.batch_upsert_variants(conn, valid_observations)
                        storage.batch_insert_price_checks(conn, valid_observations)
                        site_checks_saved += len(valid_observations)
                        site_variants_seen += len(valid_observations)

                    if events_to_create:
                        storage.batch_insert_events(conn, events_to_create)

                # -------------------------------------------------------------
                # Site Health Evaluation (Rule 5 & 6)
                # -------------------------------------------------------------
                prev_state = storage.get_site_state(conn, site_name)
                prev_obs = prev_state.get("last_observations_count", 0) if prev_state else 0

                urls_total = len(active_urls) if active_urls else (len(site_cfg.get("urls", [])) or 1)
                urls_failed = len(fetch_result.errors)

                if urls_total > 1:
                    urls_failed = min(urls_total, urls_failed)
                else:
                    urls_failed = 1 if (len(fetch_result.observations) == 0 and urls_failed > 0) else 0

                # Compute health status
                if urls_total > 0 and urls_failed >= urls_total and len(fetch_result.observations) == 0:
                    site_status = "down"
                elif urls_total > 0 and ((urls_failed / urls_total) * 100.0) > degraded_failure_percent:
                    site_status = "degraded"
                elif prev_obs > 0 and len(fetch_result.observations) < (prev_obs * (1.0 - (suspicious_drop_percent / 100.0))):
                    site_status = "suspicious"
                else:
                    site_status = "ok"

                # Record site run metrics
                err_summary = "; ".join(fetch_result.errors[:2]) if fetch_result.errors else None
                storage.record_site_run(
                    conn=conn,
                    run_id=run_id,
                    site=site_name,
                    status=site_status,
                    urls_total=urls_total,
                    urls_failed=urls_failed,
                    observations_count=len(fetch_result.observations),
                    prev_observations_count=prev_obs,
                    error_summary=err_summary,
                )

                # Admin alert on site status CHANGE only
                if prev_state and prev_state.get("last_status"):
                    old_status = prev_state.get("last_status")
                    if site_status != old_status:
                        context_msg = f"{urls_failed}/{urls_total} failed URLs; {len(fetch_result.observations)} items fetched"
                        change_msg = build_site_status_change_message(site_name, old_status, site_status, details=context_msg)
                        if not dry_run:
                            send_error_message(change_msg)
                        storage.upsert_site_state(
                            conn, site_name, site_status, len(fetch_result.observations), last_notified_status=site_status
                        )
                    else:
                        storage.upsert_site_state(conn, site_name, site_status, len(fetch_result.observations))
                else:
                    storage.upsert_site_state(
                        conn, site_name, site_status, len(fetch_result.observations), last_notified_status=site_status
                    )

                if site_status in ("ok", "degraded", "suspicious"):
                    stats["sites_ok"] += 1
                else:
                    stats["sites_failed"] += 1

                stats["variants_seen"] += site_variants_seen
                stats["new_variants"] += site_new_variants
                stats["checks_saved"] += site_checks_saved
                stats["events_created"] += site_events_created

                logger.info(
                    "Completed '%s' [%s]: %d variants seen, %d checks saved, %d events",
                    site_name,
                    site_status,
                    site_variants_seen,
                    site_checks_saved,
                    site_events_created,
                )

            except Exception as exc:
                stats["sites_failed"] += 1
                err_msg = f"Site '{site_name}' failed: {exc}"
                logger.exception(err_msg)
                stats["errors"].append(err_msg)
                storage.insert_error_record(
                    conn=conn,
                    site=site_name,
                    error_type="blocked" if "403" in str(exc) else "network",
                    message=err_msg,
                    run_id=run_id,
                )
                prev_state = storage.get_site_state(conn, site_name)
                old_status = prev_state.get("last_status", "ok") if prev_state else "ok"
                storage.record_site_run(
                    conn=conn,
                    run_id=run_id,
                    site=site_name,
                    status="down",
                    urls_total=1,
                    urls_failed=1,
                    observations_count=0,
                    prev_observations_count=0,
                    error_summary=str(exc),
                )
                if old_status != "down":
                    change_alert = build_site_status_change_message(site_name, old_status, "down", details=str(exc))
                    if not dry_run:
                        send_error_message(change_alert)
                    storage.upsert_site_state(conn, site_name, "down", 0, last_notified_status="down")
                else:
                    storage.upsert_site_state(conn, site_name, "down", 0)

        # ---------------------------------------------------------------------
        # Telegram Notification Step
        # ---------------------------------------------------------------------
        new_variants_summary_msg = None
        if not is_baseline and stats["newly_added_variants"]:
            new_variants_summary_msg = build_new_variants_summary(stats["newly_added_variants"])

        # Unnotified events (notified = 0) including delisted / relisted in one section
        unnotified = [] if is_baseline else storage.get_unnotified_events(conn)
        notification_messages = build_message(unnotified) if unnotified else []

        all_team_messages = list(notification_messages)
        if new_variants_summary_msg:
            all_team_messages.append(new_variants_summary_msg)

        if not all_team_messages:
            if is_baseline:
                stats["telegram_status"] = "Skipped (baseline run - initializing catalog)"
            else:
                stats["telegram_status"] = "Skipped (no change events detected)"
        else:
            if dry_run:
                stats["telegram_status"] = f"Dry-run mode ({len(all_team_messages)} message(s) printed to terminal, not sent)"
                print("\n" + "=" * 60)
                print("         TELEGRAM NOTIFICATION (DRY RUN - NOT SENT)")
                print("=" * 60)
                for idx, msg in enumerate(all_team_messages, 1):
                    if len(all_team_messages) > 1:
                        print(f"--- [Message Part {idx}/{len(all_team_messages)}] ---")
                    try:
                        print(msg)
                    except UnicodeEncodeError:
                        print(msg.encode("ascii", errors="replace").decode("ascii"))
                print("=" * 60 + "\n")
            else:
                try:
                    price_sent_ok = True
                    for msg in notification_messages:
                        if not send_message(msg):
                            price_sent_ok = False
                            break

                    summary_sent_ok = True
                    if new_variants_summary_msg:
                        summary_sent_ok = send_message(new_variants_summary_msg)

                    prev_team_delivery = storage.get_meta(conn, "team_delivery_status") or "ok"

                    # Rule 5: If team notification fails, keep events notified = 0 and alert admin once
                    if notification_messages and price_sent_ok:
                        notified_ids = [e["id"] for e in unnotified]
                        storage.mark_events_notified(conn, notified_ids)
                        logger.info(
                            "Delivered Telegram alert and marked %d event(s) as notified.",
                            len(notified_ids),
                        )
                        if prev_team_delivery == "failed":
                            storage.set_meta(conn, "team_delivery_status", "ok")
                            send_error_message(
                                "🟢 <b>Team Notification Delivery Recovered</b>\nPrice alerts are delivering successfully again."
                            )
                    elif notification_messages and not price_sent_ok:
                        # Failed: keep events notified = 0, alert admin once on state change
                        if prev_team_delivery != "failed":
                            storage.set_meta(conn, "team_delivery_status", "failed")
                            fail_alert = build_delivery_failure_alert(
                                "Team Chat",
                                f"Failed to send {len(notification_messages)} price alert message(s)."
                            )
                            send_error_message(fail_alert)

                    status_parts = []
                    if notification_messages:
                        status_parts.append(
                            f"✅ Sent {len(notification_messages)} price alert(s)"
                            if price_sent_ok
                            else "❌ Price alerts failed (held for retry)"
                        )
                    if new_variants_summary_msg:
                        status_parts.append(
                            "🆕 Sent new products summary"
                            if summary_sent_ok
                            else "❌ New products summary failed"
                        )
                    stats["telegram_status"] = " | ".join(status_parts)

                except Exception as err:
                    stats["telegram_status"] = f"❌ Exception during delivery: {err}"
                    logger.exception("Unexpected error during Telegram notification: %s", err)

        # ---------------------------------------------------------------------
        # Daily Heartbeat to Admin Chat (Rule 8)
        # ---------------------------------------------------------------------
        now_utc = datetime.now(timezone.utc)
        if now_utc.hour >= heartbeat_hour_utc:
            today_str = now_utc.strftime("%Y-%m-%d")
            last_hb = storage.get_meta(conn, "last_heartbeat_date")
            if last_hb != today_str:
                latest_statuses = storage.get_latest_site_statuses(conn)
                ok_cnt = sum(1 for s in latest_statuses if s.get("last_status") == "ok")
                deg_cnt = sum(1 for s in latest_statuses if s.get("last_status") == "degraded")
                down_cnt = sum(1 for s in latest_statuses if s.get("last_status") == "down")
                active_vars = sum(s.get("active_variants", 0) for s in latest_statuses)
                hb_msg = build_heartbeat_message(
                    utc_date=today_str,
                    sites_total=len(sites),
                    sites_ok=ok_cnt,
                    sites_degraded=deg_cnt,
                    sites_down=down_cnt,
                    active_variants=active_vars,
                )
                if not dry_run:
                    hb_sent = send_error_message(hb_msg)
                    if hb_sent:
                        storage.set_meta(conn, "last_heartbeat_date", today_str)
                        logger.info("Dispatched daily heartbeat to admin chat for %s", today_str)
                else:
                    logger.info("Dry-run: Heartbeat message generated for %s:\n%s", today_str, hb_msg)

        # Record finish in runs table
        run_finish_status = "success" if stats["sites_failed"] == 0 else ("failed" if stats["sites_ok"] == 0 else "degraded")
        storage.record_run_finish(
            conn=conn,
            run_id=run_id,
            status=run_finish_status,
            sites_total=stats["sites_total"],
            sites_ok=stats["sites_ok"],
            sites_failed=stats["sites_failed"],
            variants_seen=stats["variants_seen"],
            events_created=stats["events_created"],
        )

    finally:
        if hasattr(conn, "release_lock"):
            try:
                conn.release_lock()
            except Exception:
                pass
        conn.close()

    # Print run summary and detected events
    _print_summary(stats)
    return stats


def print_health_summary(
    config_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Print the latest status per site without writing to the database (Rule 9).

    Args:
        config_path: Path to sites.yaml config.
        db_path: Path to SQLite database file.
    """
    store = storage.get_storage(db_path=db_path)
    if isinstance(store, storage.SqliteStorage):
        if not os.path.exists(store.db_path):
            print(f"\n❌ Database not found at '{store.db_path}'. Run a monitoring cycle first.\n")
            return

    stale_after_hours = 36.0
    try:
        cfg = load_config(config_path)
        stale_after_hours = float(cfg.get("reliability", {}).get("stale_after_hours", 36))
    except Exception:
        pass

    try:
        statuses = store.get_latest_site_statuses()
        print("\n" + "=" * 70)
        print("                 STORE HEALTH & STATUS REPORT (READ-ONLY)")
        print("=" * 70)
        if not statuses:
            print("  No store health records found yet in database.")
        else:
            header = f"{'Store Name':<32} {'Status':<18} {'Active Vars':<14} {'Last Run'}"
            print(header)
            print("-" * 70)
            now_utc = datetime.now(timezone.utc)
            for s in statuses:
                st = (s.get("last_status") or "unknown").upper()
                if st == "OK":
                    icon_st = "✅ OK"
                elif st == "DEGRADED":
                    icon_st = "⚠️ DEGRADED"
                elif st == "DOWN":
                    icon_st = "🔴 DOWN"
                elif st == "SUSPICIOUS":
                    icon_st = "⚠️ SUSPICIOUS"
                else:
                    icon_st = f"❓ {st}"

                last_run_raw = s.get("last_run_at")
                if last_run_raw:
                    try:
                        lr_clean = str(last_run_raw).replace("Z", "+00:00")
                        lr_dt = datetime.fromisoformat(lr_clean)
                        if lr_dt.tzinfo is None:
                            lr_dt = lr_dt.replace(tzinfo=timezone.utc)
                        age_hours = (now_utc - lr_dt).total_seconds() / 3600.0
                        if age_hours > stale_after_hours:
                            icon_st += " (STALE)"
                    except Exception:
                        pass

                last_run = last_run_raw or "N/A"
                if "T" in str(last_run):
                    last_run = str(last_run).split(".")[0].replace("T", " ")

                print(
                    f"{s.get('site', 'Unknown')[:30]:<32} "
                    f"{icon_st:<18} "
                    f"{s.get('active_variants', 0):<14} "
                    f"{last_run}"
                )
        print("=" * 70 + "\n")
    finally:
        store.close()


def _print_summary(stats: Dict[str, Any]) -> None:
    """Print an easy-to-read summary of the monitoring run and detected events."""
    summary_lines = [
        "",
        "=" * 60,
        "                PRICE MONITOR RUN SUMMARY",
        "=" * 60,
        f"  Sites Total     : {stats['sites_total']}",
        f"  Sites OK        : {stats['sites_ok']}",
        f"  Sites Failed    : {stats['sites_failed']}",
        f"  Variants Seen   : {stats['variants_seen']}",
        f"  New Variants    : {stats['new_variants']}",
        f"  Checks Saved    : {stats['checks_saved']}",
        f"  Events Created  : {stats['events_created']}",
        f"  Telegram Status : {stats.get('telegram_status', 'N/A')}",
        "=" * 60,
    ]

    # Print event details
    if stats.get("is_baseline"):
        summary_lines.append("  Baseline run: no events created")
        summary_lines.append("=" * 60)
    elif stats["events"]:
        summary_lines.append(f"  DETECTED CHANGE EVENTS ({len(stats['events'])}):")
        for ev in stats["events"]:
            etype = ev["event_type"]
            prod = ev.get("product_title", "Unknown Product")
            var_title = ev.get("variant_title", "")
            title_display = f"{prod} ({var_title})" if var_title and var_title != "Default Title" else prod

            if etype in ("price_drop", "price_increase"):
                old_str = cents_to_str(ev["old_value"])
                new_str = cents_to_str(ev["new_value"])
                summary_lines.append(f"    • [{etype}] {title_display}")
                summary_lines.append(f"      Price: {old_str} -> {new_str}")
            elif etype == "out_of_stock":
                summary_lines.append(f"    • [out_of_stock] {title_display}")
                summary_lines.append("      Stock: In Stock -> Out of Stock")
            elif etype == "back_in_stock":
                summary_lines.append(f"    • [back_in_stock] {title_display}")
                summary_lines.append("      Stock: Out of Stock -> In Stock")
            elif etype == "new_variant":
                price_display = cents_to_str(ev["new_value"])
                summary_lines.append(f"    • [new_variant] {title_display}")
                summary_lines.append(f"      New variant added (Price: {price_display})")
            else:
                summary_lines.append(f"    • [{etype}] {title_display} (old: {ev['old_value']} -> new: {ev['new_value']})")
        summary_lines.append("=" * 60)

    if stats["errors"]:
        summary_lines.append("  Warnings / Errors encountered:")
        for err in stats["errors"]:
            summary_lines.append(f"    - {err}")
        summary_lines.append("=" * 60)

    summary_lines.append("")
    print("\n".join(summary_lines))


def check_single_url(
    url: str,
    site_name: str,
    config_path: Optional[str] = None,
) -> None:
    """Fetch a single product URL using its configured adapter without modifying the database.

    Requirement 4: Fetches the page using the configured adapter and prints title,
    variants, prices, availability, and any errors, WITHOUT writing anything to the database.

    Args:
        url: Direct product page URL to inspect.
        site_name: Store name matching one of the configured sites in sites.yaml.
        config_path: Optional custom path to YAML config (defaults to config/sites.yaml).
    """
    config = load_config(config_path)
    sites = config.get("sites", [])

    matched_site = None
    for s in sites:
        if (s.get("name") or "").strip().lower() == site_name.strip().lower():
            matched_site = dict(s)
            break

    if not matched_site:
        available_names = [s.get("name") for s in sites if s.get("name")]
        print(f"\n❌ Error: Store '{site_name}' not found in configuration.")
        if available_names:
            print(f"Available sites: {', '.join(available_names)}\n")
        return

    # Direct URL inspection without touching database
    matched_site["urls"] = [url]
    adapter = create_adapter(matched_site)

    logger.info("Executing single URL check for site '%s': %s", matched_site.get("name"), url)
    fetch_result: FetchResult = adapter.fetch()

    print("\n" + "=" * 60)
    print("           SINGLE URL INSPECTION (NO DATABASE CHANGES)")
    print("=" * 60)
    print(f"  Target URL : {url}")
    print(f"  Site Name  : {matched_site.get('name')}")
    print(f"  Adapter    : {matched_site.get('adapter')}")
    print("=" * 60)

    if fetch_result.observations:
        print(f"\nExtracted {len(fetch_result.observations)} variant(s):\n")
        for i, obs in enumerate(fetch_result.observations, 1):
            price_display = cents_to_str(obs.price_cents) if obs.price_cents is not None else "N/A"
            compare_display = cents_to_str(obs.compare_at_cents) if obs.compare_at_cents is not None else "N/A"
            stock_status = "In Stock" if obs.available else "Out of Stock"

            print(f"  [{i}] Product Title : {obs.product_title}")
            print(f"      Variant Title : {obs.variant_title or '(Default)'}")
            print(f"      Variant ID    : {obs.variant_id}")
            print(f"      Price         : {price_display} {obs.currency}")
            if obs.compare_at_cents is not None:
                print(f"      Compare Price : {compare_display} {obs.currency}")
            print(f"      Availability  : {stock_status}")
            print(f"      URL           : {obs.url}")
            print("  " + "-" * 56)
    else:
        print("\n  No product variants or details could be extracted.")

    if fetch_result.errors:
        print("\nWarnings / Errors Encountered:")
        for err in fetch_result.errors:
            print(f"  ❌ {err}")

    print("=" * 60 + "\n")


def __getattr__(name: str) -> Any:
    """Lazy module attribute resolver for backwards compatibility with tests and callers."""
    if name == "ShopifyAdapter":
        from monitor.adapters.shopify import ShopifyAdapter
        return ShopifyAdapter
    if name == "JsonLdAdapter":
        from monitor.adapters.jsonld import JsonLdAdapter
        return JsonLdAdapter
    if name == "PlaywrightAdapter":
        from monitor.adapters.playwright import PlaywrightAdapter
        return PlaywrightAdapter
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

