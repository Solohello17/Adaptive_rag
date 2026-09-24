# 01. Requirements: Jev decision layer (v2.0)

Status: draft for review, 25 Sept 2026

## 1. Purpose

v2.0 adds [Jev](https://docs.typesafe.ai) by TypeSafe AI as a second way to make the three judgment calls inside the Adaptive RAG graph: where to answer a question from, which retrieved chunks are relevant, and whether an answer is good enough to return. The LLM keeps doing all the writing. One setting switches between the two, and the LLM steps in automatically whenever Jev fails or is unsure.

The goal is a fair, measured comparison, not a replacement for its own sake. If Jev is not at least as good on our evaluation set, v2.0 ships with the LLM as the default and Jev as an option.

## 2. Background: how v1 decides today

v1 makes three kinds of decision, all on the "fast" LLM through structured output. These are the exact places v2 changes.

| Decision | v1 function | Called from (node) | Output | State written |
|---|---|---|---|---|
| Route the question | `route_question()` in `app/router.py` (`RouteQuery`) | `route_question_node` in `app/graph.py` | one of `documents`, `code`, `web_search`, `general_knowledge` | `route` |
| Grade retrieved chunks | `grade_documents_batch()` in `app/grader.py` (one call for all chunks) | `grade_documents` | `yes` / `no` per chunk | `documents`, `documents_kept` |
| Verify the answer | `grade_hallucination()` then `grade_answer()` in `app/grader.py` | `check_generation` | `yes` / `no` each | `grounded`, `route_decision`, `retry_count` |

Details that matter for v2:

- The router only sees the question. It does not use chat history (there is none) or the upload descriptions. Its prompt hard-codes domain hints for each route.
- After the router, a similarity probe with no LLM call can override `web_search` or `general_knowledge` to `documents` or `code` when a strong match exists in Qdrant (`ROUTER_OVERRIDE_THRESHOLD`).
- The grounded check only runs when there is context. If it fails, the answer check is skipped and the graph regenerates.
- The grounded prompt treats "the context does not contain this" as grounded. This rule fixed an infinite "I don't know" loop during v1.
- The retry cap (`retry_count >= 2`) ends the loop before any grading.
- Graph nodes are synchronous. `POST /query` calls the graph synchronously.

### v1 baseline (measured, `results/eval/v1_baseline.json`)

One run of the 40-question set on 25 Sept 2026, `LLM_PROVIDER` and `LLM_PROVIDER_FAST` both `omniroute` with the `auto/coding:free` alias.

| Metric | Result |
|---|---|
| Questions completed | 39 of 40 (1 crash) |
| Final route correct | 38 of 40 overall, 97.4% of completed |
| Router alone correct | 37 of 40 overall, 94.9% of completed |
| Median / p95 latency, route decision | 3.9 s / 6.0 s |
| Median / p95 latency, grade decision (batched) | 3.8 s / 6.1 s |
| Median / p95 latency, grounded check | 4.6 s / 8.0 s |
| Median / p95 latency, answer check | 4.2 s / 5.3 s |
| Median / p95 total time per question | 18.0 s / 45.0 s |

Known v1 issues found by the baseline. They are recorded here and are **not** fixed as part of v2.0 unless separately approved:

- **K1.** Input `?` crashed the router: the model replied in prose instead of JSON, so `/query` would return a 500.
- **K2.** For two injection questions (q36, q39) the answer was correct, but the answer check read the injected instruction as part of the question, judged the answer unhelpful, and searched the web until the retry cap.
- **K3.** Two web questions (q23, q30) hit the retry cap. The cap worked as designed.
- **K4.** "What is the capital of Japan?" was routed to web search. The answer was still correct.

## 3. Scope

**In scope**

- A decision provider interface with an LLM implementation (wrapping the v1 functions unchanged) and a Jev implementation.
- Per-decision automatic fallback from Jev to the LLM.
- Logging every decision to MongoDB.
- An optional `decisions` field in the `/query` response and a small display of it in the existing trace UI.
- Unit and integration tests, an evaluation of both providers, and the docs in `docs/v2-jev/`.

**Out of scope**

- Authentication.
- Changing generation, the graph's nodes, edges, or retry cap, or the v1 prompts.
- Chat history or sessions.
- Indexing into `code_documents`. Nothing writes to it today, so the `code` route searches an empty collection. Noted, not changed.
- Fixing K1 to K4 (see above).
- Making the API asynchronous or multi-user.

## 4. Terms

| Term | Meaning |
|---|---|
| Decision | One routing, grading, or verification judgment |
| Decision provider | The component that makes decisions: `llm` or `jev` |
| Choice | Jev question type that picks one option from a set we define |
| Noul | Jev question type that returns a probability from 0 to 1 for a yes/no question |
| Fallback | Using the LLM for one decision because Jev failed or was unsure |
| Shadow check | Evaluation only: asking the LLM the same grade or verify question Jev answered, to measure agreement |

## 5. Functional requirements

| ID | Requirement | Verified by |
|---|---|---|
| FR1 | `DECISION_PROVIDER=llm\|jev` in `.env` switches all three decision types. Default is `llm`. | Unit test, integration tests in both modes |
| FR2 | Jev routes the question with one Choice question offering `documents`, `code`, `web_search`, `general_knowledge`, and `unclear`. The final route is always one of the four v1 routes. The similarity override still runs after the provider, in both modes. | Unit tests, evaluation |
| FR3 | Jev grades each retrieved chunk with its own Noul question. A chunk is relevant if the score is at least `JEV_GRADE_THRESHOLD`. Chunks are graded concurrently, at most `JEV_MAX_CONCURRENCY` at a time. | Unit tests, evaluation |
| FR4 | Jev verifies the answer with two Noul questions (grounded, answers the question) in one request. The grounded question is only asked when there is context. A check passes if its score is at least `JEV_VERIFY_THRESHOLD`. The graph's decision logic after verification is unchanged: not grounded means regenerate; grounded but unhelpful means web search. | Unit tests, integration tests |
| FR5 | Each decision falls back to the LLM on its own when Jev times out, returns 429 or another HTTP error, returns a response we cannot parse, would receive a state longer than `JEV_MAX_STATE_CHARS`, answers `unclear`, or answers a route below `JEV_ROUTE_MIN_CONFIDENCE`. For grading, only the chunks that failed are sent to the LLM. The reason is recorded. With `JEV_FALLBACK_TO_LLM=false` the error is raised instead. | Unit tests with mocked HTTP |
| FR6 | Every decision is written to the MongoDB collection `decision_logs` with: timestamp, app version, request id, decision type, provider, model id, fallback reason, result, confidence or score, probabilities, latency, input tokens, cost and market cost when Jev reports them, and a 200-character preview of the question (and of the passage, for grading). `JEV_LOG_DECISIONS=false` turns this off. A logging failure never fails the query. | Unit tests, manual check in Mongo |
| FR7 | `POST /query` returns a new optional field `decisions`: a list with one entry per decision (type, provider, result, confidence, latency, fallback reason). All existing fields, including `answer`, are unchanged. | API test |
| FR8 | The frontend shows, inside the existing expandable trace, the provider and confidence for each decision, and whether a fallback happened. | Manual check, screenshots |
| FR9 | All Jev question wording lives in `app/decisions/jev_questions.yaml`. The v1 prompts in `app/router.py` and `app/grader.py` are not edited. | Code review |
| FR10 | The Jev model id is pinned in `JEV_MODEL` if the gateway lists a versioned id; otherwise it stays `typesafe-ai/jev` and the docs say it is unpinned. The model id returned by each response is logged. | Model-list script output |
| FR11 | `scripts/evaluate_decisions.py` runs the eval set with either provider, records route accuracy, latency, tokens, cost, and fallbacks, and with `--shadow-llm` also records LLM agreement for each Jev grade and verify decision. `scripts/compare_results.py` writes a comparison report and charts. | Saved results files |

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR1 | **No regressions.** In `llm` mode the same v1 functions are called with the same inputs, in the same order, the same number of times. Because the OmniRoute alias picks a model per request, runs are not deterministic, so the regression check is: in `llm` mode, no eval category loses more than one correct route compared with the v1 baseline. |
| NFR2 | API keys live only in `.env`. `.env.example` has placeholders only. |
| NFR3 | Jev timeout and concurrency are configurable (`JEV_TIMEOUT_SECONDS`, `JEV_MAX_CONCURRENCY`) to stay inside free-tier rate limits. |
| NFR4 | New code matches the existing style: sync functions, the `steps` list pattern, the same comment and print conventions. |
| NFR5 | Nothing logged or returned contains API keys or full documents. |
| NFR6 | If `DECISION_PROVIDER=jev` and `AI_GATEWAY_API_KEY` is empty, the app fails at startup with a clear message instead of silently falling back on every query. |
| NFR7 | The retry cap and all existing architectural rules still hold. LLMs are still only created in `app/llm.py`. Jev is a separate HTTP client under `app/decisions/`, not a LangChain chat model. |
| NFR8 | Every number in code comments, docs, and posts comes from a real run. |

## 7. Constraints

- **Vercel AI Gateway free tier:** about $5 of credit every 30 days and lower rate limits. Never buy credits, because that moves the account to the paid tier and ends the free credit.
- **Jev early access limits (reported by the vendor, may change):** text or JSON input only, about 64k tokens in total with about 32k for state plus the longest question, and best in English.
- **Jev is literal and weak with numbers and dates,** so it is never used for calculation.
- **Machine:** Windows, PowerShell, a single local user.

## 8. Assumptions

- The Vercel endpoint and request shape in the brief (Section 4) are still current. This is checked with a real call in implementation step 3.
- Qdrant, MongoDB, OmniRoute, and Tavily are running locally or reachable.
- The eval set and the three indexed ML PDFs stay the same between the baseline and the v2 runs.

## 9. Release decision rule

`DECISION_PROVIDER` defaults to `jev` in the 2.0.0 release only if the `jev` run:

1. matches or beats the `llm` run's final route accuracy overall, and
2. loses no more than one correct route in any category compared with the `llm` run, and
3. completes every question (fallbacks allowed, crashes not).

Otherwise v2.0 ships with `llm` as the default and Jev as opt-in, and the docs say why. Latency, cost, fallback rate, and shadow agreement are reported either way but do not decide the default on their own.

## 10. Where this brief differs from the real code

| Brief | This repo |
|---|---|
| `src/...`, `settings.py`, `prompts.yaml` | `app/...`, `app/config.py`, prompts inline in `router.py` and `grader.py` |
| Routes `index`, `general`, `search` | `documents`, `code`, `web_search`, `general_knowledge` |
| `/rag/query` with a `result` field | `POST /query` with an `answer` field |
| Streamlit UI | Static `static/index.html` |
| Session id, chat history in MongoDB | No sessions; a per-request id is generated instead |
| ReAct agent, query rewriting | Neither exists |
| `src/config/jev_questions.yaml` | `app/decisions/jev_questions.yaml` (`app/config.py` is already a module) |
| `decisions/logging.py` | `decisions/decision_log.py`, so it does not shadow Python's `logging` |
