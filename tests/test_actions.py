"""Action tests: preconditions reject, diffs are honest, base data is never touched.

The brief requires tests proving invalid actions are rejected. Rejection is tested by asserting
the specific precondition that failed, not merely that something raised -- an action that
rejected for the wrong reason would pass the weaker test and mislead an operator.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from flightops.actions.actions import Actions, PreconditionFailed
from flightops.ingest.loader import connect, load_month, load_reference
from flightops.ingest.rotation import derive_next_leg
from flightops.model.objects import Aircraft, Flight, FlightStatus
from flightops.model.scenario import Scenario
from flightops.model.store import ObjectStore
from flightops.propagation.engine import PropagationEngine, build_turn_model

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"

CASCADE_ROOT = "2026-01-03|WN|3851|PHX|SFO|0855"


@pytest.fixture(scope="session")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ObjectStore]:
    database = tmp_path_factory.mktemp("actions") / "sample.duckdb"
    connection = connect(database)
    load_reference(connection)
    load_month(connection, SAMPLE_CSV)
    derive_next_leg(connection)
    connection.close()
    with ObjectStore(database) as opened:
        yield opened


@pytest.fixture(scope="session")
def actions(store: ObjectStore) -> Actions:
    return Actions(PropagationEngine(build_turn_model(store)))


@pytest.fixture
def root(store: ObjectStore) -> Flight:
    return store.get_flight(CASCADE_ROOT)


@pytest.fixture
def scenario(store: ObjectStore, root: Flight) -> Scenario:
    return Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))


# -- delay_flight ---------------------------------------------------------------------------------


def test_delay_projects_the_cascade_into_the_diff(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    diff = actions.delay_flight(scenario, root.flight_id, 142, "de-icing")
    assert diff.action == "delay_flight"
    assert len(diff.legs) == 6  # the root plus its five downstream legs
    assert diff.net_minutes == 565
    assert "de-icing" in diff.summary
    assert diff.legs[0].after_delay_minutes == 142


def test_delay_rejects_zero_and_negative_minutes(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    for minutes in (0, -30):
        with pytest.raises(PreconditionFailed) as caught:
            actions.delay_flight(scenario, root.flight_id, minutes, "test")
        assert caught.value.object_id == root.flight_id
        assert "greater than zero" in caught.value.precondition


def test_delay_rejects_an_empty_reason(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    with pytest.raises(PreconditionFailed) as caught:
        actions.delay_flight(scenario, root.flight_id, 30, "   ")
    assert "reason" in caught.value.precondition


def test_delay_rejects_a_flight_that_already_departed(
    actions: Actions, store: ObjectStore, root: Flight
) -> None:
    """The clock is what makes this decidable; replaying a completed day needs a 'now'."""
    late = Scenario(store=store, clock=root.sched_dep_utc + timedelta(minutes=1))
    with pytest.raises(PreconditionFailed) as caught:
        actions.delay_flight(late, root.flight_id, 30, "test")
    assert "before the scenario clock" in caught.value.precondition


def test_bigger_delay_produces_a_bigger_cascade(
    actions: Actions, store: ObjectStore, root: Flight
) -> None:
    totals = []
    for minutes in (30, 90, 180):
        fresh = Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))
        totals.append(actions.delay_flight(fresh, root.flight_id, minutes, "test").net_minutes)
    assert totals == sorted(totals)


# -- cancel_flight --------------------------------------------------------------------------------


def test_cancel_releases_the_downstream_delay(
    actions: Actions, store: ObjectStore, root: Flight
) -> None:
    """Cancelling a delayed leg frees the aircraft, so downstream minutes come back as relief."""
    scenario = Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))
    actions.delay_flight(scenario, root.flight_id, 142, "de-icing")
    diff = actions.cancel_flight(scenario, root.flight_id, "aircraft swap unavailable")
    assert diff.net_minutes < 0
    assert all(leg.after_delay_minutes == 0 for leg in diff.legs)


def test_cancel_rejects_a_flight_already_cancelled(
    actions: Actions, store: ObjectStore
) -> None:
    cancelled = store.find_flights(status=FlightStatus.CANCELLED, limit=1)
    assert cancelled
    flight = cancelled[0]
    scenario = Scenario(store=store, clock=flight.sched_dep_utc - timedelta(hours=1))
    with pytest.raises(PreconditionFailed) as caught:
        actions.cancel_flight(scenario, flight.flight_id, "test")
    assert "already cancelled" in caught.value.precondition


def test_cancel_rejects_an_empty_reason(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    with pytest.raises(PreconditionFailed) as caught:
        actions.cancel_flight(scenario, root.flight_id, "")
    assert "reason" in caught.value.precondition


def test_cancel_flags_the_stranded_rotation_rather_than_blocking(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    """A costly consequence is surfaced, not prevented: judging the cost is the operator's job."""
    diff = actions.cancel_flight(scenario, root.flight_id, "weather")
    assert any("strands the rotation" in warning for warning in diff.warnings)
    assert any("reaccommodation is not modelled" in warning for warning in diff.warnings)


