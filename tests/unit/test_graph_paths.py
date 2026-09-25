"""
T21 to T24: full graph paths with a scripted fake decision provider. Retrieval,
web search, generation, and the similarity probe are replaced with fakes, so
no Qdrant, Tavily, or LLM is touched. The graph is rebuilt after patching,
because build_graph() binds node functions when it runs.
"""
import pytest
from langchain_core.documents import Document

import app.graph as graph
from app.decisions.base import DecisionMeta, GradeDecision, RouteDecision, VerifyDecision
from app.decisions.factory import override_decision_provider


class FakeProvider:
    name = "fake"

    def __init__(self, route="documents", relevant=(), verify=((True, True),)):
        self.route_value = route
        self.relevant = list(relevant)
        self.verify_results = list(verify)  # one (grounded, answers) per check; the last one repeats
        self.calls = []

    def _meta(self):
        return DecisionMeta(provider="fake", latency_ms=1.0)

    def route(self, question):
        self.calls.append("route")
        return RouteDecision(route=self.route_value, meta=self._meta())

    def grade(self, question, passages):
        self.calls.append("grade")
        return [GradeDecision(relevant=r, score=None, meta=self._meta()) for r in self.relevant[: len(passages)]]

    def verify(self, question, context, answer):
        self.calls.append("verify")
        grounded, answers = self.verify_results.pop(0) if len(self.verify_results) > 1 else self.verify_results[0]
        # Same contract as the real providers.
        if not context:
            grounded = None
        if grounded is False:
            answers = None
        return VerifyDecision(grounded=grounded, answers_question=answers, grounded_score=None, answers_score=None, meta=self._meta())


@pytest.fixture
def run_graph(monkeypatch):
    def _run(provider, retrieved=()):
        counts = {"retrieve": 0, "web_search": 0, "generate": 0}

        def fake_retrieve(state):
            counts["retrieve"] += 1
            docs = [Document(page_content=text) for text in retrieved]
            return {"documents": docs, "steps": state.get("steps", []) + [{"name": "retrieve", "detail": "fake"}], "documents_found": len(docs)}

        def fake_web_search(state):
            counts["web_search"] += 1
            docs = state.get("documents", []) + [Document(page_content="web result", metadata={"source": "tavily"})]
            return {"documents": docs, "steps": state.get("steps", []) + [{"name": "web search", "detail": "fake"}]}

        def fake_generate(state):
            counts["generate"] += 1
            context = "\n\n".join(d.page_content for d in state.get("documents", []))
            return {"generation": "an answer", "steps": state.get("steps", []) + [{"name": "generate", "detail": "fake"}], "context": context}

        monkeypatch.setattr(graph, "retrieve", fake_retrieve)
        monkeypatch.setattr(graph, "web_search", fake_web_search)
        monkeypatch.setattr(graph, "generate", fake_generate)
        monkeypatch.setattr(graph, "check_similarity_override", lambda question: (None, 0.0))

        override_decision_provider(provider)
        try:
            result = graph.build_graph().invoke({"question": "a question"})
        finally:
            override_decision_provider(None)
        return result, counts

    return _run


def step_names(result):
    return [s["name"] for s in result["steps"]]


# T21
def test_documents_path(run_graph):
    provider = FakeProvider(route="documents", relevant=[True, False, True])
    result, counts = run_graph(provider, retrieved=["a", "b", "c"])

    assert result["route"] == "documents"
    assert (result["documents_found"], result["documents_kept"]) == (3, 2)
    assert result["grounded"] is True
    assert result["retry_count"] == 0
    assert counts == {"retrieve": 1, "web_search": 0, "generate": 1}
    assert provider.calls == ["route", "grade", "verify"]
    assert [d["decision"] for d in result["decisions"]] == ["route", "grade", "verify"]
    assert result["decisions"][1]["result"] == "2/3 kept"
    assert step_names(result)[-2:] == ["grounding check", "answer check"]


# T22
def test_general_knowledge_path_skips_grounding(run_graph):
    provider = FakeProvider(route="general_knowledge")
    result, counts = run_graph(provider)

    assert counts == {"retrieve": 0, "web_search": 0, "generate": 1}
    assert result["grounded"] is None
    assert "grounding check" not in step_names(result)
    assert [d["decision"] for d in result["decisions"]] == ["route", "verify"]
    assert result["decisions"][1]["result"] == "answers"


# T23
def test_web_search_path(run_graph):
    provider = FakeProvider(route="web_search")
    result, counts = run_graph(provider)

    assert counts == {"retrieve": 0, "web_search": 1, "generate": 1}
    assert result["grounded"] is True
    assert result["route_decision"] == "end"


# T23
def test_no_relevant_documents_falls_back_to_web_search(run_graph):
    provider = FakeProvider(route="documents", relevant=[False, False])
    result, counts = run_graph(provider, retrieved=["a", "b"])

    assert counts == {"retrieve": 1, "web_search": 1, "generate": 1}
    assert result["documents_kept"] == 0
    assert "decision" in step_names(result)


# T24 (CLAUDE.md rule 4): the regenerate loop is capped.
def test_not_grounded_loop_stops_at_retry_cap(run_graph):
    provider = FakeProvider(route="web_search", verify=[(False, None)])
    result, counts = run_graph(provider)

    assert result["retry_count"] == 2
    assert counts["generate"] == 3
    assert step_names(result)[-1] == "retry limit"
    # The third check hits the guard before asking the provider.
    assert provider.calls.count("verify") == 2


# T24 (CLAUDE.md rule 4): the answer-check -> web search loop is capped too.
def test_unhelpful_answer_loop_stops_at_retry_cap(run_graph):
    provider = FakeProvider(route="web_search", verify=[(True, False)])
    result, counts = run_graph(provider)

    assert result["retry_count"] == 2
    assert counts == {"retrieve": 0, "web_search": 3, "generate": 3}
    assert step_names(result)[-1] == "retry limit"
