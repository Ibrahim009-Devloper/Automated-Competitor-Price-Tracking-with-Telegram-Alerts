"""Unified database storage layer supporting SQLite and PostgreSQL (Supabase).

Provides a clean backend interface (BaseStorage) with two concrete implementations:
- SqliteStorage: Local file-based SQLite database with file-level locking.
- PostgresStorage: PostgreSQL (psycopg 3) with advisory locking, RLS, and pooling.

Backend selection:
- If the environment variable DATABASE_URL is set, PostgresStorage is selected.
- Otherwise, SqliteStorage (using DATABASE_PATH or 'prices.db') is selected.

Security:
- DATABASE_URL credentials and passwords are never logged or displayed in plain text.
- Row Level Security (RLS) is enabled on all PostgreSQL tables with NO public policies.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import html
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

from monitor.models import Observation

logger = logging.getLogger(__name__)

# Fallback SQLite path
DEFAULT_DB_PATH = os.getenv("DATABASE_PATH", "prices.db")

# 64-bit integer key for PostgreSQL advisory locking to prevent overlapping runs
PRICE_MONITOR_ADVISORY_LOCK_ID = 83921049281

# Safe import for psycopg 3
try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None

# Safe import for pure-Python pg8000 fallback (handles environments like Windows AppLocker)
try:
    import pg8000.dbapi
except Exception:
    pg8000 = None

import ssl
from urllib.parse import unquote, urlparse


def clean_database_url(url: Optional[str]) -> str:
    """Normalize and clean database connection string.

    Strips surrounding quotes/whitespace, and removes outer brackets
    from password if copied directly from placeholder UI (e.g. :[password]@ -> :password@).

    Args:
        url: Raw connection string.

    Returns:
        Cleaned connection string.
    """
    if not url:
        return ""
    u = url.strip().strip("'\"")
    # Replace bracketed passwords like :[my_pass]@ with :my_pass@
    u = re.sub(r':(?:%5B|\[)(.*?)(?:%5D|\])@', r':\1@', u)
    return u


def mask_database_url(url: Optional[str]) -> str:
    """Mask password in database URL for safe logging and status reporting.

    Examples:
        postgresql://postgres.abc:secret@aws-0.pooler.supabase.com:6543/postgres
        -> postgresql://postgres.abc:*****@aws-0.pooler.supabase.com:6543/postgres

    Args:
        url: Raw connection string.

    Returns:
        Connection string with password masked by '*****'.
    """
    if not url:
        return ""
    try:
        cleaned = clean_database_url(url)
        parsed = urlparse(cleaned)
        if not parsed.scheme or not parsed.netloc:
            # Fallback for paths or non-URI strings
            return str(url)
        if parsed.password:
            # Replace password portion in netloc
            safe_netloc = parsed.netloc.replace(f":{parsed.password}@", ":*****@")
            masked = parsed._replace(netloc=safe_netloc)
            return masked.geturl()
        return cleaned
    except Exception:
        # Robust regex fallback
        return re.sub(r":([^/@:]+)@", r":*****@", str(url))


def to_bigint_id(val: Any) -> Optional[int]:
    """Convert an ID (int, numeric string, or string slug) to a 64-bit signed integer.

    Shopify IDs are large 64-bit integers.
    For non-digit IDs (e.g. from tests or mock URLs), generates a deterministic 63-bit integer.

    Args:
        val: Raw variant or product identifier.

    Returns:
        Integer representation suitable for PostgreSQL BIGINT.
    """
    if val is None:
        return None
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if not s:
        return None
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        return int(s)
    # Generate deterministic positive 63-bit signed integer from string hash
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:15]
    return int(h, 16)


def format_iso_timestamp(val: Any) -> str:
    """Ensure timestamp is formatted as an ISO 8601 UTC string."""
    if val is None:
        return datetime.now(timezone.utc).isoformat()
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# =============================================================================
# Abstract Storage Interface
# =============================================================================


class BaseStorage(ABC):
    """Abstract interface defining the contract for price monitoring persistence backends."""

    @abstractmethod
    def init_db(self) -> None:
        """Initialize tables, schemas, migrations, and indexes."""

    @abstractmethod
    def acquire_lock(self) -> bool:
        """Acquire run concurrency lock (advisory lock or file lock).

        Returns:
            bool: True if lock acquired; False if another run is in progress.
        """

    @abstractmethod
    def release_lock(self) -> None:
        """Release the concurrency lock."""

    @abstractmethod
    def is_price_checks_empty(self) -> bool:
        """Return True if price_checks table has zero records (baseline run)."""

    @abstractmethod
    def record_run_start(self, started_at: Optional[str] = None) -> int:
        """Record the beginning of a run in runs table, returning run_id."""

    @abstractmethod
    def record_run_finish(
        self,
        run_id: int,
        status: str,
        sites_total: int,
        sites_ok: int,
        sites_failed: int,
        variants_seen: int,
        events_created: int,
        finished_at: Optional[str] = None,
    ) -> None:
        """Record the completion of a run."""

    @abstractmethod
    def record_site_run(
        self,
        run_id: int,
        site: str,
        status: str,
        urls_total: int,
        urls_failed: int,
        observations_count: int,
        prev_observations_count: int,
        error_summary: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> None:
        """Record health metrics for a specific store in a run."""

    @abstractmethod
    def insert_error_record(
        self,
        site: str,
        error_type: str,
        message: str,
        url: Optional[str] = None,
        run_id: Optional[int] = None,
        created_at: Optional[str] = None,
    ) -> int:
        """Insert a classified error record into errors table."""

    @abstractmethod
    def get_site_state(self, site: str) -> Optional[Dict[str, Any]]:
        """Retrieve persistent site state for transition tracking."""

    @abstractmethod
    def upsert_site_state(
        self,
        site: str,
        status: str,
        observations_count: int = 0,
        last_notified_status: Optional[str] = None,
        run_at: Optional[str] = None,
    ) -> None:
        """Update or insert persistent site state."""

    @abstractmethod
    def get_variant_ids_for_site(self, site: str, active_only: bool = True) -> List[str]:
        """Return list of known variant IDs for a store."""

    @abstractmethod
    def find_active_variant_ids_by_url_substr(self, site: str, url_substring: str) -> List[str]:
        """Find active variant IDs for a site matching a URL substring."""

    @abstractmethod
    def deactivate_removed_variants(self, site: str, active_urls: List[str]) -> int:
        """Deactivate variants whose URLs were removed from targets."""

    @abstractmethod
    def is_variant_in_catalog(self, variant_id: Union[str, int]) -> bool:
        """Check if variant exists in variants table."""

    @abstractmethod
    def get_last_check(self, variant_id: Union[str, int]) -> Optional[Dict[str, Any]]:
        """Fetch the most recent price check snapshot for a variant."""

    @abstractmethod
    def upsert_variant(self, observation: Observation) -> bool:
        """Insert or update variant. Returns True if newly inserted."""

    @abstractmethod
    def insert_price_check(self, observation: Observation) -> int:
        """Record a historical price check snapshot."""

    @abstractmethod
    def insert_event(
        self,
        variant_id: Union[str, int],
        detected_at: str,
        event_type: str,
        old_value: Optional[int] = None,
        new_value: Optional[int] = None,
        notified: int = 0,
    ) -> int:
        """Insert detected event."""

    @abstractmethod
    def get_unnotified_events(self) -> List[Dict[str, Any]]:
        """Retrieve all events with notified = 0."""

    @abstractmethod
    def mark_events_notified(self, event_ids: List[int]) -> None:
        """Mark events as notified (notified = 1)."""

    @abstractmethod
    def process_presence_and_delisting(
        self,
        site: str,
        seen_variant_ids: List[str],
        confirmed_absent_ids: List[str],
        missing_runs_before_delisted: int = 3,
        fetched_at: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Process delisting / relisting transitions and generate events."""

    @abstractmethod
    def get_meta(self, key: str) -> Optional[str]:
        """Retrieve value from meta table."""

    @abstractmethod
    def set_meta(self, key: str, value: str, updated_at: Optional[str] = None) -> None:
        """Set value in meta table."""

    @abstractmethod
    def get_latest_site_statuses(self) -> List[Dict[str, Any]]:
        """Retrieve latest store statuses (for --health CLI)."""

    def get_site_variant_ids(self, site: str) -> set:
        """Fetch all variant IDs for a specific site."""
        return set()

    def get_site_latest_checks(self, site: str) -> Dict[str, Dict[str, Any]]:
        """Fetch mapping of variant_id -> latest price check for a site."""
        return {}

    def batch_upsert_variants(self, observations: List[Observation]) -> int:
        """Batch upsert variants for high-throughput network efficiency."""
        count = 0
        for obs in observations:
            if self.upsert_variant(obs):
                count += 1
        return count

    def batch_insert_price_checks(self, observations: List[Observation]) -> int:
        """Batch insert price check snapshots."""
        count = 0
        for obs in observations:
            self.insert_price_check(obs)
            count += 1
        return count

    def batch_insert_events(self, events: List[Dict[str, Any]]) -> List[int]:
        """Batch insert detected events."""
        ids = []
        for ev in events:
            eid = self.insert_event(
                variant_id=ev["variant_id"],
                detected_at=ev["detected_at"],
                event_type=ev["event_type"],
                old_value=ev.get("old_value"),
                new_value=ev.get("new_value"),
                notified=ev.get("notified", 0),
            )
            ids.append(eid)
        return ids

    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        """Check connection health and return backend, version, latency, row counts (for --db-check CLI)."""

    @abstractmethod
    @contextmanager
    def transaction(self):
        """Context manager executing block in an atomic database transaction."""

    def __enter__(self):
        self._active_tx = self.transaction()
        return self._active_tx.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "_active_tx") and self._active_tx is not None:
            res = self._active_tx.__exit__(exc_type, exc_val, exc_tb)
            self._active_tx = None
            return res
        return False

    @abstractmethod
    def close(self) -> None:
        """Close connection and clean up resources."""


