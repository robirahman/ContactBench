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
    # Mixed-team games name each guesser seat's model ("" = the attacker
    # model, i.e. a homogeneous team).  ``attacker`` then holds the team id.
    guesser1_model: str = ""
    guesser2_model: str = ""
    round: int = 0


def seat_model(g: "GameSpec", seat: str) -> str:
    """Model id playing ``seat`` in game ``g``."""
    if seat == "defender":
        return g.defender
    if seat == "guesser1":
        return g.guesser1_model or g.attacker
    if seat == "guesser2":
        return g.guesser2_model or g.attacker
    raise ValueError(seat)


def game_models(g: "GameSpec") -> set[str]:
    return {seat_model(g, s) for s in ("guesser1", "guesser2", "defender")}


def team_id(g1: str, g2: str) -> str:
    """'+' cannot occur in model ids, so team ids never collide with them."""
    return f"{g1}+{g2}"


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
    # "model_pair" (homogeneous A attacks B / B attacks A), or for mixed teams
    # "role" (A+B vs B+A against one defender) and "self_play" (A+A vs B+B).
    kind: str = "model_pair"
    defender_model: str = ""
    round: int = 0


def is_no_progress_capped(summary: dict) -> bool:
    """Capped game in which the attackers earned no letter."""
    return summary.get("outcome_status") == "capped" and summary.get("final_prefix") == summary.get("initial_prefix")


def rematch_fixture(f: Fixture, initial_prefix_length: int, spec_ab: "GameSpec | None" = None,
                    spec_ba: "GameSpec | None" = None) -> tuple[Fixture, list[GameSpec]]:
    """Rematch of fixture ``f`` with a longer revealed prefix.

    When the original leg specs are given, the rematch copies each leg's seat
    assignment (attacker/guesser/defender models), which is required for
    mixed-team fixtures; otherwise the homogeneous model_pair layout is used.
    """
    from dataclasses import replace

    # "~" cannot occur in model ids ([A-Za-z0-9_.-]), so these ids can never
    # collide with ordinary game ids produced by build_schedule.
    fid = f"{f.fixture_id}~rematch"
    gab, gba = f"{f.game_ab}~rematch", f"{f.game_ba}~rematch"
    fx = replace(f, fixture_id=fid, game_ab=gab, game_ba=gba, rematch_of=f.fixture_id,
                 initial_prefix_length=initial_prefix_length)
    if spec_ab is not None and spec_ba is not None:
        games = [
            replace(spec_ab, game_id=gab, fixture_id=fid, policy_seed=_seed("policy", gab),
                    initial_prefix_length=initial_prefix_length, rematch_of=f.fixture_id),
            replace(spec_ba, game_id=gba, fixture_id=fid, policy_seed=_seed("policy", gba),
                    initial_prefix_length=initial_prefix_length, rematch_of=f.fixture_id),
        ]
        return fx, games
    games = [
        GameSpec(gab, fid, f.task_id, f.repetition, f.model_a, f.model_b, "AB", _seed("policy", gab),
                 initial_prefix_length, f.fixture_id),
        GameSpec(gba, fid, f.task_id, f.repetition, f.model_b, f.model_a, "BA", _seed("policy", gba),
                 initial_prefix_length, f.fixture_id),
    ]
    return fx, games


def team_block(task_id: str, rep: int, a: str, b: str, defender: str, *, include_self_play: bool,
               round_no: int) -> tuple[list[Fixture], list[GameSpec]]:
    """One mixed-team block: legs A+B and B+A (role fixture) and optionally
    A+A and B+B (self-play fixture), all against ``defender`` on one task."""
    block = f"{task_id}-r{rep}-{a}~{b}"
    fixtures: list[Fixture] = []
    games: list[GameSpec] = []

    def leg(g1: str, g2: str, label: str) -> GameSpec:
        gid = f"{block}@{team_id(g1, g2)}-atk-{defender}"
        return GameSpec(gid, "", task_id, rep, team_id(g1, g2), defender, label, _seed("policy", gid),
                        guesser1_model=g1, guesser2_model=g2, round=round_no)

    pairs = [("role", (a, b), (b, a))]
    if include_self_play:
        pairs.append(("self_play", (a, a), (b, b)))
    for kind, t1, t2 in pairs:
        fid = f"{block}~{kind}@{defender}"
        l1, l2 = leg(*t1, "L1"), leg(*t2, "L2")
        from dataclasses import replace

        l1, l2 = replace(l1, fixture_id=fid), replace(l2, fixture_id=fid)
        fixtures.append(Fixture(fid, task_id, rep, team_id(*t1), team_id(*t2), l1.game_id, l2.game_id,
                                kind=kind, defender_model=defender, round=round_no))
        games.extend([l1, l2])
    return fixtures, games


def _seed(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


def build_schedule(cfg: BenchConfig, tasks: list[Task]) -> tuple[list[Fixture], list[GameSpec]]:
    ids = [m.id for m in cfg.models]
    fixtures: list[Fixture] = []
    games: list[GameSpec] = []
    sched = cfg.tournament.schedule
    reps = cfg.tournament.repetitions
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
    # schedule "teams" is built round by round by the runner (adaptive
    # defender selection), so it starts empty here.
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
    candidates: dict[str, list[str]] = {}
    if cfg.tournament.schedule == "teams" and not games:
        # Defenders are chosen adaptively at run time: project one block per
        # (pair, task) and charge every eligible defender as an upper bound.
        t = cfg.tournament.teams
        ids = [mc.id for mc in cfg.models]
        pool = t.defender_pool if t.defender_pool is not None else ids
        for a, b in t.pairs:
            for task in tasks:
                for r in range(R):
                    _, gs = team_block(task.task_id, r, a, b, "?", include_self_play=t.include_self_play,
                                       round_no=0)
                    for g in gs:
                        candidates[g.game_id] = [d for d in pool if d not in (a, b)]
                    games = list(games) + gs
    max_games = list(games)
    if rematch:
        for g in games:
            if g.leg not in ("AB", "BA", "L1", "L2"):
                continue
            # Recursive chains can continue until len(secret) - 1 letters are revealed.
            levels = ((secret_len[g.task_id] - 1 - base_prefix) // step if cfg.tournament.rematch_recursive
                      else 1)
            max_games.extend([g] * max(0, levels))
    def add(model: str, n: int) -> None:
        if model in llm_models:
            per_model_calls[model] = per_model_calls.get(model, 0) + n

    for g in max_games:
        if g.guesser1_model:
            # Mixed team: each guesser may also make the conditional choice.
            g1, g2 = seat_model(g, "guesser1"), seat_model(g, "guesser2")
            if g1 == g2:
                add(g1, att_calls)
            else:
                add(g1, att_calls - L)
                add(g2, att_calls - L)
        else:
            add(g.attacker, att_calls)
        for d in candidates.get(g.game_id, [g.defender]):
            add(d, def_calls)
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
