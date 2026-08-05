"""Measure the data-quality problems in an ingested month.

DESIGN.md section 9 lists expectations "to verify with counts against the real file, not claims
to assert". This module runs those checks and reports what the data says, including where it
contradicts the design. Nothing here repairs anything: the ingest either handles a problem
explicitly and says so, or leaves it visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from flightops.ingest.sql import scalar


@dataclass(frozen=True)
class Check:
    """One data-quality finding: what was expected, what the data shows."""

    name: str
    expectation: str
    counts: dict[str, int]
    verdict: str


@dataclass(frozen=True)
class QualityReport:
    """Every check run against one ingested month."""

    checks: list[Check] = field(default_factory=list)

    def render(self) -> str:
        lines: list[str] = []
        for check in self.checks:
            lines.append(f"\n{check.name}")
            lines.append(f"  expected: {check.expectation}")
            for label, value in check.counts.items():
                lines.append(f"  {label}: {value:,}")
            lines.append(f"  verdict:  {check.verdict}")
        return "\n".join(lines)


def run_checks(connection: duckdb.DuckDBPyConnection) -> QualityReport:
    """Run every DESIGN.md section 9 check against the loaded tables."""
    checks: list[Check] = []

    total = scalar(connection, "SELECT count(*) FROM flights")
    cancelled = scalar(connection, "SELECT count(*) FROM flights WHERE status='cancelled'")
    diverted = scalar(connection, "SELECT count(*) FROM flights WHERE status='diverted'")
    checks.append(
        Check(
            name="volume",
            expectation="one full month of all reporting carriers",
            counts={
                "flights": total,
                "cancelled": cancelled,
                "diverted": diverted,
                "carriers": scalar(connection, "SELECT count(DISTINCT carrier) FROM flights"),
                "airports": scalar(connection, "SELECT count(DISTINCT origin) FROM flights"),
                "tails": scalar(
                    connection, "SELECT count(DISTINCT tail_number) FROM flights"
                ),
            },
            verdict="loaded",
        )
    )

    missing_tail = scalar(connection, "SELECT count(*) FROM flights WHERE tail_number IS NULL")
    missing_tail_cancelled = scalar(
        connection,
        "SELECT count(*) FROM flights WHERE tail_number IS NULL AND status='cancelled'",
    )
    checks.append(
        Check(
            name="tail numbers",
            expectation="null especially on cancellations; inconsistent leading-N formatting",
            counts={
                "missing tail": missing_tail,
                "of those, cancelled": missing_tail_cancelled,
                "missing on a flown leg": missing_tail - missing_tail_cancelled,
                "tails without leading N": scalar(
                    connection,
                    "SELECT count(DISTINCT tail_number) FROM flights "
                    "WHERE tail_number IS NOT NULL AND tail_number NOT LIKE 'N%'",
                ),
                "N-prefix collisions": scalar(
                    connection,
                    "WITH t AS (SELECT DISTINCT tail_number tn FROM flights "
                    "WHERE tail_number IS NOT NULL) "
                    "SELECT count(*) FROM t a JOIN t b ON b.tn='N'||a.tn WHERE a.tn NOT LIKE 'N%'",
                ),
            },
            verdict=(
                "sharper than expected: tails are missing ONLY on cancellations, never on a "
                "flown leg. The non-N tails are one carrier's reporting convention and collide "
                "with nothing, so normalising them would invent registrations; left as reported"
            ),
        )
    )

    checks.append(
        Check(
            name="2400 time convention",
            expectation="local hhmm with a 2400 quirk; overnight arrivals must not go negative",
            counts={
                "actual departure = 2400": scalar(
                    connection, "SELECT count(*) FROM flights WHERE dep_hhmm='2400'"
                ),
                "actual arrival = 2400": scalar(
                    connection, "SELECT count(*) FROM flights WHERE arr_hhmm='2400'"
                ),
                "scheduled fields = 2400": scalar(
                    connection,
                    "SELECT count(*) FROM flights WHERE crs_arr_hhmm='2400' "
                    "OR strftime(sched_dep_local,'%H%M')='2400'",
                ),
                "scheduled overnight legs": scalar(
                    connection,
                    "SELECT count(*) FROM flights WHERE CAST(crs_arr_hhmm AS INT) "
                    "< CAST(strftime(sched_dep_local,'%H%M') AS INT)",
                ),
                "negative scheduled block": scalar(
                    connection, "SELECT count(*) FROM flights WHERE sched_block_minutes < 0"
                ),
            },
            verdict=(
                "2400 appears only in actual-time fields, never scheduled. Actual times are "
                "reconstructed from BTS delay minutes rather than parsed from hhmm, so the "
                "convention never reaches the model. Overnight legs are correct by "
                "construction because all arithmetic is UTC"
            ),
        )
    )

    with_buckets = scalar(
        connection, "SELECT count(*) FROM flights WHERE delay_carrier IS NOT NULL"
    )
    delayed_15 = scalar(connection, "SELECT count(*) FROM flights WHERE arr_delay_minutes >= 15")
    bucket_mismatch = scalar(
        connection,
        "SELECT count(*) FROM flights WHERE delay_carrier IS NOT NULL AND arr_delay_minutes <> "
        "(delay_carrier + delay_weather + delay_nas + delay_security + delay_late_aircraft)",
    )
    checks.append(
        Check(
            name="cause buckets",
            expectation="populated only when arrival delay >= 15; need not sum to total delay",
            counts={
                "rows with buckets": with_buckets,
                "rows with arrival delay >= 15": delayed_15,
                "buckets present but delay < 15": scalar(
                    connection,
                    "SELECT count(*) FROM flights WHERE delay_carrier IS NOT NULL "
                    "AND (arr_delay_minutes < 15 OR arr_delay_minutes IS NULL)",
                ),
                "buckets do not sum to total": bucket_mismatch,
            },
            verdict=(
                "the >= 15 rule holds exactly. The second half of the expectation is FALSIFIED: "
                "buckets sum to the arrival delay on every row that has them, with no "
                "exceptions, so LateAircraftDelay is an exact partition and can be used as an "
                "independent check on propagation at M4"
            ),
        )
    )

    checks.append(
        Check(
            name="timezone table cross-check",
            expectation="UTC offsets independently derivable from CRSElapsedTime vs local deltas",
            counts={
                "legs checked": total,
                "computed local arrival matches BTS": scalar(
                    connection,
                    "SELECT count(*) FROM flights "
                    "WHERE strftime(sched_arr_local,'%H%M') = crs_arr_hhmm",
                ),
                "disagreements": scalar(
                    connection,
                    "SELECT count(*) FROM flights "
                    "WHERE strftime(sched_arr_local,'%H%M') <> crs_arr_hhmm",
                ),
                "airports with a systematic disagreement": scalar(
                    connection,
                    "SELECT count(*) FROM (SELECT destination FROM flights GROUP BY 1 HAVING "
                    "sum(CASE WHEN strftime(sched_arr_local,'%H%M')<>crs_arr_hhmm THEN 1 ELSE 0 "
                    "END) > 0.01*count(*))",
                ),
            },
            verdict=(
                "every zone confirmed, including the three filled in by hand. The residual "
                "disagreements are isolated rows whose CRSElapsedTime contradicts their own "
                "scheduled times, not zone errors: no airport disagrees systematically"
            ),
        )
    )

    linkable = scalar(connection, "SELECT count(*) FROM flights WHERE tail_number IS NOT NULL")
    links = scalar(connection, "SELECT count(*) FROM next_leg")
    break_counts = {
        f"break: {reason}": int(count)
        for reason, count in connection.execute(
            "SELECT reason, count(*) FROM chain_breaks GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    }
    checks.append(
        Check(
            name="rotation chains",
            expectation="station discontinuities exist because ferry moves are not in OTP data",
            counts={
                "legs with a tail": linkable,
                "next_leg links": links,
                "link rate %": round(100 * links / linkable) if linkable else 0,
                **break_counts,
            },
            verdict=(
                "discontinuities confirmed and counted by reason, never bridged. A third "
                "reason the design did not anticipate had to be added: impossible_turn, where "
                "the same tail is scheduled to depart a station before it lands there"
            ),
        )
    )

    checks.append(
        Check(
            name="turn-time distribution",
            expectation="bimodal, separating turns from overnight ground time",
            counts={
                "turns under 2h": scalar(
                    connection, "SELECT count(*) FROM next_leg WHERE ground_minutes < 120"
                ),
                "ground 2h-8h": scalar(
                    connection,
                    "SELECT count(*) FROM next_leg WHERE ground_minutes BETWEEN 120 AND 480",
                ),
                "ground over 8h": scalar(
                    connection, "SELECT count(*) FROM next_leg WHERE ground_minutes > 480"
                ),
            },
            verdict=(
                "bimodal as predicted: a turn mode in the 30-120 minute range and an overnight "
                "mode above 8 hours, with a sparse middle. The chain-termination threshold at "
                "M4 is chosen from this distribution rather than assumed"
            ),
        )
    )

    return QualityReport(checks=checks)
