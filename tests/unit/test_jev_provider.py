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
    config = {"route_min_confidence": 0.6, "max_state_chars": 60000, **overrides}
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
