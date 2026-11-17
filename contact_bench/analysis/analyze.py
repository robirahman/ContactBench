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
from collections import defaultdict
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


def load_rows(records: list[dict]) -> list[GameRow]:
    return [GameRow(r) for r in records]


def fixture_results(rows: list[GameRow], fixtures: list[dict]) -> list[dict]:
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
        }
        if complete:
            item["points_a"] = match_points(ab.cost, ba.cost)
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
    cross = [r for r in rows if r.leg in ("AB", "BA") and r.scored]
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
        stats[m] = {
            "offense_games": len(off),
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


def _role_diagnostics(rows: list[GameRow]) -> dict[str, dict]:
    """Per-attacker and per-defender gameplay diagnostics (referee audit)."""
    att: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    dfn: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    block_sizes: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        a = att[r.attacker]
        dd = dfn[r.defender]
        a["games"] += 1
        dd["games"] += 1
        s = r.summary
        if s["outcome_status"] == "solved":
            a["wins"] += 1
            if s["terminal_reason"] == "prefix_completed":
                a["wins_prefix_completed"] += 1
            for src in s.get("hit_sources") or []:
                a[f"hit_source_{src}"] += 1
        canceled: list[tuple[int, str]] = []
        audits = r.rec.get("referee_audit", [])
        for t in audits:
            g1 = t.get("guesser1") or {}
            a["turns"] += 1
            a["guesser1_decisions"] += 1
            if not g1.get("valid", True):
                a["guesser1_invalid"] += 1
                continue
            act = (g1.get("canonical") or {}).get("action")
            if act == "direct":
                a["direct_turns"] += 1
                continue
            a["clue_turns"] += 1
            g2 = t.get("guesser2")
            de = t.get("defender")
            if g2 is not None:
                a["guesser2_decisions"] += 1
                if not g2["valid"]:
                    a["guesser2_invalid"] += 1
                if g2["canonical"]["action"] == "pass":
                    a["guesser2_pass"] += 1
            if de is not None:
                dd["block_decisions"] += 1
                if not de["valid"]:
                    dd["block_invalid"] += 1
                bs = t.get("block_size", len(de["canonical"]["words"]))
                block_sizes[r.defender].append(bs)
                dd["empty_blocklists"] += bs == 0
                dd["fresh_secret_candidates_blocked"] += t.get("block_fresh_secret_candidates", 0)
                dd["blocks_overlapping_clue"] += t.get("block_overlap_with_clue", 0)
            if t.get("registered_match"):
                a["registered_matches"] += 1
            if t.get("intended_covered"):
                a["intended_word_covered"] += 1
                dd["intended_word_covered"] += 1
            if t.get("contact"):
                a["contacts_awarded"] += 1
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
        for turn, w in canceled:
            later = [t for t in audits if t["turn"] > turn]
            if any(t.get("w1") == w or t.get("w2") == w for t in later):
                a["preserved_words_later_reused"] += 1
    out = {}
    for m, a in att.items():
        a = dict(a)
        ct = a.get("clue_turns", 0)
        out.setdefault(m, {})["offense"] = {
            **a,
            "rates": {
                "guesser1_invalid_per_guesser1_decision": a.get("guesser1_invalid", 0) / a["guesser1_decisions"] if a.get("guesser1_decisions") else None,
                "direct_share_per_valid_turn": a.get("direct_turns", 0) / (a.get("direct_turns", 0) + ct) if (a.get("direct_turns", 0) + ct) else None,
                "registered_match_per_clue_turn": a.get("registered_matches", 0) / ct if ct else None,
                "contact_per_clue_turn": a.get("contacts_awarded", 0) / ct if ct else None,
                "contact_per_registered_match": a.get("contacts_awarded", 0) / a["registered_matches"] if a.get("registered_matches") else None,
                "guesser2_invalid_per_guesser2_decision": a.get("guesser2_invalid", 0) / a["guesser2_decisions"] if a.get("guesser2_decisions") else None,
                "reveal_per_choice_opportunity": a.get("choice_reveal", 0) / a["choice_opportunities"] if a.get("choice_opportunities") else None,
            },
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
            },
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
        if r.scored and r.leg in ("AB", "BA"):
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


def analyze(run_dir: Path, records: list[dict], *, resamples: int, seed: int,
            penalty_scale: float, elo_center: float, write: bool = True) -> dict:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "run.json").read_text())
    sched = json.loads((run_dir / "schedule.json").read_text())
    models = [m["id"] for m in manifest["config"]["models"]]
    rows = load_rows(records)
    fx = fixture_results(rows, sched["fixtures"])
    complete = [f for f in fx if f["complete"]]
    fit = fit_ratings(models, [(f["model_a"], f["model_b"], f["points_a"]) for f in complete],
                      penalty_scale=penalty_scale, elo_center=elo_center)
    sensitivity = {
        str(s): fit_ratings(models, [(f["model_a"], f["model_b"], f["points_a"]) for f in complete],
                            penalty_scale=s, elo_center=elo_center).elo
        for s in (1.0, 2.5, 5.0)
    }
    stats = _model_stats(models, rows, fx)
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
    result = {
        "run_id": manifest["run_id"],
        "protocol_version": manifest["protocol_version"],
        "fixture_data": manifest.get("fixture_data", True),
        "condition": manifest["config"]["protocol"],
        "lexicon": {k: manifest["secret_lexicon"][k] for k in ("name", "sha256", "word_count", "license")},
        "models": models,
        "planned_games": len(sched["games"]),
        "recorded_games": len(rows),
        "scored_games": sum(1 for r in rows if r.scored),
        "planned_fixtures": len(sched["fixtures"]),
        "complete_fixtures": len(complete),
        "balanced_complete": len(complete) == len(sched["fixtures"]) and len(complete) > 0,
        "game_status_counts": dict(status_counts),
        "missing_model_pairs": [],
        "rating": fit.to_json(),
        "rating_penalty_sensitivity": sensitivity,
        "bootstrap": boot,
        "model_stats": stats,
        "role_diagnostics": _role_diagnostics(rows),
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
    result["resources"] = _resources(reqs)
    from .calibration import forecast_calibration

    result["forecast_calibration"] = forecast_calibration(records)
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
                    "deadline_hold_rate", "offense_mean_cost"])
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
        if r.scored and r.leg in ("AB", "BA"):
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
    L.append("## Paired competitive rating (batch Elo-style rating with half-point draws)\n")
    L.append("| Model | Elo | 95% CI | Match-point share (per fixture) | Offense speedup (ΣB/ΣC) | Mean paired cost advantage | Defensive cost ratio (ΣC/ΣB) | Deadline hold rate (per defended game) |")
    L.append("|---|---:|---|---:|---:|---:|---:|---:|")
    boot = (res.get("bootstrap") or {}).get("intervals_95", {})
    for m in sorted(res["models"], key=lambda m: -res["rating"]["elo"][m]):
        s = res["model_stats"][m]
        ci = boot.get(m, {}).get("elo", {})
        cis = f"[{ci['lo']:.0f}, {ci['hi']:.0f}]" if ci.get("lo") is not None else "—"
        L.append(
            f"| {m} | {res['rating']['elo'][m]:.0f} | {cis} | {_fmt(s['match_point_share'])} | "
            f"{_fmt((s['offense_aggregate_speedup'] or {}).get('value'))} | "
            f"{_fmt((s['mean_paired_cost_advantage'] or {}).get('value'))} | "
            f"{_fmt((s['defensive_cost_ratio'] or {}).get('value'))} | "
            f"{_fmt(s['defense_deadline_hold_rate_of_defense_games'])} |"
        )
    L.append("")
    L.append(f"Rating fit converged: {res['rating']['converged']} "
             f"(iterations {res['rating']['iterations']}, penalty scale {res['rating']['penalty_scale']}). "
             f"Connected components: {res['rating']['connected_components']}.")
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
    return "\n".join(L) + "\n"


def _fmt(x):
    return "—" if x is None else f"{x:.3f}"
