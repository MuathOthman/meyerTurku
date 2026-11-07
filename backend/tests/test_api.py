"""The routes the React frontend depends on. None of these need the source drawing."""
import copy
import threading
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

import api.main as api
from keel.decisions import DecisionInput, add_decision, read_decisions

DECISION = {"finding": "ESC-X:C-1", "rule_id": "ESC-X", "subject": "Corridor 1", "decision": "rejected", "note": "Not a route"}
CHECK = {"ref": "SOLAS X", "what": "Measured", "reference_confirmed": True, "status": "measured", "verdict": "PASS", "measured": "ok"}
RESULT = {
    "source": "x",
    "page": 2,
    "spaces": [
        {"number": 1, "name": "GALLEY", "category": "galley", "checklist": [CHECK], "reviewed": False},
        {"number": 2, "name": "Unidentified space", "category": "unknown", "checklist": [], "reviewed": False},
    ],
}
FAKE_RESULT = type("R", (), {"annotated": np.zeros((4, 4, 3), np.uint8), "plan": np.zeros((4, 4), np.uint8)})()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RESULTS", tmp_path / "analyses")
    monkeypatch.setattr(api, "JOBS", {})
    monkeypatch.setattr(api, "DECISIONS", tmp_path / "decisions.json")
    monkeypatch.setattr(api, "FRONTEND", tmp_path / "dist")
    monkeypatch.setattr(api, "analyze", lambda *a, **k: FAKE_RESULT)
    monkeypatch.setattr(api, "analysis_json", lambda r: copy.deepcopy(RESULT))
    monkeypatch.setattr(api, "get_llm", lambda: None)
    return TestClient(api.app)


def upload(client, name="deck.pdf"):
    return client.post("/api/analyze", files={"file": (name, b"data")}, data={"page": "2", "use_ai": "false"})


def wait_for(client, job):
    for _ in range(500):
        state = client.get(f"/api/analyze/{job}/status").json()
        if state["status"] != "running":
            return state
        time.sleep(0.01)
    raise AssertionError("the analysis did not finish")


def test_rules_list_has_status_and_source(client):
    rules = client.get("/api/rules").json()
    assert {"ESC-DEAD-END", "ACC-DOOR-CLEAR"} <= {r["id"] for r in rules}
    assert all(r["value_status"] in ("verified", "assumed") and r["source"] for r in rules)


def test_decisions_are_appended_and_keep_history(client):
    assert client.get("/api/decisions").json() == []
    assert client.post("/api/decisions", json=DECISION).status_code == 201
    client.post("/api/decisions", json={**DECISION, "decision": "cleared", "note": ""})
    log = client.get("/api/decisions").json()
    assert [d["decision"] for d in log] == ["rejected", "cleared"]
    assert log[0]["note"] == "Not a route" and log[0]["at"]


def test_unknown_decision_is_refused(client):
    assert client.post("/api/decisions", json={**DECISION, "decision": "approved"}).status_code == 422


def test_decision_log_file_round_trips(tmp_path):
    path = tmp_path / "nested" / "log.json"
    assert read_decisions(path) == []
    add_decision(path, DecisionInput(**DECISION))
    assert read_decisions(path)[0].finding == "ESC-X:C-1"
    assert not path.with_suffix(".tmp").exists()


def test_analysis_is_saved_listed_read_and_deleted(client):
    response = upload(client)
    assert response.status_code == 202
    job = response.json()["id"]
    assert wait_for(client, job)["status"] == "done"

    body = client.get(f"/api/analyze/{job}").json()
    assert body["image"] == f"/api/analyze/{job}/numbered.jpg" and body["source"] == "deck.pdf"
    assert client.get(body["image"]).headers["content-type"] == "image/jpeg"
    summary = client.get("/api/analyses").json()[0]
    assert (summary["id"], summary["identified"], summary["unidentified"], summary["page"]) == (job, 1, 1, 2)

    assert summary["status"] == "done"
    assert client.delete(f"/api/analyze/{job}").status_code == 204
    assert client.get(f"/api/analyze/{job}").status_code == 404
    assert client.get("/api/analyses").json() == []


def test_progress_is_reported_step_by_step(client, monkeypatch):
    release = threading.Event()
    seen = threading.Event()

    def slow(*args, on_step, **kwargs):
        on_step("First", "")
        on_step("Second", "1 of 2 views")
        seen.set()
        assert release.wait(5)
        return FAKE_RESULT

    monkeypatch.setattr(api, "analyze", slow)
    job = upload(client).json()["id"]
    assert seen.wait(5)
    state = client.get(f"/api/analyze/{job}/status").json()
    assert (state["status"], state["step"], state["detail"]) == ("running", "Second", "1 of 2 views")
    assert "First" in state["completed"]
    assert client.get("/api/analyses").json()[0]["status"] == "running"
    assert client.delete(f"/api/analyze/{job}").status_code == 409
    release.set()
    assert wait_for(client, job)["status"] == "done"


