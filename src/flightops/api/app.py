"""The HTTP API: read-only over baked-in data, with per-session scenario sandboxes.

BRIEF M7. The shape follows DESIGN.md section 7: one immutable DuckDB file opened read-only for
the life of the process, and scenarios as per-caller overlays. Nothing here can write to the
data, which is what makes it safe to put on a public URL with no auth.

Three deliberate choices about running in public:

Live question-answering is env-gated. Without `ANTHROPIC_API_KEY` the endpoint returns 503 with
an explanation rather than 404, because "this is switched off and here is why" is a better
answer to a reader poking at the deployed app than a missing route. DESIGN.md section 11 asks
for exactly this so the public URL cannot accrue cost.

Domain errors keep their text. A rejected action returns the precondition that failed --
"N8528Q lands at PHX at 14:05 UTC and needs 38 min to turn" -- with a 409, not a bare 400. The
message was written for a human deciding what to try next, and dropping it at the HTTP boundary
would throw away the most useful thing the domain layer produces.

Responses are the domain objects. pydantic models go over the wire as they are rather than
through a second layer of API-shaped DTOs, because a translation layer between two pydantic
models is a place for the two to disagree, and there is nothing in these objects a reader should
not see.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from flightops.actions.actions import ActionDiff, Actions, PreconditionFailed
from flightops.agent import evalset
from flightops.api.sessions import (
    Session,
    SessionLimitReached,
    SessionNotFound,
    SessionStore,
)
from flightops.model.objects import Aircraft, Airport, Carrier, DisruptionEvent, Flight
from flightops.model.scenario import Scenario
from flightops.model.store import ObjectNotFound, ObjectStore
from flightops.propagation.engine import PropagationEngine, build_turn_model
from flightops.propagation.events import rank_disruptions

# Repo-relative defaults, for running out of a checkout. Both are overridden by environment
# variables in the container image, where `parents[3]` is site-packages rather than the repo.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE = REPO_ROOT / "data" / "sample" / "sample.duckdb"
DEFAULT_TRANSCRIPTS = REPO_ROOT / "data" / "transcripts"


def database_path() -> Path:
    """Where the baked-in data lives. `FLIGHTOPS_DB` overrides it for the container image."""
    return Path(os.environ.get("FLIGHTOPS_DB", str(DEFAULT_DATABASE)))


def transcripts_path() -> Path:
    """Where the committed eval transcripts live. `FLIGHTOPS_TRANSCRIPTS` overrides it."""
    return Path(os.environ.get("FLIGHTOPS_TRANSCRIPTS", str(DEFAULT_TRANSCRIPTS)))


def live_answers_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


# -- request and response bodies ------------------------------------------------------------------


class Health(BaseModel):
    status: Literal["ok"]
    flight_count: int
    first_date: str
    last_date: str
    carriers: list[str]
    live_answers: bool = Field(
        description="Whether question-answering is enabled; false unless an API key is set."
    )
    active_sessions: int


class FlightDetail(BaseModel):
    """One flight with the links an operator immediately wants, resolved in one round trip."""

    flight: Flight
    aircraft: Aircraft | None
    origin_airport: Airport
    destination_airport: Airport
    operating_carrier: Carrier
    previous_leg: Flight | None
    next_leg: Flight | None
    ground_minutes_after: int | None
    chain_break_reason: str | None


class ScenarioRequest(BaseModel):
    flight_id: str = Field(description="The scenario clock is pinned just before this departure.")


class ScenarioState(BaseModel):
    session_id: str
    clock_utc: str
    description: str
    actions_applied: int
    changes: list[str]


class ActionRequest(BaseModel):
    action: Literal["delay_flight", "cancel_flight", "swap_aircraft"]
    flight_id: str
    additional_minutes: int | None = None
    reason: str = "simulated"
    replacement_tail: str | None = None


class ActionResponse(BaseModel):
    diff: ActionDiff
    scenario: ScenarioState
    available_tails: list[dict[str, str]] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class EvalQuestion(BaseModel):
    question_id: str
    question: str
    reference: str
    tests: str
    ontology_passed: bool | None
    sql_passed: bool | None
    ontology_failures: list[str]
    sql_failures: list[str]


class EvalReport(BaseModel):
    """The published eval, read from the committed transcripts rather than recomputed."""

    recorded: bool
    ontology_score: str
    sql_score: str
    questions: list[EvalQuestion]
    note: str


# -- process-wide state ---------------------------------------------------------------------------


@dataclass
class Services:
    """Opened once at startup. The store is read-only, so sharing it across requests is safe."""

    store: ObjectStore
    engine: PropagationEngine
    actions: Actions
    sessions: SessionStore


_services: Services | None = None


def services() -> Services:
    if _services is None:  # pragma: no cover - only reachable if the lifespan did not run
        raise RuntimeError("services not initialised")
    return _services


ServicesDep = Annotated[Services, Depends(services)]
"""Injected first in every handler, so nothing here reaches for a module global directly."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _services
    store = ObjectStore(database_path())
    engine = PropagationEngine(build_turn_model(store))
    _services = Services(
        store=store,
        engine=engine,
        actions=Actions(engine),
        sessions=SessionStore(store),
    )
    try:
        yield
    finally:
        store.close()
        _services = None


