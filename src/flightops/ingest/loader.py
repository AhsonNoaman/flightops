"""Load a BTS On-Time Performance month into DuckDB as typed flight legs.

Two decisions shape this module, both documented in DECISIONS.md:

Actual times are reconstructed from BTS's own delay minutes, not parsed from the hhmm fields.
BTS reports DepTime/ArrTime as local hhmm with no date, which makes midnight rollover and the
2400 convention a reconstruction problem. DepDelay and ArrDelay are signed minute offsets from
the scheduled times, so `actual = scheduled + delay` is exact and date-free. The hhmm fields are
still parsed, but only to cross-check the reconstruction and to count the 2400 quirk.

Scheduled arrival is computed as departure plus CRSElapsedTime, not parsed from CRSArrTime.
That makes CRSArrTime a free, independent check on the timezone table: if the computed local
arrival disagrees with the reported one, either the zone is wrong or the row is. This is the
cross-check DESIGN.md section 4 requires, and it runs on every row rather than a sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from flightops.ingest.sql import scalar

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "reference"

CAUSE_BUCKETS = ("carrier", "weather", "nas", "security", "late_aircraft")


@dataclass(frozen=True)
class LoadResult:
    """Row counts from a load, for the M2 report."""

    raw_rows: int
    loaded_rows: int
    dropped_rows: int


def _sql_literal(path: Path) -> str:
    return str(path).replace("'", "''")


def connect(database: Path) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB database with the ICU extension loaded for timezone arithmetic."""
    connection = duckdb.connect(str(database))
    connection.execute("INSTALL icu")
    connection.execute("LOAD icu")
    return connection


def _read_reference_csv(path: Path) -> list[tuple[str, ...]]:
    """Read a committed reference CSV, skipping its leading '#' provenance block.

    Parsed in Python rather than by read_csv: the provenance block contains quote characters
    that defeat DuckDB's dialect sniffer, and these tables are a few hundred rows, so there is
    nothing to gain from pushing the parse into the engine.
    """
    import csv

    with path.open(encoding="utf-8") as handle:
        body = [line for line in handle if not line.startswith("#")]
    rows = list(csv.reader(body))
    return [tuple(row) for row in rows[1:] if row]


def load_reference(connection: duckdb.DuckDBPyConnection) -> None:
    """Load the committed airport and carrier reference tables."""
    connection.execute(
        "CREATE OR REPLACE TABLE airports "
        "(iata VARCHAR, city VARCHAR, iana_timezone VARCHAR, source VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO airports VALUES (?, ?, ?, ?)",
        _read_reference_csv(REFERENCE_DIR / "airports.csv"),
    )
    connection.execute("CREATE OR REPLACE TABLE carriers (code VARCHAR, name VARCHAR)")
    connection.executemany(
        "INSERT INTO carriers VALUES (?, ?)",
        _read_reference_csv(REFERENCE_DIR / "carriers.csv"),
    )


