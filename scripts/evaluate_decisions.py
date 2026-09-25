"""
Runs the eval question set through the full graph with one decision provider
and saves per-question results plus a summary to results/eval/.

    python scripts/evaluate_decisions.py --provider llm
    python scripts/evaluate_decisions.py --provider jev --shadow-llm

--provider picks the decision layer through the real factory, so the run uses
the same stack as the app (including decision logs in MongoDB, tagged with
request_id "eval-<run>-<question id>").

--shadow-llm (eval only): after every grade and verify decision that Jev made
itself, also ask the LLM the same question on the same input and record whether
they agree. The shadow answer never changes the graph's path, and its time is
subtracted from the question's total so Jev's timings are not inflated.

The v1 baseline (results/eval/v1_baseline.json) was produced by the v1 version
of this script, which timed the v1 functions directly; compare_results.py reads
both formats.

The output file is rewritten after every question, so an interrupted run can be
continued with --resume instead of paying for the finished questions again.
"""
import argparse
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import app.decisions.factory as factory
from app.config import settings
from app.decisions.decision_log import request_id_var
from app.decisions.llm_provider import LLMDecisionProvider
from app.graph import rag_app


def _meta_record(decision, meta, **extra):
    return {
        "decision": decision,
        "provider": meta.provider,
        "latency_ms": meta.latency_ms,
        "model": meta.model,
        "confidence": meta.confidence,
        "input_tokens": meta.input_tokens,
        "output_tokens": meta.output_tokens,
        "cost_usd": meta.cost_usd,
        "market_cost_usd": meta.market_cost_usd,
        "fallback_reason": meta.fallback_reason,
        "jev_attempt": meta.jev_attempt,
        **extra,
    }


class EvalProvider:
    """Eval-only wrapper: records every decision's metadata, and optionally shadow-checks Jev against the LLM."""

    def __init__(self, inner, shadow_llm=None):
        self.inner = inner
        self.name = inner.name
        self.shadow_llm = shadow_llm
        self.reset()

    def reset(self):
        self.records, self.shadow, self.walls, self.shadow_seconds = [], [], [], 0.0

    def _timed(self, name, call):
        # Wall time of the real provider call only. The node's own timing (the
        # `decisions[].latency_ms` summaries) would include the shadow LLM call below.
        start = time.perf_counter()
        result = call()
        self.walls.append({"decision": name, "wall_ms": round((time.perf_counter() - start) * 1000, 1)})
        return result

    def route(self, question):
        decision = self._timed("route", lambda: self.inner.route(question))
        self.records.append(_meta_record("route", decision.meta, result=decision.route))
        return decision

    def grade(self, question, passages):
        decisions = self._timed("grade", lambda: self.inner.grade(question, passages))
        for d in decisions:
            self.records.append(_meta_record("grade", d.meta, result=d.relevant, score=d.score))

        jev_made = [i for i, d in enumerate(decisions) if d.meta.provider == "jev"]
        if self.shadow_llm and jev_made:
            start = time.perf_counter()
            try:
                llm_grades = self.shadow_llm.grade(question, [passages[i] for i in jev_made])
                for i, g in zip(jev_made, llm_grades):
                    self.shadow.append({"decision": "grade", "jev": decisions[i].relevant, "jev_score": decisions[i].score, "llm": g.relevant})
            except Exception as e:
                self.shadow.append({"decision": "grade", "error": repr(e)})
            self.shadow_seconds += time.perf_counter() - start
        return decisions

    def verify(self, question, context, answer):
        decision = self._timed("verify", lambda: self.inner.verify(question, context, answer))
        self.records.append(_meta_record(
            "verify", decision.meta,
            result={"grounded": decision.grounded, "answers_question": decision.answers_question},
            score={"grounded": decision.grounded_score, "answers_question": decision.answers_score},
        ))

        if self.shadow_llm and decision.meta.provider == "jev":
            start = time.perf_counter()
            try:
                llm = self.shadow_llm.verify(question, context, answer)
                self.shadow.append({
                    "decision": "verify",
                    "jev_grounded": decision.grounded, "llm_grounded": llm.grounded,
                    # The LLM skips the answer check when not grounded, so it can be None.
                    "jev_answers": decision.answers_question, "llm_answers": llm.answers_question,
                    "jev_scores": {"grounded": decision.grounded_score, "answers_question": decision.answers_score},
                })
            except Exception as e:
                self.shadow.append({"decision": "verify", "error": repr(e)})
            self.shadow_seconds += time.perf_counter() - start
        return decision


