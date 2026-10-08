"""Data migration script: Copies data from local SQLite database to Supabase (PostgreSQL).

Features:
- Reads prices.db in strictly read-only mode (never modifies or deletes SQLite).
- Copies all tables in dependency order in configurable batches.
- Preserves original auto-increment IDs using 'OVERRIDING SYSTEM VALUE'.
- Resets identity sequences using setval() so future inserts resume correctly.
- Completely idempotent using ON CONFLICT DO NOTHING.
- Includes --dry-run mode to inspect migration plan without writing.
- Prints a verification table comparing SQLite vs Postgres row counts and min/max checked_at.
- Exits non-zero if row counts differ after a live run.
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Try loading .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from monitor.storage import PostgresStorage, mask_database_url, to_bigint_id


# Dependency order for copying tables
MIGRATION_TABLES = [
    "variants",
    "price_checks",
    "events",
    "runs",
    "site_runs",
    "errors",
    "site_state",
    "meta",
]


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command line arguments for the migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate price monitoring data from SQLite to PostgreSQL (Supabase)."
    )
    parser.add_argument(
        "--sqlite-db",
        type=str,
        default=os.getenv("DATABASE_PATH", "prices.db"),
        help="Path to source SQLite database file (default: prices.db)",
    )
    parser.add_argument(
        "--postgres-url",
        type=str,
        default=os.getenv("DATABASE_URL"),
        help="Target PostgreSQL connection string (defaults to DATABASE_URL environment variable)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows per batch copy (default: 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration: count rows and verify schema without inserting records into Postgres",
    )
    return parser.parse_args(args)


def get_readonly_sqlite_conn(db_path: str) -> sqlite3.Connection:
    """Open SQLite connection strictly in read-only mode."""
    p = Path(db_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"SQLite database file not found at: {p}")

    # Use URI mode=ro to ensure the file cannot be modified or locked exclusively
    uri = f"file:{p.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_sqlite_row_count(conn: sqlite3.Connection, table: str) -> int:
    """Return total rows in an SQLite table."""
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table};")
        row = cur.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def get_postgres_row_count(pg_store: PostgresStorage, table: str) -> int:
    """Return total rows in a Postgres table."""
    try:
        conn = pg_store.get_connection()
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            row = cur.fetchone()
            return int(row["count"] if isinstance(row, dict) else row[0])
    except Exception:
        return 0


def get_price_checks_timestamp_range(
    sqlite_conn: sqlite3.Connection,
    pg_store: Optional[PostgresStorage] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Retrieve min and max timestamps of price_checks in SQLite and Postgres."""
    # SQLite
    cur = sqlite_conn.cursor()
    cur.execute("SELECT MIN(fetched_at), MAX(fetched_at) FROM price_checks;")
    sq_row = cur.fetchone()
    sq_min = sq_row[0] if sq_row else None
    sq_max = sq_row[1] if sq_row else None

    # Postgres
    pg_min = None
    pg_max = None
    if pg_store:
        try:
            conn = pg_store.get_connection()
            with conn.cursor() as pg_cur:
                pg_cur.execute("SELECT MIN(checked_at), MAX(checked_at) FROM price_checks;")
                pg_row = pg_cur.fetchone()
                if pg_row:
                    v_min = pg_row["min"] if isinstance(pg_row, dict) else pg_row[0]
                    v_max = pg_row["max"] if isinstance(pg_row, dict) else pg_row[1]
                    pg_min = v_min.isoformat() if hasattr(v_min, "isoformat") else (str(v_min) if v_min else None)
                    pg_max = v_max.isoformat() if hasattr(v_max, "isoformat") else (str(v_max) if v_max else None)
        except Exception:
            pass

    return sq_min, sq_max, pg_min, pg_max


