// ContactBench highlights page.
// SECURITY: every piece of data (clues, words, model ids, commentary) is inserted
// with textContent / createTextNode only. Never use innerHTML with data.
(function () {
  "use strict";

  var MODEL_NAMES = {
    claude_haiku_5_5: "Claude Haiku 5.5", claude_haiku_4_5: "Claude Haiku 4.5",
    claude_sonnet_5_5: "Claude Sonnet 5.5", gpt_6_luna: "GPT-6 Luna", gpt_6_1_terra: "GPT-6.1 Terra",
    gemini_4_hydrogen: "Gemini 4 Hydrogen", gemini_4_argon: "Gemini 4 Argon", gemini_3_8_flash: "Gemini 3.8 Flash"
  };
  function name(id) { return MODEL_NAMES[id] || id; }

  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (k === "text") n.textContent = v;
        else if (k === "cls") n.className = v;
        else if (k === "onclick") n.addEventListener("click", v);
        else n.setAttribute(k, v);
      });
    }
    (children || []).forEach(function (c) {
      if (c == null) return;
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }

  function prefixText(p) { return p ? p : "(empty)"; }

  function blockCell(t) {
    var parts = [];
    if (t.block_size === 0) return el("span", { cls: "words", text: "nothing" });
    var shown = (t.block_words || []).join(", ");
    if (t.block_words_total > (t.block_words || []).length) shown += " … (" + t.block_words_total + " listed)";
    if (shown) parts.push(el("span", { cls: "words", text: shown }));
    (t.block_ranges || []).forEach(function (r) {
      if (parts.length) parts.push(document.createTextNode("; "));
      parts.push(el("span", { cls: "words", text: "range " + r[0] + "–" + r[1] }));
    });
    var total = el("div", { cls: "note", text: t.block_size + " word" + (t.block_size === 1 ? "" : "s") + " blocked" });
    return el("span", null, parts.concat([total]));
  }

  function outcomePill(t, g) {
    if (t.kind === "invalid") return el("span", { cls: "pill miss", text: "invalid move" });
    if (t.result === "won" || t.result === "won_prefix_completed") return el("span", { cls: "pill win", text: "win" });
    if (t.kind === "direct") return el("span", { cls: "pill miss", text: "wrong guess" });
    if (t.result === "prefix_extended") return el("span", { cls: "pill ok", text: "letter → " + t.prefix_after });
    if (t.prevented) return el("span", { cls: "pill blocked", text: "blocked" });
    if (t.intended && t.receiver && t.intended !== t.receiver) return el("span", { cls: "pill miss", text: "no match" });
    return el("span", { cls: "pill miss", text: "no letter" });
  }

  function turnRow(t, g) {
    var cls = "";
    if (t.result === "prefix_extended") cls = "row-ok";
    if (t.result === "won" || t.result === "won_prefix_completed") cls = "row-win";
    var move, words;
    if (t.kind === "invalid") {
      move = el("span", { cls: "note", text: "Guesser 1's move was rejected (" + (t.note || "invalid") + "); the turn is lost." });
      words = el("span", { text: "" });
    } else if (t.kind === "direct") {
      move = el("span", null, ["Direct guess: ", el("span", { cls: "mono", text: t.word })]);
      words = el("span", { text: "" });
    } else {
      move = el("span", { cls: "clue", text: "“" + t.clue + "”" });
      var g2 = t.receiver ? t.receiver : "(pass)";
      words = el("span", { cls: "mono" }, [t.intended + " / " + g2]);
      if (t.choice) words.appendChild(el("div", { cls: "note", text: t.choice.seat.replace("guesser", "Guesser ") + " chose to " + t.choice.choice }));
    }
    return el("tr", { cls: cls }, [
      el("td", { cls: "n", text: String(t.turn) }),
      el("td", { cls: "prefix", text: prefixText(t.prefix_before) }),
      el("td", null, [move]),
      el("td", { cls: "hide-sm" }, [words]),
      el("td", { cls: "hide-sm" }, [t.kind === "clue" ? blockCell(t) : el("span", { text: "" })]),
      el("td", null, [outcomePill(t, g)])
    ]);
  }

  function gameCard(g) {
    var secret = el("span", { cls: "secret", text: g.secret });
    secret.hidden = true;
    var btn = el("button", { text: "Show secret", type: "button" });
    btn.addEventListener("click", function () {
      secret.hidden = !secret.hidden;
      btn.textContent = secret.hidden ? "Show secret" : "Hide secret";
    });
    var outcome = g.outcome === "solved"
      ? "solved on turn " + g.turns_used + (g.terminal_reason === "prefix_completed" ? " (final-letter contact)" : "")
      : "unsolved after " + g.turns_used + " turns";
    var meta = name(g.attacker) + " (attacking) vs " + name(g.defender) + " (defending) · " + outcome +
      " · start " + prefixText(g.initial_prefix) +
      (g.final_prefix === g.secret ? "" : ", end " + prefixText(g.final_prefix)) +
      " · " + g.contacts + " letter" + (g.contacts === 1 ? "" : "s") + " earned, " + g.prevented + " contacts blocked" +
      (g.rematch_level ? " · rematch level " + g.rematch_level : "");
    var tags = el("div", { cls: "tags" }, (g.tags || []).map(function (t) { return el("span", { text: t }); }));
    var table = el("table", { cls: "turns" }, [
      el("thead", null, [el("tr", null, [
        el("th", { text: "Turn" }), el("th", { text: "Prefix" }), el("th", { text: "Clue / move" }),
        el("th", { cls: "hide-sm", text: "Guesser 1 / Guesser 2" }), el("th", { cls: "hide-sm", text: "Defender blocked" }),
        el("th", { text: "Result" })
      ])]),
      el("tbody", null, g.turns.map(function (t) { return turnRow(t, g); }))
    ]);
    return el("article", { cls: "game", id: g.id }, [
      el("h2", { text: g.title }),
      el("p", { cls: "meta", text: meta }),
      tags,
      el("p", { cls: "blurb", text: g.blurb }),
      el("div", { cls: "secret-row" }, [btn, secret]),
      el("div", { cls: "scroll" }, [table]),
      el("p", { cls: "note", text: "Run " + g.run_id + " · game " + g.game_id + " · " + g.condition.lexicon +
        " (" + g.condition.lexicon_words + " words), " + g.condition.dictionary_access + ", turn cap " + g.turn_limit })
    ]);
  }

  fetch("highlights.json").then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (data) {
    document.getElementById("intro").textContent = data.intro || "";
    var toc = document.getElementById("toc");
    var box = document.getElementById("games");
    while (box.firstChild) box.removeChild(box.firstChild);
    data.games.forEach(function (g) {
      toc.appendChild(el("a", { href: "#" + g.id, text: g.title }));
      box.appendChild(gameCard(g));
    });
  }).catch(function (e) {
    var box = document.getElementById("games");
    while (box.firstChild) box.removeChild(box.firstChild);
    box.appendChild(el("p", { cls: "error", text: "Could not load highlights: " + e.message }));
  });
})();
