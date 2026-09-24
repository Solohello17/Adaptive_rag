from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Union, get_args

import yaml

from app.decisions.base import DecisionMeta, GradeDecision, JevDecisionError, Route, RouteDecision, VerifyDecision
from app.decisions.jev_client import JevClient, JevResponse, state_chars

QUESTIONS_PATH = Path(__file__).with_name("jev_questions.yaml")
ROUTES = set(get_args(Route))


def load_questions(path: Path = QUESTIONS_PATH) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class JevDecisionProvider:
    """
    Makes route / grade / verify decisions with Jev, using the wording in
    jev_questions.yaml. It is strict: whenever Jev fails or is unsure it raises
    JevDecisionError instead of guessing, and FallbackProvider asks the LLM.

    User text only ever goes inside `state` as JSON fields; instructions and
    criteria come only from the YAML file.
    """
    name = "jev"

    def __init__(
        self,
        client: JevClient,
        questions: Dict[str, Any],
        route_min_confidence: float,
        grade_threshold: float,
        verify_threshold: float,
        max_concurrency: int,
        max_state_chars: int,
    ):
        self.client = client
        self.questions = questions
        self.route_min_confidence = route_min_confidence
        self.grade_threshold = grade_threshold
        self.verify_threshold = verify_threshold
        self.max_concurrency = max_concurrency
        self.max_state_chars = max_state_chars

    def _ask(self, state: Dict[str, Any], questions: Dict[str, Any]) -> JevResponse:
        size = state_chars(state)
        if size > self.max_state_chars:
            # Checked before sending, so an oversized state costs no Jev call.
            raise JevDecisionError("state_too_large", {"state_chars": size, "limit": self.max_state_chars})
        return self.client.ask(state, questions)

    @staticmethod
    def _meta(response: JevResponse, **extra) -> DecisionMeta:
        return DecisionMeta(
            provider="jev",
            latency_ms=response.latency_ms,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            market_cost_usd=response.market_cost_usd,
            **extra,
        )

    def route(self, question: str) -> RouteDecision:
        response = self._ask({"question": question}, {"route": self.questions["route"]})
        answer = response.answers["route"]
        choice, confidence = answer.get("choice"), answer.get("confidence")
        probabilities = answer.get("probabilities") or {}
        attempt = {"latency_ms": response.latency_ms, "choice": choice, "confidence": confidence, "probabilities": probabilities}

        # `unclear` is our own escape hatch, not a v1 route: it never leaves this provider.
        if choice == "unclear":
            raise JevDecisionError("unclear", attempt)
        if choice not in ROUTES or not isinstance(confidence, (int, float)):
            raise JevDecisionError("bad_response", attempt)
        if confidence < self.route_min_confidence:
            raise JevDecisionError("low_confidence", attempt)

        return RouteDecision(route=choice, meta=self._meta(response, confidence=confidence, probabilities=probabilities))

    def _grade_one(self, question: str, passage: str) -> Union[GradeDecision, JevDecisionError]:
        try:
            response = self._ask({"question": question, "passage": passage}, {"grade": self.questions["grade"]})
        except JevDecisionError as e:
            return e
        score = response.answers["grade"].get("noul")
        if not isinstance(score, (int, float)):
            return JevDecisionError("bad_response", {"latency_ms": response.latency_ms, "answer": response.answers["grade"]})
        return GradeDecision(relevant=score >= self.grade_threshold, score=score, meta=self._meta(response))

    def grade_each(self, question: str, passages: List[str]) -> List[Union[GradeDecision, JevDecisionError]]:
        """
        One Noul per chunk (Jev is less accurate on long, mixed state), run
        concurrently but at most JEV_MAX_CONCURRENCY at a time. Returns a
        GradeDecision or the JevDecisionError for each chunk, in input order,
        so the fallback can send only the failed chunks to the LLM.
        """
        if not passages:
            return []
        with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
            return list(pool.map(lambda passage: self._grade_one(question, passage), passages))

    def grade(self, question: str, passages: List[str]) -> List[GradeDecision]:
        results = self.grade_each(question, passages)
        for result in results:
            if isinstance(result, JevDecisionError):
                raise result
        return results

    def verify(self, question: str, context: str, answer: str) -> VerifyDecision:
        """
        Both checks in one request (Jev answers questions in parallel, so the
        second costs almost no extra time). Like v1, there is no grounded check
        without context. Unlike v1, "answers the question" is always scored;
        check_generation ignores it when the answer is not grounded, so the
        graph's path is the same as v1's either way.
        """
        verify_questions = self.questions["verify"]
        questions = {"answers_question": verify_questions["answers_question"]}
        state = {"question": question}
        if context:
            questions["grounded"] = verify_questions["grounded"]
            state["context"] = context
        state["answer"] = answer

        response = self._ask(state, questions)
        scores = {name: response.answers[name].get("noul") for name in questions}
        if not all(isinstance(score, (int, float)) for score in scores.values()):
            raise JevDecisionError("bad_response", {"latency_ms": response.latency_ms, "answers": response.answers})

        grounded_score = scores.get("grounded")
        answers_score = scores["answers_question"]
        return VerifyDecision(
            grounded=None if grounded_score is None else grounded_score >= self.verify_threshold,
            answers_question=answers_score >= self.verify_threshold,
            grounded_score=grounded_score,
            answers_score=answers_score,
            meta=self._meta(response),
        )
