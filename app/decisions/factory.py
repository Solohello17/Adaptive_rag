from functools import lru_cache
from typing import Optional

from app.config import settings
from app.decisions.base import DecisionProvider
from app.decisions.llm_provider import LLMDecisionProvider

# Set by tests and the eval script to swap in a different provider without
# touching settings. None means "build from settings".
_override: Optional[DecisionProvider] = None


def override_decision_provider(provider: Optional[DecisionProvider]) -> None:
    global _override
    _override = provider


def get_decision_provider() -> DecisionProvider:
    """
    Returns the provider the graph nodes use for route / grade / verify
    decisions, selected by DECISION_PROVIDER. Nodes never call Jev or the LLM
    directly for a decision.
    """
    if _override is not None:
        return _override
    return _build_from_settings()


# Cached like get_embeddings(): settings are read once at import, so the
# provider can't change mid-process anyway.
@lru_cache(maxsize=1)
def _build_from_settings() -> DecisionProvider:
    provider = _build_provider()
    # Logging wraps whichever provider was chosen, so both modes are logged.
    # (The setting keeps the brief's name, JEV_LOG_DECISIONS, but covers llm too.)
    if settings.JEV_LOG_DECISIONS:
        from app.decisions.decision_log import LoggedProvider, MongoDecisionLog
        provider = LoggedProvider(provider, MongoDecisionLog(settings.MONGODB_URI), app_version=settings.APP_VERSION)
    return provider


def _build_provider() -> DecisionProvider:
    provider = settings.DECISION_PROVIDER.lower()

    if provider == "llm":
        return LLMDecisionProvider()

    elif provider == "jev":
        # Fail fast on a missing key: silently falling back on every query
        # would hide the misconfiguration.
        if not settings.AI_GATEWAY_API_KEY:
            raise ValueError("DECISION_PROVIDER=jev needs AI_GATEWAY_API_KEY in .env")

        from app.decisions.fallback import FallbackProvider
        from app.decisions.jev_client import JevClient
        from app.decisions.jev_provider import JevDecisionProvider, load_questions

        jev = JevDecisionProvider(
            client=JevClient(
                api_key=settings.AI_GATEWAY_API_KEY,
                base_url=settings.JEV_BASE_URL,
                model=settings.JEV_MODEL,
                timeout=settings.JEV_TIMEOUT_SECONDS,
            ),
            questions=load_questions(),
            route_min_confidence=settings.JEV_ROUTE_MIN_CONFIDENCE,
            grade_threshold=settings.JEV_GRADE_THRESHOLD,
            verify_threshold=settings.JEV_VERIFY_THRESHOLD,
            max_concurrency=settings.JEV_MAX_CONCURRENCY,
            max_state_chars=settings.JEV_MAX_STATE_CHARS,
        )
        return FallbackProvider(jev, LLMDecisionProvider(), enabled=settings.JEV_FALLBACK_TO_LLM)

    else:
        raise ValueError(f"Unsupported DECISION_PROVIDER: {provider}")
