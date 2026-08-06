"""The three tools the model gets, mirroring the ontology.

DESIGN.md section 11: find_objects (typed filters), traverse_links (walk a named link),
simulate_action (run one of the three actions and return its diff). No SQL path.

Two properties are load-bearing and are what the eval is actually testing:

Every tool result carries object ids. An answer that cites `2026-01-03|WN|3851|PHX|SFO|0855`
can be checked against the store by anyone; an answer that says "the Phoenix flight" cannot.
The ids are ugly on purpose -- they are the primary key, not a label.

Every rejection names the object and the precondition that failed. A tool that returns
"error" teaches the model nothing; one that returns "N8633A lands at PHX at 14:05 UTC and
needs 38 min to turn, which is 12 min short of the 14:35 departure" lets it either pick a
different tail or tell the operator why no swap exists. That text is the tool's real output
on the unhappy path, so it gets the same care as the happy path.

Scenarios are keyed by a caller-supplied name so recovery actions compose: a delay and the
swap that recovers it must land in the same overlay or the swap has no cascade to clear. The
clock is pinned once, from the first action in that scenario, and never moves -- a scenario
whose "now" drifted between calls would silently change which flights are still actionable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from flightops.actions.actions import ActionDiff, Actions, PreconditionFailed
from flightops.model.objects import Aircraft, Airport, Carrier, Flight, FlightStatus
from flightops.model.scenario import Scenario
from flightops.model.store import Link, ObjectNotFound, ObjectStore
from flightops.propagation.engine import PropagationEngine, build_turn_model

MAX_RESULTS = 40
"""Hard cap on rows returned to the model.

Not a token-saving measure: an answer built from a truncated list the model believed was
complete is wrong in a way that reads as confident. Truncation is always reported in the
result so the model can narrow its filters instead of guessing.
"""


class ToolFailure(Exception):
    """A tool-level rejection, rendered back to the model as an error tool_result.

    Distinct from a crash. The model is expected to read these and retry differently, so the
    message is written for that reader.
    """


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation and its result, recorded for the transcript."""

    name: str
    arguments: dict[str, Any]
    result: str
    is_error: bool


def _flight_json(flight: Flight) -> dict[str, Any]:
    """A flight as the model sees it. Ids first, then the fields questions are asked about."""
    payload: dict[str, Any] = {
        "flight_id": flight.flight_id,
        "describes_as": flight.describe(),
        "carrier": flight.carrier,
        "flight_number": flight.flight_number,
        "origin": flight.origin,
        "destination": flight.destination,
        "tail_number": flight.tail_number,
        "status": flight.status.value,
        "flight_date": flight.flight_date,
        "sched_dep_utc": flight.sched_dep_utc.isoformat(),
        "sched_arr_utc": flight.sched_arr_utc.isoformat(),
        "sched_dep_local": flight.sched_dep_local.strftime("%H:%M"),
        "sched_block_minutes": flight.sched_block_minutes,
        "dep_delay_minutes": flight.dep_delay_minutes,
        "arr_delay_minutes": flight.arr_delay_minutes,
    }
    if flight.causes is not None:
        payload["delay_causes_minutes"] = {
            "carrier": flight.causes.carrier,
            "weather": flight.causes.weather,
            "nas": flight.causes.nas,
            "security": flight.causes.security,
            "late_aircraft": flight.causes.late_aircraft,
        }
    if flight.cancellation_code is not None:
        payload["cancellation_code"] = flight.cancellation_code.value
    return payload


def _object_json(obj: Flight | Aircraft | Airport | Carrier) -> dict[str, Any]:
    match obj:
        case Flight():
            return _flight_json(obj)
        case Aircraft():
            return {
                "object_type": "Aircraft",
                "tail_number": obj.tail_number,
                "carrier": obj.carrier,
            }
        case Airport():
            return {
                "object_type": "Airport",
                "iata": obj.iata,
                "city": obj.city,
                "iana_timezone": obj.iana_timezone,
            }
        case Carrier():
            return {"object_type": "Carrier", "code": obj.code, "name": obj.name}