def load_month(
    connection: duckdb.DuckDBPyConnection,
    csv_path: Path,
    *,
    carrier: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> LoadResult:
    """Parse one BTS monthly CSV into the `flights` table.

    `carrier`, `date_from` and `date_to` restrict the load; they exist so the committed sample
    (DESIGN.md section 12) is produced by the same code path as the full month, rather than by
    a separate script that could drift from it.
    """
    source = _sql_literal(csv_path)
    filters = ["TRUE"]
    if carrier is not None:
        filters.append(f"Reporting_Airline = '{carrier.replace(chr(39), chr(39) * 2)}'")
    if date_from is not None:
        filters.append(f"CAST(FlightDate AS DATE) >= DATE '{date_from}'")
    if date_to is not None:
        filters.append(f"CAST(FlightDate AS DATE) <= DATE '{date_to}'")
    where = " AND ".join(filters)

    connection.execute(
        f"""
        CREATE OR REPLACE TABLE raw_flights AS
        SELECT * FROM read_csv('{source}', header=true, sample_size=-1, all_varchar=true)
        WHERE {where}
        """
    )
    raw_rows = scalar(connection, "SELECT count(*) FROM raw_flights")

    connection.execute(
        """
        CREATE OR REPLACE TABLE flights AS
        WITH typed AS (
            SELECT
                CAST(FlightDate AS DATE)                          AS flight_date,
                Reporting_Airline                                 AS carrier,
                Flight_Number_Reporting_Airline                   AS flight_number,
                Origin                                            AS origin,
                Dest                                              AS destination,
                NULLIF(TRIM(Tail_Number), '')                     AS tail_number,
                TRY_CAST(Cancelled AS DOUBLE) = 1                 AS is_cancelled,
                TRY_CAST(Diverted  AS DOUBLE) = 1                 AS is_diverted,
                NULLIF(TRIM(CancellationCode), '')                AS cancellation_code,
                LPAD(TRIM(CRSDepTime), 4, '0')                    AS crs_dep_hhmm,
                LPAD(TRIM(CRSArrTime), 4, '0')                    AS crs_arr_hhmm,
                NULLIF(LPAD(TRIM(DepTime), 4, '0'), '0000')       AS dep_hhmm,
                NULLIF(LPAD(TRIM(ArrTime), 4, '0'), '0000')       AS arr_hhmm,
                TRY_CAST(DepDelay AS DOUBLE)                      AS dep_delay_minutes,
                TRY_CAST(ArrDelay AS DOUBLE)                      AS arr_delay_minutes,
                TRY_CAST(CRSElapsedTime AS DOUBLE)                AS sched_block_minutes,
                TRY_CAST(Distance AS DOUBLE)                      AS distance_miles,
                TRY_CAST(CarrierDelay AS DOUBLE)                  AS delay_carrier,
                TRY_CAST(WeatherDelay AS DOUBLE)                  AS delay_weather,
                TRY_CAST(NASDelay AS DOUBLE)                      AS delay_nas,
                TRY_CAST(SecurityDelay AS DOUBLE)                 AS delay_security,
                TRY_CAST(LateAircraftDelay AS DOUBLE)             AS delay_late_aircraft
            FROM raw_flights
        ),
        localized AS (
            SELECT
                t.*,
                o.iana_timezone AS origin_tz,
                d.iana_timezone AS dest_tz,
                t.flight_date
                    + INTERVAL 1 HOUR   * CAST(SUBSTR(t.crs_dep_hhmm, 1, 2) AS INTEGER)
                    + INTERVAL 1 MINUTE * CAST(SUBSTR(t.crs_dep_hhmm, 3, 2) AS INTEGER)
                    AS sched_dep_local
            FROM typed t
            LEFT JOIN airports o ON o.iata = t.origin
            LEFT JOIN airports d ON d.iata = t.destination
        ),
        utc AS (
            SELECT
                l.*,
                timezone(l.origin_tz, l.sched_dep_local) AS sched_dep_utc
            FROM localized l
        ),
        arrivals AS (
            SELECT
                u.*,
                u.sched_dep_utc + INTERVAL 1 MINUTE * u.sched_block_minutes AS sched_arr_utc
            FROM utc u
        )
        SELECT
            -- Destination is part of the key. DESIGN.md section 4 keyed on
            -- (date, carrier, flight number, origin, scheduled departure); January 2026 contains
            -- one violation of that key -- F9 3237 out of JFK at 0659 on 2026-01-04, filed twice
            -- with different destinations, both cancelled -- so destination is included.
            flight_date::VARCHAR || '|' || carrier || '|' || flight_number || '|'
                || origin || '|' || destination || '|' || crs_dep_hhmm      AS flight_id,
            flight_date, carrier, flight_number, origin, destination, tail_number,
            CASE
                WHEN is_cancelled THEN 'cancelled'
                WHEN is_diverted  THEN 'diverted'
                WHEN arr_hhmm IS NOT NULL THEN 'arrived'
                WHEN dep_hhmm IS NOT NULL THEN 'departed'
                ELSE 'scheduled'
            END                                                              AS status,
            cancellation_code,
            origin_tz, dest_tz,
            sched_dep_local,
            timezone(dest_tz, sched_arr_utc)                                 AS sched_arr_local,
            sched_dep_utc,
            sched_arr_utc,
            CASE WHEN dep_hhmm IS NOT NULL AND dep_delay_minutes IS NOT NULL
                 THEN sched_dep_utc + INTERVAL 1 MINUTE * dep_delay_minutes END
                                                                             AS actual_dep_utc,
            CASE WHEN arr_hhmm IS NOT NULL AND arr_delay_minutes IS NOT NULL AND NOT is_diverted
                 THEN sched_arr_utc + INTERVAL 1 MINUTE * arr_delay_minutes END
                                                                             AS actual_arr_utc,
            CAST(dep_delay_minutes   AS INTEGER)                             AS dep_delay_minutes,
            CAST(arr_delay_minutes   AS INTEGER)                             AS arr_delay_minutes,
            CAST(sched_block_minutes AS INTEGER)                             AS sched_block_minutes,
            CAST(distance_miles      AS INTEGER)                             AS distance_miles,
            CAST(delay_carrier       AS INTEGER)                             AS delay_carrier,
            CAST(delay_weather       AS INTEGER)                             AS delay_weather,
            CAST(delay_nas           AS INTEGER)                             AS delay_nas,
            CAST(delay_security      AS INTEGER)                             AS delay_security,
            CAST(delay_late_aircraft AS INTEGER)                             AS delay_late_aircraft,
            -- Retained for the quality report only: these are what the reconstruction is
            -- checked against, and where the 2400 convention actually appears.
            crs_arr_hhmm, dep_hhmm, arr_hhmm
        FROM arrivals
        WHERE origin_tz IS NOT NULL
          AND dest_tz   IS NOT NULL
          AND sched_block_minutes IS NOT NULL
        """
    )
    loaded_rows = scalar(connection, "SELECT count(*) FROM flights")
    return LoadResult(
        raw_rows=raw_rows, loaded_rows=loaded_rows, dropped_rows=raw_rows - loaded_rows
    )