# =============================================================================
# SQLite Storage Implementation
# =============================================================================


class SqliteStorage(BaseStorage):
    """SQLite backend storing data in a local file with file locking."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or os.getenv("DATABASE_PATH", DEFAULT_DB_PATH)
        self.lock_path = f"{self.db_path}.lock"
        self._lock_fd: Optional[int] = None
        self._conn: Optional[sqlite3.Connection] = None

    def get_connection(self) -> sqlite3.Connection:
        """Return active connection or open a new one."""
        if self._conn is None:
            dirname = os.path.dirname(self.db_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            self._conn = conn
        return self._conn

    def cursor(self):
        return self.get_connection().cursor()

    def execute(self, *args, **kwargs):
        return self.get_connection().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self.get_connection().executemany(*args, **kwargs)

    def commit(self):
        return self.get_connection().commit()

    def rollback(self):
        return self.get_connection().rollback()

    def acquire_lock(self) -> bool:
        """Acquire file lock. Returns False if active run is in progress."""
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            self._lock_fd = fd
            return True
        except FileExistsError:
            # Check if holding PID is still alive
            is_alive = False
            try:
                with open(self.lock_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content.isdigit():
                        is_alive = self._is_pid_running(int(content))
            except Exception:
                is_alive = False

            if is_alive:
                logger.info("another run in progress")
                return False

            # Stale lock: clean up and retry once
            try:
                os.remove(self.lock_path)
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                self._lock_fd = fd
                return True
            except Exception as exc:
                logger.info("another run in progress: %s", exc)
                return False

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                SYNCHRONIZE = 0x00100000
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
                )
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def release_lock(self) -> None:
        """Release the file lock."""
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            except Exception:
                pass
            self._lock_fd = None
        if os.path.exists(self.lock_path):
            try:
                with open(self.lock_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content == str(os.getpid()):
                    os.remove(self.lock_path)
            except Exception:
                pass

    def init_db(self) -> None:
        """Initialize SQLite tables and run safe migrations."""
        backup_database_if_needed(self.db_path)
        conn = self.get_connection()
        init_db(conn=conn)

    @contextmanager
    def transaction(self):
        """Transaction context manager."""
        conn = self.get_connection()
        with conn:
            yield conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def is_price_checks_empty(self) -> bool:
        return is_price_checks_empty(self.get_connection())

    def record_run_start(self, started_at: Optional[str] = None) -> int:
        return record_run_start(self.get_connection(), started_at=started_at)

    def record_run_finish(
        self,
        run_id: int,
        status: str,
        sites_total: int,
        sites_ok: int,
        sites_failed: int,
        variants_seen: int,
        events_created: int,
        finished_at: Optional[str] = None,
    ) -> None:
        record_run_finish(
            conn=self.get_connection(),
            run_id=run_id,
            status=status,
            sites_total=sites_total,
            sites_ok=sites_ok,
            sites_failed=sites_failed,
            variants_seen=variants_seen,
            events_created=events_created,
            finished_at=finished_at,
        )

    def record_site_run(
        self,
        run_id: int,
        site: str,
        status: str,
        urls_total: int,
        urls_failed: int,
        observations_count: int,
        prev_observations_count: int,
        error_summary: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> None:
        record_site_run(
            conn=self.get_connection(),
            run_id=run_id,
            site=site,
            status=status,
            urls_total=urls_total,
            urls_failed=urls_failed,
            observations_count=observations_count,
            prev_observations_count=prev_observations_count,
            error_summary=error_summary,
            created_at=created_at,
        )

    def insert_error_record(
        self,
        site: str,
        error_type: str,
        message: str,
        url: Optional[str] = None,
        run_id: Optional[int] = None,
        created_at: Optional[str] = None,
    ) -> int:
        return insert_error_record(
            conn=self.get_connection(),
            site=site,
            error_type=error_type,
            message=message,
            url=url,
            run_id=run_id,
            created_at=created_at,
        )

    def get_site_state(self, site: str) -> Optional[Dict[str, Any]]:
        return get_site_state(self.get_connection(), site)

    def upsert_site_state(
        self,
        site: str,
        status: str,
        observations_count: int = 0,
        last_notified_status: Optional[str] = None,
        run_at: Optional[str] = None,
    ) -> None:
        upsert_site_state(
            conn=self.get_connection(),
            site=site,
            status=status,
            observations_count=observations_count,
            last_notified_status=last_notified_status,
            run_at=run_at,
        )

    def get_variant_ids_for_site(self, site: str, active_only: bool = True) -> List[str]:
        return get_variant_ids_for_site(self.get_connection(), site, active_only=active_only)

    def find_active_variant_ids_by_url_substr(self, site: str, url_substring: str) -> List[str]:
        return find_active_variant_ids_by_url_substr(self.get_connection(), site, url_substring)

    def deactivate_removed_variants(self, site: str, active_urls: List[str]) -> int:
        return deactivate_removed_variants(self.get_connection(), site, active_urls)

    def is_variant_in_catalog(self, variant_id: Union[str, int]) -> bool:
        return is_variant_in_catalog(self.get_connection(), variant_id)

    def get_last_check(self, variant_id: Union[str, int]) -> Optional[Dict[str, Any]]:
        return get_last_check(self.get_connection(), variant_id)

    def upsert_variant(self, observation: Observation) -> bool:
        return upsert_variant(self.get_connection(), observation)

    def insert_price_check(self, observation: Observation) -> int:
        return insert_price_check(self.get_connection(), observation)

    def insert_event(
        self,
        variant_id: Union[str, int],
        detected_at: str,
        event_type: str,
        old_value: Optional[int] = None,
        new_value: Optional[int] = None,
        notified: int = 0,
    ) -> int:
        return insert_event(
            conn=self.get_connection(),
            variant_id=variant_id,
            detected_at=detected_at,
            event_type=event_type,
            old_value=old_value,
            new_value=new_value,
            notified=notified,
        )

    def get_site_variant_ids(self, site: str) -> set:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT variant_id FROM variants WHERE site = ?;", (site,))
        return {str(row[0]) for row in cur.fetchall()}

    def get_site_latest_checks(self, site: str) -> Dict[str, Dict[str, Any]]:
        conn = self.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pc.variant_id, pc.price_cents, pc.compare_at_cents, pc.available, pc.fetched_at
            FROM price_checks pc
            JOIN variants v ON v.variant_id = pc.variant_id
            WHERE v.site = ?
            ORDER BY pc.variant_id, pc.fetched_at DESC;
            """,
            (site,),
        )
        res = {}
        for row in cur.fetchall():
            vid = str(row[0])
            if vid not in res:
                res[vid] = {
                    "variant_id": row[0],
                    "price_cents": row[1],
                    "compare_at_cents": row[2],
                    "available": row[3],
                    "checked_at": row[4],
                    "fetched_at": row[4],
                }
        return res

    def batch_upsert_variants(self, observations: List[Observation]) -> int:
        if not observations:
            return 0
        new_count = 0
        conn = self.get_connection()
        with conn:
            for obs in observations:
                if self.upsert_variant(obs):
                    new_count += 1
        return new_count

    def batch_insert_price_checks(self, observations: List[Observation]) -> int:
        if not observations:
            return 0
        conn = self.get_connection()
        with conn:
            for obs in observations:
                self.insert_price_check(obs)
        return len(observations)

    def batch_insert_events(self, events: List[Dict[str, Any]]) -> List[int]:
        if not events:
            return []
        ids = []
        conn = self.get_connection()
        with conn:
            for ev in events:
                eid = self.insert_event(
                    variant_id=ev["variant_id"],
                    detected_at=ev["detected_at"],
                    event_type=ev["event_type"],
                    old_value=ev.get("old_value"),
                    new_value=ev.get("new_value"),
                    notified=ev.get("notified", 0),
                )
                ids.append(eid)
        return ids

    def get_unnotified_events(self) -> List[Dict[str, Any]]:
        return get_unnotified_events(self.get_connection())

    def mark_events_notified(self, event_ids: List[int]) -> None:
        mark_events_notified(self.get_connection(), event_ids)

    def process_presence_and_delisting(
        self,
        site: str,
        seen_variant_ids: List[str],
        confirmed_absent_ids: List[str],
        missing_runs_before_delisted: int = 3,
        fetched_at: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        return process_presence_and_delisting(
            conn=self.get_connection(),
            site=site,
            seen_variant_ids=seen_variant_ids,
            confirmed_absent_ids=confirmed_absent_ids,
            missing_runs_before_delisted=missing_runs_before_delisted,
            fetched_at=fetched_at,
        )

    def get_meta(self, key: str) -> Optional[str]:
        return get_meta(self.get_connection(), key)

    def set_meta(self, key: str, value: str, updated_at: Optional[str] = None) -> None:
        set_meta(self.get_connection(), key, value, updated_at=updated_at)

    def get_latest_site_statuses(self) -> List[Dict[str, Any]]:
        return get_latest_site_statuses(self.get_connection())

    def check_health(self) -> Dict[str, Any]:
        """Inspect health metrics for SQLite."""
        conn = self.get_connection()
        t0 = time.time()
        cur = conn.cursor()
        cur.execute("SELECT sqlite_version();")
        version_row = cur.fetchone()
        version = f"SQLite {version_row[0]}" if version_row else "SQLite"
        latency_ms = (time.time() - t0) * 1000.0

        tables = ["variants", "price_checks", "events", "runs", "site_runs", "errors", "site_state", "meta"]
        table_counts: Dict[str, int] = {}
        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t};")
                cnt = cur.fetchone()[0]
                table_counts[t] = cnt
            except Exception:
                table_counts[t] = 0

        return {
            "backend": "SQLite",
            "version": version,
            "target": self.db_path,
            "host_or_path": self.db_path,
            "latency_ms": round(latency_ms, 2),
            "table_counts": table_counts,
            "row_counts": table_counts,
        }


