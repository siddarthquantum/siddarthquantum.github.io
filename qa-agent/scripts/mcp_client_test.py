"""Step 4b check: start the MCP server as a subprocess (like ADK will) and drive ApiDemos through it.
Run with Appium already started:  python scripts/mcp_client_test.py
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent


async def call(client, name, args=None):
    result = await client.call_tool(name, args or {})
    # Tools annotated "-> dict" send their result as JSON text in content[0], not structured_content.
    data = result.structured_content or json.loads(result.content[0].text)
    brief = {k: v for k, v in data.items() if k != "elements"}
    print(f"{name}({args or ''}) -> {json.dumps(brief)}")
    return data


async def main():
    server = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT))
    async with Client(server, read_timeout_seconds=180) as client:
        tools = await client.list_tools()
        print("Tools:", [t.name for t in tools.tools])

        await call(client, "launch_app")
        screen = await call(client, "get_screen")
        for e in screen["elements"][:5]:
            print("   ", e)

        pref = next(e["eid"] for e in screen["elements"] if e.get("text") == "Preference")
        await call(client, "tap", {"eid": pref})
        await call(client, "tap", {"eid": pref})  # guard: screen is stale now -> STALE_SCREEN
        screen = await call(client, "get_screen")
        print("    first items:", [e.get("text") for e in screen["elements"][:4]])
        await call(client, "screenshot", {"name": "preference_list"})
        await call(client, "assert_visible", {"text": "Preference dependencies"})
        await call(client, "press_back")
        await call(client, "get_screen")
        await call(client, "assert_visible", {"text": "Animation"})
        await call(client, "tap", {"eid": "e99"})  # guard: UNKNOWN_ELEMENT


if __name__ == "__main__":
    asyncio.run(main())