def _diff_json(diff: ActionDiff) -> dict[str, Any]:
    return {
        "action": diff.action,
        "target_flight_id": diff.target_flight_id,
        "summary": diff.summary,
        "net_system_minutes": diff.net_minutes,
        "legs": [
            {
                "flight_id": leg.flight_id,
                "describes_as": leg.description,
                "delay_minutes_before": leg.before_delay_minutes,
                "delay_minutes_after": leg.after_delay_minutes,
                "change_minutes": leg.change_minutes,
            }
            for leg in diff.legs
        ],
        "warnings": list(diff.warnings),
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "find_objects",
        "description": (
            "Find objects by typed filter. Set object_type to 'flight' and combine any of the "
            "flight filters, or set it to 'aircraft', 'airport', or 'carrier' and pass "
            "object_id (a tail number, an IATA code, or a two-letter carrier code). Flight "
            "results are ordered by scheduled departure. Returns at most 40 rows and tells you "
            "when the list was truncated -- narrow the filters rather than assuming you saw "
            "everything."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_type": {
                    "type": "string",
                    "enum": ["flight", "aircraft", "airport", "carrier"],
                },
                "object_id": {
                    "type": "string",
                    "description": "Required for aircraft, airport, and carrier.",
                },
                "flight_id": {"type": "string", "description": "Fetch one flight by its id."},
                "carrier": {"type": "string", "description": "Reporting carrier, e.g. WN."},
                "origin": {"type": "string", "description": "Origin IATA code."},
                "destination": {"type": "string", "description": "Destination IATA code."},
                "tail_number": {"type": "string"},
                "flight_date": {"type": "string", "description": "YYYY-MM-DD."},
                "status": {
                    "type": "string",
                    "enum": ["scheduled", "departed", "arrived", "cancelled", "diverted"],
                },
                "min_dep_delay_minutes": {"type": "integer"},
                "min_arr_delay_minutes": {"type": "integer"},
                "limit": {"type": "integer", "description": "Default 40, maximum 40."},
            },
            "required": ["object_type"],
        },
    },
    {
        "name": "traverse_links",
        "description": (
            "Walk one named link from a flight. Links: flown_by (the aircraft), operated_by "
            "(the carrier), departs_from and arrives_at (the airports), next_leg and "
            "previous_leg (the same aircraft's adjacent legs), rotation (every leg that "
            "aircraft flies that day, in order). next_leg is the link cascades travel along; "
            "where it is absent the result explains why the chain breaks there."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "flight_id": {"type": "string"},
                "link": {
                    "type": "string",
                    "enum": [link.value for link in Link],
                },
            },
            "required": ["flight_id", "link"],
        },
    },
    {
        "name": "simulate_action",
        "description": (
            "Run one action against a scenario and return the diff it would produce. Nothing "
            "is written to the underlying data. Actions: delay_flight (needs "
            "additional_minutes and reason), cancel_flight (needs reason), swap_aircraft "
            "(needs replacement_tail). Actions sharing a scenario_id stack, which is how you "
            "measure a recovery: delay the flight, then cancel or swap in the same scenario to "
            "see how many of those minutes come back. A rejection tells you the exact "
            "precondition that failed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["delay_flight", "cancel_flight", "swap_aircraft"],
                },
                "flight_id": {"type": "string"},
                "additional_minutes": {"type": "integer"},
                "reason": {"type": "string"},
                "replacement_tail": {"type": "string"},
                "scenario_id": {
                    "type": "string",
                    "description": "Defaults to 'default'. Actions sharing one stack.",
                },
            },
            "required": ["action", "flight_id"],
        },
    },
]

TOOL_NAMES = frozenset(schema["name"] for schema in TOOL_SCHEMAS)


def _require(arguments: dict[str, Any], key: str, tool: str) -> Any:
    if arguments.get(key) in (None, ""):
        raise ToolFailure(f"{tool} requires '{key}'")
    return arguments[key]


def _optional_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    return str(value) if value not in (None, "") else None


