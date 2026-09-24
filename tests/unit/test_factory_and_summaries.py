import pytest

import app.decisions.factory as factory
from app.decisions.base import DecisionMeta, GradeDecision, VerifyDecision, grade_summary, verify_summary
from app.decisions.llm_provider import LLMDecisionProvider


@pytest.fixture
def fresh_factory(monkeypatch):
    factory._build_from_settings.cache_clear()
    yield monkeypatch
    factory._build_from_settings.cache_clear()
    factory.override_decision_provider(None)


def test_llm_setting_builds_llm_provider(fresh_factory):
    fresh_factory.setattr(factory.settings, "DECISION_PROVIDER", "llm")
    assert isinstance(factory.get_decision_provider(), LLMDecisionProvider)


def test_unknown_setting_raises(fresh_factory):
    fresh_factory.setattr(factory.settings, "DECISION_PROVIDER", "nope")
    with pytest.raises(ValueError, match="Unsupported DECISION_PROVIDER"):
        factory.get_decision_provider()


def test_override_wins_and_resets(fresh_factory):
    fresh_factory.setattr(factory.settings, "DECISION_PROVIDER", "llm")
    sentinel = object()
    factory.override_decision_provider(sentinel)
    assert factory.get_decision_provider() is sentinel
    factory.override_decision_provider(None)
    assert isinstance(factory.get_decision_provider(), LLMDecisionProvider)


def _grade(relevant, provider, reason=None):
    return GradeDecision(relevant=relevant, score=None, meta=DecisionMeta(provider=provider, latency_ms=1.0, fallback_reason=reason))


def test_grade_summary_counts_fallbacks_and_marks_mixed():
    summary = grade_summary(
        [_grade(True, "jev"), _grade(False, "jev"), _grade(True, "llm", "rate_limited")],
        provider_name="jev",
        latency_ms=12.0,
    )
    assert summary["provider"] == "mixed"
    assert summary["result"] == "2/3 kept"
    assert (summary["fallback_reason"], summary["fallback_count"]) == ("rate_limited", 1)


def test_grade_summary_with_no_chunks_uses_provider_name():
    summary = grade_summary([], provider_name="llm", latency_ms=0.0)
    assert (summary["provider"], summary["result"], summary["fallback_count"]) == ("llm", "0/0 kept", 0)


def test_verify_summary_only_names_checks_that_ran():
    meta = DecisionMeta(provider="llm", latency_ms=1.0)
    assert verify_summary(VerifyDecision(False, None, None, None, meta), 1.0)["result"] == "not grounded"
    assert verify_summary(VerifyDecision(None, True, None, None, meta), 1.0)["result"] == "answers"
    assert verify_summary(VerifyDecision(True, False, None, None, meta), 1.0)["result"] == "grounded, does not answer"
