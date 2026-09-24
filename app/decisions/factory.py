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
    provider = settings.DECISION_PROVIDER.lower()

    if provider == "llm":
        return LLMDecisionProvider()

    elif provider == "jev":
        raise ValueError("DECISION_PROVIDER=jev is not wired up yet (Phase 4 step 7)")

    else:
        raise ValueError(f"Unsupported DECISION_PROVIDER: {provider}")
