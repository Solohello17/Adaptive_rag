# Phase 5: the results

40 questions, three runs: v1, v2 with the LLM, v2 with Jev.

First, a bug in my own measurement. My timings accidentally included the extra LLM calls I use to check agreement, which made Jev's grading look about 7 times slower than it really was. Caught it in the smoke test and fixed it before the real runs.

Results:

- The refactored LLM mode matched v1 in every category. Good, nothing broke.
- Jev routed 37 of 40 correctly. The LLM got 38.
- When Jev answered, it was fast: 0.64 s median per route decision against 2.04 s, and 0.62 s per verify against 3.93 s. Median time per question went from 10.48 s to 6.92 s.
- 28 of 181 decisions went back to the LLM. 23 of those were 503s from the early-access service. The fallback caught every one.

What surprised me:

- Jev grades leniently (it kept 73% of chunks against 39%) but checks grounding more strictly. In one case it was probably right: a web answer claimed a race on a future date.
- A prompt injection nudged Jev toward web search, but only at 0.37 confidence, so the fallback kicked in and the LLM routed correctly.
- Jev scored correct refusals ("I cannot reveal API keys") as not answering the question. That is a wording fix on my side.
