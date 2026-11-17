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
    # Mixed attacking team (human challenge): Guesser 2's model when it differs
    # from Guesser 1's (``attacker``).  Empty means a homogeneous team.
    attacker_g2: str = ""

    def seat_model(self, seat: str) -> str:
        if seat == "defender":
            return self.defender
        if seat == "guesser2" and self.attacker_g2:
            return self.attacker_g2
        return self.attacker

    @property
    def models(self) -> set[str]:
        return {self.attacker, self.defender} | ({self.attacker_g2} if self.attacker_g2 else set())


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
    # "~" cannot occur in model ids ([A-Za-z0-9_.-]), so these ids can never
    # collide with ordinary game ids produced by build_schedule.
    fid = f"{f.fixture_id}~rematch"
    gab, gba = f"{f.game_ab}~rematch", f"{f.game_ba}~rematch"
    fx = Fixture(fid, f.task_id, f.repetition, f.model_a, f.model_b, gab, gba,
                 rematch_of=f.fixture_id, initial_prefix_length=initial_prefix_length)
    games = [
        GameSpec(gab, fid, f.task_id, f.repetition, f.model_a, f.model_b, "AB", _seed("policy", gab),
                 initial_prefix_length, f.fixture_id),
        GameSpec(gba, fid, f.task_id, f.repetition, f.model_b, f.model_a, "BA", _seed("policy", gba),
                 initial_prefix_length, f.fixture_id),
    ]
    if any(g.attacker_g2 for g in games):  # pragma: no cover - defensive
        raise ValueError("mixed-team fixtures are never rematched")
    return fx, games


def _seed(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


def build_schedule(cfg: BenchConfig, tasks: list[Task]) -> tuple[list[Fixture], list[GameSpec]]:
    ids = [m.id for m in cfg.models]
    fixtures: list[Fixture] = []
    games: list[GameSpec] = []
    sched = cfg.tournament.schedule
    reps = cfg.tournament.repetitions
    if sched == "human_challenge":
        return _human_challenge_schedule(cfg, tasks)
    if sched in ("balanced_round_robin", "round_robin_plus_self_play", "pairs"):
        pair_list = ([tuple(p) for p in cfg.tournament.pairs] if sched == "pairs"
                     else list(itertools.combinations(ids, 2)))
        for a, b in pair_list:
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


def human_challenge_task_count(cfg: BenchConfig) -> int:
    """Each secret is used in exactly one fixture (a human remembers secrets)."""
    hc = cfg.tournament.human_challenge
    return cfg.tasks.tasks_per_pair * len(hc.opponents) if hc else cfg.tasks.tasks_per_pair


def _human_challenge_schedule(cfg: BenchConfig, tasks: list[Task]) -> tuple[list[Fixture], list[GameSpec]]:
    """Fixtures human-vs-opponent on disjoint secrets, attack leg first.

    Leg AB: human (Guesser 1) + opponent (Guesser 2) attack, opponent defends.
    Leg BA: opponent + opponent attack, human defends (the human now knows the
    secret, so this leg always comes second and the secret is never reused).
    The fixture order is shuffled by order_seed, independently of secrets.
    """
    hc = cfg.tournament.human_challenge
    h = hc.player
    k = cfg.tasks.tasks_per_pair
    need = human_challenge_task_count(cfg)
    if len(tasks) < need:
        raise ValueError(f"human_challenge needs {need} tasks (tasks_per_pair x opponents), got {len(tasks)}")
    fixtures: list[Fixture] = []
    legs: list[tuple[GameSpec, GameSpec]] = []
    for i, o in enumerate(hc.opponents):
        for t in tasks[i * k:(i + 1) * k]:
            fid = f"{t.task_id}-r0-{h}~{o}"
            gab = f"{t.task_id}-r0-{h}-atk-{o}"  # Guesser 2 is {o}: see attacker_g2
            gba = f"{t.task_id}-r0-{o}-atk-{h}"
            fixtures.append(Fixture(fid, t.task_id, 0, h, o, gab, gba))
            legs.append((GameSpec(gab, fid, t.task_id, 0, h, o, "AB", _seed("policy", gab), attacker_g2=o),
                         GameSpec(gba, fid, t.task_id, 0, o, h, "BA", _seed("policy", gba))))
    rng = random.Random(_seed("order", cfg.tournament.order_seed, len(legs)))
    rng.shuffle(legs)
    return fixtures, [g for pair in legs for g in pair]


def run_plan(cfg: BenchConfig, tasks: list[Task], games: list[GameSpec]) -> dict:
    m = len(cfg.models)
    K = len(tasks)
    R = cfg.tournament.repetitions
    L = cfg.protocol.turn_limit
    llm_models = {mc.id for mc in cfg.models if mc.is_llm}
    fork = cfg.forecasts.mode == "fork"
    # At most 4 decisions per clue turn: G1, G2 and conditional choice by
    # attackers, blocklist by defender.  Fork mode adds up to one forecast
    # branch after each of G1, G2 (attacking model) and the Defender.
    att_calls = 3 * L + (2 * L if fork else 0)
    def_calls = L + (L if fork else 0)
    per_model_calls: dict[str, int] = {}
    # A cross-model game can be followed by one rematch game (no-progress draw
    # rule), so the advertised maxima include that possibility.
    rematch = cfg.tournament.rematch_on_no_progress_draw
    secret_len = {t.task_id: len(t.secret) for t in tasks}
    base_prefix = cfg.protocol.initial_prefix_length
    step = cfg.tournament.rematch_extra_letters
    max_games = list(games)
    if rematch:
        for g in games:
            if g.leg not in ("AB", "BA"):
                continue
            # Recursive chains can continue until len(secret) - 1 letters are revealed.
            levels = ((secret_len[g.task_id] - 1 - base_prefix) // step if cfg.tournament.rematch_recursive
                      else 1)
            max_games.extend([g] * max(0, levels))
    for g in max_games:
        if g.attacker_g2:
            # Mixed team: Guesser 1 acts and may choose (2 calls/turn); Guesser 2
            # responds and may choose (2 calls/turn).
            for mid in (g.attacker, g.attacker_g2):
                if mid in llm_models:
                    per_model_calls[mid] = per_model_calls.get(mid, 0) + 2 * L
        elif g.attacker in llm_models:
            per_model_calls[g.attacker] = per_model_calls.get(g.attacker, 0) + att_calls
        if g.defender in llm_models:
            per_model_calls[g.defender] = per_model_calls.get(g.defender, 0) + def_calls
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
        "maximum_rematch_games": len(max_games) - len(games),
        "maximum_game_decisions_total": 4 * L * len(max_games),
        "maximum_paid_decisions": sum(per_model_calls.values()),
        "forecast_fork_calls_included": fork,
        "maximum_paid_decisions_by_model": per_model_calls,
        "forecast_mode": cfg.forecasts.mode,
        "separate_planning_items": [
            "transport retries (up to max_transport_attempts per decision)",
            "shadow forecast audit calls (separate command)",
            "joint-live forecast token growth" if cfg.forecasts.mode == "joint_live" else None,
            "blocklist output capacity (see preflight)",
            "lookup-tool turns (lookup_tools condition): up to max_tool_calls_per_decision + 2 model calls per decision",
        ],
        "estimated_cost": None,
    }
    plan["separate_planning_items"] = [x for x in plan["separate_planning_items"] if x]
    return plan
