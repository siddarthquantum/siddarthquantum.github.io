---
name: test-design
description: How to turn an exploration map of an Android app into reviewable manual test cases (JSON for save_proposed_tests). Load before designing any test case.
---
# Designing manual test cases

## Inputs
Use ONLY what the exploration map shows: screen names, visible texts, element types, navigation paths.
Never invent screens, buttons or messages that were not observed.

## Shape of a good suite
- 4 to 8 test cases; ids TC01, TC02, ... in the order they should run.
- Mix: happy paths (high), state changes such as checkbox/toggle (medium), negative or edge cases
  (medium/low: disabled element, cancel a dialog, back navigation).
- One clear purpose per test; title starts with a verb ("Verify WiFi settings opens a dialog").

## Steps
- actions: tap, type, scroll, back, assert_visible, assert_not_visible.
- target = the VISIBLE TEXT of the element (or its content-desc / resource-id if it has no text).
  Never use eids (e01...): they change on every screen.
- Navigate from the app's home screen: each fresh test starts there with clean app data.
- Put an assert after every meaningful navigation or state change, and end with the assert that proves
  expected_result. Every test needs at least one assert.
- Max 12 steps per test (device step limit is 25 actions incl. retries).
- To check a checkbox state, assert on the text that only appears/enables when it changes, and
  describe the expected state in "expected".
- An assert must be able to FAIL. Never assert_visible the text you just tapped (tap "Switch" then
  assert "Switch" passes even if nothing happened; the tool rejects it). Assert what appears only
  because of the action: the next screen's title or an item that exists only there, or a dialog title.
- Use only texts that are in the exploration map. The tool rejects targets never seen on a screen.
- expected_result names the exact visible text that proves success, e.g. 'Dialog titled
  "WiFi settings" is visible', not "navigated successfully".

## fresh_start
- Default true: app restarted with cleared data, starts on home. Tests must not depend on each other.
- false ONLY when the test deliberately continues the previous test's end state (for example after a
  login test). The first test is always true.

## Credentials
Only {{USERNAME}}, {{PASSWORD}}, {{OTP}} as type values. For negative cases use an obviously fake value
such as "wrong-pass-123". Never ask for or write real credentials.

## Output
Call save_proposed_tests with a JSON list. If it returns INVALID_TESTS, fix exactly the listed problems
and call again. Then show the user a short table (id, title, priority, fresh_start) and the approval
command from the tool result.
