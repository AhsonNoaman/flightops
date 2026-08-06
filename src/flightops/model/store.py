"""Read-only object store over the ingested DuckDB file, with typed link traversal.

The store is the only place that knows SQL. Everything above it -- propagation, actions, the
question-answering tools -- moves through objects and named links, which is what makes the
constraint in DESIGN.md section 11 enforceable rather than aspirational: there is no SQL path to
hand the model, because the model is never given this class.

`previous_leg` is the inverse of `next_leg` rather than a new link in the ontology. Triage walks
backwards -- an operator sees a late flight and needs its root, not its consequences -- and the
inverse of a stored link is free to traverse. Adding it costs nothing and omitting it would push
callers into writing their own SQL, which is the thing the store exists to prevent.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

from flightops.model.objects import (
    Aircraft,
    Airport,
    CancellationCode,
    Carrier,
    CauseBuckets,
    Flight,
    FlightStatus,
)

FLIGHT_COLUMNS = """
    flight_id, flight_date, carrier, flight_number, origin, destination, tail_number, status,
    cancellation_code, sched_dep_local, sched_arr_local, sched_dep_utc, sched_arr_utc,
    actual_dep_utc, actual_arr_utc, dep_delay_minutes, arr_delay_minutes, sched_block_minutes,
    distance_miles, delay_carrier, delay_weather, delay_nas, delay_security, delay_late_aircraft
"""


class Link(StrEnum):
    """The named, traversable links of the ontology (DESIGN.md section 5)."""

    FLOWN_BY = "flown_by"
    OPERATED_BY = "operated_by"
    DEPARTS_FROM = "departs_from"
    ARRIVES_AT = "arrives_at"
    NEXT_LEG = "next_leg"
    PREVIOUS_LEG = "previous_leg"
    ROTATION = "rotation"


class ObjectNotFound(LookupError):
    """Raised with the object id, per the brief's requirement that errors name the object."""

    def __init__(self, object_type: str, object_id: str) -> None:
        super().__init__(f"no {object_type} with id {object_id!r}")
        self.object_type = object_type
        self.object_id = object_id


def _flight_from_row(row: tuple[Any, ...]) -> Flight:
    """Build a Flight from a row selected with FLIGHT_COLUMNS."""
    causes = (
        CauseBuckets(
            carrier=row[19], weather=row[20], nas=row[21], security=row[22], late_aircraft=row[23]
        )
        if row[19] is not None
        else None
    )
    return Flight(
        flight_id=row[0],
        flight_date=str(row[1]),
        carrier=row[2],
        flight_number=row[3],
        origin=row[4],
        destination=row[5],
        tail_number=row[6],
        status=FlightStatus(row[7]),
        cancellation_code=CancellationCode(row[8]) if row[8] else None,
        sched_dep_local=row[9],
        sched_arr_local=row[10],
        sched_dep_utc=row[11],
        sched_arr_utc=row[12],
        actual_dep_utc=row[13],
        actual_arr_utc=row[14],
        dep_delay_minutes=row[15],
        arr_delay_minutes=row[16],
        sched_block_minutes=row[17],
        distance_miles=row[18],
        causes=causes,
    )


