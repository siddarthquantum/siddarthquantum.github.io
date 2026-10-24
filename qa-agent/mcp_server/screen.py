"""Turns Appium page_source XML into a compact element list for the model (Step 4a, FR-03).

The model sees short eids (e01, e02...). The real locator for each eid stays here, server-side,
chosen as the first one that is UNIQUE on the screen: resource-id > accessibility id > text > bounds.
"""
import re
import xml.etree.ElementTree as ET
from collections import Counter

MAX_ELEMENTS = 60
_BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _bounds(node):
    m = _BOUNDS.fullmatch(node.get("bounds", ""))
    return [int(v) for v in m.groups()] if m else None


def _is_editable(node):
    cls = node.get("class", "")
    return cls.endswith("EditText") or cls.endswith("AutoCompleteTextView")


def _is_interactive(node):
    return (
        node.get("clickable") == "true"
        or node.get("long-clickable") == "true"
        or node.get("checkable") == "true"
        or node.get("scrollable") == "true"
        or _is_editable(node)
    )


def _visible(node):
    b = _bounds(node)
    return node.get("displayed", "true") == "true" and b is not None and b[2] > b[0] and b[3] > b[1]


def _locator(node, counts):
    """Pick the first locator that matches exactly one node on this screen."""
    rid, desc, text = node.get("resource-id", ""), node.get("content-desc", ""), node.get("text", "")
    if rid and counts["rid"][rid] == 1:
        return {"by": "id", "value": rid}
    if desc and counts["desc"][desc] == 1:
        return {"by": "accessibility id", "value": desc}
    if text and counts["text"][text] == 1 and '"' not in text and node.get("password") != "true":
        return {"by": "xpath", "value": f'//*[@text="{text}"]'}
    return {"by": "xpath", "value": f'//*[@bounds="{node.get("bounds")}"]'}


def parse_screen(xml: str, max_elements: int = MAX_ELEMENTS, redact: dict | None = None) -> dict:
    """Returns {"package", "total", "elements": [...], "locators": {eid: locator}}.

    redact maps a secret value to its placeholder (e.g. "s3cret" -> "{{PASSWORD}}") so typed
    credentials never reach the model. Only "elements" is meant for the model; "locators" stays
    in the server.
    """
    redact = redact or {}
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    nodes = [n for n in root.iter() if n.get("class") and n is not root]

    counts = {
        "rid": Counter(n.get("resource-id") for n in nodes if n.get("resource-id")),
        "desc": Counter(n.get("content-desc") for n in nodes if n.get("content-desc")),
        "text": Counter(n.get("text") for n in nodes if n.get("text")),
    }

    interactive, info, consumed = [], [], set()
    for node in nodes:
        if not _visible(node) or id(node) in consumed:
            continue
        has_words = node.get("text") or node.get("content-desc")
        if _is_interactive(node):
            label = ""
            if not has_words:
                # A clickable row with no text of its own: borrow the first child label so the
                # model knows what the row is, and skip that child so it is not listed twice.
                for child in node.iter():
                    if child is not node and (child.get("text") or child.get("content-desc")):
                        label = child.get("text") or child.get("content-desc")
                        consumed.add(id(child))
                        break
            interactive.append((node, label))
        elif has_words:
            info.append((node, ""))

    ordered = interactive + info
    package = next((n.get("package") for n in nodes if n.get("package")), "")
    elements, locators = [], {}
    for i, (node, label) in enumerate(ordered[:max_elements], start=1):
        eid = f"e{i:02d}"
        password = node.get("password") == "true"
        text = "" if password else node.get("text", "")
        el = {
            "eid": eid,
            "class": node.get("class", "").rsplit(".", 1)[-1],
            "text": redact.get(text, text),
            "label": redact.get(label, label),
            "rid": node.get("resource-id", "").split(":id/")[-1],
            "desc": "" if node.get("content-desc") == node.get("text") else node.get("content-desc", ""),
            "clickable": node.get("clickable") == "true",
            "editable": _is_editable(node),
            "password": password,
            "scrollable": node.get("scrollable") == "true",
            "checked": node.get("checked") == "true" if node.get("checkable") == "true" else None,
            "disabled": node.get("enabled") == "false",
            "bounds": _bounds(node),
        }
        # Drop empty/false fields: fewer tokens per step for the model. Keep checked=False: it is a state.
        elements.append({k: v for k, v in el.items() if v not in ("", False, None) or k == "checked" and v is False})
        locators[eid] = _locator(node, counts)

    return {"package": package, "total": len(ordered), "elements": elements, "locators": locators}
