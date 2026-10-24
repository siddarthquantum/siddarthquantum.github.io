"""Model-call callbacks (R4, NFR-PE-02 / DD-06).

pace_model_calls  - at least QA_MIN_TURN_SECONDS (default 4) between ANY two model calls in this process,
                    so a free-tier key (~15 requests/minute) is not exhausted mid-demo.
track_screens     - remembers whether the last get_screen had few interactive elements, and if the agent
                    then took a screenshot, queues that (already masked) PNG for one vision look.
attach_vision     - adds the queued screenshot to the next model request, once. Agents are otherwise text-only.
"""
import asyncio
import json
import os
import time
from pathlib import Path

from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
MIN_GAP = float(os.getenv("QA_MIN_TURN_SECONDS", "4"))

_lock = asyncio.Lock()
_last_call = 0.0


def tool_result(tool_response) -> dict:
    """MCP tool results arrive as {"content": [{"type": "text", "text": "<json>"}]}; return the json."""
    if isinstance(tool_response, dict) and "ok" in tool_response:
        return tool_response
    try:
        return json.loads(tool_response["content"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        return {}


async def pace_model_calls(callback_context, llm_request):
    global _last_call
    async with _lock:
        wait = _last_call + MIN_GAP - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
    attach_vision(callback_context, llm_request)
    return None  # continue with the real model call


def track_screens(tool, args, tool_context, tool_response):
    result = tool_result(tool_response)
    if tool.name == "get_screen" and result.get("ok"):
        tool_context.state["temp:few_elements"] = bool(result.get("few_elements"))
    elif tool.name == "screenshot" and result.get("ok") and tool_context.state.get("temp:few_elements"):
        tool_context.state["temp:vision_png"] = result["path"]
    return None  # keep the tool result unchanged


def attach_vision(callback_context, llm_request):
    path = callback_context.state.get("temp:vision_png")
    if not path:
        return
    callback_context.state["temp:vision_png"] = None
    png = Path(path) if Path(path).is_absolute() else ROOT / path
    if not png.exists():
        return
    llm_request.contents.append(types.Content(role="user", parts=[
        types.Part(text="Vision fallback: the screen had too few elements in text form. Here is the "
                        "screenshot (sensitive fields are blacked out). Use it only to understand this screen."),
        types.Part.from_bytes(data=png.read_bytes(), mime_type="image/png"),
    ]))
