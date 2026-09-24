from pathlib import Path
from typing import Any, Dict, get_args

import yaml

from app.decisions.base import DecisionMeta, JevDecisionError, Route, RouteDecision
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
        max_state_chars: int,
    ):
        self.client = client
        self.questions = questions
        self.route_min_confidence = route_min_confidence
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
