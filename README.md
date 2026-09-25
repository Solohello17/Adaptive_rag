# Adaptive RAG

An agentic Retrieval-Augmented Generation system that decides, per query, where to get its answer from: your indexed documents, the model's own knowledge, or a live web search. It grades its own retrievals and answers, and self-corrects when they fall short.

> 🚧 **Building in public.** This project is being built openly over a short sprint. Follow the process in [BUILDLOG.md](./BUILDLOG.md) (v1) and [docs/v2-jev/build-log.md](./docs/v2-jev/build-log.md) (v2). Status and roadmap are at the bottom of this file.

## What's new in v2.0

v2.0 makes the system's three judgment calls swappable: **where to answer from** (route), **which retrieved chunks are relevant** (grade), and **whether the answer is grounded and actually answers the question** (verify). Each can be made by the LLM, exactly as in v1, or by [Jev](https://docs.typesafe.ai), TypeSafe AI's "System One" model that answers typed questions with probabilities instead of generating text. The LLM still writes every answer.

- **One setting switches it:** `DECISION_PROVIDER=llm` or `jev`.
- **Automatic fallback, per decision.** If Jev times out, is rate limited or unavailable, says `unclear`, or is not confident enough, that one decision goes to the LLM and the reason is recorded. For grading, only the failed chunks are re-graded.
- **Every decision is logged** to MongoDB (`decision_logs`) with provider, latency, tokens, cost, and fallback reason.
- **Visible in the API and UI.** `POST /query` returns an optional `decisions` list; the UI trace shows who made each call.

**Measured on our 40-question eval set** (one run each; full results in [results/eval/comparison.md](./results/eval/comparison.md)):

| | LLM decisions | Jev decisions |
|---|---|---|
| Final route correct | 38/40 | 37/40 |
| Median route decision | 2.04 s | 0.64 s |
| Median verify decision | 3.93 s | 0.62 s |
| Median time per question | 10.48 s | 6.92 s |
| Decisions handed back to the LLM | n/a | 28 of 181 (23 were HTTP 503s from the early-access service) |

Jev was faster but not more accurate, so **v2.0 ships with `llm` as the default and Jev as opt-in.** The full story, including what Jev did better and worse, is in [docs/v2-jev/05-release-notes.md](./docs/v2-jev/05-release-notes.md).

### Switching the decision provider

In `.env`:

```bash
DECISION_PROVIDER=jev
AI_GATEWAY_API_KEY=your_vercel_ai_gateway_key   # free tier is enough; never buy credits
```

Restart the server (uvicorn's `--reload` does not pick up `.env` changes). The startup log prints `decision provider = jev`, and the server refuses to start if the key is missing.

| Setting | Default | What it does |
|---|---|---|
| `DECISION_PROVIDER` | `llm` | `llm` or `jev` |
| `AI_GATEWAY_API_KEY` | empty | Vercel AI Gateway key; required for `jev` |
| `JEV_MODEL` | `typesafe-ai/jev` | Jev model id (unpinned: no versioned id is published) |
| `JEV_TIMEOUT_SECONDS` | `10` | per Jev call |
| `JEV_MAX_CONCURRENCY` | `3` | chunks graded at once |
| `JEV_ROUTE_MIN_CONFIDENCE` | `0.6` | below this, the route falls back to the LLM |
| `JEV_GRADE_THRESHOLD` | `0.5` | chunk relevant if Jev's score is at least this |
| `JEV_VERIFY_THRESHOLD` | `0.5` | grounded / answers check passes at or above this |
| `JEV_MAX_STATE_CHARS` | `60000` | larger inputs skip Jev and use the LLM |
| `JEV_FALLBACK_TO_LLM` | `true` | `false` raises Jev errors instead (for testing) |
| `JEV_LOG_DECISIONS` | `true` | log every decision to MongoDB (both modes) |

The thresholds are untuned starting values. The Jev question wording lives in `app/decisions/jev_questions.yaml`.

### Tests and evaluation

```bash
python -m pytest                                                   # 66 offline tests, no keys needed
python scripts/evaluate_decisions.py --provider llm                # 40 questions, real services
python scripts/evaluate_decisions.py --provider jev --shadow-llm   # also records LLM agreement
python scripts/compare_results.py                                  # writes results/eval/comparison.md and charts
```

v2 docs: [docs/v2-jev/](./docs/v2-jev/README.md). Changes: [CHANGELOG.md](./CHANGELOG.md).

## What it does

Most RAG systems retrieve first and ask questions later, which wastes calls on questions that don't need documents and gives shallow answers on questions that need fresh information. This system routes each query through an agentic graph that makes those decisions explicitly:

- **Routes** each question to indexed documents, general model knowledge, or web search
- **Retrieves** from a vector store when documents are the right source
- **Grades relevance** of what it retrieved and drops the noise
- **Falls back to web search** (via Tavily) when the documents aren't enough
- **Grades its own answer** for grounding (is it supported by the sources?) and usefulness (does it actually answer the question?), and retries when it isn't

## Architecture

The orchestration is a LangGraph state graph. The nodes:

1. `route` — classify the query (docs / knowledge / web)
2. `retrieve` — vector search against the right collection
3. `grade_documents` — filter retrieved chunks by relevance
4. `decide` — enough good context, or fall through to web?
5. `web_search` — Tavily, when documents are insufficient
6. `generate` — answer from the assembled context
7. `grade_hallucination` — is the answer grounded? if not, regenerate
8. `grade_answer` — does it address the question? if not, re-retrieve or search

## Stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph |
| API | FastAPI |
| Vector store | Qdrant (collections: `documents`, `code_documents`) |
| Metadata store | MongoDB |
| Web search | Tavily |
| LLM | Model-agnostic: Gemini, Claude, or OpenAI (config-selected) |
| Embeddings | Model-agnostic: Gemini, OpenAI, or local (sentence-transformers) |
| Decision layer (v2) | LLM (default) or Jev via the Vercel AI Gateway, with per-decision fallback |
| Frontend | Static HTML/CSS/JS served by FastAPI from `static/` |

### Why model-agnostic

The LLM and embeddings sit behind factory functions (`get_llm()` / `get_embeddings()`), selected by environment variable. Switching providers is a config change, not a code change. The cheap, high-volume grading and routing nodes can run on a fast/cheap model while a stronger model handles final generation.

## Getting started

### Prerequisites

- Python 3.11+
- Docker (for Qdrant and MongoDB)
- An LLM API key (Gemini is free from Google AI Studio; Claude and OpenAI are pay-as-you-go)
- A Tavily API key (free tier)

### Setup

```bash
# clone
git clone https://github.com/<your-username>/adaptive-rag.git
cd adaptive-rag

# virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# dependencies
pip install -r requirements.txt

# start the databases
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 27017:27017 mongo

# configure
cp .env.example .env
# then fill in your keys and provider choices in .env
```

### Run

```bash
uvicorn app.main:app --reload      # UI at http://localhost:8000, API docs at /docs
```

## Roadmap

- [x] **Layer 1**: Infra and spine: FastAPI, MongoDB, Qdrant, model-agnostic providers, upload → retrieve → generate
- [x] **Layer 2**: Agentic router, document relevance grading, Tavily web search
- [x] **Layer 3**: Hallucination and answer grading, self-correction loops
- [x] Frontend (static UI with routing trace)
- [x] **v2.0**: Swappable decision layer with Jev, per-decision fallback, decision logs, evaluation
- [ ] v2.1: Tune Jev on a new held-out question set: retry once on 503, allow correct refusals in the answer check, stricter grade threshold
- [ ] Demo and write-up



## Author

Built by [Param Parmar]
