"""Typed configuration (spec Sections 3.2 and 15).

Every result-affecting choice is explicit.  Unsupported settings are rejected
rather than approximated by a different game.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import PROTOCOL_VERSION


class ConfigError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProtocolConfig(_Strict):
    version: Literal["contact-v0.4", "contact-v0.5"] = PROTOCOL_VERSION  # type: ignore[assignment]
    # v0.5: how players learn the dictionary.
    #   full_candidate_lists — v0.4 behaviour: complete pre-turn candidate lists in every observation
    #   closed_book          — players are told only the dictionary's identity
    #   lookup_tools         — every player may call the same deterministic lookup functions
    dictionary_access: Literal["full_candidate_lists", "closed_book", "lookup_tools"] = "full_candidate_lists"
    max_tool_calls_per_decision: int = Field(20, ge=1, le=200)
    # v0.5: "words_and_ranges" adds a dictionary-ID block encoding (alphabetical
    # ranges between two dictionary words) with identical decoded effects, so
    # a full legal blocklist stays representable for very large dictionaries.
    blocklist_encoding: Literal["words", "words_and_ranges"] = "words"
    clue_track: Literal["mechanical"] = "mechanical"
    role_policy: Literal["fixed_guesser_roles"] = "fixed_guesser_roles"
    timing: Literal["sealed_initial_responses_then_conditional_reveal"] = (
        "sealed_initial_responses_then_conditional_reveal"
    )
    initial_response_collection: Literal[
        "complete_even_on_public_clue_hit", "early_stop_on_public_clue_hit"
    ] = "complete_even_on_public_clue_hit"
    initial_prefix_length: int = Field(1, ge=0)
    turn_limit: int = Field(20, ge=1)
    clue_max_characters: int = Field(100, ge=1)
    clue_max_live_candidate_mentions: None = None
    defender_block_cardinality_limit: None = None
    retirement_policy: Literal["public_utterances_and_dictionary_prefixes"] = (
        "public_utterances_and_dictionary_prefixes"
    )
    target_hit_scope: Literal["public_emissions"] = "public_emissions"
    contact_word_absent_from_current_clue: Literal[True] = True
    reveal_policy: Literal["conditional_on_block_membership"] = "conditional_on_block_membership"
    exactly_one_blocked: Literal["unblocked_seat_reveal_or_cancel"] = (
        "unblocked_seat_reveal_or_cancel"
    )
    neither_blocked: Literal["open_both"] = "open_both"
    both_blocked: Literal["open_neither"] = "open_neither"
    receiver_pass: Literal["open_guesser1_if_unblocked"] = "open_guesser1_if_unblocked"
    invalid_reveal_choice: Literal["cancel"] = "cancel"
    publish_hidden_branch_flags: Literal[False] = False
    ending_policy: Literal["final_letter_contact_wins"] = "final_letter_contact_wins"
    displayed_dictionary_prefix_is_used: Literal[True] = True
    singleton_auto_win: Literal[False] = False
    responder_visibility: Literal["sealed"] = "sealed"
    blocklist_disclosure: Literal["full"] = "full"
    tools_enabled: Literal[False] = False

    @model_validator(mode="after")
    def _version_features(self):
        if self.version == "contact-v0.4" and (
            self.dictionary_access != "full_candidate_lists" or self.blocklist_encoding != "words"
        ):
            raise ValueError("dictionary_access / blocklist_encoding extensions require protocol contact-v0.5")
        return self

    def condition_key(self) -> dict:
        """Fields that define a non-poolable leaderboard condition."""
        return self.model_dump()


class LexiconConfig(_Strict):
    manifest: str
    contact_manifest: str | None = None  # None => identical to secret lexicon
    secret_equals_contact: bool = True
    maximum_secret_word_length: int = 20

    @model_validator(mode="after")
    def _check(self):
        if self.secret_equals_contact and self.contact_manifest not in (None, self.manifest):
            raise ValueError("secret_equals_contact=true but a different contact_manifest is given")
        return self


class ScoringConfig(_Strict):
    resolver: Literal["fresh_shuffle_character_packing"] = "fresh_shuffle_character_packing"
    resolver_information: Literal["public_candidate_set_only"] = "public_candidate_set_only"
    evaluator_label: Literal["actual_target_length"] = "actual_target_length"
    resolver_defense: Literal["empty_blocklist"] = "empty_blocklist"
    resolver_conditional_choice: Literal["always_reveal"] = "always_reveal"
    reserve_guess_slots: Literal["two_longest_words"] = "two_longest_words"
    batch_selection: Literal["maximal_feasible_random_prefix"] = "maximal_feasible_random_prefix"
    numerical_method: Literal["exact_shortcuts_else_length_class_mc"] = (
        "exact_shortcuts_else_length_class_mc"
    )
    development_rollouts: int = Field(2048, ge=2)
    proposed_final_rollouts: int = Field(4096, ge=2)
    use_final_rollouts: bool = False
    average_all_words_of_target_length: Literal[True] = True
    # Exact oracle limit: maximum total candidates for the exact rational oracle.
    exact_small_state_limit: int = Field(12, ge=0, le=40)
    seed_source: Literal["referee_private_independent_of_target"] = (
        "referee_private_independent_of_target"
    )
    root_seed: int = 20261116
    cache_key: Literal["histogram_budget_policy_rng_seed_count"] = (
        "histogram_budget_policy_rng_seed_count"
    )
    cache_dir: str = ".cache/reference"
    report_numerical_standard_error: Literal[True] = True
    arithmetic_for_recorded_means: Literal["rational"] = "rational"

    @property
    def rollouts(self) -> int:
        return self.proposed_final_rollouts if self.use_final_rollouts else self.development_rollouts


class TasksConfig(_Strict):
    manifest: str | None = None  # existing manifest file; else generated
    split: Literal["development", "evaluation"] = "development"
    sampling: Literal["uniform_secret"] = "uniform_secret"
    tasks_per_pair: int = Field(4, ge=1)
    generation_seed: int = 1


class TournamentConfig(_Strict):
    schedule: Literal["balanced_round_robin", "self_play", "round_robin_plus_self_play"] = (
        "balanced_round_robin"
    )
    same_secret_both_legs: Literal[True] = True
    homogeneous_attackers: Literal[True] = True
    repetitions: int = Field(1, ge=1)
    order_seed: int = 7
    # A fixture where both legs hit the cap and neither attacker earned a
    # letter beyond the starting prefix is scored as a draw for the rating
    # (the fallback-cost difference between such legs carries no signal).
    no_progress_draws: bool = True
    # Each such draw schedules one rematch fixture on the same secret with
    # extra letters of the secret revealed at the start.  The draw stands; the
    # rematch is an additional result.  Rematches never trigger rematches.
    rematch_on_no_progress_draw: bool = True
    rematch_extra_letters: int = Field(1, ge=1)


class ForecastConfig(_Strict):
    mode: Literal["off", "shadow_audit", "joint_live", "fork"] = "off"
    # fork: after each LLM gameplay decision, branch that seat's transcript and
    # privately elicit forecasts (see contact_bench/forecasts/forks.py).
    sparse_max_entries: int = Field(20, ge=1)
    tail_policy: Literal["uniform_over_unlisted"] = "uniform_over_unlisted"
    primary_score: Literal["higher_is_better_brier"] = "higher_is_better_brier"
    invalid_audit_score: float = -1.0
    mass_tolerance: float = 1e-6

    @field_validator("mode", mode="before")
    @classmethod
    def _yaml_off(cls, v):
        # YAML 1.1 parses a bare `off` as boolean false.
        return "off" if v is False else v


SCRIPTED_POLICIES = {
    # offense policies (guesser seats)
    "first_last_two_guess",
    "alphabetical_direct",
    "reverse_direct",
    "clue_only_alphabetical",
    "clue_only_reverse",
    "clue_only_shuffled",
    "combined_alphabetical",
    "combined_reverse",
    "combined_fixed_shuffle",
    "combined_fresh_shuffle",
    "wasted_turns",
    "public_index_ambiguity",
}
SCRIPTED_DEFENDERS = {
    "empty",
    "literal_clue_words",
    "random_1",
    "random_3",
    "random_10",
    "all_nonsecret",
    "index_decoder",
}
SCRIPTED_CHOICES = {"always_reveal", "always_cancel"}

PLACEHOLDER_RE = re.compile(r"REPLACE_WITH|<[A-Z_]+>|TODO", re.IGNORECASE)


class PriceTable(_Strict):
    currency: str = "USD"
    as_of: str
    source: str = ""
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None
    reasoning_billed_as_output: bool = True


class ModelConfig(_Strict):
    id: str
    provider: Literal["scripted", "fake", "openai", "anthropic", "google"]
    # scripted
    policy: str | None = None
    defender_policy: str | None = None
    choice_policy: str | None = None
    # offense condition for LLM models: full game, direct-only or no-contact batching
    offense_mode: Literal["full", "direct_only", "no_contact_batching"] = "full"
    # llm
    api_family: str | None = None
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    credential_env: str | None = None
    max_output_tokens: int | None = None
    context_window_tokens: int | None = None
    prompt_version: str = "prompts-v1"
    prices: PriceTable | None = None
    # fake adapter fixture behavior
    fake_behavior: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9_.\-]+$", v):
            raise ValueError("model id must match [A-Za-z0-9_.-]+")
        return v

    @model_validator(mode="after")
    def _check(self):
        if self.provider == "scripted":
            pol = self.policy or "first_last_two_guess"
            if pol not in SCRIPTED_POLICIES:
                raise ValueError(f"unknown scripted policy {pol!r}")
            if (self.defender_policy or "empty") not in SCRIPTED_DEFENDERS:
                raise ValueError(f"unknown scripted defender policy {self.defender_policy!r}")
            if (self.choice_policy or "always_reveal") not in SCRIPTED_CHOICES:
                raise ValueError(f"unknown scripted choice policy {self.choice_policy!r}")
        elif self.provider == "fake":
            pass
        else:
            expected = {"openai": "responses", "anthropic": "messages", "google": "interactions"}
            fam = self.api_family or expected[self.provider]
            allowed = {
                "openai": {"responses"},
                "anthropic": {"messages"},
                "google": {"interactions", "generate_content"},
            }[self.provider]
            if fam not in allowed:
                raise ValueError(f"unsupported api_family {fam!r} for {self.provider}")
        return self

    @property
    def is_llm(self) -> bool:
        return self.provider in ("openai", "anthropic", "google", "fake")

    @property
    def effective_api_family(self) -> str | None:
        if self.provider in ("scripted",):
            return None
        if self.provider == "fake":
            return "fake"
        return self.api_family or {
            "openai": "responses",
            "anthropic": "messages",
            "google": "interactions",
        }[self.provider]

    def unresolved_placeholders(self) -> list[str]:
        bad = []
        for k in ("model", "credential_env"):
            v = getattr(self, k)
            if isinstance(v, str) and PLACEHOLDER_RE.search(v):
                bad.append(k)
        return bad


class ExecutionConfig(_Strict):
    live: bool = False
    max_requests: int = Field(0, ge=0)
    max_usd: float | None = None
    global_concurrency: int = Field(4, ge=1)
    per_provider_concurrency: int = Field(2, ge=1)
    max_transport_attempts: int = Field(3, ge=1, le=10)
    request_deadline_seconds: float = 300.0
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 60.0
    game_concurrency: int = Field(8, ge=1)


class AnalysisConfig(_Strict):
    bootstrap_resamples: int = Field(2000, ge=0)
    development_bootstrap_resamples: int = Field(200, ge=0)
    use_development_bootstrap: bool = True
    bootstrap_seed: int = 12345
    rating_method: Literal["batch_logistic_half_draw"] = "batch_logistic_half_draw"
    logit_penalty_scale: float = Field(2.5, gt=0)
    elo_center: float = 1500.0

    @property
    def resamples(self) -> int:
        return (
            self.development_bootstrap_resamples
            if self.use_development_bootstrap
            else self.bootstrap_resamples
        )


class BenchConfig(_Strict):
    name: str = "contactbench"
    fixture_data: bool = True  # marks synthetic/demo data on the website
    protocol: ProtocolConfig = ProtocolConfig()
    lexicon: LexiconConfig
    scoring: ScoringConfig = ScoringConfig()
    tasks: TasksConfig = TasksConfig()
    tournament: TournamentConfig = TournamentConfig()
    forecasts: ForecastConfig = ForecastConfig()
    models: list[ModelConfig]
    execution: ExecutionConfig = ExecutionConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    # directory against which relative paths resolve (not part of the file)
    base_dir: str = "."

    @model_validator(mode="after")
    def _check(self):
        ids = [m.id for m in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError("model ids must be unique")
        if self.tournament.schedule != "self_play" and len(self.models) < 2:
            raise ValueError("a round robin needs at least two models")
        return self

    def resolve(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else Path(self.base_dir) / path


def snapshot_with_legacy_defaults(config: dict, schedule_has_rematches: bool = False) -> dict:
    """Frozen run snapshots written before a setting existed must describe the
    games actually collected.  Rematches add games, so a run whose snapshot
    predates ``rematch_on_no_progress_draw`` had them disabled.  (The draw
    rule only changes scoring and keeps its current default.)"""
    data = dict(config)
    tour = dict(data.get("tournament") or {})
    tour.setdefault("rematch_on_no_progress_draw", bool(schedule_has_rematches))
    data["tournament"] = tour
    return data


def load_config(path: str | Path) -> BenchConfig:
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: configuration must be a mapping")
    parent = path.resolve().parent
    # Paths in configs/*.yaml are written relative to the repository root.
    data.setdefault("base_dir", str(parent.parent if parent.name == "configs" else parent))
    try:
        return BenchConfig.model_validate(data)
    except Exception as e:  # pydantic ValidationError
        raise ConfigError(f"{path}: {e}") from e
