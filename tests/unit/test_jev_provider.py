"""T08 to T13: the Jev provider, with a scripted fake client (no network)."""
import threading
import time

import pytest

from app.decisions.base import JevDecisionError
from app.decisions.jev_client import JevResponse
from app.decisions.jev_provider import JevDecisionProvider, load_questions

QUESTIONS = load_questions()


class FakeClient:
    """Answers each ask() with answer_fn(state, questions); records every call."""

    def __init__(self, answer_fn):
        self.answer_fn = answer_fn
        self.calls = []
        self._lock = threading.Lock()

    def ask(self, state, questions):
        with self._lock:
            self.calls.append((state, questions))
        answers = self.answer_fn(state, questions)
        if isinstance(answers, Exception):
            raise answers
        return JevResponse(answers=answers, model="typesafe-ai/jev", latency_ms=5.0, input_tokens=300, output_tokens=20, cost_usd=0.0, market_cost_usd=0.00001)


def provider(answer_fn, **overrides):
    config = {"route_min_confidence": 0.6, "grade_threshold": 0.5, "max_concurrency": 3, "max_state_chars": 60000, **overrides}
    client = FakeClient(answer_fn)
    return JevDecisionProvider(client=client, questions=QUESTIONS, **config), client


def route_answer(choice, confidence=0.95):
    return lambda state, questions: {"route": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {choice: confidence}}}


# T08
@pytest.mark.parametrize("choice", ["documents", "code", "web_search", "general_knowledge"])
def test_route_maps_each_choice_to_v1_route(choice):
    p, client = provider(route_answer(choice))
    decision = p.route("some question")
    assert decision.route == choice
    assert (decision.meta.provider, decision.meta.confidence, decision.meta.model) == ("jev", 0.95, "typesafe-ai/jev")
    state, questions = client.calls[0]
    assert state == {"question": "some question"}
    assert questions == {"route": QUESTIONS["route"]}


def test_route_question_offers_unclear_option():
    assert set(QUESTIONS["route"]["criteria"]) == {"documents", "code", "web_search", "general_knowledge", "unclear"}


# T09
def test_route_unclear_raises():
    p, _ = provider(route_answer("unclear", 0.9))
    with pytest.raises(JevDecisionError) as info:
        p.route("asdkjh qwe zzz")
    assert info.value.reason == "unclear"
    assert info.value.detail["choice"] == "unclear"


# T10
def test_route_low_confidence_raises():
    p, _ = provider(route_answer("documents", 0.4))
    with pytest.raises(JevDecisionError) as info:
        p.route("q")
    assert (info.value.reason, info.value.detail["confidence"]) == ("low_confidence", 0.4)


def test_route_unknown_choice_is_bad_response():
    p, _ = provider(route_answer("vectorstore"))
    with pytest.raises(JevDecisionError) as info:
        p.route("q")
    assert info.value.reason == "bad_response"


# T13
def test_oversized_state_raises_without_calling_jev():
    p, client = provider(route_answer("documents"), max_state_chars=50)
    with pytest.raises(JevDecisionError) as info:
        p.route("x" * 100)
    assert info.value.reason == "state_too_large"
    assert client.calls == []


# T11
def test_grade_applies_threshold_per_chunk_and_sends_one_chunk_per_call():
    scores = {"a": 0.9, "b": 0.49, "c": 0.5}
    p, client = provider(lambda state, questions: {"grade": {"type": "noul", "noul": scores[state["passage"]]}})
    grades = p.grade("q", ["a", "b", "c"])
    assert [(g.relevant, g.score) for g in grades] == [(True, 0.9), (False, 0.49), (True, 0.5)]
    assert all(g.meta.provider == "jev" for g in grades)
    assert sorted(state["passage"] for state, _ in client.calls) == ["a", "b", "c"]
    assert all(state == {"question": "q", "passage": state["passage"]} and questions == {"grade": QUESTIONS["grade"]} for state, questions in client.calls)


# T11
def test_grade_keeps_order_and_respects_concurrency_cap():
    in_flight, peak, lock = [0], [0], threading.Lock()

    def answer(state, questions):
        with lock:
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
        # Earlier chunks finish later, so a naive "collect as completed" would reorder them.
        time.sleep(0.05 * (10 - int(state["passage"])) / 10)
        with lock:
            in_flight[0] -= 1
        return {"grade": {"type": "noul", "noul": int(state["passage"]) / 10}}

    p, _ = provider(answer, max_concurrency=3)
    passages = [str(i) for i in range(8)]
    grades = p.grade("q", passages)
    assert [g.score for g in grades] == [i / 10 for i in range(8)]
    assert 1 < peak[0] <= 3


# T11
def test_grade_each_returns_error_only_for_failed_chunk():
    def answer(state, questions):
        if state["passage"] == "b":
            return JevDecisionError("rate_limited", {"status_code": 429})
        return {"grade": {"type": "noul", "noul": 0.8}}

    p, _ = provider(answer)
    results = p.grade_each("q", ["a", "b", "c"])
    assert [type(r).__name__ for r in results] == ["GradeDecision", "JevDecisionError", "GradeDecision"]
    assert results[1].reason == "rate_limited"
    with pytest.raises(JevDecisionError):
        p.grade("q", ["a", "b", "c"])


def test_grade_with_no_passages_makes_no_call():
    p, client = provider(lambda s, q: {})
    assert p.grade("q", []) == []
    assert client.calls == []
