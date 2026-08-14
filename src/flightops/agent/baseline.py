"""The SQL baseline: same model, same prompt shape, one read-only SELECT tool.

DESIGN.md section 11. The baseline exists to answer the only question that makes the ontology
work interesting: does the typed object layer buy anything a competent analyst with the schema
and a SQL prompt would not get anyway? Building it well is the point, because a baseline tuned to
lose proves nothing, so this one gets the derived rotation tables, the projection formula
written out, and the same row cap and citation rules as the ontology agent.

The one asymmetry is unavoidable and is stated rather than hidden: the ontology agent's
simulate_action calls the same propagation engine the project ships, while the baseline has to
implement the projection in SQL from the formula in its prompt. That gap is not an artefact of
an unfair prompt, it is the thing being measured: whether a shared, tested implementation of
the domain's hard arithmetic beats re-deriving it per question.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from flightops.agent.loop import ToolExecutor
from flightops.agent.tools import MAX_RESULTS, ToolFailure

MAX_ROWS = MAX_RESULTS
"""The same cap the ontology tools use, so neither agent can win on result volume."""

SQL_TOOL_SCHEMA: dict[str, Any] = {
    "name": "run_sql",
    "description": (
        "Execute one read-only SELECT against the flight database and return the rows. Must be "
        "a single statement beginning with SELECT or WITH. Returns at most 40 rows and tells "
        "you when the result was truncated. Aggregate in SQL rather than counting a partial "
        "list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "A single read-only SELECT statement."}
        },
        "required": ["sql"],
    },
}


def _validate(sql: str) -> str:
    """Reject anything that is not a single read-only SELECT.

    The connection is opened read-only, so this is not the security boundary. It is there so
    a rejected query comes back as a sentence the model can act on instead of a DuckDB
    permission error it has to interpret.
    """
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise ToolFailure("run_sql requires a non-empty 'sql' statement")
    if ";" in statement:
        raise ToolFailure("run_sql takes one statement; remove the ';' and send a single query")
    opening = statement.split(None, 1)[0].upper()
    if opening not in ("SELECT", "WITH"):
        raise ToolFailure(
            f"run_sql is read-only and takes a SELECT or WITH query; this one starts with {opening}"
        )
    return statement


class SqlBaseline:
    """A read-only DuckDB connection exposed as the baseline's single tool."""

    def __init__(self, database: Path | str) -> None:
        self._connection = duckdb.connect(str(database), read_only=True)
        self._connection.execute("LOAD icu")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SqlBaseline:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def run_sql(self, sql: str) -> dict[str, Any]:
        statement = _validate(sql)
        try:
            cursor = self._connection.execute(statement)
        except duckdb.Error as failed:
            raise ToolFailure(f"query failed: {failed}") from failed

        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        result: dict[str, Any] = {
            "columns": columns,
            "rows": [
                {column: value for column, value in zip(columns, row, strict=True)}
                for row in rows[:MAX_ROWS]
            ],
            "row_count": min(len(rows), MAX_ROWS),
        }
        if truncated:
            result["truncated"] = (
                f"more than {MAX_ROWS} rows match; aggregate in SQL rather than counting this "
                f"list, which is not the full result"
            )
        return result

    def executor(self) -> ToolExecutor:
        def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if name != "run_sql":
                raise ToolFailure(f"no tool named {name!r}; this agent has run_sql only")
            sql = arguments.get("sql")
            if not isinstance(sql, str):
                raise ToolFailure("run_sql requires 'sql' as a string")
            return self.run_sql(sql)

        return execute
