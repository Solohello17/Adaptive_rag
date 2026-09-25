"""
Compares the v1 baseline with the v2 llm and jev runs and writes
results/eval/comparison.md plus PNG charts in results/eval/charts/.

    python scripts/compare_results.py
    python scripts/compare_results.py --baseline results/eval/v1_baseline.json --llm results/eval/v2_llm.json --jev results/eval/v2_jev.json

Every number in the report is computed from those files. Nothing is typed in.

Accuracy is counted over all 40 questions (a crash counts as wrong), and the
percentage over completed questions is shown alongside, matching the baseline
summary. Latency is the wall time of each decision call: v1 timed the v1
functions directly (its two verify checks are summed per verification), and
v2 records `decision_wall_ms`, which excludes --shadow-llm time.
"""
import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ["in_docs", "general", "needs_web", "off_topic", "injection"]
DECISIONS = ["route", "grade", "verify"]

# Fixed entity colours (reference palette slots 1-3, validated light-mode
# all-pairs). Aqua is below 3:1 on the surface, so every bar is value-labelled.
RUNS = [("v1", "v1 baseline", "#2a78d6"), ("llm", "v2 llm", "#eb6834"), ("jev", "v2 jev", "#1baf7a")]
SURFACE, TEXT, TEXT_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0"


# ---------- loading ----------

def baseline_latencies(result):
    """v1 recorded verify_grounded and verify_answer separately; sum each verification."""
    out = defaultdict(list)
    records = [d for d in result["decisions"] if "error" not in d]
    i = 0
    while i < len(records):
        d = records[i]
        if d["decision"] == "verify_grounded":
            total = d["latency_ms"]
            if i + 1 < len(records) and records[i + 1]["decision"] == "verify_answer":
                total += records[i + 1]["latency_ms"]
                i += 1
            out["verify"].append(total)
        elif d["decision"] == "verify_answer":
            out["verify"].append(d["latency_ms"])
        else:
            out[d["decision"]].append(d["latency_ms"])
        i += 1
    return out


def v2_latencies(result):
    out = defaultdict(list)
    for d in result.get("decision_wall_ms", []):
        out[d["decision"]].append(d["wall_ms"])
    return out


def load(path, kind):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for r in data["results"]:
        r["latencies"] = baseline_latencies(r) if kind == "v1" else v2_latencies(r)
    return data


# ---------- metrics ----------

def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "n/a"


def median(values):
    return statistics.median(values) if values else None


def p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, round(0.95 * len(ordered)) - 1)]


def fmt_s(ms):
    return "n/a" if ms is None else f"{ms / 1000:.2f} s"


def accuracy(results):
    completed = [r for r in results if r["error"] is None]
    count = lambda key, rows: sum(1 for r in rows if r[key])
    per_cat = {c: (count("final_correct", [r for r in results if r["category"] == c]), sum(1 for r in results if r["category"] == c)) for c in CATEGORIES}
    return {
        "n": len(results),
        "completed": len(completed),
        "final": count("final_correct", results),
        "router": count("router_correct", results),
        "acceptable": count("final_acceptable", results),
        "per_category": per_cat,
    }


def latency(results):
    pooled = defaultdict(list)
    for r in results:
        for name, values in r["latencies"].items():
            pooled[name].extend(values)
    totals = [r["total_seconds"] * 1000 for r in results if r["error"] is None]
    return {name: {"calls": len(pooled[name]), "median": median(pooled[name]), "p95": p95(pooled[name])} for name in DECISIONS} | {
        "total": {"calls": len(totals), "median": median(totals), "p95": p95(totals)}
    }


def jev_usage(results):
    records = [rec for r in results for rec in r.get("decision_records", [])]
    jev = [rec for rec in records if rec["provider"] == "jev"]
    fell_back = [rec for rec in records if rec["fallback_reason"]]
    attempted = len(jev) + len(fell_back)
    by_type = {name: (sum(1 for rec in fell_back if rec["decision"] == name), sum(1 for rec in jev + fell_back if rec["decision"] == name)) for name in DECISIONS}
    return {
        "jev_calls": len(jev),
        "attempted": attempted,
        "fallbacks": len(fell_back),
        "fallback_reasons": Counter(rec["fallback_reason"] for rec in fell_back),
        "fallback_by_type": by_type,
        "input_tokens": sum(rec["input_tokens"] or 0 for rec in jev),
        "cost": sum(rec["cost_usd"] or 0 for rec in jev),
        "market_cost": sum(rec["market_cost_usd"] or 0 for rec in jev),
        "route_confidences": [rec["confidence"] for rec in jev if rec["decision"] == "route" and rec["confidence"] is not None],
    }


