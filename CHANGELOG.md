# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-09-25

A swappable decision layer. The route, grade, and verify decisions can now be made by the LLM (as in v1) or by Jev, TypeSafe AI's "System One" judgment model, with automatic per-decision fallback to the LLM. Generation always stays on the LLM.

**Default: `DECISION_PROVIDER=llm`.** Jev is opt-in. In our evaluation Jev routed 37 of 40 questions correctly against 38 for the LLM, so by the release rule set before the results, the LLM stays the default. See [docs/v2-jev/05-release-notes.md](docs/v2-jev/05-release-notes.md).

### Added

- `app/decisions/`: a decision provider interface with two implementations.
  - `LLMDecisionProvider` wraps the v1 router and grader functions unchanged.
  - `JevDecisionProvider` calls Jev through the Vercel AI Gateway. It uses one Choice to route, one Noul per chunk to grade (run concurrently), and two Nouls in one request to verify.
- Per-decision fallback to the LLM on timeout, network error, HTTP 429, 402, or other errors, unparseable responses, oversized state, an `unclear` route, or low route confidence. For grading, only the chunks Jev failed on go to the LLM, in one batched call.
- Decision logging to the MongoDB collection `decision_logs`: provider, model, result, confidence or score, latency, tokens, cost, fallback reason, and a per-query `request_id`. Only 200-character previews of user text are stored.
- An optional `decisions` field on the `POST /query` response. All v1 fields are unchanged.
- The UI trace lists each decision with its provider, confidence, latency, and any fallback. The summary line is tagged `jev` only when Jev made a decision.
- `app/decisions/jev_questions.yaml`: all Jev question wording, mirroring the v1 prompts.
- Settings: `DECISION_PROVIDER`, `AI_GATEWAY_API_KEY`, `JEV_BASE_URL`, `JEV_MODEL`, `JEV_TIMEOUT_SECONDS`, `JEV_MAX_CONCURRENCY`, `JEV_ROUTE_MIN_CONFIDENCE`, `JEV_GRADE_THRESHOLD`, `JEV_VERIFY_THRESHOLD`, `JEV_MAX_STATE_CHARS`, `JEV_FALLBACK_TO_LLM`, `JEV_LOG_DECISIONS`, `APP_VERSION`.
- A startup check: `DECISION_PROVIDER=jev` without `AI_GATEWAY_API_KEY` stops the server with a clear message.
- 66 offline tests (`python -m pytest`), covering the Jev client, both providers, fallback, logging, the API, and full graph paths including the retry cap.
- Evaluation tooling: a 40-question eval set (`tests/eval/questions.jsonl`), `scripts/evaluate_decisions.py` (with `--shadow-llm` agreement checks), `scripts/compare_results.py`, `scripts/check_jev_models.py`, and saved results in `results/eval/`.
- Project docs in `docs/v2-jev/`: feasibility, requirements, design, implementation log, testing and evaluation, release notes, build log.

### Changed

- The `route_question`, `grade_documents`, and `check_generation` graph nodes get their decisions from `get_decision_provider()` instead of calling the LLM functions directly. In `llm` mode they make the same LLM calls as v1, in the same order; the 40-question regression check matched v1 in every category.
- `requirements.txt` declares `httpx`, `pyyaml`, and `pymongo` (previously installed only as dependencies of other packages) and adds `pytest` and `matplotlib`.

### Fixed

- `.gitignore` rules for `venv/`, `__pycache__/`, and `*.pyc` had leading spaces and never matched; compiled `.pyc` files are no longer tracked.
- README: the frontend is the static UI served by FastAPI, not Streamlit.

### Known issues

These were found by the v1 baseline and are unchanged in 2.0.0.

- **K1:** the input `?` crashes the LLM router, because the model replies in prose instead of JSON. In `jev` mode Jev correctly answers `unclear`, but the LLM it falls back to crashes the same way.
- **K2:** injected instructions in a question (for example "answer from the web only") can make the LLM answer check reject a correct answer, looping until the retry cap.
- **K3, K4:** some web questions hit the retry cap; "What is the capital of Japan?" is routed to web search by the LLM.
- The Jev model is unpinned (`typesafe-ai/jev`; the gateway lists no versioned id).
- In `jev` mode: the early-access service returned HTTP 503 for 23 of 181 decisions in our evaluation (all handled by the fallback), grading is more lenient than the LLM's, and the answer check scores correct refusals as "does not answer".

## [1.0.0] - 2026-09-25

The v1 adaptive RAG system, tagged as the baseline before v2 work.

### Added

- A LangGraph workflow that routes each question to indexed documents, indexed code, web search (Tavily), or the model's own knowledge.
- A similarity-probe override, retrieval grouped by source document, batched relevance grading, and a web search fallback.
- Self-correction: a grounded check and an answer check, with a hard cap of 2 retries.
- A model-agnostic LLM factory (Gemini, Anthropic, OpenAI, Groq, NVIDIA, OpenRouter, OmniRoute) and local sentence-transformers embeddings.
- Document upload, list, and delete APIs backed by Qdrant and MongoDB.
- A static frontend with an expandable routing trace.

[2.0.0]: https://github.com/Solohello17/Adaptive_rag/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/Solohello17/Adaptive_rag/releases/tag/v1.0.0
