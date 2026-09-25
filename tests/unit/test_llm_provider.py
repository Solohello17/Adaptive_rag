"""
T14, T15: the LLM provider must make exactly the calls v1 made inline in the
graph nodes, so DECISION_PROVIDER=llm behaves like v1. The v1 functions are
replaced with recorders, so no LLM is called.
"""
import pytest

import app.decisions.llm_provider as llm_provider
from app.decisions.llm_provider import LLMDecisionProvider


@pytest.fixture
def calls(monkeypatch):
    log = []

    def fake(name, result):
        def _fn(*args):
            log.append((name, args))
            return result(*args) if callable(result) else result
        return _fn

    def install(route="documents", verdicts=None, grounded="yes", answers="yes"):
        monkeypatch.setattr(llm_provider, "route_question", fake("route_question", route))
        monkeypatch.setattr(llm_provider, "grade_documents_batch", fake("grade_documents_batch", lambda q, docs: verdicts if verdicts is not None else ["yes"] * len(docs)))
        monkeypatch.setattr(llm_provider, "grade_hallucination", fake("grade_hallucination", grounded))
        monkeypatch.setattr(llm_provider, "grade_answer", fake("grade_answer", answers))
        return log

    return install


# T14
def test_route_returns_v1_route_unchanged(calls):
    log = calls(route="web_search")
    decision = LLMDecisionProvider().route("What is the weather?")
    assert decision.route == "web_search"
    assert decision.meta.provider == "llm"
    assert log == [("route_question", ("What is the weather?",))]


# T14
def test_grade_is_one_batch_call_mapped_to_booleans(calls):
    log = calls(verdicts=["yes", "no", "yes"])
    grades = LLMDecisionProvider().grade("q", ["a", "b", "c"])
    assert [g.relevant for g in grades] == [True, False, True]
    assert all(g.score is None and g.meta.provider == "llm" for g in grades)
    assert log == [("grade_documents_batch", ("q", ["a", "b", "c"]))]


# T14
def test_grade_with_no_passages_still_calls_v1_once(calls):
    # v1's node called grade_documents_batch even with 0 documents (it returns [] without an LLM call).
    log = calls()
    assert LLMDecisionProvider().grade("q", []) == []
    assert log == [("grade_documents_batch", ("q", []))]


# T15
def test_verify_grounded_runs_both_checks_in_v1_order(calls):
    log = calls(grounded="yes", answers="no")
    verdict = LLMDecisionProvider().verify("q", "ctx", "ans")
    assert (verdict.grounded, verdict.answers_question) == (True, False)
    assert log == [("grade_hallucination", ("ctx", "ans")), ("grade_answer", ("q", "ans"))]


# T15
def test_verify_skips_answer_check_when_not_grounded(calls):
    log = calls(grounded="no")
    verdict = LLMDecisionProvider().verify("q", "ctx", "ans")
    assert (verdict.grounded, verdict.answers_question) == (False, None)
    assert log == [("grade_hallucination", ("ctx", "ans"))]


# T15
def test_verify_skips_grounded_check_without_context(calls):
    log = calls(answers="yes")
    verdict = LLMDecisionProvider().verify("q", "", "ans")
    assert (verdict.grounded, verdict.answers_question) == (None, True)
    assert log == [("grade_answer", ("q", "ans"))]
