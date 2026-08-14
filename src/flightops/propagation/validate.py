"""Validate propagation against the data's own answer.

DESIGN.md section 10 requires two independent checks, because a propagation model that is never
tested against reality is just arithmetic:

1. Replay real root delays and compare projected downstream delay against what actually happened.
2. Compare projected propagated minutes against BTS's LateAircraftDelay on the same legs, which
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

import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from statistics import median

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
    itself attributed to a late inbound aircraft. Otherwise the "root" is mid-cascade and its
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
    median = float(errors[middle]) if len(errors) % 2 else (errors[middle - 1] + errors[middle]) / 2
    return ValidationResult(
        roots_tested=roots_tested,
        legs_compared=len(comparisons),
        mean_error=sum(errors) / len(errors),
        median_error=median,
        within_15_minutes=sum(1 for c in comparisons if abs(c.error) <= 15),
        within_30_minutes=sum(1 for c in comparisons if abs(c.error) <= 30),
        engine_predicted_nonzero_bts_zero=sum(
            1 for c in comparisons if c.projected_minutes > 0 and c.bts_late_aircraft_minutes == 0
        ),
        bts_nonzero_engine_zero=sum(
            1 for c in comparisons if c.projected_minutes == 0 and c.bts_late_aircraft_minutes > 0
        ),
        comparisons=comparisons,
    )


@dataclass(frozen=True)
class ShapeResult:
    """How cascades are actually shaped, measured rather than assumed.

    DESIGN.md section 10 commits to measuring this before claiming it, because the brief's
    motivating example, forty minutes at one station becoming three hours by evening,
    conflates two different claims. Per-leg delay decaying down a rotation and summed downstream
    minutes exceeding the root delay are not the same statement, and the data supports them to
    very different degrees.
    """

    roots_examined: int
    roots_with_a_cascade: int
    median_sum_over_root: float
    mean_sum_over_root: float
    share_sum_exceeds_root: float
    median_first_leg_over_root: float
    median_legs_affected: float

    def render(self) -> str:
        absorbed = self.roots_examined - self.roots_with_a_cascade
        share_absorbed = 100 * absorbed / self.roots_examined if self.roots_examined else 0.0
        return "\n".join(
            [
                f"roots examined:            {self.roots_examined:,}",
                f"propagated nothing:        {absorbed:,} ({share_absorbed:.0f}%)",
                f"median first leg / root:   {self.median_first_leg_over_root:.2f}x",
                f"median legs affected:      {self.median_legs_affected:.0f}",
                f"median sum / root:         {self.median_sum_over_root:.2f}x",
                f"mean sum / root:           {self.mean_sum_over_root:.2f}x",
                f"sum exceeds root:          {self.share_sum_exceeds_root:.0f}% of cascades",
            ]
        )


def measure_cascade_shape(
    store: ObjectStore, *, min_root_delay: int = 60, max_roots: int = 500
) -> ShapeResult:
    """Ratios of downstream minutes to root delay, over real roots.

    Same root definition as the BTS comparison above, a leg delayed by at least
    `min_root_delay` whose own delay is not itself mostly inherited, so the two tables are
    measured over the same population and can be read together.
    """
    engine = PropagationEngine(build_turn_model(store))
    sums: list[float] = []
    firsts: list[float] = []
    legs: list[int] = []
    examined = 0

    for root in store.find_flights(min_dep_delay=min_root_delay, limit=max_roots * 8):
        if root.tail_number is None or root.causes is None or root.dep_delay_minutes is None:
            continue
        if root.causes.late_aircraft > root.causes.total / 2:
            continue
        examined += 1
        scenario = Scenario(store=store, clock=root.sched_dep_utc - timedelta(minutes=1))
        event = engine.project(scenario, root.flight_id, root.dep_delay_minutes)
        if not event.affected:
            continue
        sums.append(event.total_propagated_minutes / root.dep_delay_minutes)
        firsts.append(event.affected[0].propagated_delay_minutes / root.dep_delay_minutes)
        legs.append(len(event.affected))
        if len(sums) >= max_roots:
            break

    if not sums:
        return ShapeResult(examined, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return ShapeResult(
        roots_examined=examined,
        roots_with_a_cascade=len(sums),
        median_sum_over_root=median(sums),
        mean_sum_over_root=sum(sums) / len(sums),
        share_sum_exceeds_root=100 * sum(1 for ratio in sums if ratio > 1) / len(sums),
        median_first_leg_over_root=median(firsts),
        median_legs_affected=median(legs),
    )


def main(argv: list[str]) -> int:
    """Reproduce the two tables in the README.

        python -m flightops.propagation.validate [database.duckdb]

    Defaults to the committed sample, which is the one a fresh clone can run.
    """
    default = Path(__file__).resolve().parents[3] / "data" / "sample" / "sample.duckdb"
    database = Path(argv[1]) if len(argv) > 1 else default
    if not database.exists():
        raise SystemExit(f"no database at {database}; run `python -m flightops.ingest.sample`")

    with ObjectStore(database) as store:
        first, last, carriers = store.coverage()
        print(
            f"{database.name}: {first} to {last}, {store.flight_count():,} flights, "
            f"{len(carriers)} carrier(s)\n"
        )
        print("-- projection against BTS LateAircraftDelay")
        print(validate_against_bts(store).render())
        print("\n-- cascade shape")
        print(measure_cascade_shape(store).render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
