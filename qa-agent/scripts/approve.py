"""Human approval gate (DD-05, R2, R5): review proposed tests and approve them for execution.

    python scripts/approve.py <run_id>                  show tests, ask, approve
    python scripts/approve.py <run_id> --plant-defects  also plant 2 wrong expected results (M5 check)
    python scripts/approve.py <run_id> --yes            no question (scripted demo)
    python scripts/approve.py --list                    list runs and their state

Writes runs/<run_id>/approved_tests.json and approval.json (SHA-256). The MCP server refuses to execute
anything else. Only a human runs this; the agents have no tool that can.
"""
import argparse
import copy
import getpass
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mcp_server.approval import RUN_ID, sha256_file  # noqa: E402
from qa_agent.test_cases import TestSuite  # noqa: E402

RUNS = ROOT / "runs"


def plant_defects(tests: list, spec: dict) -> list:
    """Replace the target of the last assert_visible step in the first `count` tests that have one."""
    planted = []
    for test in tests:
        if len(planted) == spec["count"]:
            break
        asserts = [i for i, s in enumerate(test["steps"]) if s["action"] == "assert_visible"]
        if not asserts:
            continue
        i = asserts[-1]
        wrong = spec["wrong_texts"][len(planted) % len(spec["wrong_texts"])]
        planted.append({"test_id": test["id"], "step": i + 1, "original": test["steps"][i]["target"],
                        "planted": wrong})
        test["steps"][i]["target"] = wrong
    return planted


def list_runs():
    for d in sorted(p for p in RUNS.iterdir() if (p / "proposed_tests.json").exists()):
        state = "approved" if (d / "approval.json").exists() else "waiting for approval"
        if (d / "results.json").exists():
            state += ", executed"
        print(f"{d.name:40} {state}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--plant-defects", action="store_true", help="plant 2 wrong expected results (M5)")
    ap.add_argument("--yes", action="store_true", help="approve without asking")
    ap.add_argument("--list", action="store_true", help="list runs")
    a = ap.parse_args()
    if a.list or not a.run_id:
        list_runs()
        return 0
    if not RUN_ID.fullmatch(a.run_id):
        sys.exit("run_id may contain only letters, digits, _ and -")

    run_dir = RUNS / a.run_id
    proposed_file = run_dir / "proposed_tests.json"
    if not proposed_file.exists():
        sys.exit(f"Not found: {proposed_file.relative_to(ROOT)}")
    proposed = json.loads(proposed_file.read_text(encoding="utf-8"))
    TestSuite.model_validate({"tests": proposed["tests"]})  # refuse anything the schema would reject

    print(f"\nRun {a.run_id}: {len(proposed['tests'])} proposed test cases\n")
    for t in proposed["tests"]:
        print(f"  {t['id']}  [{t['priority']:6}] fresh_start={str(t['fresh_start']).lower():5}  {t['title']}")
        for n, s in enumerate(t["steps"], 1):
            detail = s["target"] + (f" <- '{s['value']}'" if s.get("value") else "")
            print(f"        {n:2}. {s['action']:18} {detail}")
        print(f"        expected: {t['expected_result']}\n")

    if (run_dir / "approval.json").exists():
        print("NOTE: this run is already approved; approving again replaces it and old results.")
    if not a.yes and input("Approve ALL these test cases for execution? [y/N] ").strip().lower() != "y":
        print("Not approved. Nothing will run.")
        return 1

    tests = copy.deepcopy(proposed["tests"])
    planted = []
    if a.plant_defects:
        spec = json.loads((ROOT / "evals" / "planted_defects.json").read_text(encoding="utf-8"))
        planted = plant_defects(tests, spec)

    approved_file = run_dir / "approved_tests.json"
    approved_file.write_text(json.dumps({"run_id": a.run_id, "tests": tests}, indent=2), encoding="utf-8")
    approval = {"run_id": a.run_id, "sha256": sha256_file(approved_file),
                "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "approved_by": getpass.getuser(),
                "test_ids": [t["id"] for t in tests], "planted_defects": planted}
    (run_dir / "approval.json").write_text(json.dumps(approval, indent=2), encoding="utf-8")
    (run_dir / "results.json").unlink(missing_ok=True)  # results of an older approval no longer apply

    print(f"\nApproved {len(tests)} tests. SHA-256 {approval['sha256'][:16]}...")
    for p in planted:
        print(f"  planted defect: {p['test_id']} step {p['step']}: '{p['original']}' -> '{p['planted']}'")
    print(f"\nIn adk web, ask the coordinator: run tests for {a.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
