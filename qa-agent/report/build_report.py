"""One self-contained HTML report per run (Step 6). Screenshots are embedded, so the file works offline.

    .venv\\Scripts\\python.exe report\\build_report.py runs\\<run_id>
    .venv\\Scripts\\python.exe report\\build_report.py runs\\<run_id> --session <adk-session-id>   (older runs)

Writes runs/<run_id>/report.html. Reads approved_tests.json, approval.json, results.json, the evidence
PNGs (already masked by the MCP server) and the usage log. Confidence comes from report/confidence.py.
"""
import argparse
import base64
import html
import io
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from report.confidence import WEIGHTS, score_test  # noqa: E402
from report.usage import lines_for_run, lines_for_session, summarize  # noqa: E402

STATUS_ORDER = ["pass", "fail", "blocked", "incomplete", "not run"]


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def load(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def thumb(png_path: Path, width: int = 540) -> str:
    """Embed a screenshot as a small JPEG data URI (keeps the report a few MB at most)."""
    from PIL import Image
    if not png_path.exists():
        return ""
    img = Image.open(png_path).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=72, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def img_tag(png_path: Path, alt: str) -> str:
    src = thumb(png_path)
    return f'<img alt="{esc(alt)}" src="{src}">' if src else ""


def step_label(path: str) -> str:
    # 003_TC01_s03_tap.png -> "s03 tap"
    stem = Path(path).stem.split("_", 2)[-1]
    return stem.replace("_", " ")


def build(run_dir: Path, session: str | None = None) -> Path:
    run_id = run_dir.name
    approved = load(run_dir / "approved_tests.json", {"tests": []})
    approval = load(run_dir / "approval.json", {})
    results_file = load(run_dir / "results.json", {"tests": {}})
    results, history = results_file.get("tests", {}), results_file.get("history", {})
    planted = {p["test_id"]: p for p in approval.get("planted_defects", [])}

    usage_dir = ROOT / "runs" / "_usage"
    rows = lines_for_session(usage_dir, session) if session else lines_for_run(usage_dir, run_id)
    usage = summarize(rows)

    tests = []
    for t in approved.get("tests", []):
        r = results.get(t["id"])
        conf = score_test(r, history.get(t["id"])) if r else None
        tests.append({"test": t, "result": r, "conf": conf, "status": r["status"] if r else "not run"})
    counts = {s: sum(1 for x in tests if x["status"] == s) for s in STATUS_ORDER}

    started = [x["result"].get("started_at") for x in tests if x["result"] and x["result"].get("started_at")]
    finished = [x["result"].get("finished_at") for x in tests if x["result"] and x["result"].get("finished_at")]
    span = f"{min(started)} to {max(finished)}" if started and finished else (max(finished) if finished else "")

    out = run_dir / "report.html"
    out.write_text(page(run_id, approval, tests, counts, usage, span, planted, run_dir), encoding="utf-8")
    return out


def page(run_id, approval, tests, counts, usage, span, planted, run_dir) -> str:
    tiles = "".join(f'<div class="tile s-{s.replace(" ", "-")}"><b>{counts[s]}</b><span>{s}</span></div>'
                    for s in STATUS_ORDER if counts[s] or s in ("pass", "fail", "blocked"))
    phases = "".join(f"<tr><td>{esc(p)}</td><td>{v['calls']}</td><td>{v['total']:,}</td></tr>"
                     for p, v in usage["phases"].items())
    usage_html = (f"""<table class="kv"><tr><th>Model calls</th><td>{usage['calls']}</td></tr>
        <tr><th>Tokens</th><td>{usage['total']:,} ({usage['prompt']:,} in / {usage['output']:,} out)</td></tr>
        <tr><th>Models</th><td>{esc(', '.join(usage['models']))}</td></tr>
        <tr><th>Agent time</th><td>{usage['seconds'] // 60} min {usage['seconds'] % 60} s</td></tr></table>
        <table class="grid"><tr><th>Phase</th><th>Calls</th><th>Tokens</th></tr>{phases}</table>"""
                  if usage["calls"] else '<p class="muted">No usage lines are tagged with this run '
                  '(runs before 25 Oct evening). Use --session &lt;adk session id&gt;.</p>')
    planted_note = (f'<p class="note">{len(planted)} planted defect(s): a correct executor must report '
                    f'{", ".join(planted)} as FAIL.</p>' if planted else "")
    cards = "".join(card(x, planted.get(x["test"]["id"]), run_dir) for x in tests)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA Report {esc(run_id)}</title>
<style>
:root{{--bg:#0b090a;--card:#17120d;--line:rgba(212,175,55,.25);--gold:#d4af37;--gold2:#f3e5ab;--text:#f5f3ef;
--muted:#b0a89f;--pass:#7fd18b;--fail:#ff7a6b;--blocked:#e8c36a;--grey:#9a948c}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font:15px/1.55 "Segoe UI",system-ui,sans-serif;padding:24px 16px}}
main{{max-width:1080px;margin:0 auto}}
h1{{font-family:Georgia,serif;color:var(--gold);font-size:1.7rem;letter-spacing:1px}}
h2{{color:var(--gold);font-size:1.15rem;margin:28px 0 10px}} h3{{font-size:1.05rem}}
.muted{{color:var(--muted)}} .note{{color:var(--blocked);margin-top:8px}}
.meta{{color:var(--muted);font-size:.9rem;margin-top:4px;word-break:break-all}}
.tiles{{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:96px}}
.tile b{{display:block;font-size:1.6rem}} .tile span{{color:var(--muted);text-transform:uppercase;font-size:.75rem}}
.s-pass b{{color:var(--pass)}} .s-fail b{{color:var(--fail)}} .s-blocked b{{color:var(--blocked)}}
.s-incomplete b,.s-not-run b{{color:var(--grey)}}
.cols{{display:grid;gap:16px;grid-template-columns:1fr}}
@media(min-width:760px){{.cols{{grid-template-columns:1fr 1fr}}}}
.box,.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}} th,td{{text-align:left;padding:5px 8px;vertical-align:top}}
.grid th,.grid td{{border-bottom:1px solid rgba(255,255,255,.07)}} .kv th{{color:var(--muted);font-weight:500;width:36%}}
.card{{margin-top:14px}} .head{{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center}}
.badge{{border-radius:999px;padding:2px 10px;font-size:.78rem;font-weight:600;border:1px solid currentColor}}
.b-pass{{color:var(--pass)}} .b-fail{{color:var(--fail)}} .b-blocked{{color:var(--blocked)}}
.b-incomplete,.b-not-run{{color:var(--grey)}} .b-planted{{color:var(--blocked)}}
.conf{{margin-left:auto;font-size:.85rem}} .conf b{{color:var(--gold2)}}
.reason{{margin-top:8px;padding:8px 10px;border-left:3px solid var(--fail);background:rgba(255,122,107,.07)}}
.reason.ok{{border-color:var(--pass);background:rgba(127,209,139,.06)}}
details{{margin-top:10px}} summary{{cursor:pointer;color:var(--gold2)}}
.steps{{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));margin-top:10px}}
.step{{font-size:.8rem;color:var(--muted)}} .step b{{color:var(--text)}} .step .x{{color:var(--fail)}} .step .v{{color:var(--pass)}}
.step img{{width:100%;border-radius:8px;border:1px solid var(--line);margin-top:4px;cursor:zoom-in}}
img.zoom{{position:fixed;inset:0;margin:auto;max-height:94vh;width:auto;max-width:94vw;z-index:9;cursor:zoom-out;
box-shadow:0 0 0 100vmax rgba(0,0,0,.85)}}
ol.plan{{margin:6px 0 0 20px;font-size:.88rem}} code{{color:var(--gold2)}}
footer{{margin-top:32px;color:var(--muted);font-size:.82rem}}
</style></head><body><main>
<h1>QA Report</h1>
<p class="meta">Run <code>{esc(run_id)}</code> · tests {esc(span) or "not executed yet"} · report generated {time.strftime("%Y-%m-%d %H:%M")}</p>
<p class="meta">Approved by {esc(approval.get("approved_by", "?"))} at {esc(approval.get("approved_at", "?"))} · SHA-256 {esc(approval.get("sha256", "")[:16])}…</p>
<div class="tiles">{tiles}</div>{planted_note}
<div class="cols" style="margin-top:16px"><div class="box"><h3>Model usage (M7)</h3>{usage_html}</div>
<div class="box"><h3>How confidence is computed</h3><table class="grid">
<tr><td>Expected text matched exactly / clearly absent</td><td>{WEIGHTS['exact']}</td></tr>
<tr><td>Matched only as part of a longer text</td><td>{WEIGHTS['fuzzy']}</td></tr>
<tr><td>Same verdict in 3 executions (2: {WEIGHTS['stable2']})</td><td>{WEIGHTS['stable3']}</td></tr>
<tr><td>Elements found by resource-id / accessibility id</td><td>{WEIGHTS['id']}</td></tr>
<tr><td>… by visible text / by coordinates</td><td>{WEIGHTS['text']} / {WEIGHTS['coordinates']}</td></tr>
<tr><td>No step needed a retry</td><td>{WEIGHTS['no_retries']}</td></tr></table>
<p class="muted" style="margin-top:6px">High ≥ 0.8 · Medium ≥ 0.5 · Low &lt; 0.5. Computed from recorded evidence, not asked from the model.</p></div></div>
<h2>Test cases</h2>{cards}
<footer>Screenshots were masked by the device server before they were saved (password, PIN and OTP fields).
Generated by Sichakra QA Agent · report/build_report.py</footer>
</main>
<script>document.addEventListener("click",e=>{{if(e.target.matches(".step img"))e.target.classList.toggle("zoom")}})</script>
</body></html>"""


def card(x, planted, run_dir) -> str:
    t, r, conf, status = x["test"], x["result"], x["conf"], x["status"]
    cls = status.replace(" ", "-")
    badges = f'<span class="badge b-{cls}">{esc(status.upper())}</span>'
    if planted:
        badges += f'<span class="badge b-planted" title="expected text replaced: {esc(planted["original"])}">planted defect</span>'
    conf_html = ""
    if conf:
        parts = ", ".join(f"{k} {v}" for k, v in conf["parts"].items())
        conf_html = (f'<span class="conf" title="{esc(parts)}">confidence <b>{conf["level"]}</b> '
                     f'({conf["score"]:.2f})</span>')
    plan = "".join(f"<li><code>{esc(s['action'])}</code> {esc(s.get('target'))}</li>" for s in t.get("steps", []))
    reason = ""
    if r:
        ok = status == "pass"
        reason = (f'<div class="reason{" ok" if ok else ""}"><b>{"Result" if ok else "Failure reason"}:</b> '
                  f'{esc(r.get("actual") or "-")}</div>')
    notes = "".join(f'<p class="muted" style="font-size:.82rem">· {esc(n)}</p>' for n in (conf or {}).get("notes", []))
    return f"""<div class="card"><div class="head"><h3>{esc(t['id'])} · {esc(t['title'])}</h3>{badges}
