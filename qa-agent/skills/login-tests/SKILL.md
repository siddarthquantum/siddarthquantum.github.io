---
name: login-tests
description: Rules for exploring and testing login, password and OTP screens without ever handling real credentials. Load when a screen has username/mobile, password, PIN or OTP fields.
---
# Login, password and OTP screens

## Credentials are placeholders
- Type {{USERNAME}} into the user ID / mobile number field, {{PASSWORD}} into the password field and
  {{OTP}} into the OTP field. The device server swaps in the real values; you never see them.
- If a tool returns SECRET_MISSING, the active profile has no test credentials: stop and tell the user.
- Never repeat, guess or ask the user for real values. Screens show placeholders instead of typed secrets.

## Exploring
- Explore the login screen itself (fields, buttons, links such as "Forgot password").
- Log in once with the placeholders to see the first screen after login, then continue exploring.

## Test ideas
- Valid login with placeholders reaches the home screen (high).
- Wrong password "wrong-pass-123" shows an error and stays on login (high).
- Empty fields: login button disabled or error shown (medium).
- Wrong OTP "000000" is rejected (medium).
- Tests that need a logged-in user: either start with the login steps (fresh_start true), or run right
  after the valid-login test with fresh_start false.

## Evidence
Password, PIN and OTP fields are blacked out automatically. Do not describe their content in results.
Login and OTP screenshots of the client app must never be published.
