"""Step 5: test-case schema, approval script helpers, callbacks and agent wiring (no model calls)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from qa_agent import callbacks
from qa_agent.test_cases import validate_suite

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import approve  # noqa: E402


def tc(id="TC01", fresh=True, steps=None, **kw):
    return {"id": id, "title": "Verify something works", "priority": "high", "fresh_start": fresh,
            "steps": steps or [{"action": "tap", "target": "Preference"},
                               {"action": "assert_visible", "target": "3. Preference dependencies"}],
            "expected_result": "List is shown", **kw}


# ---------- schema ----------
def test_valid_suite():
    suite, err = validate_suite(json.dumps([tc("TC01"), tc("TC02", fresh=False)]))
    assert err is None and len(suite.tests) == 2


@pytest.mark.parametrize("tests,problem", [
    ([tc("TC01", fresh=False)], "first test must have fresh_start=true"),
    ([tc("TC01"), tc("TC01")], "unique"),
    ([tc(steps=[{"action": "tap", "target": "App"}])], "no assert"),
    ([tc(steps=[{"action": "type", "target": "pw", "value": "{{PIN}}"},
                {"action": "assert_visible", "target": "x"}])], "unknown placeholder"),
    ([tc(id="T1")], "id"),
    ([tc(steps=[{"action": "swipe", "target": "x"}, {"action": "assert_visible", "target": "x"}])], "action"),
])
def test_invalid_suites_explain_the_problem(tests, problem, monkeypatch):
    monkeypatch.setenv("QA_CLICK_ONLY", "false")
    suite, err = validate_suite(json.dumps(tests))
    assert suite is None and problem in err


def test_click_only_mode_rejects_typing(monkeypatch):
    monkeypatch.setenv("QA_CLICK_ONLY", "true")
    steps = [{"action": "type", "target": "Name", "value": "abc"}, {"action": "assert_visible", "target": "abc"}]
    assert "click-only" in validate_suite(json.dumps([tc(steps=steps)]))[1]


def test_click_only_agents_have_no_type_text():
    from qa_agent import agent
    if agent.CLICK_ONLY:
        assert "type_text" not in agent.explorer.tools[0].tool_filter
        assert "type_text" not in agent.executor_agent.tools[0].tool_filter


def test_not_json():
    assert "Not valid JSON" in validate_suite("TC01: tap App")[1]


# ---------- R5 planted defects ----------
def test_plant_defects_changes_last_assert_of_first_two_tests():
    tests = [tc("TC01"), tc("TC02", steps=[{"action": "tap", "target": "App"},
                                            {"action": "assert_not_visible", "target": "x"}]),
             tc("TC03"), tc("TC04")]
    spec = {"count": 2, "wrong_texts": ["W1", "W2"]}
    planted = approve.plant_defects(tests, spec)
    assert [p["test_id"] for p in planted] == ["TC01", "TC03"]  # TC02 has no assert_visible
    assert tests[0]["steps"][1]["target"] == "W1" and tests[2]["steps"][1]["target"] == "W2"
    assert planted[0]["original"] == "3. Preference dependencies"


def test_planted_defects_file_is_valid():
    spec = json.loads((ROOT / "evals" / "planted_defects.json").read_text())
    assert spec["count"] == 2 and len(spec["wrong_texts"]) >= 2


# ---------- R4 callbacks ----------
def mcp_response(data):
    return {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False}


def test_vision_fallback_only_after_few_elements(tmp_path):
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG fake")
    ctx = SimpleNamespace(state={})
    shot = SimpleNamespace(name="screenshot")
    screen = SimpleNamespace(name="get_screen")

    callbacks.track_screens(screen, {}, ctx, mcp_response({"ok": True, "elements": []}))
    callbacks.track_screens(shot, {}, ctx, mcp_response({"ok": True, "path": str(png)}))
    assert not ctx.state.get("temp:vision_png")  # normal screen: stay text-only

    callbacks.track_screens(screen, {}, ctx, mcp_response({"ok": True, "few_elements": True}))
    callbacks.track_screens(shot, {}, ctx, mcp_response({"ok": True, "path": str(png)}))
    request = SimpleNamespace(contents=[])
    callbacks.attach_vision(ctx, request)
    assert len(request.contents) == 1 and request.contents[0].parts[1].inline_data.data == b"\x89PNG fake"
    callbacks.attach_vision(ctx, request)  # attached once only
    assert len(request.contents) == 1


def test_pacing_waits_between_model_calls(monkeypatch):
    import anyio
    import time
    monkeypatch.setenv("QA_MIN_TURN_SECONDS", "0.3")
    ctx, req = SimpleNamespace(state={}), SimpleNamespace(contents=[])

    async def two_calls():
        t0 = time.monotonic()
        await callbacks.pace_model_calls(ctx, req)
        await callbacks.pace_model_calls(ctx, req)
        return time.monotonic() - t0

    assert anyio.run(two_calls) >= 0.29


# ---------- R2 wiring ----------
def test_agent_tree_follows_review_r2():
    from google.adk.agents import LlmAgent, SequentialAgent
    from qa_agent import agent
    root = agent.root_agent
    assert isinstance(root, LlmAgent)  # coordinator, not a SequentialAgent at the root
    subs = {a.name: a for a in root.sub_agents}
    assert isinstance(subs["explore_and_design_agent"], SequentialAgent)
    assert [a.name for a in subs["explore_and_design_agent"].sub_agents] == ["explorer", "test_designer"]
    assert "--execute" in subs["executor_agent"].tools[0]._connection_params.server_params.args
    assert "--execute" not in agent.explorer.tools[0]._connection_params.server_params.args
    # the designer cannot touch the device; only the explorer and executor have device tools
    assert not any(type(t).__name__ == "McpToolset" for t in agent.test_designer.tools)


def test_set_execution_request_stores_state():
    from qa_agent.agent import set_execution_request
    ctx = SimpleNamespace(state={})
    set_execution_request(" apidemos-1 ", "", False, ctx)
    assert ctx.state == {"run_id": "apidemos-1", "select": "all", "rerun": False}


# ---------- Step 0: quota fail-fast and usage counter (M7) ----------
def quota_429(quota_id):
    from google.genai import errors
    return errors.APIError(429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded",
        "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                     "violations": [{"quotaId": quota_id}]}]}})


@pytest.fixture
def no_daily_block(monkeypatch):
    monkeypatch.setattr(callbacks, "_daily_block", None)


def text_of(resp):
    return resp.content.parts[0].text


def test_daily_quota_fails_fast_and_blocks_later_calls(no_daily_block):
    import asyncio
    req = SimpleNamespace(model="gemini-3.8-flash", contents=[])
    err = quota_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    resp = callbacks.quota_error(None, req, err)
    assert "QUOTA_DAILY" in text_of(resp) and "gemini-3.8-flash" in text_of(resp)
    # the next agent in the chain gets the same message without calling the API
    ctx = SimpleNamespace(state={})
    again = asyncio.run(callbacks.pace_model_calls(ctx, req))
    assert again is not None and "QUOTA_DAILY" in text_of(again)


def test_minute_quota_explains_wait_and_does_not_block(no_daily_block):
    req = SimpleNamespace(model="gemini-3.8-flash", contents=[])
    resp = callbacks.quota_error(None, req, quota_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"))
    assert "QUOTA_MINUTE" in text_of(resp)
    assert callbacks._daily_block is None


def test_other_errors_are_not_swallowed(no_daily_block):
    from google.genai import errors
    req = SimpleNamespace(model="m", contents=[])
    assert callbacks.quota_error(None, req, errors.APIError(500, {"error": {"code": 500}})) is None
    assert callbacks.quota_error(None, req, ValueError("boom")) is None


def test_usage_counter_adds_up_per_agent_and_logs(tmp_path, monkeypatch):
    from google.genai import types
    monkeypatch.setattr(callbacks, "USAGE_DIR", tmp_path)
    ctx = SimpleNamespace(state={}, agent_name="explorer", session=SimpleNamespace(id="s1"))

    def resp(p, o):
        return SimpleNamespace(partial=False, model_version="gemini-x", usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=p, candidates_token_count=o, total_token_count=p + o))

    callbacks.count_usage(ctx, resp(1000, 50))
    callbacks.count_usage(ctx, resp(1200, 30))
    ctx.agent_name = "test_designer"
    callbacks.count_usage(ctx, resp(900, 400))
    u = ctx.state["usage"]
    assert u["requests"] == 3 and u["total"] == 3580
    assert u["by_agent"]["explorer"] == {"requests": 2, "total": 2280}
    lines = (tmp_path / "s1.jsonl").read_text().splitlines()
    assert len(lines) == 3 and json.loads(lines[2])["agent"] == "test_designer"


def test_usage_counter_skips_partial_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(callbacks, "USAGE_DIR", tmp_path)
    ctx = SimpleNamespace(state={}, agent_name="explorer", session=SimpleNamespace(id="s1"))
    callbacks.count_usage(ctx, SimpleNamespace(partial=True, usage_metadata=object()))
    assert "usage" not in ctx.state


def test_all_agents_fail_fast_on_quota_and_count_usage():
    from qa_agent import agent
    for a in (agent.root_agent, agent.explorer, agent.test_designer, agent.executor_agent):
        assert a.on_model_error_callback is callbacks.quota_error
        assert a.after_model_callback is callbacks.count_usage
        assert 429 not in a.model.retry_options.http_status_codes


def test_per_role_model_override(monkeypatch):
    from qa_agent import agent
    monkeypatch.setenv("QA_MODEL_EXPLORE", "gemini-3.1-flash-lite")
    assert agent.model("explore").model == "gemini-3.1-flash-lite"
    monkeypatch.delenv("QA_MODEL_DESIGN", raising=False)
    assert agent.model("design").model == agent.MODEL_ID


def test_pacing_reads_env_at_call_time(monkeypatch):
    # agent.py imports callbacks before load_dotenv(); the gap must still follow .env
    monkeypatch.setenv("QA_MIN_TURN_SECONDS", "5")
    assert callbacks.min_gap() == 5.0


# ---------- no invented tests, no assertions that cannot fail (Step 5 fix, 25 Oct) ----------
def test_assert_on_just_tapped_text_is_rejected():
    steps = [{"action": "tap", "target": "Preference"}, {"action": "tap", "target": "Switch"},
             {"action": "assert_visible", "target": "Switch"}]
    assert "cannot fail" in validate_suite(json.dumps([tc(steps=steps)]))[1]


def test_assert_on_next_screen_text_is_fine():
    steps = [{"action": "tap", "target": "Preference"},
             {"action": "assert_visible", "target": "3. Preference dependencies"}]
    assert validate_suite(json.dumps([tc(steps=steps)]))[1] is None


def test_track_screens_records_seen_texts():
    state = {}
    resp = {"content": [{"type": "text", "text": json.dumps({"ok": True, "elements": [
        {"eid": "e01", "text": "Preference", "label": "Preference"}, {"eid": "e02", "desc": "Navigate up"}]})}]}
    callbacks.track_screens(SimpleNamespace(name="get_screen"), {}, SimpleNamespace(state=state), resp)
    assert state["seen_texts"] == ["Navigate up", "Preference"]


def save_with(seen, steps):
    from qa_agent.test_cases import save_proposed_tests
    return save_proposed_tests(json.dumps([tc(steps=steps)]), tool_context=SimpleNamespace(state={"seen_texts": seen}))


def test_save_refuses_without_exploration():
    assert save_with([], tc()["steps"])["error"] == "NO_EXPLORATION"


def test_save_refuses_invented_targets():
    r = save_with(["Preference"], [{"action": "tap", "target": "Preference"},
                                   {"action": "assert_visible", "target": "9. Switch"}])
    assert r["error"] == "UNSEEN_TARGET" and "9. Switch" in r["message"]


def test_save_accepts_seen_targets(tmp_path, monkeypatch):
    from qa_agent import test_cases
    monkeypatch.setattr(test_cases, "RUNS", tmp_path)
    r = save_with(["Preference", "3. Preference dependencies"], tc()["steps"])
    assert r["ok"] and (tmp_path / r["run_id"] / "proposed_tests.json").exists()
