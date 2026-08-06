"""Finding the day's cascades, not just the day's late flights.

The list an operations controller wants at the top of a screen is not "the twenty latest
departures". Most of those are the same disruption seen five times: one aircraft goes late in the
morning and every leg it flies afterwards shows up as its own late flight. Ranking by delay
minutes therefore produces a screen where the biggest problem is repeated until it crowds out the
second biggest.

So this module ranks roots, and it decides what a root is from the data rather than by guessing.
BTS already distinguishes the two cases: `late_aircraft` minutes are the carrier's own record
that a leg was late because its inbound aircraft was late. A leg whose largest cause bucket is
`late_aircraft` is a consequence, not a cause, and is excluded. What survives is ranked by what
it did to everything downstream, which is the number the propagation engine exists to produce.
"""

from __future__ import annotations

from flightops.model.objects import CauseBuckets, DisruptionEvent
from flightops.model.scenario import Scenario
from flightops.model.store import ObjectStore
from flightops.propagation.engine import PropagationEngine

MIN_ROOT_DELAY_MINUTES = 30
"""Below this a delay is noise: BTS attributes no cause under 15 minutes, and a half-hour is
about where a turn stops absorbing and starts propagating on this data."""

MAX_CANDIDATES = 80
"""Ceiling on chains walked per request. Each projection is a handful of indexed lookups, and
the ranking is stable well before eighty because the tail of the delay distribution is thin."""

CANDIDATE_FETCH_LIMIT = 6000
"""Every qualifying leg on the day, not a slice of them.

`find_flights` orders by scheduled departure, so any limit below a full day silently drops the
evening. That is not a smaller answer, it is a wrong one: fetching 320 candidates on 2026-01-03
left out 104 legs delayed by 100 minutes or more, all of them after 23:10 UTC, and the ranking
still looked plausible because the worst root of that day happened to depart in the morning. The
bound that matters is the day, and a day is at most a few thousand delayed legs.
"""


def rank_disruptions(
    store: ObjectStore,
    engine: PropagationEngine,
    flight_date: str,
    *,
    limit: int = 10,
    min_delay_minutes: int = MIN_ROOT_DELAY_MINUTES,
) -> list[DisruptionEvent]:
    """The day's disruptions, ranked by the downstream minutes each one caused.

    One event per aircraft: where a tail has more than one qualifying root, the largest wins,
    because the later ones are flying inside a day the first root already broke.
    """
    candidates = store.find_flights(
        flight_date=flight_date,
        min_dep_delay=min_delay_minutes,
        limit=CANDIDATE_FETCH_LIMIT,
    )
    if not candidates:
        return []

    # An empty scenario over the base data. The clock is unused here -- projection reads the
    # overlay but never checks whether a leg is still pending, which is an action precondition.
    scenario = Scenario(store=store, clock=candidates[0].sched_dep_utc)

    seen_tails: set[str] = set()
    events: list[DisruptionEvent] = []
    for flight in sorted(candidates, key=lambda leg: -(leg.dep_delay_minutes or 0)):
        if len(events) >= MAX_CANDIDATES:
            break
        if flight.tail_number is None or flight.tail_number in seen_tails:
            continue
        if _is_inherited(flight.causes):
            continue
        seen_tails.add(flight.tail_number)
        events.append(engine.project(scenario, flight.flight_id, flight.dep_delay_minutes or 0))

    events.sort(key=lambda event: (-event.total_propagated_minutes, -event.root_delay_minutes))
    return events[:limit]


def _is_inherited(causes: CauseBuckets | None) -> bool:
    """Whether this leg's delay is mostly the previous leg's delay wearing a different number."""
    if causes is None:
        return False
    buckets = {
        "carrier": causes.carrier,
        "weather": causes.weather,
        "nas": causes.nas,
        "security": causes.security,
        "late_aircraft": causes.late_aircraft,
    }
    largest = max(buckets, key=lambda name: buckets[name])
    return largest == "late_aircraft" and buckets[largest] > 0