@pytest.mark.parametrize(
    "error, expected",
    [(ValueError("no page 99"), "Could not read this drawing: no page 99"), (RuntimeError("secret"), "failed unexpectedly")],
)
def test_failed_analysis_reports_why_and_leaves_nothing_behind(client, monkeypatch, error, expected):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(api, "analyze", fail)
    job = upload(client).json()["id"]
    state = wait_for(client, job)
    assert state["status"] == "failed" and expected in state["error"] and "secret" not in state["error"]
    assert not (api.RESULTS / job).exists()
    assert client.get("/api/analyses").json() == []


def finished(client):
    job = upload(client).json()["id"]
    assert wait_for(client, job)["status"] == "done"
    return job


def test_plan_image_is_served_clean(client):
    job = finished(client)
    assert client.get(f"/api/analyze/{job}").json()["plan_image"] == f"/api/analyze/{job}/plan.jpg"
    assert client.get(f"/api/analyze/{job}/plan.jpg").headers["content-type"] == "image/jpeg"


def test_renaming_gives_the_new_types_regulations_saves_and_logs(client):
    job = finished(client)
    body = client.patch(f"/api/analyze/{job}/spaces/2", json={"name": " Crew cabin 7 "}).json()
    space = body["spaces"][1]
    assert (space["name"], space["category"], space["reviewed"]) == ("Crew cabin 7", "cabin", True)
    assert any(c["ref"].startswith("MLC") for c in space["checklist"])
    assert client.get(f"/api/analyze/{job}").json()["spaces"][1]["name"] == "Crew cabin 7"
    entry = client.get("/api/decisions").json()[-1]
    assert entry["decision"] == "renamed" and "Was" in entry["note"]


def test_confirming_a_name_keeps_its_measurements(client):
    job = finished(client)
    space = client.patch(f"/api/analyze/{job}/spaces/1", json={"name": "GALLEY"}).json()["spaces"][0]
    assert space["reviewed"] and space["checklist"] == [CHECK]


def test_engineer_can_choose_the_type_and_it_beats_the_name(client):
    job = finished(client)
    space = client.patch(f"/api/analyze/{job}/spaces/1", json={"name": "GALLEY", "category": "stores"}).json()["spaces"][0]
    assert space["category"] == "stores" and space["checklist"] != [CHECK]


@pytest.mark.parametrize(
    "number, payload, status",
    [(99, {"name": "X"}, 404), (1, {"name": "   "}, 422), (1, {"name": ""}, 422), (1, {"name": "X", "category": "bogus"}, 422)],
)
def test_bad_corrections_are_refused_and_change_nothing(client, number, payload, status):
    job = finished(client)
    assert client.patch(f"/api/analyze/{job}/spaces/{number}", json=payload).status_code == status
    assert client.get(f"/api/analyze/{job}").json()["spaces"][0]["name"] == "GALLEY"
    assert client.get("/api/decisions").json() == []


def test_space_types_include_every_listed_type(client):
    assert {"cabin", "galley", "unknown"} <= set(client.get("/api/space-types").json())


def test_unknown_ship_type_is_refused(client):
    response = client.post("/api/analyze", files={"file": ("d.pdf", b"x")}, data={"ship_type": "yacht"})
    assert response.status_code == 422


def test_cargo_rules_use_the_cargo_limits(client):
    cargo = {r["id"]: r for r in client.get("/api/rules/cargo").json()}
    passenger = {r["id"]: r for r in client.get("/api/rules/passenger").json()}
    assert cargo["ESC-CORRIDOR-WIDTH"]["value_mm"] == 700 and passenger["ESC-CORRIDOR-WIDTH"]["value_mm"] == 900
    assert cargo["ESC-DOOR-WIDTH"]["value_status"] == "verified" and passenger["ESC-DOOR-WIDTH"]["value_status"] == "assumed"
    assert "cargo" in cargo["ESC-STAIR-WIDTH"]["source"]


def test_unsupported_file_is_refused_at_once(client):
    assert upload(client, "deck.docx").status_code == 400


def test_unfinished_analysis_is_not_listed(client):
    (api.RESULTS / ("a" * 32)).mkdir(parents=True)
    assert client.get("/api/analyses").json() == []
    assert client.get(f"/api/analyze/{'a' * 32}").status_code == 404


@pytest.mark.parametrize("job", ["nothex", "A" * 32])
def test_bad_job_ids_are_refused(client, job):
    assert client.delete(f"/api/analyze/{job}").status_code == 404
    assert client.get(f"/api/analyze/{job}").status_code == 404


def test_frontend_routes_files_and_traversal(client, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<app>")
    (dist / "assets" / "a.js").write_text("js")
    (tmp_path / "secret.txt").write_text("secret")

    assert client.get("/").text == "<app>"
    assert client.get("/app/rules").text == "<app>"
    assert client.get("/assets/a.js").text == "js"
    assert "secret" not in client.get("/%2e%2e/secret.txt").text
    assert client.get("/api/missing").status_code == 404
    assert client.get("/assets/missing.js").status_code == 404


def test_without_a_build_the_server_says_how_to_build(client):
    response = client.get("/")
    assert response.status_code == 404 and "npm" in response.json()["detail"]
