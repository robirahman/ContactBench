"""Resumable tournament runner, replay and scoring (spec Sections 9, 14)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .. import ENGINE_VERSION, PACKING_VERSION, PROTOCOL_VERSION, RNG_VERSION, SCHEMA_VERSION
from ..config import BenchConfig, ModelConfig
from ..engine.game import (
    OUTCOME_CAPPED,
    OUTCOME_INCOMPLETE,
    OUTCOME_SOLVED,
    DecisionSpec,
    EngineInvariantError,
    Game,
    Unavailable,
)
from ..lexicon import Lexicon, load_lexicon_manifest
from ..policies.llm import AgentOutput, ContextOverflowError, Limiters, LLMAgent
from ..policies.scripted import ScriptedAgent
from ..prompts.templates import PROMPT_VERSION, prompt_hash
from ..providers.base import AdapterConfigError, InfrastructureError, RetryPolicy, sanitize
from ..scoring.cost import GameScore, score_game
from ..scoring.reference import ReferenceScorer
from .budget import Budget, BudgetExhausted
from .schedule import Fixture, GameSpec, build_schedule, run_plan
from .store import RunStore, atomic_write_json
from .tasks import Task, generate_tasks, load_tasks, save_tasks


# Fatal categories that affect every model of a provider (shared credentials
# or billing); other fatal categories are scoped to the failing model.
PROVIDER_WIDE_FATAL = {"auth", "quota_exhausted"}


class RunHalted(RuntimeError):
    """Fatal infrastructure condition (auth, invalid model, exhausted quota...)."""


class LiveModeError(RuntimeError):
    pass


def obs_hash(obs: dict) -> str:
    return hashlib.sha256(json.dumps(obs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def code_revision(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
        rev = out.stdout.strip() or None
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return f"{rev}{'+dirty' if dirty else ''}" if rev else None
    except Exception:
        return None


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def load_lexicons(cfg: BenchConfig) -> tuple[Lexicon, Lexicon]:
    vs = load_lexicon_manifest(cfg.resolve(cfg.lexicon.manifest))
    if cfg.lexicon.contact_manifest and cfg.lexicon.contact_manifest != cfg.lexicon.manifest:
        vc = load_lexicon_manifest(cfg.resolve(cfg.lexicon.contact_manifest))
    else:
        vc = vs
    if not vs.word_set <= vc.word_set:
        raise ValueError("the capacity-matched reference requires V_secret to be a subset of V_contact")
    if vs.max_word_length > cfg.lexicon.maximum_secret_word_length:
        raise ValueError("secret lexicon has words longer than maximum_secret_word_length")
    return vs, vc


def make_scorer(cfg: BenchConfig) -> ReferenceScorer:
    return ReferenceScorer(
        cfg.protocol.clue_max_characters,
        rollouts=cfg.scoring.rollouts,
        root_seed=cfg.scoring.root_seed,
        exact_small_state_limit=cfg.scoring.exact_small_state_limit,
        cache_dir=cfg.resolve(cfg.scoring.cache_dir),
    )


def validate_config(cfg: BenchConfig, *, live: bool = False) -> dict:
    """Offline validation and preflight.  Returns a report; raises on errors."""
    vs, vc = load_lexicons(cfg)
    report: dict[str, Any] = {
        "protocol": cfg.protocol.version,
        "secret_lexicon": vs.manifest(),
        "contact_lexicon": vc.manifest() if vc is not vs else "identical",
        "models": {},
    }
    C = cfg.protocol.clue_max_characters
    report["clue_only_listing_covers_all_targets"] = vs.max_word_length <= C
    # Full explicit blocklist must be representable within output limits.
    k0 = cfg.protocol.initial_prefix_length
    groups_c: dict[str, list[str]] = {}
    for w in vc.words:
        groups_c.setdefault(w[:k0], []).append(w)
    # Largest serialized full blocklist over any initial contact set (the
    # largest legal blocklist that is not redundant).
    biggest_prefix = max(groups_c, key=lambda p: len(json.dumps(groups_c[p])))
    biggest = len(groups_c[biggest_prefix])
    blocklist_json = json.dumps({"action": "block", "words": groups_c[biggest_prefix]})
    est_tokens = len(blocklist_json) // 2 + 16  # conservative (~2 chars/token)
    if cfg.protocol.blocklist_encoding == "words_and_ranges":
        # Any legal blocklist can be written as at most one range per maximal
        # run; the full dictionary is a single range.
        est_tokens = 64
    report["largest_initial_contact_set"] = biggest
    report["full_blocklist_estimated_output_tokens"] = est_tokens
    # Worst-case initial observation size (largest prefix group).  Histories
    # grow during play; the agent re-checks every request and halts rather
    # than truncating.
    from ..policies.llm import estimate_tokens
    from ..prompts.templates import system_prompt, user_prompt

    k = cfg.protocol.initial_prefix_length
    groups: dict[str, list[str]] = {}
    for w in vs.words:
        if len(w) > k:
            groups.setdefault(w[:k], []).append(w)
    big_prefix = max(groups, key=lambda p: len(groups[p]))
    g0 = Game(game_id="preflight", secret=groups[big_prefix][0], v_secret=vs, v_contact=vc, protocol=cfg.protocol)
    obs = g0.observation("defender", "block", 1, current_clue="x" * C)
    initial_obs_tokens = estimate_tokens(system_prompt(clue_max_characters=C, turn_limit=cfg.protocol.turn_limit,
                                                       dictionary_access=cfg.protocol.dictionary_access,
                                                       block_ranges=cfg.protocol.blocklist_encoding == "words_and_ranges",
                                                       empty_prefix=cfg.protocol.initial_prefix_length == 0)) + \
        estimate_tokens(user_prompt(obs))
    report["largest_initial_observation_estimated_tokens"] = initial_obs_tokens
    from ..providers.registry import make_adapter

    for m in cfg.models:
        entry: dict[str, Any] = {"provider": m.provider}
        if m.provider in ("openai", "anthropic", "google", "fake"):
            if m.provider != "fake" and not live and m.unresolved_placeholders():
                entry["status"] = "placeholder (live runs will reject)"
                report["models"][m.id] = entry
                continue
            adapter = make_adapter(m)
            entry["capabilities"] = adapter.preflight(require_credentials=live and m.provider != "fake")
            if m.context_window_tokens is not None and \
                    initial_obs_tokens + (m.max_output_tokens or 0) > m.context_window_tokens:
                raise AdapterConfigError(
                    f"model {m.id}: initial observation (~{initial_obs_tokens} tokens) plus output allowance "
                    f"exceeds context window {m.context_window_tokens}; words are never silently omitted"
                )
            if m.max_output_tokens is not None and m.max_output_tokens < est_tokens:
                raise AdapterConfigError(
                    f"model {m.id}: max_output_tokens={m.max_output_tokens} cannot represent a full legal "
                    f"blocklist (~{est_tokens} tokens) for this lexicon"
                )
            entry["status"] = "ok"
        else:
            entry["status"] = "ok"
        report["models"][m.id] = entry
    return report


class Runner:
    def __init__(
        self,
        cfg: BenchConfig,
        run_dir: Path,
        *,
        live: bool = False,
        max_requests: int | None = None,
        max_usd: float | None = None,
        replay_only: bool = False,
        adapters: dict[str, Any] | None = None,
        progress: bool = False,
        max_usd_by_provider: dict[str, float] | None = None,
    ):
        self.cfg = cfg
        self.run_dir = Path(run_dir)
        self.run_id = self.run_dir.name
        self.store = RunStore(self.run_dir)
        self.live = live
        self.replay_only = replay_only
        self.progress = progress
        self.v_secret, self.v_contact = load_lexicons(cfg)
        self.scorer = make_scorer(cfg)
        from ..dictionary import DictionaryService

        self.secret_dictionary = DictionaryService(self.v_secret)
        self.contact_dictionary = (
            self.secret_dictionary if self.v_contact is self.v_secret else DictionaryService(self.v_contact)
        )
        self.budget = Budget(max_requests, max_usd if max_usd is not None else cfg.execution.max_usd,
                             max_usd_by_provider=dict(max_usd_by_provider or {}))
        self.limiters = Limiters(cfg.execution.global_concurrency, cfg.execution.per_provider_concurrency)
        self.models: dict[str, ModelConfig] = {m.id: m for m in cfg.models}
        self._adapters = adapters or {}
        self.halted: str | None = None
        # Fatal provider errors (billing, auth, invalid model) pause only the
        # games that need that provider; other games keep running.
        # Per-provider budget-cap pauses (caps are configured per provider).
        self.halted_providers: dict[str, str] = {}
        # Auth/billing failures pause every model that shares the failing
        # credential, keyed by "provider:credential_env".
        self.halted_credentials: dict[str, str] = {}
        # Model-specific configuration failures (invalid model id, unsupported
        # parameter, bad request) pause only that model's games.
        self.halted_models: dict[str, str] = {}
        self._fork_tasks: dict[str, list] = {}
        self.budget_stopped = False

        paid = [m.id for m in cfg.models if m.provider in ("openai", "anthropic", "google")]
        if paid and not live and not replay_only:
            raise LiveModeError(
                f"models {paid} need paid provider calls; offline runs accept only scripted/fake models. "
                "Use --live with an explicit --max-requests budget."
            )
        if live and not replay_only:
            if not (max_requests or max_usd or cfg.execution.max_usd or max_usd_by_provider):
                raise LiveModeError("live mode requires a request-count or monetary stopping budget")

    # ---------------------------------------------------------------- setup
    def prepare(self) -> None:
        """Create the run manifest, task manifest and plan if absent."""
        if (self.run_dir / "run.json").exists():
            self._load_existing()
            return
        cfg = self.cfg
        if cfg.tasks.manifest:
            tasks = load_tasks(cfg.resolve(cfg.tasks.manifest))
        else:
            tasks = generate_tasks(
                v_secret=self.v_secret,
                v_contact=self.v_contact,
                count=cfg.tasks.tasks_per_pair,
                seed=cfg.tasks.generation_seed,
                split=cfg.tasks.split,
                initial_prefix_length=cfg.protocol.initial_prefix_length,
                turn_limit=cfg.protocol.turn_limit,
                clue_max_characters=cfg.protocol.clue_max_characters,
            )
        expected = {
            "secret_lexicon_sha256": self.v_secret.sha256,
            "contact_lexicon_sha256": self.v_contact.sha256,
            "initial_prefix_length": cfg.protocol.initial_prefix_length,
            "turn_limit": cfg.protocol.turn_limit,
            "clue_max_characters": cfg.protocol.clue_max_characters,
            "split": cfg.tasks.split,
            "sampling": cfg.tasks.sampling,
        }
        for t in tasks:
            bad = {k: (getattr(t, k), v) for k, v in expected.items() if getattr(t, k) != v}
            if bad:
                raise ValueError(f"task {t.task_id} provenance does not match this configuration: {bad}")
            if t.secret not in self.v_secret or len(t.secret) <= cfg.protocol.initial_prefix_length:
                raise ValueError(f"task {t.task_id} has an inadmissible secret for this configuration")
        save_tasks(self.run_dir / "private" / "tasks_private.jsonl", tasks)
        fixtures, games = build_schedule(cfg, tasks)
        root = Path(__file__).resolve().parents[2]
        manifest = {
            "run_id": self.run_id,
            "schema_version": SCHEMA_VERSION,
            "protocol_version": cfg.protocol.version,
            "engine_version": ENGINE_VERSION,
            "packing_version": PACKING_VERSION,
            "rng_version": RNG_VERSION,
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": prompt_hash(),
            "code_revision": code_revision(root),
            "dependency_lock_sha256": file_sha256(root / "requirements.lock"),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config": cfg.model_dump(mode="json", exclude={"base_dir"}),
            "secret_lexicon": self.v_secret.manifest(),
            "contact_lexicon": self.v_contact.manifest(),
            "target_distribution": "uniform over V_secret words longer than the initial prefix",
            "live": self.live,
            "fixture_data": cfg.fixture_data,
        }
        self.store.write_json("run.json", manifest)
        self.store.write_json("schedule.json", {
            "fixtures": [asdict(f) for f in fixtures],
            "games": [asdict(g) for g in games],
        })
        self.store.write_json("plan.json", run_plan(cfg, tasks, games))
        self.store.append_event({"type": "run_created", "run_id": self.run_id})
        self._load_existing()

    def _load_existing(self) -> None:
        sched = self.store.read_json("schedule.json")
        self.fixtures = [Fixture(**f) for f in sched["fixtures"]]
        self.games = [GameSpec(**g) for g in sched["games"]]
        self.tasks = {t.task_id: t for t in load_tasks(self.run_dir / "private" / "tasks_private.jsonl")}
        manifest = self.store.read_json("run.json")
        # Re-validate the snapshot so fields added by later code versions take
        # their (behaviour-preserving) defaults before comparison.
        from ..config import snapshot_with_legacy_defaults

        has_rm = any(f.rematch_of for f in self.fixtures)
        snap = BenchConfig.model_validate({**snapshot_with_legacy_defaults(manifest["config"], has_rm),
                                           "base_dir": self.cfg.base_dir}).model_dump(
            mode="json", exclude={"base_dir"})
        current = self.cfg.model_dump(mode="json", exclude={"base_dir"})
        # Never silently replace a model, prompt, cap or provider setting mid-run.
        for key in ("protocol", "lexicon", "scoring", "tournament", "models", "forecasts"):
            if snap.get(key) != current.get(key):
                if key == "scoring" and self.replay_only:
                    continue
                raise ValueError(f"configuration section '{key}' differs from the run's frozen snapshot")
        if manifest.get("prompt_hash") != prompt_hash() and not self.replay_only:
            raise ValueError("prompt templates changed since this run was created")

    # --------------------------------------------------------------- agents
    def _adapter(self, m: ModelConfig):
        if m.id not in self._adapters:
            from ..providers.registry import make_adapter

            ex = self.cfg.execution
            self._adapters[m.id] = make_adapter(
                m,
                retry=RetryPolicy(
                    max_attempts=ex.max_transport_attempts,
                    base_seconds=ex.backoff_base_seconds,
                    max_seconds=ex.backoff_max_seconds,
                    deadline_seconds=ex.request_deadline_seconds,
                ),
            )
            self._adapters[m.id].preflight(require_credentials=self.live and m.provider != "fake")
        return self._adapters[m.id]

    def _agent(self, m: ModelConfig, seat: str, g: GameSpec):
        if m.provider == "scripted":
            return ScriptedAgent(
                seat=seat,
                offense_policy=m.policy or "first_last_two_guess",
                defender_policy=m.defender_policy or "empty",
                choice_policy=m.choice_policy or "always_reveal",
                policy_seed=g.policy_seed,
                secret_dictionary=self.secret_dictionary,
                contact_dictionary=self.contact_dictionary,
            )
        return LLMAgent(
            model=m,
            adapter=self._adapter(m),
            seat=seat,
            clue_max_characters=self.cfg.protocol.clue_max_characters,
            turn_limit=self.cfg.protocol.turn_limit,
            limiters=self.limiters,
            budget=self.budget,
            sparse_max_entries=self.cfg.forecasts.sparse_max_entries,
            dictionary_access=self.cfg.protocol.dictionary_access,
            dictionary_service=self.contact_dictionary,
            max_tool_calls=self.cfg.protocol.max_tool_calls_per_decision,
            block_ranges=self.cfg.protocol.blocklist_encoding == "words_and_ranges",
            empty_prefix=self.cfg.protocol.initial_prefix_length == 0,
            keep_conversation=self.cfg.forecasts.mode == "fork",
        )

    # ----------------------------------------------------------------- game
    def new_game(self, g: GameSpec) -> Game:
        t = self.tasks[g.task_id]
        atk = self.models[g.attacker]
        protocol = self.cfg.protocol
        if g.initial_prefix_length is not None:
            protocol = protocol.model_copy(update={"initial_prefix_length": g.initial_prefix_length})
        return Game(
            game_id=g.game_id,
            secret=t.secret,
            v_secret=self.v_secret,
            v_contact=self.v_contact,
            protocol=protocol,
            offense_condition=atk.offense_mode if atk.provider != "scripted" else "full",
            joint_live=self.cfg.forecasts.mode == "joint_live",
        )

    def _schedule_fork(self, g: GameSpec, game: Game, spec: DecisionSpec, did: str, agent: Any,
                       out: AgentOutput, raw: Any) -> None:
        """Branch the deciding seat's transcript for a private forecast query.

        Runs concurrently; its result goes only to forecasts.jsonl and is never
        part of any observation, public history or gameplay state."""
        from ..engine import actions as A
        from ..forecasts.forks import fork_prompt, support_descriptor

        if out.conversation is None or spec.phase not in ("act", "respond", "block"):
            return
        prefix = game.prefix
        contact = game.contact_candidates()
        k = self.cfg.forecasts.sparse_max_entries
        if spec.phase == "act":
            adm = A.admit_guesser1(raw, pre_secret=frozenset(game.secret_candidates()),
                                   pre_contact=frozenset(contact), max_chars=game.clue_max,
                                   clue_allowed=game.offense_condition != "direct_only")
            if not adm.valid or adm.canonical["action"] != "clue":
                return
            kind, clue, w1 = "guesser1", adm.canonical["clue"], adm.canonical["word"]
            prompt = fork_prompt(kind, prefix=prefix, clue=clue, w1=w1, k=k, pass_label=True)
        else:
            kind, clue, w1 = "intended_word", spec.observation.get("current_clue", ""), None
            prompt = fork_prompt(kind, prefix=prefix, clue=clue, k=k)
        support = support_descriptor(prefix, game._used_view(), len(contact))
        fork_id = f"{did}/fork"
        base = {"fork_id": fork_id, "game_id": g.game_id, "turn": spec.turn, "seat": spec.seat,
                "phase": spec.phase, "kind": kind, "model_id": out.model_id, "support": support,
                "context": {"clue": clue, **({"w1": w1} if w1 else {})},
                "prompt_version": "forecast-fork-v1"}

        # Persist a "scheduled" marker synchronously, before the gameplay
        # decision itself is recorded, so a crash can never make a scheduled
        # fork vanish from the calibration denominator.  If no final record
        # follows, the fork is reported as unavailable ("interrupted").
        self.store.append_forecast({**base, "status": "scheduled"})

        async def run():
            try:
                fo = await agent.fork(spec, fork_id, out.conversation, kind=kind, prompt=prompt)
                rec = {**base, "status": "ok", "raw_output": fo.raw, "response": fo.response,
                       "cost_estimate": fo.cost_estimate}
            except BudgetExhausted as e:
                self._on_budget_exhausted(e, fork_id)
                rec = {**base, "status": "unavailable", "error": "budget",
                       "requests_sent": getattr(e, "fork_requests_sent", 0),
                       "cost_estimate": getattr(e, "fork_cost", None)}
            except InfrastructureError as e:
                rec = {**base, "status": "unavailable", "error": f"{e.category}: {sanitize(str(e))}",
                       "attempts": [asdict(a) for a in getattr(e, "attempts", []) or []],
                       "requests_sent": getattr(e, "fork_requests_sent", len(getattr(e, "attempts", []) or [])),
                       "cost_estimate": getattr(e, "fork_cost", None)}
            except ContextOverflowError as e:
                # Rejected before sending: no provider call was made.
                rec = {**base, "status": "unavailable", "error": f"context_overflow: {e}", "requests_sent": 0}
            self.store.append_forecast(rec)

        self._fork_tasks.setdefault(g.game_id, []).append(asyncio.ensure_future(run()))

    def _decide_fn(self, g: GameSpec, game: Game):
        decisions = self.store.decisions()
        agents: dict[str, Any] = {}

        def agent_for(seat: str):
            if seat not in agents:
                mid = g.defender if seat == "defender" else g.attacker
                agents[seat] = self._agent(self.models[mid], seat, g)
            return agents[seat]

        async def decide(spec: DecisionSpec):
            did = f"{self.run_id}/{spec.key}"
            oh = obs_hash(spec.observation)
            rec = decisions.get(did)
            if rec is not None:
                if rec.get("observation_sha256") != oh:
                    raise EngineInvariantError(f"replay divergence at {did}: observation hash mismatch")
                return rec["raw_output"]
            seat_model = g.defender if spec.seat == "defender" else g.attacker
            if self.replay_only or self.halted or self.budget_stopped:
                return Unavailable("not_recorded")
            if self._credential_key(seat_model) in self.halted_credentials:
                return Unavailable("credential_halted")
            if self.models[seat_model].provider in self.halted_providers:
                return Unavailable("provider_halted")
            if seat_model in self.halted_models:
                return Unavailable("model_halted")
            agent = agent_for(spec.seat)
            meta: dict | None = None
            try:
                if isinstance(agent, ScriptedAgent):
                    raw = await agent.decide(spec)
                else:
                    out: AgentOutput = await agent.decide(spec, did)
                    raw, meta = out.raw, out.response
                    if self.cfg.forecasts.mode == "fork":
                        self._schedule_fork(g, game, spec, did, agent, out, raw)
                    self.store.append_request({
                        "decision_id": did, "game_id": g.game_id, "turn": spec.turn, "seat": spec.seat,
                        "phase": spec.phase, "model_id": seat_model, "status": "ok",
                        "observation_sha256": oh, "schema_name": spec.schema_name,
                        "estimated_input_tokens": out.estimated_input_tokens,
                        "cost_estimate": out.cost_estimate, "response": meta,
                    })
            except BudgetExhausted as e:
                self._on_budget_exhausted(e, did)
                return Unavailable("budget")
            except InfrastructureError as e:
                self.store.append_request({
                    "decision_id": did, "game_id": g.game_id, "turn": spec.turn, "seat": spec.seat,
                    "phase": spec.phase, "model_id": seat_model, "status": "error",
                    "error_category": e.category, "error": sanitize(str(e)),
                    "attempts": [asdict(a) for a in getattr(e, "attempts", [])],
                })
                if e.fatal:
                    reason = f"{e.category}: {sanitize(str(e))}"
                    if e.category in PROVIDER_WIDE_FATAL:
                        cred = self._credential_key(seat_model)
                        self.halted_credentials.setdefault(cred, reason)
                        self.store.append_event({"type": "credential_halted", "credential": cred,
                                                 "provider": self.models[seat_model].provider, "reason": reason})
                    else:
                        self.halted_models.setdefault(seat_model, reason)
                        self.store.append_event({"type": "model_halted", "model_id": seat_model, "reason": reason})
                return Unavailable(e.category)
            except ContextOverflowError as e:
                self.halted = str(e)
                return Unavailable("context_overflow")
            self.store.record_decision({
                "decision_id": did,
                "run_id": self.run_id,
                "game_id": g.game_id,
                "turn": spec.turn,
                "seat": spec.seat,
                "phase": spec.phase,
                "model_id": seat_model,
                "observation_sha256": oh,
                "schema_name": spec.schema_name,
                "raw_output": raw,
            })
            return raw

        return decide

    def game_record(self, g: GameSpec, game: Game, score: GameScore | None) -> dict:
        t = self.tasks[g.task_id]
        return {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": self.cfg.protocol.version,
            "game": asdict(g),
            "task": asdict(t),
            "summary": game.summary(),
            "initial_secret_candidates": list(game.initial_secret_candidates),
            "final_secret_candidates": game.secret_candidates(),
            "public_history": game.public_history,
            "private_histories": game.private_history,
            "referee_audit": game.audit,
            "prefix_events": game.prefix_events,
            "diagnostics": game.diagnostics,
            "used_words": sorted(game.used_words),
            "score": score.to_json() if score else None,
        }

    def score(self, game: Game) -> GameScore:
        return score_game(
            outcome_status=game.outcome_status,
            winning_turn=game.winning_turn,
            turn_limit=game.turn_limit,
            secret=game.secret,
            initial_candidates=game.initial_secret_candidates,
            final_candidates=game.secret_candidates() if game.outcome_status == OUTCOME_CAPPED else None,
            scorer=self.scorer,
        )

    async def play(self, g: GameSpec) -> dict:
        game = self.new_game(g)
        try:
            await game.play(self._decide_fn(g, game))
        finally:
            tasks = self._fork_tasks.pop(g.game_id, [])
            if tasks:
                await asyncio.gather(*tasks)
        status = "complete" if game.terminal else "pending"
        sc = self.score(game) if game.outcome_status in (OUTCOME_SOLVED, OUTCOME_CAPPED) else None
        rec = self.game_record(g, game, sc)
        if self.cfg.forecasts.mode == "fork":
            from ..forecasts.forks import label_game_forks

            fc = self.cfg.forecasts
            rec["forecasts"] = label_game_forks(
                self.store.forecasts(g.game_id), game.audit, self.v_contact,
                max_entries=fc.sparse_max_entries, tolerance=fc.mass_tolerance,
                invalid_score=fc.invalid_audit_score)
        rec["run_status"] = status
        if not self.replay_only:
            self.store.write_game(g.game_id, rec)
            self.store.update_game({
                "game_id": g.game_id, "fixture_id": g.fixture_id, "task_id": g.task_id,
                "attacker": g.attacker, "defender": g.defender, "status": status,
                "outcome_status": game.outcome_status, "collection_status": game.collection_status,
                "cost_num": sc.cost.numerator if sc and sc.cost is not None else None,
                "cost_den": sc.cost.denominator if sc and sc.cost is not None else None,
            })
            self.store.append_event({
                "type": "game_finished" if status == "complete" else "game_pending",
                "game_id": g.game_id, "outcome_status": game.outcome_status,
                "collection_status": game.collection_status, "pending": game.pending,
            })
        return rec

    async def run(self) -> dict:
        self.prepare()
        done = {r["game_id"] for r in self.store.game_rows() if r["status"] == "complete"
                and r["collection_status"] == "complete"}
        todo = [g for g in self.games if g.game_id not in done]
        sem = asyncio.Semaphore(self.cfg.execution.game_concurrency)
        results: list[dict] = []

        async def one(g: GameSpec):
            def blocked() -> bool:
                provs = {self.models[g.attacker].provider, self.models[g.defender].provider}
                creds = {self._credential_key(g.attacker), self._credential_key(g.defender)}
                return bool(self.halted or self.budget_stopped or provs & set(self.halted_providers)
                            or creds & set(self.halted_credentials)
                            or {g.attacker, g.defender} & set(self.halted_models))

            if blocked():
                return
            async with sem:
                if blocked():
                    return
                rec = await self.play(g)
                results.append(rec)
                if self.progress:
                    s = rec["summary"]
                    print(f"  {g.game_id}: {s['outcome_status']} turns={s['turns_used']}"
                          + (f" cost={rec['score']['cost']:.3f}" if rec.get("score") and rec["score"]["cost"] is not None else ""))

        await asyncio.gather(*(one(g) for g in todo))
        if self.cfg.tournament.rematch_on_no_progress_draw and not (self.halted or self.budget_stopped):
            self.schedule_rematches()
            finished = {r["game_id"] for r in self.store.game_rows()
                        if r["status"] == "complete" and r["collection_status"] == "complete"}
            pending_rm = [g for g in self.games if g.rematch_of and g.game_id not in finished]
            await asyncio.gather(*(one(g) for g in pending_rm))
        status = self.status()
        status["budget"] = self.budget.snapshot()
        status["halted"] = self.halted
        status["halted_providers"] = dict(self.halted_providers)
        status["halted_credentials"] = dict(self.halted_credentials)
        status["halted_models"] = dict(self.halted_models)
        # Fatal provider/model failures are failures of the command even though
        # unaffected games kept running (budget pauses are not failures).
        status["fatal_failures"] = sorted(
            [f"credential:{c}" for c in self.halted_credentials]
            + [f"model:{m}" for m in self.halted_models])
        status["budget_stopped"] = self.budget_stopped
        status["duplicate_decisions_ignored"] = len(self.store.duplicate_decisions)
        status["reference_scorer_stats"] = dict(self.scorer.stats)
        self.store.write_json("status.json", status)
        return status

    DEFAULT_CREDENTIAL_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                              "google": "GEMINI_API_KEY"}

    def _credential_key(self, model_id: str) -> str:
        m = self.models[model_id]
        if m.provider in ("scripted", "fake"):
            return f"{m.provider}:{m.id}"
        return f"{m.provider}:{m.credential_env or self.DEFAULT_CREDENTIAL_ENV.get(m.provider, '')}"

    def _on_budget_exhausted(self, e: BudgetExhausted, decision_id: str) -> None:
        """A per-key cap pauses only that provider's games; a global cap stops scheduling."""
        if e.provider:
            self.halted_providers.setdefault(e.provider, f"budget: {e}")
            self.store.append_event({"type": "provider_budget_stop", "provider": e.provider,
                                     "reason": str(e), "decision_id": decision_id})
        else:
            self.budget_stopped = True
            self.store.append_event({"type": "budget_stop", "reason": str(e), "decision_id": decision_id})

    def schedule_rematches(self) -> list[Fixture]:
        """Append one rematch fixture per completed no-progress draw (idempotent).

        A rematch starts from the same secret with rematch_extra_letters more
        letters revealed.  Rematch fixtures never trigger further rematches.
        The schedule file is extended append-only and logged as an event.
        """
        from .schedule import is_no_progress_capped, rematch_fixture

        existing = {f.rematch_of for f in self.fixtures if f.rematch_of}
        added: list[Fixture] = []
        for f in list(self.fixtures):
            if f.rematch_of or f.fixture_id in existing:
                continue
            ab, ba = self.store.read_game(f.game_ab), self.store.read_game(f.game_ba)
            if not ab or not ba or ab.get("run_status") != "complete" or ba.get("run_status") != "complete":
                continue
            if not (is_no_progress_capped(ab["summary"]) and is_no_progress_capped(ba["summary"])):
                continue
            base = f.initial_prefix_length if f.initial_prefix_length is not None else self.cfg.protocol.initial_prefix_length
            plen = base + self.cfg.tournament.rematch_extra_letters
            if len(self.tasks[f.task_id].secret) <= plen:
                continue
            fx, games = rematch_fixture(f, plen)
            taken = {g.game_id for g in self.games}
            if any(g.game_id in taken for g in games):
                raise EngineInvariantError(f"rematch game id collision for fixture {f.fixture_id}")
            self.fixtures.append(fx)
            self.games.extend(games)
            added.append(fx)
        if added:
            self.store.write_json("schedule.json", {
                "fixtures": [asdict(x) for x in self.fixtures],
                "games": [asdict(x) for x in self.games],
            })
            self.store.append_event({"type": "rematches_scheduled",
                                     "fixtures": [x.fixture_id for x in added]})
        return added

    def status(self) -> dict:
        rows = {r["game_id"]: r for r in self.store.game_rows()}
        planned = len(self.games)
        complete = sum(1 for g in self.games if rows.get(g.game_id, {}).get("status") == "complete")
        incomplete_collection = sum(
            1 for g in self.games
            if rows.get(g.game_id, {}).get("status") == "complete"
            and rows[g.game_id].get("collection_status") == "incomplete"
        )
        return {
            "run_id": self.run_id,
            "planned_games": planned,
            "complete_games": complete,
            "complete_with_incomplete_collection": incomplete_collection,
            "pending_games": planned - complete,
        }

    async def replay(self) -> dict:
        """Regenerate every game from recorded decisions without providers."""
        self.prepare()
        mismatches = []
        recomputed = []
        for g in sorted(self.games, key=lambda x: x.game_id):
            rec = await self.play(g)
            recomputed.append(rec)
            stored = self.store.read_game(g.game_id)
            if stored is None:
                continue
            for key in ("summary", "public_history", "referee_audit", "private_histories", "score"):
                if json.loads(json.dumps(stored.get(key), default=str)) != json.loads(json.dumps(rec.get(key), default=str)):
                    mismatches.append({"game_id": g.game_id, "field": key})
        report = {
            "run_id": self.run_id,
            "games_replayed": len(recomputed),
            "complete": sum(1 for r in recomputed if r["run_status"] == "complete"),
            "mismatches": mismatches,
            "equivalent": not mismatches,
        }
        atomic_write_json(self.run_dir / "replay_report.json", report)
        return report


def load_game_records(run_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((Path(run_dir) / "games").glob("*.json"))]
