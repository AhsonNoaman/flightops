"""The three actions: delay, swap, cancel.

DESIGN.md section 6. Every action validates preconditions against the scenario and either
rejects with the object id and the specific failed precondition, or returns a structured diff.
No action ever writes to the base tables; changes land in the scenario overlay.

The distinction that shapes this module is hard preconditions versus flagged consequences. A
hard precondition is an impossibility -- you cannot cancel a flight that has already pushed
back. A consequence is expensive but real: swapping a tail that leaves the replacement out of
position is something carriers do, badly, on bad days. Blocking the second would be the tool
substituting its judgement for the controller's. Surfacing it in the diff is the tool doing its
job. So impossibilities reject, and costs get flagged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from flightops.model.objects import Flight, FlightStatus
from flightops.model.scenario import AppliedChange, Scenario
from flightops.model.store import ObjectNotFound
from flightops.propagation.engine import PropagationEngine


class PreconditionFailed(ValueError):
    """Rejection carrying the object id and the precondition that failed, never a bare message."""

    def __init__(self, action: str, object_id: str, precondition: str) -> None:
        super().__init__(f"{action} rejected for {object_id}: {precondition}")
        self.action = action
        self.object_id = object_id
        self.precondition = precondition


@dataclass(frozen=True)
class LegDelta:
    """One leg's before and after, in the minutes an operator reasons in."""

    flight_id: str
    description: str
    before_dep_utc: datetime
    after_dep_utc: datetime | None
    before_delay_minutes: int
    after_delay_minutes: int

    @property
    def change_minutes(self) -> int:
        return self.after_delay_minutes - self.before_delay_minutes


@dataclass(frozen=True)
class ActionDiff:
    """What an action would do. Returned instead of performing a silent mutation."""

    action: str
    target_flight_id: str
    summary: str
    legs: tuple[LegDelta, ...]
    net_minutes: int
    warnings: tuple[str, ...] = field(default=())

    def render(self) -> str:
        lines = [self.summary, ""]
        for leg in self.legs:
            arrow = f"{leg.before_delay_minutes:+d} -> {leg.after_delay_minutes:+d}"
            lines.append(f"  {leg.description:<38} {arrow:>16}  ({leg.change_minutes:+d})")
        lines.append("")
        lines.append(f"  net system minutes: {self.net_minutes:+d}")
        for warning in self.warnings:
            lines.append(f"  warning: {warning}")
        return "\n".join(lines)


def _delay_of(flight: Flight, scenario: Scenario) -> int:
    """Minutes this leg has already been pushed back by earlier actions in this scenario.

    Reported in diffs, never fed back into a projection. The overlay already carries the shift
    in the leg's own times, so projecting it again with this value would count it twice.
    """
    base = scenario.store.get_flight(flight.flight_id)
    return round((flight.sched_dep_utc - base.sched_dep_utc).total_seconds() / 60)


def _shift(flight: Flight, minutes: int) -> Flight:
    return flight.model_copy(
        update={
            "sched_dep_utc": flight.sched_dep_utc + timedelta(minutes=minutes),
            "sched_arr_utc": flight.sched_arr_utc + timedelta(minutes=minutes),
        }
    )


