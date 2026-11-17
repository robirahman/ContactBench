"""Balanced paired schedule and run plan (spec Sections 9.1 and 14.1)."""

from __future__ import annotations

import hashlib
import itertools
import math
import random
from dataclasses import asdict, dataclass

from ..config import BenchConfig
from .tasks import Task


@dataclass(frozen=True)
class GameSpec:
    game_id: str
    fixture_id: str
    task_id: str
    repetition: int
    attacker: str
    defender: str
    leg: str  # "AB" or "BA" or "self"
    policy_seed: int
    # Rematch games override the starting prefix length.
    initial_prefix_length: int | None = None
    rematch_of: str = ""


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    task_id: str
    repetition: int
    model_a: str
    model_b: str
    game_ab: str  # A attacks, B defends
    game_ba: str  # B attacks, A defends
    rematch_of: str = ""  # fixture id of the no-progress draw this rematches
    initial_prefix_length: int | None = None


def is_no_progress_capped(summary: dict) -> bool:
    """Capped game in which the attackers earned no letter."""
    return summary.get("outcome_status") == "capped" and summary.get("final_prefix") == summary.get("initial_prefix")


def rematch_fixture(f: Fixture, initial_prefix_length: int) -> tuple[Fixture, list[GameSpec]]:
    fid = f"{f.fixture_id}~rematch"
    gab, gba = f"{f.game_ab}-rematch", f"{f.game_ba}-rematch"
    fx = Fixture(fid, f.task_id, f.repetition, f.model_a, f.model_b, gab, gba,
                 rematch_of=f.fixture_id, initial_prefix_length=initial_prefix_length)
    games = [
        GameSpec(gab, fid, f.task_id, f.repetition, f.model_a, f.model_b, "AB", _seed("policy", gab),
                 initial_prefix_length, f.fixture_id),
        GameSpec(gba, fid, f.task_id, f.repetition, f.model_b, f.model_a, "BA", _seed("policy", gba),
                 initial_prefix_length, f.fixture_id),
    ]
    return fx, games


def _seed(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


def build_schedule(cfg: BenchConfig, tasks: list[Task]) -> tuple[list[Fixture], list[GameSpec]]:
    ids = [m.id for m in cfg.models]
    fixtures: list[Fixture] = []
    games: list[GameSpec] = []
    sched = cfg.tournament.schedule
    reps = cfg.tournament.repetitions
    if sched in ("balanced_round_robin", "round_robin_plus_self_play"):
        for a, b in itertools.combinations(ids, 2):
            for t in tasks:
                for r in range(reps):
                    fid = f"{t.task_id}-r{r}-{a}~{b}"
                    gab = f"{t.task_id}-r{r}-{a}-atk-{b}"
                    gba = f"{t.task_id}-r{r}-{b}-atk-{a}"
                    fixtures.append(Fixture(fid, t.task_id, r, a, b, gab, gba))
                    games.append(GameSpec(gab, fid, t.task_id, r, a, b, "AB", _seed("policy", gab)))
                    games.append(GameSpec(gba, fid, t.task_id, r, b, a, "BA", _seed("policy", gba)))
    if sched in ("self_play", "round_robin_plus_self_play"):
        for a in ids:
            for t in tasks:
                for r in range(reps):
                    gid = f"{t.task_id}-r{r}-{a}-atk-{a}"
                    games.append(GameSpec(gid, "", t.task_id, r, a, a, "self", _seed("policy", gid)))
    # Execution order is randomized independently of secrets and outcomes.
    rng = random.Random(_seed("order", cfg.tournament.order_seed, len(games)))
    order = list(games)
    rng.shuffle(order)
    return fixtures, order


def run_plan(cfg: BenchConfig, tasks: list[Task], games: list[GameSpec]) -> dict:
    m = len(cfg.models)
    K = len(tasks)
    R = cfg.tournament.repetitions
    L = cfg.protocol.turn_limit
    llm_models = {mc.id for mc in cfg.models if mc.is_llm}
    llm_games = [g for g in games if g.attacker in llm_models or g.defender in llm_models]
    per_model_calls: dict[str, int] = {}
    for g in games:
        # At most 4 decisions per clue turn: G1, G2 and conditional choice by
        # attackers, blocklist by defender.
        if g.attacker in llm_models:
            per_model_calls[g.attacker] = per_model_calls.get(g.attacker, 0) + 3 * L
        if g.defender in llm_models:
            per_model_calls[g.defender] = per_model_calls.get(g.defender, 0) + L
    plan = {
        "models": [mc.id for mc in cfg.models],
        "llm_models": sorted(llm_models),
        "schedule": cfg.tournament.schedule,
        "tasks": K,
        "repetitions": R,
        "turn_limit": L,
        "raw_games": len(games),
        "expected_round_robin_games": m * (m - 1) * K * R
        if cfg.tournament.schedule == "balanced_round_robin"
        else None,
        "maximum_game_decisions_per_game": 4 * L,
        "maximum_game_decisions_total": 4 * L * len(games),
        "maximum_paid_decisions": 4 * L * len(llm_games),
        "maximum_paid_decisions_by_model": per_model_calls,
        "forecast_mode": cfg.forecasts.mode,
        "separate_planning_items": [
            "transport retries (up to max_transport_attempts per decision)",
            "shadow forecast audit calls (separate command)",
            "joint-live forecast token growth" if cfg.forecasts.mode == "joint_live" else None,
            "blocklist output capacity (see preflight)",
        ],
        "estimated_cost": None,
    }
    plan["separate_planning_items"] = [x for x in plan["separate_planning_items"] if x]
    return plan