<span class="muted" style="font-size:.82rem">{esc(t.get('priority', ''))} priority</span>{conf_html}</div>
<p class="muted" style="margin-top:6px"><b>Expected:</b> {esc(t.get('expected_result'))}</p>{reason}{notes}
<details><summary>Approved steps ({len(t.get('steps', []))})</summary><ol class="plan">{plan}</ol></details>
{steps_html(r, run_dir) if r else ''}</div>"""


def steps_html(r, run_dir) -> str:
    repo_root = run_dir.parents[1]  # runs/<id> -> qa-agent
    items = []
    if r.get("steps"):
        for s in r["steps"]:
            mark = '<span class="v">✓</span>' if s.get("ok") and s.get("visible", True) else '<span class="x">✗</span>'
            detail = f"{esc(s.get('target'))}"
            if s.get("action") == "assert":
                detail += " (exact)" if s.get("exact") else " (substring)" if s.get("visible") else " (not visible)"
            elif s.get("locator"):
                detail += f" · {esc(s['locator'])}"
            if s.get("error"):
                detail += f" · {esc(s['error'])}"
            img = img_tag(repo_root / s["screenshot"], f"step {s['n']} screenshot") if s.get("screenshot") else ""
            items.append(f'<div class="step">{mark} <b>{s["n"]}. {esc(s["action"])}</b> {detail}{img}</div>')
    else:  # older runs: evidence list only
        for p in r.get("evidence", []):
            items.append(f'<div class="step"><b>{esc(step_label(p))}</b>{img_tag(repo_root / p, step_label(p))}</div>')
    if not items:
        return ""
    return f'<details open><summary>Executed steps and screenshots ({len(items)})</summary><div class="steps">{"".join(items)}</div></details>'


def main():
    ap = argparse.ArgumentParser(description="Build runs/<run_id>/report.html")
    ap.add_argument("run_dir", help="e.g. runs/apidemos-20261025-105313")
    ap.add_argument("--session", help="adk session id (runs/_usage/<id>.jsonl) for runs before run tagging")
    a = ap.parse_args()
    run_dir = Path(a.run_dir)
    if not run_dir.is_absolute():
        run_dir = (Path.cwd() / run_dir) if (Path.cwd() / run_dir).exists() else ROOT / a.run_dir
    if not (run_dir / "approved_tests.json").exists():
        sys.exit(f"{run_dir} has no approved_tests.json - approve the run first (scripts/approve.py).")
    out = build(run_dir.resolve(), a.session)
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
