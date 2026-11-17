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
from ..prompts.templates import PROMPT_VERSION, prompt_hash, system_prompt, user_prompt_parts
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
        dictionary_access: str = "full_candidate_lists",
        dictionary_service=None,
        max_tool_calls: int = 20,
        block_ranges: bool = False,
        empty_prefix: bool = False,
    ):
        self.model = model
        self.adapter = adapter
        self.seat = seat
        self.limiters = limiters
        self.budget = budget
        self.sparse_max_entries = sparse_max_entries
        self.dictionary_access = dictionary_access
        self.dictionary_service = dictionary_service
        self.max_tool_calls = max_tool_calls
        if dictionary_access == "lookup_tools" and dictionary_service is None:
            raise ValueError("lookup_tools condition requires a dictionary service")
        self.system = system_prompt(clue_max_characters=clue_max_characters, turn_limit=turn_limit,
                                    dictionary_access=dictionary_access, max_tool_calls=max_tool_calls,
                                    block_ranges=block_ranges, empty_prefix=empty_prefix)

    def build_request(self, spec: DecisionSpec, decision_id: str) -> DecisionRequest:
        parts, n_prefix = user_prompt_parts(spec.observation, sparse_max_entries=self.sparse_max_entries)
        up = "\n\n".join(parts)
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
            tools=self.dictionary_service.tool_specs() if self.dictionary_access == "lookup_tools" else [],
            tool_executor=self.dictionary_service.execute if self.dictionary_access == "lookup_tools" else None,
            max_tool_calls=self.max_tool_calls if self.dictionary_access == "lookup_tools" else 0,
            user_prompt_parts=parts,
            cache_prefix_parts=n_prefix,
        )

    async def decide(self, spec: DecisionSpec, decision_id: str) -> AgentOutput:
        from ..runner.budget import BudgetGate

        req = self.build_request(spec, decision_id)
        est = estimate_tokens(req.system_prompt) + estimate_tokens(req.user_prompt)
        gate = BudgetGate(self.budget, self.model, est) if self.budget is not None else None
        async with self.limiters.global_sem, self.limiters.provider(self.model.provider):
            resp = await self.adapter.decide(req, gate=gate)
        meta = resp.to_json()
        meta["prompt_version"] = PROMPT_VERSION
        meta["prompt_hash"] = prompt_hash()
        return AgentOutput(raw=resp.output_text, response=meta, model_id=self.model.id,
                           estimated_input_tokens=est, cost_estimate=gate.cost if gate else None)
