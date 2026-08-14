"""Agent tests: the tools tell the truth, the rejections are useful, the transcripts still hold.

DESIGN.md section 11 wants pytest to run offline and deterministically, so nothing here calls
the API. Three kinds of test:

Tool behaviour, against the committed sample. These are the tests that matter most, because the
tools are the whole claim: if find_objects silently truncates or simulate_action returns a diff
that does not match the engine, the eval measures nothing.

Grader self-consistency. Every hand-verified reference answer is run through its own grader. A
check that its own correct answer cannot pass is a broken check, and that is a bug worth
catching before it costs a live run.

Transcript replay. Every committed transcript has its recorded tool calls re-executed against a
freshly built store, and the results compared. This does not test the model, whose turns
are frozen. It tests that a change to propagation, actions, or the store has not changed what
the model would have seen, which is the regression that would quietly invalidate a published
score.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from flightops.agent import baseline, evalset, loop, prompts
from flightops.agent.tools import MAX_RESULTS, ToolContext, ToolFailure, dispatch
from flightops.ingest.loader import connect, load_month, load_reference
from flightops.ingest.rotation import derive_next_leg
from flightops.model.store import ObjectStore

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CSV = REPO_ROOT / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"
TRANSCRIPTS = REPO_ROOT / "data" / "transcripts"

ROOT = evalset.ROOT
IMPOSSIBLE_TURN = "2026-01-07|WN|1016|BWI|RSW|1430"


@pytest.fixture(scope="session")
def database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("agent") / "sample.duckdb"
    connection = connect(path)
    load_reference(connection)
    load_month(connection, SAMPLE_CSV)
    derive_next_leg(connection)
    connection.close()
    return path


@pytest.fixture(scope="session")
def store(database: Path) -> Iterator[ObjectStore]:
    with ObjectStore(database) as opened:
        yield opened


@pytest.fixture
def context(store: ObjectStore) -> ToolContext:
    """A fresh context per test: scenarios are per-conversation and must not leak between them."""
    return ToolContext.open(store)


# -- find_objects ---------------------------------------------------------------------------------


def test_find_objects_returns_the_id_and_the_causes(context: ToolContext) -> None:
    result = dispatch(context, "find_objects", {"object_type": "flight", "flight_id": ROOT})
    flight = result["results"][0]
    assert flight["flight_id"] == ROOT
    assert flight["dep_delay_minutes"] == 142
    assert flight["delay_causes_minutes"]["nas"] == 141


def test_find_objects_reports_truncation_rather_than_silently_capping(
    context: ToolContext,
) -> None:
    """The failure mode this guards is an answer counted off a list the model thought was whole."""
    result = dispatch(context, "find_objects", {"object_type": "flight", "carrier": "WN"})
    assert result["count"] == MAX_RESULTS
    assert "truncated" in result
    assert "not the full set" in result["truncated"]


def test_find_objects_caps_a_larger_requested_limit(context: ToolContext) -> None:
    result = dispatch(
        context, "find_objects", {"object_type": "flight", "carrier": "WN", "limit": 500}
    )
    assert result["count"] == MAX_RESULTS


def test_find_objects_rejects_an_unknown_status_by_listing_the_real_ones(
    context: ToolContext,
) -> None:
    with pytest.raises(ToolFailure) as rejected:
        dispatch(context, "find_objects", {"object_type": "flight", "status": "delayed"})
    assert "cancelled" in str(rejected.value)


def test_find_objects_rejects_a_missing_flight_by_naming_it(context: ToolContext) -> None:
    with pytest.raises(ToolFailure) as rejected:
        dispatch(context, "find_objects", {"object_type": "flight", "flight_id": "nope"})
    assert "nope" in str(rejected.value)


# -- traverse_links -------------------------------------------------------------------------------


def test_next_leg_carries_the_ground_time(context: ToolContext) -> None:
    result = dispatch(context, "traverse_links", {"flight_id": ROOT, "link": "next_leg"})
    assert result["results"][0]["flight_id"] == "2026-01-03|WN|4106|SFO|PHX|1055"
    assert result["ground_minutes"] == 50


def test_a_broken_chain_returns_the_recorded_reason_not_an_empty_list(
    context: ToolContext,
) -> None:
    result = dispatch(context, "traverse_links", {"flight_id": IMPOSSIBLE_TURN, "link": "next_leg"})
    assert result["count"] == 0
    assert result["chain_break_reason"] == "impossible_turn"


def test_rotation_returns_the_whole_day_in_order(context: ToolContext) -> None:
    result = dispatch(context, "traverse_links", {"flight_id": ROOT, "link": "rotation"})
    assert result["count"] == 7
    assert result["results"][0]["origin"] == "MSY"
    assert result["results"][-1]["destination"] == "HOU"


def test_traverse_rejects_an_unknown_link_by_listing_the_ontology(context: ToolContext) -> None:
    with pytest.raises(ToolFailure) as rejected:
        dispatch(context, "traverse_links", {"flight_id": ROOT, "link": "downstream"})
    assert "next_leg" in str(rejected.value)


# -- simulate_action ------------------------------------------------------------------------------


def test_delay_projects_the_verified_cascade(context: ToolContext) -> None:
    result = dispatch(
        context,
        "simulate_action",
        {
            "action": "delay_flight",
            "flight_id": ROOT,
            "additional_minutes": 142,
            "reason": "nas",
        },
    )
    assert result["net_system_minutes"] == 565
    assert len(result["legs"]) == 6  # the target plus five downstream
    assert result["legs"][-1]["flight_id"] == evalset.LAST_LEG


def test_a_small_delay_is_absorbed_by_scheduled_ground_time(context: ToolContext) -> None:
    result = dispatch(
        context,
        "simulate_action",
        {"action": "delay_flight", "flight_id": ROOT, "additional_minutes": 20, "reason": "test"},
    )
    assert result["net_system_minutes"] == 5
    assert len(result["legs"]) == 2


def test_actions_in_one_scenario_compose_and_in_separate_scenarios_do_not(
    context: ToolContext,
) -> None:
    """The property the scenario_id argument exists for.

    A swap simulated against an undelayed world clears nothing, because there is no cascade to
    clear. Stacking it on the delay in the same scenario is what makes the recovery measurable,
    and getting this wrong would make every recovery answer read as "saves 0 minutes".
    """
    dispatch(
        context,
        "simulate_action",
        {
            "action": "delay_flight",
            "flight_id": ROOT,
            "additional_minutes": 142,
            "reason": "nas",
            "scenario_id": "recovery",
        },
    )
    stacked = dispatch(
        context,
        "simulate_action",
        {
            "action": "swap_aircraft",
            "flight_id": ROOT,
            "replacement_tail": "N8528Q",
            "scenario_id": "recovery",
        },
    )
    assert stacked["net_system_minutes"] == -565

    isolated = dispatch(
        context,
        "simulate_action",
        {
            "action": "swap_aircraft",
            "flight_id": ROOT,
            "replacement_tail": "N8528Q",
            "scenario_id": "clean",
        },
    )
    assert isolated["net_system_minutes"] == 0


def test_a_swap_carries_the_displacement_warning(context: ToolContext) -> None:
    """A recovery presented without its cost is the failure mode the diff exists to prevent."""
    result = dispatch(
        context,
        "simulate_action",
        {"action": "swap_aircraft", "flight_id": ROOT, "replacement_tail": "N8528Q"},
    )
    assert any("remaining line of flying" in warning for warning in result["warnings"])
    assert result["available_tails"]


def test_a_rejected_action_names_the_precondition_and_the_object(context: ToolContext) -> None:
    with pytest.raises(ToolFailure) as rejected:
        dispatch(
            context,
            "simulate_action",
            {"action": "swap_aircraft", "flight_id": ROOT, "replacement_tail": "N00000"},
        )
    message = str(rejected.value)
    assert ROOT in message
    assert "N00000" in message


def test_dispatch_rejects_an_unknown_tool_by_listing_the_three(context: ToolContext) -> None:
    with pytest.raises(ToolFailure) as rejected:
        dispatch(context, "run_sql", {"sql": "SELECT 1"})
    assert "find_objects" in str(rejected.value)


# -- the SQL baseline -----------------------------------------------------------------------------


def test_baseline_answers_a_select(database: Path) -> None:
    with baseline.SqlBaseline(database) as sql:
        result = sql.run_sql("SELECT count(*) AS n FROM flights")
    assert result["rows"][0]["n"] == 26161


def test_baseline_rejects_writes_and_multiple_statements(database: Path) -> None:
    with baseline.SqlBaseline(database) as sql:
        with pytest.raises(ToolFailure):
            sql.run_sql("DELETE FROM flights")
        with pytest.raises(ToolFailure):
            sql.run_sql("SELECT 1; SELECT 2")


def test_baseline_reports_truncation_at_the_same_cap_as_the_object_tools(database: Path) -> None:
    with baseline.SqlBaseline(database) as sql:
        result = sql.run_sql("SELECT flight_id FROM flights")
    assert result["row_count"] == baseline.MAX_ROWS == MAX_RESULTS
    assert "truncated" in result


def test_baseline_returns_a_readable_message_for_a_bad_query(database: Path) -> None:
    with baseline.SqlBaseline(database) as sql, pytest.raises(ToolFailure) as rejected:
        sql.run_sql("SELECT nonexistent FROM flights")
    assert "query failed" in str(rejected.value)


# -- prompt fairness ------------------------------------------------------------------------------


def test_both_prompts_share_the_preamble_verbatim(store: ObjectStore) -> None:
    """Fairness claimed in prose is worth nothing; this is the claim made testable."""
    ontology = prompts.ontology_system_prompt(store)
    sql = prompts.sql_system_prompt(store)
    shared = prompts._shared(store)  # noqa: SLF001, asserting the private seam is the point
    assert ontology.startswith(shared)
    assert sql.startswith(shared)
    assert "cite the object ids" in shared.lower()


def test_prompts_state_the_window_that_was_actually_loaded(store: ObjectStore) -> None:
    text = prompts.ontology_system_prompt(store)
    assert "2026-01-01 to 2026-01-07" in text
    assert "WN" in text


# -- the eval set ---------------------------------------------------------------------------------


def test_there_are_exactly_ten_questions_with_unique_ids() -> None:
    assert len(evalset.QUESTIONS) == 10
    assert len(evalset.BY_ID) == 10


@pytest.mark.parametrize("question", evalset.QUESTIONS, ids=lambda q: q.question_id)
def test_each_reference_answer_passes_its_own_grader(question: evalset.Question) -> None:
    grade = question.grade(question.reference)
    assert grade.passed, grade.failures


@pytest.mark.parametrize("question", evalset.QUESTIONS, ids=lambda q: q.question_id)
def test_ids_still_count_when_markdown_escaped(question: evalset.Question) -> None:
    """A cited id laid out in a markdown table grades the same as one written in prose.

    Flight ids are pipe-delimited, and a raw pipe inside a table cell splits the cell, so an
    agent that tabulates its citations has to escape them. Both agents did on the first live
    run, and the literal substring check scored two correct, fully-cited answers as having
    cited nothing. This is that bug, held down.
    """
    grade = question.grade(question.reference.replace("|", "\\|"))
    assert grade.passed, grade.failures


def test_a_fluent_answer_with_no_ids_fails() -> None:
    """The bias the graders are built with, asserted rather than assumed."""
    question = evalset.BY_ID["cascade-projection"]
    grade = question.grade(
        "The delay cascades significantly through the aircraft's remaining rotation, "
        "affecting several downstream flights over the course of the day."
    )
    assert not grade.passed


def test_a_fabricated_aircraft_type_fails_the_unanswerable_question() -> None:
    question = evalset.BY_ID["unanswerable-aircraft-type"]
    grade = question.grade("It was a Boeing 737-800, and roughly 120 passengers were rebooked.")
    assert not grade.passed
    assert any("737" in failure for failure in grade.failures)


def test_word_numerals_count_as_numbers() -> None:
    question = evalset.BY_ID["rotation-traversal"]
    assert question.grade(
        "N8633A flies seven legs on 2026-01-03, starting at MSY and finishing at HOU."
    ).passed


# -- the loop -------------------------------------------------------------------------------------


class ScriptedTransport:
    """A transport that returns pre-written turns, so the loop can be tested without the API.

    Not the same thing as ReplayTransport, which replays a real recording. This one exists to
    drive the loop's own mechanics (tool_use extraction, tool_result assembly, error flagging,
    answer extraction) which would otherwise only ever be exercised by a live run.
    """

    def __init__(self, turns: list[loop.AssistantTurn]) -> None:
        self.turns = turns
        self.seen: list[list[dict[str, object]]] = []

    def next_turn(
        self,
        system: str,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> loop.AssistantTurn:
        self.seen.append(list(messages))
        return self.turns.pop(0)


def test_the_loop_executes_tool_calls_and_returns_the_final_text(context: ToolContext) -> None:
    transport = ScriptedTransport(
        [
            loop.AssistantTurn(
                content=[
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "find_objects",
                        "input": {"object_type": "flight", "flight_id": ROOT},
                    }
                ],
                stop_reason="tool_use",
            ),
            loop.AssistantTurn(
                content=[{"type": "text", "text": f"{ROOT} was 142 minutes late."}],
                stop_reason="end_turn",
            ),
        ]
    )
    transcript = loop.run(
        question_id="t",
        question="How late was it?",
        agent="ontology",
        system="test",
        tools=[],
        execute=loop.ontology_executor(context),
        transport=transport,
    )
    assert transcript.answer == f"{ROOT} was 142 minutes late."
    assert len(transcript.tool_calls) == 1
    assert transcript.tool_calls[0].is_error is False
    assert transcript.error is None

    # The tool result has to come back as a user message keyed to the call, or the next request
    # is rejected by the API rather than by anything this project controls.
    result_message = transport.seen[-1][-1]
    assert result_message["role"] == "user"
    block = cast("list[dict[str, object]]", result_message["content"])[0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "call_1"


def test_a_rejected_tool_call_goes_back_as_an_error_the_model_can_read(
    context: ToolContext,
) -> None:
    transport = ScriptedTransport(
        [
            loop.AssistantTurn(
                content=[
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "traverse_links",
                        "input": {"flight_id": ROOT, "link": "downstream"},
                    }
                ],
                stop_reason="tool_use",
            ),
            loop.AssistantTurn(
                content=[{"type": "text", "text": "There is no downstream link."}],
                stop_reason="end_turn",
            ),
        ]
    )
    transcript = loop.run(
        question_id="t",
        question="Walk downstream.",
        agent="ontology",
        system="test",
        tools=[],
        execute=loop.ontology_executor(context),
        transport=transport,
    )
    assert transcript.tool_calls[0].is_error is True
    assert "next_leg" in transcript.tool_calls[0].result
    block = cast("list[dict[str, object]]", transport.seen[-1][-1]["content"])[0]
    assert block["is_error"] is True


def test_a_transcript_survives_a_round_trip_through_json(tmp_path: Path) -> None:
    original = loop.Transcript(
        question_id="q",
        question="?",
        agent="ontology",
        model=loop.MODEL,
        recorded_at="2026-08-06T00:00:00+00:00",
        turns=[
            loop.AssistantTurn(content=[{"type": "text", "text": "hi"}], stop_reason="end_turn")
        ],
        answer="hi",
    )
    path = tmp_path / "t.json"
    original.write(path)
    assert loop.Transcript.read(path) == original


# -- transcript replay ----------------------------------------------------------------------------


def _recorded_transcripts() -> list[Path]:
    return sorted(TRANSCRIPTS.glob("*/*.json")) if TRANSCRIPTS.exists() else []


_LIMITED = re.compile(r"\blimit\b", re.IGNORECASE)


def _comparable(payload: str, sql: str | None = None) -> object:
    """A recorded SQL result reduced to the part the query actually pinned down.

    The ontology tools choose their own ordering, so their replays are compared byte for byte.
    The baseline's queries are written by the model, and the model wrote three kinds of query
    whose output is not fully determined:

    Unordered but complete. A `GROUP BY` with no `ORDER BY` returns every group in an arbitrary
    sequence. The rows are pinned down, the order is not, so the rows are compared as a multiset.

    An arbitrary subset. When rows are discarded without a total order over them, which rows
    survive is undefined. That happens two ways here: the tool's own 40-row cap, which sets
    `truncated`, and a model-written `LIMIT 8` over a column with ties at the boundary. Only the
    shape can be asserted, because only the shape was promised.

    Comparing more than this is how the first version of the fix became flaky. It re-ran a
    disagreeing query and expected a second disagreement to prove non-determinism, but DuckDB's
    hash-aggregate order is frequently stable inside one process and different across machines.
    That passed locally and failed in CI, which is the worst way for a test to be wrong.
    """
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return payload
    rows = parsed.get("rows") if isinstance(parsed, dict) else None
    if not isinstance(rows, list):
        return parsed
    if "truncated" in parsed or (sql is not None and _LIMITED.search(sql)):
        parsed["rows"] = f"<{len(rows)} rows, an arbitrary subset the query did not order>"
    else:
        parsed["rows"] = sorted(rows, key=lambda row: json.dumps(row, sort_keys=True))
    return parsed


def test_comparable_tolerates_only_what_the_query_left_undefined() -> None:
    """The replay comparison's own rules, asserted directly.

    This carries real judgement about what a SQL result promises, so it gets tested rather than
    only exercised through the transcripts. The first version of it was flaky, and a flaky
    reproducibility check is worse than none.
    """
    full = json.dumps({"columns": ["a"], "rows": [{"a": 1}, {"a": 2}]})
    reordered = json.dumps({"columns": ["a"], "rows": [{"a": 2}, {"a": 1}]})
    altered = json.dumps({"columns": ["a"], "rows": [{"a": 1}, {"a": 3}]})
    capped = json.dumps({"columns": ["a"], "rows": [{"a": 1}, {"a": 2}], "truncated": "more"})
    capped_other = json.dumps({"columns": ["a"], "rows": [{"a": 9}, {"a": 8}], "truncated": "more"})
    capped_shorter = json.dumps({"columns": ["a"], "rows": [{"a": 9}], "truncated": "more"})

    # Order is not promised by a GROUP BY, so a permutation is the same answer.
    assert _comparable(full) == _comparable(reordered)
    # The rows themselves are promised, so a changed value is still a regression.
    assert _comparable(full) != _comparable(altered)
    # Which rows survive a cap or a LIMIT is not promised, so a different subset is tolerated.
    assert _comparable(capped) == _comparable(capped_other)
    assert _comparable(full, "select x limit 8") == _comparable(altered, "select x limit 8")
    # Shape is still promised even then.
    assert _comparable(capped) != _comparable(capped_shorter)
    # And a query with no LIMIT gets the strict comparison.
    assert _comparable(full, "select x") != _comparable(altered, "select x")


@pytest.mark.skipif(
    not _recorded_transcripts(),
    reason="no transcripts committed yet; run scripts/run_eval.py with an API key",
)
@pytest.mark.parametrize("path", _recorded_transcripts(), ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_recorded_tool_calls_still_return_what_was_recorded(path: Path, database: Path) -> None:
    """Re-execute a transcript's tool calls and assert the tools have not changed their answers.

    Scenario state is rebuilt in recording order, which is why the whole transcript is replayed
    rather than each call in isolation: a swap only reproduces its recorded diff if the delay
    that preceded it in the same scenario has been applied first.

    The two agents are held to different standards, and the difference is a finding rather than a
    convenience. The ontology tools decide their own ordering, so a recorded result must come back
    byte for byte, and all ten of those transcripts do. The baseline's tool runs whatever SQL the
    model wrote, and `_comparable` explains what parts of that output the query actually pinned
    down. Everything a query determined is still asserted exactly.
    """
    transcript = loop.Transcript.read(path)
    with ObjectStore(database) as store:
        if transcript.agent == "ontology":
            context = ToolContext.open(store)
            for call in transcript.tool_calls:
                try:
                    replayed = json.dumps(dispatch(context, call.name, call.arguments), default=str)
                    errored = False
                except ToolFailure as failure:
                    replayed, errored = str(failure), True
                assert errored == call.is_error, f"{call.name} changed error status"
                assert replayed == call.result, f"{call.name} changed its result"
        else:
            with baseline.SqlBaseline(database) as sql:
                execute = sql.executor()
                for call in transcript.tool_calls:
                    try:
                        replayed = json.dumps(execute(call.name, call.arguments), default=str)
                        errored = False
                    except ToolFailure as failure:
                        replayed, errored = str(failure), True
                    assert errored == call.is_error, f"{call.name} changed error status"
                    query = call.arguments.get("sql") if isinstance(call.arguments, dict) else None
                    text = query if isinstance(query, str) else None
                    assert _comparable(replayed, text) == _comparable(call.result, text), (
                        f"{call.name} changed its result"
                    )
