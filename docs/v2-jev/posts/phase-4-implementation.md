# Phase 4: building the decision layer

Ten small commits. The one I cared most about was step 2: moving the graph's decisions behind the new interface without changing behaviour at all. Tests record every call the LLM provider makes to the old functions, and 5 real questions gave the same routes and the same step-by-step path as v1.

Then Jev, one decision at a time:

- Route: one choice question with an extra "unclear" option. Gibberish came back unclear, which is exactly what it is for.
- Grade: one yes/no question per chunk, three at a time.
- Verify: two yes/no questions in one request. The answer "the context does not say who founded SpaceX" scored 0.97 grounded, so my v1 loop fix survived.

Then fallback: if Jev fails or is unsure about one decision, only that decision goes to the LLM. For grading, only the chunks that failed.

Then logs in MongoDB, the API field, and the UI. One thing I did not want to assume: that a per-request id stored in a Python contextvar survives LangGraph running my nodes. I wrote a test. It does.

66 offline tests, passing in both modes.
