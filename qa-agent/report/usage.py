"""Requests and tokens per run from runs/_usage/<session>.jsonl (M7), shared by the report and
scripts/usage_report.py.

Lines are tagged with run_id once a run exists. Exploration happens before the run id is created, so
untagged lines in a session are given to the next run tagged in that same session.
"""
import json
from datetime import datetime
from pathlib import Path

PHASE = {"explorer": "design", "test_designer": "design", "executor_agent": "execute",
         "qa_coordinator": "coordinate"}


def read_lines(usage_dir: Path) -> dict[str, list[dict]]:
    sessions = {}
    for f in sorted(usage_dir.glob("*.jsonl")):
        rows = []
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        sessions[f.stem] = rows
    return sessions


def lines_for_run(usage_dir: Path, run_id: str) -> list[dict]:
    picked = []
    for rows in read_lines(usage_dir).values():
        pending = []  # untagged lines since the last tagged one (exploration before the run existed)
        for r in rows:
            tag = r.get("run_id", "")
            if not tag:
                pending.append(r)
            elif tag == run_id:
                picked += pending + [r]
                pending = []
            else:
                pending = []
    return picked


def lines_for_session(usage_dir: Path, session_id: str) -> list[dict]:
    return read_lines(usage_dir).get(session_id, [])


def summarize(rows: list[dict]) -> dict:
    out = {"calls": len(rows), "prompt": 0, "output": 0, "total": 0, "models": [], "phases": {},
           "seconds": 0}
    for r in rows:
        for k in ("prompt", "output", "total"):
            out[k] += r.get(k, 0)
        if r.get("model") and r["model"] not in out["models"]:
            out["models"].append(r["model"])
        p = out["phases"].setdefault(PHASE.get(r.get("agent"), r.get("agent", "?")), {"calls": 0, "total": 0})
        p["calls"] += 1
        p["total"] += r.get("total", 0)
    if len(rows) >= 2:
        t0, t1 = (datetime.fromisoformat(rows[i]["ts"]) for i in (0, -1))
        out["seconds"] = int((t1 - t0).total_seconds())
    return out
