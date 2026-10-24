"""MCP device server (Step 4b/4c): exposes the Device methods as MCP tools over stdio.

Run directly for a manual check:   python -m mcp_server.server [--execute]
ADK agents start it as a subprocess (stdio transport). mcp 2.x: FastMCP is now MCPServer.
  explore mode (default): Explorer / Test Designer.
  --execute: Executor; device actions are blocked until begin_execution + begin_test pass (R2).
"""
import logging
import sys

# R3: stdout carries the JSON-RPC stream. Send all logging and warnings to stderr BEFORE any library
# (mcp, Appium, urllib3, selenium) is imported, so nothing can ever print to stdout.
logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="[%(name)s] %(levelname)s %(message)s")
logging.captureWarnings(True)

import atexit  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mcp.server.mcpserver import MCPServer  # noqa: E402

from mcp_server.config import load_config  # noqa: E402
from mcp_server.device import Device  # noqa: E402

MODE = "execute" if "--execute" in sys.argv else "explore"
cfg = load_config()
device = Device(cfg, mode=MODE)
atexit.register(device.close)

mcp = MCPServer(
    name="sichakra-device",
    instructions=(
        "Android device tools for the app under test. Call launch_app first, then get_screen. "
        "Act on elements by eid from the LATEST get_screen; after tap/scroll/press_back call get_screen again. "
        "For credentials type the placeholders {{USERNAME}}, {{PASSWORD}}, {{OTP}}; never real values."
    ),
)


if MODE == "execute":  # Explorer never even sees these two tools
    @mcp.tool()
    def begin_execution(run_id: str, select: str = "all") -> dict:
        """Verify the human approval of runs/<run_id>/approved_tests.json and choose tests to run.
        select: "all" (default, overwrites old results), "failed" (re-run tests not passed last time),
        or ids like "TC02,TC05". Tests that depend on an earlier test are added automatically."""
        return device.begin_execution(run_id, select)

    @mcp.tool()
    def begin_test(test_id: str) -> dict:
        """Start a selected test case. Restarts the app with clean data unless the test has fresh_start=false.
        Device actions are allowed only inside a test."""
        return device.begin_test(test_id)

    @mcp.tool()
    def end_test(status: str, actual: str = "") -> dict:
        """Finish the current test: status pass, fail or blocked; actual = what was observed."""
        return device.end_test(status, actual)


@mcp.tool()
def launch_app() -> dict:
    """Start (or bring to front) the app under test. Starts a new phase: resets the step counter."""
    return device.launch_app()


@mcp.tool()
def reset_app() -> dict:
    """Close the app, clear its data, and start it fresh (clean state between test cases)."""
    return device.reset_app()


@mcp.tool()
def get_screen() -> dict:
    """List the elements on the current screen. Each has an eid (e01, e02...) used by other tools."""
    return device.get_screen()


@mcp.tool()
def tap(eid: str) -> dict:
    """Tap the element with this eid from the latest get_screen."""
    return device.tap(eid)


@mcp.tool()
def type_text(eid: str, text: str) -> dict:
    """Clear an editable field and type text. Use {{USERNAME}}, {{PASSWORD}}, {{OTP}} for credentials."""
    return device.type_text(eid, text)


@mcp.tool()
def scroll(direction: str = "down", eid: str | None = None) -> dict:
    """Scroll the screen (or the scrollable element eid) up, down, left or right."""
    return device.scroll(direction, eid)


@mcp.tool()
def press_back() -> dict:
    """Press the Android back button."""
    return device.press_back()


@mcp.tool()
def screenshot(name: str = "step") -> dict:
    """Save a screenshot as evidence (password and credential fields are blacked out). Returns its path."""
    return device.screenshot(name)


@mcp.tool()
def assert_visible(text: str) -> dict:
    """Check whether text appears on the current screen. Returns visible true/false."""
    return device.assert_visible(text)


if __name__ == "__main__":
    mcp.run()  # stdio transport
