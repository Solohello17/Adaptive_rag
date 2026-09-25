# Phase 6: shipping v2.0, with the LLM as the default

v2.0 is out. Jev is in, and it is opt-in.

That is not the ending I pictured at the start, but it is the one my own rule gives. Jev was faster when it answered and caught things the LLM missed, but it routed 37 of 40 correctly against 38, and the rule said "at least as accurate".

I could tune thresholds until Jev wins on these 40 questions. That would just mean fitting to the test. The honest next step is a new held-out question set, plus three fixes I now know I need: retry once on a 503, allow correct refusals in the answer check, and a stricter grading threshold.

What I have now is a system where one setting switches who makes the decisions, every decision is logged with who made it, how long it took, and what it cost, and any single failure falls back cleanly. That was the real goal.

Thanks to Dhruv Singhal for the original architecture, and to TypeSafe AI for early access to Jev through Vercel.