# =============================================================================
# PostgreSQL (Supabase) Storage Implementation
# =============================================================================


class DictRow(dict):
    """Row object that supports both dict key lookup (row['col']) and sequence index (row[0])."""

    def __init__(self, cols: List[str], vals: Any) -> None:
        val_list = list(vals) if vals is not None else []
        super().__init__(zip(cols, val_list))
        self._vals = val_list

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._vals[key]
        return super().__getitem__(key)


class Pg8000DictCursor:
    """Cursor wrapper for pg8000 that returns DictRow objects and provides psycopg-compatible API."""

    def __init__(self, cursor: Any) -> None:
        self._cur = cursor

    @property
    def description(self) -> Any:
        return self._cur.description

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    def execute(self, operation: str, params: Any = None) -> "Pg8000DictCursor":
        if params is None:
            self._cur.execute(operation)
        else:
            self._cur.execute(operation, params)
        return self

    def executemany(self, operation: str, param_seq: Any) -> "Pg8000DictCursor":
        self._cur.executemany(operation, param_seq)
        return self

    def _convert_row(self, row: Any) -> Optional[DictRow]:
        if row is None:
            return None
        if not self._cur.description:
            return row
        cols = [d[0] for d in self._cur.description]
        return DictRow(cols, row)

    def fetchone(self) -> Optional[DictRow]:
        row = self._cur.fetchone()
        return self._convert_row(row)

    def fetchall(self) -> List[DictRow]:
        rows = self._cur.fetchall()
        if not rows:
            return []
        if not self._cur.description:
            return rows
        cols = [d[0] for d in self._cur.description]
        return [DictRow(cols, r) for r in rows]

    def fetchmany(self, size: int = 1) -> List[DictRow]:
        rows = self._cur.fetchmany(size)
        if not rows:
            return []
        if not self._cur.description:
            return rows
        cols = [d[0] for d in self._cur.description]
        return [DictRow(cols, r) for r in rows]

    def close(self) -> None:
        self._cur.close()

    def __enter__(self) -> "Pg8000DictCursor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row


