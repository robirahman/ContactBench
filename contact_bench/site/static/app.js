/* ContactBench static leaderboard.
 *
 * SECURITY: every piece of data (model ids, clues, words, settings) is inserted
 * with textContent / document.createTextNode via the el() helper. This file
 * never uses innerHTML, outerHTML, insertAdjacentHTML or document.write, so
 * adversarial model-generated clue text cannot execute or render as markup.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- helpers
  function el(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "text") node.textContent = String(v);
        else if (k === "cls") node.className = v;
        else if (k === "onclick") node.addEventListener("click", v);
        else node.setAttribute(k, String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined) continue;
      if (Array.isArray(c)) c.forEach(function (x) { if (x != null) node.appendChild(typeof x === "object" ? x : document.createTextNode(String(x))); });
      else node.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
    }
    return node;
  }
  function $(id) { return document.getElementById(id); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function fval(x) { return x && typeof x === "object" && "value" in x ? x.value : x; }
  function num(x, d) {
    x = fval(x);
    if (x === null || x === undefined || x === "" || isNaN(Number(x))) return "—";
    return Number(x).toFixed(d === undefined ? 3 : d);
  }
  function pct(x) { x = fval(x); return x == null ? "—" : (100 * x).toFixed(1) + "%"; }
  function ci(c, d) { return c && c.lo != null && c.hi != null ? "[" + num(c.lo, d) + ", " + num(c.hi, d) + "]" : "—"; }
  function fetchJSON(path) {
    return fetch(path).then(function (r) {
      if (!r.ok) throw new Error(path + ": HTTP " + r.status);
      return r.json();
    });
  }

  // Generic sortable table: columns = [{label, get(row) -> sortable value, fmt(row) -> text}]
  function renderTable(table, columns, rows, opts) {
    opts = opts || {};
    var state = { col: opts.sortCol === undefined ? -1 : opts.sortCol, dir: opts.sortDir || -1 };
    function draw() {
      clear(table);
      var sorted = rows.slice();
      if (state.col >= 0) {
        var g = columns[state.col].get;
        sorted.sort(function (a, b) {
          var x = g(a), y = g(b);
          if (x == null && y == null) return 0;
          if (x == null) return 1;
          if (y == null) return -1;
          if (typeof x === "string" || typeof y === "string") return state.dir * String(x).localeCompare(String(y));
          return state.dir * (x - y);
        });
      }
      var head = el("tr");
      columns.forEach(function (c, i) {
        var mark = i === state.col ? (state.dir > 0 ? " ▲" : " ▼") : "";
        head.appendChild(el("th", {
          title: c.title || null,
          onclick: c.get ? function () {
            if (state.col === i) state.dir = -state.dir; else { state.col = i; state.dir = -1; }
            draw();
          } : null,
          cls: c.get ? "clickable" : null
        }, c.label + mark));
      });
      table.appendChild(el("thead", null, head));
      var body = el("tbody");
      sorted.forEach(function (r) {
        var tr = el("tr", opts.rowClick ? { cls: "clickable", onclick: function () { opts.rowClick(r); } } : null);
        columns.forEach(function (c) { tr.appendChild(el("td", null, c.fmt ? c.fmt(r) : String(c.get(r)))); });
        body.appendChild(tr);
      });
      if (!sorted.length) body.appendChild(el("tr", null, el("td", { colspan: columns.length, text: "No data." })));
      table.appendChild(body);
    }
    draw();
  }

  // ------------------------------------------------------------- app state
  var index = null;
  var current = null; // {entry, manifest, lb, games, fixtures}

  function init() {
    fetchJSON("data/index.json").then(function (idx) {
      index = idx;
      var sel = $("condition-select");
      idx.conditions.forEach(function (c, i) {
        var access = { closed_book: "closed-book", lookup_tools: "dictionary-assisted",
                       full_candidate_lists: "full lists" }[c.condition.dictionary_access] || "full lists";
        var hc = c.condition.human_challenge;
        var label = (c.fixture_data ? "[DEMO] " : "") +
          (hc ? "Human challenge: " + hc.display_name + " — " : "") + access + ", prefix " +
          (c.condition.initial_prefix_length == null ? 1 : c.condition.initial_prefix_length) +
          ", C=" + c.condition.clue_max_characters +
          ", L=" + c.condition.turn_limit + ", " + c.condition.lexicon_name + " — run " + c.run_id +
          " (" + c.condition_key + ")";
        sel.appendChild(el("option", { value: String(i), text: label }));
      });
      sel.addEventListener("change", function () { load(Number(sel.value)); });
      if (idx.conditions.length) load(0);
      else showError("No conditions in this site build.");
    }).catch(function (e) { showError("Could not load data: " + e.message); });
  }

  function showError(msg) { var p = $("load-error"); p.hidden = false; p.textContent = msg; }

  function load(i) {
    var entry = index.conditions[i];
    var base = "data/" + encodeURIComponent(entry.entry_id) + "/";
    Promise.all([
      fetchJSON(base + "manifest.json"),
      fetchJSON(base + "leaderboard.json"),
      fetchJSON(base + "games.json"),
      fetchJSON(base + "fixtures.json").catch(function () { return []; })
    ]).then(function (res) {
      current = { entry: entry, base: base, manifest: res[0], lb: res[1], games: res[2], fixtures: res[3] };
      renderAll();
    }).catch(function (e) { showError("Could not load condition: " + e.message); });
  }

  function models() {
    var m = current.lb.models || (current.manifest.models || []).map(function (x) { return x.id; });
    return m || [];
  }

  function renderAll() {
    $("fixture-banner").hidden = !(current.manifest.fixture_data || current.entry.fixture_data);
    var note = $("release-note"), label = current.manifest.release_label || current.entry.release_label;
    note.hidden = !label;
    note.textContent = label ? String(label) : "";  // text only, never HTML
    renderCondition();
    renderRating();
    renderEfficiency();
    renderPairwise();
    renderSettings();
    renderGames();
    renderDownloads();
  }

  // ------------------------------------------------------------ condition
  function renderCondition() {
    var m = current.manifest, c = m.condition || {};
    var dl = clear($("condition-details"));
    function row(k, v) { dl.appendChild(el("dt", { text: k })); dl.appendChild(el("dd", { text: v == null ? "—" : String(v) })); }
    row("Protocol version", m.protocol_version);
    row("Schema version", m.schema_version);
    row("Run", m.run_id);
    row("Run created", m.run_created_at);
    row("Exported", m.exported_at);
    row("Clue character budget C", c.clue_max_characters);
    row("Turn cap L", c.turn_limit);
    row("Dictionary access", c.dictionary_access || "full_candidate_lists");
    row("Initial prefix length", c.initial_prefix_length == null ? 1 : c.initial_prefix_length);
    row("Blocklist encoding", c.blocklist_encoding || "words");
    row("Lookup calls per decision", c.dictionary_access === "lookup_tools" ? c.max_tool_calls_per_decision : "n/a");
    row("Literal-mention count cap", c.count_cap == null ? "none (character budget only)" : c.count_cap);
    row("Lexicon", (c.lexicon_name || "") + " (sha256 " + String(c.lexicon_sha256 || "").slice(0, 16) + "…)" +
      (m.lexicon ? ", " + m.lexicon.word_count + " words, license: " + m.lexicon.license : ""));
    row("Resolver", c.resolver);
    row("Packing / RNG versions", (c.packing_version || "—") + " / " + (c.rng_version || "—"));
    row("Numerical rollouts", c.numerical_rollouts);
    row("Timing", c.timing);
    row("Reveal policy", c.reveal_policy);
    row("Target-hit scope", c.target_hit_scope);
    row("Forecast mode", c.forecast_mode);
    row("Prompt version", m.prompt_version);
    row("Code revision", m.code_revision);
    row("Condition key", m.condition_key);
  }

  // --------------------------------------------------------------- rating
  function renderRating() {
    var lb = current.lb, rating = lb.rating || {}, elo = rating.elo || {}, stats = lb.model_stats || {};
    var boot = (lb.bootstrap && lb.bootstrap.intervals_95) || {};
    var rows = models().map(function (m) {
      var s = stats[m] || {}, b = boot[m] || {};
      return { m: m, elo: elo[m], eloCI: b.elo, rankCI: b.rank, share: s.match_point_share,
        w: s.wins, d: s.draws, l: s.losses, fixtures: s.fixtures, pts: s.match_points };
    });
    renderTable($("rating-table"), [
      { label: "Model", get: function (r) { return r.m; }, fmt: function (r) { return r.m; } },
      { label: "Elo", get: function (r) { return r.elo; }, fmt: function (r) { return num(r.elo, 0); } },
      { label: "Elo 95% CI", get: function (r) { return r.eloCI ? r.eloCI.lo : null; }, fmt: function (r) { return ci(r.eloCI, 0); } },
      { label: "Rank 95% CI", get: function (r) { return r.rankCI ? r.rankCI.lo : null; }, fmt: function (r) { return ci(r.rankCI, 0); } },
      { label: "Match-point share (per fixture)", get: function (r) { return r.share; }, fmt: function (r) { return num(r.share); } },
      { label: "W / D / L", get: function (r) { return r.w; }, fmt: function (r) { return (r.w == null ? "—" : r.w + " / " + r.d + " / " + r.l); } },
      { label: "Fixtures (n)", get: function (r) { return r.fixtures; }, fmt: function (r) { return r.fixtures == null ? "—" : String(r.fixtures); } }
    ], rows, { sortCol: 1 });
    var notes = clear($("rating-notes"));
    var parts = [];
    parts.push("Fit converged: " + (rating.converged ? "yes" : "no") + " (iterations " + (rating.iterations == null ? "—" : rating.iterations) +
      ", penalty scale " + (rating.penalty_scale == null ? "—" : rating.penalty_scale) + ").");
    if (lb.bootstrap) parts.push("Bootstrap: " + lb.bootstrap.resamples + " resamples over " + lb.bootstrap.task_clusters +
      " task clusters (seed " + lb.bootstrap.seed + ", fit failures " + lb.bootstrap.fit_failures + ").");
    parts.push("Complete fixtures: " + (lb.complete_fixtures == null ? "—" : lb.complete_fixtures) + " of " +
      (lb.planned_fixtures == null ? "—" : lb.planned_fixtures) + (lb.balanced_complete ? " (balanced, complete)." : " (PROVISIONAL — incomplete run)."));
    notes.textContent = parts.join(" ");
    renderHuman();
  }

  // Human challenge entries: a human player vs. models, rated against fixed
  // model ratings and never pooled with model-only conditions.
  function renderHuman() {
    var box = $("human-board");
    if (!box) return;
    clear(box);
    var lb = current.lb, hc = (current.manifest.condition || {}).human_challenge;
    box.hidden = !hc;
    if (!hc) return;
    box.appendChild(el("h3", { text: "Human challenge: " + hc.display_name }));
    box.appendChild(el("p", { cls: "note", text: "A human player attacks as Guesser 1 with the opponent model as " +
      "Guesser 2, and defends against a two-instance team of the opponent model, on the same secret (attack leg first). " +
      "This is a separate condition: these fixtures are never pooled into the model ratings above or on other boards. " +
      "Play it yourself with `contact-bench play` (docs/human_play.md in the repository)." }));
    var ar = lb.anchored_rating;
    if (!ar) {
      box.appendChild(el("p", { cls: "note", text: "No anchored rating in this export (analyze with --anchor)." }));
      return;
    }
    var rows = (ar.free || []).map(function (m) {
      return { m: hc.display_name && m === hc.player ? hc.display_name : m, elo: ar.elo[m], se: (ar.elo_se_approx || {})[m], fixed: false };
    }).concat(Object.keys(ar.fixed_elo || {}).map(function (m) { return { m: m, elo: ar.fixed_elo[m], se: null, fixed: true }; }));
    var t = el("table");
    renderTable(t, [
      { label: "Player", get: function (r) { return r.m; }, fmt: function (r) { return r.m + (r.fixed ? " (fixed)" : ""); } },
      { label: "Elo", get: function (r) { return r.elo; }, fmt: function (r) { return num(r.elo, 0); } },
      { label: "± approx. s.e.", get: function (r) { return r.se; }, fmt: function (r) { return r.se == null ? "—" : num(r.se, 0); } }
    ], rows, { sortCol: 1 });
    box.appendChild(el("div", { cls: "scroll" }, t));
    box.appendChild(el("p", { cls: "note", text: "Anchored to run " + (ar.anchor_run_id || "—") + "; " + ar.results +
      " complete fixtures; opponents' Elo held fixed, same penalty as the model fit." }));
  }

  // ----------------------------------------------------------- efficiency
  function renderEfficiency() {
    var lb = current.lb, stats = lb.model_stats || {}, boot = (lb.bootstrap && lb.bootstrap.intervals_95) || {};
    var rows = models().map(function (m) {
      var s = stats[m] || {}, b = boot[m] || {};
      return { m: m, sp: fval(s.offense_aggregate_speedup), spCI: b.offense_aggregate_speedup,
        cost: fval(s.offense_mean_effective_cost), base: fval(s.offense_mean_baseline), og: s.offense_games,
        adv: fval(s.mean_paired_cost_advantage), advCI: b.mean_paired_cost_advantage,
        dcr: fval(s.defensive_cost_ratio), dcrCI: b.defensive_cost_ratio, dg: s.defense_games,
        hold: s.defense_deadline_hold_rate_of_defense_games, capped: s.offense_capped_fraction_of_offense_games,
        med: s.offense_median_effective_cost, medCI: b.offense_median_effective_cost,
        geo: s.offense_geometric_mean_cost, dmed: s.defense_median_cost_imposed };
    });
    renderTable($("efficiency-table"), [
      { label: "Model", get: function (r) { return r.m; }, fmt: function (r) { return r.m; } },
      { label: "Offense speedup ΣB/ΣC", get: function (r) { return r.sp; }, fmt: function (r) { return num(r.sp); } },
      { label: "Speedup 95% CI", get: function (r) { return r.spCI ? r.spCI.lo : null; }, fmt: function (r) { return ci(r.spCI); } },
      { label: "Median effective cost (turns)", get: function (r) { return r.med; }, fmt: function (r) { return num(r.med); } },
      { label: "Median 95% CI", get: function (r) { return r.medCI ? r.medCI.lo : null; }, fmt: function (r) { return ci(r.medCI); } },
      { label: "Geometric-mean cost", get: function (r) { return r.geo; }, fmt: function (r) { return num(r.geo); } },
      { label: "Mean effective cost (turns)", get: function (r) { return r.cost; }, fmt: function (r) { return num(r.cost); } },
      { label: "Mean reference B", get: function (r) { return r.base; }, fmt: function (r) { return num(r.base); } },
      { label: "Offense games (n)", get: function (r) { return r.og; }, fmt: function (r) { return r.og == null ? "—" : String(r.og); } },
      { label: "Mean paired cost advantage", get: function (r) { return r.adv; }, fmt: function (r) { return num(r.adv); } },
      { label: "Advantage 95% CI", get: function (r) { return r.advCI ? r.advCI.lo : null; }, fmt: function (r) { return ci(r.advCI); } },
      { label: "Median cost imposed as defender", get: function (r) { return r.dmed; }, fmt: function (r) { return num(r.dmed); } },
      { label: "Defensive cost ratio ΣC/ΣB", get: function (r) { return r.dcr; }, fmt: function (r) { return num(r.dcr); } },
      { label: "Deadline hold rate (per defended game)", get: function (r) { return r.hold; }, fmt: function (r) { return pct(r.hold); } },
      { label: "Defense games (n)", get: function (r) { return r.dg; }, fmt: function (r) { return r.dg == null ? "—" : String(r.dg); } },
      { label: "Capped (per offense game)", get: function (r) { return r.capped; }, fmt: function (r) { return pct(r.capped); } }
    ], rows, { sortCol: 1 });
  }

  // ------------------------------------------------------------- pairwise
  function matrix(table, data, field, d) {
    clear(table);
    var ms = models();
    var head = el("tr", null, el("th", { text: "row \\ column" }));
    ms.forEach(function (m) { head.appendChild(el("th", { text: m })); });
    table.appendChild(el("thead", null, head));
    var body = el("tbody");
    ms.forEach(function (a) {
      var tr = el("tr", null, el("th", { text: a }));
      ms.forEach(function (b) {
        var cell = data && data[a] && data[a][b];
        var n = cell ? (cell.fixtures != null ? cell.fixtures : cell.games) : null;
        tr.appendChild(el("td", { title: n != null ? "n = " + n : null }, cell ? num(cell[field], d) + " (n=" + n + ")" : "—"));
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
  }

  function renderPairwise() {
    var lb = current.lb;
    matrix($("points-matrix"), lb.pairwise_match_points, "mean_points", 3);
    matrix($("cost-matrix"), lb.pairwise_mean_cost, "mean_cost", 3);
    var notes = clear($("pairwise-notes"));
    var comps = (lb.rating && lb.rating.connected_components) || [];
    notes.appendChild(el("p", null, "Schedule connectivity: " + comps.length + " component(s): " +
      comps.map(function (c) { return "{" + c.join(", ") + "}"; }).join(" ") +
      (comps.length > 1 ? " — ratings in different components are not comparable." : "")));
    var missing = lb.missing_model_pairs || [];
    notes.appendChild(el("p", null, "Missing or incomplete model pairs: " +
      (missing.length ? missing.map(function (p) { return p.join(" vs "); }).join("; ") : "none")));
    var sens = lb.rating_penalty_sensitivity || {};
    var keys = Object.keys(sens);
    if (keys.length) {
      var t = el("table");
      var hr = el("tr", null, el("th", { text: "Penalty scale" }));
      models().forEach(function (m) { hr.appendChild(el("th", { text: m })); });
      t.appendChild(el("thead", null, hr));
      var tb = el("tbody");
      keys.forEach(function (k) {
        var tr = el("tr", null, el("td", { text: k }));
        models().forEach(function (m) { tr.appendChild(el("td", { text: num(sens[k][m], 0) })); });
        tb.appendChild(tr);
      });
      t.appendChild(tb);
      notes.appendChild(el("h3", { text: "Rating sensitivity to the penalty scale" }));
      notes.appendChild(el("div", { cls: "scroll" }, t));
    }
    if (lb.numerically_close_fixtures != null)
      notes.appendChild(el("p", null, "Fixtures whose cost difference is within 2 numerical standard errors: " + lb.numerically_close_fixtures + "."));
  }

  // ------------------------------------------------------------- settings
  function renderSettings() {
    var profiles = (current.manifest.models || []).map(function (m) { return m || {}; });
    renderTable($("profiles-table"), [
      { label: "Model", get: function (r) { return r.id; }, fmt: function (r) { return r.id; } },
      { label: "Provider", get: function (r) { return r.provider; }, fmt: function (r) { return r.provider || "—"; } },
      { label: "API family", get: function (r) { return r.api_family; }, fmt: function (r) { return r.api_family || "—"; } },
      { label: "Model id / policy", get: function (r) { return r.model || r.policy; }, fmt: function (r) {
        return r.model || [r.policy, r.defender_policy, r.choice_policy].filter(Boolean).join(" / ") || "—"; } },
      { label: "Parameters", fmt: function (r) { return r.parameters ? JSON.stringify(r.parameters) : "—"; } },
      { label: "Max output tokens", get: function (r) { return r.max_output_tokens; }, fmt: function (r) { return r.max_output_tokens == null ? "—" : String(r.max_output_tokens); } },
      { label: "Offense condition", fmt: function (r) { return r.offense_mode || "—"; } },
      { label: "Prompt version", fmt: function (r) { return r.prompt_version || "—"; } }
    ], profiles);

    var res = current.lb.resources || {}, rrows = [];
    Object.keys(res).forEach(function (m) {
      Object.keys(res[m] || {}).forEach(function (seat) { var v = res[m][seat] || {}; v = Object.assign({ m: m, seat: seat }, v); rrows.push(v); });
    });
    function n0(k) { return { label: k.replace(/_/g, " "), get: function (r) { return r[k]; }, fmt: function (r) { return r[k] == null ? "—" : String(Math.round(r[k] * 1000) / 1000); } }; }
    renderTable($("resources-table"), [
      { label: "Model", get: function (r) { return r.m; }, fmt: function (r) { return r.m; } },
      { label: "Seat", get: function (r) { return r.seat; }, fmt: function (r) { return r.seat; } },
      n0("requests"), n0("errors"), n0("input_tokens"), n0("output_tokens"), n0("reasoning_tokens"),
      n0("cached_input_tokens"), n0("transport_attempts"), n0("latency_s"), n0("cost_estimate"), n0("refusals"), n0("incomplete")
    ], rrows);
    if (!rrows.length) $("resources-table").appendChild(el("caption", { text: "No provider requests recorded (scripted/offline run)." }));

    var rd = current.lb.role_diagnostics || {}, drows = [];
    Object.keys(rd).forEach(function (m) {
      var o = (rd[m] || {}).offense || {}, d = (rd[m] || {}).defense || {}, orates = o.rates || {}, drates = d.rates || {};
      drows.push({ m: m, clue: o.clue_turns, direct: o.direct_turns, matches: o.registered_matches, contacts: o.contacts_awarded,
        prevented: o.contacts_prevented, cpc: orates.contact_per_clue_turn, opp: o.choice_opportunities, rev: o.choice_reveal,
        can: o.choice_cancel, reused: o.preserved_words_later_reused, g1inv: orates.guesser1_invalid_per_guesser1_decision,
        g2inv: orates.guesser2_invalid_per_guesser2_decision, bsize: d.mean_blocklist_size_per_block_decision,
        empty: drates.empty_blocklist_per_block_decision, binv: drates.block_invalid_per_block_decision });
    });
    function cnt(k, label) { return { label: label, get: function (r) { return r[k]; }, fmt: function (r) { return r[k] == null ? "0" : String(r[k]); } }; }
    function rate(k, label) { return { label: label, get: function (r) { return r[k]; }, fmt: function (r) { return pct(r[k]); } }; }
    renderTable($("roles-table"), [
      { label: "Model", get: function (r) { return r.m; }, fmt: function (r) { return r.m; } },
      cnt("clue", "Clue turns"), cnt("direct", "Direct turns"), cnt("matches", "Registered matches"),
      cnt("contacts", "Contacts awarded"), rate("cpc", "Contacts per clue turn"), cnt("prevented", "Contacts prevented (as attacker)"),
      cnt("opp", "Reveal/cancel opportunities"), cnt("rev", "Reveals"), cnt("can", "Cancels"), cnt("reused", "Preserved words later reused"),
      rate("g1inv", "G1 invalid per G1 decision"), rate("g2inv", "G2 invalid per G2 decision"),
      { label: "Mean blocklist size (as defender)", get: function (r) { return r.bsize; }, fmt: function (r) { return num(r.bsize, 2); } },
      rate("empty", "Empty blocklists per block decision"), rate("binv", "Invalid blocklists per block decision")
    ], drows);

    var nr = current.lb.numerical_reference || {}, dl = clear($("numerical"));
    Object.keys(nr).forEach(function (k) {
      var v = nr[k];
      dl.appendChild(el("dt", { text: k.replace(/_/g, " ") }));
      dl.appendChild(el("dd", { text: typeof v === "object" && v !== null ? JSON.stringify(v) : String(v) }));
    });
  }

  // ---------------------------------------------------------------- games
  function fillSelect(sel, values) {
    clear(sel);
    sel.appendChild(el("option", { value: "", text: "(all)" }));
    values.forEach(function (v) { sel.appendChild(el("option", { value: v, text: v })); });
  }

  function uniq(xs) { return xs.filter(function (x, i) { return x != null && xs.indexOf(x) === i; }).sort(); }

  function renderGames() {
    var games = current.games || [];
    fillSelect($("f-attacker"), uniq(games.map(function (g) { return g.attacker; })));
    fillSelect($("f-defender"), uniq(games.map(function (g) { return g.defender; })));
    fillSelect($("f-outcome"), uniq(games.map(function (g) { return g.outcome_status; })));
    ["f-attacker", "f-defender", "f-outcome"].forEach(function (id) { $(id).onchange = drawGames; });
    $("replay").hidden = true;
    drawGames();
  }

  function drawGames() {
    var fa = $("f-attacker").value, fd = $("f-defender").value, fo = $("f-outcome").value;
    var rows = (current.games || []).filter(function (g) {
      return (!fa || g.attacker === fa) && (!fd || g.defender === fd) && (!fo || g.outcome_status === fo);
    });
    renderTable($("games-table"), [
      { label: "Game", get: function (r) { return r.game_id; }, fmt: function (r) { return r.game_id; } },
      { label: "Attacker", get: function (r) { return r.attacker; }, fmt: function (r) { return r.attacker; } },
      { label: "Defender", get: function (r) { return r.defender; }, fmt: function (r) { return r.defender; } },
      { label: "Outcome", get: function (r) { return r.outcome_status; }, fmt: function (r) { return r.outcome_status + (r.terminal_reason ? " (" + r.terminal_reason + ")" : ""); } },
      { label: "Turns", get: function (r) { return r.turns_used; }, fmt: function (r) { return String(r.turns_used); } },
      { label: "Initial candidates", get: function (r) { return r.initial_secret_candidate_count; }, fmt: function (r) { return String(r.initial_secret_candidate_count); } },
      { label: "Reference B", get: function (r) { return r.score && r.score.baseline ? r.score.baseline.value : null; }, fmt: function (r) { return num(r.score && r.score.baseline); } },
      { label: "Cost C", get: function (r) { return r.score ? r.score.cost : null; }, fmt: function (r) { return num(r.score && r.score.cost) + (r.score && r.score.cost_exact === false ? " (est.)" : ""); } }
    ], rows, { rowClick: openReplay });
  }

  // --------------------------------------------------------------- replay
  var replay = null;

  function openReplay(g) {
    fetchJSON(current.base + "replays/" + encodeURIComponent(g.game_id) + ".json").then(function (r) {
      replay = r;
      $("replay").hidden = false;
      $("replay-title").textContent = "Replay " + r.game_id + " — " + r.attacker + " attacking, " + r.defender + " defending";
      var sel = clear($("replay-view"));
      sel.appendChild(el("option", { value: "public", text: "Public / defender view" }));
      if (r.seat_private_histories) {
        sel.appendChild(el("option", { value: "guesser1", text: "Guesser 1 knew" }));
        sel.appendChild(el("option", { value: "guesser2", text: "Guesser 2 knew" }));
        sel.appendChild(el("option", { value: "defender", text: "Defender knew" }));
      }
      if (r.referee_audit) sel.appendChild(el("option", { value: "audit", text: "Omniscient audit (post-game)" }));
      sel.onchange = drawReplay;
      var box = $("secret-box");
      box.hidden = true;
      $("reveal-secret").onclick = function () { box.hidden = false; box.textContent = "Secret: " + r.secret; };
      drawReplay();
      var box2 = $("replay");
      if (box2.scrollIntoView) { try { box2.scrollIntoView({ behavior: "smooth" }); } catch (e) { /* cosmetic */ } }
    }).catch(function (e) {
      $("replay").hidden = false;
      var missing = e && /HTTP 404/.test(String(e.message));
      $("replay-title").textContent = missing
        ? "Replay not included in this export for " + g.game_id + "."
        : "Could not display replay " + g.game_id + ": " + (e && e.message ? e.message : e);
      clear($("replay-turns"));
    });
  }

  var EXPLAIN = {
    public: "Public events only: clue, full blocklist, opened guesses and prefix. Hidden commitments, blocked seats and cancellation choices are not shown. (The defender additionally knew the secret, revealed here only on request.)",
    guesser1: "What Guesser 1 knew: public events plus its own private commitments and choices. It never saw Guesser 2's hidden word.",
    guesser2: "What Guesser 2 knew: public events plus its own private commitments and choices. It never saw Guesser 1's hidden word.",
    defender: "What the defender knew: the secret, public events and its own blocklist validity. It never saw hidden commitments.",
    audit: "OMNISCIENT POST-GAME AUDIT — hidden commitments, blocked flags, matches and the cancellation actor. None of this was visible to players during play."
  };

  function describeEvent(e) {
    if (e.type === "invalid_action") return "Guesser 1 submitted an invalid action (turn wasted).";
    if (e.type === "direct") return "Guesser 1 direct guess: " + e.word + ".";
    var parts = [];
    parts.push("Clue: “" + e.clue + "”.");
    if (e.blocklist === null || e.blocklist === undefined) parts.push("Blocklist: not collected.");
    else {
      var rg = e.blocked_ranges || [];
      var n = e.blocked_word_count != null ? e.blocked_word_count : e.blocklist.length;
      var shown = e.blocklist.slice();
      rg.forEach(function (r) { shown.push(r[0] + " … " + r[1]); });
      parts.push("Blocklist (" + n + " words" + (rg.length ? ", " + rg.length + " range" + (rg.length > 1 ? "s" : "") : "") +
        "): " + (shown.length ? shown.join(", ") : "(empty)") + ".");
    }
    var og = e.opened_guesses || [];
    parts.push("Opened guesses: " + (og.length ? og.map(function (g) { return g.seat + "=" + g.word; }).join(", ") : "none") + ".");
    return parts.join(" ");
  }

  function resultText(e) {
    var t = "Result: " + (e.result || "—");
    if (e.terminal_reason) t += " (" + e.terminal_reason + (e.hit_sources && e.hit_sources.length ? "; sources " + e.hit_sources.join(", ") : "") + ")";
    if (e.prefix_after != null) t += "; prefix now “" + e.prefix_after + "”";
    return t + ".";
  }

  function drawReplay() {
    var view = $("replay-view").value || "public", r = replay;
    $("view-explainer").textContent = EXPLAIN[view];
    $("view-explainer").className = view === "audit" ? "note audit" : "note";
    var ol = clear($("replay-turns"));
    ol.appendChild(el("li", { cls: "start" }, "Start: prefix “" + r.initial_prefix + "”, " +
      (r.initial_secret_candidate_count != null ? r.initial_secret_candidate_count :
        (r.initial_secret_candidates ? r.initial_secret_candidates.length : "?")) + " secret candidates, cap " + r.turn_limit + " turns." +
      (view === "defender" || view === "audit" ? " Secret: " + r.secret + "." : "")));
    var priv = view !== "public" && view !== "audit" && r.seat_private_histories ? (r.seat_private_histories[view] || []) : [];
    var audit = view === "audit" ? (r.referee_audit || []) : [];
    (r.public_history || []).forEach(function (e) {
      var li = el("li", { cls: "turn" }, el("strong", { text: "Turn " + e.turn + ". " }), describeEvent(e), el("br"), resultText(e));
      priv.filter(function (p) { return p.turn === e.turn; }).forEach(function (p) {
        var bits = ["Own private record: action " + (p.action || "—")];
        if (p.committed_word) bits.push("committed word " + p.committed_word);
        if (p.validity) bits.push("validity " + p.validity + (p.reason ? " (" + p.reason + ")" : ""));
        if (p.canonical_blocklist) bits.push("canonical blocklist " + (p.canonical_blocklist.join(", ") || "(empty)"));
        if (p.conditional_choice) bits.push("offered reveal/cancel (partner blocked) → " + p.conditional_choice.choice);
        li.appendChild(el("div", { cls: "private" }, bits.join("; ") + "."));
      });
      audit.filter(function (a) { return a.turn === e.turn; }).forEach(function (a) {
        var bits = [];
        if (a.w1) bits.push("G1 intended " + a.w1 + (a.blocked_guesser1 ? " [blocked]" : ""));
        if ("w2" in a) bits.push("G2 " + (a.w2 ? "registered " + a.w2 + (a.blocked_guesser2 ? " [blocked]" : "") : "passed"));
        if (a.choice_actor) bits.push("cancellation choice by " + a.choice_actor + ": " + a.choice);
        if (a.registered_match != null) bits.push("registered match " + a.registered_match);
        if (a.contact != null) bits.push("contact " + a.contact);
        if (a.blocked_contact) bits.push("contact prevented by block");
        if (a.guesser1_valid === false) bits.push("G1 invalid");
        if (a.guesser2_valid === false) bits.push("G2 invalid");
        if (a.defender_valid === false) bits.push("defender invalid");
        li.appendChild(el("div", { cls: "audit" }, "Audit: " + (bits.join("; ") || "—") + "."));
      });
      ol.appendChild(li);
    });
    var sc = r.score;
    ol.appendChild(el("li", { cls: "end" }, "End: " + r.outcome_status + (r.terminal_reason ? " (" + r.terminal_reason + ")" : "") +
      (sc ? "; cost " + num(sc.cost) + " vs reference B " + num(sc.baseline) : "") + "."));
  }

  // ------------------------------------------------------------ downloads
  function renderDownloads() {
    var ul = clear($("download-list"));
    [["games.csv", "Per-game results (CSV)"], ["games.json", "Per-game results (JSON)"], ["leaderboard.json", "Leaderboard and analysis (JSON)"],
     ["fixtures.json", "Paired fixtures (JSON)"], ["manifest.json", "Export manifest (JSON)"]].forEach(function (f) {
      ul.appendChild(el("li", null, el("a", { href: current.base + f[0], download: f[0], text: f[1] })));
    });
    ul.appendChild(el("li", null, el("a", { href: "data/index.json", text: "Condition index (JSON)" })));
  }

  document.addEventListener("DOMContentLoaded", init);
})();
