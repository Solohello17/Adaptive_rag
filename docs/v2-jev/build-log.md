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

## 25 Sept 2026: Phase 4, steps 3 to 7

- First real calls to Jev through our own client. The gateway lists one model, `jev`, with no versioned id, so it is unpinned. The systemone endpoint accepts JSON-object state.
- Built Jev route, grade, and verify, then the per-decision fallback. `DECISION_PROVIDER=jev` now works end to end.
- Sanity checks worked: gibberish came back `unclear`; the "context does not say" answer scored 0.97 grounded, so v1's "I don't know" loop fix survived the move to Jev.
- On 5 eval questions the Jev run took the same route and path as v1, with each decision well under a second. The `?` question still crashes: Jev said `unclear` correctly, but the LLM it fell back to has the known v1 JSON bug.
- Jev's grading is lenient (8 of 8 chunks kept where the LLM kept 7 and 4). Noted for threshold tuning in Phase 5.

## 25 Sept 2026: Phase 4, steps 8 to 10 and the gate

- Every decision now lands in MongoDB with its provider, latency, tokens, cost, and fallback reason, tied together by a per-query id. A test proved the id survives LangGraph's node execution, which I would otherwise have had to assume.
- `/query` returns a `decisions` list next to the unchanged v1 fields, and the UI trace shows who made each call and when Jev handed one back to the LLM.
- Gate passed: 66 tests in both modes, and a real end-to-end query answered correctly in both, with 10 decision logs each.

## 25 Sept 2026: Phase 5, evaluation

- Rewrote the eval script for v2 and caught my own measurement bug in the smoke test: the node-level timings included the shadow LLM call, which would have made Jev's grading look 7 times slower than it was. Timings now come from the provider call itself.
- Ran all 40 questions with v2 in `llm` mode (the regression check) and in `jev` mode with shadow LLM checks.
- Regression check passed: `llm` mode matched the v1 baseline in every category.
- Jev routed 37 of 40 correctly against 38 for the LLM, and was 3 to 6 times faster per route and verify decision. By the rule set before the results, v2.0 ships with the LLM as default and Jev as opt-in.
- Most useful findings: 23 fallbacks were 503s from the early-access service, all absorbed; Jev grades leniently (keeps 73% of chunks against 39%) but judges grounding more strictly; and it scores correct refusals as "does not answer". The confidence threshold also stopped a prompt injection from steering the route.

## 25 Sept 2026: Phase 6, release

- Shipped v2.0.0 with `DECISION_PROVIDER=llm` as the default and Jev as opt-in, as the release rule decided.
- Wrote the CHANGELOG, a "What's new in v2.0" section in the README (and fixed its stale Streamlit instructions), the release notes, and one post draft per phase.
- Future work is listed in `05-release-notes.md`, led by a held-out question set for tuning, since tuning on the same 40 questions would overfit.