def _optional_int(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as bad:
        raise ToolFailure(f"'{key}' must be an integer, got {value!r}") from bad


@dataclass
class ToolContext:
    """Everything the three tools read or write, held for one question.

    Scenarios live here rather than in the store because they are per-conversation state: two
    people asking questions at the same time must not see each other's hypotheticals.
    """

    store: ObjectStore
    actions: Actions
    scenarios: dict[str, Scenario] = field(default_factory=dict)

    @classmethod
    def open(cls, store: ObjectStore) -> ToolContext:
        return cls(store=store, actions=Actions(PropagationEngine(build_turn_model(store))))

    def scenario_for(self, scenario_id: str, target: Flight) -> Scenario:
        """Fetch or create a named scenario, pinning its clock to the first target's departure.

        The pin matters: the actions require a flight to be pending, and every flight in this
        data has already flown. Anchoring "now" a minute before the first target makes the
        counterfactual well defined, and keeping it fixed means a later action in the same
        scenario is judged against the same instant rather than a moving one.
        """
        existing = self.scenarios.get(scenario_id)
        if existing is not None:
            return existing
        created = Scenario(store=self.store, clock=target.sched_dep_utc - timedelta(minutes=1))
        self.scenarios[scenario_id] = created
        return created


def _find_objects(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    object_type = str(_require(arguments, "object_type", "find_objects"))

    if object_type != "flight":
        object_id = str(_require(arguments, "object_id", f"find_objects({object_type})"))
        try:
            match object_type:
                case "aircraft":
                    return _object_json(context.store.get_aircraft(object_id))
                case "airport":
                    return _object_json(context.store.get_airport(object_id))
                case "carrier":
                    return _object_json(context.store.get_carrier(object_id))
                case _:
                    raise ToolFailure(f"unknown object_type {object_type!r}")
        except ObjectNotFound as missing:
            raise ToolFailure(str(missing)) from missing

    flight_id = _optional_str(arguments, "flight_id")
    if flight_id is not None:
        try:
            return {"results": [_flight_json(context.store.get_flight(flight_id))], "count": 1}
        except ObjectNotFound as missing:
            raise ToolFailure(str(missing)) from missing

    status_value = _optional_str(arguments, "status")
    try:
        status = FlightStatus(status_value) if status_value else None
    except ValueError as bad:
        raise ToolFailure(
            f"unknown status {status_value!r}; expected one of "
            f"{', '.join(member.value for member in FlightStatus)}"
        ) from bad

    limit = _optional_int(arguments, "limit") or MAX_RESULTS
    requested = min(limit, MAX_RESULTS)
    flights = context.store.find_flights(
        carrier=_optional_str(arguments, "carrier"),
        origin=_optional_str(arguments, "origin"),
        destination=_optional_str(arguments, "destination"),
        tail_number=_optional_str(arguments, "tail_number"),
        flight_date=_optional_str(arguments, "flight_date"),
        status=status,
        min_dep_delay=_optional_int(arguments, "min_dep_delay_minutes"),
        min_arr_delay=_optional_int(arguments, "min_arr_delay_minutes"),
        limit=requested + 1,
    )
    truncated = len(flights) > requested
    shown = flights[:requested]
    result: dict[str, Any] = {
        "results": [_flight_json(flight) for flight in shown],
        "count": len(shown),
    }
    if truncated:
        result["truncated"] = (
            f"more than {requested} flights match; narrow the filters before counting or "
            f"ranking, because this list is not the full set"
        )
    return result


def _traverse_links(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    flight_id = str(_require(arguments, "flight_id", "traverse_links"))
    link_value = str(_require(arguments, "link", "traverse_links"))
    try:
        link = Link(link_value)
    except ValueError as bad:
        raise ToolFailure(
            f"unknown link {link_value!r}; the ontology has "
            f"{', '.join(member.value for member in Link)}"
        ) from bad

    try:
        flight = context.store.get_flight(flight_id)
    except ObjectNotFound as missing:
        raise ToolFailure(str(missing)) from missing

    targets = context.store.traverse(flight, link)
    result: dict[str, Any] = {
        "from_flight_id": flight_id,
        "link": link.value,
        "results": [_object_json(target) for target in targets],
        "count": len(targets),
    }
    if link is Link.NEXT_LEG:
        ground = context.store.ground_minutes_after(flight_id)
        if ground is not None:
            result["ground_minutes"] = ground
        if not targets:
            reason = context.store.chain_break_after(flight_id)
            result["chain_break_reason"] = reason or "unrecorded"
    return result


def _simulate_action(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(_require(arguments, "action", "simulate_action"))
    flight_id = str(_require(arguments, "flight_id", "simulate_action"))
    scenario_id = _optional_str(arguments, "scenario_id") or "default"

    try:
        target = context.store.get_flight(flight_id)
    except ObjectNotFound as missing:
        raise ToolFailure(str(missing)) from missing
    scenario = context.scenario_for(scenario_id, target)

    try:
        match action:
            case "delay_flight":
                minutes = _optional_int(arguments, "additional_minutes")
                if minutes is None:
                    raise ToolFailure("delay_flight requires 'additional_minutes'")
                reason = _optional_str(arguments, "reason") or "simulated"
                diff = context.actions.delay_flight(scenario, flight_id, minutes, reason)
            case "cancel_flight":
                reason = _optional_str(arguments, "reason") or "simulated"
                diff = context.actions.cancel_flight(scenario, flight_id, reason)
            case "swap_aircraft":
                tail = str(_require(arguments, "replacement_tail", "swap_aircraft"))
                diff = context.actions.swap_aircraft(scenario, flight_id, tail)
            case _:
                raise ToolFailure(f"unknown action {action!r}")
    except PreconditionFailed as rejected:
        # The precondition text is the useful part: it tells the model what to try instead.
        raise ToolFailure(
            f"{rejected.action} rejected for {rejected.object_id}: {rejected.precondition}"
        ) from rejected

    payload = _diff_json(diff)
    payload["scenario_id"] = scenario_id
    payload["scenario_clock_utc"] = scenario.clock.isoformat()
    if action == "swap_aircraft":
        payload["available_tails"] = [
            {"tail_number": tail, "arrives_utc": arrival.isoformat()}
            for tail, arrival in context.actions.available_tails(scenario, flight_id)
        ]
    return payload


def dispatch(context: ToolContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route one tool call. Raises ToolFailure for anything the model should read and retry."""
    match name:
        case "find_objects":
            return _find_objects(context, arguments)
        case "traverse_links":
            return _traverse_links(context, arguments)
        case "simulate_action":
            return _simulate_action(context, arguments)
        case _:
            raise ToolFailure(f"no tool named {name!r}; available: {', '.join(sorted(TOOL_NAMES))}")
