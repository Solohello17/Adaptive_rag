# 03. Implementation log

One entry per step of Phase 4. Each step is one commit on `feature/jev-decision-layer`.

## Step 1: settings and question wording

**Commit:** `feat(config): add decision layer settings and Jev question wording`

**What:** Added the v2 settings to `app/config.py` and `.env.example` (`DECISION_PROVIDER` defaults to `llm`), wrote `app/decisions/jev_questions.yaml`, and declared `httpx`, `pyyaml`, `pymongo`, `pytest`, and `matplotlib` in `requirements.txt`. Only `pytest` and `matplotlib` were new installs; the other three were already present as dependencies of other packages.

**Why:** Settings and wording come first so every later step reads them instead of hard-coding values. The YAML mirrors the v1 prompts so the comparison is fair.

**Worth knowing:** YAML reads a bare `true:` key as the boolean `True`, not the string `"true"` that Jev's Noul `criteria` expects, so those keys are quoted.

**Files:** `app/config.py`, `.env.example`, `requirements.txt`, `app/decisions/jev_questions.yaml`

## Step 2: decision interface and LLM provider (pure refactor)

**Commit:** `feat(decisions): add decision interface and route nodes through it`

**What:**

- `app/decisions/base.py`: the result types (`RouteDecision`, `GradeDecision`, `VerifyDecision`, `DecisionMeta`), the `DecisionProvider` interface, `JevDecisionError`, and small functions that turn decisions into summaries for graph state.
- `app/decisions/llm_provider.py`: `LLMDecisionProvider`, which calls the v1 functions (`route_question`, `grade_documents_batch`, `grade_hallucination`, `grade_answer`) and only adds timing and yes/no to boolean mapping.
- `app/decisions/factory.py`: `get_decision_provider()`, cached, plus `override_decision_provider()` for tests and the eval script. `jev` is rejected until step 7.
- `app/graph.py`: `route_question_node`, `grade_documents`, and `check_generation` now ask the provider. A new state key, `decisions`, collects one summary per decision. Edges, retry cap, similarity override, and `steps` text are unchanged.

**Why the verify call is shaped this way:** v1 ran the grounded check only with context, and skipped the answer check after a grounding failure. The LLM provider keeps both short-circuits, so `llm` mode makes the same LLM calls as v1, in the same order.

**Tests (18, all offline):**

| Test | Checks |
|---|---|
| T14 | Route, grade, and empty grade call the v1 functions with the same arguments |
| T15 | Verify runs both checks in v1 order; skips the answer check when not grounded; skips the grounded check without context |
| T21 | Documents path end to end with a fake provider |
| T22 | General knowledge path skips grounding |
| T23 | Web search path, and no relevant chunks falls back to web search |
| T24 | Both correction loops stop at the retry cap (CLAUDE.md rule 4) |
| extra | Factory selection and override; grade and verify summaries |

**Live check against the v1 baseline** (5 eval questions, `llm` mode, real LLM, 25 Sept 2026):

| Question | Route (v1 to v2) | Step names identical | Grounded | Retries |
|---|---|---|---|---|
| q01 documents | documents to documents | yes | True to True | 0 to 0 |
| q11 general | general_knowledge to general_knowledge | yes | None to None | 0 to 0 |
| q18 override case | documents to documents (router said general_knowledge, override fired in both) | yes | True to True | 0 to 0 |
| q21 web | web_search to web_search | yes | True to True | 0 to 0 |
| q32 `?` | crash to crash (`OutputParserException`, known issue K1, unchanged by design) | yes | n/a | n/a |

**Files:** `app/decisions/__init__.py`, `app/decisions/base.py`, `app/decisions/llm_provider.py`, `app/decisions/factory.py`, `app/graph.py`, `pytest.ini`, `tests/unit/test_llm_provider.py`, `tests/unit/test_graph_paths.py`, `tests/unit/test_factory_and_summaries.py`

## Step 3: Jev HTTP client and model-list check

**Commit:** `feat(decisions): add Jev HTTP client and model-list check`

**What:** `app/decisions/jev_client.py` makes one `POST {JEV_BASE_URL}/v1/systemone` call with `httpx` and returns the answers, usage, and cost. Every failure becomes a `JevDecisionError` with a reason code: `timeout`, `network_error`, `rate_limited` (429), `out_of_credit` (402), `http_error`, or `bad_response`. `scripts/check_jev_models.py` lists the gateway's evaluation models and, with `--smoke`, makes one real call.

**Why:** One small file owns the endpoint and response shape, so switching to Vercel's `/v1/evaluate` later only touches this file. Reason codes let the fallback record why Jev was skipped without parsing error text.

**Key safety:** the key only goes in the request header. Network exceptions are reduced to their type name, so no URL or header text reaches an error message. Test T07 checks this.

**Real calls (25 Sept 2026):**

- `GET /v1/models` returned one model: `name=jev`, `release_date=2026-09-15`. No versioned id exists, so `JEV_MODEL` stays `typesafe-ai/jev` and is **unpinned**. The shape is `{"models": [{"name", "description", "release_date"}]}`, not the `{"data": [{"id"}]}` shape the script first assumed.
- Smoke call with a JSON-object state (`{"question": "What is the capital of France?"}`): `direct`, confidence 1, 347 input tokens, 40 output tokens, cost 0 (free credit), market cost 0.000014574 USD, 1118 ms end to end from the laptop (a single call on a fresh connection, not a benchmark). This confirms the systemone endpoint accepts object state, so no `json.dumps` workaround is needed.

**Tests:** T01 to T07 plus a status-code and a state-size test, 11 in total, all with `httpx.MockTransport`.

**Files:** `app/decisions/jev_client.py`, `scripts/check_jev_models.py`, `tests/unit/test_jev_client.py`

## Step 4: Jev route

**Commit:** `feat(decisions): add Jev route decision`

**What:** `app/decisions/jev_provider.py` with `JevDecisionProvider.route()`. It sends one Choice with state `{"question": ...}` and the five options from the YAML. `unclear`, an unknown option, a missing confidence, or confidence below `JEV_ROUTE_MIN_CONFIDENCE` raise `JevDecisionError`, so the fallback (step 7) can hand that one decision to the LLM. A state longer than `JEV_MAX_STATE_CHARS` is rejected before any call is made.

**Why strict:** the provider never guesses. Every uncertain case becomes a named reason, which is what makes the fallback rate measurable.

**Live sanity check (4 questions, 25 Sept 2026, not the evaluation):**

| Question | Jev result | Confidence | Latency | Input tokens |
|---|---|---|---|---|
| subject code for ML in our syllabus | documents | 0.98 | 815 ms | 466 |
| Hello! How are you today? | general_knowledge | 1 | 471 ms | 460 |
| current price of Bitcoin | web_search | 1 | 443 ms | 461 |
| asdkjh qwe zzz | unclear (would fall back) | 0.98 | 484 ms | n/a |

**Tests:** T08 (each route maps, and the exact state and question sent), T09 (`unclear`), T10 (low confidence), T13 (oversized state makes no call), plus unknown-choice and YAML-option checks. 9 tests.

**Files:** `app/decisions/jev_provider.py`, `tests/unit/test_jev_provider.py`
