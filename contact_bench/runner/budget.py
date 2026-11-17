"""Request and monetary stopping budgets with in-flight reservations (14.1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..config import ModelConfig, PriceTable
from ..providers.base import NormalizedUsage


class BudgetExhausted(RuntimeError):
    pass


def estimate_cost(prices: PriceTable, usage: NormalizedUsage) -> float | None:
    """Estimated cost of one response from a dated user-supplied price table."""
    if usage.input_tokens is None or usage.output_tokens is None:
        return None
    cached = usage.cached_input_tokens or 0
    uncached = max(0, usage.input_tokens - cached)
    c = uncached * prices.input_per_mtok / 1e6
    if cached:
        rate = prices.cached_input_per_mtok if prices.cached_input_per_mtok is not None else prices.input_per_mtok
        c += cached * rate / 1e6
    if usage.cache_write_tokens and prices.cache_write_per_mtok is not None:
        c += usage.cache_write_tokens * prices.cache_write_per_mtok / 1e6
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
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def reserve(self, model: ModelConfig, est_input_tokens: int) -> float:
        async with self._lock:
            if self.max_requests is not None and self.requests_used + self.requests_reserved >= self.max_requests:
                raise BudgetExhausted("request budget exhausted")
            res = 0.0
            if self.max_usd is not None:
                if model.prices is None:
                    raise BudgetExhausted(f"monetary cap requires a price table for {model.id}")
                res = worst_case_cost(model.prices, est_input_tokens, model.max_output_tokens or 0)
                if self.usd_spent + self.usd_reserved + res > self.max_usd:
                    raise BudgetExhausted("monetary budget would be exceeded by in-flight reservation")
            self.requests_reserved += 1
            self.usd_reserved += res
            return res

    async def commit(self, model: ModelConfig, reservation: float, usage: NormalizedUsage | None, attempts: int) -> float | None:
        async with self._lock:
            self.requests_reserved -= 1
            self.usd_reserved -= reservation
            # Every transport attempt may be billed; count them all.
            self.requests_used += max(1, attempts)
            cost = None
            if model.prices is not None and usage is not None:
                cost = estimate_cost(model.prices, usage)
            if cost is None and reservation:
                # Unknown usage: conservatively charge the reservation.
                self.usd_uncertain += 1
                cost = reservation
            if cost is not None:
                self.usd_spent += cost
            return cost

    def snapshot(self) -> dict:
        return {
            "max_requests": self.max_requests,
            "max_usd": self.max_usd,
            "requests_used": self.requests_used,
            "usd_spent_estimate": round(self.usd_spent, 6),
            "responses_with_uncertain_usage": self.usd_uncertain,
        }
