"""The agent loop, and the record/replay that makes its transcripts testable offline.

DESIGN.md section 11 requires committed transcripts so pytest runs offline and deterministic.
That constraint is what shapes this module.

The loop is written by hand rather than handed to the SDK's tool runner. The runner would do
the same request-execute-repeat cycle, but it owns the message list, and the message list is
the artefact being published: an eval whose transcripts are a summary of what happened is not
checkable. Owning the loop means every assistant turn and every tool result is captured
verbatim, in order, in a format that can be replayed.

Replay is not a JSON echo. A replayed run feeds the recorded assistant turns back in sequence
but re-executes every tool call against the live store, then asserts the results match what was
recorded. So the offline test fails if the propagation engine, the actions, or the store ever
change what they would have told the model -- which is the regression worth catching. What it
deliberately does not test is the model, and the docstring on ReplayTransport says so.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from flightops.agent.tools import ToolCall, ToolContext, ToolFailure, dispatch

if TYPE_CHECKING:  # The SDK is an optional extra: only a live run needs it installed.
    from anthropic.types import (
        MessageParam,
        OutputConfigParam,
        TextBlockParam,
        ThinkingConfigAdaptiveParam,
        ToolParam,
    )

ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]
"""Runs one tool call. Raises ToolFailure for a rejection the model should read and retry."""

MODEL = "claude-opus-5"
"""One model for the ontology agent and the SQL baseline. Comparing two models would measure
the models, not the tool surface, which is the only thing this eval is trying to isolate."""

MAX_TOKENS = 16_000
EFFORT: Literal["high"] = "high"
MAX_TURNS = 16
"""Bound on the request-execute cycle. A question that needs more than sixteen turns has
failed at something other than arithmetic, and the transcript should show where it stalled
rather than run up a bill."""

INPUT_COST_PER_MTOK = 5.00
OUTPUT_COST_PER_MTOK = 25.00
"""Published Claude Opus 5 rates as of 2026-08-06. Used only to report what an eval run cost;
nothing branches on them."""


class RefusedByModel(RuntimeError):
    """The model declined the request. Distinguished from a failure so a run does not retry."""


class TurnLimitReached(RuntimeError):
    """The loop hit MAX_TURNS with the model still calling tools."""


@dataclass
class AssistantTurn:
    """One assistant message, stored as raw content blocks so it can be replayed unchanged.

    Thinking blocks in particular must go back to the API exactly as they came out, so nothing
    here reshapes or filters the content.
    """

    content: list[dict[str, Any]]
    stop_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Transcript:
    """A complete run: what was asked, every tool call, and the answer."""

    question_id: str
    question: str
    agent: str
    model: str
    recorded_at: str
    turns: list[AssistantTurn] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    answer: str = ""
    error: str | None = None

    @property
    def input_tokens(self) -> int:
        return sum(turn.input_tokens for turn in self.turns)

    @property
    def output_tokens(self) -> int:
        return sum(turn.output_tokens for turn in self.turns)

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens / 1_000_000 * INPUT_COST_PER_MTOK
            + self.output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "agent": self.agent,
            "model": self.model,
            "recorded_at": self.recorded_at,
            "turns": [asdict(turn) for turn in self.turns],
            "tool_calls": [asdict(call) for call in self.tool_calls],
            "answer": self.answer,
            "error": self.error,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": round(self.cost_usd, 4),
            },
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2, sort_keys=False) + "\n")

    @classmethod
    def read(cls, path: Path) -> Transcript:
        raw = json.loads(path.read_text())
        return cls(
            question_id=raw["question_id"],
            question=raw["question"],
            agent=raw["agent"],
            model=raw["model"],
            recorded_at=raw["recorded_at"],
            turns=[AssistantTurn(**turn) for turn in raw["turns"]],
            tool_calls=[ToolCall(**call) for call in raw["tool_calls"]],
            answer=raw["answer"],
            error=raw.get("error"),
        )


class Transport(Protocol):
    """Where the next assistant turn comes from: the API, or a recording of it."""

    def next_turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn: ...


class LiveTransport:
    """Calls the Messages API. The only place in the project that spends money."""

    def __init__(self, model: str = MODEL) -> None:
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = model

    def next_turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn:
        # The system block is cached: the prompt is identical across all ten questions and both
        # agents, so every turn after the first reads it from cache instead of paying for it.
        prompt: list[TextBlockParam] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
        thinking: ThinkingConfigAdaptiveParam = {"type": "adaptive"}
        output_config: OutputConfigParam = {"effort": EFFORT}
        response = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=prompt,
            thinking=thinking,
            output_config=output_config,
            tools=cast("list[ToolParam]", tools),
            messages=cast("list[MessageParam]", messages),
        )
        if response.stop_reason == "refusal":
            raise RefusedByModel(f"model declined: {response.stop_details}")
        return AssistantTurn(
            content=[block.model_dump(exclude_none=True) for block in response.content],
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


class ReplayTransport:
    """Serves recorded assistant turns in order, so a run needs no API key.

    What this does and does not prove is worth being exact about. Replaying does not test the
    model -- the model's turns are fixed, so a replayed run cannot fail because the model got
    worse. It tests that the tools still answer those calls the same way. Every tool the
    recording invoked is re-executed live against the store, and the caller compares the
    results; a change to propagation, actions, or the store that would have changed what the
    model saw shows up as a mismatch. The published n-out-of-10 comes from a live run, not
    from this.
    """

    def __init__(self, transcript: Transcript) -> None:
        self._turns = list(transcript.turns)
        self._position = 0

    def next_turn(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn:
        if self._position >= len(self._turns):
            raise TurnLimitReached(
                f"replay exhausted after {self._position} turns: the loop asked for a turn the "
                f"recording does not have, which means tool results diverged from the recording"
            )
        turn = self._turns[self._position]
        self._position += 1
        return turn


def _tool_result_block(tool_use_id: str, payload: str, is_error: bool) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": payload,
    }
    if is_error:
        block["is_error"] = True
    return block


def run(
    *,
    question_id: str,
    question: str,
    agent: str,
    system: str,
    tools: list[dict[str, Any]],
    execute: ToolExecutor,
    transport: Transport,
    model: str = MODEL,
) -> Transcript:
    """Drive one question to an answer, recording every turn.

    `execute` takes (name, arguments) and returns the JSON-serialisable tool result, raising
    ToolFailure for a rejection the model should read. Both agents share this loop so the
    comparison is between tool surfaces and nothing else.
    """
    transcript = Transcript(
        question_id=question_id,
        question=question,
        agent=agent,
        model=model,
        recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

    for _ in range(MAX_TURNS):
        turn = transport.next_turn(system, messages, tools)
        transcript.turns.append(turn)
        messages.append({"role": "assistant", "content": turn.content})

        calls = [block for block in turn.content if block.get("type") == "tool_use"]
        if not calls:
            transcript.answer = "\n".join(
                str(block.get("text", "")) for block in turn.content if block.get("type") == "text"
            ).strip()
            if turn.stop_reason == "max_tokens":
                transcript.error = "answer truncated at max_tokens"
            return transcript

        results: list[dict[str, Any]] = []
        for call in calls:
            name = str(call.get("name", ""))
            arguments = dict(call.get("input") or {})
            try:
                payload = json.dumps(execute(name, arguments), default=str)
                is_error = False
            except ToolFailure as rejected:
                payload = str(rejected)
                is_error = True
            transcript.tool_calls.append(
                ToolCall(name=name, arguments=arguments, result=payload, is_error=is_error)
            )
            results.append(_tool_result_block(str(call.get("id", "")), payload, is_error))
        messages.append({"role": "user", "content": results})

    transcript.error = f"reached the {MAX_TURNS}-turn limit without answering"
    return transcript


def ontology_executor(context: ToolContext) -> ToolExecutor:
    """Bind the three ontology tools to a store for one question."""

    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return dispatch(context, name, arguments)

    return execute
