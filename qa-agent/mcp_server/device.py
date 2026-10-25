"""Device layer: one Appium session plus the guards from the spec (Step 4b/4c, FR-04..FR-09).

Every public method returns {"ok": True, ...} or {"ok": False, "error": CODE, "message": ...}
and never raises. server.py only wraps these methods as MCP tools.

Guards:
  - foreground package must be the app under test (WRONG_APP)
  - an eid must come from the latest get_screen, and the screen must not have changed since (STALE_SCREEN)
  - at most STEP_LIMIT device actions per phase; launch_app/reset_app start a new phase (STEP_LIMIT)
  - execute mode (R2): no device action until begin_execution verified the human approval and
    begin_test named an approved test (NOT_APPROVED / APPROVAL_INVALID)
"""
import functools
import json
import os
import shutil
import re
import sys
import time
from pathlib import Path

from mcp_server.approval import load_approved, select_tests
from mcp_server.screen import parse_screen, MAX_ELEMENTS

ROOT = Path(__file__).resolve().parent.parent
FEW_ELEMENTS = 3  # fewer interactive elements than this -> vision fallback allowed (R4)

# Placeholder in type_text -> env var in the profile file. The model only ever sees the placeholder.
SECRET_VARS = {"USERNAME": "TEST_USERNAME", "PASSWORD": "TEST_PASSWORD", "OTP": "TEST_OTP"}
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def log(*args):
    # stdout is the MCP protocol channel; all logging must go to stderr.
    print("[device]", *args, file=sys.stderr, flush=True)


def fail(code, message):
    return {"ok": False, "error": code, "message": message}


def _secrets():
    """{placeholder_name: value} for secrets that are set. Read from env each time, never stored."""
    return {k: os.environ[v] for k, v in SECRET_VARS.items() if os.environ.get(v)}


def _scrub(text: str) -> str:
    for name, value in _secrets().items():
        text = text.replace(value, "{{" + name + "}}")
    return text


# Words in a resource-id or hint that mark a sensitive input, even without password="true" (R1).
# Matched as whole words so "spinner" is not "pin" and "country_code" is not masked.
SENSITIVE_WORDS = {"otp", "pin", "mpin", "tpin", "password", "passwd", "pwd", "passcode", "pass"}


def _sensitive_name(node) -> bool:
    for attr in ("resource-id", "hint"):
        name = node.get(attr, "").split(":id/")[-1]
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()  # mpinView -> mpin_view
        if SENSITIVE_WORDS & set(re.split(r"[^a-z0-9]+", name)):
            return True
    return False


def locator_kind(locator) -> str:
    """resource-id | accessibility-id | text | coordinates (feeds the report's confidence score)."""
    if not locator:
        return ""
    if locator["by"] == "id":
        return "resource-id"
    if locator["by"] == "accessibility id":
        return "accessibility-id"
    return "coordinates" if "@bounds" in locator["value"] else "text"


def logged(action):
    """Execute mode, inside a test: append each step's facts to the test's step log (Step 6 confidence).
    Outermost decorator, so errors turned into results by @safe are logged too (they count as retries)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            eid = kwargs.get("eid", args[0] if args and action != "assert" else None)
            locator, label = self.locators.get(eid), self.screen_labels.get(eid, "")
            result = fn(self, *args, **kwargs)
            if self.mode == "execute" and self.current_test:
                entry = {"n": len(self.step_log) + 1, "action": action, "ok": bool(result.get("ok")),
                         "target": label, "locator": locator_kind(locator)}
                if action == "assert":
                    text = kwargs.get("text", args[0] if args else "")
                    matches = result.get("matches") or []
                    entry.update(target=text, visible=bool(result.get("visible")), matches=matches,
                                 exact=any((m or "").strip().lower() == text.strip().lower() for m in matches))
                if not result.get("ok"):
                    entry["error"] = result.get("error", "")
                if result.get("screenshot"):
                    entry["screenshot"] = result["screenshot"]
                self.step_log.append(entry)
            return result
        return wrapper
    return deco


def safe(fn):
    """Turn any exception into an APPIUM_ERROR result, with secrets scrubbed from the message."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as e:  # noqa: BLE001 - tools must never raise
            msg = _scrub(f"{type(e).__name__}: {e}".splitlines()[0])[:300]
            log("error in", fn.__name__, msg)
            if type(e).__name__ in ("InvalidSessionIdException", "NoSuchDriverException"):
                # Another server process (explore vs execute) started a session on the same device,
                # which ends ours. launch_app / begin_test will reconnect.
                self.driver = None
                return fail("SESSION_LOST", "The Appium session ended. Call launch_app to reconnect.")
            return fail("APPIUM_ERROR", msg)
    return wrapper


