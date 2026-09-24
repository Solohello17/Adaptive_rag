from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol

# The four v1 routes. Jev's extra `unclear` option never leaves the Jev
# provider, so every RouteDecision carries one of these.
Route = Literal["documents", "code", "web_search", "general_knowledge"]


@dataclass
class DecisionMeta:
    """How a decision was made: who made it, how long it took, what it cost."""
    provider: str                          # "jev" or "llm"
    latency_ms: float
    model: Optional[str] = None
    confidence: Optional[float] = None     # Jev Choice only
    probabilities: dict = field(default_factory=dict)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    market_cost_usd: Optional[float] = None
    fallback_reason: Optional[str] = None  # set when Jev was tried and the LLM decided
    jev_attempt: Optional[dict] = None     # what Jev said or why it failed, when it fell back


@dataclass
class RouteDecision:
    route: Route
    meta: DecisionMeta


@dataclass
class GradeDecision:
    relevant: bool
    score: Optional[float]                 # Jev noul; None for the LLM
    meta: DecisionMeta


@dataclass
class VerifyDecision:
    # None when the check was not run: v1 skips the grounded check when there is
    # no context, and skips the answer check once an answer is not grounded.
    grounded: Optional[bool]
    answers_question: Optional[bool]
    grounded_score: Optional[float]
    answers_score: Optional[float]
    meta: DecisionMeta


class DecisionProvider(Protocol):
    name: str

    def route(self, question: str) -> RouteDecision: ...
    def grade(self, question: str, passages: List[str]) -> List[GradeDecision]: ...
    def verify(self, question: str, context: str, answer: str) -> VerifyDecision: ...


class JevDecisionError(Exception):
    """
    Jev could not make this decision (failed, or was unsure). The fallback
    provider catches only this and asks the LLM instead. `reason` is one of the
    codes in docs/v2-jev/02-design.md section 7. `detail` must never hold the API key.
    """
    def __init__(self, reason: str, detail: Optional[dict] = None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}


# Compact per-decision summaries for graph state and the /query response.
# latency_ms here is how long the node waited for the decision; the per-call
# latency lives in DecisionMeta (and the decision logs).

def route_summary(decision: RouteDecision, latency_ms: float) -> Dict[str, Any]:
    return {
        "decision": "route",
        "provider": decision.meta.provider,
        "result": decision.route,
        "confidence": decision.meta.confidence,
        "latency_ms": latency_ms,
        "fallback_reason": decision.meta.fallback_reason,
    }


def grade_summary(decisions: List[GradeDecision], provider_name: str, latency_ms: float) -> Dict[str, Any]:
    providers = {d.meta.provider for d in decisions}
    fallback_reasons = [d.meta.fallback_reason for d in decisions if d.meta.fallback_reason]
    kept = sum(1 for d in decisions if d.relevant)
    return {
        "decision": "grade",
        "provider": providers.pop() if len(providers) == 1 else ("mixed" if providers else provider_name),
        "result": f"{kept}/{len(decisions)} kept",
        "confidence": None,
        "latency_ms": latency_ms,
        "fallback_reason": Counter(fallback_reasons).most_common(1)[0][0] if fallback_reasons else None,
        "fallback_count": len(fallback_reasons),
    }


def verify_summary(decision: VerifyDecision, latency_ms: float) -> Dict[str, Any]:
    parts = []
    if decision.grounded is not None:
        parts.append("grounded" if decision.grounded else "not grounded")
    if decision.answers_question is not None:
        parts.append("answers" if decision.answers_question else "does not answer")
    return {
        "decision": "verify",
        "provider": decision.meta.provider,
        "result": ", ".join(parts),
        "confidence": None,
        "latency_ms": latency_ms,
        "fallback_reason": decision.meta.fallback_reason,
    }
