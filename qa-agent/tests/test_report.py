"""Step 6: confidence from evidence, usage attribution per run, and the HTML report."""
import json
from types import SimpleNamespace

from qa_agent import callbacks
from report.confidence import score_test
from report.usage import lines_for_run, summarize


def step(action, ok=True, **kw):
    return {"action": action, "ok": ok, **kw}


def test_planted_defect_after_three_runs_is_high_confidence():
    result = {"status": "fail", "steps": [step("tap", locator="text"), step("assert", visible=False, exact=False)]}
    one = score_test(result, [{"status": "fail"}])
    three = score_test(result, [{"status": "fail"}] * 3)
    assert one["level"] == "Medium" and one["score"] == 0.65      # 0.4 + 0 + 0.15 + 0.1
    assert three["level"] == "High" and three["score"] == 0.95     # + 0.3 stability


def test_fuzzy_match_coordinates_and_retries_lower_the_score():
    result = {"status": "pass", "steps": [step("tap", locator="coordinates"), step("tap", ok=False, error="STALE_SCREEN"),
                                          step("assert", visible=True, exact=False)]}
    c = score_test(result, [{"status": "pass"}])
    assert c["parts"] == {"text match": 0.2, "stability": 0.0, "locator": 0.05, "no retries": 0.0}
    assert c["level"] == "Low"


def test_ids_exact_and_stable_pass_is_full_marks():
    result = {"status": "pass", "steps": [step("tap", locator="resource-id"), step("assert", visible=True, exact=True)]}
    assert score_test(result, [{"status": "pass"}] * 3)["score"] == 1.0


def test_old_results_without_step_log_say_so():
    c = score_test({"status": "fail", "evidence": ["x.png"]}, None)
    assert c["score"] == 0.0 and "no step log" in c["notes"][0]


def test_blocked_gets_no_text_match_points():
    c = score_test({"status": "blocked", "steps": [step("tap", ok=False, error="ELEMENT_NOT_FOUND")]}, [])
    assert c["parts"]["text match"] == 0.0


def usage_line(agent, run_id="", total=100):
    return {"ts": "2026-10-25T05:00:00+00:00", "agent": agent, "model": "m", "run_id": run_id,
            "prompt": total - 10, "output": 10, "total": total}


def test_exploration_lines_belong_to_the_run_designed_next(tmp_path):
    rows = [usage_line("explorer"), usage_line("explorer"), usage_line("test_designer", "R1"),
            usage_line("executor_agent", "R1"), usage_line("explorer"), usage_line("test_designer", "R2")]
    (tmp_path / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    r1 = summarize(lines_for_run(tmp_path, "R1"))
    assert r1["calls"] == 4 and r1["phases"]["design"]["calls"] == 3 and r1["phases"]["execute"]["calls"] == 1
    assert summarize(lines_for_run(tmp_path, "R2"))["calls"] == 2


def test_usage_lines_are_tagged_with_the_run(tmp_path, monkeypatch):
    from google.genai import types
    monkeypatch.setattr(callbacks, "USAGE_DIR", tmp_path)
    ctx = SimpleNamespace(state={"design_run_id": "R9"}, agent_name="test_designer", session=SimpleNamespace(id="s"))
    resp = SimpleNamespace(partial=False, model_version="m", usage_metadata=types.GenerateContentResponseUsageMetadata(
        prompt_token_count=5, candidates_token_count=1, total_token_count=6))
    callbacks.count_usage(ctx, resp)
    assert json.loads((tmp_path / "s.jsonl").read_text())["run_id"] == "R9"


def test_report_builds_with_scores_reasons_and_embedded_screenshots(tmp_path, monkeypatch):
    from PIL import Image
    from report import build_report
    root = tmp_path / "qa"
    run = root / "runs" / "app-1"
    (run / "evidence" / "TC01").mkdir(parents=True)
    Image.new("RGB", (60, 120), "white").save(run / "evidence" / "TC01" / "001_TC01_s01_tap.png")
    tc = {"id": "TC01", "title": "Open <Preference>", "priority": "high", "steps": [{"action": "tap", "target": "Preference"}],
          "expected_result": "List shown"}
    (run / "approved_tests.json").write_text(json.dumps({"run_id": "app-1", "tests": [tc, {**tc, "id": "TC02"}]}))
    (run / "approval.json").write_text(json.dumps({"approved_by": "me", "sha256": "ab" * 32, "planted_defects": [
        {"test_id": "TC01", "step": 1, "original": "List", "planted": "Planted defect: x"}]}))
    (run / "results.json").write_text(json.dumps({"run_id": "app-1", "history": {"TC01": [{"status": "fail"}]}, "tests": {
        "TC01": {"status": "fail", "actual": "Expected 'Planted defect: x' was not visible",
                 "steps": [{"n": 1, "action": "tap", "ok": True, "target": "Preference", "locator": "text",
                            "screenshot": "runs/app-1/evidence/TC01/001_TC01_s01_tap.png"},
                           {"n": 2, "action": "assert", "ok": True, "target": "Planted defect: x", "visible": False,
                            "exact": False, "matches": []}]}}}))
    monkeypatch.setattr(build_report, "ROOT", root)
    out = build_report.build(run)
    page = out.read_text(encoding="utf-8")
    assert "Failure reason" in page and "planted defect" in page and "Medium" in page
    assert "data:image/jpeg;base64," in page                      # screenshot embedded: works offline
    assert "Open &lt;Preference&gt;" in page                        # escaped
    assert "NOT RUN" in page                                        # TC02 has no result
