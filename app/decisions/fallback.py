import logging
from typing import List

from app.decisions.base import DecisionMeta, GradeDecision, JevDecisionError, RouteDecision, VerifyDecision
from app.decisions.jev_provider import JevDecisionProvider
from app.decisions.llm_provider import LLMDecisionProvider

logger = logging.getLogger(__name__)


def _mark(meta: DecisionMeta, error: JevDecisionError) -> None:
    meta.fallback_reason = error.reason
    meta.jev_attempt = error.detail


class FallbackProvider:
    """
    Tries Jev for each decision and asks the LLM only for the decisions Jev
    could not make, recording why. One failed decision never switches the rest
    of the query to the LLM, and for grading only the chunks Jev failed on are
    re-graded (in one batched LLM call).

    Only JevDecisionError triggers a fallback. Any other exception is a bug and
    is raised. With enabled=False (JEV_FALLBACK_TO_LLM=false), Jev errors are
    raised too, which is useful for testing Jev on its own.
    """
    name = "jev"

    def __init__(self, jev: JevDecisionProvider, llm: LLMDecisionProvider, enabled: bool = True):
        self.jev = jev
        self.llm = llm
        self.enabled = enabled

    def _fall_back(self, error: JevDecisionError, decision_name: str) -> None:
        if not self.enabled:
            raise error
        print(f"--- JEV FALLBACK: {decision_name} -> llm ({error.reason}) ---")
        logger.info("Jev %s fell back to the LLM: %s", decision_name, error.reason)

    def route(self, question: str) -> RouteDecision:
        try:
            return self.jev.route(question)
        except JevDecisionError as e:
            self._fall_back(e, "route")
            decision = self.llm.route(question)
            _mark(decision.meta, e)
            return decision

    def grade(self, question: str, passages: List[str]) -> List[GradeDecision]:
        results = self.jev.grade_each(question, passages)
        failed = [i for i, result in enumerate(results) if isinstance(result, JevDecisionError)]
        if not failed:
            return results

        self._fall_back(results[failed[0]], f"grade ({len(failed)}/{len(passages)} chunks)")
        llm_grades = self.llm.grade(question, [passages[i] for i in failed])
        for i, grade in zip(failed, llm_grades):
            _mark(grade.meta, results[i])
            results[i] = grade
        return results

    def verify(self, question: str, context: str, answer: str) -> VerifyDecision:
        try:
            return self.jev.verify(question, context, answer)
        except JevDecisionError as e:
            self._fall_back(e, "verify")
            decision = self.llm.verify(question, context, answer)
            _mark(decision.meta, e)
            return decision
