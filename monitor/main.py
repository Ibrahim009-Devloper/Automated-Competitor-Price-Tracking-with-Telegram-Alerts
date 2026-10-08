"""Command-line entry point for the price monitoring bot.

Usage:
    python -m monitor.main
    python -m monitor.main --site "Soko Glam"
    python -m monitor.main --dry-run
    python -m monitor.main --config config/sites.yaml --db prices.db --log-level DEBUG
"""

import argparse
import sys
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from monitor.runner import run_once
from monitor.utils.logging_setup import setup_logging


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="python -m monitor.main",
        description="E-commerce Price Monitoring Bot - Monitors Shopify catalogs and sends Telegram alerts.",
    )
    parser.add_argument(
        "--site",
        type=str,
        default=None,
        help="Optional name filter to run only one specific store (e.g. --site 'Soko Glam')",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/sites.yaml",
        help="Path to YAML configuration file (default: config/sites.yaml)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to SQLite database file (default: prices.db, overridden if DATABASE_URL is set)",
    )
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test notification to Telegram to verify bot token and chat ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print Telegram alert messages to console without sending, leaving events unnotified",
    )
    parser.add_argument(
        "--check-url",
        type=str,
        default=None,
        help="Fetch and inspect a single product page using its configured adapter without modifying the database",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Print the latest status per site without writing to the database",
    )
    parser.add_argument(
        "--db-check",
        action="store_true",
        help="Connect to configured database, print backend type, version, latency, and row counts without writing or revealing credentials",
    )
    parser.add_argument(
        "--ci-check",
        action="store_true",
        help="Run pre-flight CI environment, database, and Playwright verification without fetching any site",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    return parser.parse_args(args)


def main() -> None:
    """Main execution function."""
    # Ensure stdout/stderr safely handle UTF-8 symbols and emojis on Windows
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = parse_args()
    setup_logging(log_level=args.log_level)

    if args.test_telegram:
        from monitor.notifier import test_connection
        print("\nTesting Telegram bot connection...")
        success, message = test_connection()
        if success:
            print(f"✅ {message}\n")
            sys.exit(0)
        else:
            print(f"❌ {message}\n", file=sys.stderr)
            sys.exit(1)

    if args.health:
        from monitor.runner import print_health_summary
        print_health_summary(config_path=args.config, db_path=args.db)
        sys.exit(0)

    if args.db_check:
        from monitor import storage
        try:
            store = storage.get_storage(db_path=args.db)
            health = store.check_health()
            store.close()

            print("\n" + "=" * 60)
            print("             DATABASE DIAGNOSTIC CHECK (--db-check)")
            print("=" * 60)
            print(f"Backend Type  : {health.get('backend', 'Unknown').upper()}")
            print(f"Server Version: {health.get('version', 'Unknown')}")
            print(f"Latency       : {health.get('latency_ms', 0.0):.2f} ms")
            print(f"Database/Host : {health.get('host_or_path', 'N/A')}")
            print("-" * 60)
            print("Table Row Counts:")
            counts = health.get("row_counts", {})
            if counts:
                for tbl, cnt in counts.items():
                    print(f"  • {tbl:<20}: {cnt:>8,} rows")
            else:
                print("  (No tables found or empty database)")
            print("=" * 60 + "\n")
            sys.exit(0)
        except Exception as exc:
            print(f"\n❌ Database check failed: {exc}\n", file=sys.stderr)
            sys.exit(1)

    if args.ci_check:
        from monitor.ci_check import run_ci_check
        ok = run_ci_check(config_path=args.config, db_path=args.db)
        sys.exit(0 if ok else 1)

    if args.check_url:
        if not args.site:
            print("❌ Error: --site <site_name> is required when using --check-url", file=sys.stderr)
            sys.exit(1)
        from monitor.runner import check_single_url
        check_single_url(url=args.check_url, site_name=args.site, config_path=args.config)
        sys.exit(0)

    try:
        stats = run_once(
            config_path=args.config,
            site_filter=args.site,
            db_path=args.db,
            dry_run=args.dry_run,
        )
        if stats.get("status") == "locked":
            # Concurrency: another run is currently holding the lock; exit cleanly with code 0
            sys.exit(0)

        # Requirement 2: Exit 0 on success even when some or all sites failed (reported via health alerts)
        sys.exit(0)
    except Exception as exc:
        # Rule 7: Admin alert when whole run crashes (top-level try/except, non-zero exit code)
        from monitor.notifier import build_crash_alert_message, send_error_message
        try:
            crash_msg = build_crash_alert_message(str(exc))
            send_error_message(crash_msg)
        except Exception:
            pass
        print(f"Fatal error during execution: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
