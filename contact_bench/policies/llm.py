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
    conversation: Any = None  # provider-native transcript (fork mode only)


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
        keep_conversation: bool = False,
    ):
        self.keep_conversation = keep_conversation
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
            tools=self.dictionary_service.tool_specs() if self.dictionary_access == "lookup_tools" else [],
            tool_executor=self.dictionary_service.execute if self.dictionary_access == "lookup_tools" else None,
            max_tool_calls=self.max_tool_calls if self.dictionary_access == "lookup_tools" else 0,
            keep_conversation=self.keep_conversation,
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
                           estimated_input_tokens=est, cost_estimate=gate.cost if gate else None,
                           conversation=resp.conversation)

    async def fork(self, spec: DecisionSpec, decision_id: str, conversation: Any, *, kind: str,
                   prompt: str) -> AgentOutput:
        """Branch this seat's finished transcript with a private forecast query."""
        from ..forecasts.forks import fork_schema
        from ..runner.budget import BudgetGate

        base = self.build_request(spec, decision_id)
        name, schema = fork_schema(kind)
        req = DecisionRequest(
            decision_id=decision_id,
            seat=spec.seat,
            phase=f"fork_{kind}",
            system_prompt=self.system,
            user_prompt=prompt,
            schema_name=name,
            json_schema=schema,
            max_output_tokens=self.model.max_output_tokens,
            tools=base.tools,
            tool_executor=base.tool_executor,
            max_tool_calls=base.max_tool_calls,
        )
        # The fork resends the whole retained transcript (gameplay prompt, any
        # tool turns, the model's answer) plus the forecast prompt; check it
        # all fits with the fork's output allowance before sending.
        import json as _json

        transcript = _json.dumps(conversation, default=str)
        est = estimate_tokens(base.system_prompt) + estimate_tokens(transcript) + estimate_tokens(prompt)
        if self.model.context_window_tokens is not None:
            need = est + (self.model.max_output_tokens or 0)
            if need > self.model.context_window_tokens:
                raise ContextOverflowError(
                    f"{self.model.id}: forked transcript needs ~{need} tokens > context window "
                    f"{self.model.context_window_tokens}")
        gate = BudgetGate(self.budget, self.model, est) if self.budget is not None else None
        try:
            async with self.limiters.global_sem, self.limiters.provider(self.model.provider):
                resp = await self.adapter.fork(req, conversation, gate=gate)
        except Exception as e:
            # Keep what was actually sent and charged for failure accounting.
            e.fork_requests_sent = gate.calls if gate else len(getattr(e, "attempts", []) or [])  # type: ignore[attr-defined]
            e.fork_cost = gate.cost if gate else None  # type: ignore[attr-defined]
            raise
        return AgentOutput(raw=resp.output_text, response=resp.to_json(), model_id=self.model.id,
                           estimated_input_tokens=est, cost_estimate=gate.cost if gate else None)
