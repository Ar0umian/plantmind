/* PlantMind - operator assistant panel (plain JavaScript, no external libraries). */
(function () {
  "use strict";

  var SUGGESTIONS = ["What is happening?", "What should I check first?",
                     "Is the PLC program the approved one?", "What does IL-04 do?",
                     "What is the chlorine level?"];
  var MODE_NOTE = { mock: "mock model (offline demo)", live: "Nemotron", unavailable: "unavailable",
                    blocked: "advisory only" };
  var history = [];
  var pending = false;

  function $(id) { return document.getElementById(id); }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function addMessage(role, text, reply) {
    var log = $("chat-log");
    var box = el("div", "msg " + role);
    box.appendChild(el("div", "msg-text", text));
    if (reply) {
      var meta = el("div", "msg-meta");
      meta.appendChild(el("span", "badge", MODE_NOTE[reply.mode] || reply.mode));
      (reply.sources || []).forEach(function (id) { meta.appendChild(el("span", "chip", id)); });
      box.appendChild(meta);
    }
    log.appendChild(box);
    log.scrollTop = log.scrollHeight;
    return box;
  }

  function ask(question) {
    var text = question.trim();
    if (!text || pending) { return; }
    pending = true;
    $("chat-send").disabled = true;
    $("chat-input").value = "";
    addMessage("user", text);
    var waiting = addMessage("assistant", "Thinking...");
    fetch("/api/assistant/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text.slice(0, 500), history: history.slice(-6) })
    }).then(function (response) {
      if (!response.ok) { throw new Error("status " + response.status); }
      return response.json();
    }).then(function (reply) {
      waiting.remove();
      addMessage("assistant", reply.answer, reply);
      history.push({ role: "user", text: text.slice(0, 500) });
      history.push({ role: "assistant", text: reply.answer.slice(0, 500) });
    }).catch(function () {
      waiting.remove();
      addMessage("assistant", "The assistant could not be reached.");
    }).then(function () {
      pending = false;
      $("chat-send").disabled = false;
      $("chat-input").focus();
    });
  }

  function init() {
    if (!$("assistant-panel")) { return; }
    var box = $("chat-suggestions");
    SUGGESTIONS.forEach(function (text) {
      var button = el("button", "sugg", text);
      button.type = "button";
      button.addEventListener("click", function () { ask(text); });
      box.appendChild(button);
    });
    $("chat-send").addEventListener("click", function () { ask($("chat-input").value); });
    $("chat-input").addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); ask($("chat-input").value); }
    });
    addMessage("assistant", "Ask about the current alert, an interlock, the PLC program, or live values. " +
                            "I am advisory only and cannot send commands to equipment.");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
