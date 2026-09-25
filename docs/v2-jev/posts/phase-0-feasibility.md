# Phase 0: can I even reach Jev?

Starting v2 of my Adaptive RAG project. The idea: my RAG system makes three judgment calls on every question (where to look, which chunks are relevant, is the answer any good), and right now an LLM makes all of them. Each call takes seconds.

TypeSafe AI just released Jev, a "System One" model. It does not write text. You give it a state and typed questions, and it returns choices and probabilities. That sounds like exactly the shape of those three calls.

Step one was just getting access:

- TypeSafe direct: signups paused.
- Cloudflare Workers AI: the request reached Jev, then came back 402, insufficient balance.
- Vercel AI Gateway: worked on the free tier.

First real call: "What is the capital of France?" with three options. Jev picked `direct` with confidence 1, using 341 input tokens.

Next: measure my current system properly before changing anything.

Credit to Dhruv Singhal, whose Adaptive-Rag repo my architecture is based on.