class Pg8000ConnectionAdapter:
    """Connection wrapper adapting pg8000 to psycopg 3 connection interface."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def cursor(self, *args, **kwargs) -> Pg8000DictCursor:
        return Pg8000DictCursor(self._conn.cursor())

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        if not self._closed:
            try:
                self._conn.close()
            except Exception:
                pass
            self._closed = True

    def execute(self, *args, **kwargs) -> Pg8000DictCursor:
        cur = self.cursor()
        return cur.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs) -> Pg8000DictCursor:
        cur = self.cursor()
        return cur.executemany(*args, **kwargs)

    @contextmanager
    def transaction(self):
        if getattr(self, "_in_transaction", False):
            yield
            return
        self._in_transaction = True
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise
        finally:
            self._in_transaction = False

    def __enter__(self) -> "Pg8000ConnectionAdapter":
        self._in_transaction = True
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_type is not None:
                self.rollback()
            else:
                self.commit()
        finally:
            self._in_transaction = False


class PostgresStorage(BaseStorage):
    """PostgreSQL backend for Supabase with advisory locking, RLS, and session pooling."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        raw_url = database_url or os.getenv("DATABASE_URL")
        if not raw_url:
            raise ValueError("DATABASE_URL environment variable or parameter is required for PostgresStorage.")
        self.database_url = clean_database_url(raw_url)
        self._conn: Optional[Any] = None
        self._locked: bool = False

    def _get_connection(self) -> Any:
        """Connect to Postgres with 3 retry attempts, exponential backoff, and timeouts."""
        if self._conn is not None and not getattr(self._conn, "closed", False):
            return self._conn

        max_attempts = 3
        last_exc: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.debug("Connecting to PostgreSQL (attempt %d/%d)...", attempt, max_attempts)
                # Try psycopg 3 first if available
                if psycopg is not None:
                    try:
                        conn = psycopg.connect(
                            self.database_url,
                            connect_timeout=10,
                            sslmode="require",
                            options="-c statement_timeout=30000",
                            row_factory=dict_row,
                            autocommit=False,
                        )
                        self._conn = conn
                        return conn
                    except (ImportError, OSError) as load_err:
                        # e.g., Windows AppLocker blocking psycopg_binary DLL
                        logger.debug("psycopg unavailable or blocked (%s); trying pg8000 fallback", load_err)

                # Pure-Python pg8000 fallback
                if pg8000 is not None:
                    parsed = urlparse(self.database_url)
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    user = unquote(parsed.username) if parsed.username else None
                    password = unquote(parsed.password) if parsed.password else None
                    host = parsed.hostname
                    port = parsed.port or 5432
                    database = parsed.path.lstrip("/") or "postgres"

                    raw_conn = pg8000.dbapi.connect(
                        user=user,
                        password=password,
                        host=host,
                        port=port,
                        database=database,
                        ssl_context=ctx,
                        timeout=10,
                    )
                    conn = Pg8000ConnectionAdapter(raw_conn)
                    self._conn = conn
                    return conn

                raise ImportError(
                    "Neither psycopg nor pg8000 is available for PostgreSQL connections. "
                    "Install via: pip install 'psycopg[binary]>=3.1.0' or pip install pg8000"
                )
            except Exception as exc:
                last_exc = exc
                masked = mask_database_url(self.database_url)
                logger.warning(
                    "Postgres connection attempt %d/%d to %s failed: %s",
                    attempt,
                    max_attempts,
                    masked,
                    exc,
                )
                if attempt < max_attempts:
                    time.sleep(2 ** (attempt - 1))

        # All attempts failed: report through existing admin alert path
        masked = mask_database_url(self.database_url)
        err_msg = f"Failed to connect to PostgreSQL ({masked}) after {max_attempts} attempts: {last_exc}"
        logger.error(err_msg)
        try:
            from monitor.notifier import send_error_message
            clean_err = html.escape(str(last_exc))
            send_error_message(
                f"🚨 <b>Database Connection Failure</b>\n\n"
                f"Could not connect to PostgreSQL backend (<code>{masked}</code>):\n"
                f"<code>{clean_err[:1500]}</code>"
            )
        except Exception as alert_err:
            logger.warning("Could not dispatch database error alert: %s", alert_err)

        raise RuntimeError(err_msg) from last_exc

    def get_connection(self) -> Any:
        return self._get_connection()

    def cursor(self):
        return self._get_connection().cursor()

    def execute(self, *args, **kwargs):
        return self._get_connection().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._get_connection().executemany(*args, **kwargs)

    def commit(self):
        return self._get_connection().commit()

    def rollback(self):
        return self._get_connection().rollback()

    def acquire_lock(self) -> bool:
        """Acquire PostgreSQL session-level advisory lock.

        Returns:
            bool: True if lock acquired; False if another run is currently holding the lock.
        """
        conn = self._get_connection()
        self._conn = conn
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s);", (PRICE_MONITOR_ADVISORY_LOCK_ID,))
                row = cur.fetchone()
                acquired = bool(row["pg_try_advisory_lock"] if isinstance(row, dict) else row[0])
                if acquired:
                    self._locked = True
                    return True
                else:
                    logger.info("another run in progress")
                    return False
        except Exception as exc:
            logger.error("Error acquiring PostgreSQL advisory lock: %s", exc)
            return False

    def release_lock(self) -> None:
        """Release PostgreSQL advisory lock if held."""
        if not self._locked:
            return
        conn = self._conn or self._get_connection()
        if conn and not (getattr(conn, "closed", False) is True):
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s);", (PRICE_MONITOR_ADVISORY_LOCK_ID,))
                conn.commit()
            except Exception as exc:
                logger.debug("Error releasing PostgreSQL advisory lock: %s", exc)
        self._locked = False

    def init_db(self) -> None:
        """Apply versioned, idempotent schema migrations and enable Row Level Security."""
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                # 0. Migrations tracking table
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
                    );
                    """
                )

                # Check if Migration 1 is already applied
                cur.execute("SELECT version FROM schema_migrations WHERE version = 1;")
                if not cur.fetchone():
                    logger.info("Applying PostgreSQL migration 1: core tables, indexes, and RLS...")

                    # 1. Product variants catalog table (Shopify IDs are BIGINT)
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS variants (
                            variant_id BIGINT PRIMARY KEY,
                            product_id BIGINT,
                            site TEXT NOT NULL,
                            product_title TEXT NOT NULL,
                            variant_title TEXT,
                            url TEXT,
                            currency TEXT,
                            active SMALLINT DEFAULT 1,
                            consecutive_misses INTEGER DEFAULT 0,
                            last_seen_at TIMESTAMPTZ,
                            status TEXT DEFAULT 'active',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
                        );
                        """
                    )

                    # 2. Historical price checks table
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS price_checks (
                            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                            variant_id BIGINT NOT NULL REFERENCES variants(variant_id),
                            price_cents BIGINT,
                            compare_at_cents BIGINT,
                            available SMALLINT NOT NULL,
                            checked_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
                            fetched_at TIMESTAMPTZ GENERATED ALWAYS AS (checked_at) STORED
                        );
                        """
                    )

                    # 3. Change detection events table
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS events (
                            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                            variant_id BIGINT NOT NULL,
                            detected_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
                            event_type TEXT NOT NULL,
                            old_value BIGINT,
                            new_value BIGINT,
                            notified SMALLINT DEFAULT 0
                        );
                        """
                    )

                    # 4. Runs health logging table
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS runs (
                            run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                            started_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
                            finished_at TIMESTAMPTZ,
                            status TEXT NOT NULL,
                            sites_total INTEGER DEFAULT 0,
                            sites_ok INTEGER DEFAULT 0,
                            sites_failed INTEGER DEFAULT 0,
                            variants_seen INTEGER DEFAULT 0,
                            events_created INTEGER DEFAULT 0
                        );
                        """
                    )

                    # 5. Per-site run health table
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS site_runs (
                            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                            run_id BIGINT NOT NULL REFERENCES runs(run_id),
                            site TEXT NOT NULL,
                            status TEXT NOT NULL,
                            urls_total INTEGER DEFAULT 0,
                            urls_failed INTEGER DEFAULT 0,
                            observations_count INTEGER DEFAULT 0,
                            prev_observations_count INTEGER DEFAULT 0,
                            error_summary TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
                        );
                        """
                    )

                    # 6. Structured error logs table
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS errors (
                            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                            run_id BIGINT,
                            site TEXT NOT NULL,
                            error_type TEXT NOT NULL,
                            message TEXT NOT NULL,
                            url TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
                        );
                        """
                    )

                    # 7. Persistent site state table for transition alerts
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS site_state (
                            site TEXT PRIMARY KEY,
                            last_status TEXT NOT NULL,
                            last_notified_status TEXT,
                            last_run_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
                            consecutive_failures INTEGER DEFAULT 0,
                            last_observations_count INTEGER DEFAULT 0
                        );
                        """
                    )

                    # 8. Meta key-value table
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS meta (
                            key TEXT PRIMARY KEY,
                            value TEXT NOT NULL,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
                        );
                        """
                    )

                    # Indexes as specified in requirements
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_checks_variant_checked_at ON price_checks(variant_id, checked_at DESC);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_notified ON events(notified);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_variants_site_status ON variants(site, status);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_variants_site ON variants(site);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_checks_variant ON price_checks(variant_id);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_site_runs_run_id ON site_runs(run_id);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_errors_run_id ON errors(run_id);")

                    # Enable Row Level Security (RLS) on every table with NO public policies
                    tables = ["variants", "price_checks", "events", "runs", "site_runs", "errors", "site_state", "meta", "schema_migrations"]
                    for tbl in tables:
                        cur.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")

                    # Record migration
                    cur.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (1, 'initial_schema', NOW() AT TIME ZONE 'utc');"
                    )
                    logger.info("PostgreSQL migration 1 applied successfully with RLS enabled.")

    @contextmanager
    def transaction(self):
        """Transaction context manager for atomic multi-statement blocks."""
        conn = self._get_connection()
        with conn.transaction():
            yield conn

    def close(self) -> None:
        """Close connection and release advisory lock if held."""
        self.release_lock()
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def is_price_checks_empty(self) -> bool:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM price_checks LIMIT 1;")
            return cur.fetchone() is None

    def record_run_start(self, started_at: Optional[str] = None) -> int:
        ts = format_iso_timestamp(started_at)
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO runs (started_at, status) VALUES (%s, %s) RETURNING run_id;",
                    (ts, "in_progress"),
                )
                row = cur.fetchone()
                return int(row["run_id"] if isinstance(row, dict) else row[0])

    def record_run_finish(
        self,
        run_id: int,
        status: str,
        sites_total: int,
        sites_ok: int,
        sites_failed: int,
        variants_seen: int,
        events_created: int,
        finished_at: Optional[str] = None,
    ) -> None:
        ts = format_iso_timestamp(finished_at)
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE runs SET
                        finished_at = %s,
                        status = %s,
                        sites_total = %s,
                        sites_ok = %s,
                        sites_failed = %s,
                        variants_seen = %s,
                        events_created = %s
                    WHERE run_id = %s;
                    """,
                    (ts, status, sites_total, sites_ok, sites_failed, variants_seen, events_created, run_id),
                )

    def record_site_run(
        self,
        run_id: int,
        site: str,
        status: str,
        urls_total: int,
        urls_failed: int,
        observations_count: int,
        prev_observations_count: int,
        error_summary: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> None:
        ts = format_iso_timestamp(created_at)
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO site_runs (
                        run_id, site, status, urls_total, urls_failed,
                        observations_count, prev_observations_count, error_summary, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (run_id, site, status, urls_total, urls_failed, observations_count, prev_observations_count, error_summary, ts),
                )

    def insert_error_record(
        self,
        site: str,
        error_type: str,
        message: str,
        url: Optional[str] = None,
        run_id: Optional[int] = None,
        created_at: Optional[str] = None,
    ) -> int:
        ts = format_iso_timestamp(created_at)
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO errors (run_id, site, error_type, message, url, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (run_id, site, error_type, message, url, ts),
                )
                row = cur.fetchone()
                return int(row["id"] if isinstance(row, dict) else row[0])

    def get_site_state(self, site: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT site, last_status, last_notified_status, last_run_at, consecutive_failures, last_observations_count
                FROM site_state WHERE site = %s;
                """,
                (site,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def upsert_site_state(
        self,
        site: str,
        status: str,
        observations_count: int = 0,
        last_notified_status: Optional[str] = None,
        run_at: Optional[str] = None,
    ) -> None:
        ts = format_iso_timestamp(run_at)
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO site_state (
                        site, last_status, last_notified_status, last_run_at, consecutive_failures, last_observations_count
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (site) DO UPDATE SET
                        last_status = EXCLUDED.last_status,
                        last_notified_status = COALESCE(EXCLUDED.last_notified_status, site_state.last_notified_status),
                        last_run_at = EXCLUDED.last_run_at,
                        consecutive_failures = EXCLUDED.consecutive_failures,
                        last_observations_count = EXCLUDED.last_observations_count;
                    """,
                    (
                        site,
                        status,
                        last_notified_status,
                        ts,
                        0 if status == "ok" else 1,
                        observations_count,
                    ),
                )

    def get_variant_ids_for_site(self, site: str, active_only: bool = True) -> List[str]:
        conn = self._get_connection()
        with conn.cursor() as cur:
            if active_only:
                cur.execute("SELECT variant_id FROM variants WHERE site = %s AND active = 1;", (site,))
            else:
                cur.execute("SELECT variant_id FROM variants WHERE site = %s;", (site,))
            rows = cur.fetchall()
            return [str(r["variant_id"] if isinstance(r, dict) else r[0]) for r in rows]

    def find_active_variant_ids_by_url_substr(self, site: str, url_substring: str) -> List[str]:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT variant_id FROM variants WHERE site = %s AND url LIKE %s AND active = 1;",
                (site, f"%{url_substring}%"),
            )
            rows = cur.fetchall()
            return [str(r["variant_id"] if isinstance(r, dict) else r[0]) for r in rows]

    def deactivate_removed_variants(self, site: str, active_urls: List[str]) -> int:
        if not active_urls:
            return 0
        norm_urls = [u.split("?")[0].rstrip("/").lower() for u in active_urls if u]
        ts = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        deactivated = []
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT variant_id, url FROM variants WHERE site = %s AND active = 1;", (site,))
                for row in cur.fetchall():
                    vid = str(row["variant_id"] if isinstance(row, dict) else row[0])
                    url = str(row["url"] if isinstance(row, dict) else row[1] or "")
                    norm = url.split("?")[0].rstrip("/").lower()
                    if norm not in norm_urls:
                        deactivated.append(vid)

                if deactivated:
                    bigint_ids = [to_bigint_id(v) for v in deactivated]
                    cur.execute(
                        "UPDATE variants SET active = 0, updated_at = %s WHERE variant_id = ANY(%s);",
                        (ts, bigint_ids),
                    )
        return len(deactivated)

    def is_variant_in_catalog(self, variant_id: Union[str, int]) -> bool:
        vid = to_bigint_id(variant_id)
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM variants WHERE variant_id = %s;", (vid,))
            return cur.fetchone() is not None

    def get_last_check(self, variant_id: Union[str, int]) -> Optional[Dict[str, Any]]:
        vid = to_bigint_id(variant_id)
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, variant_id, price_cents, compare_at_cents, available, checked_at, fetched_at
                FROM price_checks
                WHERE variant_id = %s
                ORDER BY checked_at DESC, id DESC
                LIMIT 1;
                """,
                (vid,),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            # Ensure variant_id matches string representation
            d["variant_id"] = str(d["variant_id"])
            return d

    def upsert_variant(self, observation: Observation) -> bool:
        vid = to_bigint_id(observation.variant_id)
        pid = to_bigint_id(observation.product_id)
        ts = format_iso_timestamp(observation.fetched_at)
        conn = self._get_connection()

        is_new = False
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM variants WHERE variant_id = %s;", (vid,))
                is_new = cur.fetchone() is None

                cur.execute(
                    """
                    INSERT INTO variants (
                        variant_id, product_id, site, product_title, variant_title,
                        url, currency, created_at, updated_at, active, status, consecutive_misses, last_seen_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 'active', 0, %s)
                    ON CONFLICT (variant_id) DO UPDATE SET
                        product_id = EXCLUDED.product_id,
                        site = EXCLUDED.site,
                        product_title = EXCLUDED.product_title,
                        variant_title = EXCLUDED.variant_title,
                        url = EXCLUDED.url,
                        currency = EXCLUDED.currency,
                        updated_at = EXCLUDED.updated_at,
                        active = 1,
                        status = 'active',
                        consecutive_misses = 0,
                        last_seen_at = EXCLUDED.last_seen_at;
                    """,
                    (
                        vid,
                        pid,
                        observation.site,
                        observation.product_title,
                        observation.variant_title,
                        observation.url,
                        observation.currency,
                        ts,
                        ts,
                        ts,
                    ),
                )
        return is_new

    def insert_price_check(self, observation: Observation) -> int:
        vid = to_bigint_id(observation.variant_id)
        ts = format_iso_timestamp(observation.fetched_at)
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO price_checks (variant_id, price_cents, compare_at_cents, available, checked_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        vid,
                        observation.price_cents,
                        observation.compare_at_cents,
                        1 if observation.available else 0,
                        ts,
                    ),
                )
                row = cur.fetchone()
                return int(row["id"] if isinstance(row, dict) else row[0])

    def insert_event(
        self,
        variant_id: Union[str, int],
        detected_at: str,
        event_type: str,
        old_value: Optional[int] = None,
        new_value: Optional[int] = None,
        notified: int = 0,
    ) -> int:
        vid = to_bigint_id(variant_id)
        ts = format_iso_timestamp(detected_at)
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events (variant_id, detected_at, event_type, old_value, new_value, notified)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (vid, ts, event_type, old_value, new_value, notified),
                )
                row = cur.fetchone()
                return int(row["id"] if isinstance(row, dict) else row[0])

    def get_site_variant_ids(self, site: str) -> set:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT variant_id FROM variants WHERE site = %s;", (site,))
            rows = cur.fetchall()
            return {str(r["variant_id"] if isinstance(r, dict) else r[0]) for r in rows}

    def get_site_latest_checks(self, site: str) -> Dict[str, Dict[str, Any]]:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (pc.variant_id)
                    pc.variant_id, pc.price_cents, pc.compare_at_cents, pc.available, pc.checked_at
                FROM price_checks pc
                JOIN variants v ON v.variant_id = pc.variant_id
                WHERE v.site = %s
                ORDER BY pc.variant_id, pc.checked_at DESC;
                """,
                (site,),
            )
            rows = cur.fetchall()
            res = {}
            for r in rows:
                vid = str(r["variant_id"] if isinstance(r, dict) else r[0])
                ts_val = r["checked_at"] if isinstance(r, dict) else r[4]
                ts_str = ts_val.isoformat() if hasattr(ts_val, "isoformat") else str(ts_val)
                res[vid] = {
                    "variant_id": r["variant_id"] if isinstance(r, dict) else r[0],
                    "price_cents": r["price_cents"] if isinstance(r, dict) else r[1],
                    "compare_at_cents": r["compare_at_cents"] if isinstance(r, dict) else r[2],
                    "available": r["available"] if isinstance(r, dict) else r[3],
                    "checked_at": ts_str,
                    "fetched_at": ts_str,
                }
            return res

    def batch_upsert_variants(self, observations: List[Observation]) -> int:
        if not observations:
            return 0
        conn = self._get_connection()
        chunk_size = 100
        for i in range(0, len(observations), chunk_size):
            chunk = observations[i:i + chunk_size]
            placeholders = []
            params = []
            for obs in chunk:
                vid = to_bigint_id(obs.variant_id)
                pid = to_bigint_id(obs.product_id)
                ts = format_iso_timestamp(obs.fetched_at)
                placeholders.append("(%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 'active', 0, %s)")
                params.extend([
                    vid, pid, obs.site, obs.product_title, obs.variant_title,
                    obs.url, obs.currency, ts, ts, ts
                ])
            val_clause = ", ".join(placeholders)
            sql = (
                "INSERT INTO variants ("
                "variant_id, product_id, site, product_title, variant_title, "
                "url, currency, created_at, updated_at, active, status, "
                "consecutive_misses, last_seen_at"
                f") VALUES {val_clause} "
                "ON CONFLICT (variant_id) DO UPDATE SET "
                "product_title = EXCLUDED.product_title, "
                "variant_title = EXCLUDED.variant_title, "
                "url = EXCLUDED.url, "
                "currency = EXCLUDED.currency, "
                "updated_at = EXCLUDED.updated_at, "
                "active = 1, "
                "status = 'active', "
                "consecutive_misses = 0, "
                "last_seen_at = EXCLUDED.last_seen_at;"
            )
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(sql, params)
        return len(observations)

    def batch_insert_price_checks(self, observations: List[Observation]) -> int:
        if not observations:
            return 0
        conn = self._get_connection()
        chunk_size = 100
        for i in range(0, len(observations), chunk_size):
            chunk = observations[i:i + chunk_size]
            placeholders = []
            params = []
            for obs in chunk:
                vid = to_bigint_id(obs.variant_id)
                ts = format_iso_timestamp(obs.fetched_at)
                placeholders.append("(%s, %s, %s, %s, %s)")
                params.extend([
                    vid, obs.price_cents, obs.compare_at_cents,
                    1 if obs.available else 0, ts
                ])
            val_clause = ", ".join(placeholders)
            sql = f"INSERT INTO price_checks (variant_id, price_cents, compare_at_cents, available, checked_at) VALUES {val_clause};"
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(sql, params)
        return len(observations)

    def batch_insert_events(self, events: List[Dict[str, Any]]) -> List[int]:
        if not events:
            return []
        conn = self._get_connection()
        chunk_size = 100
        ids = []
        for i in range(0, len(events), chunk_size):
            chunk = events[i:i + chunk_size]
            placeholders = []
            params = []
            for ev in chunk:
                vid = to_bigint_id(ev["variant_id"])
                ts = format_iso_timestamp(ev["detected_at"])
                placeholders.append("(%s, %s, %s, %s, %s, %s)")
                params.extend([
                    vid, ts, ev["event_type"], ev.get("old_value"),
                    ev.get("new_value"), ev.get("notified", 0)
                ])
            val_clause = ", ".join(placeholders)
            sql = f"INSERT INTO events (variant_id, detected_at, event_type, old_value, new_value, notified) VALUES {val_clause} RETURNING id;"
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                    ids.extend([int(r["id"] if isinstance(r, dict) else r[0]) for r in rows])
        return ids

    def get_unnotified_events(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    e.id, e.variant_id, e.detected_at, e.event_type, e.old_value, e.new_value, e.notified,
                    v.product_title, v.variant_title, v.site, v.url
                FROM events e
                JOIN variants v ON e.variant_id = v.variant_id
                WHERE e.notified = 0
                ORDER BY e.detected_at ASC, e.id ASC;
                """
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["variant_id"] = str(d["variant_id"])
                results.append(d)
            return results

    def mark_events_notified(self, event_ids: List[int]) -> None:
        if not event_ids:
            return
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("UPDATE events SET notified = 1 WHERE id = ANY(%s);", (list(event_ids),))

    def process_presence_and_delisting(
        self,
        site: str,
        seen_variant_ids: List[str],
        confirmed_absent_ids: List[str],
        missing_runs_before_delisted: int = 3,
        fetched_at: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        ts = format_iso_timestamp(fetched_at)
        created_events: List[Dict[str, Any]] = []

        seen_set = set(str(v) for v in seen_variant_ids)
        absent_set = set(str(v) for v in confirmed_absent_ids) - seen_set

        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                # 1. Process seen variants that may have been previously delisted
                cur.execute(
                    "SELECT variant_id, product_title, variant_title, status FROM variants WHERE site = %s AND status IN ('delisted', 'inactive');",
                    (site,),
                )
                delisted_rows = cur.fetchall()
                for row in delisted_rows:
                    vid_val = row["variant_id"] if isinstance(row, dict) else row[0]
                    vid_str = str(vid_val)
                    if vid_str in seen_set:
                        vid = to_bigint_id(vid_val)
                        cur.execute(
                            """
                            UPDATE variants SET
                                status = 'active',
                                active = 1,
                                consecutive_misses = 0,
                                last_seen_at = %s,
                                updated_at = %s
                            WHERE variant_id = %s;
                            """,
                            (ts, ts, vid),
                        )
                        ev_id = self.insert_event(
                            variant_id=vid,
                            detected_at=ts,
                            event_type="relisted",
                            old_value=None,
                            new_value=None,
                            notified=0,
                        )
                        created_events.append(
                            {
                                "id": ev_id,
                                "variant_id": str(vid),
                                "detected_at": ts,
                                "event_type": "relisted",
                                "old_value": None,
                                "new_value": None,
                                "product_title": row["product_title"],
                                "variant_title": row["variant_title"],
                                "site": site,
                                "notified": 0,
                            }
                        )

                # 2. Process confirmed absent variants
                for vid_str in absent_set:
                    vid = to_bigint_id(vid_str)
                    cur.execute(
                        "SELECT variant_id, product_title, variant_title, status, consecutive_misses FROM variants WHERE variant_id = %s AND site = %s;",
                        (vid, site),
                    )
                    row = cur.fetchone()
                    if not row:
                        continue

                    prev_status = row["status"] or "active"
                    curr_misses = (row["consecutive_misses"] or 0) + 1

                    if prev_status == "active" and curr_misses >= missing_runs_before_delisted:
                        cur.execute(
                            """
                            UPDATE variants SET
                                status = 'delisted',
                                consecutive_misses = %s,
                                updated_at = %s
                            WHERE variant_id = %s;
                            """,
                            (curr_misses, ts, vid),
                        )
                        ev_id = self.insert_event(
                            variant_id=vid,
                            detected_at=ts,
                            event_type="delisted",
                            old_value=None,
                            new_value=None,
                            notified=0,
                        )
                        created_events.append(
                            {
                                "id": ev_id,
                                "variant_id": str(vid),
                                "detected_at": ts,
                                "event_type": "delisted",
                                "old_value": None,
                                "new_value": None,
                                "product_title": row["product_title"],
                                "variant_title": row["variant_title"],
                                "site": site,
                                "notified": 0,
                            }
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE variants SET
                                consecutive_misses = %s,
                                updated_at = %s
                            WHERE variant_id = %s;
                            """,
                            (curr_misses, ts, vid),
                        )

        return created_events

    def get_meta(self, key: str) -> Optional[str]:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM meta WHERE key = %s;", (key,))
            row = cur.fetchone()
            if row:
                return str(row["value"] if isinstance(row, dict) else row[0])
            return None

    def set_meta(self, key: str, value: str, updated_at: Optional[str] = None) -> None:
        ts = format_iso_timestamp(updated_at)
        conn = self._get_connection()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meta (key, value, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at;
                    """,
                    (key, str(value), ts),
                )

    def get_latest_site_statuses(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    s.site,
                    s.last_status,
                    s.last_notified_status,
                    s.last_run_at,
                    s.consecutive_failures,
                    s.last_observations_count,
                    (SELECT COUNT(*) FROM variants v WHERE v.site = s.site AND v.active = 1) AS active_variants,
                    (SELECT COUNT(*) FROM variants v WHERE v.site = s.site AND v.status = 'delisted') AS delisted_variants
                FROM site_state s
                ORDER BY s.site ASC;
                """
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def check_health(self) -> Dict[str, Any]:
        """Inspect health metrics for PostgreSQL backend (for --db-check CLI)."""
        conn = self._get_connection()
        t0 = time.time()
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            ver_row = cur.fetchone()
            version = ver_row["version"] if isinstance(ver_row, dict) else ver_row[0]
            latency_ms = (time.time() - t0) * 1000.0

            tables = ["variants", "price_checks", "events", "runs", "site_runs", "errors", "site_state", "meta"]
            table_counts: Dict[str, int] = {}
            for t in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t};")
                    r = cur.fetchone()
                    cnt = r["count"] if isinstance(r, dict) else r[0]
                    table_counts[t] = int(cnt)
                except Exception:
                    table_counts[t] = 0

        masked_target = mask_database_url(self.database_url)
        return {
            "backend": "PostgreSQL (Supabase)",
            "version": version.split(" on ")[0] if " on " in version else version,
            "target": masked_target,
            "host_or_path": masked_target,
            "latency_ms": round(latency_ms, 2),
            "table_counts": table_counts,
            "row_counts": table_counts,
        }


