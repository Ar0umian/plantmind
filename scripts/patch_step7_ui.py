"""One-time patch: adds incident-report links to alerts and the operator assistant panel.

Run from the project root:  python scripts/patch_step7_ui.py
Safe to run twice. Stops with a clear message if the files differ from what it expects.
"""
import sys

PANEL = '''      <div class="panel" id="assistant-panel">
        <h2>Ask PlantMind</h2>
        <p class="hint small">Grounded in the approved PLC logic and the live state. Advisory only.</p>
        <div id="chat-log" class="chat-log"></div>
        <div id="chat-suggestions" class="suggestions"></div>
        <div class="chat-input">
          <input id="chat-input" type="text" maxlength="500" autocomplete="off" placeholder="Ask a question...">
          <button id="chat-send" class="btn" type="button">Send</button>
        </div>
      </div>
'''

JS_HOOK = '''  function renderReportLinks(card, alert) {
    var base = "/api/alerts/" + encodeURIComponent(alert.id);
    var row = el("div", "report-links");
    row.appendChild(el("span", "", "Incident report:"));
    [["Open", base + "/report.html", false], ["Markdown", base + "/report.md?download=true", true],
     ["HTML file", base + "/report.html?download=true", true]].forEach(function (item) {
      var link = el("a", "", item[0]);
      link.href = item[1];
      if (item[2]) { link.setAttribute("download", ""); } else { link.target = "_blank"; link.rel = "noopener"; }
      row.appendChild(link);
    });
    card.appendChild(row);
  }

  function decide(alertId, decision) {'''

CSS = '''
.report-links { display: flex; gap: 10px; align-items: center; margin-top: 8px; font-size: 12px; color: var(--muted); }
.report-links a { color: var(--accent); text-decoration: none; border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; }
.report-links a:hover { border-color: var(--accent); }
.chat-log { max-height: 280px; overflow-y: auto; display: grid; gap: 8px; margin-bottom: 8px; }
.msg { border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px; font-size: 12.5px; background: var(--panel-2); }
.msg.user { background: #12302f; border-color: #1f5a58; justify-self: end; max-width: 88%; }
.msg.assistant { justify-self: start; max-width: 96%; }
.msg-meta { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 5px; font-size: 11px; }
.suggestions { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.sugg { background: transparent; color: var(--text); border: 1px solid var(--border); border-radius: 999px; padding: 3px 10px; font: inherit; font-size: 11.5px; cursor: pointer; }
.sugg:hover { border-color: var(--accent); }
.chat-input { display: flex; gap: 8px; }
.chat-input input { flex: 1; background: #0f161d; color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px; font: inherit; }
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


patch("web/index.html", 'id="assistant-panel"', [
    ('        <div id="alerts" class="alerts"></div>\n      </div>\n    </section>\n  </main>',
     '        <div id="alerts" class="alerts"></div>\n      </div>\n' + PANEL + '    </section>\n  </main>'),
    ('<script src="/static/guard.js"></script>',
     '<script src="/static/guard.js"></script>\n  <script src="/static/assistant.js"></script>'),
])

patch("web/static/app.js", "renderReportLinks", [
    ('      renderAnalysis(card, alert);\n', '      renderAnalysis(card, alert);\n      renderReportLinks(card, alert);\n'),
    ('  function decide(alertId, decision) {', JS_HOOK),
])

with open("web/static/style.css", encoding="utf-8") as handle:
    css = handle.read()
if ".chat-log {" in css:
    print("web/static/style.css: already patched")
else:
    with open("web/static/style.css", "a", encoding="utf-8") as handle:
        handle.write(CSS)
    print("web/static/style.css: patched")
