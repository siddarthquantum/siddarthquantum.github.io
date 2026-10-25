"""Confidence per verdict, computed from recorded evidence - never asked from the model (Step 6).

    score = text match + stability + locator + no retries        (max 1.0)

    text match   0.4  every deciding assert matched exactly (pass) / the expected text was absent (fail)
                 0.2  pass, but at least one assert matched only as a substring (fuzzy)
    stability    0.3  same verdict in the last 3 executions; 0.15 if the last 2 agree (our choice)
    locator      0.2  every element found by resource-id or accessibility id
                 0.15 weakest was visible text (our choice: between ids and coordinates)
                 0.05 weakest was coordinates (bounds)
    no retries   0.1  no step returned an error (stale screen, element not found, ...)

    High >= 0.8, Medium >= 0.5, Low < 0.5. A blocked test scores 0 for text match.
"""

WEIGHTS = {"exact": 0.4, "fuzzy": 0.2, "stable3": 0.3, "stable2": 0.15,
           "id": 0.2, "text": 0.15, "coordinates": 0.05, "no_retries": 0.1}
LOCATOR_SCORE = {"resource-id": WEIGHTS["id"], "accessibility-id": WEIGHTS["id"],
                 "text": WEIGHTS["text"], "coordinates": WEIGHTS["coordinates"]}


def level(score: float) -> str:
    return "High" if score >= 0.8 else "Medium" if score >= 0.5 else "Low"


def score_test(result: dict, history: list[dict] | None = None) -> dict:
    """result: one entry of results.json "tests"; history: that test's verdicts across executions."""
    status, steps = result.get("status"), result.get("steps")
    parts, notes = {}, []
    if steps is None:  # results written before the step log existed (before 25 Oct evening)
        notes.append("no step log in this run: text, locator and retry evidence unavailable")
        steps = []

    asserts = [s for s in steps if s.get("action") == "assert" and s.get("ok")]
    if status == "pass" and asserts:
        parts["text match"] = WEIGHTS["exact"] if all(s.get("exact") for s in asserts) else WEIGHTS["fuzzy"]
    elif status == "fail" and any(not s.get("visible") for s in asserts):
        parts["text match"] = WEIGHTS["exact"]  # the expected text was clearly not on screen
    else:
        parts["text match"] = 0.0

    verdicts = [h.get("status") for h in (history or [])]
    if len(verdicts) >= 3 and len(set(verdicts[-3:])) == 1 and verdicts[-1] == status:
        parts["stability"] = WEIGHTS["stable3"]
    elif len(verdicts) >= 2 and len(set(verdicts[-2:])) == 1 and verdicts[-1] == status:
        parts["stability"] = WEIGHTS["stable2"]
    else:
        parts["stability"] = 0.0
        notes.append(f"{len(verdicts)} execution(s) recorded; 3 matching runs add 0.3")

    kinds = [s.get("locator") for s in steps if s.get("action") in ("tap", "type") and s.get("locator")]
    if kinds:
        parts["locator"] = min(LOCATOR_SCORE.get(k, 0.0) for k in kinds)
    else:
        parts["locator"] = WEIGHTS["id"] if steps else 0.0  # assert-only test: nothing was located by guess

    parts["no retries"] = WEIGHTS["no_retries"] if steps and all(s.get("ok") for s in steps) else 0.0

    total = round(sum(parts.values()), 2)
    return {"score": total, "level": level(total), "parts": parts, "notes": notes}
