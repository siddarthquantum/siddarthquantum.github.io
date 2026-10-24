"""Sichakra QA Agent - ADK agents (Step 5). Run with:  adk web   (then pick qa_agent)

root_agent (LlmAgent coordinator)                                   R2: no SequentialAgent at the root
  ├─ explore_and_design_agent (SequentialAgent)
  │     explorer       - drives the app through the MCP server (explore mode), writes an exploration map
  │     test_designer  - turns the map into test cases, saves runs/<id>/proposed_tests.json
  │  (human: python scripts/approve.py <run_id> [--plant-defects])
  └─ executor_agent    - MCP server in --execute mode: device actions only after the SHA-256 gate passes
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models import Gemini
from google.adk.skills import load_skills_from_dir
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.adk.tools.skill_toolset import SkillDiscoveryMode, SkillToolset
from google.genai import types
from mcp import StdioServerParameters

from qa_agent.callbacks import pace_model_calls, track_screens
from qa_agent.test_cases import save_proposed_tests

ROOT = Path(__file__).resolve().parent.parent
# Only the main .env (API key, model, profile name). Profile credentials are loaded by the MCP server
# process alone, so they never exist in the agent process.
load_dotenv(ROOT / ".env")

MODEL_ID = os.getenv("QA_MODEL") or "gemini-3.8-flash"
# Fast demo mode: click-only (no typing), few screens, few tests -> fewer model calls.
CLICK_ONLY = os.getenv("QA_CLICK_ONLY", "true").lower() == "true"
MAX_SCREENS = int(os.getenv("QA_MAX_SCREENS", "3"))
MAX_TESTS = int(os.getenv("QA_MAX_TESTS", "4"))
ACTIONS = ["get_screen", "tap", "scroll", "press_back", "screenshot", "assert_visible"]
if not CLICK_ONLY:
    ACTIONS.append("type_text")
CLICK_RULE = ("CLICK-ONLY MODE: do not type text; use only tap, scroll, back and asserts. "
              if CLICK_ONLY else "")


def model():
    # Retry 429 / 5xx with backoff instead of failing the demo (R4).
    return Gemini(model=MODEL_ID, retry_options=types.HttpRetryOptions(
        attempts=4, initial_delay=10, max_delay=60, http_status_codes=[429, 500, 503]))


def device_tools(execute: bool, tool_filter: list[str]):
    args = ["-m", "mcp_server.server"] + (["--execute"] if execute else [])
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(command=sys.executable, args=args, cwd=str(ROOT)),
            timeout=120,  # ADK uses this as the per-call read timeout on stdio; Appium start takes ~10-30 s
        ),
        tool_filter=tool_filter,
    )


SKILLS = {s.name: s for s in load_skills_from_dir(ROOT / "skills")}


def skills(*names):
    return SkillToolset([SKILLS[n] for n in names], discovery_mode=SkillDiscoveryMode.EAGER)


COMMON = dict(before_model_callback=pace_model_calls, after_tool_callback=track_screens)

explorer = LlmAgent(
    name="explorer",
    model=model(),
    description="Explores the Android app on the device and writes an exploration map.",
    instruction=CLICK_RULE + f"""You are a mobile QA explorer. Explore the app under test through the device tools.

1. Call launch_app once, then get_screen.
2. Explore breadth-first along the user's goal (if no goal: the main menu). Visit at most {MAX_SCREENS} screens. Be quick: no repeated get_screen.
   For each: get_screen, note what is there, tap into the most relevant items, press_back to return.
   Act only on eids from the LATEST get_screen. STALE_SCREEN means: call get_screen again.
3. If get_screen says few_elements, take ONE screenshot; you will be shown the image.
4. Login/password/OTP screens: load the login-tests skill first.
5. You have about 25 device actions. Stop exploring before running out.

Final answer = the EXPLORATION MAP (plain text, no eids, max ~40 lines):
- Goal: <the user's goal>
- For each screen: path from home (e.g. Home > Preference > 3. Preference dependencies), its key
  elements with their visible text, type (button, checkbox+state, edit field, list item), and what
  happens when used (navigates to X, opens dialog Y, enabled only when Z).""",
    tools=[device_tools(False, ["launch_app"] + ACTIONS),
           skills("login-tests")],
    output_key="exploration",
    **COMMON,
)

test_designer = LlmAgent(
    name="test_designer",
    model=model(),
    description="Designs manual test cases from the exploration map and saves them for human approval.",
    instruction=CLICK_RULE + f"Design at most {MAX_TESTS} test cases. " + """You are a senior QA test designer. Load the test-design skill first and follow it.
If the map contains login, password or OTP fields, also load the login-tests skill.

Exploration map from the explorer:
{exploration}

Design the test cases from this map only, save them with save_proposed_tests, then show the user a
short table (id, title, priority, fresh_start) and the exact approval command from the tool result.
Say clearly that NOTHING runs on the device until a human approves.""",
    tools=[save_proposed_tests, skills("test-design", "login-tests")],
    output_key="proposed",
    **COMMON,
)

explore_and_design_agent = SequentialAgent(
    name="explore_and_design_agent",
    description="Explores the app, then designs test cases for human approval. Never executes tests.",
    sub_agents=[explorer, test_designer],
)

executor_agent = LlmAgent(
    name="executor_agent",
    model=model(),
    description="Executes HUMAN-APPROVED test cases on the device and records evidence.",
    instruction="""You are the test executor. Load the evidence skill first and follow it exactly.

Run id: {run_id?}   Selection: {select?}
1. begin_execution(run_id, select). If it fails (NOT_APPROVED, APPROVAL_INVALID, NOTHING_TO_RUN), stop
   and explain to the user what to do (approval command: python scripts/approve.py <run_id>).
2. It returns the approved tests. Run each selected test in order: begin_test, the steps with one
   screenshot per step, end_test.
3. Finish with the summary table.""",
    tools=[device_tools(True, ["begin_execution", "begin_test", "end_test"] + ACTIONS),
           skills("evidence")],
    include_contents="none",  # only this turn: keeps the explorer's long history out of every call (R4)
    **COMMON,
)


def set_execution_request(run_id: str, select: str, tool_context: ToolContext) -> dict:
    """Record which approved run to execute, before transferring to executor_agent.

    Args:
      run_id: The run id the human approved, e.g. apidemos-20261025-101500.
      select: "all", "failed", or test ids like "TC02,TC05".
    """
    tool_context.state["run_id"] = run_id.strip()
    tool_context.state["select"] = (select or "all").strip()
    return {"ok": True, "run_id": run_id, "select": select}


root_agent = LlmAgent(
    name="qa_coordinator",
    model=model(),
    description="Routes the user to exploration/design or to execution of approved tests.",
    instruction="""You coordinate an AI mobile QA workflow for the Android app under test.

- User wants to explore the app and/or design test cases -> transfer to explore_and_design_agent.
- User wants to run / execute / re-run tests -> they must give a run id that a human approved with
  scripts/approve.py. Ask for it if missing. Selection is "all" unless they say "failed" or list ids.
  Call set_execution_request(run_id, select), then transfer to executor_agent.
- Never claim tests were approved or executed yourself. Approval is a human step outside this chat:
  python scripts/approve.py <run_id>   (add --plant-defects for the M5 planted-defect check)
- Otherwise briefly explain these two options.""",
    tools=[set_execution_request],
    sub_agents=[explore_and_design_agent, executor_agent],
    before_model_callback=pace_model_calls,
)
