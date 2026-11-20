"""ContactBench as an Inspect task: the evaluated model plays fixtures against a
fixed reference panel and is rated on the arena's Elo scale with the panel's
ratings held fixed (the same anchored fit used for human challenges).

One sample = one fixture on one secret against one panel opponent:

- AB leg: the evaluated model attacks (Guesser 1 and Guesser 2 are separate
  instances of it) and the opponent defends.
- BA leg: two opponent instances attack and the evaluated model defends.

The fixture point goes to the side with the lower attacking cost; two capped
legs with no letter earned are a draw.  As in the arena, a no-progress draw is
replayed on the same secret with one more letter revealed, recursively, and
every fixture counts.  The engine, prompts, admission rules and cost scoring
are the arena's own code; only the model transport is Inspect.

Usage:
    inspect eval contact_bench/inspect_task/task.py --model openai/gpt-6.2-sol \\
        -T secrets_per_opponent=4 --reasoning-effort low
Opponents can be re-bound with --model-role (e.g. --model-role terra=...), but
the frozen Elo then no longer applies to that opponent; the log records the
models actually used.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import GenerateConfig, get_model, model_roles
from inspect_ai.scorer import Metric, SampleScore, Score, Target, metric, scorer
from inspect_ai.solver import Generate, TaskState, solver

from contact_bench.analysis.rating import fit_anchored, match_points
from contact_bench.config import BenchConfig, ModelConfig, load_config
from contact_bench.engine.game import OUTCOME_CAPPED, OUTCOME_SOLVED, DecisionSpec, Game, Unavailable
from contact_bench.policies.llm import ContextOverflowError, Limiters, LLMAgent
from contact_bench.providers.base import InfrastructureError
from contact_bench.runner.run import load_lexicons, make_scorer
from contact_bench.runner.tasks import generate_tasks
from contact_bench.dictionary import DictionaryService
from contact_bench.scoring.cost import score_game
from contact_bench.inspect_task.adapter import InspectAdapter

REPO = Path(__file__).resolve().parents[2]
PANELS = Path(__file__).resolve().parent / "panels"
EVALUATED = "evaluated"


def load_panel(name: str) -> dict:
    p = Path(name)
    if not p.suffix:
        p = PANELS / f"{name}.json"
    return json.loads(p.read_text())


class _Env:
    """Lexicons, dictionary and reference scorer shared by all samples."""

    _cache: dict[str, "_Env"] = {}

    def __init__(self, cfg: BenchConfig):
        self.cfg = cfg
        self.v_secret, self.v_contact = load_lexicons(cfg)
        self.dictionary = DictionaryService(self.v_contact)
        self.scorer = make_scorer(cfg)
        self.limiters = Limiters(10_000, 10_000)  # Inspect's max_connections governs concurrency

    @classmethod
    def get(cls, condition_config: str) -> "_Env":
        if condition_config not in cls._cache:
            cfg = load_config(REPO / condition_config)
            cache = Path.home() / ".cache" / "contact_bench" / "reference"
            cfg = cfg.model_copy(update={"scoring": cfg.scoring.model_copy(update={"cache_dir": str(cache)})})
            cls._cache[condition_config] = _Env(cfg)
        return cls._cache[condition_config]


def _model_config(mid: str, max_tokens: int | None) -> ModelConfig:
    # Context-window checks are left to the provider; prices are not tracked here
    # (Inspect logs token usage per call).
    return ModelConfig(id=mid, provider="fake", model=mid, max_output_tokens=max_tokens)


def _agent(env: _Env, seat: str, mid: str, model, max_tokens: int | None) -> LLMAgent:
    p = env.cfg.protocol
    return LLMAgent(
        model=_model_config(mid, max_tokens),
        adapter=InspectAdapter(_model_config(mid, max_tokens), model),
        seat=seat,
        clue_max_characters=p.clue_max_characters,
        turn_limit=p.turn_limit,
        limiters=env.limiters,
        dictionary_access=p.dictionary_access,
        dictionary_service=env.dictionary,
        max_tool_calls=p.max_tool_calls_per_decision,
        block_ranges=p.blocklist_encoding == "words_and_ranges",
        empty_prefix=p.initial_prefix_length == 0,
    )


async def _play_leg(env: _Env, game_id: str, secret: str, prefix_len: int, attacker: tuple, defender: tuple,
                    max_tokens: int | None) -> dict:
    """Play one game; attacker/defender are (model_id, inspect Model)."""
    protocol = env.cfg.protocol.model_copy(update={"initial_prefix_length": prefix_len})
    game = Game(game_id=game_id, secret=secret, v_secret=env.v_secret, v_contact=env.v_contact, protocol=protocol)
    seats = {"guesser1": attacker, "guesser2": attacker, "defender": defender}
    agents = {s: _agent(env, s, mid, model, max_tokens) for s, (mid, model) in seats.items()}
    errors: list[str] = []

    async def decide(spec: DecisionSpec):
        try:
            out = await agents[spec.seat].decide(spec, f"{game_id}/{spec.key}")
        except (InfrastructureError, ContextOverflowError) as e:
            errors.append(f"{spec.key}: {e}")
            return Unavailable(getattr(e, "category", "context_overflow"))
        return out.raw

    await game.play(decide)
    if errors or not game.terminal or game.collection_status != "complete":
        # Never score an infrastructure failure as play: Inspect marks the sample
        # as errored (retry with --retry-on-error).
        raise RuntimeError(f"{game_id}: game could not be completed: {'; '.join(errors) or game.pending}")
    sc = score_game(
        outcome_status=game.outcome_status, winning_turn=game.winning_turn, turn_limit=game.turn_limit,
        secret=secret, initial_candidates=game.initial_secret_candidates,
        final_candidates=game.secret_candidates() if game.outcome_status == OUTCOME_CAPPED else None,
        scorer=env.scorer)
    s = game.summary()
    return {"game_id": game_id, "attacker": attacker[0], "defender": defender[0], "cost": sc.cost,
            "outcome_status": s["outcome_status"], "turns_used": s.get("turns_used"),
            "initial_prefix": s.get("initial_prefix"), "final_prefix": s.get("final_prefix"),
            "public_history": game.public_history}


def _no_progress(leg: dict) -> bool:
    return leg["outcome_status"] == "capped" and leg["final_prefix"] == leg["initial_prefix"]


@solver
def contact_fixture(panel: dict, condition_config: str, rematches: bool = True):
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        env = _Env.get(condition_config)
        md = state.metadata
        opp = md["opponent"]
        spec = panel["opponents"][opp]
        # A --model-role binding for this opponent overrides the panel default.
        bound = model_roles().get(opp)
        opp_model = bound or get_model(spec["model"], config=GenerateConfig(**spec["config"]))
        # A --model-role binding replaces the calibrated panel model, so its frozen
        # Elo no longer applies: such samples are left out of the anchored metrics.
        md["opponent_rebound"] = bound is not None
        me = (EVALUATED, get_model())
        them = (spec["board_id"], opp_model)
        # Each model keeps its own token limit: Inspect's CLI/config for the evaluated
        # model, the panel config (or the role binding) for the opponent.
        max_tokens = None
        secret = md["secret"]
        prefix = env.cfg.protocol.initial_prefix_length
        fixtures = []
        while True:
            fid = f"{state.sample_id}-p{prefix}"
            # A TaskGroup cancels the other leg if one fails, so no orphaned leg keeps
            # making (paid) model calls while Inspect records or retries the sample.
            async with asyncio.TaskGroup() as tg:
                t_ab = tg.create_task(_play_leg(env, f"{fid}-AB", secret, prefix, me, them, max_tokens))
                t_ba = tg.create_task(_play_leg(env, f"{fid}-BA", secret, prefix, them, me, max_tokens))
            ab, ba = t_ab.result(), t_ba.result()
            draw = _no_progress(ab) and _no_progress(ba)
            pts = 0.5 if draw else match_points(ab["cost"], ba["cost"])
            fixtures.append({"fixture_id": fid, "initial_prefix_length": prefix, "points": pts,
                             "no_progress_draw": draw, "cost_attack": float(ab["cost"]),
                             "cost_defend": float(ba["cost"]), "legs": [_public(ab), _public(ba)]})
            if not (rematches and draw and len(secret) > prefix + 1):
                break
            prefix += 1
        md["fixtures"] = fixtures
        md["opponent_model"] = str(opp_model)
        state.output.completion = json.dumps([{k: f[k] for k in ("fixture_id", "points", "no_progress_draw")}
                                              for f in fixtures])
        state.completed = True
        return state

    return solve


def _public(leg: dict) -> dict:
    out = {k: v for k, v in leg.items() if k != "cost"}
    out["cost"] = float(leg["cost"])
    return out


def _results(scores: list[SampleScore], anchored_only: bool = True) -> list[tuple[str, str, float]]:
    res = []
    for s in scores:
        md = s.score.metadata or {}
        if anchored_only and md.get("opponent_rebound"):
            continue
        for f in md.get("fixtures", []):
            res.append((EVALUATED, md["opponent_board_id"], f["points"]))
    return res


def _fixed(scores: list[SampleScore]) -> dict[str, float]:
    out = {}
    for s in scores:
        md = s.score.metadata or {}
        if "opponent_board_id" in md:
            out[md["opponent_board_id"]] = md["opponent_elo"]
    return out


def _anchored(scores: list[SampleScore], key: str) -> float:
    res = _results(scores)
    if not res:
        return float("nan")
    md = scores[0].score.metadata or {}
    fit = fit_anchored(_fixed(scores), res, [EVALUATED], penalty_scale=md.get("penalty_scale", 2.5),
                       elo_center=md.get("elo_center", 1500.0))
    v = fit["elo"][EVALUATED] if key == "elo" else fit["elo_se_approx"][EVALUATED]
    return float("nan") if v is None else float(v)


@metric
def anchored_elo() -> Metric:
    """Elo of the evaluated model with the panel's frozen ratings held fixed."""
    def m(scores: list[SampleScore]) -> float:
        return _anchored(scores, "elo")
    return m


