"""One-time patch: shows model analysis, hypotheses and the AI mode pill in the dashboard.

Run from the project root:  python scripts/patch_step5_ui.py
Safe to run twice (it detects an already patched file). Stops with a clear message if
the files differ from what it expects.
"""
import sys

JS_HOOK = '''  function renderAnalysis(card, alert) {
    var box = el("div", "analysis");
    var head = el("div", "an-head");
    head.appendChild(el("span", "an-title", "Model analysis"));
    head.appendChild(el("span", "badge", "model-generated"));
    if (alert.triage_tier) { head.appendChild(el("span", "badge", "tier: " + alert.triage_tier)); }
    box.appendChild(head);
    if (!alert.operator_explanation) {
      box.appendChild(el("div", "an-pending", "Analyzing..."));
      card.appendChild(box);
      return;
    }
    box.appendChild(el("p", "an-text", alert.operator_explanation));
    if (alert.hypotheses.length) {
      var hyps = el("div", "hyps");
      alert.hypotheses.forEach(function (h) {
        var pct = Math.round(h.confidence * 100);
        var row = el("div", "hyp");
        var top = el("div", "hyp-top");
        top.appendChild(el("span", "hyp-label", h.label.replace(/_/g, " ")));
        top.appendChild(el("span", "hyp-pct", pct + "%"));
        row.appendChild(top);
        var bar = el("div", "bar");
        var fill = el("div", "fill");
        fill.style.width = pct + "%";
        bar.appendChild(fill);
        row.appendChild(bar);
        row.appendChild(el("div", "hyp-why", h.reasoning + " (" + h.evidence_ids.join(", ") + ")"));
        hyps.appendChild(row);
      });
      box.appendChild(hyps);
    }
    if (alert.recommended_actions.length) {
      box.appendChild(el("div", "an-sub", "Suggested checks (a human decides)"));
      var list = el("ol", "checks");
      alert.recommended_actions.forEach(function (text) { list.appendChild(el("li", "", text)); });
      box.appendChild(list);
    }
    card.appendChild(box);
  }

  function renderLlm(llm) {
    var pill = $("ai");
    if (!pill || !llm || !llm.enabled) { return; }
    if (llm.mock) {
      pill.textContent = "AI: mock model (offline demo)";
      pill.className = "pill warn";
    } else {
      pill.textContent = "AI: Nemotron live";
      pill.className = "pill on";
    }
  }

  function decide(alertId, decision) {'''

CSS = '''
.pills { display: flex; gap: 8px; align-items: center; }
.pill.warn { color: var(--medium); border-color: #5a4a1f; background: #2a2411; }
.analysis { margin-top: 8px; border: 1px solid var(--border); border-radius: 6px; padding: 8px; background: #111a22; }
.an-head { display: flex; gap: 6px; align-items: center; font-size: 11px; color: var(--muted); margin-bottom: 4px; }
.an-title { font-weight: 700; color: var(--text); font-size: 12px; }
.an-pending { color: var(--muted); font-size: 12px; font-style: italic; }
.an-text { margin: 4px 0 8px; font-size: 12.5px; }
.hyp { margin-bottom: 7px; }
.hyp-top { display: flex; justify-content: space-between; font-size: 12.5px; font-weight: 600; text-transform: capitalize; }
.hyp-pct { color: var(--accent); }
.bar { height: 6px; background: #1d2833; border-radius: 3px; overflow: hidden; margin: 3px 0; }
.bar .fill { height: 100%; background: var(--accent); }
.hyp-why { font-size: 11.5px; color: var(--muted); }
.an-sub { font-size: 11.5px; color: var(--muted); margin: 8px 0 3px; }
.checks { margin: 0; padding-left: 18px; font-size: 12.5px; display: grid; gap: 3px; }
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


patch("web/index.html", 'id="ai"', [
    ('<span id="live" class="pill off">connecting...</span>',
     '<div class="pills"><span id="ai" class="pill warn">AI: ...</span>'
     '<span id="live" class="pill off">connecting...</span></div>'),
    ('all findings below are rule-based checks of the approved PLC logic',
     'evidence comes from rule-based checks of the approved PLC logic; model-written analysis is labeled'),
])

patch("web/static/app.js", "renderAnalysis", [
    ('return [a.id, a.status, a.severity, a.title, a.evidence.length];',
     'return [a.id, a.status, a.severity, a.title, a.evidence.length,\n'
     '        a.hypotheses.length, a.operator_explanation.length, a.triage_tier];'),
    ('      card.appendChild(list);\n\n      if (alert.status === "open") {',
     '      card.appendChild(list);\n      renderAnalysis(card, alert);\n\n      if (alert.status === "open") {'),
    ('  function decide(alertId, decision) {', JS_HOOK),
    ('      markActiveScenario(state.demo_scenario);',
     '      markActiveScenario(state.demo_scenario);\n      renderLlm(state.llm);'),
])

with open("web/static/style.css", encoding="utf-8") as handle:
    css = handle.read()
if ".analysis {" in css:
    print("web/static/style.css: already patched")
else:
    with open("web/static/style.css", "a", encoding="utf-8") as handle:
        handle.write(CSS)
    print("web/static/style.css: patched")