def run_question(q, provider, run_id):
    provider.reset()
    token = request_id_var.set(f"eval-{run_id}-{q['id']}")
    start = time.perf_counter()
    error, result = None, {}
    try:
        result = rag_app.invoke({"question": q["question"]})
    except Exception as e:
        error = repr(e)
    finally:
        request_id_var.reset(token)
    wall = time.perf_counter() - start

    decisions = result.get("decisions", [])
    router_route = next((d["result"] for d in decisions if d["decision"] == "route"), None)
    if router_route is None:
        # A crash before the node returned: fall back to what the provider recorded.
        router_route = next((r["result"] for r in provider.records if r["decision"] == "route"), None)
    final_route = result.get("route")
    acceptable = q.get("acceptable_routes") or [q["expected_route"]]
    steps = result.get("steps", [])

    return {
        "id": q["id"],
        "question": q["question"],
        "category": q["category"],
        "expected_route": q["expected_route"],
        "acceptable_routes": acceptable,
        "router_route": router_route,
        "final_route": final_route,
        "override": any(s["name"] == "route override" for s in steps),
        "router_correct": router_route == q["expected_route"],
        "final_correct": final_route == q["expected_route"],
        "final_acceptable": final_route in acceptable,
        "documents_found": result.get("documents_found"),
        "documents_kept": result.get("documents_kept"),
        "grounded": result.get("grounded"),
        "retry_count": result.get("retry_count"),
        "answer": result.get("generation"),
        "steps": steps,
        "decisions": decisions,
        "decision_records": list(provider.records),
        # Use these for latency, not decisions[].latency_ms (which includes shadow time).
        "decision_wall_ms": list(provider.walls),
        "shadow": list(provider.shadow),
        "shadow_seconds": round(provider.shadow_seconds, 2),
        "total_seconds": round(wall - provider.shadow_seconds, 2),
        "error": error,
    }


def rate(rows, key):
    return round(sum(1 for r in rows if r[key]) / len(rows), 3) if rows else None


