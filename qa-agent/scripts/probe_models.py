"""Step 0: one tiny call per model to see which ones this API key can use right now.

    python scripts/probe_models.py                      # default candidates
    python scripts/probe_models.py gemini-3.5-flash     # or name models

Prints status (OK / NOT_FOUND / QUOTA_DAILY / QUOTA_MINUTE / ERROR), latency and tokens per model.
Each probe costs ONE request of that model's daily quota. The key is read from .env and never printed.
The exact free-tier limits per model are shown in AI Studio > Usage & limits; the API does not report them.
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from qa_agent.callbacks import quota_kind  # noqa: E402

DEFAULT = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-flash-latest"]


def probe(client, model: str) -> tuple[str, str]:
    start = time.monotonic()
    try:
        resp = client.models.generate_content(model=model, contents="Reply with the single word OK.")
    except errors.APIError as e:
        kind = quota_kind(e)
        if kind:
            return ("QUOTA_DAILY" if kind == "day" else "QUOTA_MINUTE"), "limit reached for now"
        if e.code == 404:
            return "NOT_FOUND", "not available for this key"
        return "ERROR", f"HTTP {e.code} {e.status or ''}".strip()
    ms = int((time.monotonic() - start) * 1000)
    u = resp.usage_metadata
    tokens = f"{u.prompt_token_count or 0} in / {u.candidates_token_count or 0} out" if u else "n/a"
    return "OK", f"{ms} ms, {tokens}, said {(resp.text or '').strip()[:12]!r}"


def main():
    load_dotenv(ROOT / ".env")
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("GOOGLE_API_KEY is not set in .env")
    client = genai.Client()
    models = sys.argv[1:] or DEFAULT
    width = max(len(m) for m in models)
    for m in models:
        status, detail = probe(client, m)
        print(f"{m:<{width}}  {status:<13} {detail}")


if __name__ == "__main__":
    main()