def migrate_table(
    table: str,
    sqlite_conn: sqlite3.Connection,
    pg_store: PostgresStorage,
    batch_size: int = 500,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """Copy a single table from SQLite to PostgreSQL in batches."""
    sq_cur = sqlite_conn.cursor()
    sq_cur.execute(f"SELECT * FROM {table};")

    if dry_run:
        cur = sqlite_conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table};")
        row = cur.fetchone()
        cnt = row[0] if row else 0
        return cnt, cnt

    pg_conn = pg_store.get_connection()
    total_rows = 0
    copied_rows = 0

    while True:
        batch = sq_cur.fetchmany(batch_size)
        if not batch:
            break
        total_rows += len(batch)

        with pg_conn.transaction():
            with pg_conn.cursor() as cur:
                if table == "variants":
                    rows_to_insert = []
                    for r in batch:
                        rows_to_insert.append((
                            to_bigint_id(r["variant_id"]),
                            to_bigint_id(r["product_id"]),
                            r["site"],
                            r["product_title"],
                            r["variant_title"],
                            r["url"],
                            r["currency"],
                            int(r["active"]) if r["active"] is not None else 1,
                            int(r["consecutive_misses"] or 0),
                            r["last_seen_at"],
                            r["status"] or "active",
                            r["created_at"],
                            r["updated_at"],
                        ))
                    cur.executemany(
                        """
                        INSERT INTO variants (
                            variant_id, product_id, site, product_title, variant_title,
                            url, currency, active, consecutive_misses, last_seen_at, status, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (variant_id) DO NOTHING;
                        """,
                        rows_to_insert,
                    )
                    copied_rows += len(batch)

                elif table == "price_checks":
                    rows_to_insert = []
                    for r in batch:
                        ts = r["fetched_at"]
                        rows_to_insert.append((
                            int(r["id"]),
                            to_bigint_id(r["variant_id"]),
                            r["price_cents"],
                            r["compare_at_cents"],
                            int(r["available"]) if r["available"] is not None else 1,
                            ts,
                        ))
                    cur.executemany(
                        """
                        INSERT INTO price_checks (
                            id, variant_id, price_cents, compare_at_cents, available, checked_at
                        ) OVERRIDING SYSTEM VALUE
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING;
                        """,
                        rows_to_insert,
                    )
                    copied_rows += len(batch)

                elif table == "events":
                    rows_to_insert = []
                    for r in batch:
                        rows_to_insert.append((
                            int(r["id"]),
                            to_bigint_id(r["variant_id"]),
                            r["detected_at"],
                            r["event_type"],
                            r["old_value"],
                            r["new_value"],
                            int(r["notified"] or 0),
                        ))
                    cur.executemany(
                        """
                        INSERT INTO events (
                            id, variant_id, detected_at, event_type, old_value, new_value, notified
                        ) OVERRIDING SYSTEM VALUE
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING;
                        """,
                        rows_to_insert,
                    )
                    copied_rows += len(batch)

                elif table == "runs":
                    rows_to_insert = []
                    for r in batch:
                        rows_to_insert.append((
                            int(r["run_id"]),
                            r["started_at"],
                            r["finished_at"],
                            r["status"],
                            r["sites_total"],
                            r["sites_ok"],
                            r["sites_failed"],
                            r["variants_seen"],
                            r["events_created"],
                        ))
                    cur.executemany(
                        """
                        INSERT INTO runs (
                            run_id, started_at, finished_at, status, sites_total, sites_ok,
                            sites_failed, variants_seen, events_created
                        ) OVERRIDING SYSTEM VALUE
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (run_id) DO NOTHING;
                        """,
                        rows_to_insert,
                    )
                    copied_rows += len(batch)

                elif table == "site_runs":
                    rows_to_insert = []
                    for r in batch:
                        rows_to_insert.append((
                            int(r["id"]),
                            int(r["run_id"]) if r["run_id"] is not None else None,
                            r["site"],
                            r["status"],
                            r["urls_total"],
                            r["urls_failed"],
                            r["observations_count"],
                            r["prev_observations_count"],
                            r["error_summary"],
                            r["created_at"],
                        ))
                    cur.executemany(
                        """
                        INSERT INTO site_runs (
                            id, run_id, site, status, urls_total, urls_failed,
                            observations_count, prev_observations_count, error_summary, created_at
                        ) OVERRIDING SYSTEM VALUE
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING;
                        """,
                        rows_to_insert,
                    )
                    copied_rows += len(batch)

                elif table == "errors":
                    rows_to_insert = []
                    for r in batch:
                        rows_to_insert.append((
                            int(r["id"]),
                            int(r["run_id"]) if r["run_id"] is not None else None,
                            r["site"],
                            r["error_type"],
                            r["message"],
                            r["url"],
                            r["created_at"],
                        ))
                    cur.executemany(
                        """
                        INSERT INTO errors (
                            id, run_id, site, error_type, message, url, created_at
                        ) OVERRIDING SYSTEM VALUE
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING;
                        """,
                        rows_to_insert,
                    )
                    copied_rows += len(batch)

                elif table == "site_state":
                    rows_to_insert = []
                    for r in batch:
                        rows_to_insert.append((
                            r["site"],
                            r["last_status"],
                            r["last_notified_status"],
                            r["last_run_at"],
                            int(r["consecutive_failures"] or 0),
                            int(r["last_observations_count"] or 0),
                        ))
                    cur.executemany(
                        """
                        INSERT INTO site_state (
                            site, last_status, last_notified_status, last_run_at, consecutive_failures, last_observations_count
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (site) DO NOTHING;
                        """,
                        rows_to_insert,
                    )
                    copied_rows += len(batch)

                elif table == "meta":
                    rows_to_insert = []
                    for r in batch:
                        rows_to_insert.append((
                            r["key"],
                            r["value"],
                            r["updated_at"],
                        ))
                    cur.executemany(
                        """
                        INSERT INTO meta (key, value, updated_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (key) DO NOTHING;
                        """,
                        rows_to_insert,
                    )
                    copied_rows += len(batch)

    return total_rows, copied_rows


