"""Model-call callbacks (R4, NFR-PE-02 / DD-06).

pace_model_calls  - at least QA_MIN_TURN_SECONDS (default 4) between ANY two model calls in this process,
                    so a free-tier key (~15 requests/minute) is not exhausted mid-demo.
track_screens     - remembers whether the last get_screen had few interactive elements, and if the agent
                    then took a screenshot, queues that (already masked) PNG for one vision look.
attach_vision     - adds the queued screenshot to the next model request, once. Agents are otherwise text-only.
quota_error       - turns a 429 into a clear message instead of retrying; a DAILY limit also blocks every
                    later call in this process, so a SequentialAgent does not keep hitting the wall.
count_usage       - M7: requests and tokens per agent in session state["usage"], plus one JSON line per call
                    in runs/_usage/<session_id>.jsonl for evals/metrics.py.
"""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

ROOT = Path(__file__).resolve().parent.parent
MIN_GAP = float(os.getenv("QA_MIN_TURN_SECONDS", "4"))
USAGE_DIR = ROOT / "runs" / "_usage"

_lock = asyncio.Lock()
_last_call = 0.0
_daily_block = None  # message once a per-day quota is exhausted; cleared by restarting adk web


def text_response(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


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
    if _daily_block:
        return text_response(_daily_block)  # skip the API call: it would only fail again
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


def quota_kind(error) -> str | None:
    """'day' or 'minute' for a 429 quota error, else None. Google names the quota in details[].quotaId."""
    if not isinstance(error, errors.APIError) or error.code != 429:
        return None
    text = json.dumps(error.details) if error.details else str(error)
    return "day" if "PerDay" in text else "minute"


def quota_error(callback_context, llm_request, error):
    global _daily_block
    kind = quota_kind(error)
    if kind is None:
        return None  # not a quota problem: let ADK raise it
    model = llm_request.model or os.getenv("QA_MODEL", "the model")
    if kind == "day":
        _daily_block = (
            f"QUOTA_DAILY: the free-tier DAILY request limit for {model} is used up. Nothing more will run "
            "in this session. Fix: set QA_MODEL in .env to a model with quota left (python "
            "scripts/probe_models.py), or enable billing, then restart adk web.")
        return text_response(_daily_block)
    return text_response(
        f"QUOTA_MINUTE: {model} hit its per-minute request limit. Wait about 60 seconds and send the "
        "same message again (or raise QA_MIN_TURN_SECONDS in .env).")


def count_usage(callback_context, llm_response):
    meta = llm_response.usage_metadata
    if meta is None or llm_response.partial:
        return None
    tokens = {"prompt": meta.prompt_token_count or 0, "output": meta.candidates_token_count or 0,
              "thoughts": meta.thoughts_token_count or 0, "total": meta.total_token_count or 0}
    agent = callback_context.agent_name
    usage = dict(callback_context.state.get("usage") or {"requests": 0, "by_agent": {}})
    usage["requests"] += 1
    for k, v in tokens.items():
        usage[k] = usage.get(k, 0) + v
    per_agent = dict(usage["by_agent"].get(agent) or {"requests": 0, "total": 0})
    per_agent["requests"] += 1
    per_agent["total"] += tokens["total"]
    usage["by_agent"] = {**usage["by_agent"], agent: per_agent}
    callback_context.state["usage"] = usage

    session_id = getattr(callback_context.session, "id", None) or "unknown"
    USAGE_DIR.mkdir(parents=True, exist_ok=True)
    line = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "agent": agent,
            "model": llm_response.model_version or os.getenv("QA_MODEL", ""), **tokens}
    with (USAGE_DIR / f"{session_id}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return None  # keep the response unchanged
