/* PlantMind dashboard - plain JavaScript, no external libraries (works offline). */
(function () {
  "use strict";

  var POLL_MS = 1000;
  var WINDOW = 180;

  var PUMPS = [
    { tag: "P-101", name: "Intake pump" },
    { tag: "P-201", name: "Chlorine dosing pump" },
    { tag: "P-301", name: "Distribution pump" }
  ];
  var TILES = [
    { tag: "LT-101", label: "Raw tank level", unit: "%", digits: 1 },
    { tag: "LT-301", label: "Treated tank level", unit: "%", digits: 1 },
    { tag: "AT-201", label: "Chlorine residual", unit: "ppm", digits: 2 },
    { tag: "FT-101", label: "Intake flow", unit: "m3/h", digits: 0 },
    { tag: "PT-301", label: "Discharge pressure", unit: "bar", digits: 2 }
  ];
  var CHARTS = [
    { id: "chart-levels", title: "Tank levels (%)", min: 0, max: 100,
      series: [{ tag: "LT-101", name: "Raw LT-101", color: "#5aa9ff" },
               { tag: "LT-301", name: "Treated LT-301", color: "#7ee787" }],
      lines: [{ y: 15, label: "trip 15", color: "#ff4d6d" }] },
    { id: "chart-chlorine", title: "Chlorine residual (ppm)", min: 0, max: 8,
      series: [{ tag: "AT-201", name: "AT-201", color: "#f2b84b" }],
      lines: [{ y: 1.2, label: "start 1.2", color: "#5d6f82" },
              { y: 1.8, label: "stop 1.8", color: "#5d6f82" },
              { y: 4.0, label: "IL-04 trip 4.0", color: "#ff4d6d" }] },
    { id: "chart-flow", title: "Intake flow (m3/h)", min: 0, max: 160,
      series: [{ tag: "FT-101", name: "FT-101", color: "#c792ea" }],
      lines: [{ y: 120, label: "nominal 120", color: "#5d6f82" }] },
    { id: "chart-pressure", title: "Discharge pressure (bar)", min: 0, max: 8,
      series: [{ tag: "PT-301", name: "PT-301", color: "#ff9e64" }],
      lines: [{ y: 5.0, label: "alarm 5.0", color: "#f2b84b" },
              { y: 6.0, label: "IL-06 trip 6.0", color: "#ff4d6d" }] }
  ];
  var KIND_LABEL = {
    interlock_violation: "Interlock",
    physical_inconsistency: "Physical",
    command_anomaly: "Command",
    stale_value: "Stale sensor"
  };

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

  function fmt(value, digits) {
    return (typeof value === "number" && isFinite(value)) ? value.toFixed(digits) : "-";
  }

  function clock(unixSeconds) {
    var d = new Date(unixSeconds * 1000);
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
  }

  /* ---------------------------------------------------------------- charts */
  function drawChart(cfg, frames) {
    var canvas = $(cfg.id);
    if (!canvas) { return; }
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) { return; }
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    var pad = { l: 40, r: 10, t: 24, b: 18 };
    var pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
    function yOf(v) { return pad.t + ph * (1 - (v - cfg.min) / (cfg.max - cfg.min)); }

    ctx.font = "11px -apple-system, Segoe UI, Roboto, sans-serif";
    ctx.textBaseline = "middle";

    // horizontal grid + labels
    ctx.strokeStyle = "#25313e"; ctx.fillStyle = "#8396a9"; ctx.lineWidth = 1;
    ctx.textAlign = "right";
    for (var i = 0; i <= 4; i++) {
      var gv = cfg.min + (cfg.max - cfg.min) * i / 4;
      var gy = Math.round(yOf(gv)) + 0.5;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w - pad.r, gy); ctx.stroke();
      ctx.fillText(String(Math.round(gv * 10) / 10), pad.l - 6, gy);
    }

    // threshold lines
    ctx.setLineDash([5, 4]);
    cfg.lines.forEach(function (line) {
      var ly = Math.round(yOf(line.y)) + 0.5;
      ctx.strokeStyle = line.color; ctx.fillStyle = line.color;
      ctx.beginPath(); ctx.moveTo(pad.l, ly); ctx.lineTo(w - pad.r, ly); ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(line.label, w - pad.r - 2, ly - 7);
    });
    ctx.setLineDash([]);

    // series (right-aligned: newest sample at the right edge)
    cfg.series.forEach(function (s) {
      var values = frames.map(function (f) { return f.values[s.tag]; })
                         .filter(function (v) { return typeof v === "number"; });
      if (values.length < 2) { return; }
      ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
      values.forEach(function (v, idx) {
        var x = pad.l + pw * (idx + (WINDOW - values.length)) / (WINDOW - 1);
        var y = Math.max(pad.t, Math.min(pad.t + ph, yOf(v)));
        if (idx === 0) { ctx.moveTo(x, y); } else { ctx.lineTo(x, y); }
      });
      ctx.stroke();
    });

    // title + legend
    ctx.textAlign = "left"; ctx.fillStyle = "#d9e2ec";
    ctx.font = "bold 12px -apple-system, Segoe UI, Roboto, sans-serif";
    ctx.fillText(cfg.title, pad.l, 11);
    var lx = w - pad.r;
    ctx.font = "11px -apple-system, Segoe UI, Roboto, sans-serif";
    ctx.textAlign = "right";
    cfg.series.slice().reverse().forEach(function (s) {
      ctx.fillStyle = s.color;
      ctx.fillText(s.name, lx, 11);
      lx -= ctx.measureText(s.name).width + 14;
    });
  }

  /* ----------------------------------------------------------- plant status */
  function buildStatic() {
    var pumps = $("pumps");
    PUMPS.forEach(function (p) {
      var card = el("div", "pump stopped");
      card.id = "pump-" + p.tag;
      var left = el("div");
      left.appendChild(el("div", "name", p.name));
      left.appendChild(el("span", "tag", p.tag));
      var note = el("span", "note", "");
      note.id = "note-" + p.tag;
      left.appendChild(note);
      card.appendChild(left);
      var state = el("span", "state", "-");
      state.id = "state-" + p.tag;
      card.appendChild(state);
      pumps.appendChild(card);
    });
    var tiles = $("tiles");
    TILES.forEach(function (t) {
      var tile = el("div", "tile");
      tile.appendChild(el("div", "label", t.label + " " + t.tag));
      var value = el("div", "value", "-");
      value.id = "tile-" + t.tag;
      var unit = el("span", "unit", t.unit);
      value.appendChild(unit);
      tile.appendChild(value);
      tiles.appendChild(tile);
    });
  }

  function renderStatus(frame) {
    if (!frame) { return; }
    PUMPS.forEach(function (p) {
      var running = frame.status[p.tag] === true;
      var commanded = frame.commands && frame.commands[p.tag] === true;
      var refused = commanded && !running;
      var card = $("pump-" + p.tag);
      card.className = "pump " + (running ? "running" : "stopped") + (refused ? " refused" : "");
      $("state-" + p.tag).textContent = running ? "RUNNING" : "STOPPED";
      $("note-" + p.tag).textContent = refused ? "start command refused" : "";
    });
    TILES.forEach(function (t) {
      var node = $("tile-" + t.tag);
      node.firstChild.nodeValue = fmt(frame.values[t.tag], t.digits);
    });
  }

  /* ------------------------------------------------------------------ alerts */
  var lastAlertSignature = "";

  function renderAlerts(alerts) {
    $("alert-count").textContent = String(alerts.length);
    var signature = JSON.stringify(alerts.map(function (a) {
      return [a.id, a.status, a.severity, a.title, a.evidence.length,
        a.hypotheses.length, a.operator_explanation.length, a.triage_tier];
    }));
    if (signature === lastAlertSignature) { return; }
    lastAlertSignature = signature;

    var box = $("alerts");
    box.textContent = "";
    if (!alerts.length) {
      box.appendChild(el("div", "empty", "No alerts. The plant behaves as the approved PLC logic expects."));
      return;
    }
    alerts.forEach(function (alert) {
      var card = el("div", "alert sev-" + alert.severity);
      var head = el("div", "alert-head");
      head.appendChild(el("span", "sev", alert.severity.toUpperCase()));
      head.appendChild(el("span", "", alert.id));
      head.appendChild(el("span", "", clock(alert.ts)));
      card.appendChild(head);
      card.appendChild(el("div", "alert-title", alert.title));

      var list = el("ul", "evidence");
      alert.evidence.forEach(function (ev) {
        var item = el("li");
        var top = el("div", "ev-top");
        top.appendChild(el("span", "ev-id", ev.id));
        top.appendChild(el("span", "badge", KIND_LABEL[ev.kind] || ev.kind));
        top.appendChild(el("span", "badge", "rule-based"));
        item.appendChild(top);
        item.appendChild(el("div", "", ev.summary));
        list.appendChild(item);
      });
      card.appendChild(list);
      renderAnalysis(card, alert);

      if (alert.status === "open") {
        var actions = el("div", "actions");
        [["approve", "Approve"], ["reject", "Reject"], ["deferred", "Defer"]].forEach(function (pair) {
          var decision = pair[0] === "approve" ? "approved" : (pair[0] === "reject" ? "rejected" : "deferred");
          var button = el("button", pair[0], pair[1]);
          button.type = "button";
          button.addEventListener("click", function () { decide(alert.id, decision); });
          actions.appendChild(button);
        });
        card.appendChild(actions);
      } else {
        var done = el("div", "decided", "Decision: ");
        done.appendChild(el("b", "", alert.status));
        card.appendChild(done);
      }
      box.appendChild(card);
    });
  }

  function renderAnalysis(card, alert) {
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

  function decide(alertId, decision) {
    api("/api/alerts/" + encodeURIComponent(alertId) + "/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision: decision })
    }).then(refresh).catch(showOffline);
  }

  /* --------------------------------------------------------------- scenarios */
  var scenariosBuilt = false;

  function buildScenarios(list) {
    var box = $("scenarios");
    list.forEach(function (s) {
      if (s.name === "normal") { return; }
      var button = el("button", "sc");
      button.type = "button";
      button.dataset.name = s.name;
      button.appendChild(el("span", "t", s.name.replace(/_/g, " ")));
      button.appendChild(el("span", "d", s.description));
      button.addEventListener("click", function () {
        api("/api/scenarios/" + encodeURIComponent(s.name) + "/start", { method: "POST" })
          .then(refresh).catch(showOffline);
      });
      box.appendChild(button);
    });
    scenariosBuilt = true;
  }

  function markActiveScenario(name) {
    $("demo-label").textContent = name;
    var buttons = document.querySelectorAll(".sc");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle("active", buttons[i].dataset.name === name);
    }
  }

  /* -------------------------------------------------------------------- loop */
  var busy = false;

  function showOffline() {
    var pill = $("live");
    pill.textContent = "offline";
    pill.className = "pill off";
  }

  function showLive() {
    var pill = $("live");
    pill.textContent = "live";
    pill.className = "pill on";
  }

  function refresh() {
    if (busy) { return Promise.resolve(); }
    busy = true;
    var tasks = [api("/api/state"), api("/api/telemetry?n=" + WINDOW), api("/api/alerts")];
    if (!scenariosBuilt) { tasks.push(api("/api/scenarios")); }
    return Promise.all(tasks).then(function (results) {
      var state = results[0], frames = results[1], alerts = results[2];
      if (!scenariosBuilt && results[3]) { buildScenarios(results[3]); }
      showLive();
      renderStatus(state.latest);
      CHARTS.forEach(function (cfg) { drawChart(cfg, frames); });
      renderAlerts(alerts);
      markActiveScenario(state.demo_scenario);
      renderLlm(state.llm);
    }).catch(showOffline).then(function () { busy = false; });
  }

  function init() {
    buildStatic();
    $("btn-normal").addEventListener("click", function () {
      api("/api/scenarios/stop", { method: "POST" }).then(refresh).catch(showOffline);
    });
    $("btn-reset").addEventListener("click", function () {
      lastAlertSignature = "";
      api("/api/demo/reset", { method: "POST" }).then(refresh).catch(showOffline);
    });
    window.addEventListener("resize", refresh);
    refresh();
    setInterval(refresh, POLL_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
