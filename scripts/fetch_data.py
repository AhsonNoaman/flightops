"""Download a BTS On-Time Performance month, load it, derive rotations, report data quality.

    python scripts/fetch_data.py --month 2026-01
    python scripts/fetch_data.py --month 2026-01 --sample     # rebuild the committed sample

The full month is gitignored and rebuilt on demand. The sample (DESIGN.md section 12: Southwest,
one week) is committed so tests and a fresh clone work with no download, and is produced by this
same code path so it cannot drift from the real ingest.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from flightops.ingest.loader import connect, load_month, load_reference  # noqa: E402
from flightops.ingest.quality import run_checks  # noqa: E402
from flightops.ingest.rotation import derive_next_leg  # noqa: E402

PREZIP = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# DESIGN.md section 12: Southwest, one week of the ingested month. Single fleet type, so the
# fleet-compatibility caveat is moot inside the sample; no regional operators, so no
# marketing-versus-operating ambiguity; high-frequency point-to-point rotations with tight
# turns, which makes cascades dense and legible.
SAMPLE_CARRIER = "WN"
SAMPLE_DAYS = 7
SAMPLE_CSV = REPO_ROOT / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"


def extract_sample(csv_path: Path, destination: Path) -> Path:
    """Write the committed sample: the sample carrier's first week, in the original BTS columns.

    Kept in the source schema and gzipped rather than trimmed to the columns the model uses, so
    that load_month parses it by exactly the same code path as the full month. A slimmed sample
    would be smaller and would quietly stop exercising the parser.
    """
    import duckdb

    destination.parent.mkdir(parents=True, exist_ok=True)
    source = str(csv_path).replace("'", "''")
    connection = duckdb.connect()
    first_day = connection.execute(
        f"SELECT min(CAST(FlightDate AS DATE)) FROM read_csv('{source}', header=true, "
        "sample_size=-1, all_varchar=true)"
    ).fetchone()[0]
    last_day = first_day.fromordinal(first_day.toordinal() + SAMPLE_DAYS - 1)
    target = str(destination).replace("'", "''")
    connection.execute(
        f"""
        COPY (
            SELECT * FROM read_csv('{source}', header=true, sample_size=-1, all_varchar=true)
            WHERE Reporting_Airline = '{SAMPLE_CARRIER}'
              AND CAST(FlightDate AS DATE) BETWEEN DATE '{first_day}' AND DATE '{last_day}'
        ) TO '{target}' (HEADER, DELIMITER ',', COMPRESSION gzip)
        """
    )
    connection.close()
    print(
        f"sample: {SAMPLE_CARRIER} {first_day} to {last_day} -> {destination.name} "
        f"({destination.stat().st_size / 1e6:.2f} MB)"
    )
    return destination


def download(year: int, month: int, destination: Path) -> Path:
    """Fetch the monthly zip unless it is already on disk, and return the extracted CSV."""
    destination.mkdir(parents=True, exist_ok=True)
    csv_path = destination / f"bts_{year}_{month:02d}.csv"
    if csv_path.exists():
        print(f"using cached {csv_path}")
        return csv_path

    zip_path = destination / f"bts_{year}_{month:02d}.zip"
    if not zip_path.exists():
        url = PREZIP.format(year=year, month=month)
        print(f"downloading {url}")
        with urllib.request.urlopen(url, timeout=600) as response:
            payload = response.read()
        if not payload.startswith(b"PK"):
            raise RuntimeError(
                f"{url} did not return a zip ({len(payload)} bytes). BTS serves an HTML error "
                "page with HTTP 200 when a month is unavailable."
            )
        zip_path.write_bytes(payload)

    with zipfile.ZipFile(zip_path) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
        with archive.open(name) as source, csv_path.open("wb") as target:
            while chunk := source.read(1 << 20):
                target.write(chunk)
    print(f"extracted {csv_path} ({csv_path.stat().st_size / 1e6:.0f} MB)")
    return csv_path


def build(csv_path: Path, database: Path, *, sample: bool) -> None:
    """Load, derive rotation links, and print the data-quality report."""
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        database.unlink()

    if sample:
        csv_path = extract_sample(csv_path, SAMPLE_CSV)

    connection = connect(database)
    load_reference(connection)
    result = load_month(connection, csv_path)

    print(
        f"rows: raw={result.raw_rows:,} loaded={result.loaded_rows:,} "
        f"dropped={result.dropped_rows:,}"
    )
    rotation = derive_next_leg(connection)
    print(
        f"rotation: {rotation.links_created:,} links from {rotation.linkable_legs:,} legs "
        f"with a tail; breaks {rotation.chain_breaks}"
    )
    print(run_checks(connection).render())
    connection.close()
    print(f"\nwrote {database} ({database.stat().st_size / 1e6:.0f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="YYYY-MM, e.g. 2026-01")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="build the committed one-carrier, one-week sample instead of the full month",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help=(
            "where to write the month; default data/flights.duckdb. Needed to hold two months "
            "side by side, which is how the cascade-shape findings get replicated across seasons "
            "instead of asserted from a single January."
        ),
    )
    args = parser.parse_args()

    year, month = (int(part) for part in args.month.split("-"))
    csv_path = download(year, month, REPO_ROOT / "data" / "raw")
    if args.sample:
        database = REPO_ROOT / "data" / "sample" / "sample.duckdb"
    else:
        database = args.database or REPO_ROOT / "data" / "flights.duckdb"
    build(csv_path, database, sample=args.sample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
