"""Propagation tests, including one built from a real cascade in the data.

The pinned cascade is deliberately exact. If a change to the turn estimator or the projection
formula moves these numbers, this test fails and the change gets looked at, which is the point:
the engine's output is the product, so it should not be able to drift quietly.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from flightops.ingest.loader import connect, load_month, load_reference
from flightops.ingest.rotation import derive_next_leg
from flightops.model.objects import ChainTermination
from flightops.model.scenario import Scenario
from flightops.model.store import ObjectStore
from flightops.propagation.engine import (
    OVERNIGHT_GROUND_MINUTES,
    PropagationEngine,
    TurnTimeModel,
    build_turn_model,
)
from flightops.propagation.validate import validate_against_bts

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"

# A real Southwest cascade from the committed week. N8633A takes a 142-minute NAS delay leaving
# Phoenix and works it down the rest of its day, ending in Houston that night.
CASCADE_ROOT = "2026-01-03|WN|3851|PHX|SFO|0855"
CASCADE_ROOT_DELAY = 142
CASCADE_EXPECTED = [
    ("2026-01-03|WN|4106|SFO|PHX|1055", 127),
    ("2026-01-03|WN|172|PHX|LGB|1440", 117),
    ("2026-01-03|WN|65|LGB|LAS|1545", 112),
    ("2026-01-03|WN|65|LAS|DAL|1735", 107),
    ("2026-01-03|WN|65|DAL|HOU|2255", 102),
]


@pytest.fixture(scope="session")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ObjectStore]:
    database = tmp_path_factory.mktemp("propagation") / "sample.duckdb"
    connection = connect(database)
    load_reference(connection)
    load_month(connection, SAMPLE_CSV)
    derive_next_leg(connection)
    connection.close()
    with ObjectStore(database) as opened:
        yield opened


@pytest.fixture(scope="session")
def engine(store: ObjectStore) -> PropagationEngine:
    return PropagationEngine(build_turn_model(store))


def _scenario_before(store: ObjectStore, flight_id: str) -> Scenario:
    root = store.get_flight(flight_id)
    return Scenario(store=store, clock=root.sched_dep_utc - timedelta(minutes=1))


def test_real_cascade_projects_the_legs_it_actually_hit(
    store: ObjectStore, engine: PropagationEngine
) -> None:
    """The pinned case: a real 142-minute delay working down a real rotation."""
    event = engine.project(_scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, CASCADE_ROOT_DELAY)
    assert event.tail_number == "N8633A"
    assert event.cause == "nas"
    assert [(leg.flight_id, leg.propagated_delay_minutes) for leg in event.affected] == (
        CASCADE_EXPECTED
    )
    assert event.total_propagated_minutes == sum(minutes for _, minutes in CASCADE_EXPECTED)
    assert event.termination is ChainTermination.OVERNIGHT_BREAK


def test_real_cascade_tracks_the_carriers_own_attribution(
    store: ObjectStore, engine: PropagationEngine
) -> None:
    """Projections are checked against LateAircraftDelay, produced independently by the carrier.

    A 20-minute mean tolerance is not a loose test, it is the honest one: the engine projects a
    do-nothing world using scheduled block times, while BTS records a world where crews turned
    faster and flew faster to recover. Tightening this would only be possible by fitting to the
    answer.
    """
    event = engine.project(_scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, CASCADE_ROOT_DELAY)
    errors = []
    for leg in event.affected:
        downstream = store.get_flight(leg.flight_id)
        assert downstream.causes is not None
        errors.append(abs(leg.propagated_delay_minutes - downstream.causes.late_aircraft))
    assert sum(errors) / len(errors) < 20


def test_cascade_damps_down_the_rotation(store: ObjectStore, engine: PropagationEngine) -> None:
    """Per-leg delay decays as scheduled slack absorbs it, even while the sum exceeds the root.

    DESIGN.md section 10 flagged the brief's motivating example for presuming amplification. It
    damps: 142 minutes at the root becomes 102 by the fifth leg. The total across legs is larger
    than the root delay, which is a different claim and the one the tool actually makes.
    """
    event = engine.project(_scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, CASCADE_ROOT_DELAY)
    projected = [leg.propagated_delay_minutes for leg in event.affected]
    assert projected == sorted(projected, reverse=True)
    assert projected[0] < CASCADE_ROOT_DELAY
    assert event.total_propagated_minutes > CASCADE_ROOT_DELAY


def test_no_delay_produces_no_cascade(store: ObjectStore, engine: PropagationEngine) -> None:
    event = engine.project(_scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, 0)
    assert event.affected == ()
    assert event.total_propagated_minutes == 0
    assert event.termination in (ChainTermination.ABSORBED, ChainTermination.OVERNIGHT_BREAK)


def test_small_delay_is_absorbed_by_scheduled_slack(
    store: ObjectStore, engine: PropagationEngine
) -> None:
    """The whole reason cascades are bounded: slack in the schedule soaks up small delays."""
    event = engine.project(_scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, 5)
    assert (
        event.total_propagated_minutes
        < engine.project(
            _scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, 120
        ).total_propagated_minutes
    )


def test_bigger_root_never_produces_a_smaller_cascade(
    store: ObjectStore, engine: PropagationEngine
) -> None:
    """Monotonicity. A property, so it is checked across the whole range rather than at a point."""
    totals = [
        engine.project(
            _scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, minutes
        ).total_propagated_minutes
        for minutes in (0, 15, 30, 60, 120, 240)
    ]
    assert totals == sorted(totals)


def test_projection_never_moves_a_leg_earlier(
    store: ObjectStore, engine: PropagationEngine
) -> None:
    """A delay cannot pull a departure forward. Projected departure is bounded below by schedule."""
    event = engine.project(_scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, CASCADE_ROOT_DELAY)
    for leg in event.affected:
        scheduled = store.get_flight(leg.flight_id)
        assert leg.projected_dep_utc >= scheduled.sched_dep_utc
        assert leg.projected_arr_utc > leg.projected_dep_utc
        assert leg.propagated_delay_minutes > 0


def test_cascade_stays_on_one_aircraft(store: ObjectStore, engine: PropagationEngine) -> None:
    event = engine.project(_scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, CASCADE_ROOT_DELAY)
    for leg in event.affected:
        assert store.get_flight(leg.flight_id).tail_number == event.tail_number


def test_termination_reason_is_always_explained(
    store: ObjectStore, engine: PropagationEngine
) -> None:
    """Every projection ends for a stated reason. A cascade that just stops is a bug."""
    checked = 0
    for root in store.find_flights(min_dep_delay=45, limit=120):
        if root.tail_number is None or root.dep_delay_minutes is None:
            continue
        event = engine.project(
            _scenario_before(store, root.flight_id), root.flight_id, root.dep_delay_minutes
        )
        assert event.termination in set(ChainTermination)
        checked += 1
    assert checked > 20


def test_overnight_labelling_does_not_change_the_numbers(
    store: ObjectStore, engine: PropagationEngine
) -> None:
    """The overnight threshold labels a reason; it must not alter a projected minute.

    Guards the decision to keep the empirically chosen boundary out of the arithmetic. Absorption
    is decided by the max() in the formula, so moving this constant may relabel a termination but
    must leave every projection identical.
    """
    import flightops.propagation.engine as engine_module

    baseline = engine.project(
        _scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, CASCADE_ROOT_DELAY
    )
    original = engine_module.OVERNIGHT_GROUND_MINUTES
    try:
        engine_module.OVERNIGHT_GROUND_MINUTES = 60
        shifted = engine.project(
            _scenario_before(store, CASCADE_ROOT), CASCADE_ROOT, CASCADE_ROOT_DELAY
        )
    finally:
        engine_module.OVERNIGHT_GROUND_MINUTES = original

    assert [leg.propagated_delay_minutes for leg in shifted.affected] == [
        leg.propagated_delay_minutes for leg in baseline.affected
    ]
    assert original == OVERNIGHT_GROUND_MINUTES


def test_turn_model_falls_back_when_a_station_is_thin(store: ObjectStore) -> None:
    model = build_turn_model(store)
    assert model.minimum_turn("WN", "LAS") > 0
    assert "WN at LAS" in model.basis("WN", "LAS")
    assert model.minimum_turn("WN", "ZZZ") == model.per_carrier["WN"]
    assert "network-wide" in model.basis("WN", "ZZZ")


def test_turn_model_falls_back_to_the_network_for_unknown_carriers() -> None:
    model = TurnTimeModel(per_station={}, per_carrier={}, network=33)
    assert model.minimum_turn("XX", "YYY") == 33
    assert model.basis("XX", "YYY") == "all carriers"


def test_turn_estimates_are_operationally_plausible(store: ObjectStore) -> None:
    """A turn estimate outside 15-120 minutes means the estimator is measuring the wrong thing."""
    model = build_turn_model(store)
    assert 15 <= model.network <= 120
    for minutes in model.per_station.values():
        assert 15 <= minutes <= 120


def test_validation_never_misses_a_cascade_bts_attributed(store: ObjectStore) -> None:
    """The asymmetry that matters operationally: over-warn, never under-warn.

    A triage tool that misses a real cascade is worse than one that flags a cascade a controller
    already prevented, because the second is visible and the first is not.
    """
    result = validate_against_bts(store, min_root_delay=60, max_roots=60)
    assert result.legs_compared > 0
    assert result.bts_nonzero_engine_zero == 0


def test_validation_error_is_small_and_centred_for_this_carrier(store: ObjectStore) -> None:
    """Calibration on the sample carrier, which is where the offline tests can measure it.

    An earlier version of this test asserted the error must be biased high, reasoning that
    scheduled block times are padded and crews compress turns, so a do-nothing projection must
    over-predict. The data refused: on Southwest's week the mean error is roughly zero.

    Measured across the full month, the bias turns out to be strongly carrier-dependent --
    SkyWest +74 minutes, United +28, Southwest +6, Frontier -7, because the error is really a
    measure of how hard a carrier works to recover, and the engine projects a world where nobody
    does. Southwest's dense point-to-point rotations leave little room to swap, so its recorded
    outcomes sit close to the do-nothing projection. The assertion here is therefore about
    calibration for this carrier, not about a universal direction of error.
    """
    result = validate_against_bts(store, min_root_delay=60, max_roots=60)
    assert result.legs_compared > 50
    assert abs(result.median_error) <= 15
    assert abs(result.mean_error) <= 15
