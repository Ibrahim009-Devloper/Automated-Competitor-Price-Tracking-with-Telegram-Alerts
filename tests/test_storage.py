"""Unit tests for SQLite storage layer."""

import sqlite3
from datetime import datetime, timezone
import pytest

from monitor.models import Observation
from monitor.storage import (
    init_db,
    upsert_variant,
    insert_price_check,
    get_last_check,
    insert_event,
    get_unnotified_events,
    is_price_checks_empty,
    get_variant_ids_for_site,
)


@pytest.fixture
def memory_db() -> sqlite3.Connection:
    """Create an in-memory database initialized with the schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn=conn)
    return conn


def test_upsert_variant_and_insert_price_check(memory_db: sqlite3.Connection):
    """Test inserting new variant and appending price check history."""
    now = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
    obs1 = Observation(
        site="Demo Skin",
        product_id="101",
        variant_id="202",
        product_title="Hyaluronic Serum",
        variant_title="50ml",
        price_cents=2500,
        compare_at_cents=3000,
        currency="USD",
        available=True,
        url="https://demo.com/products/serum?variant=202",
        fetched_at=now,
    )

    with memory_db:
        # First upsert should report as new
        is_new = upsert_variant(memory_db, obs1)
        assert is_new is True

        # Check insertion
        check_id = insert_price_check(memory_db, obs1)
        assert check_id > 0

    # Retrieve last check
    last_check = get_last_check(memory_db, "202")
    assert last_check is not None
    assert last_check["price_cents"] == 2500
    assert last_check["compare_at_cents"] == 3000
    assert last_check["available"] == 1

    # Second check for same variant with price drop
    obs2 = Observation(
        site="Demo Skin",
        product_id="101",
        variant_id="202",
        product_title="Hyaluronic Serum (Updated Title)",
        variant_title="50ml",
        price_cents=2100,
        compare_at_cents=3000,
        currency="USD",
        available=True,
        url="https://demo.com/products/serum?variant=202",
        fetched_at=datetime(2026, 10, 7, 13, 0, 0, tzinfo=timezone.utc),
    )

    with memory_db:
        # Second upsert should update variant, not report as new
        is_new_second = upsert_variant(memory_db, obs2)
        assert is_new_second is False

        # Add second check
        insert_price_check(memory_db, obs2)

    # Historical checks must both exist (never delete rows)
    cur = memory_db.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM price_checks WHERE variant_id = '202'")
    assert cur.fetchone()["cnt"] == 2

    # Latest check should reflect obs2
    latest = get_last_check(memory_db, "202")
    assert latest["price_cents"] == 2100


def test_insert_event_and_get_unnotified(memory_db: sqlite3.Connection):
    """Test inserting events and retrieving unnotified ones."""
    now_iso = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    with memory_db:
        event_id = insert_event(
            memory_db,
            variant_id=202,
            detected_at=now_iso,
            event_type="price_drop",
            old_value=2500,
            new_value=2100,
            notified=0,
        )
        assert event_id > 0

    # Retrieve unnotified events
    unnotified = get_unnotified_events(memory_db)
    assert len(unnotified) == 1
    ev = unnotified[0]
    assert ev["variant_id"] == 202
    assert ev["event_type"] == "price_drop"
    assert ev["old_value"] == 2500
    assert ev["new_value"] == 2100
    assert ev["notified"] == 0


def test_is_price_checks_empty_and_get_variant_ids(memory_db: sqlite3.Connection):
    """Test is_price_checks_empty helper for baseline checks and get_variant_ids_for_site."""
    assert is_price_checks_empty(memory_db) is True

    obs = Observation(
        site="Skin Store",
        product_id="1",
        variant_id="999",
        product_title="Cleanser",
        variant_title="Default",
        price_cents=1000,
        compare_at_cents=None,
        currency="USD",
        available=True,
        url="https://store.com/p",
        fetched_at=datetime.now(timezone.utc),
    )

    with memory_db:
        upsert_variant(memory_db, obs)
        insert_price_check(memory_db, obs)

    assert is_price_checks_empty(memory_db) is False

    variants = get_variant_ids_for_site(memory_db, "Skin Store")
    assert variants == ["999"]
    assert get_variant_ids_for_site(memory_db, "Other Store") == []
