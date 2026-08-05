"""Ingest tests, run against the committed sample.

These assert invariants and real values from the data, not the shape of the code. Every one of
them fails if the ingest logic is wrong: the timezone test reproduces BTS's own arithmetic, the
continuity tests assert properties that must hold for every link in the table, and the rotation
test walks an actual aircraft through an actual day.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from flightops.ingest.loader import connect, load_month, load_reference
from flightops.ingest.rotation import derive_next_leg

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"


@pytest.fixture(scope="session")
def db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[duckdb.DuckDBPyConnection]:
    """Build the sample database once per session, by the production code path."""
    database = tmp_path_factory.mktemp("flightops") / "sample.duckdb"
    connection = connect(database)
    load_reference(connection)
    load_month(connection, SAMPLE_CSV)
    derive_next_leg(connection)
    yield connection
    connection.close()


def test_sample_loads_every_row(db: duckdb.DuckDBPyConnection) -> None:
    """Nothing is silently dropped: the sample is one carrier's full week."""
    assert db.execute("SELECT count(*) FROM flights").fetchone()[0] == 26161
    assert db.execute("SELECT count(DISTINCT carrier) FROM flights").fetchone()[0] == 1


def test_every_leg_has_a_timezone(db: duckdb.DuckDBPyConnection) -> None:
    """A leg without both zones cannot be ordered in UTC, so it must not survive the load."""
    assert (
        db.execute(
            "SELECT count(*) FROM flights WHERE origin_tz IS NULL OR dest_tz IS NULL"
        ).fetchone()[0]
        == 0
    )


def test_utc_conversion_matches_bts_own_arithmetic(db: duckdb.DuckDBPyConnection) -> None:
    """The computed local arrival must reproduce BTS's reported CRSArrTime.

    This is the timezone table's independent check. A wrong zone shifts every leg touching that
    airport by a whole hour, so the tolerance is tight: a handful of rows at most, and no
    airport allowed to disagree systematically.
    """
    total, disagreements = db.execute(
        "SELECT count(*), sum(CASE WHEN strftime(sched_arr_local,'%H%M') <> crs_arr_hhmm "
        "THEN 1 ELSE 0 END) FROM flights"
    ).fetchone()
    assert disagreements / total < 0.001

    systematic = db.execute(
        "SELECT count(*) FROM (SELECT destination FROM flights GROUP BY 1 HAVING "
        "sum(CASE WHEN strftime(sched_arr_local,'%H%M') <> crs_arr_hhmm THEN 1 ELSE 0 END) "
        "> 0.01 * count(*))"
    ).fetchone()[0]
    assert systematic == 0


def test_actual_times_reconstructed_from_delays(db: duckdb.DuckDBPyConnection) -> None:
    """actual = scheduled + delay, exactly, on every leg that reports both."""
    wrong = db.execute(
        "SELECT count(*) FROM flights WHERE actual_dep_utc IS NOT NULL AND "
        "date_diff('minute', sched_dep_utc, actual_dep_utc) <> dep_delay_minutes"
    ).fetchone()[0]
    assert wrong == 0


def test_diverted_flights_are_not_arrivals(db: duckdb.DuckDBPyConnection) -> None:
    """BTS gives diverted rows their own field semantics; treating them as arrivals is wrong."""
    assert db.execute("SELECT count(*) FROM flights WHERE status='diverted'").fetchone()[0] > 0
    assert (
        db.execute(
            "SELECT count(*) FROM flights WHERE status='diverted' AND actual_arr_utc IS NOT NULL"
        ).fetchone()[0]
        == 0
    )


def test_every_link_preserves_station_continuity(db: duckdb.DuckDBPyConnection) -> None:
    """The load-bearing invariant: an aircraft departs from where it last landed."""
    violations = db.execute(
        "SELECT count(*) FROM next_leg n "
        "JOIN flights a ON a.flight_id = n.from_flight_id "
        "JOIN flights b ON b.flight_id = n.to_flight_id "
        "WHERE a.destination <> b.origin"
    ).fetchone()[0]
    assert violations == 0


def test_no_link_turns_in_negative_time(db: duckdb.DuckDBPyConnection) -> None:
    """A negative ground time is not a turn; those pairs belong in chain_breaks, not next_leg."""
    assert db.execute("SELECT count(*) FROM next_leg WHERE ground_minutes < 0").fetchone()[0] == 0
    assert (
        db.execute("SELECT count(*) FROM chain_breaks WHERE reason='impossible_turn'").fetchone()[
            0
        ]
        > 0
    )


