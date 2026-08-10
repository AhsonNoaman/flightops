"""The month-comparison script restates the root filter in SQL. This checks it did not drift.

`measure_cascade_shape` decides what counts as a root in Python, walking objects. The README's
root-population table needs the same decision applied to a whole month at once, which is a
`count(*)`, which means the filter exists twice in two languages. Two spellings of one definition
is exactly the kind of duplication that silently diverges and then quietly changes a number in a
README, so the two are asserted to select the same flights rather than merely to read alike.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from flightops.ingest.loader import connect, load_month, load_reference
from flightops.ingest.rotation import derive_next_leg
from flightops.model.store import ObjectStore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from compare_months import ROOT_FILTER, profile, render  # noqa: E402

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("compare") / "sample.duckdb"
    connection = connect(path)
    load_reference(connection)
    load_month(connection, SAMPLE_CSV)
    derive_next_leg(connection)
    connection.close()
    return path


@pytest.fixture(scope="module")
def store(database: Path) -> Iterator[ObjectStore]:
    with ObjectStore(database) as opened:
        yield opened


def test_sql_root_filter_selects_exactly_what_the_python_one_does(
    database: Path, store: ObjectStore
) -> None:
    """The same population, flight by flight -- not just the same count."""
    # The filter as measure_cascade_shape applies it, copied deliberately rather than imported:
    # importing the loop would test that the loop equals itself. A limit far above the sample's
    # size so this is the whole population, which is what the README table counts.
    python_side = {
        flight.flight_id
        for flight in store.find_flights(min_dep_delay=60, limit=1_000_000)
        if flight.tail_number is not None
        and flight.causes is not None
        and flight.dep_delay_minutes is not None
        and flight.causes.late_aircraft <= flight.causes.total / 2
    }

    connection = duckdb.connect(str(database), read_only=True)
    try:
        sql_side = {
            row[0]
            for row in connection.execute(
                f"SELECT flight_id FROM flights WHERE {ROOT_FILTER}"
            ).fetchall()
        }
    finally:
        connection.close()

    assert python_side, "the sample should contain at least one qualifying root"
    assert sql_side == python_side


def test_profile_reports_the_sample_it_was_given(database: Path) -> None:
    """Shares are derived from the counts they claim to describe, not computed twice."""
    result = profile(database)
    assert result.flights == result.arrived + result.cancelled + result.diverted
    assert 0 <= result.late_share <= 100
    assert 0 <= result.cancel_share <= 100
    assert result.carriers == ("WN",)
    assert result.days == 7
    assert abs(sum(result.cause_shares.values()) - 100) < 0.01
    assert result.roots > 0
    assert result.roots_per_day == pytest.approx(result.roots / result.days)


def test_render_puts_both_months_in_every_row(database: Path) -> None:
    """A comparison table missing a column is worse than no table."""
    left = profile(database)
    output = render(left, left)
    for label in ("flights", "qualifying roots", "per 1,000 flights flown", "median, minutes"):
        line = next(row for row in output.splitlines() if row.startswith(label))
        assert len(line.split()) >= 3, f"{label!r} row does not carry two values"
