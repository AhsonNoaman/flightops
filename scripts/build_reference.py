"""Regenerate the committed reference tables under src/flightops/reference/.

Reference data, not a second operational source: static, small, committed, and used only to
give airports a timezone and carriers a name. DESIGN.md section 4 requires the timezone table
to carry provenance in-file, because it is load-bearing. BTS reports local times and rotation
ordering across timezones is wrong without it.

Run:  python scripts/build_reference.py data/raw/bts_2026_01.csv
"""

from __future__ import annotations

import csv
import sys
import urllib.request
from pathlib import Path

OPENFLIGHTS_AIRPORTS = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
)

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "src" / "flightops" / "reference"

# Airports flown in the ingested month that OpenFlights does not carry an IANA zone for.
# Each is a small US field with an unambiguous zone; every one is independently confirmed by
# the CRSElapsedTime cross-check in flightops.ingest.timezones, which is why they are safe to
# state here rather than drop.
MANUAL_ZONES: dict[str, tuple[str, str]] = {
    "BIH": ("America/Los_Angeles", "Bishop, CA"),
    "EAR": ("America/Chicago", "Kearney, NE"),
    "XWA": ("America/Chicago", "Williston, ND"),
}

# DOT-assigned reporting carrier names. Transcribed rather than fetched: the BTS lookup
# endpoint (Download_Lookup.asp?Y11x72=Y_UNIQUE_CARRIERS) returned HTTP 500 on 2026-08-05, and
# the readme.html shipped inside the monthly zip carries the record layout but no carrier table.
# build_reference.py fails loudly on a code missing from this map rather than emitting a blank
# name, so a new reporting carrier in a future month surfaces as an error instead of a hole.
DOT_CARRIER_NAMES: dict[str, str] = {
    "AA": "American Airlines Inc.",
    "AS": "Alaska Airlines Inc.",
    "B6": "JetBlue Airways",
    "DL": "Delta Air Lines Inc.",
    "F9": "Frontier Airlines Inc.",
    "G4": "Allegiant Air",
    "HA": "Hawaiian Airlines Inc.",
    "MQ": "Envoy Air",
    "NK": "Spirit Air Lines",
    "OH": "PSA Airlines Inc.",
    "OO": "SkyWest Airlines Inc.",
    "QX": "Horizon Air",
    "UA": "United Air Lines Inc.",
    "WN": "Southwest Airlines Co.",
    "YV": "Mesa Airlines Inc.",
    "YX": "Republic Airline",
    "9E": "Endeavor Air Inc.",
}

AIRPORTS_PROVENANCE = """\
# Airport timezone reference.
#
# Source: OpenFlights airports.dat (https://github.com/jpatokal/openflights), IATA code and
#   "Tz database time zone" columns, retrieved {date}.
# Scope: only the airports appearing as an origin or destination in the ingested BTS month.
# Manual entries: BIH, EAR, XWA are absent from OpenFlights; their zones are stated in
#   scripts/build_reference.py with justification.
# Validation: every row is cross-checked against the offset implied by CRSElapsedTime versus
#   local-time deltas per city pair (flightops.ingest.timezones). That derivation is a check,
#   not the source, because it is fragile around DST transitions and the 2400 convention.
"""

CARRIERS_PROVENANCE = """\
# Reporting carrier reference.
#
# Source: DOT-assigned carrier names, transcribed. The BTS lookup endpoint returned HTTP 500
#   on 2026-08-05 and the monthly zip's readme.html carries no carrier table.
# Note: Reporting_Airline is the *operating* entity. Regionals (OO SkyWest, YX Republic,
#   MQ Envoy, OH PSA) report separately from the mainline brand whose flights they fly, so a
#   passenger's "American" itinerary can appear here under MQ or OH. The marketing-versus-
#   operating split is a named limitation, not something this table resolves.
"""


def read_openflights_zones() -> dict[str, tuple[str, str]]:
    """Map IATA code -> (IANA zone, city) for every airport OpenFlights gives a zone for."""
    with urllib.request.urlopen(OPENFLIGHTS_AIRPORTS, timeout=60) as response:
        text = response.read().decode("utf-8")
    zones: dict[str, tuple[str, str]] = {}
    for row in csv.reader(text.splitlines()):
        if len(row) < 12:
            continue
        iata, city, zone = row[4].strip(), row[2].strip(), row[11].strip()
        if iata and iata != r"\N" and zone and zone != r"\N":
            zones[iata] = (zone, city)
    return zones


def codes_in_month(csv_path: Path) -> tuple[list[str], list[str]]:
    """Distinct airport codes and reporting carriers actually present in the month."""
    import duckdb

    connection = duckdb.connect()
    # DuckDB cannot bind a prepared parameter inside CREATE VIEW, so the path is escaped and
    # inlined. csv_path comes from argv, not from the data.
    escaped = str(csv_path).replace("'", "''")
    connection.execute(
        f"CREATE VIEW r AS SELECT * FROM "
        f"read_csv('{escaped}', header=true, sample_size=-1, all_varchar=true)"
    )
    airports = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT Origin FROM r UNION SELECT DISTINCT Dest FROM r ORDER BY 1"
        ).fetchall()
    ]
    carriers = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT Reporting_Airline FROM r ORDER BY 1"
        ).fetchall()
    ]
    return airports, carriers


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    source_csv = Path(sys.argv[1])
    if not source_csv.exists():
        print(f"no such file: {source_csv}", file=sys.stderr)
        return 1

    from datetime import date

    airports, carriers = codes_in_month(source_csv)
    openflights = read_openflights_zones()

    unresolved = [a for a in airports if a not in openflights and a not in MANUAL_ZONES]
    if unresolved:
        print(
            f"no timezone for {len(unresolved)} airports: {unresolved}\n"
            "Add them to MANUAL_ZONES with a justification, or the ingest cannot order their "
            "rotations correctly.",
            file=sys.stderr,
        )
        return 1

    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    airports_path = REFERENCE_DIR / "airports.csv"
    with airports_path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(AIRPORTS_PROVENANCE.format(date=date.today().isoformat()))
        writer = csv.writer(handle)
        writer.writerow(["iata", "city", "iana_timezone", "source"])
        for code in airports:
            if code in MANUAL_ZONES:
                zone, city = MANUAL_ZONES[code]
                writer.writerow([code, city, zone, "manual"])
            else:
                zone, city = openflights[code]
                writer.writerow([code, city, zone, "openflights"])

    missing_names = [c for c in carriers if c not in DOT_CARRIER_NAMES]
    if missing_names:
        print(
            f"no name for reporting carriers {missing_names}. Add them to DOT_CARRIER_NAMES.",
            file=sys.stderr,
        )
        return 1

    carriers_path = REFERENCE_DIR / "carriers.csv"
    with carriers_path.open("w", newline="", encoding="utf-8") as handle:
        handle.write(CARRIERS_PROVENANCE)
        writer = csv.writer(handle)
        writer.writerow(["code", "name"])
        for code in carriers:
            writer.writerow([code, DOT_CARRIER_NAMES[code]])

    print(f"wrote {airports_path} ({len(airports)} airports)")
    print(f"wrote {carriers_path} ({len(carriers)} carriers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