def test_links_and_breaks_account_for_every_leg(db: duckdb.DuckDBPyConnection) -> None:
    """Each leg with a tail either links forward or is recorded as a break. Nothing vanishes."""
    legs = db.execute("SELECT count(*) FROM flights WHERE tail_number IS NOT NULL").fetchone()[0]
    links = db.execute("SELECT count(*) FROM next_leg").fetchone()[0]
    breaks = db.execute("SELECT count(*) FROM chain_breaks").fetchone()[0]
    assert links + breaks == legs


def test_every_tail_ends_its_window_exactly_once(db: duckdb.DuckDBPyConnection) -> None:
    """One end_of_window break per tail: the derivation covers each rotation to its last leg."""
    tails = db.execute(
        "SELECT count(DISTINCT tail_number) FROM flights WHERE tail_number IS NOT NULL"
    ).fetchone()[0]
    ends = db.execute("SELECT count(*) FROM chain_breaks WHERE reason='end_of_window'").fetchone()[
        0
    ]
    assert ends == tails


def test_a_real_rotation_walks_in_order(db: duckdb.DuckDBPyConnection) -> None:
    """Walk one real aircraft's real day and assert the chain the data actually contains.

    Derived from the sample rather than hand-written: the test picks the longest single-day
    chain in the week, follows next_leg from its first leg, and requires the walk to be
    connected and strictly ordered in time.
    """
    start_id, tail = db.execute(
        """
        WITH day_chain AS (
            SELECT tail_number, flight_date, count(*) legs, min(sched_dep_utc) first_dep
            FROM flights WHERE tail_number IS NOT NULL
            GROUP BY 1, 2 ORDER BY legs DESC, first_dep LIMIT 1
        )
        SELECT f.flight_id, f.tail_number FROM flights f
        JOIN day_chain d ON d.tail_number = f.tail_number AND d.flight_date = f.flight_date
        WHERE f.sched_dep_utc = d.first_dep
        """
    ).fetchone()

    walk = []
    current: str | None = start_id
    while current is not None:
        walk.append(
            db.execute(
                "SELECT flight_id, origin, destination, sched_dep_utc FROM flights "
                "WHERE flight_id = ?",
                [current],
            ).fetchone()
        )
        following = db.execute(
            "SELECT to_flight_id FROM next_leg WHERE from_flight_id = ?", [current]
        ).fetchone()
        current = following[0] if following else None
        if len(walk) > 60:
            pytest.fail("rotation walk did not terminate; next_leg contains a cycle")

    assert len(walk) >= 5, f"expected a multi-leg rotation for {tail}, walked {len(walk)}"
    for earlier, later in zip(walk, walk[1:], strict=False):
        assert earlier[2] == later[1], (
            f"{tail}: {earlier[0]} lands at {earlier[2]}, next departs {later[1]}"
        )
        assert earlier[3] < later[3], f"{tail}: {later[0]} departs before {earlier[0]}"


def test_cause_buckets_partition_the_arrival_delay(db: duckdb.DuckDBPyConnection) -> None:
    """M4 validates propagation against LateAircraftDelay, which requires the buckets be exact.

    DESIGN.md section 9 expected the buckets not to sum to the total. In this data they always
    do, and M4's validation depends on it, so the corrected assumption is pinned here.
    """
    rows, mismatched = db.execute(
        "SELECT count(*), sum(CASE WHEN arr_delay_minutes <> (delay_carrier + delay_weather + "
        "delay_nas + delay_security + delay_late_aircraft) THEN 1 ELSE 0 END) "
        "FROM flights WHERE delay_carrier IS NOT NULL"
    ).fetchone()
    assert rows > 0
    assert mismatched == 0


def test_buckets_appear_only_at_fifteen_minutes(db: duckdb.DuckDBPyConnection) -> None:
    """BTS populates the cause buckets only when arrival delay reaches 15 minutes."""
    leaked = db.execute(
        "SELECT count(*) FROM flights WHERE delay_carrier IS NOT NULL "
        "AND (arr_delay_minutes < 15 OR arr_delay_minutes IS NULL)"
    ).fetchone()[0]
    assert leaked == 0
