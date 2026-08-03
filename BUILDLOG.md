# Build Log

A running log of building this project in public. Each entry captures what got built, the decisions behind it, what broke, and what I learned. Newest entries go at the top.

The point of this log is honesty and reasoning, not polish. It's the paper trail that shows the work is mine.

---

## Entry template (copy this for each new entry)

### [Date] — [Layer / milestone]

**Built:**
- What actually works now that didn't before.

**Decisions:**
- A choice I made and why. Include the alternative I didn't pick.

**What broke:**
- The bug or wall I hit, and how I got past it (or that I'm still stuck).

**Learned:**
- One thing I understand now that I didn't this morning.

**Next:**
- The single next thing.

---

## [2026-07-28] — Day 0: Setup

**Built:**
- Public repo created, `.gitignore` in place, keys configured, Docker running Qdrant and MongoDB.

**Decisions:**
- LLM provider: Started with Gemini as the baseline because it is easily accessible, but designed a factory pattern to quickly swap providers without breaking the graph.
- Embeddings: Local HuggingFace (`all-MiniLM-L6-v2`) because it is free, fast, and completely runs offline via sentence-transformers, avoiding API costs for indexing.

**What broke:**
- Nothing initially, just setting the foundation.

**Learned:**
- The LangGraph structure heavily relies on state dictionaries that must be carefully passed between nodes.

**Next:**
- Layer 1: get the upload → retrieve → generate loop working end to end.

---

## [2026-07-30] — Layer 1-3: Adaptive Routing, Grading, & Dual-LLMs

**Built:**
- Full LangGraph spine implemented (upload → retrieve → grade → generate).
- Split LLM Architecture: Integrated Groq (Llama-3.1-8b) for ultra-fast routing and grading, and NVIDIA NIM (Llama-3.1-70b) for complex generation and reasoning.
- UI Integration: Swapped API endpoint in `index.html` to communicate directly with FastAPI without CORS issues by mounting static files.

**Decisions:**
- Dual-Provider Factory: Chose to split tasks between a "fast" model (Groq) and a "smart" model (NVIDIA). Using a single model for both routing (needs speed) and generation (needs reasoning) is inefficient.
- Forced `json_mode` on Groq wrapper instead of tool calling because open-source Llama models frequently output raw `<function>` XML tags instead of strict Pydantic tool calls.

**What broke:**
- **The "I don't know" Loop:** When the model accurately stated it didn't know the answer, the Hallucination grader marked it as "ungrounded" and caused an infinite loop! Fixed by explicitly instructing the grader that acknowledging a lack of facts is actually factually accurate.
- **Groq JSON Schema Bug:** LangChain's `json_mode` doesn't pass Pydantic schemas automatically like tool calling does, so the LLM guessed the JSON keys incorrectly (e.g. `{"route": "documents"}` instead of `{"datasource": "documents"}`). Fixed by hardcoding the exact JSON schemas and Literal options into the system prompts.
- **NVIDIA Deprecation 404:** Initialized with `meta/llama3-70b-instruct` which was recently deprecated by NVIDIA and caused timeout/404 errors. Updated to `meta/llama-3.1-70b-instruct` and removed the hardcoded `base_url` to let LangChain route it internally.

**Learned:**
- Using `json_mode` across LangChain requires you to manually inject the exact expected JSON schema and keys directly into your prompt text, otherwise the LLM is just guessing.
- `uvicorn --reload` caches environment variables from the parent process, meaning hot-reloading a `.py` file will NOT refresh a changed `.env` file unless you restart the entire server!

**Next:**
- Finalize documentation, record demo, and ship!

## Milestones to log as I hit them

- Day 0 — Setup and repo
- Layer 1 — Spine works (upload a doc, ask a question, grounded answer)
- Layer 2 — Adaptive router live (three questions take three different paths)
- Layer 3 — Self-correction firing (a bad first answer gets caught and retried)
- Ship — Demo recorded, README finalized, posted
