---
name: evidence
description: How the Executor runs approved test steps on the device and records evidence and verdicts. Load before executing tests.
---
# Executing approved tests with evidence

## For every test (in the order given by begin_execution)
1. begin_test(test_id). The server restarts the app unless fresh_start is false.
2. For each step:
   - Find the element whose text / desc / label / rid matches the step target in the CURRENT screen
     (exact match first, then case-insensitive contains) and use its eid. The current screen is the
     "screen" in the last begin_test / tap / type_text / scroll / press_back result. Call get_screen only
     if there is no "screen" there or you got STALE_SCREEN.
   - Perform the action: tap(eid) | type_text(eid, value) | scroll(direction) | press_back().
     assert_visible / assert_not_visible: call assert_visible(target) and compare "visible".
   - Do NOT call screenshot: the server saves one after every step itself ("screenshot" in the result).
3. end_test(status, actual):
   - pass: every assert matched.
   - fail: an assert did not match. actual = what the screen showed instead (short, factual).
   - blocked: a step could not be performed (element not found after one scroll, WRONG_APP, STEP_LIMIT,
     SESSION_LOST). actual = which step and the error code.

## Rules
- begin_execution ALREADY_EXECUTED: the run has results. Show them; call again with rerun=true only if
  the user's message explicitly asked to run / re-run.
- Follow the approved steps exactly. Do not add, skip or "fix" steps, and never change an expected
  result to make a test pass - a planted or real mismatch must be reported as fail.
- If an element is not on screen: scroll down once and retry get_screen, then mark blocked.
- STALE_SCREEN means call get_screen again; it is not a failure.
- Never write secret values in actual; placeholders only.
- Finish with a summary table: test id, status, one-line actual.
