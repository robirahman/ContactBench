"""Analysis of a completed (or provisional) run (spec Sections 9 and 17.1).

All statistics are recomputed from immutable game records regenerated from
logs; nothing is read from an editable leaderboard file.  Every rate names its
denominator.
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from statistics import mean
from typing import Any

from .rating import fit_ratings, match_points


def _frac(d: dict | None) -> Fraction | None:
    if not d or d.get("cost_numerator") is None:
        return None
    return Fraction(d["cost_numerator"], d["cost_denominator"])


def _bfrac(d: dict | None) -> Fraction | None:
    if not d or not d.get("baseline"):
        return None
    b = d["baseline"]
    return Fraction(b["numerator"], b["denominator"])


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _geomean(xs: list[float]) -> float | None:
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs and all(x > 0 for x in xs) else None


def _f(x: Fraction | None) -> float | None:
    return None if x is None else float(x)


def _fj(x: Fraction | None) -> dict | None:
    return None if x is None else {"numerator": x.numerator, "denominator": x.denominator, "value": float(x)}


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class GameRow:
    def __init__(self, rec: dict):
        g = rec["game"]
        self.rec = rec
        self.game_id = g["game_id"]
        self.fixture_id = g["fixture_id"]
        self.task_id = g["task_id"]
        self.rep = g["repetition"]
        self.attacker = g["attacker"]
        self.defender = g["defender"]
        self.leg = g["leg"]
        s = rec["summary"]
        self.summary = s
        self.status = rec.get("run_status", "complete")
        self.cost = _frac(rec.get("score"))
        self.baseline = _bfrac(rec.get("score"))
        sc = rec.get("score") or {}
        self.cost_exact = sc.get("cost_exact")
        self.cost_mcse = sc.get("cost_mcse")
        self.fallback = sc.get("fallback")
        self.baseline_info = sc.get("baseline")
        self.capped = s["outcome_status"] == "capped"
        self.secret_len = len(s["secret"])
        self.n0 = s["initial_secret_candidate_count"]

    @property
    def scored(self) -> bool:
        return self.cost is not None and self.baseline is not None


# Leg labels of scored paired games: AB/BA (homogeneous) and L1/L2 (team fixtures).
PAIRED_LEGS = ("AB", "BA", "L1", "L2")


def load_rows(records: list[dict]) -> list[GameRow]:
    return [GameRow(r) for r in records]


def _no_progress(r: "GameRow") -> bool:
    s = r.summary
    return s["outcome_status"] == "capped" and s["final_prefix"] == s["initial_prefix"]


def fixture_results(rows: list[GameRow], fixtures: list[dict], *, no_progress_draws: bool = True) -> list[dict]:
    by_id = {r.game_id: r for r in rows}
    out = []
    for f in fixtures:
        ab, ba = by_id.get(f["game_ab"]), by_id.get(f["game_ba"])
        complete = bool(ab and ba and ab.scored and ba.scored)
        item = {
            "fixture_id": f["fixture_id"],
            "task_id": f["task_id"],
            "repetition": f["repetition"],
            "model_a": f["model_a"],
            "model_b": f["model_b"],
            "complete": complete,
            "cost_ab": _fj(ab.cost) if ab else None,
            "cost_ba": _fj(ba.cost) if ba else None,
            "rematch_of": f.get("rematch_of", ""),
            "kind": f.get("kind", "model_pair"),
            "defender_model": f.get("defender_model", ""),
            "game_ab": f["game_ab"],
            "game_ba": f["game_ba"],
            "initial_prefix_length": f.get("initial_prefix_length"),
        }
        if complete:
            item["no_progress_draw"] = bool(no_progress_draws and _no_progress(ab) and _no_progress(ba))
            # Both legs capped without any letter: the fallback-cost difference
            # carries no signal, so the fixture is a draw for the rating.
            item["points_a"] = 0.5 if item["no_progress_draw"] else match_points(ab.cost, ba.cost)
            item["points_b"] = 1.0 - item["points_a"]
            # Numerical uncertainty of the cost difference (estimated fallbacks).
            m1 = ab.cost_mcse or 0.0
            m2 = ba.cost_mcse or 0.0
            same = (
                ab.fallback and ba.fallback
                and ab.fallback.get("cache_key") == ba.fallback.get("cache_key")
                and ab.fallback.get("target_length") == ba.fallback.get("target_length")
                and ab.fallback.get("cache_key") is not None
            )
            item["cost_difference_mcse"] = 0.0 if same else math.sqrt(m1 * m1 + m2 * m2)
            diff = abs(float(ab.cost - ba.cost))
            item["numerically_close"] = bool(item["cost_difference_mcse"] and diff < 2 * item["cost_difference_mcse"])
        out.append(item)
    return out


def _model_stats(models: list[str], rows: list[GameRow], fx: list[dict]) -> dict[str, dict]:
    cross = [r for r in rows if r.leg in PAIRED_LEGS and r.scored]
    stats: dict[str, dict] = {}
    for m in models:
        off = [r for r in cross if r.attacker == m]
        de = [r for r in cross if r.defender == m]
        sb_o = sum((r.baseline for r in off), Fraction(0))
        sc_o = sum((r.cost for r in off), Fraction(0))
        sb_d = sum((r.baseline for r in de), Fraction(0))
        sc_d = sum((r.cost for r in de), Fraction(0))
        # mean paired cost advantage A_i = mean_j mean_tasks (C_ji - C_ij)
        per_opp: dict[str, list[Fraction]] = defaultdict(list)
        pts = w = d = l = 0.0
        nfx = 0
        for f in fx:
            if not f["complete"]:
                continue
            cab = Fraction(f["cost_ab"]["numerator"], f["cost_ab"]["denominator"])
            cba = Fraction(f["cost_ba"]["numerator"], f["cost_ba"]["denominator"])
            if f["model_a"] == m:
                per_opp[f["model_b"]].append(cba - cab)
                p = f["points_a"]
            elif f["model_b"] == m:
                per_opp[f["model_a"]].append(cab - cba)
                p = f["points_b"]
            else:
                continue
            nfx += 1
            pts += p
            w += p == 1.0
            d += p == 0.5
            l += p == 0.0
        adv = (
            sum((sum(v, Fraction(0)) / len(v) for v in per_opp.values()), Fraction(0)) / len(per_opp)
            if per_opp
            else None
        )
        off_costs = sorted(float(r.cost) for r in off)
        de_costs = sorted(float(r.cost) for r in de)
        stats[m] = {
            "offense_games": len(off),
            # Robust summaries: an unsolved game at a large-dictionary state is
            # charged thousands of fallback turns, which dominates means.
            "offense_median_effective_cost": _median(off_costs),
            "offense_geometric_mean_cost": _geomean(off_costs),
            "defense_median_cost_imposed": _median(de_costs),
            "defense_geometric_mean_cost_imposed": _geomean(de_costs),
            "offense_aggregate_speedup": _fj(sb_o / sc_o) if sc_o else None,
            "offense_mean_effective_cost": _fj(sc_o / len(off)) if off else None,
            "offense_mean_baseline": _fj(sb_o / len(off)) if off else None,
            "offense_capped_fraction_of_offense_games": (sum(r.capped for r in off) / len(off)) if off else None,
            "defense_games": len(de),
            "defensive_cost_ratio": _fj(sc_d / sb_d) if sb_d else None,
            "defense_deadline_hold_rate_of_defense_games": (sum(r.capped for r in de) / len(de)) if de else None,
            "mean_paired_cost_advantage": _fj(adv),
            "opponents": sorted(per_opp),
            "fixtures": nfx,
            "match_points": pts,
            "match_point_share": pts / nfx if nfx else None,
            "wins": int(w),
            "draws": int(d),
            "losses": int(l),
        }
    return stats


ENDGAME_CANDIDATES = 20


def _self_contained(sc: Counter) -> dict:
    """Scores in [0, 1], higher is better, that depend only on the evaluated model.

    - action_validity: share of its decisions (any seat) that were legal.
    - clue_length_compliance: share of its Guesser 1 decisions not rejected for exceeding C.
    - self_coordination: share of clue turns where its Guesser 2 named its Guesser 1's intended
      word, in games where both guessers are this model. Responses are sealed and the defender
      acts simultaneously, so the opponent cannot affect whether the match happens.
    """
    dec = sc.get("g1_decisions", 0) + sc.get("g2_decisions", 0) + sc.get("d_decisions", 0)
    inv = sc.get("g1_invalid", 0) + sc.get("g2_invalid", 0) + sc.get("d_invalid", 0)
    return {
        "action_validity": 1 - inv / dec if dec else None,
        "clue_length_compliance": 1 - sc.get("g1_overlong", 0) / sc["g1_decisions"] if sc.get("g1_decisions") else None,
        "self_coordination": sc.get("self_matches", 0) / sc["self_clue_turns"] if sc.get("self_clue_turns") else None,
        "self_coordination_clue_turns": sc.get("self_clue_turns", 0),
    }


def _role_diagnostics(rows: list[GameRow], clue_max: int | None = None) -> dict[str, dict]:
    """Per-attacker and per-defender gameplay diagnostics (referee audit)."""
    att: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    dfn: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    block_sizes: dict[str, list[int]] = defaultdict(list)
    clue_chars: dict[str, list[int]] = defaultdict(list)
    reasons: dict[str, Counter] = defaultdict(Counter)  # model -> "seat: reason" -> count
    seat: dict[str, Counter] = defaultdict(Counter)  # per seat model (not team id)

    def why(x: dict) -> str:
        return re.sub(r"\d+", "N", str(x.get("reason") or "invalid"))[:80]

    for r in rows:
        a = att[r.attacker]
        dd = dfn[r.defender]
        a["games"] += 1
        dd["games"] += 1
        s = r.summary
        # Efficiency per letter: letters of the secret earned (all of them when solved).
        il = len(s.get("initial_prefix") or "")
        fl = len(s["secret"]) if s["outcome_status"] == "solved" else len(s.get("final_prefix") or "")
        a["letters_earned"] += max(0, fl - il)
        a["turns_used_total"] += s.get("turns_used") or 0
        # Endgame conversion: once at most ENDGAME_CANDIDATES secret candidates remain.
        if any((t.get("secret_candidates_after") or 10**9) <= ENDGAME_CANDIDATES for t in r.rec.get("referee_audit", [])) \
                or (s.get("initial_secret_candidate_count") or 10**9) <= ENDGAME_CANDIDATES:
            a["endgame_reached"] += 1
            a["endgame_converted"] += s["outcome_status"] == "solved"
        if s["outcome_status"] == "solved":
            a["wins"] += 1
            if s["terminal_reason"] == "prefix_completed":
                a["wins_prefix_completed"] += 1
            for src in s.get("hit_sources") or []:
                a[f"hit_source_{src}"] += 1
        canceled: list[tuple[int, str]] = []
        audits = r.rec.get("referee_audit", [])
        # Seat models (mixed teams / human challenges have different G1 and G2).
        seat_m = dict(zip(("guesser1", "guesser2", "defender"), _seats(r.rec["game"])))
        for t in audits:
            g1 = t.get("guesser1") or {}
            seat[seat_m["guesser1"]]["g1_decisions"] += 1
            if not g1.get("valid", True):
                seat[seat_m["guesser1"]]["g1_invalid"] += 1
                if "clue exceeds" in str(g1.get("reason") or ""):
                    seat[seat_m["guesser1"]]["g1_overlong"] += 1
            a["turns"] += 1
            a["guesser1_decisions"] += 1
            if not g1.get("valid", True):
                a["guesser1_invalid"] += 1
                reasons[seat_m["guesser1"]]["guesser1: " + why(g1)] += 1
                continue
            act = (g1.get("canonical") or {}).get("action")
            if act == "direct":
                a["direct_turns"] += 1
                continue
            a["clue_turns"] += 1
            if t.get("defender") is not None:
                dd["clue_turns_faced"] += 1  # only turns where the defender was asked to block
            if t.get("clue") is not None:
                clue_chars[seat_m["guesser1"]].append(len(t["clue"]))
            g2 = t.get("guesser2")
            de = t.get("defender")
            if g2 is not None:
                seat[seat_m["guesser2"]]["g2_decisions"] += 1
                if not g2["valid"]:
                    seat[seat_m["guesser2"]]["g2_invalid"] += 1
                a["guesser2_decisions"] += 1
                if not g2["valid"]:
                    a["guesser2_invalid"] += 1
                    reasons[seat_m["guesser2"]]["guesser2: " + why(g2)] += 1
                if g2["canonical"]["action"] == "pass":
                    a["guesser2_pass"] += 1
            homogeneous = seat_m["guesser1"] == seat_m["guesser2"]
            if g2 is not None and homogeneous:
                seat[seat_m["guesser1"]]["self_clue_turns"] += 1
                seat[seat_m["guesser1"]]["self_matches"] += bool(t.get("registered_match"))
            if de is not None:
                a["clue_turns_defended"] += 1
                seat[seat_m["defender"]]["d_decisions"] += 1
                if not de["valid"]:
                    seat[seat_m["defender"]]["d_invalid"] += 1
                dd["block_decisions"] += 1
                if not de["valid"]:
                    dd["block_invalid"] += 1
                    reasons[seat_m["defender"]]["defender: " + why(de)] += 1
                bs = t.get("block_size", len(de["canonical"]["words"]))
                block_sizes[r.defender].append(bs)
                dd["empty_blocklists"] += bs == 0
                dd["fresh_secret_candidates_blocked"] += t.get("block_fresh_secret_candidates", 0)
                dd["blocks_overlapping_clue"] += t.get("block_overlap_with_clue", 0)
            if t.get("registered_match"):
                a["registered_matches"] += 1
                dd["registered_matches_faced"] += 1
                if t.get("covered_match"):
                    # The matched word was on the blocklist (whether or not the
                    # engine's contact rule would otherwise have applied).
                    a["registered_matches_blocked"] += 1
                    dd["registered_matches_blocked"] += 1
            if t.get("intended_covered"):
                a["intended_word_covered"] += 1
                dd["intended_word_covered"] += 1
            if t.get("contact"):
                a["contacts_awarded"] += 1
                dd["contacts_conceded"] += 1
            if t.get("blocked_contact"):
                a["contacts_prevented"] += 1
                dd["contacts_prevented"] += 1
            if t.get("choice_actor"):
                a["choice_opportunities"] += 1
                if t.get("choice") == "reveal":
                    a["choice_reveal"] += 1
                else:
                    a["choice_cancel"] += 1
                    actor = t["choice_actor"]
                    w = t["w1"] if actor == "guesser1" else t.get("w2")
                    if w:
                        canceled.append((t["turn"], w))
                    if t["turn"] == r.summary["turn_limit"]:
                        a["final_turn_cancellations"] += 1
                if t.get("choice_valid") is False:
                    a["choice_invalid"] += 1
                    actor = t.get("choice_actor")
                    reasons[seat_m.get(actor, r.attacker)][f"{actor}: invalid reveal/cancel choice"] += 1
        for turn, w in canceled:
            later = [t for t in audits if t["turn"] > turn]
            if any(t.get("w1") == w or t.get("w2") == w for t in later):
                a["preserved_words_later_reused"] += 1
    out = {}
    C = clue_max
    for m, a in att.items():
        a = dict(a)
        ct = a.get("clue_turns", 0)
        out.setdefault(m, {})["offense"] = {
            **a,
            "rates": {
                "guesser1_invalid_per_guesser1_decision": a.get("guesser1_invalid", 0) / a["guesser1_decisions"] if a.get("guesser1_decisions") else None,
                "direct_share_per_valid_turn": a.get("direct_turns", 0) / (a.get("direct_turns", 0) + ct) if (a.get("direct_turns", 0) + ct) else None,
                "registered_match_per_clue_turn": a.get("registered_matches", 0) / ct if ct else None,
                # Clue leakage: the defender put the clue-giver's intended word on its blocklist.
                "clue_leak_per_defended_clue_turn": a.get("intended_word_covered", 0) / a["clue_turns_defended"] if a.get("clue_turns_defended") else None,
                "endgame_conversion": a.get("endgame_converted", 0) / a["endgame_reached"] if a.get("endgame_reached") else None,
                "contact_per_clue_turn": a.get("contacts_awarded", 0) / ct if ct else None,
                "contact_per_registered_match": a.get("contacts_awarded", 0) / a["registered_matches"] if a.get("registered_matches") else None,
                "guesser2_invalid_per_guesser2_decision": a.get("guesser2_invalid", 0) / a["guesser2_decisions"] if a.get("guesser2_decisions") else None,
                "reveal_per_choice_opportunity": a.get("choice_reveal", 0) / a["choice_opportunities"] if a.get("choice_opportunities") else None,
                # Of turns where both guessers named the same word, the share the defender blocked.
                "matches_blocked_per_registered_match": a.get("registered_matches_blocked", 0) / a["registered_matches"] if a.get("registered_matches") else None,
            },
            "turns_per_letter_earned": a.get("turns_used_total", 0) / a["letters_earned"] if a.get("letters_earned") else None,
        }
    for m, dd in dfn.items():
        dd = dict(dd)
        bs = block_sizes.get(m, [])
        out.setdefault(m, {})["defense"] = {
            **dd,
            "mean_blocklist_size_per_block_decision": mean(bs) if bs else None,
            "rates": {
                "empty_blocklist_per_block_decision": dd.get("empty_blocklists", 0) / dd["block_decisions"] if dd.get("block_decisions") else None,
                "block_invalid_per_block_decision": dd.get("block_invalid", 0) / dd["block_decisions"] if dd.get("block_decisions") else None,
                # Block recall: the clue-giver's intended word was on the blocklist.
                "intended_word_blocked_per_clue_turn": dd.get("intended_word_covered", 0) / dd["clue_turns_faced"] if dd.get("clue_turns_faced") else None,
                # Of the opponents' registered matches, the share this defender blocked.
                "matches_blocked_per_registered_match": dd.get("registered_matches_blocked", 0) / dd["registered_matches_faced"] if dd.get("registered_matches_faced") else None,
            },
            # Blocklist precision: words blocked per contact actually prevented.
            "blocked_words_per_contact_prevented": (sum(bs) / dd["contacts_prevented"]) if bs and dd.get("contacts_prevented") else None,
        }
    for m, rs in reasons.items():
        out.setdefault(m, {})["invalid_reasons"] = dict(rs.most_common())
    # Seat-level metrics keyed by the model that occupied the seat (differs from
    # the team-level offense rows for mixed teams and human challenges).
    for m in set(seat) | set(clue_chars):
        sc, cc = seat.get(m, Counter()), clue_chars.get(m, [])
        out.setdefault(m, {})["seat"] = {
            **dict(sc),
            "mean_clue_characters": mean(cc) if cc else None,
            "median_clue_characters": _median([float(x) for x in cc]),
            "clue_budget_used": (mean(cc) / C) if cc and C else None,
            "guesser1_invalid_rate": sc["g1_invalid"] / sc["g1_decisions"] if sc.get("g1_decisions") else None,
            "guesser2_invalid_rate": sc["g2_invalid"] / sc["g2_decisions"] if sc.get("g2_decisions") else None,
            # Self-contained scores: depend only on this model (0-1, higher is better).
            "self_contained": _self_contained(sc),
        }
    return out


def _resources(requests: list[dict]) -> dict:
    agg: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for q in requests:
        m, seat = q.get("model_id"), q.get("seat")
        a = agg[m][seat]
        a["requests"] += 1
        if q.get("status") != "ok":
            a["errors"] += 1
            # Failed calls can still have been sent (retries) and charged.
            a["transport_attempts"] += len(q.get("attempts") or [])
            if q.get("cost_estimate") is not None:
                a["cost_estimate"] += q["cost_estimate"]
            continue
        resp = q.get("response") or {}
        u = resp.get("usage") or {}
        for k in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens"):
            if u.get(k) is None:
                a[f"{k}_unknown"] += 1
            else:
                a[k] += u[k]
        a["latency_s"] += resp.get("latency_s") or 0.0
        a["transport_attempts"] += len(resp.get("attempts") or [])
        if q.get("cost_estimate") is not None:
            a["cost_estimate"] += q["cost_estimate"]
        if resp.get("refusal"):
            a["refusals"] += 1
        if resp.get("incomplete"):
            a["incomplete"] += 1
    return {m: {s: dict(v) for s, v in d.items()} for m, d in agg.items()}


def _strata(rows: list[GameRow]) -> dict:
    by_len: dict[tuple[str, int], list[GameRow]] = defaultdict(list)
    by_n: dict[tuple[str, str], list[GameRow]] = defaultdict(list)
    for r in rows:
        if not r.scored or r.leg == "self":
            continue
        by_len[(r.attacker, r.secret_len)].append(r)
        b = "1-10" if r.n0 <= 10 else "11-30" if r.n0 <= 30 else "31-100" if r.n0 <= 100 else ">100"
        by_n[(r.attacker, b)].append(r)

    def summ(rs):
        sb = sum((x.baseline for x in rs), Fraction(0))
        sc = sum((x.cost for x in rs), Fraction(0))
        return {"games": len(rs), "aggregate_speedup": _f(sb / sc) if sc else None,
                "mean_cost": _f(sc / len(rs)), "mean_baseline": _f(sb / len(rs))}

    return {
        "by_target_length": [{"model": m, "target_length": l, **summ(rs)} for (m, l), rs in sorted(by_len.items())],
        "by_initial_candidate_count": [{"model": m, "bin": b, **summ(rs)} for (m, b), rs in sorted(by_n.items())],
    }


def _numerical(rows: list[GameRow]) -> dict:
    base_exact = sum(1 for r in rows if r.baseline_info and r.baseline_info["exact"])
    base_est = sum(1 for r in rows if r.baseline_info and not r.baseline_info["exact"])
    fb = [r.fallback for r in rows if r.fallback]
    fb_exact = sum(1 for f in fb if f["exact"])
    mcses = [f["mcse"] for f in fb if f.get("mcse")] + [
        r.baseline_info["mcse"] for r in rows if r.baseline_info and r.baseline_info.get("mcse")
    ]
    methods: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.baseline_info:
            methods["baseline:" + r.baseline_info["method"]] += 1
        if r.fallback:
            methods["fallback:" + r.fallback["method"]] += 1
    keys = [f.get("cache_key") for f in fb if f.get("cache_key")]
    return {
        "baselines_exact": base_exact,
        "baselines_estimated": base_est,
        "fallbacks_exact": fb_exact,
        "fallbacks_estimated": len(fb) - fb_exact,
        "max_mcse": max(mcses) if mcses else 0.0,
        "mean_mcse_of_estimates": mean(mcses) if mcses else 0.0,
        "methods": dict(methods),
        "fallback_cache_entries_used": len(set(keys)),
        "fallback_cache_reuse": len(keys) - len(set(keys)),
    }


def bootstrap(models: list[str], fx: list[dict], rows: list[GameRow], *, resamples: int, seed: int,
              penalty_scale: float, elo_center: float) -> dict:
    complete = [f for f in fx if f["complete"]]
    tasks = sorted({f["task_id"] for f in complete})
    by_task: dict[str, list[dict]] = defaultdict(list)
    for f in complete:
        by_task[f["task_id"]].append(f)
    rows_by_task: dict[str, list[GameRow]] = defaultdict(list)
    for r in rows:
        if r.scored and r.leg in PAIRED_LEGS:
            rows_by_task[r.task_id].append(r)
    rng = random.Random(seed)
    samples: dict[str, dict[str, list[float]]] = {m: defaultdict(list) for m in models}
    failures = 0
    for _ in range(resamples):
        pick = [tasks[rng.randrange(len(tasks))] for _ in tasks] if tasks else []
        sfx = [f for t in pick for f in by_task[t]]
        srows = [r for t in pick for r in rows_by_task[t]]
        fit = fit_ratings(models, [(f["model_a"], f["model_b"], f["points_a"]) for f in sfx],
                          penalty_scale=penalty_scale, elo_center=elo_center)
        if not fit.converged:
            failures += 1
        order = sorted(models, key=lambda m: -fit.elo[m])
        st = _model_stats(models, srows, sfx)
        for m in models:
            samples[m]["elo"].append(fit.elo[m])
            samples[m]["rank"].append(order.index(m) + 1)
            sp = st[m]["offense_aggregate_speedup"]
            if sp:
                samples[m]["offense_aggregate_speedup"].append(sp["value"])
            adv = st[m]["mean_paired_cost_advantage"]
            if adv:
                samples[m]["mean_paired_cost_advantage"].append(adv["value"])
            dc = st[m]["defensive_cost_ratio"]
            if dc:
                samples[m]["defensive_cost_ratio"].append(dc["value"])
            for k in ("offense_median_effective_cost", "offense_geometric_mean_cost",
                      "defense_median_cost_imposed"):
                if st[m][k] is not None:
                    samples[m][k].append(st[m][k])
    ci = {
        m: {k: {"lo": _pct(v, 0.025), "hi": _pct(v, 0.975), "n": len(v)} for k, v in d.items()}
        for m, d in samples.items()
    }
    return {
        "resamples": resamples,
        "seed": seed,
        "cluster": "task (secret) — both directions and all pairings kept together",
        "task_clusters": len(tasks),
        "fit_failures": failures,
        "intervals_95": ci,
    }


def _seats(game: dict) -> tuple[str, str, str]:
    return (game.get("guesser1_model") or game["attacker"],
            game.get("guesser2_model") or game.get("attacker_g2") or game["attacker"],
            game["defender"])


def role_fixture_data(rows: list[GameRow], fx: list[dict], *, with_task: bool = False) -> list:
    """(leg1 seats, leg2 seats, first-leg points) for every complete fixture.

    With ``with_task`` each item is prefixed by its bootstrap cluster key: the
    secret, so the same secret played in several (compatible) runs forms one
    cluster, as do a fixture and its rematches."""
    by_id = {r.game_id: r for r in rows}
    out = []
    for f in fx:
        if not f.get("complete"):
            continue
        ab, ba = by_id.get(f.get("game_ab", "")), by_id.get(f.get("game_ba", ""))
        if ab is None or ba is None:
            continue
        item = (_seats(ab.rec["game"]), _seats(ba.rec["game"]), f["points_a"])
        out.append((ab.summary["secret"], item) if with_task else item)
    return out


def compact_record(rec: dict) -> dict:
    """The fields rating fits need (full game records can be large)."""
    return {k: rec.get(k) for k in ("game", "summary", "score", "run_status")}


class PriorRunError(ValueError):
    pass


def check_prior_run(current_run_dir: Path, prior_dir: Path, profiles: dict | None = None) -> None:
    """Reject a prior run whose condition differs from the team run's
    (protocol apart from partner disclosure, lexicons, scoring, draw rules,
    base prompts, and the profile of every shared model id)."""
    from ..prompts.templates import prompt_hash
    from .combined import CONDITION_SECTIONS, TOURNAMENT_RULES, _normalized_config

    cur, pri = _normalized_config(Path(current_run_dir)), _normalized_config(Path(prior_dir))
    cm = json.loads((Path(current_run_dir) / "run.json").read_text())
    pm = json.loads((Path(prior_dir) / "run.json").read_text())
    name = Path(prior_dir).name
    for sec in CONDITION_SECTIONS:
        a, b = dict(cur[sec]), dict(pri[sec])
        if sec == "protocol":
            a.pop("partner_disclosure", None), b.pop("partner_disclosure", None)
        if a != b:
            raise PriorRunError(f"prior run {name}: section '{sec}' differs from the team run")
    for k in TOURNAMENT_RULES:
        if cur["tournament"][k] != pri["tournament"][k]:
            raise PriorRunError(f"prior run {name}: tournament rule '{k}' differs")
    for k in ("engine_version", "packing_version", "rng_version", "protocol_version"):
        if cm.get(k) != pm.get(k):
            raise PriorRunError(f"prior run {name}: {k} differs")
    if not pri["tournament"].get("homogeneous_attackers", True):
        # A mixed-team prior run must be the same disclosure condition.
        if (pri["protocol"].get("partner_disclosure", "blind") != cur["protocol"].get("partner_disclosure", "blind")
                or pm.get("prompt_hash") != cm.get("prompt_hash")):
            raise PriorRunError(f"prior run {name}: a mixed-team run from another disclosure condition")
    elif pm.get("prompt_hash") != prompt_hash("blind"):
        raise PriorRunError(f"prior run {name}: prompt templates differ")
    for key in ("secret_lexicon", "contact_lexicon"):
        if (cm.get(key) or {}).get("sha256") != (pm.get(key) or {}).get("sha256"):
            raise PriorRunError(f"prior run {name}: {key} differs")
    # Profiles seen so far (the team run's, then earlier prior runs'), so one
    # model id always means one inference profile in the pooled fit.
    mine = profiles if profiles is not None else {}
    for m in cur["models"]:
        mine.setdefault(m["id"], m)
    for m in pri["models"]:
        if mine.setdefault(m["id"], m) != m:
            raise PriorRunError(f"prior run {name}: model '{m['id']}' is configured differently")


def prior_run_legs(runs_root: Path, names: list[str], *, no_progress_draws: bool,
                   current_run_dir: Path | None = None) -> list[tuple[str, tuple]]:
    """(secret cluster, role-fit fixture) for every complete fixture of earlier runs."""
    from ..runner.store import RunStore

    out = []
    profiles: dict = {}
    for name in names:
        d = Path(runs_root) / name
        if current_run_dir is not None:
            check_prior_run(current_run_dir, d, profiles)
        sched = json.loads((d / "schedule.json").read_text())
        store = RunStore(d)
        recs = []
        for g in sched["games"]:
            r = store.read_game(g["game_id"])
            if r and r.get("run_status") == "complete":
                recs.append(compact_record(r))
        fx = fixture_results(load_rows(recs), sched["fixtures"], no_progress_draws=no_progress_draws)
        out.extend(role_fixture_data(load_rows(recs), fx, with_task=True))
    return out


def centred_components(fit, reference: list[str]) -> dict[str, dict[str, float]]:
    """Role components in Elo points, each role centred over ``reference``."""
    from .rating import ROLES

    scale = 400.0 / math.log(10)
    mean = {r: sum(fit.theta[k][r] for k in reference) / len(reference) for r in ROLES}
    return {m: {r: scale * (fit.theta[m][r] - mean[r]) for r in ROLES} for m in fit.models}


def role_bootstrap(models: list[str], legs_by_task: dict[str, list], *, resamples: int, seed: int,
                   penalty_scale: float, elo_center: float, drop_for: dict | None = None,
                   reference: list[str] | None = None) -> dict:
    from .rating import ROLES, fit_role_ratings

    tasks = sorted(legs_by_task)
    rng = random.Random(seed)
    samples: dict[str, dict[str, list[float]]] = {m: defaultdict(list) for m in models}
    failures = 0
    for _ in range(resamples):
        pick = [tasks[rng.randrange(len(tasks))] for _ in tasks] if tasks else []
        fit = fit_role_ratings(models, [x for t in pick for x in legs_by_task[t]],
                               penalty_scale=penalty_scale, elo_center=elo_center)
        failures += not fit.converged
        comp = centred_components(fit, reference or models)
        for m in models:
            samples[m]["elo"].append(fit.elo[m])
            for r in ROLES:
                samples[m][r].append(comp[m][r])
    return {"resamples": resamples, "seed": seed, "task_clusters": len(tasks), "fit_failures": failures,
            "intervals_95": {m: {k: {"lo": _pct(v, 0.025), "hi": _pct(v, 0.975)} for k, v in d.items()
                                 if k not in (drop_for or {}).get(m, ())} for m, d in samples.items()}}


def team_diagnostics(rows: list[GameRow]) -> dict:
    """Cross-play matrix (Guesser 1 model x Guesser 2 model) and self-play gaps."""
    cells: dict[str, dict[str, list[GameRow]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r.scored and r.rec["game"].get("guesser1_model"):
            g1, g2, _ = _seats(r.rec["game"])
            cells[g1][g2].append(r)

    def contact_rate(rs):
        clue = sum(1 for r in rs for t in r.rec.get("referee_audit", []) if t.get("clue") is not None)
        con = sum(1 for r in rs for t in r.rec.get("referee_audit", []) if t.get("contact"))
        return con / clue if clue else None

    matrix = {g1: {g2: {"games": len(rs), "median_cost": _median([float(r.cost) for r in rs]),
                        "contacts_per_clue_turn": contact_rate(rs)} for g2, rs in d.items()}
              for g1, d in cells.items()}
    gaps = {}
    for m in sorted(set(cells) | {g2 for d in cells.values() for g2 in d}):
        selfp = [float(r.cost) for r in cells.get(m, {}).get(m, [])]
        mixed = [float(r.cost) for g1, d in cells.items() for g2, rs in d.items() if g1 != g2 and m in (g1, g2)
                 for r in rs]
        gaps[m] = {"self_play_median_cost": _median(selfp), "cross_play_median_cost": _median(mixed),
                   "self_play_games": len(selfp), "cross_play_games": len(mixed)}
    return {"cross_play_matrix": matrix, "self_vs_cross_play": gaps}


def analyze(run_dir: Path, records: list[dict], *, resamples: int, seed: int,
            penalty_scale: float, elo_center: float, write: bool = True,
            anchor: dict | None = None) -> dict:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "run.json").read_text())
    sched = json.loads((run_dir / "schedule.json").read_text())
    models = [m["id"] for m in manifest["config"]["models"]]
    rows = load_rows(records)
    draw_rule = manifest["config"].get("tournament", {}).get("no_progress_draws", True)
    fx = fixture_results(rows, sched["fixtures"], no_progress_draws=draw_rule)
    team_mode = any(f.get("kind") in ("role", "self_play") for f in sched["fixtures"])
    model_ids = models
    if team_mode:
        # Rating entities are teams ("G1+G2"); per-model role ratings below.
        models = sorted({f["model_a"] for f in sched["fixtures"]} | {f["model_b"] for f in sched["fixtures"]})
    complete = [f for f in fx if f["complete"]]
    fit = fit_ratings(models, [(f["model_a"], f["model_b"], f["points_a"]) for f in complete],
                      penalty_scale=penalty_scale, elo_center=elo_center)
    sensitivity = {
        str(s): fit_ratings(models, [(f["model_a"], f["model_b"], f["points_a"]) for f in complete],
                            penalty_scale=s, elo_center=elo_center).elo
        for s in (1.0, 2.5, 5.0)
    }
    stats = _model_stats(models + ([m for m in model_ids if m not in models] if team_mode else []), rows, fx)
    boot = bootstrap(models, fx, rows, resamples=resamples, seed=seed,
                     penalty_scale=penalty_scale, elo_center=elo_center) if complete else None
    # pairwise matrices
    pts: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    costm: dict[str, dict[str, list[Fraction]]] = defaultdict(lambda: defaultdict(list))
    for f in complete:
        pts[f["model_a"]][f["model_b"]].append(f["points_a"])
        pts[f["model_b"]][f["model_a"]].append(f["points_b"])
    for r in rows:
        if r.scored:
            costm[r.attacker][r.defender].append(r.cost)
    pair_points = {a: {b: {"mean_points": mean(v), "fixtures": len(v)} for b, v in d.items()} for a, d in pts.items()}
    pair_cost = {a: {b: {"mean_cost": _f(sum(v, Fraction(0)) / len(v)), "games": len(v)} for b, v in d.items()} for a, d in costm.items()}
    planned_pairs = {(f["model_a"], f["model_b"]) for f in sched["fixtures"]}
    status_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        status_counts[f"{r.summary['outcome_status']}/{r.summary['collection_status']}"] += 1
    capped = [r for r in rows if r.capped]
    team_result = None
    if team_mode or any(r.rec["game"].get("guesser1_model") for r in rows):
        from .rating import fit_role_ratings

        tagged = role_fixture_data(rows, fx, with_task=True)
        tcfg = manifest["config"].get("tournament", {}).get("teams") or {}
        prior = tcfg.get("prior_runs") or []
        if prior:
            # The homogeneous fixtures used for defender selection also identify
            # defender components; include them (as separate task clusters).
            tagged += prior_run_legs(Path(run_dir).parent, prior, no_progress_draws=draw_rule,
                                     current_run_dir=Path(run_dir))
        legs = [leg for _, leg in tagged]
        by_task: dict[str, list] = defaultdict(list)
        for t, leg in tagged:
            by_task[t].append(leg)
        fit_models = sorted(set(model_ids) | {m for l1, l2, _ in legs for leg in (l1, l2) for m in leg})
        rfit = fit_role_ratings(fit_models, legs, penalty_scale=penalty_scale, elo_center=elo_center)
        rjson = rfit.to_json()
        from .rating import ROLES, role_estimability

        # Components are reported centred over the team models (the models that
        # played guesser seats in team fixtures); every value is published only
        # if the fixture design identifies it exactly (design-matrix row space).
        reference = sorted({m for l1, l2, _ in legs for leg in (l1, l2) if leg[0] != leg[1] for m in leg[:2]}
                           ) or fit_models
        est = role_estimability(fit_models, legs, reference=reference)
        comp = centred_components(rfit, reference)
        drop_for = {}
        for m in fit_models:
            rjson["components_elo_points"][m] = {r: (comp[m][r] if est[m][r] else None) for r in ROLES}
            # Same centring and gating for the logit-scale components.
            rjson["components_logit"][m] = {r: (comp[m][r] * math.log(10) / 400.0 if est[m][r] else None)
                                            for r in ROLES}
            if not est[m]["composite"]:
                rjson["elo"][m] = None
                rjson["composite_logit"][m] = None
            drop_for[m] = tuple(r for r in ROLES if not est[m][r]) + (() if est[m]["composite"] else ("elo",))
        rjson["components_centred_over"] = reference
        omitted = {m: list(v) for m, v in drop_for.items() if v}
        team_result = {
            "role_rating": rjson,
            "estimable": est,
            "omitted_unidentified": omitted,
            "prior_runs_in_role_fit": prior,
            "role_bootstrap": role_bootstrap(fit_models, by_task, resamples=resamples, seed=seed,
                                             penalty_scale=penalty_scale, elo_center=elo_center,
                                             drop_for=drop_for, reference=reference) if legs else None,
            **team_diagnostics(rows),
            "partner_disclosure": manifest["config"]["protocol"].get("partner_disclosure", "blind"),
            "identifiability_note": "Role fixtures (A+B vs B+A, one defender) identify differences in "
                                    "clue-giver minus receiver skill; self-play fixtures (A+A vs B+B) identify "
                                    "differences in g1+g2; homogeneous fixtures identify composite differences. "
                                    "Components are centred over the team models and a value is shown only when "
                                    "the fixture design identifies it exactly.",
        }
    result = {
        "run_id": manifest["run_id"],
        "teams": team_result,
        "model_ids": model_ids,
        "protocol_version": manifest["protocol_version"],
        "fixture_data": manifest.get("fixture_data", True),
        "condition": manifest["config"]["protocol"],
        "lexicon": {k: manifest["secret_lexicon"][k] for k in ("name", "sha256", "word_count", "license")},
        "models": models,
        "planned_games": len(sched["games"]),
        "recorded_games": len(rows),
        "scored_games": sum(1 for r in rows if r.scored),
        "planned_fixtures": len(sched["fixtures"]),
        "rematch_fixtures": sum(1 for f in sched["fixtures"] if f.get("rematch_of")),
        "no_progress_draw_rule": draw_rule,
        "no_progress_draws": sum(1 for f in fx if f.get("no_progress_draw")),
        "complete_fixtures": len(complete),
        "balanced_complete": len(complete) == len(sched["fixtures"]) and len(complete) > 0,
        "game_status_counts": dict(status_counts),
        "missing_model_pairs": [],
        "rating": fit.to_json(),
        "rating_penalty_sensitivity": sensitivity,
        "bootstrap": boot,
        "model_stats": stats,
        "role_diagnostics": _role_diagnostics(rows, manifest["config"]["protocol"].get("clue_max_characters")),
        "pairwise_match_points": pair_points,
        "pairwise_mean_cost": pair_cost,
        "fixtures": fx,
        "capped_games": len(capped),
        "capped_fraction_of_scored_games": len(capped) / max(1, sum(1 for r in rows if r.scored)),
        "residual_candidate_counts_capped": sorted(r.summary["final_secret_candidate_count"] for r in capped),
        "strata": _strata(rows),
        "numerical_reference": _numerical(rows),
        "numerically_close_fixtures": sum(1 for f in complete if f.get("numerically_close")),
    }
    for a, b in sorted(planned_pairs):
        if not any(f["complete"] and f["model_a"] == a and f["model_b"] == b for f in fx):
            result["missing_model_pairs"].append([a, b])
    reqs = []
    rp = run_dir / "requests.jsonl"
    if rp.exists():
        reqs = [json.loads(l) for l in rp.read_text().splitlines() if l.strip()]
    unsent: dict[str, dict[str, dict[str, int]]] = {}
    # Forecast-fork calls are billed and budgeted like gameplay calls; account
    # for them under a separate role key ("<seat>/fork").
    if (run_dir / "forecasts.jsonl").exists():
        from ..runner.store import RunStore

        for f in RunStore(run_dir).forecasts():
            role = f"{f['seat']}/fork"
            if f["status"] == "ok":
                reqs.append({"model_id": f["model_id"], "seat": role, "status": "ok",
                             "response": f.get("response"), "cost_estimate": f.get("cost_estimate")})
            elif f.get("requests_sent"):
                # Sent (possibly retried) but failed: keep attempts and charged cost.
                # requests_sent (BudgetGate calls) covers every model/tool turn;
                # the error's attempts list covers only the final failed turn.
                attempts = list(f.get("attempts") or [])
                attempts += [{} for _ in range(max(0, f["requests_sent"] - len(attempts)))]
                reqs.append({"model_id": f["model_id"], "seat": role, "status": "error",
                             "attempts": attempts, "cost_estimate": f.get("cost_estimate")})
            else:
                # Never sent (context overflow, pre-send budget stop) or
                # interrupted with unknown sending: not a request.
                key = "interrupted" if f.get("error") == "interrupted" else "not_sent"
                unsent.setdefault(f["model_id"], {}).setdefault(role, {}).setdefault(key, 0)
                unsent[f["model_id"]][role][key] += 1
    result["resources"] = _resources(reqs)
    for m, roles in unsent.items():
        for role, counts in roles.items():
            for k, v in counts.items():
                result["resources"].setdefault(m, {}).setdefault(role, {})[f"forks_{k}"] = v
    from .calibration import forecast_calibration

    result["forecast_calibration"] = forecast_calibration(records)
    humans = [m["id"] for m in manifest["config"]["models"] if m.get("provider") == "human"]
    if humans:
        result["human_challenge"] = {
            "players": humans,
            "display_names": {m["id"]: m.get("display_name") or m["id"]
                              for m in manifest["config"]["models"] if m.get("provider") == "human"},
            "note": "Human vs model fixtures; never pooled with model-only ratings.",
        }
        # The joint fit above moves the opponents' Elo with the human's games,
        # so it is never the headline rating of a human-challenge run.
        result["rating_joint_unanchored"] = result["rating"]
        for iv in ((boot or {}).get("intervals_95") or {}).values():
            iv.pop("elo", None)
            iv.pop("rank", None)
        result["rating_penalty_sensitivity"] = None
    if anchor is not None:
        from .rating import fit_anchored

        res = [(f["model_a"], f["model_b"], f["points_a"]) for f in complete]
        free = humans or [m for m in models if m not in anchor["elo"]]
        missing = sorted(set(models) - set(free) - set(anchor["elo"]))
        if missing:
            raise ValueError(f"anchor ratings lack {missing}")
        ar = {**fit_anchored(anchor["elo"], res, free, penalty_scale=penalty_scale, elo_center=elo_center),
              "anchor_run_id": anchor.get("run_id")}
        result["anchored_rating"] = ar
        if humans:
            result["rating"] = {
                "method": ar["method"], "models": models,
                "elo": {m: ar["elo"][m] if m in ar["elo"] else anchor["elo"][m] for m in models},
                "fixed": sorted(m for m in models if m not in ar["elo"]),
                "anchor_run_id": ar["anchor_run_id"], "converged": ar["converged"],
                "iterations": ar["iterations"], "gradient_norm": ar["gradient_norm"], "loss": ar["loss"],
                "penalty_scale": penalty_scale, "connected_components": result["rating"]["connected_components"],
            }
    elif humans:
        result["rating"] = {**result["rating"], "unanchored": True,
                            "note": "Unanchored joint fit of this run only; opponents' Elo is not their "
                                    "leaderboard rating. Analyze with --anchor to rate the player on the model scale."}
    if write:
        write_outputs(run_dir / "analysis", result, rows)
    return result


def write_outputs(out: Path, result: dict, rows: list[GameRow]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    models = result["models"]
    boot = (result.get("bootstrap") or {}).get("intervals_95", {})
    with (out / "leaderboard.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "elo", "elo_lo", "elo_hi", "match_point_share", "fixtures",
                    "offense_speedup", "mean_paired_cost_advantage", "defensive_cost_ratio",
                    "deadline_hold_rate", "offense_mean_cost", "offense_median_cost",
                    "offense_geometric_mean_cost", "defense_median_cost_imposed"])
        for m in sorted(models, key=lambda m: -result["rating"]["elo"][m]):
            s = result["model_stats"][m]
            ci = boot.get(m, {}).get("elo", {})
            w.writerow([
                m, round(result["rating"]["elo"][m], 1), _r(ci.get("lo")), _r(ci.get("hi")),
                _r(s["match_point_share"]), s["fixtures"],
                _r((s["offense_aggregate_speedup"] or {}).get("value")),
                _r((s["mean_paired_cost_advantage"] or {}).get("value")),
                _r((s["defensive_cost_ratio"] or {}).get("value")),
                _r(s["defense_deadline_hold_rate_of_defense_games"]),
                _r((s["offense_mean_effective_cost"] or {}).get("value")),
                _r(s["offense_median_effective_cost"]), _r(s["offense_geometric_mean_cost"]),
                _r(s["defense_median_cost_imposed"]),
            ])
    with (out / "pairwise.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["attacker_row_model", "opponent", "mean_match_points", "fixtures", "mean_attacking_cost", "games"])
        for a in models:
            for b in models:
                p = result["pairwise_match_points"].get(a, {}).get(b)
                c = result["pairwise_mean_cost"].get(a, {}).get(b)
                if p or c:
                    w.writerow([a, b, _r(p and p["mean_points"]), p and p["fixtures"],
                                _r(c and c["mean_cost"]), c and c["games"]])
    with (out / "games.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_id", "task_id", "attacker", "defender", "leg", "outcome_status", "terminal_reason",
                    "collection_status", "turns_used", "secret_length", "initial_candidates",
                    "final_candidates", "baseline", "cost", "cost_exact", "cost_mcse"])
        for r in rows:
            s = r.summary
            w.writerow([r.game_id, r.task_id, r.attacker, r.defender, r.leg, s["outcome_status"],
                        s["terminal_reason"], s["collection_status"], s["turns_used"], r.secret_len, r.n0,
                        s["final_secret_candidate_count"], _r(_f(r.baseline)), _r(_f(r.cost)),
                        r.cost_exact, _r(r.cost_mcse)])
    (out / "report.md").write_text(render_report(result))
    from .figures import write_figures

    costs: dict[str, list[float]] = {}
    for r in rows:
        if r.scored and r.leg in PAIRED_LEGS:
            costs.setdefault(r.attacker, []).append(float(r.cost))
    write_figures(out / "figures", result, costs)


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


def render_report(res: dict) -> str:
    L = []
    if res.get("fixture_data", True):
        L.append("> **FIXTURE / DEMO DATA** — synthetic offline run; not a benchmark result.\n")
    L.append(f"# ContactBench analysis — run `{res['run_id']}`\n")
    L.append(f"Protocol {res['protocol_version']}; lexicon {res['lexicon']['name']} "
             f"({res['lexicon']['word_count']} words, sha256 {res['lexicon']['sha256'][:12]}…); "
             f"C={res['condition']['clue_max_characters']}, L={res['condition']['turn_limit']}.\n")
    L.append(f"Games: planned {res['planned_games']}, recorded {res['recorded_games']}, scored {res['scored_games']}. "
             f"Fixtures: planned {res['planned_fixtures']}, complete {res['complete_fixtures']}"
             f"{' (balanced and complete)' if res['balanced_complete'] else ' (PROVISIONAL: incomplete)'}.\n")
    L.append(f"No-progress draws (both legs capped without a letter; scored ½–½): {res.get('no_progress_draws', 0)}; "
             f"rematch fixtures (same secret, extra letter revealed): {res.get('rematch_fixtures', 0)}.\n")
    L.append("## Paired competitive rating (batch Elo-style rating with half-point draws)\n")
    L.append("| Model | Elo | 95% CI | Match-point share (per fixture) | Offense speedup (ΣB/ΣC) | Median offense cost (turns) | Median cost imposed as defender | Mean paired cost advantage | Defensive cost ratio (ΣC/ΣB) | Deadline hold rate (per defended game) |")
    L.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    boot = (res.get("bootstrap") or {}).get("intervals_95", {})
    for m in sorted(res["models"], key=lambda m: -res["rating"]["elo"][m]):
        s = res["model_stats"][m]
        ci = boot.get(m, {}).get("elo", {})
        cis = f"[{ci['lo']:.0f}, {ci['hi']:.0f}]" if ci.get("lo") is not None else "—"
        L.append(
            f"| {m} | {res['rating']['elo'][m]:.0f} | {cis} | {_fmt(s['match_point_share'])} | "
            f"{_fmt((s['offense_aggregate_speedup'] or {}).get('value'))} | "
            f"{_fmt(s['offense_median_effective_cost'])} | {_fmt(s['defense_median_cost_imposed'])} | "
            f"{_fmt((s['mean_paired_cost_advantage'] or {}).get('value'))} | "
            f"{_fmt((s['defensive_cost_ratio'] or {}).get('value'))} | "
            f"{_fmt(s['defense_deadline_hold_rate_of_defense_games'])} |"
        )
    L.append("")
    L.append(f"Rating fit converged: {res['rating']['converged']} "
             f"(iterations {res['rating']['iterations']}, penalty scale {res['rating']['penalty_scale']}). "
             f"Connected components: {res['rating']['connected_components']}.")
    if res.get("anchored_rating"):
        ar = res["anchored_rating"]
        names = (res.get("human_challenge") or {}).get("display_names", {})
        L.append("\n### Anchored rating (opponents fixed at the anchor run's Elo)\n")
        for m in ar["free"]:
            se = ar["elo_se_approx"].get(m)
            L.append(f"- {names.get(m, m)}: Elo {ar['elo'][m]:.0f}" + (f" (± {se:.0f} approx. s.e.)" if se else "")
                     + f" from {ar['results']} fixtures; anchor run {ar.get('anchor_run_id')}.")
        L.append("- Fixed opponents: " + ", ".join(f"{m} {v:.0f}" for m, v in ar["fixed_elo"].items()))
    if res.get("bootstrap"):
        b = res["bootstrap"]
        L.append(f"Bootstrap: {b['resamples']} resamples of {b['task_clusters']} task clusters, seed {b['seed']}, "
                 f"fit failures {b['fit_failures']}.")
    L.append("\nRatings summarize paired cost comparisons; they are not efficiency. "
             "A scalar rating does not imply dominance against every opponent.\n")
    n = res["numerical_reference"]
    L.append("## Numerical reference\n")
    L.append(f"Baselines exact/estimated: {n['baselines_exact']}/{n['baselines_estimated']}; "
             f"fallbacks exact/estimated: {n['fallbacks_exact']}/{n['fallbacks_estimated']}; "
             f"max MCSE {n['max_mcse']:.4g}; numerically close fixtures: {res['numerically_close_fixtures']}.\n")
    L.append(f"Capped games: {res['capped_games']} ({res['capped_fraction_of_scored_games']:.1%} of scored games).\n")
    from .calibration import render_calibration

    L.append(render_calibration(res.get("forecast_calibration") or {}))
    if res["missing_model_pairs"]:
        L.append(f"Missing pairs: {res['missing_model_pairs']}\n")
    L.append(render_gameplay(res.get("role_diagnostics") or {}))
    if res.get("teams"):
        L.append(render_teams(res["teams"]))
    return "\n".join(L) + "\n"


def render_gameplay(rd: dict) -> str:
    """Objective per-model gameplay metrics from the referee log."""
    if not rd:
        return ""
    L = ["## Gameplay metrics (referee log)\n",
         "| Model | Median clue chars | Clue budget used | Contacts / clue turn | Own matches blocked | "
         "Block recall (defense) | Opp. matches blocked | Words blocked / contact prevented | G1 invalid | "
         "G2 invalid | Defender invalid |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]

    def pc(x):
        return "—" if x is None else f"{100 * x:.1f}%"

    for m in sorted(rd):
        o, d, st = rd[m].get("offense") or {}, rd[m].get("defense") or {}, rd[m].get("seat") or {}
        orr, drr = o.get("rates") or {}, d.get("rates") or {}
        L.append(f"| {m} | {_fmt(st.get('median_clue_characters'))} | {pc(st.get('clue_budget_used'))} | "
                 f"{pc(orr.get('contact_per_clue_turn'))} | {pc(orr.get('matches_blocked_per_registered_match'))} | "
                 f"{pc(drr.get('intended_word_blocked_per_clue_turn'))} | {pc(drr.get('matches_blocked_per_registered_match'))} | "
                 f"{_fmt(d.get('blocked_words_per_contact_prevented'))} | "
                 f"{pc(st.get('guesser1_invalid_rate'))} | "
                 f"{pc(st.get('guesser2_invalid_rate'))} | "
                 f"{pc(drr.get('block_invalid_per_block_decision'))} |")
    L.append("\n### Self-contained scores (depend only on the model; 0-100%, higher is better)\n")
    L.append("| Model | Self-coordination | n | Action validity | Clue-length compliance | Clue leakage* | Endgame conversion* | Turns per letter* |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for m in sorted(rd):
        sc = (rd[m].get("seat") or {}).get("self_contained") or {}
        o = rd[m].get("offense") or {}
        orr = o.get("rates") or {}
        if not sc and not o:
            continue
        L.append(f"| {m} | {pc(sc.get('self_coordination'))} | {sc.get('self_coordination_clue_turns', 0)} | "
                 f"{pc(sc.get('action_validity'))} | {pc(sc.get('clue_length_compliance'))} | "
                 f"{pc(orr.get('clue_leak_per_defended_clue_turn'))} | {pc(orr.get('endgame_conversion'))} | "
                 f"{_fmt(o.get('turns_per_letter_earned'))} |")
    L.append("\n*Opponent-dependent (shown for context).")
    reasons = [(m, k, v) for m in sorted(rd) for k, v in (rd[m].get("invalid_reasons") or {}).items()]
    if reasons:
        L.append("\nInvalid actions by reason: " + "; ".join(f"{m} {k} ×{v}" for m, k, v in reasons) + ".")
    return "\n".join(L) + "\n"


def render_teams(t: dict) -> str:
    L = [f"## Mixed-model attacking teams (partner disclosure: {t['partner_disclosure']})\n",
         "The table above rates teams (\"Guesser 1+Guesser 2\"). Role ratings per model (Elo-scale components; "
         "composite = clue-giver + receiver + defender):\n",
         "| Model | Composite Elo | 95% CI | Clue-giver (G1) | Receiver (G2) | Defender |",
         "|---|---:|---|---:|---:|---:|"]
    rr = t["role_rating"]
    boot = ((t.get("role_bootstrap") or {}).get("intervals_95") or {})
    scale = 400.0 / math.log(10)

    def ci(m, k):
        c = boot.get(m, {}).get(k) or {}
        return f"[{c['lo']:.0f}, {c['hi']:.0f}]" if c.get("lo") is not None else "—"

    def sg(x):
        return "—" if x is None else f"{x:+.0f}"

    for m in sorted(rr["elo"], key=lambda m: -(rr["elo"][m] or 0)):
        th = rr["components_elo_points"][m]
        elo = "—" if rr["elo"][m] is None else f"{rr['elo'][m]:.0f}"
        L.append(f"| {m} | {elo} | {ci(m, 'elo')} | {sg(th['g1'])} {ci(m, 'g1')} | "
                 f"{sg(th['g2'])} {ci(m, 'g2')} | {sg(th['d'])} {ci(m, 'd')} |")
    if t.get("omitted_unidentified"):
        L.append("\nNot identified by the design (shown as —): " + "; ".join(
            f"{m}: {', '.join(v)}" for m, v in sorted(t["omitted_unidentified"].items())) + ".")
    L.append("\n" + t["identifiability_note"] + "\n")
    L.append("### Cross-play matrix (median cost, turns; rows = Guesser 1, columns = Guesser 2)\n")
    mat = t["cross_play_matrix"]
    cols = sorted({g2 for d in mat.values() for g2 in d})
    L.append("| G1 \\ G2 | " + " | ".join(cols) + " |")
    L.append("|---|" + "---:|" * len(cols))
    for g1 in sorted(mat):
        cells = []
        for g2 in cols:
            c = mat[g1].get(g2)
            cells.append(f"{_fmt(c['median_cost'])} (n={c['games']})" if c else "—")
        L.append(f"| {g1} | " + " | ".join(cells) + " |")
    L.append("\n### Self-play vs cross-play (median cost)\n")
    L.append("| Model | Self-play | n | With other partner | n |")
    L.append("|---|---:|---:|---:|---:|")
    for m, g in sorted(t["self_vs_cross_play"].items()):
        L.append(f"| {m} | {_fmt(g['self_play_median_cost'])} | {g['self_play_games']} | "
                 f"{_fmt(g['cross_play_median_cost'])} | {g['cross_play_games']} |")
    return "\n".join(L) + "\n"


def _fmt(x):
    return "—" if x is None else f"{x:.3f}"
