"""T01 to T07: the Jev HTTP client, with httpx.MockTransport (no network)."""
import json

import httpx
import pytest

from app.decisions.base import JevDecisionError
from app.decisions.jev_client import JevClient, state_chars

KEY = "test-secret-key-123"
QUESTIONS = {"refund": {"type": "noul", "instructions": "Is the customer asking for money back?"}}

# Shape from the Vercel TypeSafe API docs.
OK_BODY = {
    "model": "typesafe-ai/jev",
    "answers": {"refund": {"type": "noul", "noul": 0.98}},
    "usage": {"input_tokens": 275, "output_tokens": 20},
    "provider_metadata": {"gateway": {"cost": "0.00001155", "marketCost": "0.00001155"}},
}


def client_with(handler):
    return JevClient(KEY, "https://gateway.test/typesafe", "typesafe-ai/jev", 5, transport=httpx.MockTransport(handler))


def ask(handler):
    return client_with(handler).ask({"message": "I was charged twice."}, QUESTIONS)


def reason_of(handler):
    with pytest.raises(JevDecisionError) as info:
        ask(handler)
    return info.value


# T01
def test_success_parses_answers_usage_and_string_costs():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    r = ask(handler)
    assert seen["url"] == "https://gateway.test/typesafe/v1/systemone"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["body"] == {"model": "typesafe-ai/jev", "state": {"message": "I was charged twice."}, "questions": QUESTIONS}
    assert r.answers["refund"]["noul"] == 0.98
    assert (r.model, r.input_tokens, r.output_tokens) == ("typesafe-ai/jev", 275, 20)
    assert r.cost_usd == pytest.approx(0.00001155) and r.market_cost_usd == pytest.approx(0.00001155)


# T02
def test_429_is_rate_limited():
    e = reason_of(lambda req: httpx.Response(429, json={"message": "slow down", "error_type": "rate_limited"}))
    assert e.reason == "rate_limited" and e.detail["status_code"] == 429


# T03
def test_402_is_out_of_credit():
    e = reason_of(lambda req: httpx.Response(402, json={"message": "Insufficient balance", "error_type": "payment_required"}))
    assert e.reason == "out_of_credit"


def test_other_status_is_http_error_with_message():
    e = reason_of(lambda req: httpx.Response(400, json={"message": "questions.refund.type: expected one of 'noul', 'choice', 'score'", "error_type": "invalid_request"}))
    assert (e.reason, e.detail["error_type"]) == ("http_error", "invalid_request")


# T04
def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)
    assert reason_of(handler).reason == "timeout"


# T05
def test_connection_error_is_network_error():
    def handler(request):
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)
    assert reason_of(handler).reason == "network_error"


# T06
def test_invalid_json_is_bad_response():
    assert reason_of(lambda req: httpx.Response(200, content=b"not json")).reason == "bad_response"


# T06
def test_missing_answer_is_bad_response():
    body = {**OK_BODY, "answers": {"something_else": {"type": "noul", "noul": 0.5}}}
    assert reason_of(lambda req: httpx.Response(200, json=body)).reason == "bad_response"


# T07
@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(401, json={"message": "bad key", "error_type": "unauthorized"}),
    lambda req: (_ for _ in ()).throw(httpx.ConnectError("boom", request=req)),
])
def test_api_key_never_in_error(handler):
    e = reason_of(handler)
    assert KEY not in str(e) and KEY not in json.dumps(e.detail)


def test_state_chars_counts_serialized_json():
    assert state_chars("abc") == 3
    assert state_chars({"q": "é"}) == len('{"q": "é"}')