def shadow(results):
    rows = [s for r in results for s in r.get("shadow", []) if "error" not in s]
    grade = [(s["jev"], s["llm"]) for s in rows if s["decision"] == "grade"]
    grounded = [(s["jev_grounded"], s["llm_grounded"]) for s in rows if s["decision"] == "verify" and s["jev_grounded"] is not None and s["llm_grounded"] is not None]
    answers = [(s["jev_answers"], s["llm_answers"]) for s in rows if s["decision"] == "verify" and s["jev_answers"] is not None and s["llm_answers"] is not None]

    def table(pairs):
        c = Counter(pairs)
        return {"n": len(pairs), "agree": c[(True, True)] + c[(False, False)], "jev_yes_llm_no": c[(True, False)], "jev_no_llm_yes": c[(False, True)], "both_yes": c[(True, True)], "both_no": c[(False, False)]}

    return {"grade": table(grade), "grounded": table(grounded), "answers": table(answers), "errors": sum(1 for r in results for s in r.get("shadow", []) if "error" in s)}


def downstream(results):
    ok = [r for r in results if r["error"] is None]
    docs = [r for r in ok if r["documents_found"]]
    return {
        "grounded_true": sum(1 for r in ok if r["grounded"] is True),
        "grounded_false": sum(1 for r in ok if r["grounded"] is False),
        "retry_cap": sum(1 for r in ok if r["retry_count"] == 2),
        "kept": sum(r["documents_kept"] or 0 for r in docs),
        "found": sum(r["documents_found"] or 0 for r in docs),
        "overrides": sum(1 for r in ok if r["override"]),
    }


# ---------- charts ----------

