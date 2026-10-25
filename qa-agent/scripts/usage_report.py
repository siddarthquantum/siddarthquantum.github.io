"""Model calls and tokens per run (M7), and the speed-up between two runs.

    .venv\\Scripts\\python.exe scripts\\usage_report.py <run_id>
    .venv\\Scripts\\python.exe scripts\\usage_report.py <new_run_id> --compare <old_run_id>
    .venv\\Scripts\\python.exe scripts\\usage_report.py --session <adk-session-id>      (runs before run tagging)

The key number is execute-phase model calls per executed test step. Baseline before the 25 Oct
optimisation: 50 executor calls for about 17 steps (run apidemos-20261025-105313) = about 2.9; target about 1.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from report.usage import lines_for_run, lines_for_session, summarize  # noqa: E402

USAGE = ROOT / "runs" / "_usage"
BASELINE_CALLS_PER_STEP = 2.9  # measured 25 Oct, before server-side screenshots + screen in results


def executed_steps(run_id: str) -> int:
    """Steps actually executed (step log), else the approved steps of tests that have a result."""
    run = ROOT / "runs" / run_id
    results = json.loads((run / "results.json").read_text(encoding="utf-8")).get("tests", {}) \
        if (run / "results.json").exists() else {}
    if any("steps" in r for r in results.values()):
        return sum(len(r.get("steps", [])) for r in results.values())
    approved = json.loads((run / "approved_tests.json").read_text(encoding="utf-8")).get("tests", []) \
        if (run / "approved_tests.json").exists() else []
    return sum(len(t["steps"]) for t in approved if t["id"] in results)


def measure(run_id: str | None, session: str | None) -> dict:
    rows = lines_for_session(USAGE, session) if session else lines_for_run(USAGE, run_id)
    s = summarize(rows)
    steps = executed_steps(run_id) if run_id else 0
    exe = s["phases"].get("execute", {"calls": 0, "total": 0})
    s["label"] = " / ".join(x for x in (run_id, f"session {session[:8]}" if session else "") if x)
    s["steps"] = steps
    s["calls_per_step"] = round(exe["calls"] / steps, 2) if steps else None
    s["tokens_per_step"] = round(exe["total"] / steps) if steps else None
    return s


def show(s: dict):
    print(f"\n{s['label']}")
    if not s["calls"]:
        print("  no usage lines found (older run? try --session <adk session id>)")
        return
    print(f"  calls {s['calls']}, tokens {s['total']:,} ({s['prompt']:,} in / {s['output']:,} out), "
          f"agent time {s['seconds'] // 60} min {s['seconds'] % 60} s, models {', '.join(s['models'])}")
    for phase, v in s["phases"].items():
        print(f"  {phase:<11} {v['calls']:>4} calls {v['total']:>10,} tokens")
    if s["calls_per_step"] is not None:
        print(f"  execute: {s['steps']} steps -> {s['calls_per_step']} calls/step, {s['tokens_per_step']:,} tokens/step")


def main():
    ap = argparse.ArgumentParser(description="Usage (M7) per run, and speed-up between runs")
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--session", help="adk session id instead of a run id")
    ap.add_argument("--compare", help="older run id to compare against")
    ap.add_argument("--compare-session", help="older adk session id to compare against")
    a = ap.parse_args()
    if not a.run_id and not a.session:
        ap.error("give a run id or --session")
    new = measure(a.run_id, a.session)
    show(new)
    if a.compare or a.compare_session:
        old = measure(a.compare, a.compare_session)
        show(old)
        if old["calls_per_step"] and new["calls_per_step"]:
            cut = 1 - new["calls_per_step"] / old["calls_per_step"]
            tok = 1 - new["tokens_per_step"] / old["tokens_per_step"]
            print(f"\nSpeed-up: calls per step {old['calls_per_step']} -> {new['calls_per_step']} ({cut:.0%} fewer), "
                  f"tokens per step {tok:.0%} fewer")
    elif new["calls_per_step"]:
        cut = 1 - new["calls_per_step"] / BASELINE_CALLS_PER_STEP
        print(f"\nVs 25 Oct baseline ({BASELINE_CALLS_PER_STEP} calls/step): {new['calls_per_step']} calls/step "
              f"({cut:.0%} fewer)")


if __name__ == "__main__":
    main()