app = FastAPI(
    title="flightops",
    summary="Rotation-cascade intelligence over BTS On-Time Performance data",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # The API is read-only and unauthenticated, so there is no cross-origin secret to protect
    # and no cookie an origin restriction would be defending. Locking it to one deploy URL
    # would only break local development against the deployed API.
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# -- reads ------------------------------------------------------------------------------------


@app.get("/api/health", response_model=Health)
def health(state: ServicesDep) -> Health:
    first, last, carriers = state.store.coverage()
    return Health(
        status="ok",
        flight_count=state.store.flight_count(),
        first_date=first,
        last_date=last,
        carriers=carriers,
        live_answers=live_answers_enabled(),
        active_sessions=len(state.sessions),
    )


@app.get("/api/disruptions", response_model=list[DisruptionEvent])
def disruptions(
    state: ServicesDep,
    date: str = Query(description="Flight date, YYYY-MM-DD."),
    limit: int = Query(default=10, ge=1, le=25),
) -> list[DisruptionEvent]:
    """The day's cascades, ranked by downstream minutes caused, one per aircraft."""
    return rank_disruptions(state.store, state.engine, date, limit=limit)


@app.get("/api/flights", response_model=list[Flight])
def flights(
    state: ServicesDep,
    carrier: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
    tail_number: str | None = None,
    date: str | None = None,
    min_dep_delay: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Flight]:
    return state.store.find_flights(
        carrier=carrier,
        origin=origin,
        destination=destination,
        tail_number=tail_number,
        flight_date=date,
        min_dep_delay=min_dep_delay,
        limit=limit,
    )


@app.get("/api/flights/{flight_id:path}/rotation", response_model=list[Flight])
def rotation(state: ServicesDep, flight_id: str) -> list[Flight]:
    """The whole line of flying for this leg's aircraft on this day, in scheduled order."""
    flight = _flight_or_404(state.store, flight_id)
    if flight.tail_number is None:
        return [flight]
    return state.store.rotation(flight.tail_number, flight.flight_date)


@app.get("/api/flights/{flight_id:path}/cascade", response_model=DisruptionEvent)
def cascade(
    state: ServicesDep,
    flight_id: str,
    minutes: int | None = Query(
        default=None,
        ge=0,
        le=1440,
        description="Root delay to project. Defaults to the delay the flight actually had.",
    ),
) -> DisruptionEvent:
    flight = _flight_or_404(state.store, flight_id)
    root_delay = minutes if minutes is not None else (flight.dep_delay_minutes or 0)
    scenario = Scenario(store=state.store, clock=flight.sched_dep_utc)
    return state.engine.project(scenario, flight_id, root_delay)


@app.get("/api/flights/{flight_id:path}/swap-candidates")
def swap_candidates(state: ServicesDep, flight_id: str) -> list[dict[str, str]]:
    """Tails that could take this leg, before committing to a scenario."""
    flight = _flight_or_404(state.store, flight_id)
    scenario = Scenario(store=state.store, clock=flight.sched_dep_utc - timedelta(minutes=1))
    return [
        {"tail_number": tail, "arrives_utc": arrival.isoformat()}
        for tail, arrival in state.actions.available_tails(scenario, flight_id)
    ]


@app.get("/api/flights/{flight_id:path}", response_model=FlightDetail)
def flight_detail(state: ServicesDep, flight_id: str) -> FlightDetail:
    store = state.store
    flight = _flight_or_404(store, flight_id)
    following = store.next_leg(flight_id)
    return FlightDetail(
        flight=flight,
        aircraft=store.get_aircraft(flight.tail_number) if flight.tail_number else None,
        origin_airport=store.get_airport(flight.origin),
        destination_airport=store.get_airport(flight.destination),
        operating_carrier=store.get_carrier(flight.carrier),
        previous_leg=store.previous_leg(flight_id),
        next_leg=following,
        ground_minutes_after=store.ground_minutes_after(flight_id),
        chain_break_reason=None if following else store.chain_break_after(flight_id),
    )


# -- scenarios and actions ----------------------------------------------------------------------


@app.post("/api/scenarios", response_model=ScenarioState, status_code=201)
def open_scenario(state: ServicesDep, request: ScenarioRequest) -> ScenarioState:
    """Open a sandbox pinned one minute before the given flight's scheduled departure.

    The pin is what makes a counterfactual well defined over a completed day: every flight in
    the data has already operated, so without a "now" earlier than the target, no action is
    ever legal. See DESIGN.md section 7.
    """
    flight = _flight_or_404(state.store, request.flight_id)
    session = state.sessions.create(flight.sched_dep_utc - timedelta(minutes=1))
    return _scenario_state(session)


@app.get("/api/scenarios/{session_id}", response_model=ScenarioState)
def read_scenario(state: ServicesDep, session_id: str) -> ScenarioState:
    return _scenario_state(_session_or_404(state, session_id))


@app.post("/api/scenarios/{session_id}/actions", response_model=ActionResponse)
def run_action(state: ServicesDep, session_id: str, request: ActionRequest) -> ActionResponse:
    session = _session_or_404(state, session_id)
    try:
        state.sessions.guard_action_limit(session)
    except SessionLimitReached as limited:
        raise HTTPException(status_code=429, detail=str(limited)) from limited

    _flight_or_404(state.store, request.flight_id)
    scenario = session.scenario
    try:
        match request.action:
            case "delay_flight":
                if request.additional_minutes is None:
                    raise HTTPException(
                        status_code=422, detail="delay_flight requires additional_minutes"
                    )
                diff = state.actions.delay_flight(
                    scenario, request.flight_id, request.additional_minutes, request.reason
                )
            case "cancel_flight":
                diff = state.actions.cancel_flight(scenario, request.flight_id, request.reason)
            case "swap_aircraft":
                if not request.replacement_tail:
                    raise HTTPException(
                        status_code=422, detail="swap_aircraft requires replacement_tail"
                    )
                diff = state.actions.swap_aircraft(
                    scenario, request.flight_id, request.replacement_tail
                )
    except PreconditionFailed as rejected:
        # 409, not 400: the request was well formed and the world said no. The precondition text
        # is the response body because it is the only thing that tells the caller what to try.
        raise HTTPException(status_code=409, detail=rejected.precondition) from rejected

    available = [
        {"tail_number": tail, "arrives_utc": arrival.isoformat()}
        for tail, arrival in state.actions.available_tails(scenario, request.flight_id)
    ]
    return ActionResponse(diff=diff, scenario=_scenario_state(session), available_tails=available)


# -- question answering, env-gated ----------------------------------------------------------------


@app.post("/api/ask")
def ask(state: ServicesDep, request: AskRequest) -> dict[str, Any]:
    """Answer one question through the three ontology tools.

    Switched off unless `ANTHROPIC_API_KEY` is set, so the public URL cannot spend money
    (DESIGN.md section 11). When it is off the eval transcripts are still served, which is the
    honest substitute: recorded answers to fixed questions rather than live ones.
    """
    if not live_answers_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "Live question-answering is disabled on this deployment: it costs money per "
                "question and the URL is public. The recorded eval transcripts at /api/eval "
                "show the same three tools answering ten fixed questions. To enable it, set "
                "ANTHROPIC_API_KEY and restart."
            ),
        )

    from flightops.agent import loop, prompts, tools

    context = tools.ToolContext.open(state.store)
    transcript = loop.run(
        question_id="live",
        question=request.question,
        agent="ontology",
        system=prompts.ontology_system_prompt(state.store),
        tools=list(tools.TOOL_SCHEMAS),
        execute=loop.ontology_executor(context),
        transport=loop.LiveTransport(),
    )
    return {
        "answer": transcript.answer,
        "error": transcript.error,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments, "is_error": call.is_error}
            for call in transcript.tool_calls
        ],
        "usage": transcript.to_json()["usage"],
    }


