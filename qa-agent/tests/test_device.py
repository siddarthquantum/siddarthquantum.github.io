"""Step 4c: device.py guards, secret handling and error contract, using a fake Appium driver."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from mcp_server.device import Device

APP = "io.appium.android.apis"
HOME = (Path(__file__).parent / "fixtures" / "apidemos_home.xml").read_text(encoding="utf-8")
LOGIN = (
    '<hierarchy class="hierarchy">'
    f'<android.widget.EditText class="android.widget.EditText" package="{APP}" resource-id="{APP}:id/user" '
    'text="" bounds="[0,0][100,40]" />'
    f'<android.widget.EditText class="android.widget.EditText" package="{APP}" resource-id="{APP}:id/pw" '
    'password="true" text="" bounds="[0,50][100,90]" />'
    f'<android.widget.Button class="android.widget.Button" package="{APP}" resource-id="{APP}:id/go" '
    'clickable="true" text="Login" bounds="[0,100][100,140]" />'
    "</hierarchy>"
)


class FakeElement:
    def __init__(self, driver, value):
        self.driver, self.value = driver, value

    def click(self):
        self.driver.clicks.append(self.value)
        if self.driver.on_click:
            self.driver.on_click(self.driver)

    def clear(self):
        pass

    def send_keys(self, text):
        self.driver.typed.append(text)
        if self.driver.on_type:
            self.driver.on_type(self.driver, text)


class FakeDriver:
    def __init__(self, page_source=HOME):
        self.page_source = page_source
        self.current_package = APP
        self.current_activity = ".ApiDemos"
        self.clicks, self.typed, self.backs = [], [], 0
        self.on_click = self.on_type = None
        self.missing = False
        self.scripts = []

    def find_elements(self, by, value):
        return [] if self.missing else [FakeElement(self, value)]

    def back(self):
        self.backs += 1

    def activate_app(self, pkg):
        self.current_package = pkg

    def terminate_app(self, pkg):
        pass

    def execute_script(self, name, args):
        self.scripts.append(name)
        return True

    def hide_keyboard(self):
        pass

    def get_window_size(self):
        return {"width": 100, "height": 200}

    def get_screenshot_as_png(self):
        # No save_screenshot on purpose: the server must never write an unmasked file (R1).
        buf = io.BytesIO()
        Image.new("RGB", (100, 200), "white").save(buf, "PNG")
        return buf.getvalue()

    def quit(self):
        pass


CFG = {"app_package": APP, "app_activity": ".ApiDemos", "device_name": "fake",
       "appium_url": "", "app_path": "", "step_limit": 3}


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    monkeypatch.setattr("mcp_server.device.time.sleep", lambda s: None)


@pytest.fixture(autouse=True)
def no_real_secrets(monkeypatch):
    for var in ("TEST_USERNAME", "TEST_PASSWORD", "TEST_OTP"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def dev(tmp_path):
    fake = FakeDriver()
    d = Device(dict(CFG), driver_factory=lambda: fake)
    d.run_dir = tmp_path
    d.fake = fake
    return d


def eid_of(screen, text):
    return next(e["eid"] for e in screen["elements"] if e.get("text") == text)


def test_tools_need_a_session_first(dev):
    for result in (dev.get_screen(), dev.tap("e01"), dev.press_back(), dev.screenshot()):
        assert result == {"ok": False, "error": "NO_SESSION", "message": result["message"]}


def test_launch_and_get_screen(dev):
    assert dev.launch_app()["ok"]
    s = dev.get_screen()
    assert s["ok"] and s["in_app"] and s["shown"] == 13
    assert "locators" not in s  # locators stay server-side


def test_tap_uses_server_side_locator(dev):
    dev.launch_app()
    s = dev.get_screen()
    r = dev.tap(eid_of(s, "Animation"))
    assert r["ok"] and r["steps_used"] == 1
    assert dev.fake.clicks == ["Animation"]  # accessibility id, because text1 is shared


def test_stale_screen_after_tap_and_unknown_eid(dev):
    dev.launch_app()
    dev.get_screen()
    dev.tap("e01")
    assert dev.tap("e02")["error"] == "STALE_SCREEN"
    dev.get_screen()
    assert dev.tap("e99")["error"] == "UNKNOWN_ELEMENT"


def test_wrong_app_guard(dev):
    dev.launch_app()
    dev.get_screen()
    dev.fake.current_package = "com.android.chrome"
    r = dev.tap("e01")
    assert r["error"] == "WRONG_APP" and "com.android.chrome" in r["message"]
    assert dev.press_back()["ok"]  # back is still allowed, to get home


def test_left_app_reported_after_action(dev):
    dev.launch_app()
    dev.get_screen()
    dev.fake.on_click = lambda d: setattr(d, "current_package", "com.android.settings")
    r = dev.tap("e01")
    assert r["ok"] and r["left_app"] and r["foreground"] == "com.android.settings"


def test_step_limit_per_phase(dev):
    dev.launch_app()
    for _ in range(3):
        dev.get_screen()
        assert dev.tap("e01")["ok"]
    dev.get_screen()
    assert dev.tap("e01")["error"] == "STEP_LIMIT"
    dev.launch_app()  # new phase resets the counter
    dev.get_screen()
    assert dev.tap("e01")["ok"]


def test_element_not_found(dev):
    dev.launch_app()
    dev.get_screen()
    dev.fake.missing = True
    assert dev.tap("e01")["error"] == "ELEMENT_NOT_FOUND"


def test_secret_placeholder_resolved_only_on_device(dev, monkeypatch):
    monkeypatch.setenv("TEST_USERNAME", "9876543210")
    monkeypatch.setenv("TEST_PASSWORD", "hunter2")
    dev.fake.page_source = LOGIN
    dev.launch_app()
    s = dev.get_screen()
    user, pw = s["elements"][0]["eid"], s["elements"][1]["eid"]

    def fill(d, text):  # the field shows what was typed, like a real EditText
        d.page_source = d.page_source.replace('id/user" text=""', f'id/user" text="{text}"', 1)
    dev.fake.on_type = fill

    r1 = dev.type_text(user, "{{USERNAME}}")
    r2 = dev.type_text(pw, "{{PASSWORD}}")  # no get_screen needed: typing keeps eids valid
    assert r1["ok"] and r2["ok"]
    assert dev.fake.typed == ["9876543210", "hunter2"]
    assert r1["text"] == "{{USERNAME}}"
    after = dev.get_screen()
    assert "9876543210" not in str(after) and "hunter2" not in str(after)
    assert after["elements"][0]["text"] == "{{USERNAME}}"


def test_secret_missing_and_unknown_placeholder(dev):
    dev.fake.page_source = LOGIN
    dev.launch_app()
    dev.get_screen()
    assert dev.type_text("e01", "{{PASSWORD}}")["error"] == "SECRET_MISSING"
    assert dev.type_text("e01", "{{PIN}}")["error"] == "BAD_ARGUMENT"
    assert dev.fake.typed == []


def test_exceptions_become_errors_with_secrets_scrubbed(dev, monkeypatch):
    monkeypatch.setenv("TEST_PASSWORD", "hunter2")
    dev.fake.page_source = LOGIN
    dev.launch_app()
    dev.get_screen()

    def boom(d, text):
        raise RuntimeError(f"could not type {text}")
    dev.fake.on_type = boom
    r = dev.type_text("e02", "{{PASSWORD}}")
    assert r["ok"] is False and r["error"] == "APPIUM_ERROR"
    assert "hunter2" not in r["message"] and "{{PASSWORD}}" in r["message"]


def test_screenshot_masks_password_field(dev):
    dev.fake.page_source = LOGIN
    dev.launch_app()
    r = dev.screenshot("login")
    assert r["ok"] and r["masked_fields"] == 1
    img = Image.open(r["path"])
    assert img.getpixel((50, 70)) == (0, 0, 0)        # inside the password field
    assert img.getpixel((50, 20)) == (255, 255, 255)  # username field untouched


def test_scroll_and_bad_direction(dev):
    dev.launch_app()
    dev.get_screen()
    assert dev.scroll("sideways")["error"] == "BAD_ARGUMENT"
    assert dev.scroll("down")["can_scroll_more"] is True


def test_assert_visible(dev):
    dev.launch_app()
    assert dev.assert_visible("animation")["visible"] is True
    assert dev.assert_visible("Bluetooth")["visible"] is False


# ---------- R1: masking from the live screen ----------
OTP_SCREEN = (
    '<hierarchy class="hierarchy">'
    f'<android.widget.EditText class="android.widget.EditText" package="{APP}" resource-id="{APP}:id/et_otp" '
    'text="123456" bounds="[0,0][100,40]" />'
    f'<android.widget.EditText class="android.widget.EditText" package="{APP}" resource-id="{APP}:id/mpinView" '
    'text="" bounds="[0,50][100,90]" />'
    f'<android.widget.Spinner class="android.widget.Spinner" package="{APP}" resource-id="{APP}:id/spinner" '
    'bounds="[0,100][100,140]" />'
    f'<android.widget.EditText class="android.widget.EditText" package="{APP}" resource-id="{APP}:id/country_code" '
    'text="+91" bounds="[0,150][100,190]" />'
    "</hierarchy>"
)


def test_otp_and_pin_fields_masked_without_password_flag(dev):
    dev.fake.page_source = OTP_SCREEN
    dev.launch_app()
    r = dev.screenshot("otp")
    assert r["ok"] and r["masked_fields"] == 2
    img = Image.open(r["path"])
    assert img.getpixel((50, 20)) == (0, 0, 0)         # et_otp
    assert img.getpixel((50, 70)) == (0, 0, 0)         # mpinView (camelCase split)
    assert img.getpixel((50, 120)) == (255, 255, 255)  # spinner is not "pin"
    assert img.getpixel((50, 170)) == (255, 255, 255)  # country_code is not masked


def test_mask_uses_live_bounds_not_cached(dev):
    dev.fake.page_source = LOGIN
    dev.launch_app()
    dev.get_screen()
    # keyboard pops up / layout shifts: the password field moves down after get_screen
    dev.fake.page_source = LOGIN.replace("[0,50][100,90]", "[0,150][100,190]")
    img = Image.open(dev.screenshot("shifted")["path"])
    assert img.getpixel((50, 170)) == (0, 0, 0)
    assert img.getpixel((50, 70)) == (255, 255, 255)


# ---------- D2: reset clears app data unless the profile sets RESET_CLEAR_DATA=false ----------
def test_reset_app_clears_data_by_default(dev):
    dev.launch_app()
    r = dev.reset_app()
    assert r["ok"] and r["data_cleared"] is True
    assert "mobile: clearApp" in dev.fake.scripts


def test_reset_app_keeps_data_when_configured(dev):
    dev.cfg["reset_clears_data"] = False
    dev.launch_app()
    assert dev.reset_app()["data_cleared"] is False
    assert "mobile: clearApp" not in dev.fake.scripts


# ---------- R2: approval gate in execute mode ----------
def approve(runs, run_id, tests):
    from mcp_server.approval import sha256_file
    d = runs / run_id
    d.mkdir(parents=True)
    (d / "approved_tests.json").write_text(json.dumps({"tests": tests}), encoding="utf-8")
    (d / "approval.json").write_text(json.dumps({"sha256": sha256_file(d / "approved_tests.json")}),
                                     encoding="utf-8")
    return d


@pytest.fixture
def exe(tmp_path):
    fake = FakeDriver()
    d = Device(dict(CFG), driver_factory=lambda: fake, mode="execute")
    d.runs_dir = tmp_path / "runs"
    d.fake = fake
    return d


def test_execute_mode_blocks_actions_until_approved(exe):
    exe.launch_app()
    exe.get_screen()  # reading is allowed
    assert exe.tap("e01")["error"] == "NOT_APPROVED"
    assert exe.press_back()["error"] == "NOT_APPROVED"
    assert exe.begin_execution("run1")["error"] == "NOT_APPROVED"  # no files yet
    assert exe.fake.clicks == [] and exe.fake.backs == 0


def test_approved_run_allows_only_approved_tests(exe):
    approve(exe.runs_dir, "run1", [{"id": "TC01"}, {"id": "TC02"}])
    exe.launch_app()
    assert exe.begin_execution("run1")["selected"] == ["TC01", "TC02"]
    exe.get_screen()
    assert exe.tap("e01")["error"] == "NOT_APPROVED"  # no test started yet
    assert exe.begin_test("TC99")["error"] == "NOT_APPROVED"
    assert exe.begin_test("TC01")["ok"]
    exe.get_screen()
    assert exe.tap("e01")["ok"]


def test_edit_after_approval_is_rejected(exe):
    d = approve(exe.runs_dir, "run1", [{"id": "TC01"}])
    exe.launch_app()
    assert exe.begin_execution("run1")["ok"]
    (d / "approved_tests.json").write_text(json.dumps({"tests": [{"id": "TC01"}, {"id": "EVIL"}]}))
    r = exe.begin_test("TC01")
    assert r["error"] == "APPROVAL_INVALID" and "SHA-256" in r["message"]
    exe.get_screen()
    assert exe.tap("e01")["error"] == "NOT_APPROVED"  # gate closed again


def test_run_id_cannot_escape_runs_dir(exe):
    assert exe.begin_execution("../secrets")["error"] == "BAD_ARGUMENT"


def test_explore_mode_has_no_gate_and_rejects_begin_execution(dev):
    assert dev.begin_execution("run1")["error"] == "WRONG_MODE"


# ---------- re-runs: overwrite, selection, fresh_start ----------
CHAIN = [{"id": "TC01"}, {"id": "TC02"}, {"id": "TC03", "fresh_start": False}, {"id": "TC04"}]


def run_all(exe, statuses, select="all"):
    r = exe.begin_execution("run1", select, rerun=True)  # these tests deliberately re-run
    for tid in r["selected"]:
        assert exe.begin_test(tid)["ok"]
        exe.screenshot("step")
        exe.end_test(statuses.get(tid, "pass"), f"{tid} done")
    return r


def results(exe):
    return json.loads((exe.runs_dir / "run1" / "results.json").read_text())["tests"]


def test_end_test_writes_results_with_evidence(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    run_all(exe, {"TC02": "fail"})
    res = results(exe)
    assert {k: v["status"] for k, v in res.items()} == {"TC01": "pass", "TC02": "fail", "TC03": "pass", "TC04": "pass"}
    assert res["TC01"]["evidence"] == [str(exe.runs_dir / "run1/evidence/TC01/001_step.png").replace("\\", "/")]


def test_select_all_overwrites_old_results_and_evidence(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    run_all(exe, {"TC02": "fail"})
    stale = exe.runs_dir / "run1" / "evidence" / "TC09"
    stale.mkdir(parents=True)
    run_all(exe, {})
    assert all(v["status"] == "pass" for v in results(exe).values())
    assert not stale.exists()


def test_select_failed_reruns_only_failed_and_keeps_others(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    run_all(exe, {"TC04": "fail"})
    first_tc01 = results(exe)["TC01"]["finished_at"]
    r = run_all(exe, {}, select="failed")
    assert r["selected"] == ["TC04"] and r["added_for_dependency"] == []
    res = results(exe)
    assert res["TC04"]["status"] == "pass" and res["TC01"]["finished_at"] == first_tc01


def test_select_list_adds_dependency_chain(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    exe.launch_app()
    r = exe.begin_execution("run1", "TC03")
    assert r["selected"] == ["TC02", "TC03"] and r["added_for_dependency"] == ["TC02"]
    assert exe.begin_test("TC01")["error"] == "NOT_APPROVED"  # approved but not selected


def test_select_errors(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    assert exe.begin_execution("run1", "failed")["error"] == "NOTHING_TO_RUN"  # no previous results
    assert exe.begin_execution("run1", "TC01,TC77")["error"] == "NOT_APPROVED"


def test_fresh_start_restarts_and_clears_by_default_but_not_when_false(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    exe.begin_execution("run1", "TC02,TC03")
    exe.begin_test("TC02")
    assert exe.fake.scripts.count("mobile: clearApp") == 1
    exe.end_test("pass")
    r = exe.begin_test("TC03")
    assert r["fresh_start"] is False and "warning" not in r
    assert exe.fake.scripts.count("mobile: clearApp") == 1  # no restart for TC03


def test_dependent_test_warns_if_previous_failed(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    exe.begin_execution("run1", "TC03")
    exe.begin_test("TC02")
    exe.end_test("fail", "login failed")
    assert "warning" in exe.begin_test("TC03")


def test_unfinished_test_recorded_as_incomplete(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    exe.begin_execution("run1")
    exe.begin_test("TC01")
    exe.begin_test("TC02")
    assert results(exe)["TC01"]["status"] == "incomplete"


def test_end_test_validation_and_secret_scrub(exe, monkeypatch):
    monkeypatch.setenv("TEST_PASSWORD", "hunter2")
    approve(exe.runs_dir, "run1", CHAIN)
    exe.begin_execution("run1")
    assert exe.end_test("pass")["error"] == "NOT_APPROVED"
    exe.begin_test("TC01")
    assert exe.end_test("maybe")["error"] == "BAD_ARGUMENT"
    exe.end_test("fail", "error shown for hunter2")
    assert "hunter2" not in json.dumps(results(exe))


def test_launch_app_reports_restart_failure(dev):
    def broken(name, args):
        raise RuntimeError("activity not found")
    dev.launch_app()
    dev.fake.execute_script = broken
    r = dev.launch_app()
    assert r["ok"] is False and r["error"] == "APPIUM_ERROR"


# ---------- Step 5 server additions ----------
def test_session_lost_is_reported_and_launch_reconnects(tmp_path):
    class InvalidSessionIdException(Exception):
        pass

    made = []

    def factory():
        made.append(FakeDriver())
        return made[-1]

    d = Device(dict(CFG), driver_factory=factory)
    d.launch_app()
    d.get_screen()

    def dead(*a, **k):
        raise InvalidSessionIdException("A session is either terminated or not started")
    made[0].find_elements = dead
    assert d.tap("e01")["error"] == "SESSION_LOST"
    assert d.launch_app()["ok"] and len(made) == 2


def test_few_elements_flag(dev):
    dev.fake.page_source = LOGIN  # 2 edit fields + 1 button = 3 interactive -> not few
    dev.launch_app()
    assert "few_elements" not in dev.get_screen()
    dev.fake.page_source = ('<hierarchy class="hierarchy"><android.view.View class="android.view.View" '
                            f'package="{APP}" bounds="[0,0][100,100]" text="Canvas game" /></hierarchy>')
    assert dev.get_screen()["few_elements"] is True


def test_begin_execution_returns_verified_test_content(exe):
    approve(exe.runs_dir, "run1", [{"id": "TC01", "title": "t", "steps": [{"action": "back"}]}])
    r = exe.begin_execution("run1")
    assert r["tests"][0]["steps"] == [{"action": "back"}]


# ---------- 25 Oct optimisation: server-side evidence, screen in results, re-run guard ----------
def test_actions_save_evidence_and_return_the_new_screen(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    exe.begin_execution("run1")
    start = exe.begin_test("TC01")
    assert start["screen"]["elements"]  # step 1 needs no get_screen
    eid = start["screen"]["elements"][0]["eid"]
    r = exe.tap(eid)
    assert r["screenshot"].endswith("_s01_tap.png") and r["screen"]["elements"]
    a = exe.assert_visible("No such text anywhere")
    assert a["visible"] is False and a["screenshot"].endswith("_s02_assert_fail.png") and "screen" not in a
    exe.end_test("fail", "not visible")
    assert len(results(exe)["TC01"]["evidence"]) == 2


def test_explore_mode_saves_no_automatic_evidence(dev):
    dev.launch_app()
    eid = dev.get_screen()["elements"][0]["eid"]
    r = dev.tap(eid)
    assert "screenshot" not in r and "screen" not in r


def test_rerun_needs_explicit_flag(exe):
    approve(exe.runs_dir, "run1", CHAIN)
    run_all(exe, {})
    r = exe.begin_execution("run1")  # e.g. a follow-up chat message reaching the executor
    assert r["error"] == "ALREADY_EXECUTED" and r["results"]["TC01"] == "pass"
    assert results(exe)["TC01"]["status"] == "pass"  # nothing was wiped
    assert exe.begin_execution("run1", rerun=True)["ok"]
