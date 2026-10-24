"""Step 4c: screen.py turns page_source XML into the compact element list (no device needed)."""
from pathlib import Path

from mcp_server.screen import parse_screen

HOME = (Path(__file__).parent / "fixtures" / "apidemos_home.xml").read_text(encoding="utf-8")


def node(cls="android.widget.TextView", bounds="[0,0][100,100]", **attrs):
    extra = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    return f'<{cls} class="{cls}" package="com.demo" bounds="{bounds}" {extra}>'


def xml(*body):
    return '<hierarchy class="hierarchy">' + "".join(body) + "</hierarchy>"


def test_apidemos_home_compact_list():
    s = parse_screen(HOME)
    assert s["package"] == "io.appium.android.apis"
    assert s["total"] == 13
    clickable = [e for e in s["elements"] if e.get("clickable")]
    assert len(clickable) == 12
    # interactive first: the 12 list rows, then the non-clickable title
    assert s["elements"][-1]["text"] == "API Demos"
    assert [e["eid"] for e in s["elements"][:3]] == ["e01", "e02", "e03"]


def test_shared_resource_id_falls_back_to_accessibility_id():
    s = parse_screen(HOME)
    anim = next(e for e in s["elements"] if e.get("text") == "Animation")
    assert anim["rid"] == "text1"  # every row shares android:id/text1, so it cannot be the locator
    assert s["locators"][anim["eid"]] == {"by": "accessibility id", "value": "Animation"}


def test_unique_resource_id_preferred():
    s = parse_screen(xml(node(clickable="true", resource_id="com.demo:id/login", text="Login") + "</android.widget.TextView>"))
    assert s["locators"]["e01"] == {"by": "id", "value": "com.demo:id/login"}


def test_bounds_fallback_when_nothing_unique():
    row = node("android.widget.Button", "[0,0][10,10]", clickable="true", text="OK") + "</android.widget.Button>"
    row2 = node("android.widget.Button", "[0,20][10,30]", clickable="true", text="OK") + "</android.widget.Button>"
    s = parse_screen(xml(row, row2))
    assert s["locators"]["e02"] == {"by": "xpath", "value": '//*[@bounds="[0,20][10,30]"]'}


def test_max_elements_truncates_but_reports_total():
    rows = [node(bounds=f"[0,{i * 10}][10,{i * 10 + 5}]", clickable="true", text=f"Item {i}")
            + "</android.widget.TextView>" for i in range(80)]
    s = parse_screen(xml(*rows), max_elements=60)
    assert s["total"] == 80 and len(s["elements"]) == 60
    assert s["elements"][-1]["eid"] == "e60"


def test_clickable_row_borrows_child_label_and_child_not_duplicated():
    row = (node("android.widget.LinearLayout", "[0,0][100,50]", clickable="true")
           + node(bounds="[0,0][100,50]", text="Wi-Fi") + "</android.widget.TextView>"
           + "</android.widget.LinearLayout>")
    s = parse_screen(xml(row))
    assert len(s["elements"]) == 1
    assert s["elements"][0]["label"] == "Wi-Fi"


def test_invisible_and_zero_size_nodes_skipped():
    s = parse_screen(xml(
        node(bounds="[0,0][0,0]", text="zero") + "</android.widget.TextView>",
        node(displayed="false", text="hidden") + "</android.widget.TextView>",
        node(text="shown") + "</android.widget.TextView>",
    ))
    assert [e["text"] for e in s["elements"]] == ["shown"]


def test_password_text_hidden_and_secrets_redacted():
    pw = node("android.widget.EditText", "[0,0][100,50]", password="true", text="hunter2", resource_id="com.demo:id/pw")
    user = node("android.widget.EditText", "[0,60][100,110]", text="9876543210", resource_id="com.demo:id/user")
    s = parse_screen(xml(pw + "</android.widget.EditText>", user + "</android.widget.EditText>"),
                     redact={"9876543210": "{{USERNAME}}"})
    pw_el, user_el = s["elements"]
    assert pw_el["password"] and pw_el["editable"] and "text" not in pw_el
    assert user_el["text"] == "{{USERNAME}}"
    assert "9876543210" not in str(s["elements"])


def test_unchecked_checkbox_keeps_checked_false():
    cb = node("android.widget.CheckBox", checkable="true", checked="false", clickable="true")
    s = parse_screen(xml(cb + "</android.widget.CheckBox>"))
    assert s["elements"][0]["checked"] is False
