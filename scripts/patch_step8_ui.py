"""One-time patch: adds the Plant documentation panel to the dashboard.

Run from the project root:  python scripts/patch_step8_ui.py
Safe to run twice. Stops with a clear message if the files differ from what it expects.
"""
import sys

PANEL = '''      <div class="panel" id="docs-panel">
        <h2>Plant documentation <span class="muted">generated from the approved PLC program</span></h2>
        <div class="report-links">
          <a href="/api/docs/plant.html" target="_blank" rel="noopener">Open</a>
          <a href="/api/docs/plant.md?download=true" download>Markdown</a>
          <a href="/api/docs/plant.html?download=true" download>HTML file</a>
        </div>
        <iframe id="docs-frame" class="docs-frame" src="/api/docs/plant.html" sandbox title="Plant operating document" loading="lazy"></iframe>
      </div>
'''

CSS = '''
.docs-frame { width: 100%; height: 360px; border: 1px solid var(--border); border-radius: 8px; background: #ffffff; margin-top: 8px; }
.report-links { display: flex; gap: 10px; align-items: center; font-size: 12px; color: var(--muted); }
.report-links a { color: var(--accent); text-decoration: none; border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; }
.report-links a:hover { border-color: var(--accent); }
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


patch("web/index.html", 'id="docs-panel"', [
    ('        <div id="guard-result"></div>\n      </div>\n',
     '        <div id="guard-result"></div>\n      </div>\n' + PANEL),
])

with open("web/static/style.css", encoding="utf-8") as handle:
    css = handle.read()
if ".docs-frame {" in css:
    print("web/static/style.css: already patched")
else:
    with open("web/static/style.css", "a", encoding="utf-8") as handle:
        handle.write(CSS)
    print("web/static/style.css: patched")