# =============================================================================
# Backend Factory
# =============================================================================


def get_storage(
    database_url: Optional[str] = None,
    db_path: Optional[str] = None,
) -> BaseStorage:
    """Factory creating the appropriate BaseStorage backend.

    Selects PostgresStorage if database_url or DATABASE_URL is set (and no explicit
    db_path was provided without an explicit database_url); otherwise defaults to SqliteStorage.

    Args:
        database_url: Optional explicit PostgreSQL connection string.
        db_path: Optional SQLite database file path.

    Returns:
        BaseStorage implementation instance.
    """
    if db_path is not None and not database_url:
        return SqliteStorage(db_path=db_path)
    pg_url = database_url or os.getenv("DATABASE_URL")
    if pg_url and pg_url.strip():
        return PostgresStorage(database_url=pg_url.strip())

    # CI Guard: Never silently fall back to SQLite in CI
    is_ci = os.getenv("CI", "").strip().lower() in ("true", "1", "yes") or bool(os.getenv("GITHUB_ACTIONS"))
    if is_ci and not database_url and db_path is None:
        raise RuntimeError("DATABASE_URL is required in CI (SQLite does not persist in Actions)")

    return SqliteStorage(db_path=db_path)


# =============================================================================
# Legacy Module-Level Helper Functions (100% Backwards Compatible for Tests)
# =============================================================================