class Device:
    def __init__(self, cfg: dict, driver_factory=None, mode: str = "explore"):
        self.cfg = cfg
        self.mode = mode           # "explore" (Explorer/Designer) or "execute" (Executor, gated)
        self.runs_dir = ROOT / "runs"
        self.run_id = None         # set by begin_execution after the approval check
        self.tests = {}            # approved test id -> test dict
        self.selected = []         # ids chosen for this execution, in approved order
        self.results = {}          # test id -> result, saved to runs/<id>/results.json
        self.current_test = None
        self.last_status = None
        self.evidence = []         # screenshot paths of the current test
        self.step_log = []         # facts per executed step of the current test (report confidence)
        self.history = {}          # test id -> every verdict ever recorded, kept across re-runs
        self.test_started = None
        self.app_package = cfg["app_package"]
        self.step_limit = cfg.get("step_limit", 25)
        self._driver_factory = driver_factory or self._appium_driver
        self.driver = None
        self.locators = {}       # eid -> locator, from the latest get_screen only
        self.screen_bounds = {}  # eid -> [x1, y1, x2, y2]
        self.screen_labels = {}  # eid -> visible label, for the step log
        self.stale = True        # True after anything that may change the screen
        self.steps = 0
        self.masked = set()      # locators of fields that received a secret (masked in screenshots)
        self.run_dir = ROOT / "runs" / time.strftime("%Y%m%d-%H%M%S")
        self.shot_no = 0

    # ---------- session ----------
    def _appium_driver(self):
        from appium import webdriver
        from appium.options.android import UiAutomator2Options

        opts = UiAutomator2Options()
        opts.device_name = self.cfg["device_name"]
        if self.cfg.get("app_path"):
            opts.app = self.cfg["app_path"]
        opts.app_package = self.app_package
        opts.app_activity = self.cfg["app_activity"]
        opts.new_command_timeout = 300
        opts.no_reset = True
        return webdriver.Remote(self.cfg["appium_url"], options=opts)

    def _new_phase(self):
        self.steps = 0
        self.stale = True
        self.locators, self.screen_bounds = {}, {}

    def _need_session(self):
        if self.driver is None:
            return fail("NO_SESSION", "No app session. Call launch_app first.")
        return None

    def _foreground(self):
        return self.driver.current_package

    def _need_app(self):
        pkg = self._foreground()
        if pkg != self.app_package:
            return fail("WRONG_APP", f"Foreground app is {pkg}, not {self.app_package}. "
                                     "Call press_back or launch_app.")
        return None

    def _need_approval(self):
        if self.mode != "execute":
            return None
        if self.run_id is None:
            return fail("NOT_APPROVED", "Execute mode: call begin_execution(run_id) first.")
        if self.current_test is None:
            return fail("NOT_APPROVED", "Execute mode: call begin_test(test_id) before acting.")
        return None

    def _count_step(self):
        """Every state-changing action passes here, so it is also the approval choke point."""
        err = self._need_approval()
        if err:
            return err
        if self.steps >= self.step_limit:
            return fail("STEP_LIMIT", f"Step limit {self.step_limit} reached for this phase.")
        self.steps += 1
        return None

    def _resolve(self, eid):
        if eid not in self.locators:
            return None, fail("UNKNOWN_ELEMENT", f"{eid} is not on the latest screen. Call get_screen.")
        if self.stale:
            return None, fail("STALE_SCREEN", "The screen may have changed since get_screen. Call get_screen.")
        return self.locators[eid], None

    def _find(self, locator):
        from appium.webdriver.common.appiumby import AppiumBy

        by = {"id": AppiumBy.ID, "accessibility id": AppiumBy.ACCESSIBILITY_ID, "xpath": AppiumBy.XPATH}
        found = self.driver.find_elements(by[locator["by"]], locator["value"])
        return found[0] if found else None

    def _after_action(self, result, action: str = ""):
        """Mark the screen stale, report if the action left the app, and save step evidence."""
        self.stale = True
        pkg = self._foreground()
        if pkg != self.app_package:
            result["left_app"] = True
            result["foreground"] = pkg
        result["steps_used"] = self.steps
        return self._auto_evidence(result, action, with_screen=True)

    def _auto_evidence(self, result, action: str, with_screen: bool = False):
        """Execute mode, inside a test: every step leaves a masked screenshot (FR-14), saved by the server so
        evidence never depends on the model asking for it. After an action the new screen is attached too,
        so the next step needs no separate get_screen call (about 3 model calls per step -> 1)."""
        if self.mode == "execute" and self.current_test and action:
            shot = self.screenshot(f"{self.current_test}_s{self.shot_no + 1:02d}_{action}")
            if shot.get("ok"):
                result["screenshot"] = shot["path"]
            if with_screen and not result.get("left_app"):
                screen = self.get_screen()
                if screen.get("ok"):
                    result["screen"] = {"activity": screen["activity"], "elements": screen["elements"]}
        return result

    def _guarded(self, eid=None, count=True):
        """Run the common guards. Returns (locator, error)."""
        err = self._need_session() or self._need_app()
        if err:
            return None, err
        locator = None
        if eid is not None:
            locator, err = self._resolve(eid)
            if err:
                return None, err
        if count:
            err = self._count_step()
            if err:
                return None, err
        return locator, None

    # ---------- tools ----------
    # ---------- execution (execute mode only) ----------
    def _results_file(self):
        return self.runs_dir / self.run_id / "results.json"

    def _load_file(self, run_id):
        f = self.runs_dir / run_id / "results.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def _load_results(self, run_id):
        return self._load_file(run_id).get("tests", {})

    def _save_results(self):
        self._results_file().write_text(json.dumps(
            {"run_id": self.run_id, "tests": self.results, "history": self.history}, indent=2), encoding="utf-8")

    @safe
    def begin_execution(self, run_id: str, select: str = "all", rerun: bool = False):
        if self.mode != "execute":
            return fail("WRONG_MODE", "begin_execution is only available when the server runs with --execute.")
        tests, err = load_approved(self.runs_dir, run_id)
        if err:
            return fail(*err)
        previous = self._load_results(run_id)
        ids, added, err = select_tests(tests, select, previous)
        if err:
            return fail(*err)
        wiping = [tid for tid in (previous if (select or "all").strip().lower() == "all" else ids) if tid in previous]
        if wiping and not rerun:
            # A follow-up chat message reaches the executor directly; without this it silently re-ran
            # everything and overwrote finished results (seen 25 Oct).
            summary = {tid: previous[tid].get("status") for tid in previous}
            return {"ok": False, "error": "ALREADY_EXECUTED",
                    "message": f"{run_id} already has results {summary}. Re-running overwrites them. Call again "
                               "with rerun=true ONLY if the user explicitly asked to run again.",
                    "results": summary}
        # Overwrite: "all" wipes every old result; a subset wipes only the re-run tests' results and
        # evidence, so the report still has the latest result of every test.
        evidence = self.runs_dir / run_id / "evidence"
        if (select or "all").strip().lower() == "all":
            shutil.rmtree(evidence, ignore_errors=True)
            previous = {}
        for tid in ids:
            shutil.rmtree(evidence / tid, ignore_errors=True)
            previous.pop(tid, None)
        self.run_id, self.current_test, self.last_status = run_id, None, None
        self.history = self._load_file(run_id).get("history", {})  # survives re-runs: "same verdict in 3 runs"
        self.tests = {t["id"]: t for t in tests}
        self.selected, self.results = ids, previous
        self._save_results()
        log("execution approved for", run_id, "selected:", ids)
        # The Executor gets the test steps ONLY from here, i.e. from the hash-verified file.
        return {"ok": True, "run_id": run_id, "selected": ids, "added_for_dependency": added,
                "tests": [self.tests[tid] for tid in ids],
                "next": "Call begin_test for each selected id, in this order."}

    @safe
    def begin_test(self, test_id: str):
        if self.mode != "execute" or self.run_id is None:
            return fail("NOT_APPROVED", "Call begin_execution(run_id) first (execute mode only).")
        tests, err = load_approved(self.runs_dir, self.run_id)  # re-check: file may have been edited mid-run
        if err:
            self.run_id, self.current_test = None, None
            return fail(*err)
        if test_id not in self.selected:
            return fail("NOT_APPROVED", f"{test_id} is not selected in this execution: {self.selected}.")
        if self.current_test is not None:  # previous test never called end_test
            self._record("incomplete", "Test was not ended before the next one started.")
        self._ensure_driver()
        fresh = self.tests[test_id].get("fresh_start", True) is not False
        result = {"ok": True, "test_id": test_id, "fresh_start": fresh, "step_limit": self.step_limit}
        if fresh:
            self._restart(clear_data=bool(self.cfg.get("reset_clears_data", True)))
        else:
            self._new_phase()
            if self.last_status != "pass":
                result["warning"] = (f"fresh_start is false but the previous test ended '{self.last_status}'; "
                                     "the starting state may be wrong.")
        self.current_test = test_id
        self.run_dir = self.runs_dir / self.run_id / "evidence" / test_id
        self.shot_no, self.evidence, self.step_log = 0, [], []
        self.test_started = time.strftime("%Y-%m-%dT%H:%M:%S")
        screen = self.get_screen()  # starting screen, so step 1 needs no get_screen call
        if screen.get("ok"):
            result["screen"] = {"activity": screen["activity"], "elements": screen["elements"]}
        return result

    @safe
    def end_test(self, status: str, actual: str = ""):
        if self.current_test is None:
            return fail("NOT_APPROVED", "No test in progress. Call begin_test first.")
        if status not in ("pass", "fail", "blocked"):
            return fail("BAD_ARGUMENT", "status must be pass, fail or blocked.")
        test_id = self.current_test
        self._record(status, actual)
        remaining = [t for t in self.selected if t not in self.results]
        return {"ok": True, "test_id": test_id, "status": status, "remaining": remaining}

    def _record(self, status, actual):
        finished = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.results[self.current_test] = {
            "status": status, "actual": _scrub(actual)[:1000], "steps_used": self.steps,
            "evidence": self.evidence, "steps": self.step_log, "started_at": self.test_started,
            "finished_at": finished}
        self.history.setdefault(self.current_test, []).append({"status": status, "at": finished})
        self._save_results()
        self.last_status, self.current_test = status, None

    def _ensure_driver(self):
        """Create the Appium session, or replace it if another process ended it."""
        if self.driver is not None:
            try:
                self.driver.current_package
                return
            except Exception:  # noqa: BLE001 - dead session, reconnect below
                log("Appium session lost; reconnecting")
        log("starting Appium session")
        self.driver = self._driver_factory()

    def _restart(self, clear_data=False):
        """Stop the app and start its main activity, so every phase begins on the home screen.

        Without the stop, a no-reset session only brings the old task (and its back stack) to the front.
        activate_app right after clearApp can leave the launcher in front, so start the activity explicitly.
        """
        self.driver.terminate_app(self.app_package)
        if clear_data:
            self.driver.execute_script("mobile: clearApp", {"appId": self.app_package})
        activity = self.cfg["app_activity"]
        if activity.startswith("."):
            activity = self.app_package + activity
        self.driver.execute_script("mobile: startActivity", {"component": f"{self.app_package}/{activity}"})
        time.sleep(1)
        self._new_phase()

    @safe
    def launch_app(self):
        self._ensure_driver()
        self._restart()
        return {"ok": True, "package": self._foreground(), "activity": self.driver.current_activity,
                "step_limit": self.step_limit}

    @safe
    def reset_app(self):
        err = self._need_session()
        if err:
            return err
        clear = bool(self.cfg.get("reset_clears_data", True))
        self._restart(clear_data=clear)
        return {"ok": True, "package": self._foreground(), "activity": self.driver.current_activity,
                "data_cleared": clear}

    @safe
    def get_screen(self):
        err = self._need_session()
        if err:
            return err
        redact = {v: "{{" + k + "}}" for k, v in _secrets().items()}
        s = parse_screen(self.driver.page_source, MAX_ELEMENTS, redact)
        self.locators = s["locators"]
        self.screen_bounds = {e["eid"]: e["bounds"] for e in s["elements"]}
        self.screen_labels = {e["eid"]: e.get("label") or e.get("text") or e.get("desc", "") for e in s["elements"]}
        self.stale = False
        pkg = self._foreground()
        result = {"ok": True, "package": pkg, "activity": self.driver.current_activity,
                  "in_app": pkg == self.app_package, "total": s["total"],
                  "shown": len(s["elements"]), "elements": s["elements"]}
        interactive = sum(1 for e in s["elements"]
                          if e.get("clickable") or e.get("editable") or e.get("scrollable") or "checked" in e)
        if interactive < FEW_ELEMENTS:
            # R4: text is not enough here (canvas, WebView, game...). The agent may take ONE screenshot
            # and look at it (vision fallback); otherwise agents stay text-only.
            result["few_elements"] = True
        return result

    @logged("tap")
    @safe
    def tap(self, eid: str):
        locator, err = self._guarded(eid)
        if err:
            return err
        el = self._find(locator)
        if el is None:
            self.stale = True
            return fail("ELEMENT_NOT_FOUND", f"{eid} is no longer on screen. Call get_screen.")
        el.click()
        time.sleep(0.5)  # let the transition start before the next page_source
        return self._after_action({"ok": True, "tapped": eid}, "tap")

    @logged("type")
    @safe
    def type_text(self, eid: str, text: str):
        locator, err = self._guarded(eid)
        if err:
            return err
        secrets = _secrets()
        missing = [m for m in _PLACEHOLDER.findall(text) if m not in secrets]
        unknown = [m for m in _PLACEHOLDER.findall(text) if m not in SECRET_VARS]
        if unknown:
            return fail("BAD_ARGUMENT", f"Unknown placeholder(s): {unknown}. Use {list(SECRET_VARS)}.")
        if missing:
            return fail("SECRET_MISSING", f"Profile does not define a value for {missing}.")
        real = _PLACEHOLDER.sub(lambda m: secrets[m.group(1)], text)
        el = self._find(locator)
        if el is None:
            self.stale = True
            return fail("ELEMENT_NOT_FOUND", f"{eid} is no longer on screen. Call get_screen.")
        el.clear()
        el.send_keys(real)
        if real != text:
            self.masked.add((locator["by"], locator["value"]))
        # No hide_keyboard(): on UiAutomator2 it can send BACK, which closes dialogs. The agent can
        # call press_back itself if the keyboard covers something.
        result = self._after_action({"ok": True, "typed_into": eid, "text": text}, "type")
        if not result.get("left_app"):
            self.stale = False  # typing does not change the screen, so the eids stay valid
        return result

    @logged("scroll")
    @safe
    def scroll(self, direction: str = "down", eid: str | None = None):
        if direction not in ("up", "down", "left", "right"):
            return fail("BAD_ARGUMENT", "direction must be up, down, left or right.")
        _, err = self._guarded(eid)
        if err:
            return err
        if eid is not None:
            x1, y1, x2, y2 = self.screen_bounds[eid]
        else:
            size = self.driver.get_window_size()
            x1, y1, x2, y2 = 0, int(size["height"] * 0.2), size["width"], int(size["height"] * 0.8)
        more = self.driver.execute_script("mobile: scrollGesture", {
            "left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1,
            "direction": direction, "percent": 0.7})
        return self._after_action({"ok": True, "direction": direction, "can_scroll_more": bool(more)}, "scroll")

    @logged("back")
    @safe
    def press_back(self):
        err = self._need_session() or self._count_step()
        if err:
            return err
        self.driver.back()
        time.sleep(0.5)
        return self._after_action({"ok": True}, "back")

    @logged("assert")
    @safe
    def assert_visible(self, text: str):
        """Checks whether any element's text or content-desc contains `text` (case-insensitive)."""
        _, err = self._guarded(count=False)
        if err:
            return err
        redact = {v: "{{" + k + "}}" for k, v in _secrets().items()}
        s = parse_screen(self.driver.page_source, max_elements=10_000, redact=redact)
        needle = text.lower()
        hits = [e for e in s["elements"]
                if needle in " ".join([e.get("text", ""), e.get("desc", ""), e.get("label", "")]).lower()]
        result = {"ok": True, "text": text, "visible": bool(hits),
                  "matches": [e.get("text") or e.get("desc") or e.get("label") for e in hits[:5]]}
        return self._auto_evidence(result, "assert" if hits else "assert_fail")

    @safe
    def screenshot(self, name: str = "step"):
        err = self._need_session()
        if err:
            return err
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.shot_no += 1
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name)[:40] or "step"
        path = self.run_dir / f"{self.shot_no:03d}_{safe_name}.png"
        # R1: capture to memory, read the LIVE page_source for current bounds, mask, and only then write.
        # An unmasked image never touches disk.
        png = self.driver.get_screenshot_as_png()
        img, masked = self._mask(png, self.driver.page_source)
        img.save(path)
        shown = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path).replace("\\", "/")
        self.evidence.append(shown)
        return {"ok": True, "path": shown, "masked_fields": masked}

    def _mask(self, png: bytes, page_source: str):
        """Black out sensitive fields using bounds from the live page_source. Returns (image, count).

        Sensitive = password="true", resource-id/hint naming an OTP/PIN/password field, text equal to a
        secret value, or a field that type_text filled from a placeholder.
        """
        import io
        import xml.etree.ElementTree as ET
        from PIL import Image, ImageDraw

        root = ET.fromstring(page_source.encode("utf-8"))
        secret_values = set(_secrets().values())
        boxes = []
        for node in root.iter():
            secret_field = node.get("text") in secret_values or any(
                (by == "id" and node.get("resource-id") == v)
                or (by == "accessibility id" and node.get("content-desc") == v)
                or (by == "xpath" and v == f'//*[@bounds="{node.get("bounds")}"]')
                for by, v in self.masked)
            if node.get("password") == "true" or secret_field or _sensitive_name(node):
                m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
                if m:
                    boxes.append([int(g) for g in m.groups()])
        img = Image.open(io.BytesIO(png)).convert("RGB")
        draw = ImageDraw.Draw(img)
        for box in boxes:
            draw.rectangle(box, fill="black")
        return img, len(boxes)

    def close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:  # noqa: BLE001
                pass
            self.driver = None
