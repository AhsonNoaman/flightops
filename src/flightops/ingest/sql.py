"""One shared helper for scalar queries, used across the ingest modules."""

from __future__ import annotations

import duckdb


def scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    """Fetch a single integer. Raises rather than returning None, so callers stay typed."""
    row = connection.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(f"expected one row from: {sql}")
    return 0 if row[0] is None else int(row[0])
