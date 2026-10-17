"""One-time patch: adds the Change Guard panel to the dashboard.

Run from the project root:  python scripts/patch_step6_ui.py
Safe to run twice. Stops with a clear message if the files differ from what it expects.
"""
import sys

PANEL = '''      <div class="panel" id="guard-panel">
        <h2>Change Guard <span class="muted">approved program vs candidate</span></h2>
        <div id="guard-running" class="g-run">Checking the running program...</div>
        <textarea id="guard-text" spellcheck="false" placeholder="Paste a candidate PLC program (Structured Text), choose a file, or load the tampered sample..."></textarea>
        <div class="row">
          <button id="guard-sample" class="btn ghost" type="button">Load tampered sample</button>
          <label class="btn ghost filebtn">Choose file<input id="guard-file" type="file" accept=".st,.txt" hidden></label>
          <button id="guard-check" class="btn" type="button">Check against approved</button>
        </div>
        <div id="guard-result"></div>
      </div>
'''

CSS = '''
#guard-text { width: 100%; min-height: 140px; background: #0f161d; color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 8px; font: 12px/1.45 ui-monospace, Menlo, Consolas, monospace; resize: vertical; margin: 8px 0; }
.g-run { display: flex; gap: 8px; align-items: center; justify-content: space-between; padding: 8px 10px; border-radius: 8px; font-size: 12.5px; border: 1px solid var(--border); }
.g-run.ok { color: var(--ok); border-color: #1f5a3e; background: #0f2a1f; }
.g-run.bad { color: var(--high); border-color: #5a2a1f; background: #2a1511; }
.g-run .btn { padding: 4px 10px; font-size: 12px; white-space: nowrap; }
.filebtn { display: inline-flex; align-items: center; cursor: pointer; }
.g-head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 12px 0 8px; font-size: 12px; color: var(--muted); }
.gsev { font-weight: 800; letter-spacing: 0.5px; padding: 1px 8px; border-radius: 5px; color: #101820; font-size: 12px; }
.gsev-info { background: var(--info); }
.gsev-low { background: var(--ok); }
.gsev-medium { background: var(--medium); }
.gsev-high { background: var(--high); }
.gsev-critical { background: var(--critical); }
.g-finding { border: 1px solid var(--border); border-left-width: 4px; border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; background: var(--panel-2); }
.g-finding.s-info { border-left-color: var(--info); }
.g-finding.s-low { border-left-color: var(--ok); }
.g-finding.s-medium { border-left-color: var(--medium); }
.g-finding.s-high { border-left-color: var(--high); }
.g-finding.s-critical { border-left-color: var(--critical); }
.g-top { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 11px; color: var(--muted); }
.g-summary { font-weight: 600; margin: 5px 0 3px; }
.g-hazard, .g-rec { font-size: 12.5px; margin: 2px 0; }
.g-rec { color: var(--muted); }
.chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 5px; }
.chip { border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; font-size: 11px; color: var(--accent); }
.g-diff { margin: 8px 0; background: #0f161d; border: 1px solid var(--border); border-radius: 8px; padding: 8px; max-height: 230px; overflow: auto; font: 11.5px/1.4 ui-monospace, Menlo, Consolas, monospace; white-space: pre; }
.g-diff .add { color: #7ee787; }
.g-diff .del { color: #ff7b8b; }
.g-diff .hunk { color: var(--info); }
.g-note { font-size: 11px; color: var(--muted); margin: 2px 0 6px; }
'''


def patch(path, marker, pairs):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    if marker in text:
        print(f"{path}: already patched")
        return
    for old, new in pairs:
        if old not in text:
            sys.exit(f"PATCH FAILED in {path}: expected text not found:\n{old[:90]}")
        text = text.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"{path}: patched")


patch("web/index.html", 'id="guard-panel"', [
    ('    </section>\n\n    <section class="col-right">', PANEL + '    </section>\n\n    <section class="col-right">'),
    ('<script src="/static/app.js"></script>',
     '<script src="/static/app.js"></script>\n  <script src="/static/guard.js"></script>'),
])

with open("web/static/style.css", encoding="utf-8") as handle:
    css = handle.read()
if "#guard-text {" in css:
    print("web/static/style.css: already patched")
else:
    with open("web/static/style.css", "a", encoding="utf-8") as handle:
        handle.write(CSS)
    print("web/static/style.css: patched")
