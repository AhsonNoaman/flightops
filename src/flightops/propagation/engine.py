"""Propagation through the rotation: the hard logic.

DESIGN.md section 10. For consecutive legs n and n+1 on one tail's chain:

    projected_dep(n+1) = max(sched_dep(n+1), projected_arr(n) + min_turn(carrier, station))
    projected_arr(n+1) = projected_dep(n+1) + sched_block(n+1)

Everything interesting is in the `max`. A delay only propagates when the aircraft cannot make its
next scheduled departure; where the schedule has slack, the delay is absorbed and the cascade
stops. That is why cascades damp rather than amplify down most rotations, and why the question
"what does this drag down tonight" has a bounded answer instead of an alarming one.

Both thresholds are measured, not assumed, as section 10 requires. See TURN_QUANTILE and
OVERNIGHT_GROUND_MINUTES.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from flightops.model.objects import (
    AffectedLeg,
    ChainTermination,
    DisruptionEvent,
    Flight,
    FlightStatus,
)
from flightops.model.scenario import Scenario
from flightops.model.store import MIN_TURN_SAMPLE, ObjectStore

TURN_QUANTILE = 0.05
"""Fifth percentile of observed ground time, per DESIGN.md section 10.

The intent is the fastest turn a carrier actually achieves at a station, which is the binding
constraint when an aircraft is running late. Measured for Southwest this lands at 35-40 minutes
per station, consistent with published 737 minimum turn times -- a useful sign the estimator is
measuring what it claims to.
"""

IMPLAUSIBLE_TURN_MINUTES = 15
"""Ground times below this are excluded from the estimate.

1,943 links in January 2026 show a scheduled turn under 15 minutes, including some at zero. No
narrowbody turns in that time; these are schedule artefacts. Including them pulls the fifth
percentile from 33 to 31 minutes -- small, but it biases the estimator toward exactly the
implausible end it is trying to measure.
"""

OVERNIGHT_GROUND_MINUTES = 285
"""Boundary between a turn and an overnight sit, taken from the measured trough.

The ground-time distribution is bimodal as section 10 predicted: a turn mode peaking at 60-89
minutes, a minimum-density bin at 270-299, and an overnight mode rising again from 360. 285 is
the centre of that trough.

