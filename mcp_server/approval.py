"""Approval gate (R2, DD-05): the hash is recorded when the HUMAN approves, and checked by the server.

runs/<run_id>/approved_tests.json  - the approved test cases: {"tests": [{"id": "TC01", ...}, ...]}
                                     optional per test: "fresh_start": false = continue from the previous
                                     test's state (default true = restart app + clear data)
runs/<run_id>/approval.json        - written by scripts/approve.py: {"run_id", "sha256", "approved_at",
                                     "planted_defects"}
Any edit to approved_tests.json after approval changes its SHA-256, so the server refuses to execute it.
"""
import hashlib
import json
import re
from pathlib import Path

RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # no slashes or dots: run_id cannot escape runs/


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_approved(runs_dir: Path, run_id: str):
    """Returns (list_of_test_dicts, None) if the approval is valid, else (None, (code, message))."""
    if not RUN_ID.fullmatch(run_id or ""):
        return None, ("BAD_ARGUMENT", "run_id may contain only letters, digits, _ and -.")
    run_dir = runs_dir / run_id
    tests_file, approval_file = run_dir / "approved_tests.json", run_dir / "approval.json"
    if not tests_file.exists() or not approval_file.exists():
        return None, ("NOT_APPROVED", f"No approved_tests.json + approval.json in runs/{run_id}. "
                                      "A human must run scripts/approve.py first.")
    try:
        approval = json.loads(approval_file.read_text(encoding="utf-8"))
        tests = json.loads(tests_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, ("APPROVAL_INVALID", f"Cannot read approval files: {type(e).__name__}")
    if approval.get("sha256") != sha256_file(tests_file):
        return None, ("APPROVAL_INVALID", "approved_tests.json changed after approval (SHA-256 mismatch).")
    items = tests.get("tests", []) if isinstance(tests, dict) else tests
    items = [t for t in items if isinstance(t, dict) and t.get("id")]
    if not items:
        return None, ("APPROVAL_INVALID", "approved_tests.json has no test cases with an id.")
    return items, None


def select_tests(tests: list, select: str, previous: dict):
    """Pick which approved tests to run, in approved order.

    select: "all", "failed" (not "pass" in the previous results), or "TC02,TC05".
    A test with "fresh_start": false continues from the test before it, so its predecessors back to the
    nearest fresh-start test are added automatically.
    Returns (ids, added_for_dependency, None) or (None, None, (code, message)).
    """
    order = [t["id"] for t in tests]
    select = (select or "all").strip()
    if select.lower() == "all":
        wanted = set(order)
    elif select.lower() == "failed":
        wanted = {tid for tid, r in previous.items() if tid in order and r.get("status") != "pass"}
        if not previous:
            return None, None, ("NOTHING_TO_RUN", "No previous results for this run, so nothing has failed yet.")
    else:
        wanted = {s.strip() for s in select.split(",") if s.strip()}
        unknown = sorted(wanted - set(order))
        if unknown:
            return None, None, ("NOT_APPROVED", f"Not approved: {unknown}. Approved: {order}.")
    if not wanted:
        return None, None, ("NOTHING_TO_RUN", f"Selection {select!r} matches no test.")

    needed = set(wanted)
    for i, t in enumerate(tests):
        if t["id"] in wanted:
            j = i
            while j > 0 and tests[j].get("fresh_start", True) is False:
                j -= 1
                needed.add(tests[j]["id"])
    ids = [tid for tid in order if tid in needed]
    return ids, [tid for tid in ids if tid not in wanted], None