@app.get("/api/eval", response_model=EvalReport)
def eval_report() -> EvalReport:
    return _eval_report(_transcripts_fingerprint())


# -- helpers ----------------------------------------------------------------------------------


def _flight_or_404(store: ObjectStore, flight_id: str) -> Flight:
    try:
        return store.get_flight(flight_id)
    except ObjectNotFound as missing:
        raise HTTPException(status_code=404, detail=str(missing)) from missing


def _session_or_404(state: Services, session_id: str) -> Session:
    try:
        return state.sessions.get(session_id)
    except SessionNotFound as missing:
        raise HTTPException(status_code=404, detail=str(missing)) from missing


def _scenario_state(session: Session) -> ScenarioState:
    return ScenarioState(
        session_id=session.session_id,
        clock_utc=session.scenario.clock.isoformat(),
        description=session.scenario.describe(),
        actions_applied=session.action_count,
        changes=[change.summary for change in session.scenario.changes],
    )


def _transcripts_fingerprint() -> tuple[tuple[str, int], ...]:
    """Paths and sizes of the committed transcripts, so the cache invalidates if they change."""
    root = transcripts_path()
    if not root.exists():
        return ()
    return tuple(
        (str(path.relative_to(root)), path.stat().st_size) for path in sorted(root.glob("*/*.json"))
    )


