"""Sanitized public export built from an explicit field allowlist (spec 16, 17).

Nothing is copied wholesale from run records.  Every exported object is
constructed field by field, and the final bundle is scanned for credential
patterns and environment secrets before it is written.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from .. import PACKING_VERSION, PROTOCOL_VERSION, RNG_VERSION, SCHEMA_VERSION

CREDENTIAL_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)\b(x-api-key|authorization|api[_-]?key)\b\s*[:=]"),
]
CREDENTIAL_ENVS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


MAX_EXPORTED_CANDIDATE_LIST = 2000


class ExportLeakError(RuntimeError):
    pass


def _pick(d: dict | None, keys: list[str]) -> dict | None:
    if d is None:
        return None
    return {k: d.get(k) for k in keys}


MODEL_KEYS = ["id", "provider", "api_family", "model", "parameters", "max_output_tokens",
              "context_window_tokens", "prompt_version", "policy", "defender_policy", "choice_policy",
              "offense_mode"]
PROTOCOL_KEYS = None  # all protocol fields are public rule settings


def _public_event(e: dict) -> dict:
    """Public history events contain only public fields by construction; re-pick anyway."""
    keys = ["turn", "type", "seat", "word", "clue", "blocklist", "blocked_ranges", "blocked_word_count",
            "blocklist_collected", "opened_guesses",
            "prefix_after", "result", "terminal_reason", "hit_sources"]
    out = {k: e[k] for k in keys if k in e}
    if "opened_guesses" in out:
        out["opened_guesses"] = [{"seat": g["seat"], "word": g["word"]} for g in out["opened_guesses"]]
    return out


def _audit_turn(t: dict) -> dict:
    keys = ["turn", "prefix_before", "prefix_after", "w1", "w2", "clue", "mentions", "blocklist", "blocked_ranges",
            "blocked_guesser1", "blocked_guesser2", "choice_actor", "choice", "choice_valid", "opened",
            "emissions", "target_hit", "hit_sources", "registered_match", "intended_covered",
            "covered_match", "fresh_for_contact", "contact", "blocked_contact", "result",
            "secret_candidates_before", "secret_candidates_after", "block_size",
            "block_fresh_secret_candidates", "block_overlap_with_clue"]
    out = {k: t[k] for k in keys if k in t}
    if isinstance(out.get("emissions"), list) and len(out["emissions"]) > MAX_EXPORTED_CANDIDATE_LIST:
        # Range blocks can emit tens of thousands of words; the set is fully
        # recomputable from the clue, explicit blocklist, ranges and openings.
        out["emission_count"] = len(out["emissions"])
        out["emissions"] = None
    for seat in ("guesser1", "guesser2", "defender"):
        if t.get(seat) is not None:
            out[f"{seat}_valid"] = t[seat].get("valid")
            out[f"{seat}_action"] = (t[seat].get("canonical") or {}).get("action")
    return out


def _private_entry(e: dict) -> dict:
    keys = ["turn", "action", "word", "committed_word", "clue", "validity", "reason", "canonical_action",
            "canonical_blocklist", "canonical_ranges"]
    out = {k: e[k] for k in keys if k in e}
    if "conditional_choice" in e:
        out["conditional_choice"] = _pick(e["conditional_choice"], ["offered", "partner_word_blocked", "choice", "validity"])
    return out


def _score(sc: dict | None) -> dict | None:
    if not sc:
        return None
    ref_keys = ["numerator", "denominator", "value", "exact", "method", "histogram", "target_length", "C",
                "mcse", "rollouts", "rank_total", "rank_denominator", "cache_key"]
    return {
        "status": sc.get("status"),
        "cost": sc.get("cost"),
        "cost_numerator": sc.get("cost_numerator"),
        "cost_denominator": sc.get("cost_denominator"),
        "cost_exact": sc.get("cost_exact"),
        "cost_mcse": sc.get("cost_mcse"),
        "baseline": _pick(sc.get("baseline"), ref_keys),
        "fallback": _pick(sc.get("fallback"), ref_keys),
    }


def scan_for_secrets(root: Path, extra_secrets: list[str] | None = None) -> list[str]:
    secrets = [os.environ.get(e) for e in CREDENTIAL_ENVS]
    secrets = [s for s in secrets + list(extra_secrets or []) if s]
    hits = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        text = p.read_text(errors="replace")
        for s in secrets:
            if s in text:
                hits.append(f"{p}: credential value")
        for pat in CREDENTIAL_PATTERNS:
            if pat.search(text):
                hits.append(f"{p}: matches {pat.pattern}")
    return hits


def export_public(run_dir: Path, out_dir: Path, analysis: dict, records: list[dict], *,
                  include_audit: bool = False, max_replays: int | None = None, release_label: str | None = None,
                  extra_secrets: list[str] | None = None) -> Path:
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    manifest = json.loads((run_dir / "run.json").read_text())
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "replays").mkdir(parents=True)
    cfg = manifest["config"]
    condition = {
        "protocol_version": cfg["protocol"]["version"],
        "protocol": cfg["protocol"],
        "dictionary_access": cfg["protocol"].get("dictionary_access", "full_candidate_lists"),
        "blocklist_encoding": cfg["protocol"].get("blocklist_encoding", "words"),
        "initial_prefix_length": cfg["protocol"].get("initial_prefix_length", 1),
        "max_tool_calls_per_decision": cfg["protocol"].get("max_tool_calls_per_decision"),
        "clue_max_characters": cfg["protocol"]["clue_max_characters"],
        "turn_limit": cfg["protocol"]["turn_limit"],
        "target_hit_scope": cfg["protocol"]["target_hit_scope"],
        "reveal_policy": cfg["protocol"]["reveal_policy"],
        "timing": cfg["protocol"]["timing"],
        "count_cap": cfg["protocol"]["clue_max_live_candidate_mentions"],
        "lexicon_name": manifest["secret_lexicon"]["name"],
        "lexicon_sha256": manifest["secret_lexicon"]["sha256"],
        "resolver": cfg["scoring"]["resolver"],
        "packing_version": PACKING_VERSION,
        "rng_version": RNG_VERSION,
        "numerical_rollouts": cfg["scoring"]["proposed_final_rollouts"] if cfg["scoring"]["use_final_rollouts"] else cfg["scoring"]["development_rollouts"],
        "forecast_mode": cfg["forecasts"]["mode"],
        # Scoring rules that change fixture points (and hence ratings) are part
        # of the condition identity; older snapshots take the current defaults.
        "no_progress_draws": cfg.get("tournament", {}).get("no_progress_draws", True),
        "rematch_on_no_progress_draw": cfg.get("tournament", {}).get("rematch_on_no_progress_draw", True),
        "rematch_extra_letters": cfg.get("tournament", {}).get("rematch_extra_letters", 1),
        "inference_profiles": {m["id"]: _pick(m, ["provider", "api_family", "model", "parameters", "max_output_tokens"]) for m in cfg["models"]},
    }
    ckey = hashlib.sha256(json.dumps(condition, sort_keys=True).encode()).hexdigest()[:16]
    pub_manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": cfg["protocol"]["version"],
        "run_id": manifest["run_id"],
        "run_created_at": manifest["created_at"],
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "code_revision": manifest.get("code_revision"),
        "prompt_version": manifest.get("prompt_version"),
        "prompt_hash": manifest.get("prompt_hash"),
        "fixture_data": manifest.get("fixture_data", True),
        "release_label": release_label,
        "condition": condition,
        "condition_key": ckey,
        "lexicon": _pick(manifest["secret_lexicon"], ["name", "word_count", "sha256", "source", "license", "source_revision"]),
        "release_policy": {
            "secrets_revealed_post_game": True,
            "omniscient_audit_included": include_audit,
            "seat_private_histories_included": include_audit,
            "note": "Players never saw secrets (except the defender), hidden commitments or audit fields during play.",
        },
        "licenses": {"code": "see repository LICENSE", "lexicon": manifest["secret_lexicon"].get("license"),
                     "transcripts": "researcher to declare before publication"},
        "models": [_pick(m, MODEL_KEYS) for m in cfg["models"]],
    }
    keep = ["run_id", "protocol_version", "fixture_data", "models", "planned_games", "recorded_games",
            "scored_games", "planned_fixtures", "complete_fixtures", "rematch_fixtures", "no_progress_draw_rule",
            "no_progress_draws", "balanced_complete", "game_status_counts",
            "missing_model_pairs", "rating", "rating_penalty_sensitivity", "bootstrap", "model_stats",
            "role_diagnostics", "pairwise_match_points", "pairwise_mean_cost", "capped_games",
            "capped_fraction_of_scored_games", "residual_candidate_counts_capped", "strata",
            "numerical_reference", "numerically_close_fixtures", "resources", "forecast_calibration"]
    leaderboard = {k: analysis.get(k) for k in keep}
    fixtures = [_pick(f, ["fixture_id", "task_id", "repetition", "model_a", "model_b", "complete", "cost_ab",
                          "cost_ba", "points_a", "points_b", "cost_difference_mcse", "numerically_close",
                          "no_progress_draw", "rematch_of", "initial_prefix_length"])
                for f in analysis.get("fixtures", [])]
    games = []
    for i, r in enumerate(sorted(records, key=lambda r: r["game"]["game_id"])):
        g, s = r["game"], r["summary"]
        games.append({
            "game_id": g["game_id"], "fixture_id": g["fixture_id"], "task_id": g["task_id"],
            "repetition": g["repetition"], "attacker": g["attacker"], "defender": g["defender"], "leg": g["leg"],
            "secret": s["secret"], "initial_prefix": s["initial_prefix"], "final_prefix": s["final_prefix"],
            "outcome_status": s["outcome_status"], "terminal_reason": s["terminal_reason"],
            "collection_status": s["collection_status"], "turns_used": s["turns_used"],
            "turn_limit": s["turn_limit"], "hit_sources": s["hit_sources"],
            "initial_secret_candidate_count": s["initial_secret_candidate_count"],
            "final_secret_candidate_count": s["final_secret_candidate_count"],
            "score": _score(r.get("score")),
        })
        if max_replays is None or i < max_replays:
            rep = {
                "game_id": g["game_id"], "attacker": g["attacker"], "defender": g["defender"],
                "secret": s["secret"], "initial_prefix": s["initial_prefix"], "turn_limit": s["turn_limit"],
                # Large initial sets (e.g. a whole dictionary at prefix length 0)
                # are recomputable from the public lexicon and prefix; export the count.
                "initial_secret_candidate_count": len(r.get("initial_secret_candidates", [])),
                **({"initial_secret_candidates": list(r["initial_secret_candidates"])}
                   if len(r.get("initial_secret_candidates", [])) <= MAX_EXPORTED_CANDIDATE_LIST else {}),
                "outcome_status": s["outcome_status"], "terminal_reason": s["terminal_reason"],
                "public_history": [_public_event(e) for e in r.get("public_history", [])],
                "score": _score(r.get("score")),
            }
            if include_audit:
                rep["seat_private_histories"] = {
                    seat: [_private_entry(e) for e in hist]
                    for seat, hist in (r.get("private_histories") or {}).items()
                }
                rep["referee_audit"] = [_audit_turn(t) for t in r.get("referee_audit", [])]
            (out_dir / "replays" / f"{g['game_id']}.json").write_text(json.dumps(rep, indent=1) + "\n")
    (out_dir / "manifest.json").write_text(json.dumps(pub_manifest, indent=2) + "\n")
    (out_dir / "leaderboard.json").write_text(json.dumps(leaderboard, indent=2, default=str) + "\n")
    (out_dir / "fixtures.json").write_text(json.dumps(fixtures, indent=1) + "\n")
    (out_dir / "games.json").write_text(json.dumps(games, indent=1) + "\n")
    with (out_dir / "games.csv").open("w", newline="") as f:
        w = csv.writer(f)
        cols = ["game_id", "task_id", "attacker", "defender", "leg", "secret", "outcome_status",
                "terminal_reason", "collection_status", "turns_used", "initial_secret_candidate_count",
                "final_secret_candidate_count"]
        w.writerow(cols + ["baseline", "cost", "cost_exact", "cost_mcse"])
        for g in games:
            sc = g["score"] or {}
            w.writerow([g[c] for c in cols] + [(sc.get("baseline") or {}).get("value"), sc.get("cost"),
                                               sc.get("cost_exact"), sc.get("cost_mcse")])
    hits = scan_for_secrets(out_dir, extra_secrets)
    if hits:
        shutil.rmtree(out_dir)
        raise ExportLeakError("export aborted; credential-like content found: " + "; ".join(hits[:5]))
    return out_dir
