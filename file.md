# CLAUDE.md

Context for Claude Code sessions in this repo. Read this before making changes.

## What this project is

An agentic Adaptive RAG system. It decides, per query, where to get an answer from (indexed documents, indexed code, live web search, or the model's own knowledge), grades what it retrieves, and checks its own answers before returning them.

Built as a portfolio project. The architecture follows [dhruvsinghal09/Adaptive-Rag](https://github.com/dhruvsinghal09/Adaptive-Rag), rebuilt from the ground up rather than cloned, with a model-agnostic provider layer and a custom frontend added.

**I need to be able to explain every part of this in an interview.** When you make changes, explain what you did and why, and flag anything I'd struggle to defend. Don't silently refactor across many files — small, reviewable changes I can follow.

## Stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph |
| API | FastAPI |
| Vector store | Qdrant (local, Docker) — collections `documents` and `code_documents` |
| Metadata store | MongoDB (local, Docker) — DB `adaptive_rag` |
| Web search | Tavily |
| LLM | Model-agnostic (see below) |
| Embeddings | Model-agnostic, currently local sentence-transformers |
| Frontend | Static HTML/CSS/JS served by FastAPI from `static/` |

## Architectural rules (do not break these)

1. **Providers are abstracted.** All LLM and embeddings instantiation happens behind `get_llm()` and `get_embeddings()` in `app/llm.py`, selected by the `LLM_PROVIDER` and `EMBEDDINGS_PROVIDER` env vars. **Never import a provider class (`ChatAnthropic`, `ChatGoogleGenerativeAI`, `ChatGroq`, `ChatOllama`, etc.) anywhere outside `app/llm.py`.** This is the single most important constraint in the codebase — it is what let me swap providers mid-build when I hit a rate limit.
2. **There is an optional fast/smart split** (`LLM_PROVIDER_FAST` / `LLM_PROVIDER_SMART`) so cheap high-volume nodes (routing, grading) can run on a different model than final generation.
3. **The static mount must stay last** in `app/main.py`. `app.mount("/", StaticFiles(...))` is a catch-all and will swallow the API routes if registered before them.
4. **Retry loops must always have a hard cap.** The self-correction edges can cycle; `retry_count` maxes at 2 and then ends regardless of grade results. Never remove this guard.
5. **Changing the embeddings model requires re-indexing.** Different models produce different vector dimensions, so existing Qdrant vectors become incompatible.
6. **Decisions go through the decision provider (v2).** The route, grade, and verify nodes call `get_decision_provider()` in `app/decisions/factory.py` and never call the LLM grader/router functions or Jev directly. `DECISION_PROVIDER=llm|jev` picks the provider; Jev falls back to the LLM per decision. Jev is an HTTP client under `app/decisions/`, not a LangChain chat model, so rule 1 still holds. Jev question wording lives in `app/decisions/jev_questions.yaml`.

## The graph

Nodes, in the order a query can flow through them:

1. `route_question` — classifies the query into `documents` / `code` / `web_search` / `general_knowledge` using structured output (`RouteQuery` in `app/router.py`)
2. `retrieve` — vector search against the appropriate Qdrant collection
3. `grade_documents` — filters retrieved chunks for relevance (`GradeDocuments` in `app/grader.py`)
4. `decide_to_generate` — conditional edge: relevant docs → generate, none → web search
5. `web_search` — Tavily, ~3 results, written into `state["documents"]` so `generate` consumes it unchanged
6. `generate` — answers from whatever context is in state (documents, web results, or none)
7. `grade_generation` — conditional edge running two checks:
   - **hallucination check**: is the answer grounded in the context? If not → regenerate
   - **answer check**: does it address the question? If grounded but unhelpful → web search for better context
   - both pass, or retry limit hit → END

Every node appends to `state["steps"]` (`{name, detail}`) and prints its name, so the path is visible in logs and returned to the frontend.

## API

- `POST /rag/documents/upload` — file plus `X-Description` header. Chunks, embeds, upserts to Qdrant, writes metadata to MongoDB.
- `POST /query` — runs the graph. Returns `answer`, `route`, `documents_found`, `documents_kept`, `grounded`, `retry_count`, `failed`, and `steps`, plus (v2) an optional `decisions` list: one entry per route / grade / verify decision with provider, result, confidence, latency, and fallback reason.
- `GET /` — the frontend. `GET /docs` — Swagger.

## Frontend

Single file at `static/index.html`, no framework or build step. Two panes: document library left, conversation right.

**The routing trace is the point of the UI.** Each answer carries a compact mono summary line (e.g. `documents · 2/4 docs kept · grounded`) that expands into the full step list. It is the only element in the interface that uses the accent color — everything else is ink, paper, and hairlines, deliberately, so the agent's reasoning is what stands out. Design tokens live in the `:root` block at the top of the file; restyle from there.

It has a `MOCK` flag for working on the UI without a backend. Should be `false` in normal use.

## Running it

```bash
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 27017:27017 mongo
source venv/bin/activate
uvicorn app.main:app --reload
```

Then `http://localhost:8000`.

## Current state and what's left

Layers 1–3 are built and working (spine, adaptive router with grading and web search, self-correction). Frontend is built and wired. The document grader is batched (one LLM call for all chunks), and Groq and OmniRoute are in the provider factory.

**v2.0 (tag `v2.0.0`)** adds the swappable decision layer with Jev, per-decision fallback, decision logs in MongoDB, the `decisions` API field and UI rows, 66 offline tests (`python -m pytest`), and an evaluation. Default is `DECISION_PROVIDER=llm`; Jev is opt-in. Everything about v2 is in `docs/v2-jev/`, and the changes are in `CHANGELOG.md`.

Remaining:
- [ ] Add Ollama to the provider factory for free local inference. Machine is an RTX 4060 (8GB VRAM), so 7–8B models run fine locally.
- [ ] Verify structured output reliability on any new provider — the router and graders depend entirely on constrained `Literal` outputs, and smaller models are weaker at this. Test with the standalone `__main__` blocks in `app/router.py` and `app/grader.py` before running the full graph.
- [ ] v2.1: tune Jev on a new held-out question set (retry once on 503, allow correct refusals in the answer check, stricter grade threshold). See `docs/v2-jev/05-release-notes.md`.
- [ ] Known v1 issues K1 to K4 (`docs/v2-jev/01-requirements.md`), e.g. the `?` input crashing the router.
- [ ] Architecture diagram, demo recording.

## Working style

- Test nodes in isolation using the `__main__` blocks before running the full graph. The full graph makes 6–8 LLM calls per query; testing one node shouldn't cost all of them.
- Commit at each working checkpoint.
- `BUILDLOG.md` tracks decisions and what broke; `UNDERSTANDING-CHECKS.md` has the questions I should be able to answer per layer.
- Never commit `.env`. Only `.env.example`.