def backup_database_if_needed(db_path: Optional[str] = None) -> Optional[str]:
    """Create timestamped backup copy (prices_backup_<timestamp>.db) for SQLite database."""
    path = db_path or DEFAULT_DB_PATH
    if not os.path.exists(path):
        return None
    try:
        if os.path.getsize(path) == 0:
            return None
    except OSError:
        return None

    dirname = os.path.dirname(path) or "."
    try:
        existing = [
            f for f in os.listdir(dirname)
            if f.startswith("prices_backup_") and f.endswith(".db")
        ]
        if existing:
            return None
    except OSError:
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(dirname, f"prices_backup_{timestamp}.db")
    try:
        shutil.copy2(path, backup_file)
        logger.info("Created database backup copy before migration: %s", backup_file)
        return backup_file
    except Exception as exc:
        logger.warning("Failed to create database backup: %s", exc)
        return None


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Return an SQLite database connection (legacy helper)."""
    return SqliteStorage(db_path=db_path).get_connection()


def init_db(db_path: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> None:
    """Initialize SQLite database tables and migrations (legacy helper)."""
    should_close = False
    if conn is None:
        backup_database_if_needed(db_path)
        conn = get_connection(db_path)
        should_close = True
    else:
        try:
            cur = conn.execute("PRAGMA database_list;")
            for row in cur.fetchall():
                file_candidate = row[2] if len(row) > 2 else row["file"]
                if file_candidate and os.path.exists(file_candidate):
                    backup_database_if_needed(file_candidate)
                    break
        except Exception:
            pass

    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS variants (
                    variant_id TEXT PRIMARY KEY,
                    product_id TEXT,
                    site TEXT NOT NULL,
                    product_title TEXT NOT NULL,
                    variant_title TEXT,
                    url TEXT,
                    currency TEXT,
                    active INTEGER DEFAULT 1,
                    consecutive_misses INTEGER DEFAULT 0,
                    last_seen_at TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            # Safe migration: ensure new columns exist
            variants_info = conn.execute("PRAGMA table_info(variants);").fetchall()
            existing_variant_cols = {col["name"] for col in variants_info} if variants_info else set()
            if "active" not in existing_variant_cols:
                conn.execute("ALTER TABLE variants ADD COLUMN active INTEGER DEFAULT 1;")
            if "consecutive_misses" not in existing_variant_cols:
                conn.execute("ALTER TABLE variants ADD COLUMN consecutive_misses INTEGER DEFAULT 0;")
            if "last_seen_at" not in existing_variant_cols:
                conn.execute("ALTER TABLE variants ADD COLUMN last_seen_at TEXT;")
            if "status" not in existing_variant_cols:
                conn.execute("ALTER TABLE variants ADD COLUMN status TEXT DEFAULT 'active';")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    variant_id TEXT NOT NULL,
                    price_cents INTEGER,
                    compare_at_cents INTEGER,
                    available INTEGER NOT NULL,
                    fetched_at TEXT NOT NULL,
                    FOREIGN KEY (variant_id) REFERENCES variants(variant_id)
                );
                """
            )

            table_info = conn.execute("PRAGMA table_info(events);").fetchall()
            existing_cols = {col["name"] for col in table_info} if table_info else set()
            if existing_cols and "detected_at" not in existing_cols:
                conn.execute("DROP TABLE events;")
                existing_cols = set()

            if not existing_cols:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        variant_id INTEGER NOT NULL,
                        detected_at TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        old_value INTEGER,
                        new_value INTEGER,
                        notified INTEGER DEFAULT 0
                    );
                    """
                )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    sites_total INTEGER DEFAULT 0,
                    sites_ok INTEGER DEFAULT 0,
                    sites_failed INTEGER DEFAULT 0,
                    variants_seen INTEGER DEFAULT 0,
                    events_created INTEGER DEFAULT 0
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    site TEXT NOT NULL,
                    status TEXT NOT NULL,
                    urls_total INTEGER DEFAULT 0,
                    urls_failed INTEGER DEFAULT 0,
                    observations_count INTEGER DEFAULT 0,
                    prev_observations_count INTEGER DEFAULT 0,
                    error_summary TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    site TEXT NOT NULL,
                    error_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    url TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_state (
                    site TEXT PRIMARY KEY,
                    last_status TEXT NOT NULL,
                    last_notified_status TEXT,
                    last_run_at TEXT NOT NULL,
                    consecutive_failures INTEGER DEFAULT 0,
                    last_observations_count INTEGER DEFAULT 0
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            conn.execute("CREATE INDEX IF NOT EXISTS idx_price_checks_variant ON price_checks(variant_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_price_checks_fetched ON price_checks(fetched_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_variants_site ON variants(site);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_variant ON events(variant_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_notified ON events(notified);")
    finally:
        if should_close:
            conn.close()


def is_price_checks_empty(conn: Any) -> bool:
    if isinstance(conn, BaseStorage):
        return conn.is_price_checks_empty()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM price_checks LIMIT 1;")
    return cur.fetchone() is None


def is_variant_in_catalog(conn: Any, variant_id: Union[str, int]) -> bool:
    if isinstance(conn, BaseStorage):
        return conn.is_variant_in_catalog(variant_id)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM variants WHERE variant_id = ?;", (str(variant_id),))
    return cur.fetchone() is not None


def get_last_check(conn: Any, variant_id: Union[str, int]) -> Optional[Dict[str, Any]]:
    if isinstance(conn, BaseStorage):
        return conn.get_last_check(variant_id)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, variant_id, price_cents, compare_at_cents, available, fetched_at
        FROM price_checks
        WHERE variant_id = ?
        ORDER BY fetched_at DESC, id DESC
        LIMIT 1;
        """,
        (str(variant_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def upsert_variant(conn: Any, observation: Observation) -> bool:
    if isinstance(conn, BaseStorage):
        return conn.upsert_variant(observation)
    ts = format_iso_timestamp(observation.fetched_at)
    with conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM variants WHERE variant_id = ?;", (str(observation.variant_id),))
        is_new = cur.fetchone() is None
        cur.execute(
            """
            INSERT INTO variants (
                variant_id, product_id, site, product_title, variant_title,
                url, currency, created_at, updated_at, active, status, consecutive_misses, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', 0, ?)
            ON CONFLICT(variant_id) DO UPDATE SET
                product_id = excluded.product_id,
                site = excluded.site,
                product_title = excluded.product_title,
                variant_title = excluded.variant_title,
                url = excluded.url,
                currency = excluded.currency,
                updated_at = excluded.updated_at,
                active = 1,
                status = 'active',
                consecutive_misses = 0,
                last_seen_at = excluded.last_seen_at;
            """,
            (
                str(observation.variant_id),
                str(observation.product_id),
                observation.site,
                observation.product_title,
                observation.variant_title,
                observation.url,
                observation.currency,
                ts,
                ts,
                ts,
            ),
        )
        return is_new


def insert_price_check(conn: Any, observation: Observation) -> int:
    if isinstance(conn, BaseStorage):
        return conn.insert_price_check(observation)
    ts = format_iso_timestamp(observation.fetched_at)
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO price_checks (variant_id, price_cents, compare_at_cents, available, fetched_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                str(observation.variant_id),
                observation.price_cents,
                observation.compare_at_cents,
                1 if observation.available else 0,
                ts,
            ),
        )
        return cur.lastrowid or 0


def insert_event(
    conn: Any,
    variant_id: Union[str, int],
    detected_at: str,
    event_type: str,
    old_value: Optional[int] = None,
    new_value: Optional[int] = None,
    notified: int = 0,
) -> int:
    if isinstance(conn, BaseStorage):
        return conn.insert_event(variant_id, detected_at, event_type, old_value=old_value, new_value=new_value, notified=notified)
    val_id = int(variant_id) if str(variant_id).isdigit() else variant_id
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO events (variant_id, detected_at, event_type, old_value, new_value, notified)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (val_id, detected_at, event_type, old_value, new_value, notified),
    )
    return cur.lastrowid or 0


