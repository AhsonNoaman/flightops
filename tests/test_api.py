"""API tests: the read surface is honest, the sandbox is real, and the gate holds.

Two of these matter more than the rest. The scenario-isolation test is the load-bearing claim of
DESIGN.md section 7 -- two callers holding contradictory hypotheticals over one read-only file --
and if it ever fails the deployed app is silently sharing state between strangers. The env-gate
test is what keeps a public URL from spending money.

The app is exercised through TestClient rather than by calling the handlers, so route ordering is
covered too: every flight id contains slashes-free pipes but the path converter still has to
prefer `/rotation` and `/cascade` over the catch-all detail route.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flightops.api import app as api
from flightops.ingest.loader import connect, load_month, load_reference
from flightops.ingest.rotation import derive_next_leg

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_CSV = REPO_ROOT / "data" / "sample" / "bts_wn_2026_01_w1.csv.gz"

ROOT = "2026-01-03|WN|3851|PHX|SFO|0855"


@pytest.fixture(scope="module")
def client(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch_module: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    database = tmp_path_factory.mktemp("api") / "sample.duckdb"
    connection = connect(database)
    load_reference(connection)
    load_month(connection, SAMPLE_CSV)
    derive_next_leg(connection)
    connection.close()
    monkeypatch_module.setenv("FLIGHTOPS_DB", str(database))
    monkeypatch_module.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(api.app) as opened:
        yield opened


@pytest.fixture(scope="module")
def monkeypatch_module() -> Iterator[pytest.MonkeyPatch]:
    """A module-scoped monkeypatch, since the app is built once per module."""
    patch = pytest.MonkeyPatch()
    yield patch
    patch.undo()


# -- reads ------------------------------------------------------------------------------------


def test_health_reports_the_window_that_was_loaded(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["flight_count"] == 26161
    assert body["first_date"] == "2026-01-01"
    assert body["last_date"] == "2026-01-07"
    assert body["carriers"] == ["WN"]
    assert body["live_answers"] is False


def test_flight_detail_resolves_the_links_in_one_call(client: TestClient) -> None:
    body = client.get(f"/api/flights/{ROOT}").json()
    assert body["flight"]["dep_delay_minutes"] == 142
    assert body["aircraft"]["tail_number"] == "N8633A"
    assert body["origin_airport"]["iata"] == "PHX"
    assert body["operating_carrier"]["code"] == "WN"
    assert body["next_leg"]["flight_id"] == "2026-01-03|WN|4106|SFO|PHX|1055"
    assert body["ground_minutes_after"] == 50


def test_a_broken_chain_is_reported_with_its_reason(client: TestClient) -> None:
    body = client.get("/api/flights/2026-01-07|WN|1016|BWI|RSW|1430").json()
    assert body["next_leg"] is None
    assert body["chain_break_reason"] == "impossible_turn"


def test_the_rotation_route_wins_over_the_catch_all_detail_route(client: TestClient) -> None:
    legs = client.get(f"/api/flights/{ROOT}/rotation").json()
    assert len(legs) == 7
    assert legs[0]["origin"] == "MSY"
    assert legs[-1]["destination"] == "HOU"


def test_cascade_defaults_to_the_delay_the_flight_actually_had(client: TestClient) -> None:
    body = client.get(f"/api/flights/{ROOT}/cascade").json()
    assert body["root_delay_minutes"] == 142
    assert body["total_propagated_minutes"] == 565
    assert len(body["affected"]) == 5


def test_cascade_accepts_a_counterfactual_delay(client: TestClient) -> None:
    body = client.get(f"/api/flights/{ROOT}/cascade", params={"minutes": 20}).json()
    assert body["total_propagated_minutes"] == 5
    assert body["termination"] == "absorbed"


def test_disruptions_rank_by_downstream_minutes_not_by_delay(client: TestClient) -> None:
    """The product judgement in propagation/events.py, asserted rather than assumed."""
    events = client.get("/api/disruptions", params={"date": "2026-01-03", "limit": 10}).json()
    assert events
    totals = [event["total_propagated_minutes"] for event in events]
    assert totals == sorted(totals, reverse=True)
    assert len({event["tail_number"] for event in events}) == len(events)
    assert all(event["cause"] != "late_aircraft" for event in events)


def test_the_ranking_reaches_the_end_of_the_day(client: TestClient) -> None:
    """Regression: the candidate fetch used to cut off mid-evening.

    `find_flights` orders by scheduled departure, so a limit below a full day silently drops the
    late roots. On 2026-01-03 that hid 104 legs delayed 100 minutes or more, all after 23:10
    UTC, and the ranking still looked right because that day's worst root departs in the
    morning. WN4124 PHX-SFO leaves at 01:40 UTC on the 4th and belongs near the top.
    """
    events = client.get("/api/disruptions", params={"date": "2026-01-03", "limit": 10}).json()
    roots = [event["root_flight_id"] for event in events]
    assert "2026-01-03|WN|4124|PHX|SFO|1840" in roots
    assert max(event["affected"][-1]["projected_dep_utc"] for event in events) > "2026-01-04"


def test_a_date_outside_the_loaded_window_is_rejected_with_the_window(client: TestClient) -> None:
    """The cache is keyed on the date, so an unbounded date is an unbounded number of keys."""
    response = client.get("/api/disruptions", params={"date": "1999-01-01"})
    assert response.status_code == 422
    assert "2026-01-01 to 2026-01-07" in response.json()["detail"]


def test_the_ranking_is_cached_and_still_returns_a_fresh_list(client: TestClient) -> None:
    first = client.get("/api/disruptions", params={"date": "2026-01-03", "limit": 5}).json()
    second = client.get("/api/disruptions", params={"date": "2026-01-03", "limit": 5}).json()
    assert first == second
    assert len(first) == 5


def test_an_unknown_flight_is_a_404_naming_the_id(client: TestClient) -> None:
    response = client.get("/api/flights/not-a-flight")
    assert response.status_code == 404
    assert "not-a-flight" in response.json()["detail"]


# -- scenarios --------------------------------------------------------------------------------


def test_a_scenario_applies_a_delay_and_reports_the_cascade(client: TestClient) -> None:
    session = client.post("/api/scenarios", json={"flight_id": ROOT}).json()
    response = client.post(
        f"/api/scenarios/{session['session_id']}/actions",
        json={
            "action": "delay_flight",
            "flight_id": ROOT,
            "additional_minutes": 142,
            "reason": "nas",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["diff"]["net_minutes"] == 565
    assert body["scenario"]["actions_applied"] == 1


def test_two_sessions_over_one_read_only_file_do_not_see_each_other(client: TestClient) -> None:
    """The claim DESIGN.md section 7 makes about deploying an immutable database."""
    first = client.post("/api/scenarios", json={"flight_id": ROOT}).json()["session_id"]
    second = client.post("/api/scenarios", json={"flight_id": ROOT}).json()["session_id"]
    client.post(
        f"/api/scenarios/{first}/actions",
        json={
            "action": "delay_flight",
            "flight_id": ROOT,
            "additional_minutes": 142,
            "reason": "nas",
        },
    )
    assert client.get(f"/api/scenarios/{first}").json()["actions_applied"] == 1
    assert client.get(f"/api/scenarios/{second}").json()["actions_applied"] == 0

    # And the base data is untouched, which is the part that would be catastrophic to get wrong.
    assert client.get(f"/api/flights/{ROOT}").json()["flight"]["dep_delay_minutes"] == 142


def test_stacking_a_swap_on_a_delay_measures_the_recovery(client: TestClient) -> None:
    session = client.post("/api/scenarios", json={"flight_id": ROOT}).json()["session_id"]
    client.post(
        f"/api/scenarios/{session}/actions",
        json={
            "action": "delay_flight",
            "flight_id": ROOT,
            "additional_minutes": 142,
            "reason": "nas",
        },
    )
    body = client.post(
        f"/api/scenarios/{session}/actions",
        json={"action": "swap_aircraft", "flight_id": ROOT, "replacement_tail": "N8528Q"},
    ).json()
    assert body["diff"]["net_minutes"] == -565
    assert any("remaining line of flying" in warning for warning in body["diff"]["warnings"])


def test_a_rejected_action_returns_409_with_the_precondition(client: TestClient) -> None:
    session = client.post("/api/scenarios", json={"flight_id": ROOT}).json()["session_id"]
    response = client.post(
        f"/api/scenarios/{session}/actions",
        json={"action": "swap_aircraft", "flight_id": ROOT, "replacement_tail": "N00000"},
    )
    assert response.status_code == 409
    assert "N00000" in response.json()["detail"]


def test_an_expired_or_unknown_session_is_a_404(client: TestClient) -> None:
    response = client.get("/api/scenarios/nope")
    assert response.status_code == 404
    assert "expired" in response.json()["detail"]


def test_swap_candidates_are_listed_before_committing_to_a_scenario(client: TestClient) -> None:
    candidates = client.get(f"/api/flights/{ROOT}/swap-candidates").json()
    assert candidates
    assert all({"tail_number", "arrives_utc"} == set(entry) for entry in candidates)


# -- the gate and the published eval ------------------------------------------------------------


def test_live_answering_is_off_without_a_key_and_says_why(client: TestClient) -> None:
    response = client.post("/api/ask", json={"question": "How late was WN3851?"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "ANTHROPIC_API_KEY" in detail
    assert "/api/eval" in detail


def test_the_eval_endpoint_serves_the_questions_even_with_no_run_recorded(
    client: TestClient,
) -> None:
    body = client.get("/api/eval").json()
    assert len(body["questions"]) == 10
    assert all(question["reference"] for question in body["questions"])
    if not body["recorded"]:
        assert body["ontology_score"] == "not run"
        assert "no eval run" in body["note"].lower()