@metric
def anchored_elo_se() -> Metric:
    def m(scores: list[SampleScore]) -> float:
        return _anchored(scores, "se")
    return m


@metric
def match_point_share() -> Metric:
    """Bounded companion score in [0, 1]: mean fixture points against the panel."""
    def m(scores: list[SampleScore]) -> float:
        pts = [p for _, _, p in _results(scores, anchored_only=False)]
        return sum(pts) / len(pts) if pts else float("nan")
    return m


@scorer(metrics=[anchored_elo(), anchored_elo_se(), match_point_share()])
def fixture_scorer(panel: dict):
    async def score(state: TaskState, target: Target) -> Score:
        md = state.metadata
        fixtures = md.get("fixtures") or []
        spec = panel["opponents"][md["opponent"]]
        pts = [f["points"] for f in fixtures]
        return Score(
            value=sum(pts) / len(pts) if pts else 0.0,
            answer=state.output.completion,
            explanation=f"{len(fixtures)} fixture(s) vs {md['opponent']} ({md.get('opponent_model')}): points {pts}"
                        + (" [opponent re-bound with --model-role: excluded from anchored_elo]"
                           if md.get("opponent_rebound") else ""),
            metadata={"opponent": md["opponent"], "opponent_board_id": spec["board_id"],
                      "opponent_elo": spec["elo"], "opponent_model": md.get("opponent_model"),
                      "opponent_rebound": bool(md.get("opponent_rebound")),
                      "penalty_scale": panel["penalty_scale"], "elo_center": panel["elo_center"],
                      "fixtures": [{k: f[k] for k in ("fixture_id", "initial_prefix_length", "points",
                                                       "no_progress_draw", "cost_attack", "cost_defend")}
                                   for f in fixtures]},
        )

    return score


