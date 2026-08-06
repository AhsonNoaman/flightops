"""The five domain objects.

DESIGN.md section 4 fixes the ontology at five objects, and section 13 makes adding a sixth a
stop-and-ask. Each one here is an entity an operations controller would name, not a table that
happened to be convenient: the operational unit that gets delayed, swapped, or cancelled is the
leg, so Flight is a leg and not a flight number.

Times are carried in both local and UTC, per DESIGN.md section 8. Local is what the operator
reads on a board; UTC is what every comparison and interval uses, because a rotation crossing a
timezone cannot be ordered in local time. Keeping both is the decision; deriving one on demand
at each call site is how the two get mixed up.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FlightStatus(StrEnum):
    """Operational state of a leg, as reported by BTS.

    `diverted` is distinct from `arrived` on purpose: BTS gives diverted rows their own field
    semantics, leaves arrival delay null, and reports the eventual outcome separately.
    """

    SCHEDULED = "scheduled"
    DEPARTED = "departed"
    ARRIVED = "arrived"
    CANCELLED = "cancelled"
    DIVERTED = "diverted"


class CancellationCode(StrEnum):
    """BTS cancellation reason codes."""

    CARRIER = "A"
    WEATHER = "B"
    NATIONAL_AIR_SYSTEM = "C"
    SECURITY = "D"


class CauseBuckets(BaseModel):
    """BTS's own attribution of an arrival delay across five causes.

    Populated only when arrival delay reaches 15 minutes, and then the five sum to the arrival
    delay exactly -- measured across all 107,475 bucketed legs in January 2026, with no
    exceptions. `late_aircraft` is the dataset's independent answer to the question the
    propagation engine computes, which is what makes it usable as validation at M4.
    """

    model_config = ConfigDict(frozen=True)

    carrier: int
    weather: int
    nas: int
    security: int
    late_aircraft: int

    @property
    def total(self) -> int:
        return self.carrier + self.weather + self.nas + self.security + self.late_aircraft


class Flight(BaseModel):
    """One operated leg on one calendar date.

    Keyed by date, carrier, flight number, origin, destination, and scheduled departure. The
    destination is part of the key because the design's key without it is not unique: F9 3237
    out of JFK at 0659 on 2026-01-04 appears twice, to CVG and to LAS.
    """

    model_config = ConfigDict(frozen=True)

    flight_id: str
    flight_date: str
    carrier: str
    flight_number: str
    origin: str
    destination: str
    tail_number: str | None
    status: FlightStatus
    cancellation_code: CancellationCode | None

    sched_dep_local: datetime
    sched_arr_local: datetime
    sched_dep_utc: datetime
    sched_arr_utc: datetime
    actual_dep_utc: datetime | None
    actual_arr_utc: datetime | None

    dep_delay_minutes: int | None
    arr_delay_minutes: int | None
    sched_block_minutes: int
    distance_miles: int | None
    causes: CauseBuckets | None

    @property
    def is_cancelled(self) -> bool:
        return self.status is FlightStatus.CANCELLED

    @property
    def has_departed(self) -> bool:
        """Whether the leg left the gate. Diverted flights departed; cancelled ones did not."""
        return self.status in (FlightStatus.DEPARTED, FlightStatus.ARRIVED, FlightStatus.DIVERTED)

    @property
    def projected_arr_utc(self) -> datetime:
        """Best known arrival: actual where the leg landed, scheduled otherwise."""
        return self.actual_arr_utc or self.sched_arr_utc

    def describe(self) -> str:
        """One line in the operator's vocabulary, for answers and diffs."""
        return (
            f"{self.carrier}{self.flight_number} {self.origin}-{self.destination} "
            f"{self.sched_dep_local:%H:%M} {self.flight_date}"
        )


class Aircraft(BaseModel):
    """A tail as BTS reports it.

    Deliberately not the FAA registry object: BTS carries no aircraft type, and joining the
    registry would be a second operational data source. The consequence is that swap_aircraft
    validates carrier, position, and timing but not fleet compatibility -- a named limitation
    surfaced in TRAINING.md rather than papered over.
    """

    model_config = ConfigDict(frozen=True)

    tail_number: str
    carrier: str


class Airport(BaseModel):
    """A station. The timezone is the load-bearing property.

    BTS reports times in local, and a rotation crossing timezones cannot be ordered without
    normalising to UTC. Every zone in the committed table is confirmed against the offset
    implied by the data's own scheduled block times.
    """

    model_config = ConfigDict(frozen=True)

    iata: str
    city: str
    iana_timezone: str


class Carrier(BaseModel):
    """A reporting carrier: the operating entity, not the marketing brand.

    Regionals report separately from the mainline whose flights they fly, so a passenger's
    "American" itinerary can appear under MQ or OH. The tool is scoped to the operating carrier;
    the marketing-versus-operating split is a named limitation.
    """

    model_config = ConfigDict(frozen=True)

    code: str
    name: str


class ChainTermination(StrEnum):
    """Why a cascade stopped propagating down a rotation."""

    ABSORBED = "absorbed"
    OVERNIGHT_BREAK = "overnight_break"
    CANCELLATION = "cancellation"
    CHAIN_BREAK = "chain_break"
    END_OF_WINDOW = "end_of_window"


class AffectedLeg(BaseModel):
    """One downstream leg of a cascade, with the minutes attributed to the root."""

    model_config = ConfigDict(frozen=True)

    flight_id: str
    position: int = Field(ge=1, description="1 is the leg immediately after the root")
    projected_dep_utc: datetime
    projected_arr_utc: datetime
    propagated_delay_minutes: int
    absorbed_minutes: int = Field(
        ge=0, description="Delay the scheduled ground and block time soaked up at this leg"
    )


class DisruptionEvent(BaseModel):
    """A root delay and everything it drags down: the addressable unit of a cascade.

    An object rather than a report because the operator needs to point at "this morning's ORD
    cascade" -- questions reference it, actions target it. Always recomputed from flights and
    chains, never hand-edited: a curated event would be synthetic data presented as real.
    """

    model_config = ConfigDict(frozen=True)

    event_id: str
    root_flight_id: str
    tail_number: str
    cause: str
    root_delay_minutes: int
    affected: tuple[AffectedLeg, ...]
    total_propagated_minutes: int
    termination: ChainTermination

    @property
    def leg_count(self) -> int:
        """Downstream legs touched, excluding the root."""
        return len(self.affected)
