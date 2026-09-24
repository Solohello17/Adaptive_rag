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

## Step 5: Jev grade

**Commit:** `feat(decisions): add Jev per-chunk grading`

**What:** `JevDecisionProvider.grade_each()` sends one Noul per chunk with state `{"question": ..., "passage": ...}`, through a `ThreadPoolExecutor` capped at `JEV_MAX_CONCURRENCY`. It returns, in input order, either a `GradeDecision` (relevant if `noul >= JEV_GRADE_THRESHOLD`) or the `JevDecisionError` for that chunk. `grade()` is the strict version that raises on the first failure.

**Why per chunk, and why errors are returned instead of raised:** one chunk per call follows the brief's rule that Jev is less accurate on long, mixed state. Returning each chunk's error lets the fallback (step 7) send only the failed chunks to the LLM, instead of re-grading all of them.

**Live sanity check (3 chunks, question "What is the subject code for Machine Learning?", 25 Sept 2026):**

| Chunk | Noul | Relevant at 0.5 |
|---|---|---|
| question bank header with "Machine Learning (3170724)" | 0.99 | yes |
| syllabus header with "Subject Code : 3170724" | 0.99 | yes |
| Chapter 9 neural network questions (no subject code) | 0.72 | yes |

All three calls ran concurrently: about 886 ms each, 891 ms wall time. The third chunk shows how lenient the wording is. That leniency deliberately mirrors v1's grader ("It does not need to be a stringent test"), and v1 was similar (it kept 7 of 8 chunks on q01 in the baseline). `JEV_GRADE_THRESHOLD` is a Phase 5 tuning question, not changed here.

**Tests:** T11 (threshold, one chunk per call, order kept under concurrency, cap of 3 never exceeded, one failed chunk leaves the others intact), plus an empty-input test. 4 new tests.

**Files:** `app/decisions/jev_provider.py`, `tests/unit/test_jev_provider.py`

## Step 6: Jev verify

**Commit:** `feat(decisions): add Jev answer verification`

**What:** `JevDecisionProvider.verify()` sends two Nouls, `grounded` and `answers_question`, in one request with state `{"question", "context", "answer"}`. Without context it drops both the `context` field and the grounded question, matching v1, which skips the grounded check when there is no context. Each check passes at `>= JEV_VERIFY_THRESHOLD`.

**Why one request:** Jev evaluates questions in parallel, so asking both at once costs about the same time as asking one. The node still ignores "answers the question" when the answer is not grounded, so the graph takes the same path as v1.

