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
    monkeypatch.setattr(callbacks, "MIN_GAP", 0.3)
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
    set_execution_request(" apidemos-1 ", "", ctx)
    assert ctx.state == {"run_id": "apidemos-1", "select": "all"}
