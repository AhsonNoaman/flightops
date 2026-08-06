"""Validate propagation against the data's own answer.

DESIGN.md section 10 requires two independent checks, because a propagation model that is never
tested against reality is just arithmetic:

1. Replay real root delays and compare projected downstream delay against what actually happened.
2. Compare projected propagated minutes against BTS's LateAircraftDelay on the same legs -- the
   dataset's own attribution of how much of a leg's delay came from its inbound aircraft.

The second is the stronger test. LateAircraftDelay is produced by the carrier, independently of
anything here, and the cause buckets were measured to partition arrival delay exactly, so it is a
clean measurement of the quantity this engine predicts.

Section 10 also requires the known error sources be stated rather than discovered by a reader:

- Schedule padding absorbs delay. Actual block times routinely beat scheduled ones, so a model
  that projects arrival as departure plus *scheduled* block over-predicts how late the aircraft
  really gets in.
- Controller interventions are already inside the actuals. The engine projects a do-nothing
  world; the recorded outcome is a world where someone swapped a tail or called in a spare. So
  the model predicts cascades that a human prevented, and that gap is the tool's whole point.
- min_turn is an estimate from observed ground times, not the carrier's contractual minimum.
- Mainline-regional handoffs and ferry moves are invisible in OTP data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from flightops.model.objects import FlightStatus
from flightops.model.scenario import Scenario
from flightops.model.store import ObjectStore
from flightops.propagation.engine import PropagationEngine, build_turn_model


@dataclass(frozen=True)
class LegComparison:
    """One downstream leg: what the engine projected against what BTS attributed."""

    flight_id: str
    position: int
    projected_minutes: int
    bts_late_aircraft_minutes: int
    actual_dep_delay_minutes: int | None

    @property
    def error(self) -> int:
        return self.projected_minutes - self.bts_late_aircraft_minutes


@dataclass(frozen=True)
class ValidationResult:
    """Aggregate accuracy over many replayed root delays."""

    roots_tested: int
    legs_compared: int
    mean_error: float
    median_error: float
    within_15_minutes: int
    within_30_minutes: int
    engine_predicted_nonzero_bts_zero: int
    bts_nonzero_engine_zero: int
    comparisons: list[LegComparison]

    def render(self) -> str:
        if self.legs_compared == 0:
            return "no comparable legs found"

        within_15 = 100 * self.within_15_minutes / self.legs_compared
        within_30 = 100 * self.within_30_minutes / self.legs_compared
        return "\n".join(
            [
                f"roots replayed:            {self.roots_tested:,}",
                f"downstream legs compared:  {self.legs_compared:,}",
                f"mean error (min):          {self.mean_error:+.1f}",
                f"median error (min):        {self.median_error:+.1f}",
                f"within 15 min of BTS:      {self.within_15_minutes:,} ({within_15:.0f}%)",
                f"within 30 min of BTS:      {self.within_30_minutes:,} ({within_30:.0f}%)",
                f"engine says late, BTS 0:   {self.engine_predicted_nonzero_bts_zero:,}",
                f"BTS says late, engine 0:   {self.bts_nonzero_engine_zero:,}",
            ]
        )


def validate_against_bts(
    store: ObjectStore,
    *,
    min_root_delay: int = 60,
    max_roots: int = 400,
) -> ValidationResult:
    """Replay real root delays and score the projection against LateAircraftDelay.

    A root is a leg that departed late by at least `min_root_delay` and whose own delay was not
    itself attributed to a late inbound aircraft -- otherwise the "root" is mid-cascade and its
    downstream legs are being double counted.
    """
    engine = PropagationEngine(build_turn_model(store))
    comparisons: list[LegComparison] = []
    roots_tested = 0

    for root in store.find_flights(min_dep_delay=min_root_delay, limit=max_roots * 4):
        if root.tail_number is None or root.causes is None:
            continue
        if root.causes.late_aircraft > root.causes.total / 2:
            continue
        if root.dep_delay_minutes is None:
            continue

        scenario = Scenario(store=store, clock=root.sched_dep_utc - timedelta(minutes=1))
        event = engine.project(scenario, root.flight_id, root.dep_delay_minutes)
        if not event.affected:
            continue

        roots_tested += 1
        for leg in event.affected:
            downstream = store.get_flight(leg.flight_id)
            if downstream.causes is None or downstream.status is FlightStatus.CANCELLED:
                continue
            comparisons.append(
                LegComparison(
                    flight_id=leg.flight_id,
                    position=leg.position,
                    projected_minutes=leg.propagated_delay_minutes,
                    bts_late_aircraft_minutes=downstream.causes.late_aircraft,
                    actual_dep_delay_minutes=downstream.dep_delay_minutes,
                )
            )
        if roots_tested >= max_roots:
            break

    if not comparisons:
        return ValidationResult(roots_tested, 0, 0.0, 0.0, 0, 0, 0, 0, [])

    errors = sorted(comparison.error for comparison in comparisons)
    middle = len(errors) // 2
    median = (
        float(errors[middle])
        if len(errors) % 2
        else (errors[middle - 1] + errors[middle]) / 2
    )
    return ValidationResult(
        roots_tested=roots_tested,
        legs_compared=len(comparisons),
        mean_error=sum(errors) / len(errors),
        median_error=median,
        within_15_minutes=sum(1 for c in comparisons if abs(c.error) <= 15),
        within_30_minutes=sum(1 for c in comparisons if abs(c.error) <= 30),
        engine_predicted_nonzero_bts_zero=sum(
            1
            for c in comparisons
            if c.projected_minutes > 0 and c.bts_late_aircraft_minutes == 0
        ),
        bts_nonzero_engine_zero=sum(
            1
            for c in comparisons
            if c.projected_minutes == 0 and c.bts_late_aircraft_minutes > 0
        ),
        comparisons=comparisons,
    )