@lru_cache(maxsize=4)
def _eval_report(fingerprint: tuple[tuple[str, int], ...]) -> EvalReport:
    """Grade the committed transcripts. Cached on their fingerprint; they change only on deploy."""
    graded: dict[str, dict[str, evalset.Grade]] = {"ontology": {}, "sql": {}}
    for agent in graded:
        for question in evalset.QUESTIONS:
            path = transcripts_path() / agent / f"{question.question_id}.json"
            if not path.exists():
                continue
            answer = str(json.loads(path.read_text()).get("answer", ""))
            graded[agent][question.question_id] = question.grade(answer)

    recorded = bool(graded["ontology"] or graded["sql"])
    questions = [
        EvalQuestion(
            question_id=question.question_id,
            question=question.question,
            reference=question.reference,
            tests=question.tests,
            ontology_passed=_passed(graded["ontology"].get(question.question_id)),
            sql_passed=_passed(graded["sql"].get(question.question_id)),
            ontology_failures=list(_failures(graded["ontology"].get(question.question_id))),
            sql_failures=list(_failures(graded["sql"].get(question.question_id))),
        )
        for question in evalset.QUESTIONS
    ]
    return EvalReport(
        recorded=recorded,
        ontology_score=_score(graded["ontology"]),
        sql_score=_score(graded["sql"]),
        questions=questions,
        note=(
            "Scores come from the committed transcripts in data/transcripts/, graded by the "
            "same programmatic checks pytest uses. Every expected value was verified by hand "
            "against the sample."
            if recorded
            else "No eval run has been recorded yet, so there is no score to report. The "
            "questions, the hand-verified answers and the graders are all here; what is "
            "missing is a run against the live API."
        ),
    )


def _passed(grade: evalset.Grade | None) -> bool | None:
    return None if grade is None else grade.passed


def _failures(grade: evalset.Grade | None) -> Iterator[str]:
    if grade is not None:
        yield from grade.failures


def _score(grades: dict[str, evalset.Grade]) -> str:
    if not grades:
        return "not run"
    passed = sum(1 for grade in grades.values() if grade.passed)
    return f"{passed} / {len(evalset.QUESTIONS)}"
