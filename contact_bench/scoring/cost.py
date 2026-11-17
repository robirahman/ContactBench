"""Model game cost and aggregate efficiency (spec Section 7.7)."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Sequence

from .reference import RefValue, ReferenceScorer


@dataclass
class GameScore:
    status: str  # scored | unscored_incomplete
    baseline: RefValue | None
    cost: Fraction | None
    cost_exact: bool | None
    cost_mcse: float | None
    fallback: RefValue | None

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "baseline": self.baseline.to_json() if self.baseline else None,
            "cost_numerator": self.cost.numerator if self.cost is not None else None,
            "cost_denominator": self.cost.denominator if self.cost is not None else None,
            "cost": float(self.cost) if self.cost is not None else None,
            "cost_exact": self.cost_exact,
            "cost_mcse": self.cost_mcse,
            "fallback": self.fallback.to_json() if self.fallback else None,
        }

    @staticmethod
    def from_json(d: dict) -> "GameScore":
        return GameScore(
            status=d["status"],
            baseline=RefValue.from_json(d["baseline"]) if d.get("baseline") else None,
            cost=Fraction(d["cost_numerator"], d["cost_denominator"])
            if d.get("cost_numerator") is not None
            else None,
            cost_exact=d.get("cost_exact"),
            cost_mcse=d.get("cost_mcse"),
            fallback=RefValue.from_json(d["fallback"]) if d.get("fallback") else None,
        )


def score_game(
    *,
    outcome_status: str,
    winning_turn: int | None,
    turn_limit: int,
    secret: str,
    initial_candidates: Sequence[str],
    final_candidates: Sequence[str] | None,
    scorer: ReferenceScorer,
) -> GameScore:
    """B = R(S0, s); C = t if won, L + R(SL, s) if capped; unknown otherwise."""
    B = scorer.reference(initial_candidates, secret)
    if outcome_status == "solved":
        assert winning_turn is not None
        return GameScore("scored", B, Fraction(winning_turn), True, 0.0, None)
    if outcome_status == "capped":
        assert final_candidates is not None
        fb = scorer.reference(final_candidates, secret)
        return GameScore(
            "scored", B, turn_limit + fb.value, fb.exact, fb.mcse if not fb.exact else 0.0, fb
        )
    return GameScore("unscored_incomplete", B, None, None, None, None)


@dataclass
class Aggregate:
    games: int
    sum_baseline: Fraction
    sum_cost: Fraction

    @property
    def aggregate_speedup(self) -> Fraction | None:
        return self.sum_baseline / self.sum_cost if self.sum_cost else None

    @property
    def fraction_of_turns_saved(self) -> Fraction | None:
        return 1 - self.sum_cost / self.sum_baseline if self.sum_baseline else None

    @property
    def mean_effective_cost(self) -> Fraction | None:
        return self.sum_cost / self.games if self.games else None

    @property
    def mean_turns_saved(self) -> Fraction | None:
        return (self.sum_baseline - self.sum_cost) / self.games if self.games else None

    def to_json(self) -> dict:
        def f(x):
            return None if x is None else {"numerator": x.numerator, "denominator": x.denominator, "value": float(x)}

        return {
            "games": self.games,
            "sum_baseline": f(self.sum_baseline),
            "sum_cost": f(self.sum_cost),
            "aggregate_speedup": f(self.aggregate_speedup),
            "fraction_of_turns_saved": f(self.fraction_of_turns_saved),
            "mean_effective_cost": f(self.mean_effective_cost),
            "mean_turns_saved": f(self.mean_turns_saved),
        }


def aggregate(pairs: Iterable[tuple[Fraction, Fraction]]) -> Aggregate:
    """Ratio of totals over (baseline, cost) pairs; never a mean of ratios."""
    n = 0
    sb = Fraction(0)
    sc = Fraction(0)
    for b, c in pairs:
        n += 1
        sb += b
        sc += c
    return Aggregate(n, sb, sc)
