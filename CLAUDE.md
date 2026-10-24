# Sichakra QA Agent - project context for Claude Code

## What this is
M.Tech AI/ML lab exam project (exam window 30 Oct - 2 Nov 2026, 20-minute slot: live demo + report + viva).
An AI agent that explores an Android app, writes manual test cases, runs them only after human approval,
and produces an HTML report with a screenshot per step. Spec: SQA-SPEC-001 (SRS, HLD, LLD, Evaluation),
file Sichakra_QA_Agent_SRS_HLD_LLD_Evaluation.docx.

## Working style (important)
The author is learning: work as a TUTOR. Explain each file when asked, map new Python code to their existing
Java/Appium knowledge (C:\Users\shant\IdeaProjects\mobileTesting, BaseTest.java, codeFunction.java).
The author may also ask Claude to implement directly; then implement, test, and explain on request.
When a design choice is unclear, ASK the author instead of guessing. Never read or print .env or
profiles/client.env (auto-permission mode is on; secrets must never appear in chat or logs).

## Stack (decided)
- Windows 11, Python 3.12.2, venv at .venv
- google-adk 2.13.0, mcp 2.3.0, Appium-Python-Client 6.0.9 (newer than most docs: verify APIs against installed versions)
  - mcp 2.x: FastMCP is now `from mcp.server.mcpserver import MCPServer`; client is `mcp.Client(StdioServerParameters)`.
- Appium 3.8.0 server started separately (`appium`), uiautomator2 driver 8.7.0, Java 21
- Emulator emulator-5554 (AVD SIDApplication). Emulator only for build and exam; real device after.
- Model: QA_MODEL=gemini-3.8-flash via AI Studio key (works). gemini-2.5-flash is NOT available (404).
- Agent framework: Google ADK (Python). Device access ONLY through our own MCP server wrapping Appium.

## Architecture
```
adk web
  root_agent (LlmAgent coordinator, qa_agent/agent.py)          <- R2: NOT a SequentialAgent at root
    ├─ explore_and_design_agent: Explorer -> Test Designer -> writes runs/<id>/proposed_tests.json
    │      (stop; human reviews)
    │  scripts/approve.py <id> [--plant-defects]  -> approved_tests.json + approval.json (SHA-256)
    └─ executor_agent: runs approved tests only; MCP server enforces the gate (R2)
  MCP server (python -m mcp_server.server, stdio) -> Appium -> emulator
```
- MCP tools: launch_app, get_screen, tap, type_text, scroll, press_back, screenshot, assert_visible, reset_app
  (+ begin_execution, begin_test, end_test in --execute mode only, see R2, D6-D8).
- Executor flow: begin_execution(run_id, select) -> for each selected id: begin_test -> steps + screenshot ->
  end_test(pass|fail|blocked, actual). Results: runs/<id>/results.json; evidence: runs/<id>/evidence/<test_id>/.
  A test left open when the next begins is recorded "incomplete".
- Files: mcp_server/screen.py (XML -> compact list), device.py (Appium + guards + masking),
  approval.py (SHA-256 gate), server.py (MCP wrapper), config.py (.env + profile).
- Tools return {"ok": true,...} or {"ok": false, "error": CODE, "message": ...}; never raise.
- Element ids e01, e02... per screen; server-side locator = first UNIQUE of resource-id > accessibility id >
  text > bounds-xpath (ApiDemos rows all share android:id/text1, so uniqueness matters).
- Guards: foreground package must be the app (WRONG_APP); eid must be from the latest get_screen and the screen
  unchanged since (UNKNOWN_ELEMENT / STALE_SCREEN); STEP_LIMIT per phase; NO_SESSION; SECRET_MISSING.

## Review decisions (external review, 25 Oct 2026)
R1 FR-12/SEC-03 (High) Screenshot masking from LIVE screen, never cached bounds.  [DONE 4d]
   - device.screenshot(): get_screenshot_as_png() to memory -> read live page_source -> black boxes (PIL) ->
     only then write PNG. An unmasked image never touches disk. Code: mcp_server/device.py _mask().
   - Masked: password="true"; text equal to a secret; fields type_text filled from a placeholder; resource-id
     or hint containing a WORD in SENSITIVE_WORDS (otp, pin, mpin, tpin, password, passwd, pwd, passcode, pass).
     Word match with camelCase split: et_otp, mpinView masked; spinner, country_code not.
