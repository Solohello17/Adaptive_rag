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

## [Date] — Day 0: Setup

**Built:**
- Public repo created, `.gitignore` in place, keys configured, Docker running Qdrant and MongoDB.

**Decisions:**
- LLM provider: [Gemini / Claude / OpenAI] because [reason].
- Embeddings: [Gemini / local] because [reason].

**What broke:**
-

**Learned:**
-

**Next:**
- Layer 1: get the upload → retrieve → generate loop working end to end.

---

## Milestones to log as I hit them

- Day 0 — Setup and repo
- Layer 1 — Spine works (upload a doc, ask a question, grounded answer)
- Layer 2 — Adaptive router live (three questions take three different paths)
- Layer 3 — Self-correction firing (a bad first answer gets caught and retried)
- Ship — Demo recorded, README finalized, posted
