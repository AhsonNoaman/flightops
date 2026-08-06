"""Build the committed sample into a queryable database, offline.

    python -m flightops.ingest.sample [destination.duckdb] [source.csv.gz]

The full month is downloaded and gitignored; the sample is a committed CSV. Everything that runs
without network access -- the test suite, the eval, and the container image, which bakes the
database in read-only at build time -- needs the same one-line way to turn that CSV into a
DuckDB file. Having one avoids the usual failure where the image and the tests are built by two
slightly different code paths and diverge on a Friday.
"""

from __future__ import annotations

import sys
from pathlib import Path

from flightops.ingest.loader import connect, load_month, load_reference
from flightops.ingest.rotation import derive_next_leg

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_CSV = REPO_ROOT / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"
SAMPLE_DB = REPO_ROOT / "data" / "sample" / "sample.duckdb"


def build_sample_database(
    destination: Path = SAMPLE_DB, source: Path = SAMPLE_CSV, *, force: bool = False
) -> Path:
    """Load the sample CSV and derive its rotation links. Idempotent unless `force`."""
    if destination.exists() and not force:
        return destination
    if not source.exists():
        raise FileNotFoundError(f"missing sample CSV at {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    connection = connect(destination)
    load_reference(connection)
    load_month(connection, source)
    derive_next_leg(connection)
    connection.close()
    return destination


def main(argv: list[str]) -> int:
    """Both paths are arguments because the defaults are repo-relative.

    Installed into a container's site-packages, `parents[3]` is not the repository, so the
    image build passes both explicitly rather than relying on a path that only resolves in a
    checkout.
    """
    destination = Path(argv[1]) if len(argv) > 1 else SAMPLE_DB
    source = Path(argv[2]) if len(argv) > 2 else SAMPLE_CSV
    built = build_sample_database(destination, source, force=True)
    print(f"built {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
