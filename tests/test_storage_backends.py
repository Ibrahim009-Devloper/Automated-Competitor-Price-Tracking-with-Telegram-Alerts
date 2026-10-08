"""Backend contract tests and unit tests for SQLite and PostgreSQL storage implementations."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from monitor.models import Observation
from monitor.storage import (
    BaseStorage,
    PostgresStorage,
    SqliteStorage,
    get_storage,
    mask_database_url,
    to_bigint_id,
)
from scripts.migrate_sqlite_to_postgres import (
    get_readonly_sqlite_conn,
    get_sqlite_row_count,
    migrate_table,
)


# =============================================================================
# URL Masking Tests
# =============================================================================


def test_mask_database_url_standard():
    """Verify password segment is replaced with asterisks in standard Postgres URLs."""
    raw = "postgresql://postgres:supersecretpassword@db.supabase.co:5432/postgres"
    masked = mask_database_url(raw)
    assert "supersecretpassword" not in masked
    assert masked == "postgresql://postgres:*****@db.supabase.co:5432/postgres"


def test_mask_database_url_special_characters():
    """Verify password with percent-encoded characters is masked correctly."""
    raw = "postgresql://myuser:p%40ss%23word%21@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
    masked = mask_database_url(raw)
    assert "p%40ss%23word%21" not in masked
    assert masked.startswith("postgresql://myuser:*****@aws-0-us-east-1.pooler.supabase.com:6543/postgres")


def test_mask_database_url_no_password():
    """Verify URLs without password remain intact."""
    raw = "postgresql://localhost:5432/mydb"
    masked = mask_database_url(raw)
    assert masked == raw


def test_mask_database_url_none_or_empty():
    """Verify None or empty strings are handled safely."""
    assert mask_database_url(None) == ""
    assert mask_database_url("") == ""


# =============================================================================
# ID and Translation Helpers Tests
# =============================================================================


def test_to_bigint_id_numeric():
    """Numeric string and integer IDs preserve their 64-bit value."""
    # 64-bit Shopify variant id
    val_64bit = 8923482390482039
    assert to_bigint_id(val_64bit) == val_64bit
    assert to_bigint_id(str(val_64bit)) == val_64bit


def test_to_bigint_id_non_numeric():
    """Non-numeric string IDs (e.g. slugs) deterministically hash into positive BIGINT."""
    h1 = to_bigint_id("cream-soothing-50ml")
    h2 = to_bigint_id("cream-soothing-50ml")
    assert isinstance(h1, int)
    assert h1 == h2
    assert 1 <= h1 < (2**63 - 1)


def test_to_bigint_id_none():
    """None values return None."""
    assert to_bigint_id(None) is None


# =============================================================================
# Concurrency & Advisory Lock Tests
# =============================================================================


def test_sqlite_file_locking(tmp_path: Path):
    """SqliteStorage acquires file lock and prevents concurrent run."""
    db_file = tmp_path / "lock_test.db"
    store1 = SqliteStorage(str(db_file))
    store2 = SqliteStorage(str(db_file))

    # store1 acquires lock
    assert store1.acquire_lock() is True
    assert os.path.exists(store1.lock_path)

    # store2 cannot acquire lock while store1 holds it
    assert store2.acquire_lock() is False

    # store1 releases lock
    store1.release_lock()
    assert not os.path.exists(store1.lock_path)

    # store2 can now acquire lock
    assert store2.acquire_lock() is True
    store2.release_lock()


def test_postgres_advisory_lock_mocked():
    """PostgresStorage uses pg_try_advisory_lock and handles held locks cleanly."""
    store = PostgresStorage(database_url="postgresql://test:pass@localhost:5432/mockdb")

    # Case 1: Lock is available -> returns True
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"pg_try_advisory_lock": True}
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch.object(store, "_get_connection", return_value=mock_conn):
        assert store.acquire_lock() is True
        mock_cur.execute.assert_called_with(
            "SELECT pg_try_advisory_lock(%s);", (83921049281,)
        )

        # Release lock
        store.release_lock()
        mock_cur.execute.assert_called_with(
            "SELECT pg_advisory_unlock(%s);", (83921049281,)
        )

    # Case 2: Lock is already held by another run -> returns False
    mock_cur_held = MagicMock()
    mock_cur_held.fetchone.return_value = {"pg_try_advisory_lock": False}
    mock_conn_held = MagicMock()
    mock_conn_held.cursor.return_value.__enter__.return_value = mock_cur_held

    with patch.object(store, "_get_connection", return_value=mock_conn_held):
        assert store.acquire_lock() is False


# =============================================================================
# Storage Backend Factory Tests
# =============================================================================


def test_get_storage_selects_backend(tmp_path: Path):
    """get_storage factory returns SqliteStorage when DATABASE_URL is unset, and PostgresStorage when set."""
    db_file = tmp_path / "factory.db"

    # With no DATABASE_URL -> SqliteStorage
    with patch.dict(os.environ, {}, clear=True):
        st = get_storage(db_path=str(db_file))
        assert isinstance(st, SqliteStorage)
        assert st.db_path == str(db_file)

    # With DATABASE_URL -> PostgresStorage
    fake_pg_url = "postgresql://user:pass@ep-pooler.supabase.com:6543/postgres"
    with patch.dict(os.environ, {"DATABASE_URL": fake_pg_url}):
        st = get_storage()
        assert isinstance(st, PostgresStorage)
        assert st.database_url == fake_pg_url


# =============================================================================
# Backend Contract Tests (Parametrized over SQLite and Postgres)
# =============================================================================


@pytest.fixture(params=["sqlite", "postgres"])
def storage_backend(request, tmp_path: Path):
    """Provide a storage instance for contract tests.

    Skips postgres if TEST_DATABASE_URL is not set.
    """
    backend_type = request.param

    if backend_type == "sqlite":
        db_path = str(tmp_path / "contract_test.db")
        store = SqliteStorage(db_path=db_path)
        store.init_db()
        yield store
        store.close()

    elif backend_type == "postgres":
        test_url = os.getenv("TEST_DATABASE_URL")
        if not test_url:
            pytest.skip("TEST_DATABASE_URL not set; skipping live PostgreSQL contract tests")

        # Live postgres testing in dedicated test schema
        import psycopg
        from psycopg.rows import dict_row

        schema_name = f"test_schema_{int(time.time())}"
        admin_conn = psycopg.connect(test_url, autocommit=True)
        with admin_conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name};")
        admin_conn.close()

        # Connect with search_path set to isolated test schema
        store = PostgresStorage(database_url=f"{test_url}?options=-csearch_path%3D{schema_name}")
        store.init_db()
        yield store

        store.close()
        # Drop test schema after completion
        admin_conn = psycopg.connect(test_url, autocommit=True)
        with admin_conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
        admin_conn.close()


def test_storage_contract_lifecycle(storage_backend: BaseStorage):
    """Contract test verifying all storage operations on any compliant backend."""
    store = storage_backend

    # 1. Baseline check: is_price_checks_empty should be True initially
    assert store.is_price_checks_empty() is True

    # 2. Record run start and finish
    run_id = store.record_run_start()
    assert run_id > 0

    # 3. Upsert variant observation
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
    obs = Observation(
        site="Skin Care Store",
        product_id="101",
        variant_id="202",
        product_title="Hydrating Toner",
        variant_title="200ml",
        price_cents=2500,
        compare_at_cents=3000,
        currency="USD",
        available=True,
        url="https://store.com/toner?variant=202",
        fetched_at=now,
    )
    is_new = store.upsert_variant(obs)
    assert is_new is True

    # Check catalog presence
    assert store.is_variant_in_catalog("202") is True
    assert store.is_variant_in_catalog("9999") is False

    # 4. Insert price check
    check_id = store.insert_price_check(obs)
    assert check_id > 0
    assert store.is_price_checks_empty() is False

    # 5. Fetch last check
    last_check = store.get_last_check("202")
    assert last_check is not None
    assert int(last_check["price_cents"]) == 2500
    assert int(last_check["available"]) == 1

    # 6. Insert event and query unnotified
    event_id = store.insert_event(
        variant_id="202",
        detected_at=now.isoformat(),
        event_type="price_drop",
        old_value=3000,
        new_value=2500,
        notified=0,
    )
    assert event_id > 0

    unnotified = store.get_unnotified_events()
    assert len(unnotified) >= 1
    found_ev = next(e for e in unnotified if e["id"] == event_id)
    assert str(found_ev["variant_id"]) == "202"
    assert found_ev["event_type"] == "price_drop"

    # Mark notified
    store.mark_events_notified([event_id])
    unnotified_after = store.get_unnotified_events()
    assert all(e["id"] != event_id for e in unnotified_after)

    # 7. Site run & site state tracking
    store.record_site_run(
        run_id=run_id,
        site="Skin Care Store",
        status="ok",
        urls_total=5,
        urls_failed=0,
        observations_count=1,
        prev_observations_count=0,
    )
    store.upsert_site_state(
        site="Skin Care Store",
        status="ok",
        observations_count=1,
    )
    state = store.get_site_state("Skin Care Store")
    assert state is not None
    assert state["site"] == "Skin Care Store"
    assert state["last_status"] == "ok"

    # 8. Meta table get and set
    store.set_meta("last_test_key", "sample_val")
    assert store.get_meta("last_test_key") == "sample_val"

    # 9. Health diagnostic check
    health = store.check_health()
    assert "backend" in health
    assert "version" in health
    assert "latency_ms" in health
    assert "table_counts" in health
    assert health["table_counts"]["variants"] >= 1
    assert health["table_counts"]["price_checks"] >= 1

    # 10. URL substring lookup
    matched_ids = store.find_active_variant_ids_by_url_substr("Skin Care Store", "toner")
    assert "202" in matched_ids

    # 11. Deactivate removed variants
    deactivated_count = store.deactivate_removed_variants("Skin Care Store", ["https://store.com/other"])
    assert deactivated_count == 1
    variant_ids_active = store.get_variant_ids_for_site("Skin Care Store", active_only=True)
    assert "202" not in variant_ids_active

    # Finish run record
    store.record_run_finish(
        run_id=run_id,
        status="success",
        sites_total=1,
        sites_ok=1,
        sites_failed=0,
        variants_seen=1,
        events_created=1,
    )


# =============================================================================
# Migration Script Unit Tests
# =============================================================================


def test_migration_script_dry_run_and_readonly(tmp_path: Path):
    """Test migration script reads SQLite read-only and does not modify it."""
    # Create temp SQLite DB with sample data
    db_file = tmp_path / "source.db"
    store = SqliteStorage(str(db_file))
    store.init_db()

    obs = Observation(
        site="Sample Store",
        product_id="10",
        variant_id="20",
        product_title="Serum",
        variant_title="30ml",
        price_cents=1800,
        compare_at_cents=2200,
        currency="USD",
        available=True,
        url="https://store.com/serum?variant=20",
        fetched_at=datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc),
    )
    store.upsert_variant(obs)
    store.insert_price_check(obs)
    store.close()

    # Get file modification time before migration
    mtime_before = os.path.getmtime(db_file)

    # 1. Test read-only connection
    ro_conn = get_readonly_sqlite_conn(str(db_file))
    with pytest.raises(sqlite3.OperationalError):
        # Attempting write on read-only connection MUST fail
        ro_conn.execute("INSERT INTO meta (key, value, updated_at) VALUES ('x', 'y', 'z');")

    assert get_sqlite_row_count(ro_conn, "variants") == 1
    assert get_sqlite_row_count(ro_conn, "price_checks") == 1

    # 2. Test migrate_table in dry-run mode
    total, copied = migrate_table("variants", ro_conn, None, batch_size=10, dry_run=True)
    assert total == 1
    assert copied == 1
    ro_conn.close()

    # Ensure SQLite file timestamp and contents remain untouched
    assert os.path.getmtime(db_file) == mtime_before