R2 C1/DD-05 (High) Approval gate.
   - [Step 5] root_agent is an LlmAgent coordinator with two sub-agents (explore_and_design_agent,
     executor_agent); SequentialAgent only INSIDE explore_and_design_agent, never at root.
   - [DONE 4d] Server side: `python -m mcp_server.server --execute` (executor_agent's McpToolset uses this).
     Only in execute mode are begin_execution(run_id) and begin_test(test_id) registered. Every state-changing
     action (tap, type_text, scroll, press_back) is blocked (NOT_APPROVED) until begin_execution verified
     runs/<id>/approved_tests.json against the SHA-256 in runs/<id>/approval.json AND begin_test named an
     approved id. Hash re-checked on every begin_test (edit mid-run -> APPROVAL_INVALID, gate closes).
     run_id is [A-Za-z0-9_-] only (no path escape). Code: mcp_server/approval.py (shared with approve.py).
     Execute-mode screenshots go to runs/<id>/evidence/.
R3 SI-01 (Medium) stdout is the JSON-RPC channel.  [DONE 4d]
   - server.py: logging.basicConfig(stream=sys.stderr) + logging.captureWarnings(True) BEFORE importing mcp or
     Appium; device.log() prints to stderr. tests/test_server.py spawns the server over real stdio.
R4 NFR-PE-02/DD-06 (Medium) Quota (free tier ~15 RPM; verify the exact limit for gemini-3.8-flash in AI Studio).
   - Already true: screenshot returns only a file path; get_screen is compact JSON (~1.8 KB), no images to the model.
   - Agents are text-only; vision fallback only when get_screen has < 3 interactive elements.
   - before_model_callback enforces a minimum gap between model calls: QA_MIN_TURN_SECONDS (default 4).
R5 M5 (Low) Planted defects ready in seconds.
   - scripts/approve.py --plant-defects applies 2 wrong expected results from evals/planted_defects.json
     BEFORE hashing, and records planted=true in approval.json so the report and M5 metric can show it.

## Author decisions (confirmed 25 Oct 2026)
D1 STEP_LIMIT resets on launch_app/reset_app/begin_test -> per test case for the Executor. (yes)
D2 (revised 25 Oct) reset CLEARS app data: RESET_CLEAR_DATA=true is the default (profile may set false).
   launch_app always stops + restarts the main activity (home screen); reset_app does the same + clears data.
D6 Re-running an execution OVERWRITES old results: select="all" wipes runs/<id>/evidence and results.json;
   a subset wipes only the re-run tests' evidence/results (others keep their latest result for the report).
D7 Test selection: begin_execution(run_id, select) with "all" | "failed" (status != pass last time) | "TC02,TC05".
   Only approved ids; begin_test refuses ids not selected in this execution.
D8 Per-test "fresh_start" in approved_tests.json (default true). begin_test itself restarts + clears data for
   fresh tests (server-enforced, not left to the model); fresh_start=false continues from the previous test's
   state (e.g. TC03 after TC02's login). Selecting a dependent test auto-adds its predecessors back to the
   nearest fresh-start test (reported as added_for_dependency). Warning if the predecessor did not pass.
D3 After tap/scroll/press_back the model must call get_screen (STALE_SCREEN); type_text keeps eids valid. (fine for now)
D4 Extra compact fields beyond spec: label, scrollable, checked (kept even when false), disabled. (ok)
D5 approval.json lives in runs/<id>/, written only by the author running scripts/approve.py. (proposal, not objected)

## Apps under test (profiles/, chosen by QA_PROFILE in .env)
- Phase 1 (must): apidemos -> ApiDemos-debug.apk, io.appium.android.apis / .ApiDemos (no login)
- Phase 2 (should): client -> app-dev-release.apk with mobile-number user ID, password, developer-default OTP.

## Security rules
- Credentials live ONLY in profiles/client.env (git-ignored). Never in code, docs, logs, reports, chat.
- type_text resolves {{USERNAME}}, {{PASSWORD}}, {{OTP}} inside the MCP server; model never sees real values.
  get_screen and error messages replace any secret value with its placeholder.
- Mask password/OTP fields in screenshots (R1). Never publish client-app login/OTP screens; max 5 high-level
  client-app screenshots on sichakra.in.
- Do not use employer (Infosys) resources, licences or code.

## Progress
- [x] Step 1 environment verified
- [x] Step 2 skeleton, venv, API key, model chosen
- [x] Step 3 scripts/smoke_test.py opened ApiDemos (21 elements, 12 clickable, runs/smoke.png)
- [x] Step 4a mcp_server/screen.py: XML -> compact list, max 60, interactive first (ApiDemos home 13.6 KB -> 1.8 KB)
- [x] Step 4b mcp_server/server.py (MCPServer) + mcp_server/device.py; scripts/mcp_client_test.py drives it over
      stdio. Tools returning dict send JSON in content[0].text.
- [x] Step 4c 9 tools + guards + secret redaction + masking; pytest 24 passing with FakeDriver; live-checked.
      Lessons: hide_keyboard() sends BACK and closes dialogs (removed); reset_app uses mobile: startActivity.
- [x] Step 4d review fixes: R1 masking, R2 server-side gate, R3 stderr logging, D2 reset without data clear;
      pytest 35 passing; live-checked twice on emulator.
      Lesson: a no-reset session resumes the old back stack (started on "Preference dependencies"), so
      launch_app now restarts the app.
- [x] Step 4e re-runs: D2 revised (clear data), D6 overwrite, D7 selection, D8 fresh_start + dependency chain,
      end_test + results.json; pytest 45 passing (~7 s); live executor run on emulator verified all four.
- [ ] Step 5 ADK agents (R2 coordinator layout, R4 pacing/text-only) + skills/*.md + scripts/approve.py (R5), adk web
- [ ] Step 6 HTML report, adk eval (evals/), metrics M1-M8, publish docs/ to sichakra.in/qa-agent/

## Next step
Step 5: qa_agent/agent.py (R2 coordinator layout, R4 pacing via before_model_callback + text-only),
skills/*.md, scripts/approve.py (R5 --plant-defects, evals/planted_defects.json), run in adk web.
Explorer/Designer McpToolset: `python -m mcp_server.server`; Executor: `... --execute`.
Test Designer must output "fresh_start" per test (false only for tests that continue a previous one).