def get_unnotified_events(conn: Any) -> List[Dict[str, Any]]:
    if isinstance(conn, BaseStorage):
        return conn.get_unnotified_events()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 
            e.id, e.variant_id, e.detected_at, e.event_type, e.old_value, e.new_value, e.notified,
            v.product_title, v.variant_title, v.site, v.url
        FROM events e
        LEFT JOIN variants v ON CAST(e.variant_id AS TEXT) = CAST(v.variant_id AS TEXT)
        WHERE e.notified = 0
        ORDER BY e.detected_at ASC, e.id ASC;
        """
    )
    return [dict(row) for row in cur.fetchall()]


def mark_events_notified(conn: Any, event_ids: List[int]) -> None:
    if isinstance(conn, BaseStorage):
        return conn.mark_events_notified(event_ids)
    if not event_ids:
        return
    placeholders = ",".join("?" * len(event_ids))
    with conn:
        conn.execute(f"UPDATE events SET notified = 1 WHERE id IN ({placeholders});", event_ids)


def get_variant_ids_for_site(conn: Any, site: str, active_only: bool = True) -> List[str]:
    if isinstance(conn, BaseStorage):
        return conn.get_variant_ids_for_site(site, active_only=active_only)
    cur = conn.cursor()
    if active_only:
        cur.execute("SELECT variant_id FROM variants WHERE site = ? AND active = 1;", (site,))
    else:
        cur.execute("SELECT variant_id FROM variants WHERE site = ?;", (site,))
    return [str(row["variant_id"]) for row in cur.fetchall()]


def find_active_variant_ids_by_url_substr(
    conn: Any, site: str, url_substring: str
) -> List[str]:
    """Find active variant IDs for a site matching a URL substring."""
    if isinstance(conn, BaseStorage):
        return conn.find_active_variant_ids_by_url_substr(site, url_substring)
    cur = conn.cursor()
    cur.execute(
        "SELECT variant_id FROM variants WHERE site = ? AND url LIKE ? AND active = 1;",
        (site, f"%{url_substring}%"),
    )
    return [str(row["variant_id"]) for row in cur.fetchall()]


def deactivate_removed_variants(conn: Any, site: str, active_urls: List[str]) -> int:
    if isinstance(conn, BaseStorage):
        return conn.deactivate_removed_variants(site, active_urls)
    if not active_urls:
        return 0
    normalized_active = [u.split("?")[0].rstrip("/").lower() for u in active_urls if u]
    cur = conn.cursor()
    cur.execute("SELECT variant_id, url FROM variants WHERE site = ? AND active = 1;", (site,))
    rows = cur.fetchall()
    deactivated = []
    ts = datetime.now(timezone.utc).isoformat()
    with conn:
        for r in rows:
            u = (r["url"] or "").split("?")[0].rstrip("/").lower()
            if u not in normalized_active:
                vid = str(r["variant_id"])
                deactivated.append(vid)
                conn.execute(
                    "UPDATE variants SET active = 0, updated_at = ? WHERE variant_id = ?;",
                    (ts, vid),
                )
    return len(deactivated)


def record_run_start(conn: Any, started_at: Optional[str] = None) -> int:
    if isinstance(conn, BaseStorage):
        return conn.record_run_start(started_at=started_at)
    ts = format_iso_timestamp(started_at)
    with conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO runs (started_at, status) VALUES (?, ?);", (ts, "in_progress"))
        return cur.lastrowid or 0


def record_run_finish(
    conn: Any,
    run_id: int,
    status: str,
    sites_total: int,
    sites_ok: int,
    sites_failed: int,
    variants_seen: int,
    events_created: int,
    finished_at: Optional[str] = None,
) -> None:
    if isinstance(conn, BaseStorage):
        return conn.record_run_finish(
            run_id=run_id,
            status=status,
            sites_total=sites_total,
            sites_ok=sites_ok,
            sites_failed=sites_failed,
            variants_seen=variants_seen,
            events_created=events_created,
            finished_at=finished_at,
        )
    ts = format_iso_timestamp(finished_at)
    with conn:
        conn.execute(
            """
            UPDATE runs SET
                finished_at = ?, status = ?, sites_total = ?, sites_ok = ?,
                sites_failed = ?, variants_seen = ?, events_created = ?
            WHERE run_id = ?;
            """,
            (ts, status, sites_total, sites_ok, sites_failed, variants_seen, events_created, run_id),
        )


def record_site_run(
    conn: Any,
    run_id: int,
    site: str,
    status: str,
    urls_total: int,
    urls_failed: int,
    observations_count: int,
    prev_observations_count: int,
    error_summary: Optional[str] = None,
    created_at: Optional[str] = None,
) -> None:
    if isinstance(conn, BaseStorage):
        return conn.record_site_run(
            run_id=run_id,
            site=site,
            status=status,
            urls_total=urls_total,
            urls_failed=urls_failed,
            observations_count=observations_count,
            prev_observations_count=prev_observations_count,
            error_summary=error_summary,
            created_at=created_at,
        )
    ts = format_iso_timestamp(created_at)
    with conn:
        conn.execute(
            """
            INSERT INTO site_runs (
                run_id, site, status, urls_total, urls_failed,
                observations_count, prev_observations_count, error_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (run_id, site, status, urls_total, urls_failed, observations_count, prev_observations_count, error_summary, ts),
        )