class ObjectStore:
    """Typed reads and link traversal over one ingested month."""

    def __init__(self, database: Path | str, *, read_only: bool = True) -> None:
        self._connection = duckdb.connect(str(database), read_only=read_only)
        self._connection.execute("LOAD icu")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> ObjectStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- objects ----------------------------------------------------------------------------

    def get_flight(self, flight_id: str) -> Flight:
        row = self._connection.execute(
            f"SELECT {FLIGHT_COLUMNS} FROM flights WHERE flight_id = ?", [flight_id]
        ).fetchone()
        if row is None:
            raise ObjectNotFound("Flight", flight_id)
        return _flight_from_row(row)

    def get_aircraft(self, tail_number: str) -> Aircraft:
        row = self._connection.execute(
            "SELECT tail_number, any_value(carrier) FROM flights WHERE tail_number = ? "
            "GROUP BY 1",
            [tail_number],
        ).fetchone()
        if row is None:
            raise ObjectNotFound("Aircraft", tail_number)
        return Aircraft(tail_number=row[0], carrier=row[1])

    def get_airport(self, iata: str) -> Airport:
        row = self._connection.execute(
            "SELECT iata, city, iana_timezone FROM airports WHERE iata = ?", [iata]
        ).fetchone()
        if row is None:
            raise ObjectNotFound("Airport", iata)
        return Airport(iata=row[0], city=row[1], iana_timezone=row[2])

    def get_carrier(self, code: str) -> Carrier:
        row = self._connection.execute(
            "SELECT code, name FROM carriers WHERE code = ?", [code]
        ).fetchone()
        if row is None:
            raise ObjectNotFound("Carrier", code)
        return Carrier(code=row[0], name=row[1])

    # -- filtered search --------------------------------------------------------------------

    def find_flights(
        self,
        *,
        carrier: str | None = None,
        origin: str | None = None,
        destination: str | None = None,
        tail_number: str | None = None,
        flight_date: str | None = None,
        status: FlightStatus | None = None,
        min_dep_delay: int | None = None,
        min_arr_delay: int | None = None,
        departing_after: datetime | None = None,
        departing_before: datetime | None = None,
        limit: int = 200,
    ) -> list[Flight]:
        """Typed filters only. Every parameter is bound, never interpolated."""
        clauses: list[str] = ["TRUE"]
        params: list[object] = []
        for column, value in (
            ("carrier", carrier),
            ("origin", origin),
            ("destination", destination),
            ("tail_number", tail_number),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if flight_date is not None:
            clauses.append("flight_date = CAST(? AS DATE)")
            params.append(flight_date)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if min_dep_delay is not None:
            clauses.append("dep_delay_minutes >= ?")
            params.append(min_dep_delay)
        if min_arr_delay is not None:
            clauses.append("arr_delay_minutes >= ?")
            params.append(min_arr_delay)
        if departing_after is not None:
            clauses.append("sched_dep_utc >= ?")
            params.append(departing_after)
        if departing_before is not None:
            clauses.append("sched_dep_utc <= ?")
            params.append(departing_before)

        rows = self._connection.execute(
            f"SELECT {FLIGHT_COLUMNS} FROM flights WHERE {' AND '.join(clauses)} "
            "ORDER BY sched_dep_utc, flight_id LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [_flight_from_row(row) for row in rows]

    # -- traversal --------------------------------------------------------------------------

    def next_leg(self, flight_id: str) -> Flight | None:
        """The same aircraft's following leg, or None where the chain breaks."""
        row = self._connection.execute(
            f"SELECT {FLIGHT_COLUMNS} FROM flights WHERE flight_id = "
            "(SELECT to_flight_id FROM next_leg WHERE from_flight_id = ?)",
            [flight_id],
        ).fetchone()
        return _flight_from_row(row) if row else None

    def previous_leg(self, flight_id: str) -> Flight | None:
        """The leg the aircraft flew in immediately before this one."""
        row = self._connection.execute(
            f"SELECT {FLIGHT_COLUMNS} FROM flights WHERE flight_id = "
            "(SELECT from_flight_id FROM next_leg WHERE to_flight_id = ?)",
            [flight_id],
        ).fetchone()
        return _flight_from_row(row) if row else None

    def ground_minutes_after(self, flight_id: str) -> int | None:
        """Scheduled ground time between this leg's arrival and the tail's next departure."""
        row = self._connection.execute(
            "SELECT ground_minutes FROM next_leg WHERE from_flight_id = ?", [flight_id]
        ).fetchone()
        return int(row[0]) if row else None

    def chain_break_after(self, flight_id: str) -> str | None:
        """Why the chain stops here, if it does: the recorded reason, never a guess."""
        row = self._connection.execute(
            "SELECT reason FROM chain_breaks WHERE flight_id = ?", [flight_id]
        ).fetchone()
        return str(row[0]) if row else None

    def rotation(self, tail_number: str, flight_date: str | None = None) -> list[Flight]:
        """An aircraft's legs in scheduled order, optionally restricted to one day."""
        clauses = ["tail_number = ?"]
        params: list[object] = [tail_number]
        if flight_date is not None:
            clauses.append("flight_date = CAST(? AS DATE)")
            params.append(flight_date)
        rows = self._connection.execute(
            f"SELECT {FLIGHT_COLUMNS} FROM flights WHERE {' AND '.join(clauses)} "
            "ORDER BY sched_dep_utc, flight_id",
            params,
        ).fetchall()
        return [_flight_from_row(row) for row in rows]

    def traverse(self, flight: Flight, link: Link) -> list[Flight | Aircraft | Airport | Carrier]:
        """Walk a named link from a flight. The generic entry point the agent tools use."""
        match link:
            case Link.FLOWN_BY:
                return [self.get_aircraft(flight.tail_number)] if flight.tail_number else []
            case Link.OPERATED_BY:
                return [self.get_carrier(flight.carrier)]
            case Link.DEPARTS_FROM:
                return [self.get_airport(flight.origin)]
            case Link.ARRIVES_AT:
                return [self.get_airport(flight.destination)]
            case Link.NEXT_LEG:
                following = self.next_leg(flight.flight_id)
                return [following] if following else []
            case Link.PREVIOUS_LEG:
                preceding = self.previous_leg(flight.flight_id)
                return [preceding] if preceding else []
            case Link.ROTATION:
                if flight.tail_number is None:
                    return []
                return list(self.rotation(flight.tail_number, flight.flight_date))

    def turn_time_estimates(
        self, *, quantile: float, min_ground_minutes: int, min_sample: int
    ) -> tuple[dict[tuple[str, str], int], dict[str, int], int]:
        """Observed turn-time quantiles per carrier-station, per carrier, and network-wide.

        Lives here because the store owns the SQL. The propagation engine consumes the three
        levels and decides the fallback order; it never sees a query.
        """
        per_station = {
            (str(carrier), str(station)): int(minutes)
            for carrier, station, minutes in self._connection.execute(
                """
                SELECT f.carrier, f.destination,
                       CAST(quantile_cont(n.ground_minutes, ?) AS INTEGER)
                FROM next_leg n JOIN flights f ON f.flight_id = n.from_flight_id
                WHERE n.ground_minutes BETWEEN ? AND 480
                GROUP BY 1, 2 HAVING count(*) >= ?
                """,
                [quantile, min_ground_minutes, min_sample],
            ).fetchall()
        }
        per_carrier = {
            str(carrier): int(minutes)
            for carrier, minutes in self._connection.execute(
                """
                SELECT f.carrier, CAST(quantile_cont(n.ground_minutes, ?) AS INTEGER)
                FROM next_leg n JOIN flights f ON f.flight_id = n.from_flight_id
                WHERE n.ground_minutes BETWEEN ? AND 480
                GROUP BY 1
                """,
                [quantile, min_ground_minutes],
            ).fetchall()
        }
        row = self._connection.execute(
            "SELECT CAST(quantile_cont(ground_minutes, ?) AS INTEGER) FROM next_leg "
            "WHERE ground_minutes BETWEEN ? AND 480",
            [quantile, min_ground_minutes],
        ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("no observed turns: cannot estimate minimum turn times")
        return per_station, per_carrier, int(row[0])

    def turn_percentile(self, carrier: str, station: str, quantile: float) -> int | None:
        """Observed ground-time quantile for a carrier at a station, the min_turn input.

        Returns None where the sample is too small to estimate from; the caller decides the
        fallback rather than silently receiving a number derived from three observations.
        """
        row = self._connection.execute(
            """
            SELECT count(*), CAST(quantile_cont(n.ground_minutes, ?) AS INTEGER)
            FROM next_leg n JOIN flights f ON f.flight_id = n.from_flight_id
            WHERE f.carrier = ? AND f.destination = ? AND n.ground_minutes BETWEEN 0 AND 480
            """,
            [quantile, carrier, station],
        ).fetchone()
        if row is None or row[0] < MIN_TURN_SAMPLE:
            return None
        return int(row[1])


MIN_TURN_SAMPLE = 30
"""Below this many observed turns, a per-station estimate is noise; fall back carrier-wide."""
