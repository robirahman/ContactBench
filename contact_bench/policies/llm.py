"""LLM-backed seat agent: observation -> prompt -> adapter -> raw output.

The agent never interprets or repairs the model's answer; the engine admits
it.  Each call is stateless: the full permitted seat history is rebuilt from
the observation, so no provider-side conversation state crosses games or seats.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ..config import ModelConfig
from ..engine.game import DecisionSpec
from ..prompts.templates import PROMPT_VERSION, prompt_hash, system_prompt, user_prompt
from ..providers.base import AdapterResponse, DecisionRequest, ProviderAdapter


class ContextOverflowError(ValueError):
    """Observation cannot fit the model's context window.  Never truncated."""


def estimate_tokens(text: str) -> int:
    # Conservative heuristic (~3 characters per token for JSON word lists).
    return len(text) // 3 + 16


@dataclass
class AgentOutput:
    raw: Any
    response: dict | None
    model_id: str
    estimated_input_tokens: int | None = None
    cost_estimate: float | None = None


class Limiters:
    """Global and per-provider concurrency limits (operational, not scored)."""

    def __init__(self, global_limit: int, per_provider: int):
        self.global_sem = asyncio.Semaphore(global_limit)
        self.per_provider = per_provider
        self._prov: dict[str, asyncio.Semaphore] = {}

    def provider(self, name: str) -> asyncio.Semaphore:
        if name not in self._prov:
            self._prov[name] = asyncio.Semaphore(self.per_provider)
        return self._prov[name]


class LLMAgent:
    def __init__(
        self,
        *,
        model: ModelConfig,
        adapter: ProviderAdapter,
        seat: str,
        clue_max_characters: int,
        turn_limit: int,
        limiters: Limiters,
        budget=None,
        sparse_max_entries: int = 20,
    ):
        self.model = model
        self.adapter = adapter
        self.seat = seat
        self.limiters = limiters
        self.budget = budget
        self.sparse_max_entries = sparse_max_entries
        self.system = system_prompt(clue_max_characters=clue_max_characters, turn_limit=turn_limit)

    def build_request(self, spec: DecisionSpec, decision_id: str) -> DecisionRequest:
        up = user_prompt(spec.observation, sparse_max_entries=self.sparse_max_entries)
        est = estimate_tokens(self.system) + estimate_tokens(up)
        if self.model.context_window_tokens is not None:
            need = est + (self.model.max_output_tokens or 0)
            if need > self.model.context_window_tokens:
                raise ContextOverflowError(
                    f"{self.model.id}: observation needs ~{need} tokens > context window "
                    f"{self.model.context_window_tokens}; use a smaller lexicon or larger-context model"
                )
        return DecisionRequest(
            decision_id=decision_id,
            seat=spec.seat,
            phase=spec.phase,
            system_prompt=self.system,
            user_prompt=up,
            schema_name=spec.schema_name,
            json_schema=spec.schema,
            max_output_tokens=self.model.max_output_tokens,
        )

    async def decide(self, spec: DecisionSpec, decision_id: str) -> AgentOutput:
        req = self.build_request(spec, decision_id)
        est = estimate_tokens(req.system_prompt) + estimate_tokens(req.user_prompt)
        reservation = 0.0
        if self.budget is not None:
            reservation = await self.budget.reserve(self.model, est)
        resp: AdapterResponse | None = None
        attempts = 1
        try:
            async with self.limiters.global_sem, self.limiters.provider(self.model.provider):
                resp = await self.adapter.decide(req)
            attempts = len(resp.attempts) or 1
        except Exception as e:
            attempts = len(getattr(e, "attempts", []) or [None])
            raise
        finally:
            cost = None
            if self.budget is not None:
                cost = await self.budget.commit(self.model, reservation, resp.usage if resp else None, attempts)
        meta = resp.to_json()
        meta["prompt_version"] = PROMPT_VERSION
        meta["prompt_hash"] = prompt_hash()
        return AgentOutput(raw=resp.output_text, response=meta, model_id=self.model.id,
                           estimated_input_tokens=est, cost_estimate=cost)
