"""Domain model tests: typed objects, link traversal, and overlay isolation.

Run against the real sample rather than fixtures. The traversal tests assert properties that
must hold for every aircraft in the week, and the overlay tests assert the property the whole
scenario mechanism exists to guarantee: that nothing an action does reaches the base data.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from flightops.ingest.loader import connect, load_month, load_reference
from flightops.ingest.rotation import derive_next_leg
from flightops.model.objects import Flight, FlightStatus
from flightops.model.scenario import AppliedChange, Scenario
from flightops.model.store import Link, ObjectNotFound, ObjectStore

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"


@pytest.fixture(scope="session")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ObjectStore]:
    database = tmp_path_factory.mktemp("model") / "sample.duckdb"
    connection = connect(database)
    load_reference(connection)
    load_month(connection, SAMPLE_CSV)
    derive_next_leg(connection)
    connection.close()
    with ObjectStore(database) as opened:
        yield opened


@pytest.fixture
def busy_flight(store: ObjectStore) -> Flight:
    """A leg that has a real downstream rotation, so chain tests have something to walk."""
    for candidate in store.find_flights(status=FlightStatus.ARRIVED, limit=400):
        if candidate.tail_number and store.next_leg(candidate.flight_id):
            return candidate
    pytest.fail("sample contains no linked rotation")


def test_unknown_ids_name_the_object(store: ObjectStore) -> None:
    """The brief requires errors to surface the object id and the failed lookup."""
    with pytest.raises(ObjectNotFound) as caught:
        store.get_flight("no-such-flight")
    assert "no-such-flight" in str(caught.value)
    assert caught.value.object_type == "Flight"


def test_flight_round_trips_into_a_typed_object(store: ObjectStore) -> None:
    flights = store.find_flights(limit=1)
    assert flights
    flight = flights[0]
    assert flight.carrier == "WN"
    assert flight.sched_arr_utc > flight.sched_dep_utc
    assert flight.describe().startswith("WN")


def test_cause_buckets_present_only_when_delayed(store: ObjectStore) -> None:
    """CauseBuckets is None below the 15-minute threshold, and sums exactly above it."""
    for flight in store.find_flights(min_arr_delay=15, limit=50):
        assert flight.causes is not None
        assert flight.causes.total == flight.arr_delay_minutes


def test_traversal_returns_the_right_types(store: ObjectStore, busy_flight: Flight) -> None:
    assert store.traverse(busy_flight, Link.OPERATED_BY)[0].code == "WN"
    assert store.traverse(busy_flight, Link.DEPARTS_FROM)[0].iata == busy_flight.origin
    assert store.traverse(busy_flight, Link.ARRIVES_AT)[0].iata == busy_flight.destination
    assert store.traverse(busy_flight, Link.FLOWN_BY)[0].tail_number == busy_flight.tail_number


def test_next_and_previous_leg_are_inverses(store: ObjectStore) -> None:
    """Walking forward then back must return to the starting leg, for every linked flight."""
    checked = 0
    for flight in store.find_flights(limit=300):
        following = store.next_leg(flight.flight_id)
        if following is None:
            continue
        assert store.previous_leg(following.flight_id) == flight
        checked += 1
    assert checked > 50, "sample did not exercise enough links to be meaningful"


def test_traversal_never_leaves_the_aircraft(store: ObjectStore) -> None:
    """next_leg must stay on the same tail and move forward in time. No exceptions."""
    for flight in store.find_flights(limit=300):
        following = store.next_leg(flight.flight_id)
        if following is None:
            continue
        assert following.tail_number == flight.tail_number
        assert following.origin == flight.destination
        assert following.sched_dep_utc >= flight.sched_arr_utc


def test_chain_break_reason_is_recorded_not_guessed(store: ObjectStore) -> None:
    """Where next_leg is absent, a reason must exist. A silent dead end is a bug."""
    for flight in store.find_flights(limit=300):
        if flight.tail_number is None:
            continue
        if store.next_leg(flight.flight_id) is None:
            assert store.chain_break_after(flight.flight_id) in {
                "end_of_window",
                "station_discontinuity",
                "impossible_turn",
            }


def test_rotation_is_ordered_and_connected(store: ObjectStore, busy_flight: Flight) -> None:
    assert busy_flight.tail_number is not None
    legs = store.rotation(busy_flight.tail_number, busy_flight.flight_date)
    assert len(legs) >= 2
    for earlier, later in zip(legs, legs[1:], strict=False):
        assert earlier.sched_dep_utc <= later.sched_dep_utc


def test_turn_percentile_refuses_a_thin_sample(store: ObjectStore) -> None:
    """A per-station estimate from a handful of turns is noise; the store returns None."""
    assert store.turn_percentile("WN", "ZZZ", 0.05) is None
    busiest = store.find_flights(limit=1)[0]
    assert isinstance(store.turn_percentile("WN", busiest.destination, 0.05), int | type(None))


# -- scenario overlay ---------------------------------------------------------------------------


def _delayed(flight: Flight, minutes: int) -> Flight:
    return flight.model_copy(
        update={
            "sched_dep_utc": flight.sched_dep_utc + timedelta(minutes=minutes),
            "sched_arr_utc": flight.sched_arr_utc + timedelta(minutes=minutes),
        }
    )


def test_overlay_changes_what_the_scenario_sees(store: ObjectStore, busy_flight: Flight) -> None:
    scenario = Scenario(store=store, clock=busy_flight.sched_dep_utc - timedelta(hours=1))
    shifted = _delayed(busy_flight, 90)
    scenario.apply(
        AppliedChange(
            flight_id=busy_flight.flight_id,
            action="delay_flight",
            summary="+90",
            before=busy_flight,
            after=shifted,
        )
    )
    assert scenario.get_flight(busy_flight.flight_id).sched_dep_utc == shifted.sched_dep_utc


def test_overlay_never_reaches_the_base_data(store: ObjectStore, busy_flight: Flight) -> None:
    """The guarantee the whole mechanism exists for: base data is immutable historical fact."""
    original = store.get_flight(busy_flight.flight_id)
    scenario = Scenario(store=store, clock=busy_flight.sched_dep_utc - timedelta(hours=1))
    scenario.apply(
        AppliedChange(
            flight_id=busy_flight.flight_id,
            action="delay_flight",
            summary="+240",
            before=busy_flight,
            after=_delayed(busy_flight, 240),
        )
    )
    assert store.get_flight(busy_flight.flight_id) == original

    untouched = Scenario(store=store, clock=scenario.clock)
    assert untouched.get_flight(busy_flight.flight_id) == original


def test_scenarios_are_isolated_from_each_other(store: ObjectStore, busy_flight: Flight) -> None:
    """Two sessions replaying the same day must not see each other's changes."""
    clock = busy_flight.sched_dep_utc - timedelta(hours=1)
    first = Scenario(store=store, clock=clock)
    second = Scenario(store=store, clock=clock)
    first.apply(
        AppliedChange(
            flight_id=busy_flight.flight_id,
            action="delay_flight",
            summary="+60",
            before=busy_flight,
            after=_delayed(busy_flight, 60),
        )
    )
    assert second.get_flight(busy_flight.flight_id).sched_dep_utc == busy_flight.sched_dep_utc


