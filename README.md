# Adaptive RAG

An agentic Retrieval-Augmented Generation system that decides, per query, where to get its answer from: your indexed documents, the model's own knowledge, or a live web search. It grades its own retrievals and answers, and self-corrects when they fall short.

> 🚧 **Building in public.** This project is being built openly over a short sprint. Follow the process in [BUILDLOG.md](./BUILDLOG.md). Status and roadmap are at the bottom of this file.

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
| Frontend | Streamlit |

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
# backend
uvicorn app.main:app --reload      # http://localhost:8000  (docs at /docs)

# frontend
streamlit run streamlit_app.py     # http://localhost:8501
```

## Roadmap

- [ ] **Layer 1** — Infra and spine: FastAPI, MongoDB, Qdrant, model-agnostic providers, upload → retrieve → generate
- [ ] **Layer 2** — Agentic router, document relevance grading, Tavily web search
- [ ] **Layer 3** — Hallucination and answer grading, self-correction loops
- [ ] Streamlit frontend
- [ ] Demo and write-up



## Author

Built by [Param Parmar]
