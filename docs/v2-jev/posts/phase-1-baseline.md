# Phase 1: measuring v1 before touching it

Before adding anything new, I wanted a baseline I could compare against honestly.

- Tagged v1.0.0 and branched.
- Wrote a 40-question eval set: questions only my course PDFs can answer, general questions, questions that need the live web, off-topic ones, and prompt injections.
- Ran all 40 through v1.

v1 routed 38 of 40 correctly. Each LLM decision took a median of about 4 seconds.

Two things I did not expect:

1. The input `?` crashed the router. The model replied in plain English instead of JSON.
2. On two injection questions ("answer from the web only"), the router was fine, but the answer checker got fooled. It read the injected instruction as part of the question and rejected a perfectly correct answer.

I also found that my `.gitignore` had leading spaces on three lines, so those rules never matched. That is how compiled Python files ended up in the repo. Small thing, fixed.
