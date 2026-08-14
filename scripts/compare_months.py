"""Compare two ingested BTS months: operational character, root population, block-time slack.

    python scripts/compare_months.py data/flights_2026_01.duckdb data/flights_2025_07.duckdb

`flightops.propagation.validate` measures one month at a time, cascade shape and the
LateAircraftDelay check, and is the thing that must stay untouched between months if a
replication is to mean anything. This script measures what `validate` deliberately does not: how
different the two months are in the first place, and how many roots each one produces.

That second number matters more than it looks. Cascade *shape* is a property of a root; the
ranking's value is a property of how many roots there are. A month can damp harder and still be
the harder month to work, and the README's July-versus-January reading turns on exactly that.

Nothing here is used by the API or the frontend. It exists so the README's month-comparison
tables are reproducible rather than asserted.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

# Both halves of the root definition in `measure_cascade_shape`, restated in SQL. Keeping them in
# sync by hand is the cost of counting the whole population instead of the replayed sample: the
# engine walks rotations in Python and cannot answer "how many are there" without replaying all of
# them. `delay_carrier IS NOT NULL` is the SQL spelling of `flight.causes is not None`, not an
# arrival-delay threshold restated. tests/test_compare_months.py asserts the two filters select
# the same flights on the committed sample rather than trusting that they read alike.
MIN_ROOT_DELAY = 60
CAUSE_SUM = "(delay_carrier + delay_weather + delay_nas + delay_security + delay_late_aircraft)"
ROOT_FILTER = f"""
    dep_delay_minutes >= {MIN_ROOT_DELAY}
    AND tail_number IS NOT NULL
    AND delay_carrier IS NOT NULL
    AND delay_late_aircraft <= {CAUSE_SUM} / 2.0
"""


@dataclass(frozen=True)
class MonthProfile:
    """One month, described by the numbers that decide whether it is a fair second sample."""

    name: str
    first_date: str
    last_date: str
    days: int
    flights: int
    arrived: int
    cancelled: int
    diverted: int
    carriers: tuple[str, ...]
    late_15: int
    cause_shares: dict[str, float]
    median_block_slack: float
    roots: int

    @property
    def late_share(self) -> float:
        return 100 * self.late_15 / self.arrived if self.arrived else 0.0

    @property
    def cancel_share(self) -> float:
        return 100 * self.cancelled / self.flights if self.flights else 0.0

    @property
    def roots_per_day(self) -> float:
        return self.roots / self.days if self.days else 0.0

    @property
    def roots_per_thousand(self) -> float:
        return 1000 * self.roots / self.arrived if self.arrived else 0.0


def profile(database: Path) -> MonthProfile:
    """Read one month. Read-only, so this can run against a database the API is serving."""
    connection = duckdb.connect(str(database), read_only=True)
    try:
        first, last, days, flights = connection.execute(
            "SELECT min(flight_date), max(flight_date), count(DISTINCT flight_date), count(*) "
            "FROM flights"
        ).fetchone()
        arrived, cancelled, diverted = connection.execute(
            "SELECT count(*) FILTER (WHERE status = 'arrived'), "
            "count(*) FILTER (WHERE status = 'cancelled'), "
            "count(*) FILTER (WHERE status = 'diverted') FROM flights"
        ).fetchone()
        carriers = tuple(
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT carrier FROM flights ORDER BY carrier"
            ).fetchall()
        )
        late_15 = connection.execute(
            "SELECT count(*) FROM flights WHERE status = 'arrived' AND arr_delay_minutes >= 15"
        ).fetchone()[0]

        buckets = connection.execute(
            "SELECT sum(delay_carrier), sum(delay_weather), sum(delay_nas), "
            "sum(delay_security), sum(delay_late_aircraft) "
            "FROM flights WHERE arr_delay_minutes >= 15"
        ).fetchone()
        total = sum(buckets) or 1
        names = ("carrier", "weather", "nas", "security", "late_aircraft")
        shares = {name: 100 * value / total for name, value in zip(names, buckets, strict=True)}

        # Actual minus scheduled block time. The projection adds *scheduled* block to a projected
        # departure, so a negative median here is the size of the systematic over-prediction that
        # introduces, and comparing it across months is what tests the block-time explanation
        # for the engine's positive bias rather than repeating it.
        slack = connection.execute(
            "SELECT median(date_diff('minute', actual_dep_utc, actual_arr_utc) "
            "- sched_block_minutes) FROM flights "
            "WHERE status = 'arrived' AND sched_block_minutes IS NOT NULL"
        ).fetchone()[0]

        roots = connection.execute(f"SELECT count(*) FROM flights WHERE {ROOT_FILTER}").fetchone()[
            0
        ]
    finally:
        connection.close()

    return MonthProfile(
        name=database.stem,
        first_date=str(first),
        last_date=str(last),
        days=days,
        flights=flights,
        arrived=arrived,
        cancelled=cancelled,
        diverted=diverted,
        carriers=carriers,
        late_15=late_15,
        cause_shares=shares,
        median_block_slack=float(slack),
        roots=roots,
    )


def render(left: MonthProfile, right: MonthProfile) -> str:
    """The three README tables, in the order the argument reads."""
    width = max(len(left.name), len(right.name), 34)

    def row(label: str, a: str, b: str) -> str:
        return f"{label:<52} {a:>{width}} {b:>{width}}"

    only_left = sorted(set(left.carriers) - set(right.carriers))
    only_right = sorted(set(right.carriers) - set(left.carriers))

    lines = [
        row("", left.name, right.name),
        row(
            "", f"{left.first_date} to {left.last_date}", f"{right.first_date} to {right.last_date}"
        ),
        "",
        "-- operational character",
        row("flights", f"{left.flights:,}", f"{right.flights:,}"),
        row("reporting carriers", str(len(left.carriers)), str(len(right.carriers))),
        row("arrived 15+ min late", f"{left.late_share:.1f}%", f"{right.late_share:.1f}%"),
        row("cancelled", f"{left.cancel_share:.1f}%", f"{right.cancel_share:.1f}%"),
    ]
    for name in ("carrier", "weather", "nas", "late_aircraft"):
        lines.append(
            row(
                f"delay minutes coded {name}",
                f"{left.cause_shares[name]:.0f}%",
                f"{right.cause_shares[name]:.0f}%",
            )
        )
    if only_left or only_right:
        lines.append(
            row(
                "carriers unique to one month",
                ",".join(only_left) or "-",
                ",".join(only_right) or "-",
            )
        )

    lines += [
        "",
        "-- block-time slack (actual minus scheduled)",
        row(
            "median, minutes",
            f"{left.median_block_slack:+.0f}",
            f"{right.median_block_slack:+.0f}",
        ),
        "",
        "-- root population (same filter as measure_cascade_shape)",
        row("qualifying roots", f"{left.roots:,}", f"{right.roots:,}"),
        row("per day", f"{left.roots_per_day:.0f}", f"{right.roots_per_day:.0f}"),
        row(
            "per 1,000 flights flown",
            f"{left.roots_per_thousand:.1f}",
            f"{right.roots_per_thousand:.1f}",
        ),
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        raise SystemExit(
            "usage: python scripts/compare_months.py <month.duckdb> <other-month.duckdb>\n"
            "build each with: python scripts/fetch_data.py --month YYYY-MM --database <path>"
        )
    databases = [Path(argument) for argument in argv[1:]]
    for database in databases:
        if not database.exists():
            raise SystemExit(f"no database at {database}; run scripts/fetch_data.py first")
    print(render(profile(databases[0]), profile(databases[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
