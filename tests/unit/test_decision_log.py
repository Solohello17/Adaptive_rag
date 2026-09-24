"""T19: decision logging (no MongoDB needed; the writer is replaced or pointed at a dead port)."""
import json

from langgraph.graph import END, START, StateGraph
from typing import TypedDict

import app.decisions.factory as factory
from app.decisions.base import DecisionMeta, GradeDecision, RouteDecision, VerifyDecision
from app.decisions.decision_log import PREVIEW_CHARS, LoggedProvider, MongoDecisionLog, request_id_var


class MemoryLog:
    def __init__(self):
        self.documents = []

    def write(self, documents):
        self.documents.extend(documents)


class StubProvider:
    name = "jev"

    def route(self, question):
        return RouteDecision(route="documents", meta=DecisionMeta(provider="jev", latency_ms=500.0, model="typesafe-ai/jev", confidence=0.97, probabilities={"documents": 0.97}, input_tokens=460, cost_usd=0.0, market_cost_usd=0.000014))

    def grade(self, question, passages):
        return [
            GradeDecision(relevant=True, score=0.9, meta=DecisionMeta(provider="jev", latency_ms=800.0)),
            GradeDecision(relevant=True, score=None, meta=DecisionMeta(provider="llm", latency_ms=3000.0, fallback_reason="rate_limited", jev_attempt={"status_code": 429})),
        ][: len(passages)]

    def verify(self, question, context, answer):
        return VerifyDecision(grounded=True, answers_question=False, grounded_score=0.95, answers_score=0.2, meta=DecisionMeta(provider="jev", latency_ms=600.0))


def logged():
    log = MemoryLog()
    return LoggedProvider(StubProvider(), log, app_version="2.0.0-test"), log


# T19
def test_one_document_per_decision_with_request_id():
    provider, log = logged()
    token = request_id_var.set("req-123")
    try:
        provider.route("q")
        provider.grade("q", ["passage one", "passage two"])
        provider.verify("q", "ctx", "ans")
    finally:
        request_id_var.reset(token)

    assert [d["decision"] for d in log.documents] == ["route", "grade", "grade", "verify"]
    assert {d["request_id"] for d in log.documents} == {"req-123"}
    assert {d["app_version"] for d in log.documents} == {"2.0.0-test"}

    route = log.documents[0]
    assert (route["provider"], route["result"], route["confidence"], route["input_tokens"], route["market_cost_usd"]) == ("jev", "documents", 0.97, 460, 0.000014)

    fell_back = log.documents[2]
    assert (fell_back["provider"], fell_back["fallback_reason"], fell_back["jev_attempt"]) == ("llm", "rate_limited", {"status_code": 429})
    assert fell_back["passage_preview"] == "passage two"

    verify = log.documents[3]
    assert verify["result"] == {"grounded": True, "answers_question": False}
    assert verify["score"] == {"grounded": 0.95, "answers_question": 0.2}
    assert "passage_preview" not in verify


# T19 (NFR5): only previews of user text are stored.
def test_only_previews_are_stored():
    provider, log = logged()
    long_question, long_passage = "q" * 1000, "p" * 5000
    provider.route(long_question)
    provider.grade(long_question, [long_passage])
    provider.verify(long_question, "c" * 5000, "a" * 5000)

    for document in log.documents:
        assert len(document["query_preview"]) == PREVIEW_CHARS
        assert len(document.get("passage_preview", "")) <= PREVIEW_CHARS
        # No full context or answer anywhere in the document.
        assert "c" * (PREVIEW_CHARS + 1) not in json.dumps(document, default=str)
        assert "a" * (PREVIEW_CHARS + 1) not in json.dumps(document, default=str)


# T19
def test_decisions_pass_through_unchanged():
    provider, _ = logged()
    stub = StubProvider()
    assert provider.route("q") == stub.route("q")
    assert provider.verify("q", "c", "a") == stub.verify("q", "c", "a")
    assert provider.name == "jev"


# T19: a dead MongoDB must not break the query.
def test_mongo_failure_is_swallowed():
    log = MongoDecisionLog("mongodb://127.0.0.1:1")  # nothing listens on port 1
    provider = LoggedProvider(StubProvider(), log, app_version="x")
    assert provider.route("q").route == "documents"


def test_empty_grade_writes_nothing():
    provider, log = logged()
    provider.grade("q", [])
    assert log.documents == []


# The request_id contextvar must survive LangGraph's node execution, or every
# log from a real query would have request_id=None.
def test_request_id_reaches_graph_nodes():
    class State(TypedDict):
        seen: str

    workflow = StateGraph(State)
    workflow.add_node("read", lambda state: {"seen": request_id_var.get()})
    workflow.add_edge(START, "read")
    workflow.add_edge("read", END)

    token = request_id_var.set("req-graph")
    try:
        result = workflow.compile().invoke({"seen": ""})
    finally:
        request_id_var.reset(token)
    assert result["seen"] == "req-graph"


def test_factory_wraps_with_logging_when_enabled(monkeypatch):
    factory._build_from_settings.cache_clear()
    monkeypatch.setattr(factory.settings, "DECISION_PROVIDER", "llm")
    monkeypatch.setattr(factory.settings, "JEV_LOG_DECISIONS", True)
    try:
        provider = factory.get_decision_provider()
        assert isinstance(provider, LoggedProvider)
        assert provider.name == "llm"
    finally:
        factory._build_from_settings.cache_clear()
