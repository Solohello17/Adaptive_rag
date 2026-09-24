import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import MongoClient

from app.decisions.base import DecisionMeta, DecisionProvider, GradeDecision, RouteDecision, VerifyDecision

logger = logging.getLogger(__name__)

# Set per request by POST /query (and by the eval script) so every decision log
# can be tied back to one query without adding a parameter to the provider interface.
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

PREVIEW_CHARS = 200


class MongoDecisionLog:
    """
    Writes decision documents to MongoDB with a sync pymongo client. The graph
    nodes are sync, so they can't await the app's async Motor client.

    Logging must never break a query: any Mongo error is logged as a warning and
    dropped. The client is created on first write.
    """

    def __init__(self, uri: str, database: str = "adaptive_rag", collection: str = "decision_logs"):
        self.uri, self.database, self.collection = uri, database, collection
        self._client: Optional[MongoClient] = None

    def write(self, documents: List[Dict[str, Any]]) -> None:
        if not documents:
            return
        try:
            if self._client is None:
                self._client = MongoClient(self.uri, serverSelectionTimeoutMS=2000)
            self._client[self.database][self.collection].insert_many(documents)
        except Exception as e:
            logger.warning("Could not write %d decision log(s): %s", len(documents), type(e).__name__)


class LoggedProvider:
    """
    Wraps any decision provider (llm, or jev with fallback) and writes one log
    document per decision after the inner provider returns; grading writes one
    per chunk. Returns the inner provider's decisions unchanged.

    Only previews of user text are stored (PREVIEW_CHARS), never full passages,
    context, answers, headers, or keys.
    """

    def __init__(self, inner: DecisionProvider, log: MongoDecisionLog, app_version: str):
        self.inner = inner
        self.log = log
        self.app_version = app_version
        self.name = inner.name

    def _document(self, decision: str, meta: DecisionMeta, result: Any, question: str, score: Any = None, passage: Optional[str] = None) -> Dict[str, Any]:
        document = {
            "timestamp": datetime.now(timezone.utc),
            "app_version": self.app_version,
            "request_id": request_id_var.get(),
            "decision": decision,
            "provider": meta.provider,
            "model": meta.model,
            "fallback_reason": meta.fallback_reason,
            "jev_attempt": meta.jev_attempt,
            "result": result,
            "confidence": meta.confidence,
            "score": score,
            "probabilities": meta.probabilities,
            "latency_ms": meta.latency_ms,
            "input_tokens": meta.input_tokens,
            "output_tokens": meta.output_tokens,
            "cost_usd": meta.cost_usd,
            "market_cost_usd": meta.market_cost_usd,
            "query_preview": question[:PREVIEW_CHARS],
        }
        if passage is not None:
            document["passage_preview"] = passage[:PREVIEW_CHARS]
        return document

    def route(self, question: str) -> RouteDecision:
        decision = self.inner.route(question)
        self.log.write([self._document("route", decision.meta, decision.route, question)])
        return decision

    def grade(self, question: str, passages: List[str]) -> List[GradeDecision]:
        decisions = self.inner.grade(question, passages)
        self.log.write([
            self._document("grade", d.meta, "relevant" if d.relevant else "irrelevant", question, score=d.score, passage=passage)
            for d, passage in zip(decisions, passages)
        ])
        return decisions

    def verify(self, question: str, context: str, answer: str) -> VerifyDecision:
        decision = self.inner.verify(question, context, answer)
        self.log.write([self._document(
            "verify",
            decision.meta,
            {"grounded": decision.grounded, "answers_question": decision.answers_question},
            question,
            score={"grounded": decision.grounded_score, "answers_question": decision.answers_score},
        )])
        return decision