def insert_error_record(
    conn: Any,
    site: str,
    error_type: str,
    message: str,
    url: Optional[str] = None,
    run_id: Optional[int] = None,
    created_at: Optional[str] = None,
) -> int:
    if isinstance(conn, BaseStorage):
        return conn.insert_error_record(
            site=site,
            error_type=error_type,
            message=message,
            url=url,
            run_id=run_id,
            created_at=created_at,
        )
    ts = format_iso_timestamp(created_at)
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO errors (run_id, site, error_type, message, url, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (run_id, site, error_type, message, url, ts),
        )
        return cur.lastrowid or 0


def get_site_state(conn: Any, site: str) -> Optional[Dict[str, Any]]:
    if isinstance(conn, BaseStorage):
        return conn.get_site_state(site)
    cur = conn.cursor()
    cur.execute("SELECT * FROM site_state WHERE site = ?;", (site,))
    row = cur.fetchone()
    return dict(row) if row else None


def upsert_site_state(
    conn: Any,
    site: str,
    status: str,
    observations_count: int = 0,
    last_notified_status: Optional[str] = None,
    run_at: Optional[str] = None,
) -> None:
    if isinstance(conn, BaseStorage):
        return conn.upsert_site_state(
            site=site,
            status=status,
            observations_count=observations_count,
            last_notified_status=last_notified_status,
            run_at=run_at,
        )
    ts = format_iso_timestamp(run_at)
    existing = get_site_state(conn, site)
    with conn:
        cur = conn.cursor()
        if existing is None:
            cur.execute(
                """
                INSERT INTO site_state (
                    site, last_status, last_notified_status, last_run_at, consecutive_failures, last_observations_count
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (site, status, last_notified_status or status, ts, 0 if status == "ok" else 1, observations_count),
            )
        else:
            prev_fails = existing.get("consecutive_failures", 0) or 0
            new_fails = 0 if status == "ok" else (prev_fails + 1)
            notified_st = last_notified_status if last_notified_status is not None else existing.get("last_notified_status")
            cur.execute(
                """
                UPDATE site_state SET
                    last_status = ?,
                    last_notified_status = ?,
                    last_run_at = ?,
                    consecutive_failures = ?,
                    last_observations_count = ?
                WHERE site = ?;
                """,
                (status, notified_st, ts, new_fails, observations_count, site),
            )


def get_latest_site_statuses(conn: Any) -> List[Dict[str, Any]]:
    if isinstance(conn, BaseStorage):
        return conn.get_latest_site_statuses()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='site_state';")
    if not cur.fetchone():
        return []

    cur.execute(
        """
        SELECT 
            s.site,
            s.last_status,
            s.last_notified_status,
            s.last_run_at,
            s.consecutive_failures,
            s.last_observations_count,
            (SELECT COUNT(*) FROM variants v WHERE v.site = s.site AND v.active = 1) AS active_variants,
            (SELECT COUNT(*) FROM variants v WHERE v.site = s.site AND v.status = 'delisted') AS delisted_variants
        FROM site_state s
        ORDER BY s.site ASC;
        """
    )
    return [dict(row) for row in cur.fetchall()]


def get_meta(conn: Any, key: str) -> Optional[str]:
    if isinstance(conn, BaseStorage):
        return conn.get_meta(key)
    cur = conn.cursor()
    cur.execute("SELECT value FROM meta WHERE key = ?;", (key,))
    row = cur.fetchone()
    return str(row["value"]) if row else None


def set_meta(conn: Any, key: str, value: str, updated_at: Optional[str] = None) -> None:
    if isinstance(conn, BaseStorage):
        return conn.set_meta(key, value, updated_at=updated_at)
    ts = format_iso_timestamp(updated_at)
    with conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO meta (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
            """,
            (key, str(value), ts),
        )


def process_presence_and_delisting(
    conn: Any,
    site: str,
    seen_variant_ids: List[str],
    confirmed_absent_ids: List[str],
    missing_runs_before_delisted: int = 3,
    fetched_at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    if isinstance(conn, BaseStorage):
        return conn.process_presence_and_delisting(
            site=site,
            seen_variant_ids=seen_variant_ids,
            confirmed_absent_ids=confirmed_absent_ids,
            missing_runs_before_delisted=missing_runs_before_delisted,
            fetched_at=fetched_at,
        )
    ts = format_iso_timestamp(fetched_at)
    created_events: List[Dict[str, Any]] = []
    seen_set = set(str(v) for v in seen_variant_ids)
    absent_set = set(str(v) for v in confirmed_absent_ids) - seen_set

    cur = conn.cursor()

    # 1. Process seen variants that may have been previously delisted
    cur.execute(
        "SELECT variant_id, product_title, variant_title, status FROM variants WHERE site = ? AND status IN ('delisted', 'inactive');",
        (site,),
    )
    for row in cur.fetchall():
        vid = str(row["variant_id"])
        if vid in seen_set:
            cur.execute(
                """
                UPDATE variants SET
                    status = 'active',
                    active = 1,
                    consecutive_misses = 0,
                    last_seen_at = ?,
                    updated_at = ?
                WHERE variant_id = ?;
                """,
                (ts, ts, vid),
            )
            ev_id = insert_event(
                conn=conn,
                variant_id=vid,
                detected_at=ts,
                event_type="relisted",
                old_value=None,
                new_value=None,
                notified=0,
            )
            created_events.append(
                {
                    "id": ev_id,
                    "variant_id": vid,
                    "detected_at": ts,
                    "event_type": "relisted",
                    "old_value": None,
                    "new_value": None,
                    "product_title": row["product_title"],
                    "variant_title": row["variant_title"],
                    "site": site,
                    "notified": 0,
                }
            )

    # 2. Process confirmed absent variants
    for vid in absent_set:
        cur.execute(
            "SELECT variant_id, product_title, variant_title, status, consecutive_misses FROM variants WHERE variant_id = ? AND site = ?;",
            (vid, site),
        )
        row = cur.fetchone()
        if not row:
            continue

        prev_status = row["status"] or "active"
        curr_misses = (row["consecutive_misses"] or 0) + 1

        if prev_status == "active" and curr_misses >= missing_runs_before_delisted:
            cur.execute(
                """
                UPDATE variants SET
                    status = 'delisted',
                    consecutive_misses = ?,
                    updated_at = ?
                WHERE variant_id = ?;
                """,
                (curr_misses, ts, vid),
            )
            ev_id = insert_event(
                conn=conn,
                variant_id=vid,
                detected_at=ts,
                event_type="delisted",
                old_value=None,
                new_value=None,
                notified=0,
            )
            created_events.append(
                {
                    "id": ev_id,
                    "variant_id": vid,
                    "detected_at": ts,
                    "event_type": "delisted",
                    "old_value": None,
                    "new_value": None,
                    "product_title": row["product_title"],
                    "variant_title": row["variant_title"],
                    "site": site,
                    "notified": 0,
                }
            )
        else:
            cur.execute(
                """
                UPDATE variants SET
                    consecutive_misses = ?,
                    updated_at = ?
                WHERE variant_id = ?;
                """,
                (curr_misses, ts, vid),
            )

    return created_events


def get_site_variant_ids(conn: Any, site: str) -> set:
    if isinstance(conn, BaseStorage):
        return conn.get_site_variant_ids(site)
    cur = conn.cursor()
    cur.execute("SELECT variant_id FROM variants WHERE site = ?;", (site,))
    return {str(row[0]) for row in cur.fetchall()}


def get_site_latest_checks(conn: Any, site: str) -> Dict[str, Dict[str, Any]]:
    if isinstance(conn, BaseStorage):
        return conn.get_site_latest_checks(site)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pc.variant_id, pc.price_cents, pc.compare_at_cents, pc.available, pc.fetched_at
        FROM price_checks pc
        JOIN variants v ON v.variant_id = pc.variant_id
        WHERE v.site = ?
        ORDER BY pc.variant_id, pc.fetched_at DESC;
        """,
        (site,),
    )
    res = {}
    for row in cur.fetchall():
        vid = str(row[0])
        if vid not in res:
            res[vid] = {
                "variant_id": row[0],
                "price_cents": row[1],
                "compare_at_cents": row[2],
                "available": row[3],
                "checked_at": row[4],
                "fetched_at": row[4],
            }
    return res


def batch_upsert_variants(conn: Any, observations: List[Observation]) -> int:
    if isinstance(conn, BaseStorage):
        return conn.batch_upsert_variants(observations)
    for obs in observations:
        upsert_variant(conn, obs)
    return len(observations)


def batch_insert_price_checks(conn: Any, observations: List[Observation]) -> int:
    if isinstance(conn, BaseStorage):
        return conn.batch_insert_price_checks(observations)
    for obs in observations:
        insert_price_check(conn, obs)
    return len(observations)


def batch_insert_events(conn: Any, events: List[Dict[str, Any]]) -> List[int]:
    if isinstance(conn, BaseStorage):
        return conn.batch_insert_events(events)
    ids = []
    for ev in events:
        eid = insert_event(
            conn=conn,
            variant_id=ev["variant_id"],
            detected_at=ev["detected_at"],
            event_type=ev["event_type"],
            old_value=ev.get("old_value"),
            new_value=ev.get("new_value"),
            notified=ev.get("notified", 0),
        )
        ids.append(eid)
    return ids