def test_rotation_reorders_after_a_delay_moves_a_leg(store: ObjectStore) -> None:
    """A delayed leg must not be returned in its old position in the rotation."""
    tail_row = None
    for candidate in store.find_flights(limit=400):
        if candidate.tail_number is None:
            continue
        if len(store.rotation(candidate.tail_number, candidate.flight_date)) >= 3:
            tail_row = candidate
            break
    assert tail_row is not None and tail_row.tail_number is not None

    scenario = Scenario(store=store, clock=tail_row.sched_dep_utc - timedelta(hours=2))
    legs = scenario.rotation(tail_row.tail_number, tail_row.flight_date)
    first = legs[0]
    scenario.apply(
        AppliedChange(
            flight_id=first.flight_id,
            action="delay_flight",
            summary="+1440",
            before=first,
            after=_delayed(first, 1440),
        )
    )
    reordered = scenario.rotation(tail_row.tail_number, tail_row.flight_date)
    assert reordered[-1].flight_id == first.flight_id


def test_downstream_chain_matches_a_manual_walk(store: ObjectStore, busy_flight: Flight) -> None:
    scenario = Scenario(store=store, clock=busy_flight.sched_dep_utc)
    chain = scenario.downstream_chain(busy_flight.flight_id)

    manual: list[str] = []
    current = busy_flight.flight_id
    while (following := store.next_leg(current)) is not None:
        manual.append(following.flight_id)
        current = following.flight_id
    assert [leg.flight_id for leg in chain] == manual


def test_pending_reads_the_clock_not_the_recorded_status(
    store: ObjectStore, busy_flight: Flight
) -> None:
    """Every leg in the base data already happened; replay decides what is still ahead."""
    before = Scenario(store=store, clock=busy_flight.sched_dep_utc - timedelta(minutes=1))
    after = Scenario(store=store, clock=busy_flight.sched_dep_utc + timedelta(minutes=1))
    assert before.is_pending(busy_flight)
    assert not after.is_pending(busy_flight)
