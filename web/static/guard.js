/* PlantMind - Change Guard panel (plain JavaScript, no external libraries). */
(function () {
  "use strict";

  var ORDER = { info: 0, low: 1, medium: 2, high: 3, critical: 4 };
  var MODE = {
    none: "no assessment needed",
    mock: "assessment: mock model (offline demo)",
    live: "assessment: Nemotron",
    unavailable: "assessment: model unavailable (rule-based text)"
  };
  var lastRunningHash = "";

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function api(path, options) {
    return fetch(path, options).then(function (response) {
      if (!response.ok) { throw new Error(path + " -> " + response.status); }
      return response.json();
    });
  }

  function finalSeverity(finding) {
    var rule = finding.rule_severity, llm = finding.llm_severity;
    return (llm && ORDER[llm] > ORDER[rule]) ? llm : rule;
  }

  function shortHash(hash) { return hash ? hash.slice(0, 8) : "-"; }

  function renderDiff(diffText) {
    var pre = el("div", "g-diff");
    var lines = diffText.split("\n").slice(0, 160);
    lines.forEach(function (line) {
      var cls = "";
      if (line.indexOf("@@") === 0) { cls = "hunk"; }
      else if (line.charAt(0) === "+" && line.indexOf("+++") !== 0) { cls = "add"; }
      else if (line.charAt(0) === "-" && line.indexOf("---") !== 0) { cls = "del"; }
      pre.appendChild(el("div", cls, line === "" ? " " : line));
    });
    return pre;
  }

  function renderResult(result) {
    var box = $("guard-result");
    box.textContent = "";
    var report = result.report;

    var head = el("div", "g-head");
    head.appendChild(el("span", "gsev gsev-" + report.overall_severity, report.overall_severity.toUpperCase()));
    head.appendChild(el("span", "", report.findings.length + " finding(s)"));
    head.appendChild(el("span", "badge", "source: " + result.source));
    head.appendChild(el("span", "badge", "approved " + shortHash(report.baseline_hash) +
                                         " -> candidate " + shortHash(report.candidate_hash)));
    head.appendChild(el("span", "badge", MODE[result.mode] || result.mode));
    box.appendChild(head);

    if (!report.findings.length) {
      box.appendChild(el("div", "empty", "No difference from the approved program that affects protection, alarms, setpoints or command paths."));
    }
    report.findings.forEach(function (f) {
      var sev = finalSeverity(f);
      var card = el("div", "g-finding s-" + sev);
      var top = el("div", "g-top");
      top.appendChild(el("span", "gsev gsev-" + sev, sev.toUpperCase()));
      top.appendChild(el("span", "ev-id", f.id));
      top.appendChild(el("span", "badge", f.kind));
      if (f.interlock_id) { top.appendChild(el("span", "badge", f.interlock_id)); }
      top.appendChild(el("span", "badge", "rule-based severity"));
      card.appendChild(top);
      card.appendChild(el("div", "g-summary", f.summary));
      if (f.hazard) { card.appendChild(el("div", "g-hazard", "What could go wrong: " + f.hazard)); }
      if (f.recommendation) { card.appendChild(el("div", "g-rec", "Suggested review: " + f.recommendation)); }
      if (f.mitre && f.mitre.length) {
        var chips = el("div", "chips");
        f.mitre.forEach(function (m) { chips.appendChild(el("span", "chip", m.technique_id + " " + m.name)); });
        card.appendChild(chips);
      }
      box.appendChild(card);
    });
    if (report.findings.length) {
      box.appendChild(el("div", "g-note", "MITRE ATT&CK for ICS IDs were checked against attack.mitre.org."));
    }

    if (result.diff) { box.appendChild(renderDiff(result.diff)); }

    var decision = el("div", "actions");
    if (report.decision === "pending" && report.findings.length) {
      [["approve", "approved", "Approve change"], ["reject", "rejected", "Reject"],
       ["deferred", "needs_review", "Needs review"]].forEach(function (item) {
        var button = el("button", item[0], item[2]);
        button.type = "button";
        button.addEventListener("click", function () { decide(report.candidate_hash, item[1]); });
        decision.appendChild(button);
      });
      box.appendChild(decision);
    } else if (report.decision !== "pending") {
      var done = el("div", "decided", "Decision: ");
      done.appendChild(el("b", "", report.decision.replace("_", " ")));
      box.appendChild(done);
    }
  }

  function decide(hash, decision) {
    api("/api/guard/" + encodeURIComponent(hash) + "/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision: decision })
    }).then(renderResult).catch(function () { $("guard-result").textContent = "Could not save the decision."; });
  }

  function refreshRunning() {
    api("/api/guard/running").then(function (data) {
      var bar = $("guard-running");
      bar.textContent = "";
      if (data.matches_approved) {
        bar.className = "g-run ok";
        bar.appendChild(el("span", "", "The program running on the PLC matches the approved baseline."));
        lastRunningHash = "";
        return;
      }
      var report = data.result.report;
      bar.className = "g-run bad";
      bar.appendChild(el("span", "", "The program running on the PLC DIFFERS from the approved baseline: " +
        report.findings.length + " finding(s), overall " + report.overall_severity.toUpperCase() + "."));
      var button = el("button", "btn ghost", "Show findings");
      button.type = "button";
      button.addEventListener("click", function () { renderResult(data.result); });
      bar.appendChild(button);
      if (report.candidate_hash !== lastRunningHash) {      // new differing program: show it once
        lastRunningHash = report.candidate_hash;
        renderResult(data.result);
      }
    }).catch(function () {
      var bar = $("guard-running");
      bar.className = "g-run";
      bar.textContent = "Change Guard is not reachable.";
    });
  }

  function init() {
    if (!$("guard-panel")) { return; }
    $("guard-sample").addEventListener("click", function () {
      api("/api/guard/samples").then(function (s) { $("guard-text").value = s.tampered; });
    });
    $("guard-file").addEventListener("change", function (event) {
      var file = event.target.files && event.target.files[0];
      if (!file) { return; }
      var reader = new FileReader();
      reader.onload = function () { $("guard-text").value = String(reader.result || ""); };
      reader.readAsText(file);
    });
    $("guard-check").addEventListener("click", function () {
      var text = $("guard-text").value.trim();
      var out = $("guard-result");
      if (!text) { out.textContent = "Paste a candidate program or load the tampered sample first."; return; }
      var button = $("guard-check");
      button.disabled = true;
      out.textContent = "Checking against the approved program...";
      api("/api/guard/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate: text, label: "uploaded program" })
      }).then(renderResult)
        .catch(function () { out.textContent = "The check failed (is the program under 200 KB?)."; })
        .then(function () { button.disabled = false; });
    });
    refreshRunning();
    setInterval(refreshRunning, 2000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