class Actions:
    """The three state changes an operations controller can make in a scenario."""

    def __init__(self, engine: PropagationEngine) -> None:
        self.engine = engine

    # -- delay ---------------------------------------------------------------------------------

    def delay_flight(
        self, scenario: Scenario, flight_id: str, additional_minutes: int, reason: str
    ) -> ActionDiff:
        """Push a leg back and recompute the projection for every downstream leg on its tail."""
        flight = scenario.get_flight(flight_id)
        if additional_minutes <= 0:
            raise PreconditionFailed(
                "delay_flight", flight_id, "additional_minutes must be greater than zero"
            )
        if not reason.strip():
            raise PreconditionFailed("delay_flight", flight_id, "reason must not be empty")
        if flight.status is FlightStatus.CANCELLED:
            raise PreconditionFailed("delay_flight", flight_id, "flight is cancelled")
        if not scenario.is_pending(flight):
            raise PreconditionFailed(
                "delay_flight",
                flight_id,
                f"flight departed at {flight.sched_dep_utc:%H:%M} UTC, before the scenario "
                f"clock of {scenario.clock:%H:%M} UTC",
            )

        before = self.engine.project(scenario, flight_id, 0)
        after = self.engine.project(scenario, flight_id, additional_minutes)
        before_by_leg = {leg.flight_id: leg.propagated_delay_minutes for leg in before.affected}

        legs = [
            LegDelta(
                flight_id=flight_id,
                description=flight.describe(),
                before_dep_utc=flight.sched_dep_utc,
                after_dep_utc=flight.sched_dep_utc + timedelta(minutes=additional_minutes),
                before_delay_minutes=0,
                after_delay_minutes=additional_minutes,
            )
        ]
        for leg in after.affected:
            downstream = scenario.get_flight(leg.flight_id)
            legs.append(
                LegDelta(
                    flight_id=leg.flight_id,
                    description=downstream.describe(),
                    before_dep_utc=downstream.sched_dep_utc,
                    after_dep_utc=leg.projected_dep_utc,
                    before_delay_minutes=before_by_leg.get(leg.flight_id, 0),
                    after_delay_minutes=leg.propagated_delay_minutes,
                )
            )

        warnings: list[str] = []
        if after.termination.value == "guard_limit":
            warnings.append("cascade exceeded the projection bound; downstream list is truncated")

        scenario.apply(
            AppliedChange(
                flight_id=flight_id,
                action="delay_flight",
                summary=f"{flight.describe()} delayed {additional_minutes} min ({reason})",
                before=flight,
                after=_shift(flight, additional_minutes),
            )
        )
        return ActionDiff(
            action="delay_flight",
            target_flight_id=flight_id,
            summary=(
                f"Delay {flight.describe()} by {additional_minutes} min ({reason}): "
                f"{len(after.affected)} downstream legs affected, "
                f"{after.total_propagated_minutes - before.total_propagated_minutes:+d} "
                "downstream minutes"
            ),
            legs=tuple(legs),
            net_minutes=after.total_propagated_minutes - before.total_propagated_minutes,
            warnings=tuple(warnings),
        )

    # -- cancel --------------------------------------------------------------------------------

    def cancel_flight(self, scenario: Scenario, flight_id: str, reason: str) -> ActionDiff:
        """Cancel a leg and show the downstream relief, plus any rotation it strands."""
        flight = scenario.get_flight(flight_id)
        if not reason.strip():
            raise PreconditionFailed("cancel_flight", flight_id, "reason must not be empty")
        if flight.status is FlightStatus.CANCELLED:
            raise PreconditionFailed("cancel_flight", flight_id, "flight is already cancelled")
        if not scenario.is_pending(flight):
            raise PreconditionFailed(
                "cancel_flight",
                flight_id,
                f"flight departed at {flight.sched_dep_utc:%H:%M} UTC, before the scenario "
                f"clock of {scenario.clock:%H:%M} UTC",
            )

        current_delay = _delay_of(flight, scenario)
        # Zero additional delay: the overlay already carries any earlier shift in this leg's own
        # times, so passing current_delay here would apply it a second time.
        before = self.engine.project(scenario, flight_id, 0)

        legs = [
            LegDelta(
                flight_id=flight_id,
                description=f"{flight.describe()} CANCELLED",
                before_dep_utc=flight.sched_dep_utc,
                after_dep_utc=None,
                before_delay_minutes=current_delay,
                after_delay_minutes=0,
            )
        ]
        for leg in before.affected:
            downstream = scenario.get_flight(leg.flight_id)
            legs.append(
                LegDelta(
                    flight_id=leg.flight_id,
                    description=downstream.describe(),
                    before_dep_utc=leg.projected_dep_utc,
                    after_dep_utc=downstream.sched_dep_utc,
                    before_delay_minutes=leg.propagated_delay_minutes,
                    after_delay_minutes=0,
                )
            )

        warnings: list[str] = []
        following = scenario.next_leg(flight_id)
        if following is not None and following.origin == flight.destination:
            warnings.append(
                f"strands the rotation: {following.describe()} departs {following.origin}, "
                f"which this aircraft now never reaches. In reality that forces another "
                f"cancellation or a ferry, neither of which is modelled."
            )
        warnings.append("passenger reaccommodation is not modelled")

        scenario.apply(
            AppliedChange(
                flight_id=flight_id,
                action="cancel_flight",
                summary=f"{flight.describe()} cancelled ({reason})",
                before=flight,
                after=flight.model_copy(update={"status": FlightStatus.CANCELLED}),
            )
        )
        return ActionDiff(
            action="cancel_flight",
            target_flight_id=flight_id,
            summary=(
                f"Cancel {flight.describe()} ({reason}): releases "
                f"{before.total_propagated_minutes} downstream minutes across "
                f"{len(before.affected)} legs"
            ),
            legs=tuple(legs),
            net_minutes=-before.total_propagated_minutes,
            warnings=tuple(warnings),
        )

    # -- swap ----------------------------------------------------------------------------------

    def swap_aircraft(
        self, scenario: Scenario, flight_id: str, replacement_tail: str
    ) -> ActionDiff:
        """Exchange two tails' remaining lines of flying from this flight onward.

        A line swap, which is what carriers actually do, rather than a single-leg borrow, which
        creates repositioning problems the model would then have to invent its way out of.
        """
        flight = scenario.get_flight(flight_id)
        if flight.tail_number is None:
            raise PreconditionFailed(
                "swap_aircraft", flight_id, "flight has no tail assigned to swap out"
            )
        if flight.tail_number == replacement_tail:
            raise PreconditionFailed(
                "swap_aircraft", flight_id, f"{replacement_tail} is already assigned"
            )
        if flight.status is FlightStatus.CANCELLED:
            raise PreconditionFailed("swap_aircraft", flight_id, "flight is cancelled")
        if not scenario.is_pending(flight):
            raise PreconditionFailed(
                "swap_aircraft",
                flight_id,
                f"flight departed at {flight.sched_dep_utc:%H:%M} UTC, before the scenario "
                f"clock of {scenario.clock:%H:%M} UTC",
            )

        # DESIGN.md section 6 lists existence as a precondition of the swap, so an unknown tail
        # is a rejection an operator can act on, not a lookup error escaping from the store.
        try:
            replacement = scenario.store.get_aircraft(replacement_tail)
        except ObjectNotFound as missing:
            raise PreconditionFailed(
                "swap_aircraft",
                flight_id,
                f"no aircraft {replacement_tail} operates in this data",
            ) from missing
        if replacement.carrier != flight.carrier:
            raise PreconditionFailed(
                "swap_aircraft",
                flight_id,
                f"{replacement_tail} is operated by {replacement.carrier}, not {flight.carrier}",
            )

        position = self._position_of(scenario, replacement_tail, flight)
        if position is None:
            raise PreconditionFailed(
                "swap_aircraft",
                flight_id,
                f"{replacement_tail} is not projected to be on the ground at {flight.origin} "
                f"before {flight.sched_dep_utc:%H:%M} UTC",
            )
        inbound, ready_at = position

        turn = self.engine.turn_model.minimum_turn(flight.carrier, flight.origin)
        earliest = ready_at + timedelta(minutes=turn)
        if earliest > flight.sched_dep_utc:
            short_by = round((earliest - flight.sched_dep_utc).total_seconds() / 60)
            raise PreconditionFailed(
                "swap_aircraft",
                flight_id,
                f"{replacement_tail} lands at {flight.origin} at {ready_at:%H:%M} UTC and needs "
                f"{turn} min to turn, which is {short_by} min short of the "
                f"{flight.sched_dep_utc:%H:%M} departure",
            )

        current_delay = _delay_of(flight, scenario)
        # Zero additional delay: the overlay already carries any earlier shift in this leg's own
        # times, so passing current_delay here would apply it a second time.
        before = self.engine.project(scenario, flight_id, 0)

        legs = [
            LegDelta(
                flight_id=flight_id,
                description=f"{flight.describe()} now flown by {replacement_tail}",
                before_dep_utc=flight.sched_dep_utc,
                after_dep_utc=flight.sched_dep_utc,
                before_delay_minutes=current_delay,
                after_delay_minutes=0,
            )
        ]
        for leg in before.affected:
            downstream = scenario.get_flight(leg.flight_id)
            legs.append(
                LegDelta(
                    flight_id=leg.flight_id,
                    description=downstream.describe(),
                    before_dep_utc=leg.projected_dep_utc,
                    after_dep_utc=downstream.sched_dep_utc,
                    before_delay_minutes=leg.propagated_delay_minutes,
                    after_delay_minutes=0,
                )
            )

        warnings = [
            "fleet compatibility is not checked: BTS carries no aircraft type, so this swap "
            "validates carrier, position and timing only",
            f"the displaced aircraft {flight.tail_number} takes over {replacement_tail}'s "
            f"remaining line of flying, which this diff does not re-project",
        ]
        if inbound is not None:
            warnings.append(
                f"{replacement_tail} arrives on {inbound.describe()}; if that leg slips, "
                f"the swap slips with it"
            )

        scenario.apply(
            AppliedChange(
                flight_id=flight_id,
                action="swap_aircraft",
                summary=f"{flight.describe()} swapped to {replacement_tail}",
                before=flight,
                after=flight.model_copy(update={"tail_number": replacement_tail}),
            )
        )
        return ActionDiff(
            action="swap_aircraft",
            target_flight_id=flight_id,
            summary=(
                f"Swap {flight.describe()} from {flight.tail_number} to {replacement_tail}: "
                f"clears {before.total_propagated_minutes} downstream minutes across "
                f"{len(before.affected)} legs"
            ),
            legs=tuple(legs),
            net_minutes=-before.total_propagated_minutes,
            warnings=tuple(warnings),
        )

    def _position_of(
        self, scenario: Scenario, tail: str, flight: Flight
    ) -> tuple[Flight | None, datetime] | None:
        """Where a candidate tail is, and when it is free, relative to the flight's departure.

        Returns the inbound leg that puts it at the station and the time it is available, or
        None where it cannot be there at all.
        """
        legs = scenario.rotation(tail, flight.flight_date)
        if not legs:
            return None

        inbound: Flight | None = None
        for leg in legs:
            if leg.sched_arr_utc <= flight.sched_dep_utc and leg.destination == flight.origin:
                inbound = leg
        if inbound is not None:
            return inbound, inbound.sched_arr_utc

        first = legs[0]
        if first.origin == flight.origin and first.sched_dep_utc >= flight.sched_dep_utc:
            # Starts its day at this station and has not left yet: available now.
            return None, flight.sched_dep_utc - timedelta(
                minutes=self.engine.turn_model.minimum_turn(flight.carrier, flight.origin)
            )
        return None

    def available_tails(
        self, scenario: Scenario, flight_id: str, limit: int = 10
    ) -> list[tuple[str, datetime]]:
        """Tails that could legally take this flight, for the operator to choose between."""
        flight = scenario.get_flight(flight_id)
        candidates: list[tuple[str, datetime]] = []
        turn = self.engine.turn_model.minimum_turn(flight.carrier, flight.origin)
        for other in scenario.store.find_flights(
            carrier=flight.carrier,
            destination=flight.origin,
            flight_date=flight.flight_date,
            limit=400,
        ):
            if other.tail_number in (None, flight.tail_number):
                continue
            if other.sched_arr_utc + timedelta(minutes=turn) > flight.sched_dep_utc:
                continue
            assert other.tail_number is not None
            candidates.append((other.tail_number, other.sched_arr_utc))
            if len(candidates) >= limit:
                break
        return candidates
