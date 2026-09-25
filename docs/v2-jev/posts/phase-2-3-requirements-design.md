# Phases 2 and 3: writing the rules down first

Two documents before any code: requirements and design.

The most important line in the requirements is the release rule. I decided, before seeing a single Jev result, that Jev only becomes the default if it routes at least as accurately as the LLM, does not get worse in any category, and completes every question. Writing it down first means I cannot bend it later to fit the results I want.

In design, I checked the API against the live docs instead of trusting my notes. Three corrections: answers are nested one level deeper than I thought, costs come back as strings, and yes/no questions accept "criteria" describing what counts as yes and what counts as no.

That last one mattered. My v1 grader has a rule I added after an infinite loop: saying "the context does not contain this" counts as grounded. With criteria I could carry that rule over to Jev word for word.

The design itself is a small stack: logging, then fallback, then Jev or the LLM, all behind one interface. The graph does not change.