This threshold labels a termination reason. It does not change a single projected minute:
absorption is decided by the `max` above, which already handles a ten-hour sit correctly without
being told it is overnight. Keeping it out of the arithmetic means the empirical choice cannot
quietly move the numbers the tool reports.
"""

MAX_CHAIN_LEGS = 40
"""Guard on the walk. next_leg is derived from a strict time ordering and cannot cycle; this
bounds the damage if a database is ever corrupt."""


@dataclass(frozen=True)
class TurnTimeModel:
    """Minimum turn times estimated from observed ground times.

    Estimated per carrier and station, falling back carrier-wide where a station has too few
    observations to estimate from, and network-wide where a carrier does. 1,135 of 1,436
    carrier-station pairs clear the 30-turn bar, covering 98.8% of observed turns, so the
    fallback is a genuine edge case rather than the common path.
    """

    per_station: dict[tuple[str, str], int]
    per_carrier: dict[str, int]
    network: int

    def minimum_turn(self, carrier: str, station: str) -> int:
        station_estimate = self.per_station.get((carrier, station))
        if station_estimate is not None:
            return station_estimate
        return self.per_carrier.get(carrier, self.network)

    def basis(self, carrier: str, station: str) -> str:
        """Which estimate was used, so a projection can explain itself."""
        if (carrier, station) in self.per_station:
            return f"{carrier} at {station}"
        if carrier in self.per_carrier:
            return f"{carrier} network-wide (too few turns at {station})"
        return "all carriers"


def build_turn_model(store: ObjectStore) -> TurnTimeModel:
    """Measure turn times once, from the ingested month."""
    per_station, per_carrier, network = store.turn_time_estimates(
        quantile=TURN_QUANTILE,
        min_ground_minutes=IMPLAUSIBLE_TURN_MINUTES,
        min_sample=MIN_TURN_SAMPLE,
    )
    return TurnTimeModel(per_station=per_station, per_carrier=per_carrier, network=network)


def _minutes_between(earlier: datetime, later: datetime) -> int:
    """Whole minutes from one instant to another. Both are UTC-aware, as stored."""
    return round((later - earlier).total_seconds() / 60)


class PropagationEngine:
    """Projects a root delay down an aircraft's remaining line of flying."""

    def __init__(self, turn_model: TurnTimeModel) -> None:
        self.turn_model = turn_model

    def project(
        self,
        scenario: Scenario,
        root_flight_id: str,
        root_delay_minutes: int,
    ) -> DisruptionEvent:
        """Walk the chain forward from a delayed root and attribute downstream minutes.

        The root's own delay is not counted in the total: the question is what this delay costs
        *elsewhere*, so the total is the sum of minutes forced onto downstream legs.
        """
        root = scenario.get_flight(root_flight_id)
        if root.tail_number is None:
            return DisruptionEvent(
                event_id=f"evt:{root_flight_id}",
                root_flight_id=root_flight_id,
                tail_number="",
                cause=_root_cause(root),
                root_delay_minutes=root_delay_minutes,
                affected=(),
                total_propagated_minutes=0,
                termination=ChainTermination.CHAIN_BREAK,
            )

        projected_arrival = root.sched_arr_utc + timedelta(minutes=root_delay_minutes)
        carried = root_delay_minutes
        affected: list[AffectedLeg] = []
        termination = ChainTermination.END_OF_WINDOW
        current = root

        for position in range(1, MAX_CHAIN_LEGS + 1):
            following = scenario.next_leg(current.flight_id)
            if following is None:
                termination = _break_termination(scenario.store, current.flight_id)
                break

            if following.status is FlightStatus.CANCELLED:
                termination = ChainTermination.CANCELLATION
                break

            turn = self.turn_model.minimum_turn(following.carrier, following.origin)
            earliest_departure = projected_arrival + timedelta(minutes=turn)
            projected_departure = max(following.sched_dep_utc, earliest_departure)
            propagated = _minutes_between(following.sched_dep_utc, projected_departure)

            if propagated <= 0:
                ground = scenario.store.ground_minutes_after(current.flight_id)
                termination = (
                    ChainTermination.OVERNIGHT_BREAK
                    if ground is not None and ground >= OVERNIGHT_GROUND_MINUTES
                    else ChainTermination.ABSORBED
                )
                break

            projected_arrival = projected_departure + timedelta(
                minutes=following.sched_block_minutes
            )
            affected.append(
                AffectedLeg(
                    flight_id=following.flight_id,
                    position=position,
                    projected_dep_utc=projected_departure,
                    projected_arr_utc=projected_arrival,
                    propagated_delay_minutes=propagated,
                    absorbed_minutes=max(0, carried - propagated),
                )
            )
            carried = propagated
            current = following
        else:
            termination = ChainTermination.GUARD_LIMIT

        return DisruptionEvent(
            event_id=f"evt:{root_flight_id}",
            root_flight_id=root_flight_id,
            tail_number=root.tail_number,
            cause=_root_cause(root),
            root_delay_minutes=root_delay_minutes,
            affected=tuple(affected),
            total_propagated_minutes=sum(leg.propagated_delay_minutes for leg in affected),
            termination=termination,
        )


def _root_cause(flight: Flight) -> str:
    """The BTS cause bucket carrying most of this leg's delay, or 'unattributed'.

    Read from the data rather than inferred. Below 15 minutes BTS attributes nothing, and saying
    'carrier' when the source says nothing would be inventing an attribution.
    """
    if flight.causes is None:
        return "unattributed"
    buckets = {
        "carrier": flight.causes.carrier,
        "weather": flight.causes.weather,
        "nas": flight.causes.nas,
        "security": flight.causes.security,
        "late_aircraft": flight.causes.late_aircraft,
    }
    largest = max(buckets, key=lambda name: buckets[name])
    return largest if buckets[largest] > 0 else "unattributed"


def _break_termination(store: ObjectStore, flight_id: str) -> ChainTermination:
    """Map the recorded chain-break reason onto a termination, never guessing."""
    reason = store.chain_break_after(flight_id)
    if reason == "end_of_window":
        return ChainTermination.END_OF_WINDOW
    return ChainTermination.CHAIN_BREAK
