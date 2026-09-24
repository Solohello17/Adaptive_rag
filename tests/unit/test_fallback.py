"""T16 to T18, T20: per-decision fallback and the jev factory branch (no network)."""
import pytest

import app.decisions.factory as factory
from app.decisions.base import DecisionMeta, GradeDecision, JevDecisionError, RouteDecision, VerifyDecision
from app.decisions.fallback import FallbackProvider


def meta(provider):
    return DecisionMeta(provider=provider, latency_ms=1.0)


class ScriptedJev:
    """Returns a value or raises, per method, as scripted."""
    name = "jev"

    def __init__(self, route=None, grade_each=None, verify=None):
        self._route, self._grade_each, self._verify = route, grade_each, verify

    def route(self, question):
        if isinstance(self._route, Exception):
            raise self._route
        return self._route

    def grade_each(self, question, passages):
        return list(self._grade_each)

    def verify(self, question, context, answer):
        if isinstance(self._verify, Exception):
            raise self._verify
        return self._verify


class RecordingLLM:
    name = "llm"

    def __init__(self):
        self.calls = []

    def route(self, question):
        self.calls.append(("route", question))
        return RouteDecision(route="general_knowledge", meta=meta("llm"))

    def grade(self, question, passages):
        self.calls.append(("grade", list(passages)))
        return [GradeDecision(relevant=True, score=None, meta=meta("llm")) for _ in passages]

    def verify(self, question, context, answer):
        self.calls.append(("verify", question))
        return VerifyDecision(grounded=True, answers_question=True, grounded_score=None, answers_score=None, meta=meta("llm"))


# T16
def test_route_success_does_not_touch_llm():
    llm = RecordingLLM()
    jev_decision = RouteDecision(route="documents", meta=meta("jev"))
    decision = FallbackProvider(ScriptedJev(route=jev_decision), llm).route("q")
    assert decision is jev_decision
    assert llm.calls == []


# T16
def test_route_failure_falls_back_and_records_reason_and_attempt():
    llm = RecordingLLM()
    error = JevDecisionError("unclear", {"choice": "unclear", "confidence": 0.98, "latency_ms": 480.0})
    decision = FallbackProvider(ScriptedJev(route=error), llm).route("asdkjh")
    assert decision.route == "general_knowledge"
    assert decision.meta.provider == "llm"
    assert decision.meta.fallback_reason == "unclear"
    assert decision.meta.jev_attempt == {"choice": "unclear", "confidence": 0.98, "latency_ms": 480.0}
    assert llm.calls == [("route", "asdkjh")]


# T16
def test_verify_failure_falls_back():
    llm = RecordingLLM()
    decision = FallbackProvider(ScriptedJev(verify=JevDecisionError("timeout", {})), llm).verify("q", "ctx", "ans")
    assert (decision.meta.provider, decision.meta.fallback_reason) == ("llm", "timeout")
    assert llm.calls == [("verify", "q")]


# T17
def test_grade_sends_only_failed_chunks_to_llm_in_one_call():
    llm = RecordingLLM()
    jev_results = [
        GradeDecision(relevant=False, score=0.1, meta=meta("jev")),
        JevDecisionError("rate_limited", {"status_code": 429}),
        GradeDecision(relevant=True, score=0.9, meta=meta("jev")),
        JevDecisionError("timeout", {}),
    ]
    grades = FallbackProvider(ScriptedJev(grade_each=jev_results), llm).grade("q", ["a", "b", "c", "d"])

    assert llm.calls == [("grade", ["b", "d"])]
    assert [g.meta.provider for g in grades] == ["jev", "llm", "jev", "llm"]
    assert [g.meta.fallback_reason for g in grades] == [None, "rate_limited", None, "timeout"]
    assert [g.relevant for g in grades] == [False, True, True, True]


# T17
def test_grade_with_no_failures_makes_no_llm_call():
    llm = RecordingLLM()
    jev_results = [GradeDecision(relevant=True, score=0.9, meta=meta("jev"))]
    FallbackProvider(ScriptedJev(grade_each=jev_results), llm).grade("q", ["a"])
    assert llm.calls == []


# T18
def test_disabled_fallback_raises_jev_error():
    llm = RecordingLLM()
    provider = FallbackProvider(ScriptedJev(route=JevDecisionError("rate_limited", {}), grade_each=[JevDecisionError("timeout", {})]), llm, enabled=False)
    with pytest.raises(JevDecisionError, match="rate_limited"):
        provider.route("q")
    with pytest.raises(JevDecisionError, match="timeout"):
        provider.grade("q", ["a"])
    assert llm.calls == []


def test_non_jev_errors_are_not_swallowed():
    llm = RecordingLLM()
    with pytest.raises(KeyError):
        FallbackProvider(ScriptedJev(route=KeyError("bug")), llm).route("q")
    assert llm.calls == []


@pytest.fixture
def fresh_factory(monkeypatch):
    factory._build_from_settings.cache_clear()
    yield monkeypatch
    factory._build_from_settings.cache_clear()


# T20
def test_jev_without_key_fails_fast(fresh_factory):
    fresh_factory.setattr(factory.settings, "DECISION_PROVIDER", "jev")
    fresh_factory.setattr(factory.settings, "AI_GATEWAY_API_KEY", None)
    with pytest.raises(ValueError, match="AI_GATEWAY_API_KEY"):
        factory.get_decision_provider()


def test_jev_with_key_builds_fallback_stack(fresh_factory):
    fresh_factory.setattr(factory.settings, "DECISION_PROVIDER", "jev")
    fresh_factory.setattr(factory.settings, "AI_GATEWAY_API_KEY", "dummy-key-for-test")
    fresh_factory.setattr(factory.settings, "JEV_FALLBACK_TO_LLM", False)
    provider = factory.get_decision_provider()
    assert isinstance(provider, FallbackProvider)
    assert provider.name == "jev" and provider.enabled is False
    assert provider.jev.route_min_confidence == factory.settings.JEV_ROUTE_MIN_CONFIDENCE