def summarize(results):
    ok = [r for r in results if r["error"] is None]
    by_category = defaultdict(list)
    for r in ok:
        by_category[r["category"]].append(r)

    records = [rec for r in results for rec in r["decision_records"]]
    fallbacks = Counter(rec["fallback_reason"] for rec in records if rec["fallback_reason"])
    jev = [rec for rec in records if rec["provider"] == "jev"]
    shadow = [s for r in results for s in r["shadow"] if "error" not in s]

    def agree(pairs):
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        return {"n": len(pairs), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None}

    return {
        "questions": len(results),
        "completed": len(ok),
        "errors": len(results) - len(ok),
        "router_accuracy": rate(ok, "router_correct"),
        "final_route_accuracy": rate(ok, "final_correct"),
        "final_route_acceptable": rate(ok, "final_acceptable"),
        "per_category": {c: {"n": len(rows), "final_route_accuracy": rate(rows, "final_correct")} for c, rows in sorted(by_category.items())},
        "decisions_recorded": Counter(rec["decision"] for rec in records),
        "by_provider": Counter(rec["provider"] for rec in records),
        "fallbacks": dict(fallbacks),
        "rate_limited_429": fallbacks.get("rate_limited", 0),
        "jev_calls": len(jev),
        "jev_input_tokens": sum(rec["input_tokens"] or 0 for rec in jev),
        "jev_cost_usd": round(sum(rec["cost_usd"] or 0 for rec in jev), 8),
        "jev_market_cost_usd": round(sum(rec["market_cost_usd"] or 0 for rec in jev), 8),
        "shadow": {
            "grade": agree((s["jev"], s["llm"]) for s in shadow if s["decision"] == "grade"),
            "verify_grounded": agree((s["jev_grounded"], s["llm_grounded"]) for s in shadow if s["decision"] == "verify"),
            "verify_answers": agree((s["jev_answers"], s["llm_answers"]) for s in shadow if s["decision"] == "verify"),
            "errors": sum(1 for r in results for s in r["shadow"] if "error" in s),
        },
    }


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["llm", "jev"], required=True)
    parser.add_argument("--shadow-llm", action="store_true", help="jev only: also ask the LLM each Jev grade/verify question and record agreement")
    parser.add_argument("--questions", default=str(ROOT / "tests" / "eval" / "questions.jsonl"))
    parser.add_argument("--out", default=None)
    parser.add_argument("--delay", type=float, default=3.0, help="seconds to wait between questions (rate limits)")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N questions")
    parser.add_argument("--resume", action="store_true", help="skip questions already completed without error in --out")
    args = parser.parse_args()

    if args.shadow_llm and args.provider != "jev":
        parser.error("--shadow-llm only makes sense with --provider jev")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else ROOT / "results" / "eval" / f"{args.provider}_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    # Build the provider exactly as the app would for this setting.
    settings.DECISION_PROVIDER = args.provider
    factory._build_from_settings.cache_clear()
    provider = EvalProvider(factory.get_decision_provider(), shadow_llm=LLMDecisionProvider() if args.shadow_llm else None)
    factory.override_decision_provider(provider)

    questions = [json.loads(line) for line in open(args.questions, encoding="utf-8") if line.strip()]
    if args.limit:
        questions = questions[: args.limit]

    done, run_id = {}, f"{args.provider}-{stamp}"
    if args.resume and out.exists():
        previous = json.loads(out.read_text(encoding="utf-8"))
        run_id = previous["meta"]["run_id"]
        done = {r["id"]: r for r in previous["results"] if r["error"] is None}

    # Non-secret settings only. OMNIROUTE_MODEL may be a routing alias, in which
    # case the concrete model per request is chosen by OmniRoute and not known here.
    meta = {
        "run_id": run_id,
        "provider": args.provider,
        "shadow_llm": args.shadow_llm,
        "started_at": stamp,
        "git_commit": git_commit(),
        "app_version": settings.APP_VERSION,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_provider_fast": settings.LLM_PROVIDER_FAST,
        "omniroute_model": settings.OMNIROUTE_MODEL if "omniroute" in (settings.LLM_PROVIDER, settings.LLM_PROVIDER_FAST) else None,
        "embeddings_provider": settings.EMBEDDINGS_PROVIDER,
        "router_override_threshold": settings.ROUTER_OVERRIDE_THRESHOLD,
        "retrieval_docs_per_query": settings.RETRIEVAL_DOCS_PER_QUERY,
        "retrieval_chunks_per_doc": settings.RETRIEVAL_CHUNKS_PER_DOC,
        "jev_model": settings.JEV_MODEL if args.provider == "jev" else None,
        "jev_route_min_confidence": settings.JEV_ROUTE_MIN_CONFIDENCE,
        "jev_grade_threshold": settings.JEV_GRADE_THRESHOLD,
        "jev_verify_threshold": settings.JEV_VERIFY_THRESHOLD,
        "jev_max_concurrency": settings.JEV_MAX_CONCURRENCY,
        "delay_seconds": args.delay,
    }

    def save(results):
        out.write_text(json.dumps({"meta": meta, "summary": summarize(results), "results": results}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    results = []
    try:
        for i, q in enumerate(questions, 1):
            if q["id"] in done:
                results.append(done[q["id"]])
                continue
            r = run_question(q, provider, run_id)
            results.append(r)
            mark = "ok " if r["final_correct"] else ("acc" if r["final_acceptable"] else "XX ")
            fb = [rec["fallback_reason"] for rec in r["decision_records"] if rec["fallback_reason"]]
            print(f"[{i}/{len(questions)}] {mark} {q['id']} expected={q['expected_route']} router={r['router_route']} final={r['final_route']} "
                  f"{r['total_seconds']}s" + (f" fallbacks={dict(Counter(fb))}" if fb else "") + (f" ERROR {r['error'][:120]}" if r["error"] else ""), flush=True)
            save(results)
            if i < len(questions):
                time.sleep(args.delay)
    finally:
        factory.override_decision_provider(None)

    save(results)
    print(f"\nSaved {out}")
    print(json.dumps(summarize(results), indent=2))


if __name__ == "__main__":
    main()
