"""Derive the next_leg rotation chain: the link that makes propagation computable.

Per DESIGN.md section 5, chains are built once at ingest rather than re-derived per query, so
that data-quality failures surface once and countable instead of hiding inside query logic.

Two choices worth stating, because neither is forced by the spec:

Chains are built from the schedule, cancellations included. A cancelled leg still occupies a
slot in the aircraft's planned line of flying, and it is what the controller sees on the board.
Dropping cancelled legs here would manufacture station discontinuities -- the aircraft's next
scheduled departure would appear to come from an airport it never reached -- and would bury a
cancellation's downstream effect inside the link derivation, where the propagation engine and
the cancel_flight action could no longer reason about it.

Links span the whole loaded window, not calendar days. Ordering by scheduled departure UTC per
tail makes the overnight simply the largest ground gap, which is what lets the turn-time
distribution be measured rather than assumed. Where the chain should terminate for propagation
is a threshold chosen at M4 from that distribution, not a decision baked into the links.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from flightops.ingest.sql import scalar


@dataclass(frozen=True)
class RotationResult:
    """Counts from a chain derivation, for the M2 report."""

    linkable_legs: int
    links_created: int
    chain_breaks: dict[str, int]


def derive_next_leg(connection: duckdb.DuckDBPyConnection) -> RotationResult:
    """Build the `next_leg` and `chain_breaks` tables from `flights`.

    A link is created only where the aircraft's next scheduled departure is from the station
    this leg arrives at. Where it is not, no link is created and the break is recorded with a
    reason, because the gap is real: OTP data does not report ferry and positioning moves, so
    the aircraft got there by a flight this dataset cannot see.
    """
    connection.execute(
        """
        CREATE OR REPLACE TABLE rotation_sequence AS
        SELECT
            flight_id, tail_number, carrier, origin, destination,
            sched_dep_utc, sched_arr_utc, status,
            LEAD(flight_id)      OVER w AS next_flight_id,
            LEAD(origin)         OVER w AS next_origin,
            LEAD(sched_dep_utc)  OVER w AS next_sched_dep_utc
        FROM flights
        WHERE tail_number IS NOT NULL
        WINDOW w AS (PARTITION BY tail_number ORDER BY sched_dep_utc, flight_id)
        """
    )

    connection.execute(
        """
        CREATE OR REPLACE TABLE next_leg AS
        SELECT
            flight_id                                                        AS from_flight_id,
            next_flight_id                                                   AS to_flight_id,
            tail_number,
            date_diff('minute', sched_arr_utc, next_sched_dep_utc)           AS ground_minutes
        FROM rotation_sequence
        WHERE next_flight_id IS NOT NULL
          AND next_origin = destination
          AND date_diff('minute', sched_arr_utc, next_sched_dep_utc) >= 0
        """
    )

    connection.execute(
        """
        CREATE OR REPLACE TABLE chain_breaks AS
        SELECT
            flight_id, tail_number, destination AS arrived_at,
            next_origin AS next_departs_from,
            date_diff('minute', sched_arr_utc, next_sched_dep_utc) AS gap_minutes,
            CASE
                WHEN next_flight_id IS NULL THEN 'end_of_window'
                -- The aircraft's next departure is from somewhere it did not fly to. OTP data
                -- carries no ferry or positioning legs, so the move that repositioned it is
                -- invisible here. Recorded, never bridged: inventing the missing leg would be
                -- inventing a flight.
                WHEN next_origin <> destination THEN 'station_discontinuity'
                -- Same tail, same station, but the next leg is scheduled to push back before
                -- this one lands. No aircraft turns in negative time, so the two legs cannot
                -- both belong to this tail as reported: a swap that BTS recorded against the
                -- original schedule, or a tail keying error. Propagating through it would
                -- produce a cascade for an aircraft that was never there.
                ELSE 'impossible_turn'
            END AS reason
        FROM rotation_sequence
        WHERE next_flight_id IS NULL
           OR next_origin <> destination
           OR date_diff('minute', sched_arr_utc, next_sched_dep_utc) < 0
        """
    )

    linkable = scalar(connection, "SELECT count(*) FROM flights WHERE tail_number IS NOT NULL")
    links = scalar(connection, "SELECT count(*) FROM next_leg")
    breaks = {
        str(reason): int(count)
        for reason, count in connection.execute(
            "SELECT reason, count(*) FROM chain_breaks GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    }
    return RotationResult(linkable_legs=linkable, links_created=links, chain_breaks=breaks)
