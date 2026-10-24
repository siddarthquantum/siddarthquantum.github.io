"""Test case schema and the Test Designer's only write tool (FR-10, FR-11).

The Designer can write runs/<run_id>/proposed_tests.json and nothing else. Only the human-run
scripts/approve.py turns it into approved_tests.json + approval.json (R2 gate).
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
PLACEHOLDERS = {"{{USERNAME}}", "{{PASSWORD}}", "{{OTP}}"}


def click_only():
    return os.getenv("QA_CLICK_ONLY", "true").lower() == "true"


class Step(BaseModel):
    action: Literal["tap", "type", "scroll", "back", "assert_visible", "assert_not_visible"]
    target: str = Field("", description="Visible text, content-desc or resource-id of the element; "
                                        "for scroll: up/down/left/right; for asserts: the text to check")
    value: str = Field("", description="Text to type (type only). Credentials only as placeholders.")
    expected: str = Field("", description="What should be true after this step")

    @field_validator("value")
    @classmethod
    def only_known_placeholders(cls, v):
        for p in re.findall(r"\{\{[^}]*\}\}", v):
            if p not in PLACEHOLDERS:
                raise ValueError(f"unknown placeholder {p}; allowed: {sorted(PLACEHOLDERS)}")
        return v

    @model_validator(mode="after")
    def target_required(self):
        if self.action != "back" and not self.target.strip():
            raise ValueError(f"{self.action} step needs a target")
        if self.action == "type" and click_only():
            raise ValueError("click-only mode (QA_CLICK_ONLY=true): type steps are not allowed")
        if self.action == "type" and not self.value:
            raise ValueError("type step needs a value")
        return self


class TestCase(BaseModel):
    __test__ = False  # not a pytest class
    id: str = Field(pattern=r"^TC\d{2,3}$")
    title: str = Field(min_length=5, max_length=120)
    priority: Literal["high", "medium", "low"] = "medium"
    fresh_start: bool = True
    preconditions: str = ""
    steps: list[Step] = Field(min_length=1, max_length=15)
    expected_result: str = Field(min_length=3)

    @model_validator(mode="after")
    def has_assertion(self):
        if not any(s.action.startswith("assert") for s in self.steps):
            raise ValueError(f"{self.id} has no assert_visible/assert_not_visible step")
        return self


class TestSuite(BaseModel):
    __test__ = False
    tests: list[TestCase] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_ids_and_chain(self):
        ids = [t.id for t in self.tests]
        if len(ids) != len(set(ids)):
            raise ValueError("test ids must be unique")
        if not self.tests[0].fresh_start:
            raise ValueError("the first test must have fresh_start=true (nothing runs before it)")
        return self


def validate_suite(tests_json: str):
    """Returns (TestSuite, None) or (None, error_text)."""
    try:
        data = json.loads(tests_json)
    except ValueError as e:
        return None, f"Not valid JSON: {e}"
    if isinstance(data, list):
        data = {"tests": data}
    try:
        return TestSuite.model_validate(data), None
    except ValidationError as e:
        return None, "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())[:1500]


def save_proposed_tests(tests_json: str) -> dict:
    """Save the designed manual test cases for human review.

    Args:
      tests_json: JSON list of test cases. Each: {"id": "TC01", "title", "priority": "high|medium|low",
        "fresh_start": true, "preconditions", "steps": [{"action": "tap|type|scroll|back|assert_visible|
        assert_not_visible", "target", "value", "expected"}], "expected_result"}.

    Returns:
      {"ok": true, "run_id", "path", "count"} or {"ok": false, "error": "INVALID_TESTS", "message"} -
      fix the listed problems and call again.
    """
    suite, err = validate_suite(tests_json)
    if err:
        return {"ok": False, "error": "INVALID_TESTS", "message": err}
    run_id = f"{os.getenv('QA_PROFILE', 'app')}-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "proposed_tests.json"
    out.write_text(json.dumps({"run_id": run_id, "profile": os.getenv("QA_PROFILE", ""),
                               "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                               **suite.model_dump()}, indent=2), encoding="utf-8")
    return {"ok": True, "run_id": run_id, "path": f"runs/{run_id}/proposed_tests.json",
            "count": len(suite.tests),
            "next": f"Human reviews and approves with: python scripts/approve.py {run_id}"}
