"""Request and monetary stopping budgets with in-flight reservations (14.1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..config import ModelConfig, PriceTable
from ..providers.base import AttemptGate, NormalizedUsage


class BudgetExhausted(RuntimeError):
    def __init__(self, msg: str, provider: str | None = None):
        super().__init__(msg)
        self.provider = provider  # set when only one provider's cap is reached


def estimate_cost(prices: PriceTable, usage: NormalizedUsage) -> float | None:
    """Estimated cost of one response from a dated user-supplied price table."""
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    # Normalized convention: input_tokens includes cache reads and writes.
    cached = usage.cached_input_tokens or 0
    written = (usage.cache_write_tokens or 0) if prices.cache_write_per_mtok is not None else 0
    uncached = max(0, usage.input_tokens - cached - written)
    c = uncached * prices.input_per_mtok / 1e6
    if cached:
        rate = prices.cached_input_per_mtok if prices.cached_input_per_mtok is not None else prices.input_per_mtok
        c += cached * rate / 1e6
    if usage.cache_write_tokens and prices.cache_write_per_mtok is not None:
        long = min(usage.cache_write_1h_tokens or 0, usage.cache_write_tokens)
        c += (usage.cache_write_tokens - long) * prices.cache_write_per_mtok / 1e6
        c += long * 2 * prices.input_per_mtok / 1e6  # 1-hour cache writes: 2x base input
    out = usage.billable_output_tokens() or 0
    c += out * prices.output_per_mtok / 1e6
    return c


def worst_case_cost(prices: PriceTable, input_tokens: int, max_output_tokens: int) -> float:
    return input_tokens * prices.input_per_mtok / 1e6 + max_output_tokens * prices.output_per_mtok / 1e6


@dataclass
class Budget:
    max_requests: int | None
    max_usd: float | None
    requests_reserved: int = 0
    requests_used: int = 0
    usd_reserved: float = 0.0
    usd_spent: float = 0.0
    usd_uncertain: int = 0  # responses with unknown usage
    # Optional per-provider dollar caps (one API key per provider).
    max_usd_by_provider: dict[str, float] = field(default_factory=dict)
    usd_spent_by_provider: dict[str, float] = field(default_factory=dict)
    usd_reserved_by_provider: dict[str, float] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def reserve(self, model: ModelConfig, est_input_tokens: int) -> float:
        async with self._lock:
            if self.max_requests is not None and self.requests_used + self.requests_reserved >= self.max_requests:
                raise BudgetExhausted("request budget exhausted")
            res = 0.0
            pcap = self.max_usd_by_provider.get(model.provider)
            if self.max_usd is not None or pcap is not None:
                if model.prices is None:
                    raise BudgetExhausted(f"monetary cap requires a price table for {model.id}")
                res = worst_case_cost(model.prices, est_input_tokens, model.max_output_tokens or 0)
                if self.max_usd is not None and self.usd_spent + self.usd_reserved + res > self.max_usd:
                    raise BudgetExhausted("monetary budget would be exceeded by in-flight reservation")
                p = model.provider
                if pcap is not None and (self.usd_spent_by_provider.get(p, 0.0)
                                         + self.usd_reserved_by_provider.get(p, 0.0) + res) > pcap:
                    raise BudgetExhausted(f"{p} monetary budget would be exceeded by in-flight reservation", provider=p)
                self.usd_reserved_by_provider[p] = self.usd_reserved_by_provider.get(p, 0.0) + res
            self.requests_reserved += 1
            self.usd_reserved += res
            return res

    async def commit(self, model: ModelConfig, reservation: float, usage: NormalizedUsage | None, attempts: int,
                     possibly_billed: bool = True) -> float | None:
        async with self._lock:
            self.requests_reserved -= 1
            self.usd_reserved -= reservation
            p = model.provider
            if p in self.usd_reserved_by_provider:
                self.usd_reserved_by_provider[p] -= reservation
            # Every transport attempt may be billed; count them all.
            self.requests_used += max(1, attempts)
            cost = None
            if model.prices is not None and usage is not None:
                cost = estimate_cost(model.prices, usage)
            if cost is None and reservation and possibly_billed:
                # Unknown usage: conservatively charge the reservation.
                self.usd_uncertain += 1
                cost = reservation
            if cost is not None:
                self.usd_spent += cost
                self.usd_spent_by_provider[p] = self.usd_spent_by_provider.get(p, 0.0) + cost
            return cost

    def snapshot(self) -> dict:
        return {
            "max_requests": self.max_requests,
            "max_usd": self.max_usd,
            "requests_used": self.requests_used,
            "usd_spent_estimate": round(self.usd_spent, 6),
            "max_usd_by_provider": dict(self.max_usd_by_provider),
            "usd_spent_by_provider": {k: round(v, 6) for k, v in self.usd_spent_by_provider.items()},
            "responses_with_uncertain_usage": self.usd_uncertain,
        }


class BudgetGate(AttemptGate):
    """Reserve budget before EVERY transport attempt (retries and tool-loop
    turns included) and settle it afterwards, so request and spend caps hold
    per provider call rather than per logical decision."""

    def __init__(self, budget: "Budget", model: ModelConfig, est_input_tokens: int):
        self.budget = budget
        self.model = model
        self.est = est_input_tokens
        self.cost = 0.0
        self.calls = 0

    async def before(self):
        return await self.budget.reserve(self.model, self.est)

    async def after(self, token, usage, ok, possibly_billed=True):
        self.calls += 1
        c = await self.budget.commit(self.model, token, usage, 1, possibly_billed=ok or possibly_billed)
        if c:
            self.cost += c