def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_2, labelsize=9, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def grouped_bars(path, groups, series, ylabel, title, value_fmt, ymax=None):
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=200, facecolor=SURFACE)
    style(ax)
    width = 0.8 / len(series)
    for i, (label, colour, values) in enumerate(series):
        xs = [g + (i - (len(series) - 1) / 2) * width for g in range(len(groups))]
        bars = ax.bar(xs, [v if v is not None else 0 for v in values], width=width, color=colour, label=label,
                      edgecolor=SURFACE, linewidth=2)  # 2px surface gap between adjacent bars
        for bar, v in zip(bars, values):
            if v is not None:
                ax.annotate(value_fmt(v), (bar.get_x() + bar.get_width() / 2, bar.get_height()), xytext=(0, 2),
                            textcoords="offset points", ha="center", va="bottom", fontsize=7, color=TEXT)
    ax.set_xticks(range(len(groups)), groups)
    ax.set_ylabel(ylabel, color=TEXT_2, fontsize=9)
    if ymax:
        ax.set_ylim(0, ymax)
    ax.set_title(title, color=TEXT, fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=8, labelcolor=TEXT, ncol=len(series), loc="upper left", bbox_to_anchor=(0, -0.1))
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def hbar(path, labels, values, colour, title, xlabel):
    fig, ax = plt.subplots(figsize=(7, 0.5 + 0.45 * len(labels)), dpi=200, facecolor=SURFACE)
    style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    bars = ax.barh(labels, values, color=colour, edgecolor=SURFACE, linewidth=2, height=0.6)
    for bar, v in zip(bars, values):
        ax.annotate(str(v), (bar.get_width(), bar.get_y() + bar.get_height() / 2), xytext=(3, 0), textcoords="offset points", va="center", fontsize=8, color=TEXT)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel, color=TEXT_2, fontsize=9)
    ax.set_title(title, color=TEXT, fontsize=11, loc="left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


# ---------- report ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default=str(ROOT / "results/eval/v1_baseline.json"))
    parser.add_argument("--llm", default=str(ROOT / "results/eval/v2_llm.json"))
    parser.add_argument("--jev", default=str(ROOT / "results/eval/v2_jev.json"))
    parser.add_argument("--out", default=str(ROOT / "results/eval/comparison.md"))
    args = parser.parse_args()

    runs = {"v1": load(args.baseline, "v1"), "llm": load(args.llm, "v2"), "jev": load(args.jev, "v2")}
    res = {k: v["results"] for k, v in runs.items()}
    acc = {k: accuracy(v) for k, v in res.items()}
    lat = {k: latency(v) for k, v in res.items()}
    down = {k: downstream(v) for k, v in res.items()}
    usage = jev_usage(res["jev"])
    agree = shadow(res["jev"])

    charts = Path(args.out).parent / "charts"
    charts.mkdir(parents=True, exist_ok=True)

    # Chart 1: route accuracy per category.
    groups = CATEGORIES + ["overall"]
    series = []
    for key, label, colour in RUNS:
        values = [100 * n / total if total else None for n, total in (acc[key]["per_category"][c] for c in CATEGORIES)]
        values.append(100 * acc[key]["final"] / acc[key]["n"])
        series.append((label, colour, values))
    grouped_bars(charts / "route_accuracy_by_category.png", groups, series, "final route correct (%)",
                 "Route accuracy by category (all 40 questions; a crash counts as wrong)", lambda v: f"{v:.0f}%", ymax=112)

    # Chart 2: median latency per decision.
    series = [(label, colour, [None if lat[key][d]["median"] is None else lat[key][d]["median"] / 1000 for d in DECISIONS]) for key, label, colour in RUNS]
    grouped_bars(charts / "decision_latency_median.png", DECISIONS, series, "median seconds per decision",
                 "Median time per decision (wall time of the decision call)", lambda v: f"{v:.2f}s")

    # Chart 3: Jev fallback reasons (single series, so no legend).
    if usage["fallback_reasons"]:
        reasons = usage["fallback_reasons"].most_common()
        hbar(charts / "jev_fallback_reasons.png", [r.replace("_", " ") for r, _ in reasons], [n for _, n in reasons], RUNS[2][2],
             f"Why Jev handed decisions back to the LLM ({usage['fallbacks']} of {usage['attempted']} decisions)", "decisions")

    # ---------- markdown ----------
    L = []
    w = L.append
    meta = {k: v["meta"] for k, v in runs.items()}
    w("# Evaluation: v1 baseline vs v2 llm vs v2 jev\n")
    w("Generated by `scripts/compare_results.py` from the saved run files. Every number below is computed from them.\n")
    w("| Run | File | Git commit | Started (UTC) | LLM (fast / smart) | Notes |")
    w("|---|---|---|---|---|---|")
    for key, label, _ in RUNS:
        m = meta[key]
        notes = f"Jev model `{m.get('jev_model')}` (unpinned), shadow LLM: {m.get('shadow_llm')}" if key == "jev" else ""
        w(f"| {label} | `{Path(getattr(args, 'baseline' if key == 'v1' else key)).name}` | `{m.get('git_commit')}` | {m.get('started_at')} | {m.get('llm_provider_fast')} / {m.get('llm_provider')} (`{m.get('omniroute_model')}`) | {notes} |")
    w("\nThe OmniRoute alias picks a concrete model per request, so the LLM side is not deterministic between runs. Each configuration was run once.\n")

    w("## 1. Route accuracy\n")
    w("| | v1 baseline | v2 llm | v2 jev |")
    w("|---|---|---|---|")
    w("| Completed without crashing | " + " | ".join(f"{acc[k]['completed']}/{acc[k]['n']}" for k, _, _ in RUNS) + " |")
    w("| Final route correct (of 40) | " + " | ".join(f"{acc[k]['final']}/{acc[k]['n']} ({pct(acc[k]['final'], acc[k]['n'])})" for k, _, _ in RUNS) + " |")
    w("| Final route correct (of completed) | " + " | ".join(pct(acc[k]['final'], acc[k]['completed']) for k, _, _ in RUNS) + " |")
    w("| Router decision correct, before the similarity override | " + " | ".join(f"{acc[k]['router']}/{acc[k]['n']}" for k, _, _ in RUNS) + " |")
    w("| Final route in `acceptable_routes` | " + " | ".join(f"{acc[k]['acceptable']}/{acc[k]['n']}" for k, _, _ in RUNS) + " |")
    for c in CATEGORIES:
        w(f"| {c} | " + " | ".join(f"{acc[k]['per_category'][c][0]}/{acc[k]['per_category'][c][1]}" for k, _, _ in RUNS) + " |")
    w("\n![Route accuracy by category](charts/route_accuracy_by_category.png)\n")

    w("### Questions where the runs disagree or a run missed\n")
    w("| ID | Category | Expected | v1 final | v2 llm final | v2 jev router | v2 jev final | Jev fallbacks |")
    w("|---|---|---|---|---|---|---|---|")
    by_id = {k: {r["id"]: r for r in v} for k, v in res.items()}
    for q in res["v1"]:
        rows = {k: by_id[k].get(q["id"]) for k in by_id}
        finals = {k: (r["final_route"] if r and r["error"] is None else "crash") for k, r in rows.items()}
        if len(set(finals.values())) > 1 or any(f != q["expected_route"] for f in finals.values()):
            jr = rows["jev"]
            fb = ", ".join(f"{d}: {n}" for d, n in Counter(rec["decision"] + " " + rec["fallback_reason"] for rec in jr.get("decision_records", []) if rec["fallback_reason"]).items()) if jr else ""
            w(f"| {q['id']} | {q['category']} | {q['expected_route']} | {finals['v1']} | {finals['llm']} | {jr['router_route'] if jr else ''} | {finals['jev']} | {fb or 'none'} |")

    w("\n## 2. Regression check (NFR1): v2 llm vs v1 baseline\n")
    w("Rule: in `llm` mode, no category may lose more than one correct route compared with the v1 baseline.\n")
    w("| Category | v1 baseline | v2 llm | Change | Result |")
    w("|---|---|---|---|---|")
    nfr1_ok = True
    for c in CATEGORIES:
        b, l = acc["v1"]["per_category"][c][0], acc["llm"]["per_category"][c][0]
        ok = l >= b - 1
        nfr1_ok &= ok
        w(f"| {c} | {b} | {l} | {l - b:+d} | {'PASS' if ok else 'FAIL'} |")
    w(f"\n**NFR1: {'PASS' if nfr1_ok else 'FAIL'}**\n")

    w("## 3. Release rule (requirements section 9): v2 jev vs v2 llm\n")
    r1 = acc["jev"]["final"] >= acc["llm"]["final"]
    cat_losses = {c: acc["jev"]["per_category"][c][0] - acc["llm"]["per_category"][c][0] for c in CATEGORIES}
    r2 = all(v >= -1 for v in cat_losses.values())
    r3 = acc["jev"]["completed"] == acc["jev"]["n"]
    w("| Condition | Result | Detail |")
    w("|---|---|---|")
    w(f"| 1. Final route accuracy matches or beats llm | {'PASS' if r1 else 'FAIL'} | jev {acc['jev']['final']}/40 vs llm {acc['llm']['final']}/40 |")
    w(f"| 2. No category loses more than one correct route | {'PASS' if r2 else 'FAIL'} | " + ", ".join(f"{c} {v:+d}" for c, v in cat_losses.items()) + " |")
    crashed = [r["id"] for r in res["jev"] if r["error"]]
    llm_crashed = [r["id"] for r in res["llm"] if r["error"]]
    w(f"| 3. Completes every question | {'PASS' if r3 else 'FAIL'} | jev crashed on: {', '.join(crashed) or 'none'}; llm crashed on: {', '.join(llm_crashed) or 'none'} |")
    w("")

    w("## 4. Latency\n")
    w("Wall time of each decision call. Grade is one batched LLM call in v1 and v2 llm, and up to "
      f"{meta['jev'].get('jev_max_concurrency')} concurrent Jev calls in v2 jev.\n")
    w("| Decision | v1 baseline median / p95 (calls) | v2 llm median / p95 (calls) | v2 jev median / p95 (calls) |")
    w("|---|---|---|---|")
    for d in DECISIONS + ["total"]:
        label = "total per question" if d == "total" else d
        w(f"| {label} | " + " | ".join(f"{fmt_s(lat[k][d]['median'])} / {fmt_s(lat[k][d]['p95'])} ({lat[k][d]['calls']})" for k, _, _ in RUNS) + " |")
    w("\nTotal per question includes generation, retrieval, and web search, which are the same LLM and tools in every run. For v2 jev it excludes the shadow LLM calls.\n")
    w("![Median time per decision](charts/decision_latency_median.png)\n")

    w("## 5. Jev usage, cost, and fallbacks (v2 jev run)\n")
    confs = usage["route_confidences"]
    w("| Metric | Value |")
    w("|---|---|")
    w(f"| Decisions Jev made itself | {usage['jev_calls']} |")
    w(f"| Decisions handed back to the LLM | {usage['fallbacks']} of {usage['attempted']} attempted ({pct(usage['fallbacks'], usage['attempted'])}) |")
    for d in DECISIONS:
        fb, total = usage["fallback_by_type"][d]
        w(f"| Fallback rate, {d} | {fb}/{total} ({pct(fb, total)}) |")
    w(f"| HTTP 429 (rate limited) | {usage['fallback_reasons'].get('rate_limited', 0)} |")
    w(f"| Jev input tokens | {usage['input_tokens']} |")
    w(f"| Jev cost charged | {usage['cost']:.8f} USD |")
    w(f"| Jev market cost (what it would cost without free credit) | {usage['market_cost']:.8f} USD, {usage['market_cost'] / len(res['jev']):.8f} USD per question |")
    if confs:
        w(f"| Route confidence when Jev routed: median / min | {median(confs):.2f} / {min(confs):.2f} |")
    w("\n| Fallback reason | Decisions |")
    w("|---|---|")
    for reason, n in usage["fallback_reasons"].most_common() or [("none", 0)]:
        w(f"| {reason} | {n} |")
    if usage["fallback_reasons"]:
        w("\n![Jev fallback reasons](charts/jev_fallback_reasons.png)\n")
    w("\nLLM token usage is not available: OmniRoute does not report it through this code path.\n")

    w("## 6. Agreement with the LLM on the same inputs (shadow checks)\n")
    w("For every grade and verify decision Jev made itself, the LLM was asked the same question on the same input. The shadow answer never changed the graph's path.\n")
    w("| Check | Pairs | Agree | Jev yes, LLM no | Jev no, LLM yes |")
    w("|---|---|---|---|---|")
    for name, label in (("grade", "Grade: chunk relevant"), ("grounded", "Verify: grounded"), ("answers", "Verify: answers the question")):
        t = agree[name]
        w(f"| {label} | {t['n']} | {t['agree']} ({pct(t['agree'], t['n'])}) | {t['jev_yes_llm_no']} | {t['jev_no_llm_yes']} |")
    w(f"\nShadow calls that errored: {agree['errors']}. Verify pairs only count checks both sides ran: the LLM skips the answer check once it judges an answer not grounded.\n")

    w("## 7. Downstream effects\n")
    w("| | v1 baseline | v2 llm | v2 jev |")
    w("|---|---|---|---|")
    w("| Chunks kept / retrieved (questions that retrieved) | " + " | ".join(f"{down[k]['kept']}/{down[k]['found']} ({pct(down[k]['kept'], down[k]['found'])})" for k, _, _ in RUNS) + " |")
    w("| Answers judged grounded / not grounded | " + " | ".join(f"{down[k]['grounded_true']} / {down[k]['grounded_false']}" for k, _, _ in RUNS) + " |")
    w("| Questions that hit the retry cap | " + " | ".join(str(down[k]["retry_cap"]) for k, _, _ in RUNS) + " |")
    w("| Similarity overrides | " + " | ".join(str(down[k]["overrides"]) for k, _, _ in RUNS) + " |")

    Path(args.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} and charts in {charts}")


if __name__ == "__main__":
    main()
