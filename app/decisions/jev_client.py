import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from app.decisions.base import JevDecisionError


@dataclass
class JevResponse:
    answers: Dict[str, Any]
    model: Optional[str]
    latency_ms: float
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    cost_usd: Optional[float]
    market_cost_usd: Optional[float]


def _to_float(value) -> Optional[float]:
    # The gateway reports costs as strings, e.g. "0.00001155".
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class JevClient:
    """
    Minimal client for Jev on the Vercel AI Gateway's TypeSafe-compatible API
    (POST {base_url}/v1/systemone). This is the only file that knows the
    endpoint and response shape.

    Every failure becomes a JevDecisionError with a reason code, so the caller
    can fall back to the LLM. The API key only ever goes in the request header;
    error details never include headers, and httpx exceptions are reduced to
    their type name so no URL or header text leaks into logs.
    """

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float, transport: Optional[httpx.BaseTransport] = None):
        self.model = model
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            transport=transport,  # tests pass httpx.MockTransport
        )

    def ask(self, state: Any, questions: Dict[str, Any]) -> JevResponse:
        """One systemone request: evaluate `state` against every question at once."""
        start = time.perf_counter()

        def detail(**extra):
            return {"latency_ms": round((time.perf_counter() - start) * 1000, 1), **extra}

        try:
            response = self._client.post("/v1/systemone", json={"model": self.model, "state": state, "questions": questions})
        except httpx.TimeoutException as e:
            raise JevDecisionError("timeout", detail(error=type(e).__name__))
        except httpx.TransportError as e:
            # DNS failures (like the Phase 0 NameResolutionError) and refused connections.
            raise JevDecisionError("network_error", detail(error=type(e).__name__))

        if response.status_code != 200:
            reason = {429: "rate_limited", 402: "out_of_credit"}.get(response.status_code, "http_error")
            error_type, message = None, None
            try:
                body = response.json()
                error_type, message = body.get("error_type"), str(body.get("message", ""))[:200]
            except ValueError:
                pass
            raise JevDecisionError(reason, detail(status_code=response.status_code, error_type=error_type, message=message))

        try:
            body = response.json()
            answers = body["answers"]
        except (ValueError, KeyError, TypeError):
            raise JevDecisionError("bad_response", detail(status_code=200, message="missing or invalid 'answers'"))

        missing = [name for name in questions if not isinstance(answers.get(name), dict)]
        if missing:
            raise JevDecisionError("bad_response", detail(status_code=200, message=f"no answer for {missing}"))

        usage = body.get("usage") or {}
        gateway = (body.get("provider_metadata") or {}).get("gateway") or {}
        return JevResponse(
            answers=answers,
            model=body.get("model"),
            latency_ms=detail()["latency_ms"],
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cost_usd=_to_float(gateway.get("cost")),
            market_cost_usd=_to_float(gateway.get("marketCost")),
        )

    def list_models(self) -> Dict[str, Any]:
        """GET {base_url}/v1/models. Used once to check for a pinnable Jev id."""
        response = self._client.get("/v1/models")
        response.raise_for_status()
        return response.json()


def state_chars(state: Any) -> int:
    """Size of the state as it goes over the wire, for the JEV_MAX_STATE_CHARS guard."""
    return len(state) if isinstance(state, str) else len(json.dumps(state, ensure_ascii=False))