@task
def contact_bench(panel: str = "c50_api_v1", secrets_per_opponent: int = 4, seed: int = 20261120,
                  opponents: str | None = None, rematches: bool = True) -> Task:
    """ContactBench (C=50, lookup tools) against a fixed reference panel.

    Args:
        panel: Panel name under contact_bench/inspect_task/panels, or a path to a panel JSON.
        secrets_per_opponent: Fixtures (fresh secrets) per panel opponent.
        seed: Secret-generation seed (secrets are drawn uniformly from the ENABLE support).
        opponents: Comma-separated subset of panel opponents (default: all).
        rematches: Replay no-progress draws with one more letter revealed, as in the arena.
    """
    pan = load_panel(panel)
    env = _Env.get(pan["condition_config"])
    p = env.cfg.protocol
    names = [o.strip() for o in opponents.split(",")] if opponents else list(pan["opponents"])
    unknown = [o for o in names if o not in pan["opponents"]]
    if unknown:
        raise ValueError(f"unknown panel opponents: {unknown}")
    tasks = generate_tasks(v_secret=env.v_secret, v_contact=env.v_contact,
                           count=secrets_per_opponent * len(names), seed=seed, split="inspect",
                           initial_prefix_length=p.initial_prefix_length, turn_limit=p.turn_limit,
                           clue_max_characters=p.clue_max_characters)
    samples = []
    for i, opp in enumerate(names):
        for j in range(secrets_per_opponent):
            t = tasks[i * secrets_per_opponent + j]
            samples.append(Sample(
                id=f"{opp}-{j:03d}",
                input=f"ContactBench fixture vs {opp} (secret {t.task_id})",
                metadata={"opponent": opp, "task_id": t.task_id, "secret": t.secret}))
    return Task(
        dataset=MemoryDataset(samples, name=f"contact-bench-{pan['name']}"),
        solver=contact_fixture(pan, pan["condition_config"], rematches),
        scorer=fixture_scorer(pan),
        metadata={"panel": pan["name"], "anchor_run_id": pan["anchor_run_id"],
                  "condition_config": pan["condition_config"], "seed": seed},
        version=1,
    )
