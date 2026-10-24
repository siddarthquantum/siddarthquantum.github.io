"""Step 4c/4d: the MCP server's tool list per mode, error contract, and a clean stdout (R3)."""
import json
import logging
import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

from mcp_server import server

ROOT = Path(__file__).resolve().parent.parent
SPEC_TOOLS = {"launch_app", "get_screen", "tap", "type_text", "scroll", "press_back",
              "screenshot", "assert_visible", "reset_app"}


def test_server_lists_spec_tools_and_errors_without_session():
    async def run():
        async with Client(server.mcp) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            result = await client.call_tool("tap", {"eid": "e01"})
            return names, json.loads(result.content[0].text)

    names, tap = anyio.run(run)
    assert names == SPEC_TOOLS  # explore mode: no begin_execution / begin_test
    assert tap["ok"] is False and tap["error"] == "NO_SESSION"


def test_logging_goes_to_stderr():
    streams = [h.stream for h in logging.getLogger().handlers if hasattr(h, "stream")]
    assert sys.stdout not in streams


def test_execute_mode_over_real_stdio():
    """Spawns the server like ADK will. A stray print to stdout would break this JSON-RPC session."""
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server", "--execute"],
                                   cwd=str(ROOT))

    async def run():
        async with Client(params, read_timeout_seconds=60) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            gate = await client.call_tool("begin_execution", {"run_id": "no_such_run"})
            return names, json.loads(gate.content[0].text)

    names, gate = anyio.run(run)
    assert names == SPEC_TOOLS | {"begin_execution", "begin_test", "end_test"}
    assert gate["error"] == "NOT_APPROVED"
