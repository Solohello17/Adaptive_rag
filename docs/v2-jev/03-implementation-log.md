# 03. Implementation log

One entry per step of Phase 4. Each step is one commit on `feature/jev-decision-layer`.

## Step 1: settings and question wording

**Commit:** `feat(config): add decision layer settings and Jev question wording`

**What:** Added the v2 settings to `app/config.py` and `.env.example` (`DECISION_PROVIDER` defaults to `llm`), wrote `app/decisions/jev_questions.yaml`, and declared `httpx`, `pyyaml`, `pymongo`, `pytest`, and `matplotlib` in `requirements.txt`. Only `pytest` and `matplotlib` were new installs; the other three were already present as dependencies of other packages.

**Why:** Settings and wording come first so every later step reads them instead of hard-coding values. The YAML mirrors the v1 prompts so the comparison is fair.

**Worth knowing:** YAML reads a bare `true:` key as the boolean `True`, not the string `"true"` that Jev's Noul `criteria` expects, so those keys are quoted.

**Files:** `app/config.py`, `.env.example`, `requirements.txt`, `app/decisions/jev_questions.yaml`

## Step 2: decision interface and LLM provider (pure refactor)

**Commit:** `feat(decisions): add decision interface and route nodes through it`

**What:**

- `app/decisions/base.py`: the result types (`RouteDecision`, `GradeDecision`, `VerifyDecision`, `DecisionMeta`), the `DecisionProvider` interface, `JevDecisionError`, and small functions that turn decisions into summaries for graph state.
- `app/decisions/llm_provider.py`: `LLMDecisionProvider`, which calls the v1 functions (`route_question`, `grade_documents_batch`, `grade_hallucination`, `grade_answer`) and only adds timing and yes/no to boolean mapping.
- `app/decisions/factory.py`: `get_decision_provider()`, cached, plus `override_decision_provider()` for tests and the eval script. `jev` is rejected until step 7.
- `app/graph.py`: `route_question_node`, `grade_documents`, and `check_generation` now ask the provider. A new state key, `decisions`, collects one summary per decision. Edges, retry cap, similarity override, and `steps` text are unchanged.

**Why the verify call is shaped this way:** v1 ran the grounded check only with context, and skipped the answer check after a grounding failure. The LLM provider keeps both short-circuits, so `llm` mode makes the same LLM calls as v1, in the same order.

**Tests (18, all offline):**

| Test | Checks |
|---|---|
| T14 | Route, grade, and empty grade call the v1 functions with the same arguments |
| T15 | Verify runs both checks in v1 order; skips the answer check when not grounded; skips the grounded check without context |
| T21 | Documents path end to end with a fake provider |
| T22 | General knowledge path skips grounding |
| T23 | Web search path, and no relevant chunks falls back to web search |
| T24 | Both correction loops stop at the retry cap (CLAUDE.md rule 4) |
| extra | Factory selection and override; grade and verify summaries |

**Live check against the v1 baseline** (5 eval questions, `llm` mode, real LLM, 25 Sept 2026):

| Question | Route (v1 to v2) | Step names identical | Grounded | Retries |
|---|---|---|---|---|
| q01 documents | documents to documents | yes | True to True | 0 to 0 |
| q11 general | general_knowledge to general_knowledge | yes | None to None | 0 to 0 |
| q18 override case | documents to documents (router said general_knowledge, override fired in both) | yes | True to True | 0 to 0 |
| q21 web | web_search to web_search | yes | True to True | 0 to 0 |
| q32 `?` | crash to crash (`OutputParserException`, known issue K1, unchanged by design) | yes | n/a | n/a |

**Files:** `app/decisions/__init__.py`, `app/decisions/base.py`, `app/decisions/llm_provider.py`, `app/decisions/factory.py`, `app/graph.py`, `pytest.ini`, `tests/unit/test_llm_provider.py`, `tests/unit/test_graph_paths.py`, `tests/unit/test_factory_and_summaries.py`
