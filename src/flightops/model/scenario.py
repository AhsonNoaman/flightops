"""The scenario overlay: a pinned clock plus applied changes, read through over immutable base data.

DESIGN.md section 7. The base DuckDB file is historical fact and is never written to. A scenario
is a "now" inside a replayed day plus an ordered list of applied action diffs; reads go through
the overlay, so an action can change what the model sees without changing what is stored.

This is a mechanism, not an entity. It does not appear in the ontology and does not count
against the five objects. Three things make it worth the code: the brief forbids silent
mutation; the deployed API ships DuckDB baked in read-only, which this turns from a
contradiction into a feature, since every session gets its own sandbox over shared bytes; and it
gives the demo its shape, which is replaying a real disrupted day and trying the swap you wish
you had made.

The clock matters for preconditions rather than for reads. An action is legal or not depending
on where "now" sits relative to a leg: you cannot cancel a flight that has already pushed back.
Pinning it makes that check deterministic and replayable instead of dependent on wall time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from flightops.model.objects import Flight, FlightStatus
from flightops.model.store import Link, ObjectStore


@dataclass(frozen=True)
class AppliedChange:
    """One leg changed by one action, kept so the overlay can be explained and replayed."""

    flight_id: str
    action: str
    summary: str
    before: Flight
    after: Flight


@dataclass
class Scenario:
    """A sandbox over the base data: a pinned clock and the changes applied so far."""

    store: ObjectStore
    clock: datetime
    changes: list[AppliedChange] = field(default_factory=list)
    _overrides: dict[str, Flight] = field(default_factory=dict, repr=False)

    # -- reads through the overlay ------------------------------------------------------------

    def get_flight(self, flight_id: str) -> Flight:
        """The flight as this scenario sees it: the overridden version where one exists."""
        override = self._overrides.get(flight_id)
        return override if override is not None else self.store.get_flight(flight_id)

    def next_leg(self, flight_id: str) -> Flight | None:
        following = self.store.next_leg(flight_id)
        return self.get_flight(following.flight_id) if following else None

    def previous_leg(self, flight_id: str) -> Flight | None:
        preceding = self.store.previous_leg(flight_id)
        return self.get_flight(preceding.flight_id) if preceding else None

    def rotation(self, tail_number: str, flight_date: str | None = None) -> list[Flight]:
        """The tail's legs in scheduled order, each read through the overlay.

        Re-sorted after the overlay is applied: a delay action moves a leg in time, and a
        rotation returned in stale order would silently mislead every caller downstream.
        """
        legs = [
            self.get_flight(leg.flight_id)
            for leg in self.store.rotation(tail_number, flight_date)
        ]
        return sorted(legs, key=lambda leg: (leg.sched_dep_utc, leg.flight_id))

    def traverse(self, flight: Flight, link: Link) -> list[object]:
        """Link traversal through the overlay, so agent tools never see stale legs."""
        results = self.store.traverse(flight, link)
        return [
            self.get_flight(item.flight_id) if isinstance(item, Flight) else item
            for item in results
        ]

    # -- the chain a cascade actually walks ---------------------------------------------------

    def downstream_chain(self, flight_id: str, *, max_legs: int = 40) -> list[Flight]:
        """Every leg after this one on the same tail, in order, stopping where the chain does.

        `max_legs` is a guard, not a model parameter. next_leg is derived from a strict ordering
        so it cannot contain a cycle, but a bounded walk means a corrupt database degrades into
        a short answer rather than a hang.
        """
        chain: list[Flight] = []
        current = flight_id
        while len(chain) < max_legs:
            following = self.next_leg(current)
            if following is None:
                break
            chain.append(following)
            current = following.flight_id
        return chain

    # -- writes, which only ever touch the overlay --------------------------------------------

    def apply(self, change: AppliedChange) -> None:
        """Record a change. The base tables are not touched, now or ever."""
        self._overrides[change.flight_id] = change.after
        self.changes.append(change)

    def is_pending(self, flight: Flight) -> bool:
        """Whether the leg is still ahead of the scenario clock and so still actionable.

        Reads the scenario clock rather than the flight's recorded status, because the base data
        is a completed day: every leg in it has already happened. Replaying that day means
        deciding what is still in the future relative to the pinned "now".
        """
        if flight.status is FlightStatus.CANCELLED:
            return False
        return flight.sched_dep_utc > self.clock

    def describe(self) -> str:
        """The scenario as a line an operator can read, for diffs and answers."""
        if not self.changes:
            return f"scenario at {self.clock:%Y-%m-%d %H:%M} UTC, no changes applied"
        applied = "; ".join(change.summary for change in self.changes)
        return (
            f"scenario at {self.clock:%Y-%m-%d %H:%M} UTC, "
            f"{len(self.changes)} applied: {applied}"
        )
