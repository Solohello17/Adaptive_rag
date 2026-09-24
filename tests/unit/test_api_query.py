"""
T25: POST /query returns the optional `decisions` field and leaves every v1
field unchanged. The graph is replaced with a stub, and TestClient is used
without its context manager so startup (Qdrant, embeddings) does not run.
"""
from fastapi.testclient import TestClient

import app.main as main
from app.decisions.decision_log import request_id_var

V1_FIELDS = {"answer", "route", "documents_found", "documents_kept", "grounded", "retry_count", "failed", "steps"}

FINAL_STATE = {
    "generation": "The subject code is 3170724.",
    "route": "documents",
    "documents": ["chunk"],
    "documents_found": 8,
    "documents_kept": 6,
    "grounded": True,
    "retry_count": 0,
    "steps": [{"name": "route", "detail": "matches documents"}, {"name": "answer check", "detail": "passed"}],
    "decisions": [
        {"decision": "route", "provider": "jev", "result": "documents", "confidence": 0.98, "latency_ms": 784.0, "fallback_reason": None},
        {"decision": "grade", "provider": "mixed", "result": "6/8 kept", "confidence": None, "latency_ms": 1666.0, "fallback_reason": "rate_limited", "fallback_count": 1},
        {"decision": "verify", "provider": "jev", "result": "grounded, answers", "confidence": None, "latency_ms": 780.0, "fallback_reason": None},
    ],
}


class StubGraph:
    def __init__(self, state):
        self.state = state
        self.seen_request_ids = []

    def invoke(self, initial_state):
        self.seen_request_ids.append(request_id_var.get())
        return self.state


def post(monkeypatch, state):
    graph = StubGraph(state)
    monkeypatch.setattr(main, "rag_app", graph)
    response = TestClient(main.app).post("/query", json={"question": "What is the subject code?"})
    return response, graph


# T25
def test_query_returns_decisions_and_unchanged_v1_fields(monkeypatch):
    response, _ = post(monkeypatch, FINAL_STATE)
    assert response.status_code == 200
    body = response.json()

    assert set(body) == V1_FIELDS | {"decisions"}
    assert (body["answer"], body["route"], body["documents_kept"], body["grounded"], body["failed"]) == ("The subject code is 3170724.", "documents", 6, True, False)
    assert [d["decision"] for d in body["decisions"]] == ["route", "grade", "verify"]
    assert body["decisions"][1]["fallback_count"] == 1
    assert body["decisions"][0]["fallback_count"] is None


# T25
def test_query_without_decisions_in_state_returns_empty_list(monkeypatch):
    state = {k: v for k, v in FINAL_STATE.items() if k != "decisions"}
    response, _ = post(monkeypatch, state)
    assert response.status_code == 200
    assert response.json()["decisions"] == []


def test_each_query_gets_its_own_request_id_and_it_is_reset(monkeypatch):
    graph = StubGraph(FINAL_STATE)
    monkeypatch.setattr(main, "rag_app", graph)
    client = TestClient(main.app)
    client.post("/query", json={"question": "a"})
    client.post("/query", json={"question": "b"})
    first, second = graph.seen_request_ids
    assert first and second and first != second
    assert request_id_var.get() is None