# -- swap_aircraft --------------------------------------------------------------------------------


def test_swap_rejects_a_tail_that_does_not_exist(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    """Existence is a precondition of the swap, so it rejects rather than raising a lookup error."""
    with pytest.raises(PreconditionFailed) as caught:
        actions.swap_aircraft(scenario, root.flight_id, "N0000X")
    assert caught.value.action == "swap_aircraft"
    assert "no aircraft N0000X" in caught.value.precondition


def test_swap_rejects_a_tail_from_another_carrier(
    actions: Actions, scenario: Scenario, root: Flight, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed sample is one carrier by design, so the cross-carrier tail is stubbed.

    DESIGN.md section 12 scopes the sample to Southwest deliberately, which means no real
    foreign tail exists to test against. Stubbing the store's answer exercises the precondition
    itself rather than skipping the branch.
    """
    monkeypatch.setattr(
        scenario.store,
        "get_aircraft",
        lambda tail: Aircraft(tail_number=tail, carrier="DL"),
    )
    with pytest.raises(PreconditionFailed) as caught:
        actions.swap_aircraft(scenario, root.flight_id, "N123DL")
    assert "operated by DL, not WN" in caught.value.precondition


def test_swap_rejects_the_tail_already_assigned(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    assert root.tail_number is not None
    with pytest.raises(PreconditionFailed) as caught:
        actions.swap_aircraft(scenario, root.flight_id, root.tail_number)
    assert "already assigned" in caught.value.precondition


def test_swap_rejects_a_tail_that_cannot_reach_the_station(
    actions: Actions, store: ObjectStore, scenario: Scenario, root: Flight
) -> None:
    """Position is a hard precondition: an aircraft that is not there cannot fly the leg."""
    elsewhere = None
    for candidate in store.find_flights(flight_date=root.flight_date, limit=500):
        if candidate.tail_number and candidate.tail_number != root.tail_number:
            legs = store.rotation(candidate.tail_number, root.flight_date)
            if legs and all(leg.destination != root.origin for leg in legs):
                elsewhere = candidate.tail_number
                break
    assert elsewhere is not None, "sample has no tail that never visits the origin"

    with pytest.raises(PreconditionFailed) as caught:
        actions.swap_aircraft(scenario, root.flight_id, elsewhere)
    assert "not projected to be on the ground" in caught.value.precondition


def test_swap_finds_a_legal_replacement_and_clears_the_cascade(
    actions: Actions, store: ObjectStore, root: Flight
) -> None:
    """The decision the tool exists for: what a swap actually buys, before committing to it."""
    scenario = Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))
    candidates = actions.available_tails(scenario, root.flight_id)
    if not candidates:
        pytest.skip("no legally positioned replacement in the sample for this flight")

    actions.delay_flight(scenario, root.flight_id, 142, "de-icing")
    diff = actions.swap_aircraft(scenario, root.flight_id, candidates[0][0])
    assert diff.net_minutes <= 0
    assert any("fleet compatibility is not checked" in w for w in diff.warnings)


def test_available_tails_are_all_legally_positioned(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    """Every suggestion must survive the precondition it will be checked against."""
    for tail, arrival in actions.available_tails(scenario, root.flight_id):
        assert tail != root.tail_number
        assert arrival <= root.sched_dep_utc


# -- the guarantee across all three ---------------------------------------------------------------


def test_no_action_ever_writes_to_the_base_data(
    actions: Actions, store: ObjectStore, root: Flight
) -> None:
    """DESIGN.md section 6: no action writes to the base tables. Asserted for all three."""
    original = store.get_flight(root.flight_id)
    following = store.next_leg(root.flight_id)

    scenario = Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))
    actions.delay_flight(scenario, root.flight_id, 60, "test")
    actions.cancel_flight(scenario, root.flight_id, "test")

    assert store.get_flight(root.flight_id) == original
    assert store.next_leg(root.flight_id) == following


def test_rejected_actions_leave_no_trace(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    """A rejection must not half-apply. The overlay is unchanged after a failed precondition."""
    before = len(scenario.changes)
    with pytest.raises(PreconditionFailed):
        actions.delay_flight(scenario, root.flight_id, -5, "test")
    with pytest.raises(PreconditionFailed):
        actions.cancel_flight(scenario, root.flight_id, "")
    assert len(scenario.changes) == before
    assert scenario.get_flight(root.flight_id) == scenario.store.get_flight(root.flight_id)


def test_applied_actions_are_recorded_in_order(
    actions: Actions, store: ObjectStore, root: Flight
) -> None:
    scenario = Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))
    actions.delay_flight(scenario, root.flight_id, 45, "gate hold")
    actions.cancel_flight(scenario, root.flight_id, "gave up")
    assert [change.action for change in scenario.changes] == ["delay_flight", "cancel_flight"]
    assert "gate hold" in scenario.describe()


def test_diff_renders_for_an_operator(
    actions: Actions, scenario: Scenario, root: Flight
) -> None:
    rendered = actions.delay_flight(scenario, root.flight_id, 142, "de-icing").render()
    assert "WN3851 PHX-SFO" in rendered
    assert "net system minutes" in rendered


def test_recovery_clears_exactly_what_the_delay_caused(
    actions: Actions, store: ObjectStore, root: Flight
) -> None:
    """Regression: a recovery action must not double-count a delay already in the overlay.

    The first version of cancel and swap re-projected using the delay measured off the overlay,
    but the overlay already carries that shift in the leg's own times, so the cascade was
    computed against a root delayed twice. The swap then reported clearing 1,447 minutes of a
    510-minute cascade -- an error that made the tool overstate the value of its own advice,
    which is the worst direction for it to be wrong in.

    Asserted as a symmetry: what a delay creates, an equivalent recovery removes.
    """
    delayed = Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))
    caused = actions.delay_flight(delayed, root.flight_id, 142, "de-icing").net_minutes

    recovered = Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))
    actions.delay_flight(recovered, root.flight_id, 142, "de-icing")
    released = actions.cancel_flight(recovered, root.flight_id, "no aircraft").net_minutes

    assert caused > 0
    assert released == -caused


def test_recovery_after_two_delays_still_balances(
    actions: Actions, store: ObjectStore, root: Flight
) -> None:
    """The same invariant when delays stack, which is where double-counting compounds."""
    scenario = Scenario(store=store, clock=root.sched_dep_utc - timedelta(hours=1))
    first = actions.delay_flight(scenario, root.flight_id, 60, "gate hold").net_minutes
    second = actions.delay_flight(scenario, root.flight_id, 45, "crew").net_minutes
    released = actions.cancel_flight(scenario, root.flight_id, "gave up").net_minutes
    assert released == -(first + second)
