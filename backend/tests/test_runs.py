import json
import time

from tests.test_auth_registry import login


def wait_for(client, headers, run_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/runs/{run_id}", headers=headers).json()
        if detail["run"]["status"] != "running":
            return detail
        time.sleep(0.3)
    raise AssertionError("run did not finish")


def test_research_crew_end_to_end(client):
    viewer = login(client, "demo", "demo")  # the public demo account can start runs
    res = client.post("/runs", json={"task": "Prepare a customer brief for Acme Corp"}, headers=viewer)
    assert res.status_code == 201, res.text
    run_id = res.json()["id"]

    detail = wait_for(client, viewer, run_id)
    run = detail["run"]
    assert run["status"] == "succeeded", run["output"]
    assert run["mode"] == "scripted"
    out = run["output"]
    assert "## Acme Corp" in out and "<PERSON>" in out  # personal data stayed masked
    assert "priya.sharma@" not in out and "blocked by policy" in out
    assert out.strip().endswith(".") and "Approved" in out

    # Traces: one run span, four agent spans, and tool/llm/a2a spans parented to agents
    spans = detail["spans"]
    agents = {s["name"]: s["id"] for s in spans if s["kind"] == "agent"}
    assert set(agents) == {"planner", "researcher", "writer", "reviewer"}
    assert [s for s in spans if s["kind"] == "run"][0]["id"] == f"run-{run_id}"
    assert all(s["parent_id"] == f"run-{run_id}" for s in spans if s["kind"] == "agent")
    tool_spans = [s for s in spans if s["kind"] == "tool"]
    assert tool_spans and all(s["parent_id"] in agents.values() for s in tool_spans)

    # Governance: the contract lookup was denied and audited; PII was masked
    denied = [a for a in detail["audit"] if a["decision"] == "denied"]
    assert [(a["tool"], a["principal"]) for a in denied] == [("get_contract", "research-crew")]
    assert sum(a["pii_masked"] for a in detail["audit"]) > 0

    # Hand-offs went through A2A in order
    assert [(m["sender"], m["recipient"]) for m in detail["messages"]] == [
        ("planner", "researcher"),
        ("researcher", "writer"),
        ("writer", "reviewer"),
        ("reviewer", "planner"),
    ]


def test_run_events_stream(client):
    viewer = login(client, "demo", "demo")
    run_id = client.post("/runs", json={"task": "Brief on Globex"}, headers=viewer).json()["id"]
    token = viewer["Authorization"].split()[1]
    events = []
    with client.stream("GET", f"/runs/{run_id}/events", params={"token": token}) as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1]["type"] == "run_finished":
                    break
    types = [e["type"] for e in events]
    assert types[0] == "run_started" and types[-1] == "run_finished"
    assert {"agent_started", "tool_call", "llm", "a2a"} <= set(types)
    denied = [e for e in events if e["type"] == "tool_call" and e["decision"] == "denied"]
    assert denied and denied[0]["tool"] == "get_contract"
    assert events[-1]["status"] == "succeeded"


def test_events_require_auth_and_validation(client):
    viewer = login(client, "demo", "demo")
    assert client.get("/runs/nope/events").status_code == 401
    assert client.get("/runs/nope/events", headers=viewer).status_code == 404
    assert client.post("/runs", json={"task": "x"}, headers=viewer).status_code == 422