**Live sanity check (v1's own grader test cases, 25 Sept 2026):**

| Case | Grounded (score) | Answers (score) | Latency |
|---|---|---|---|
| Falcon 9 uses LOX and RP-1 (correct) | True (0.99) | True (0.98) | 809 ms |
| Falcon 9 uses liquid hydrogen, built in Texas (hallucinated) | False (0.01) | False (0.45) | 459 ms |
| "The context does not say who founded SpaceX" | **True (0.97)** | False (0.18) | 556 ms |
| Eiffel Tower "is located in Paris" to "how tall", no context | n/a | False (0.02) | 503 ms |

The third row is the important one: the grounded criteria carry v1's "saying the context lacks it counts as grounded" rule, so Jev does not recreate v1's "I don't know" loop. The low answer score then sends the graph to web search, which is v1's intended behaviour for a grounded but unhelpful answer.

**Tests:** T12 (one request with both checks, no grounded question without context, inclusive threshold), a missing-score test, and T13 for an oversized context. 5 new tests.

**Files:** `app/decisions/jev_provider.py`, `tests/unit/test_jev_provider.py`

## Step 7: fallback wrapper and factory

**Commit:** `feat(decisions): add per-decision LLM fallback and enable jev mode`

**What:**

- `app/decisions/fallback.py`: `FallbackProvider` tries Jev for each decision and catches only `JevDecisionError`. On a failure it asks the LLM for that one decision and records `fallback_reason` and `jev_attempt` (what Jev said, or why it failed). For grading, only the failed chunks are re-graded, in one batched LLM call. With `JEV_FALLBACK_TO_LLM=false` Jev errors are raised instead.
- `app/decisions/factory.py`: `DECISION_PROVIDER=jev` now builds `FallbackProvider(JevDecisionProvider(...), LLMDecisionProvider())` from settings, and raises a clear error if `AI_GATEWAY_API_KEY` is missing. The Jev imports sit inside that branch, the same way `app/llm.py` imports each provider only in its own branch.
- `app/main.py`: startup builds the provider once, so a missing key stops the server at boot (NFR6) instead of failing every query.

**Why only `JevDecisionError`:** a Jev failure is expected (free-tier rate limits, `unclear`, timeouts) and has a known LLM answer. Any other exception is a bug in our code, and hiding it behind a silent fallback would make it invisible.

**Checks (25 Sept 2026):**

- With `DECISION_PROVIDER=jev` and no key, the app refused to start: `DECISION_PROVIDER=jev needs AI_GATEWAY_API_KEY in .env`.
- Live run of the same 5 eval questions as step 2, in `jev` mode:

| Question | Route (v1 to v2) | Steps, grounded, retries | Jev route | Jev grade (wall) | Jev verify |
|---|---|---|---|---|---|
| q01 documents | same | same | documents, 784 ms | 8/8 kept, 1666 ms | 780 ms |
| q11 general | same | same | general_knowledge, 423 ms | n/a | 454 ms |
| q18 override case | same (override fired) | same | general_knowledge, 513 ms | 8/8 kept, 1501 ms | 707 ms |
| q21 web | same | same | web_search, 475 ms | n/a | 679 ms |
| q32 `?` | crash to crash | n/a | `unclear`, fell back to the LLM router, which crashed (K1) | n/a | n/a |

For comparison, the step 2 `llm` run of the same questions took 2048 to 10006 ms per route decision, 2289 to 4277 ms per grade, and 2187 to 5424 ms per verify. That is five questions, one run each, so it shows direction, not a benchmark; Phase 5 measures it properly. Jev kept 8 of 8 chunks on q01 and q18, where the LLM kept 7 and 4, which matches the leniency seen in step 5.

**Tests:** T16 (route and verify fall back, record reason and attempt), T17 (only failed chunks go to the LLM, in one call; no failures means no LLM call), T18 (fallback disabled raises), T20 (jev without a key fails fast; with a key builds the stack from settings), and a check that non-Jev exceptions are not swallowed. 9 new tests, 56 in total.

**Files:** `app/decisions/fallback.py`, `app/decisions/factory.py`, `app/main.py`, `tests/unit/test_fallback.py`

## Step 8: decision logs in MongoDB

**Commit:** `feat(logging): log every decision to MongoDB`

**What:** `app/decisions/decision_log.py` adds `LoggedProvider`, which wraps whichever provider the factory built (llm, or jev with fallback) and writes one document per decision to the `decision_logs` collection, one per chunk for grading. `MongoDecisionLog` uses a sync `pymongo` client, created on first write. A `request_id` contextvar ties each document to one query. The factory adds the wrapper when `JEV_LOG_DECISIONS=true`; the setting keeps the brief's name but covers both modes, since FR6 asks for every decision.

**Why these choices:**

- **Sync pymongo, not the app's Motor client:** the graph nodes are sync and cannot await Motor. pymongo was already installed as part of Motor.
- **A contextvar for `request_id`:** it keeps the provider interface unchanged. A test confirms LangGraph passes the contextvar into the nodes it runs; without that, every real log would have `request_id=None`.
- **Never raise:** a Mongo error only logs a warning. A dead Mongo waits up to 2 s (`serverSelectionTimeoutMS`) per write, which is acceptable because the app already needs Mongo for uploads.
- **Previews only:** at most 200 characters of the question and passage. No full passages, context, answers, headers, or keys (NFR5).

**Live check (25 Sept 2026):** one real Jev route decision, logged with `request_id="manual-check-step8"` and read back from Mongo: provider `jev`, model `typesafe-ai/jev`, result `general_knowledge`, confidence 1, 1356 ms, 460 input tokens, cost 0, market cost 0.00001932 USD. The API key does not appear in the document. That test document was left in place and is easy to filter out by its `request_id`.

**Tests:** T19 (one document per decision with request id and app version, fallback reason and attempt kept, previews capped, decisions returned unchanged, dead Mongo swallowed, empty grade writes nothing), contextvar through LangGraph, and the factory wrapping. 7 new tests, 63 in total.

**Files:** `app/decisions/decision_log.py`, `app/decisions/factory.py`, `tests/unit/test_decision_log.py`, `tests/unit/test_factory_and_summaries.py`, `tests/unit/test_fallback.py`