def reset_identity_sequences(pg_store: PostgresStorage) -> None:
    """Reset PostgreSQL IDENTITY sequences so next inserted IDs resume after MAX(id)."""
    identity_tables = [
        ("price_checks", "id"),
        ("events", "id"),
        ("runs", "run_id"),
        ("site_runs", "id"),
        ("errors", "id"),
    ]
    conn = pg_store.get_connection()
    with conn.transaction():
        with conn.cursor() as cur:
            for tbl, id_col in identity_tables:
                # Find current max ID in table
                cur.execute(f"SELECT COALESCE(MAX({id_col}), 1) AS max_val FROM {tbl};")
                row = cur.fetchone()
                max_val = row["max_val"] if isinstance(row, dict) else row[0]
                # Reset sequence using setval
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence(%s, %s), %s, true);",
                    (tbl, id_col, int(max_val)),
                )


def run_migration() -> None:
    """Entry point for migration execution."""
    # Ensure UTF-8 output on Windows
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = parse_args()

    if not args.postgres_url:
        if args.dry_run:
            args.postgres_url = "postgresql://postgres:*****@aws-0-[REGION].pooler.supabase.com:6543/postgres"
        else:
            print(
                "❌ Error: DATABASE_URL is not set and --postgres-url was not provided.\n"
                "Please provide a Supabase connection string via environment variable or argument.",
                file=sys.stderr,
            )
            sys.exit(1)

    masked_url = mask_database_url(args.postgres_url)
    print("\n" + "=" * 70)
    print("        SQLITE TO POSTGRESQL (SUPABASE) DATA MIGRATION")
    print("=" * 70)
    print(f"Source SQLite DB : {args.sqlite_db}")
    print(f"Target Database  : {masked_url}")
    print(f"Batch Size       : {args.batch_size}")
    print(f"Dry Run Mode     : {'YES (Read-only simulation)' if args.dry_run else 'NO (Live copy)'}")
    print("=" * 70)

    # 1. Connect to SQLite read-only
    try:
        sqlite_conn = get_readonly_sqlite_conn(args.sqlite_db)
    except Exception as exc:
        print(f"❌ Failed to open SQLite database: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Connect to Postgres and apply schema migrations
    pg_store = None
    if not args.dry_run:
        try:
            pg_store = PostgresStorage(database_url=args.postgres_url)
            pg_store.init_db()
        except Exception as exc:
            print(f"❌ Failed to connect to PostgreSQL / Supabase: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            pg_store = PostgresStorage(database_url=args.postgres_url)
        except Exception:
            pg_store = None

    # 3. Copy tables in dependency order
    sqlite_counts: Dict[str, int] = {}
    copied_counts: Dict[str, int] = {}
    t0 = time.time()

    for table in MIGRATION_TABLES:
        row_count = get_sqlite_row_count(sqlite_conn, table)
        sqlite_counts[table] = row_count

        if row_count == 0:
            print(f"  • {table:<15}: 0 rows (skipped)")
            copied_counts[table] = 0
            continue

        print(f"  • {table:<15}: copying {row_count:>6,} rows ...", end="", flush=True)
        _, copied = migrate_table(
            table=table,
            sqlite_conn=sqlite_conn,
            pg_store=pg_store,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        copied_counts[table] = copied
        print(f" done ({copied:,} processed)")

    # 4. Sequence reset on Postgres
    if not args.dry_run:
        print("\nResetting PostgreSQL IDENTITY sequences...")
        try:
            reset_identity_sequences(pg_store)
            print("✅ All sequences synchronized with MAX(id).")
        except Exception as exc:
            print(f"⚠️ Warning: Sequence reset encountered an error: {exc}")

    elapsed = time.time() - t0
    print(f"\nMigration phase finished in {elapsed:.2f} seconds.\n")

    # 5. Verification Table
    print("=" * 70)
    print("                    DATA VERIFICATION TABLE")
    print("=" * 70)
    hdr = f"{'Table Name':<18} {'SQLite Count':>14} {'Postgres Count':>16} {'Status':>16}"
    print(hdr)
    print("-" * 70)

    all_matched = True
    pg_counts: Dict[str, int] = {}

    for table in MIGRATION_TABLES:
        sq_cnt = sqlite_counts.get(table, 0)
        pg_cnt = get_postgres_row_count(pg_store, table) if not args.dry_run else sq_cnt
        pg_counts[table] = pg_cnt

        matched = (sq_cnt == pg_cnt)
        if not matched:
            all_matched = False
            status_str = "❌ MISMATCH"
        else:
            status_str = "✅ MATCH"

        if args.dry_run:
            status_str = "DRY-RUN READY"

        print(f"{table:<18} {sq_cnt:>14,} {pg_cnt:>16,} {status_str:>16}")

    print("-" * 70)

    # Compare min / max timestamps of price_checks
    sq_min, sq_max, pg_min, pg_max = get_price_checks_timestamp_range(
        sqlite_conn, pg_store if not args.dry_run else None
    )
    print(f"price_checks min(checked_at):")
    print(f"  • SQLite   : {sq_min}")
    print(f"  • Postgres : {pg_min or ('(Dry-run match)' if args.dry_run else 'None')}")
    print(f"price_checks max(checked_at):")
    print(f"  • SQLite   : {sq_max}")
    print(f"  • Postgres : {pg_max or ('(Dry-run match)' if args.dry_run else 'None')}")
    print("=" * 70 + "\n")

    # Cleanup
    sqlite_conn.close()
    if pg_store is not None:
        pg_store.close()

    if args.dry_run:
        print("💡 Dry-run completed successfully without writing to PostgreSQL.")
        sys.exit(0)

    if not all_matched:
        print("❌ Error: Verification detected row count differences between SQLite and Postgres!", file=sys.stderr)
        sys.exit(1)
    else:
        print("🎉 Migration verified successfully! All table row counts match exactly.")
        sys.exit(0)


if __name__ == "__main__":
    run_migration()
