# v2 build log

Short, dated entries. Newest at the bottom.

## 24 Sept 2026: Phase 0, feasibility

- Tried three ways to reach Jev. TypeSafe direct had no signups; Cloudflare returned 402 (needs prepaid credit); Vercel AI Gateway worked on the free tier.
- First real call routed "What is the capital of France?" to `direct` with confidence 1, 341 input tokens.

## 25 Sept 2026: Phase 1, baseline

- Checked for leaked keys: the two Jev test scripts are gone and were never committed. No key patterns in any commit.
- Fixed `.gitignore`: three rules had leading spaces and never matched, which is how `.pyc` files got committed. Untracked them.
- Tagged `v1.0.0` and branched `feature/jev-decision-layer`.
- Explored the real code. It differs a lot from the reference repo the brief was written against (four routes, no Streamlit, no ReAct agent, no chat history), so the requirements were adjusted to match.
- Wrote a 40-question eval set against three indexed ML course PDFs, including a solved question bank so answers can actually be grounded.
- Ran the v1 baseline. The final route was right for 38 of 40 questions. One question (`?`) crashed the router because the model answered in prose instead of JSON. Each LLM decision took a median of 3.8 to 4.6 seconds.
- Most interesting finding: on two injection questions the router was fine, but the answer check was fooled. It read "answer from the web only" as part of the question and rejected a correct answer from our documents.

## 25 Sept 2026: Phase 2, requirements

- Drafted `01-requirements.md` from the brief, adjusted to the real code, with a release rule decided before any Jev results exist.

## 25 Sept 2026: Phase 3, design

- Requirements approved.
- Checked the brief's API notes against the live Vercel and TypeSafe docs before designing. Three corrections: answers come back nested under `answers`, `cost` and `marketCost` are strings, and Noul questions accept optional `criteria` for the yes and no cases.
- Used Noul `criteria` to carry v1's grader rules into Jev word for word, including the "saying the context lacks it counts as grounded" rule that fixed v1's "I don't know" loop.
- Drafted `02-design.md`: a stack of small wrappers (logging, fallback, Jev, LLM) behind one interface, with the graph itself unchanged.

## 25 Sept 2026: Phase 4, steps 1 and 2

- Design approved. Added the settings and the Jev question wording (step 1).
- Step 2 moved the three decision nodes behind one interface, with the LLM provider calling the v1 functions unchanged. 18 offline tests pass, including both retry-cap loops.
- Live check: 5 eval questions in `llm` mode gave the same routes, the same step sequence, and the same grounded and retry values as the v1 baseline. The `?` crash still happens, as expected, since that v1 bug is out of scope.
