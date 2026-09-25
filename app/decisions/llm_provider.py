import time
from typing import List

from app.router import route_question
from app.grader import grade_documents_batch, grade_hallucination, grade_answer
from app.decisions.base import DecisionMeta, GradeDecision, RouteDecision, VerifyDecision


def _ms_since(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


class LLMDecisionProvider:
    """
    The v1 decision path, wrapped behind the decision interface. It calls the
    exact v1 functions in app/router.py and app/grader.py with the same inputs,
    in the same order, the same number of times -- so DECISION_PROVIDER=llm
    behaves like v1. It only adds timing and maps 'yes'/'no' to booleans.
    """
    name = "llm"

    def route(self, question: str) -> RouteDecision:
        start = time.perf_counter()
        route = route_question(question)
        return RouteDecision(route=route, meta=DecisionMeta(provider="llm", latency_ms=_ms_since(start)))

    def grade(self, question: str, passages: List[str]) -> List[GradeDecision]:
        # One batched LLM call for all chunks (v1 behaviour), so every chunk's
        # decision carries that one call's latency.
        start = time.perf_counter()
        verdicts = grade_documents_batch(question, passages)
        latency = _ms_since(start)
        return [
            GradeDecision(relevant=verdict == "yes", score=None, meta=DecisionMeta(provider="llm", latency_ms=latency))
            for verdict in verdicts
        ]

    def verify(self, question: str, context: str, answer: str) -> VerifyDecision:
        start = time.perf_counter()

        # Same short-circuits as v1's check_generation: no grounding check
        # without context, and no answer check once the answer is ungrounded
        # (the graph regenerates instead, so v1 never asks).
        grounded = None
        if context:
            grounded = grade_hallucination(context, answer) == "yes"

        answers_question = None
        if grounded is not False:
            answers_question = grade_answer(question, answer) == "yes"

        return VerifyDecision(
            grounded=grounded,
            answers_question=answers_question,
            grounded_score=None,
            answers_score=None,
            meta=DecisionMeta(provider="llm", latency_ms=_ms_since(start)),
        )
