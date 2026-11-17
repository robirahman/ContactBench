// ContactBench local play page (served only on 127.0.0.1 by `contact-bench play`).
// SECURITY: all data (clues, words, model names) is inserted with textContent /
// createTextNode only. Never use innerHTML with data.
(function () {
  "use strict";

  var TOKEN = decodeURIComponent((location.hash || "").replace(/^#/, ""));
  var state = null;
  var shownDecision = null;   // decision_id whose form is on screen
  var shownVersion = -1;
  var busy = false;

  // ---------------------------------------------------------------- helpers
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === "text") n.textContent = String(v);
      else if (k === "cls") n.className = v;
      else if (k === "onclick") n.addEventListener("click", v);
      else n.setAttribute(k, String(v));
    });
    (children || []).forEach(function (c) {
      if (c == null) return;
      n.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
    });
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
  function name(id) { return (state && state.model_names && state.model_names[id]) || id; }
  function showError(msg) { var e = $("error"); e.hidden = !msg; e.textContent = msg || ""; }
  function api(method, path, body) {
    return fetch(path, {
      method: method,
      headers: Object.assign({ "X-Play-Token": TOKEN }, body ? { "Content-Type": "application/json" } : {}),
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    });
  }
  function prefixText(p) { return p ? p : "(empty)"; }
  function num(x, d) { return x == null ? "—" : Number(x).toFixed(d == null ? 2 : d); }
  function words(s) {
    return String(s || "").toLowerCase().split(/[\s,;]+/).filter(function (w) { return w.length; });
  }

  // ----------------------------------------------------------------- status
  function renderStatus() {
    var s = state, cur = s.current, box = $("status-box"), p = $("status");
    $("who").textContent = "Player: " + s.display_name + " · run " + s.run_id;
    var text;
    if (s.status === "finished") text = "All available games are done. Your results are on the right; the run is saved.";
    else if (s.status === "stopped") text = "Paused. " + (s.message ? s.message + " " : "") +
      "Every recorded move is saved; resume with: contact-bench play --resume " + s.run_id;
    else if (!cur) text = "Starting…";
    else {
      var role = cur.role === "attack"
        ? "You attack as Guesser 1 with " + name(cur.teammate) + " as Guesser 2, against " + name(cur.opponent) + " defending."
        : "You defend against two instances of " + name(cur.opponent) + ".";
      text = (s.status === "your_turn" ? "Your move. " : "Waiting for the models… ") + role +
        " (game " + cur.game_id + ")";
    }
    p.textContent = text;
    box.className = "status" + (s.status === "your_turn" ? " your-turn" : "");
    $("stop").disabled = s.status === "stopped" || s.status === "finished";
  }

  // ---------------------------------------------------------------- history
  function blockText(e) {
    var parts = [];
    if (e.blocklist && e.blocklist.length) parts.push(e.blocklist.join(", "));
    (e.blocked_ranges || []).forEach(function (r) { parts.push("range " + r[0] + "–" + r[1]); });
    var t = parts.length ? parts.join("; ") : "nothing";
    if (e.blocked_word_count != null) t += " (" + e.blocked_word_count + " words)";
    return t;
  }
  function resultPill(e) {
    if (e.result === "won") return el("span", { cls: "pill win", text: "win" });
    if (e.result === "prefix_extended") return el("span", { cls: "pill ok", text: "letter → " + e.prefix_after });
    if (e.type === "invalid_action") return el("span", { cls: "pill", text: "invalid move" });
    if (e.type === "direct") return el("span", { cls: "pill", text: "wrong guess" });
    return el("span", { cls: "pill", text: "no letter" });
  }
  function renderHistory(obs) {
    var t = clear($("history"));
    t.appendChild(el("thead", null, [el("tr", null, [
      el("th", { text: "Turn" }), el("th", { text: "Clue / move" }), el("th", { text: "Blocked" }),
      el("th", { text: "Opened guesses" }), el("th", { text: "Result" })])]));
    var body = el("tbody");
    (obs.public_history || []).forEach(function (e) {
      var move = e.type === "clue_round" ? el("span", { cls: "clue", text: "“" + e.clue + "”" })
        : e.type === "direct" ? el("span", null, ["Direct guess: ", el("span", { cls: "mono", text: e.word })])
        : el("span", { cls: "note", text: "Guesser 1's move was invalid" });
      var opened = (e.opened_guesses || []).map(function (g) { return g.seat.replace("guesser", "G") + ": " + g.word; }).join(", ");
      body.appendChild(el("tr", null, [
        el("td", { text: String(e.turn) }), el("td", { cls: "wrap" }, [move]),
        el("td", { cls: "wrap words", text: e.type === "clue_round" ? blockText(e) : "" }),
        el("td", { cls: "mono wrap", text: opened }), el("td", null, [resultPill(e)])]));
    });
    if (!(obs.public_history || []).length) body.appendChild(el("tr", null, [el("td", { colspan: 5, text: "No turns yet." })]));
    t.appendChild(body);
    var used = obs.used_words || [], ranges = obs.used_ranges || [];
    $("used-summary").textContent = "Used words: " + used.length + (ranges.length ? " + " + ranges.length + " used range(s)" : "");
    $("used").textContent = used.join(", ") + (ranges.length ? (used.length ? "; " : "") + ranges.map(function (r) { return r[0] + "–" + r[1]; }).join("; ") : "");
    var pb = clear($("private-box"));
    var priv = obs.own_private_history || [];
    if (priv.length) {
      pb.appendChild(el("h3", { text: "Your private notes (only you see these)" }));
      var ul = el("ul", { cls: "words" });
      priv.forEach(function (h) {
        var bits = Object.keys(h).filter(function (k) { return k !== "turn"; }).map(function (k) {
          var v = h[k]; return k + ": " + (typeof v === "object" ? JSON.stringify(v) : String(v));
        });
        ul.appendChild(el("li", { text: "Turn " + h.turn + " — " + bits.join(", ") }));
      });
      pb.appendChild(ul);
    }
    $("history-box").hidden = false;
  }

  // ------------------------------------------------------------------ forms
  function submitAction(action, force) {
    if (busy) return;
    busy = true;
    $("check").textContent = "Submitting…";
    api("POST", "/api/decide", { decision_id: state.pending.decision_id, action: action, force: !!force })
      .then(function (r) {
        if (r.accepted) { $("check").textContent = "Submitted."; shownDecision = null; poll(); return; }
        var c = clear($("check"));
        c.appendChild(document.createTextNode("The referee would reject this move: " + r.reason + ". Fix it, or "));
        c.appendChild(el("button", { type: "button", text: "submit anyway (the turn is lost)",
          onclick: function () { submitAction(action, true); } }));
      })
      .catch(function (e) { $("check").textContent = "Error: " + e.message; })
      .then(function () { busy = false; });
  }

  function clueCounter(textarea, counter, max) {
    function upd() {
      var s = textarea.value.replace(/^[ \t\n\r\v\f]+|[ \t\n\r\v\f]+$/g, "");
      var bad = /[^\x20-\x7e]/.test(s);
      counter.textContent = s.length + " / " + max + " characters" + (bad ? " · only printable ASCII is allowed" : "");
      counter.className = "counter" + (s.length > max || bad ? " over" : "");
    }
    textarea.addEventListener("input", upd);
    upd();
  }

  function guesser1Form(f, obs) {
    var mode = "clue";
    var rClue = el("input", { type: "radio", name: "mode", value: "clue", checked: "checked" });
    var rDirect = el("input", { type: "radio", name: "mode", value: "direct" });
    var word = el("input", { cls: "word", id: "g1-word", placeholder: "intended word", spellcheck: "false", required: "required" });
    var clue = el("textarea", { id: "g1-clue", maxlength: String(obs.clue_max_characters * 4), placeholder: "public clue for your partner" });
    var counter = el("span", { cls: "counter" });
    var clueWrap = el("label", null, ["Clue (public; the Defender sees it too)", clue, counter]);
    clueCounter(clue, counter, obs.clue_max_characters);
    function sync() {
      mode = rDirect.checked ? "direct" : "clue";
      clueWrap.hidden = mode === "direct";
      word.placeholder = mode === "direct" ? "your guess of the secret" : "intended word (private)";
    }
    rClue.addEventListener("change", sync); rDirect.addEventListener("change", sync);
    f.appendChild(el("div", { cls: "row" }, [
      el("label", { cls: "row" }, [rClue, "Give a clue"]), el("label", { cls: "row" }, [rDirect, "Direct guess"])]));
    f.appendChild(el("label", null, ["Word (must start with the prefix and be unused)", word]));
    f.appendChild(clueWrap);
    f.appendChild(el("div", { cls: "row" }, [el("button", { cls: "primary", type: "submit", text: "Submit move" })]));
    sync();
    return function () {
      return mode === "direct" ? { action: "direct", word: word.value.trim(), clue: null }
        : { action: "clue", word: word.value.trim(), clue: clue.value };
    };
  }

  function guesser2Form(f, obs) {
    var word = el("input", { cls: "word", placeholder: "your guess of Guesser 1's word", spellcheck: "false" });
    var pass = el("input", { type: "checkbox" });
    f.appendChild(el("p", null, ["Clue: ", el("span", { cls: "clue", text: "“" + obs.current_clue + "”" })]));
    f.appendChild(el("label", null, ["Word", word]));
    f.appendChild(el("label", { cls: "row" }, [pass, "Pass"]));
    f.appendChild(el("div", { cls: "row" }, [el("button", { cls: "primary", type: "submit", text: "Submit" })]));
    return function () {
      return pass.checked ? { action: "pass", word: null } : { action: "guess", word: word.value.trim() };
    };
  }

  function defenderForm(f, obs) {
    var ranges = obs.blocklist_encoding === "words_and_ranges";
    f.appendChild(el("p", null, ["Clue: ", el("span", { cls: "clue", text: "“" + obs.current_clue + "”" })]));
    f.appendChild(el("p", { cls: "note", text: "Block the words you think the guessers will both pick. Every blocked word " +
      "becomes public and used; blocking the secret itself loses the game." }));
    var ta = el("textarea", { placeholder: "words to block, separated by spaces or commas", spellcheck: "false" });
    f.appendChild(el("label", null, ["Blocked words", ta]));
    var rangeBox = el("div");
    function addRange() {
      var a = el("input", { cls: "word", placeholder: "from", spellcheck: "false" });
      var b = el("input", { cls: "word", placeholder: "to", spellcheck: "false" });
      var row = el("div", { cls: "range-row" }, [a, "–", b]);
      row.appendChild(el("button", { type: "button", text: "remove", onclick: function () { rangeBox.removeChild(row); } }));
      rangeBox.appendChild(row);
    }
    if (ranges) {
      f.appendChild(el("div", null, [el("span", { text: "Blocked ranges (every dictionary word alphabetically between two dictionary words, inclusive)" }), rangeBox,
        el("button", { type: "button", text: "add range", onclick: addRange })]));
    }
    f.appendChild(el("div", { cls: "row" }, [el("button", { cls: "primary", type: "submit", text: "Publish blocklist" })]));
    return function () {
      var out = { action: "block", words: words(ta.value) };
      if (ranges) {
        out.ranges = [];
        Array.prototype.forEach.call(rangeBox.querySelectorAll(".range-row"), function (row) {
          var ins = row.querySelectorAll("input");
          var a = ins[0].value.trim().toLowerCase(), b = ins[1].value.trim().toLowerCase();
          if (a || b) out.ranges.push({ from: a, to: b });
        });
      }
      return out;
    };
  }

  function choiceForm(f, obs) {
    f.appendChild(el("p", null, ["Clue: ", el("span", { cls: "clue", text: "“" + obs.current_clue + "”" })]));
    f.appendChild(el("p", null, ["Your partner's word was blocked. Your registered word ",
      el("span", { cls: "mono", text: obs.own_committed_word }),
      " is not. Reveal it as a public guess (it becomes used; it wins only if it is the secret), or cancel and keep it unused."]));
    var bl = (obs.published_blocklist || []);
    f.appendChild(el("p", { cls: "words", text: "Published blocklist: " + (bl.length ? bl.join(", ") : "(words only in ranges)") }));
    var chosen = null;
    f.appendChild(el("div", { cls: "row" }, [
      el("button", { cls: "primary", type: "submit", text: "Reveal", onclick: function () { chosen = "reveal"; } }),
      el("button", { type: "submit", text: "Cancel", onclick: function () { chosen = "cancel"; } })]));
    return function () { return { action: chosen || "cancel" }; };
  }

  function renderDecision() {
    var p = state.pending, sec = $("decision");
    if (!p) { sec.hidden = true; shownDecision = null; return; }
    sec.hidden = false;
    var obs = p.observation;
    $("prefix").textContent = prefixText(obs.prefix);
    $("turn").textContent = obs.turn + " of " + obs.turn_limit;
    $("secret-wrap").hidden = !obs.secret;
    $("secret").textContent = obs.secret || "";
    renderHistory(obs);
    renderLookups(p);
    if (shownDecision === p.decision_id) return;  // keep what the player is typing
    shownDecision = p.decision_id;
    $("check").textContent = "";
    var ctx = clear($("context"));
    ctx.appendChild(el("h2", { text: p.seat_label + " — " + { act: "your move", respond: "respond", block: "block", choice: "reveal or cancel" }[p.phase] }));
    var f = clear($("action-form"));
    var get = p.phase === "choice" ? choiceForm(f, obs)
      : p.seat === "guesser1" ? guesser1Form(f, obs)
      : p.seat === "guesser2" ? guesser2Form(f, obs) : defenderForm(f, obs);
    f.onsubmit = function (ev) { ev.preventDefault(); submitAction(get(), false); };
    var first = f.querySelector("input:not([type=radio]):not([type=checkbox]), textarea");
    if (first) first.focus();
  }

  // ---------------------------------------------------------------- lookups
  function renderLookups(p) {
    var box = $("lookup-box");
    box.hidden = !p || !p.max_lookups;
    if (box.hidden) return;
    $("lookups-left").textContent = p.lookups_remaining + " of " + p.max_lookups + " left for this move.";
    var out = clear($("lookup-results"));
    p.lookup_results.slice().reverse().forEach(function (r) {
      var args = Object.keys(r.args || {}).map(function (k) { return k + "=" + JSON.stringify(r.args[k]); }).join(", ");
      var res = r.error ? "error: " + r.error : Array.isArray(r.result) ? (r.result.length ? r.result.join(", ") : "(none)") : String(r.result);
      out.appendChild(el("div", { cls: "lookup" }, [el("div", { cls: "call", text: r.name + "(" + args + ")" }), el("div", { text: res })]));
    });
  }
  $("lookup-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (!state || !state.pending) return;
    var fn = $("lookup-fn").value, arg = $("lookup-arg").value.trim().toLowerCase();
    var args = fn === "is_legal_word" ? { word: arg } : { prefix: arg };
    if (fn === "list_words") { args.offset = Math.max(0, parseInt($("lookup-offset").value, 10) || 0); args.limit = 100; }
    api("POST", "/api/lookup", { decision_id: state.pending.decision_id, name: fn, args: args })
      .then(function () { poll(); })
      .catch(function (e) { showError(e.message); });
  });

  // ---------------------------------------------------------------- results
  function legText(leg, attack) {
    if (!leg) return "—";
    var c = leg.cost == null ? "—" : num(leg.cost);
    var how = leg.outcome === "solved" ? "solved turn " + leg.turns_used : "capped, reached " + prefixText(leg.final_prefix);
    return (attack ? "your team: " : "their team: ") + c + " (" + how + "; reference " + num(leg.reference_cost) + ")";
  }
  function renderResults() {
    var s = state.summary;
    $("score").textContent = s.complete + " of " + s.fixtures + " fixtures complete · " + s.points +
      " match points. Lower cost is better; you win a fixture when your team's attacking cost beats the model team's.";
    var t = clear($("results"));
    t.appendChild(el("thead", null, [el("tr", null, [el("th", { text: "Opponent" }), el("th", { text: "Secret" }),
      el("th", { text: "Your attack" }), el("th", { text: "Your defense" }), el("th", { text: "Points" })])]));
    var body = el("tbody");
    state.fixtures.forEach(function (r) {
      if (!r.attack && !r.defend) return;
      body.appendChild(el("tr", null, [
        el("td", { text: name(r.opponent) }),
        el("td", { cls: "mono", text: r.attack ? r.attack.secret : "—" }),
        el("td", { cls: "wrap", text: legText(r.attack, true) }),
        el("td", { cls: "wrap", text: legText(r.defend, false) }),
        el("td", { text: r.points == null ? "—" : String(r.points) + (r.draw ? " (no-progress draw)" : "") })]));
    });
    if (!body.firstChild) body.appendChild(el("tr", null, [el("td", { colspan: 5, text: "No finished games yet." })]));
    t.appendChild(body);
  }

  // ------------------------------------------------------------------- loop
  function render() {
    renderStatus();
    renderDecision();
    renderResults();
    if (!state.pending) $("history-box").hidden = true;
  }
  function poll() {
    return api("GET", "/api/state").then(function (s) {
      showError("");
      state = s;
      if (s.version !== shownVersion) { shownVersion = s.version; render(); }
    }).catch(function (e) { showError("Lost contact with the local server: " + e.message); });
  }
  $("stop").addEventListener("click", function () {
    api("POST", "/api/stop", {}).then(poll).catch(function (e) { showError(e.message); });
  });
  if (!TOKEN) showError("This page needs the link printed by `contact-bench play` (it carries a session token).");
  poll();
  setInterval(function () { if (!busy) poll(); }, 1000);
})();
