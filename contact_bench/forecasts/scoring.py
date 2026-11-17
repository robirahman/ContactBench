"""Sparse probability forecasts and proper scores (spec Sections 8.2-8.5)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from ..lexicon import normalize_word

NO_MATCH = "NO_MATCH"


class ForecastError(ValueError):
    pass


@dataclass(frozen=True)
class SparseForecast:
    """q(w) = listed p for listed words; other_mass/(M-h) for each unlisted word."""

    support_size: int
    listed: dict[str, float]
    other_mass: float

    def prob(self, w: str) -> float:
        if w in self.listed:
            return self.listed[w]
        rest = self.support_size - len(self.listed)
        return self.other_mass / rest if rest > 0 else 0.0

    def sum_squares(self) -> float:
        rest = self.support_size - len(self.listed)
        s = sum(p * p for p in self.listed.values())
        if rest > 0:
            s += self.other_mass * self.other_mass / rest
        return s

    def dense(self, support: Sequence[str]) -> dict[str, float]:
        return {w: self.prob(w) for w in support}


def parse_sparse(
    report: Any,
    support: Sequence[str],
    *,
    max_entries: int = 20,
    tolerance: float = 1e-6,
    allow_no_match: bool = False,
) -> SparseForecast:
    """Validate a sparse report; small mass errors within tolerance are renormalized."""
    if not isinstance(report, dict) or set(report) != {"entries", "other_mass"}:
        raise ForecastError("forecast must have exactly entries and other_mass")
    entries = report["entries"]
    if not isinstance(entries, list) or len(entries) > max_entries:
        raise ForecastError(f"entries must be a list of at most {max_entries}")
    sup = set(support)
    listed: dict[str, float] = {}
    for e in entries:
        if not isinstance(e, dict) or set(e) != {"word", "probability"}:
            raise ForecastError("each entry needs exactly word and probability")
        raw = e["word"]
        w = NO_MATCH if (allow_no_match and raw == NO_MATCH) else normalize_word(raw)
        if w is None or w not in sup:
            raise ForecastError("forecast word outside support")
        if w in listed:
            raise ForecastError("duplicate forecast entry")
        p = e["probability"]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ForecastError("probabilities must be finite and in [0,1]")
        listed[w] = float(p)
    a = report["other_mass"]
    if isinstance(a, bool) or not isinstance(a, (int, float)) or not math.isfinite(a) or not 0 <= a <= 1:
        raise ForecastError("other_mass must be finite and in [0,1]")
    a = float(a)
    M = len(sup)
    if len(listed) == M and a != 0:
        if abs(a) > tolerance:
            raise ForecastError("full-support report requires zero residual mass")
        a = 0.0
    total = sum(listed.values()) + a
    if abs(total - 1.0) > tolerance:
        raise ForecastError("total probability mass must be one")
    if total != 1.0:
        listed = {w: p / total for w, p in listed.items()}
        a = a / total
    return SparseForecast(M, listed, a)


def brier(fc: SparseForecast, truth: str) -> float:
    """Higher-is-better affine Brier score 2 q(W) - sum q^2, range [-1, 1]."""
    return 2 * fc.prob(truth) - fc.sum_squares()


def log_score(fc: SparseForecast, truth: str) -> tuple[float, bool]:
    """(log q(W), zero_probability_failure).  No silent clipping."""
    p = fc.prob(truth)
    if p <= 0:
        return float("-inf"), True
    return math.log(p), False


def dense_brier(q: dict[str, float], truth: str) -> float:
    return 1 - sum((p - (1.0 if w == truth else 0.0)) ** 2 for w, p in q.items())


def match_label(w1: str, receiver_canonical: dict | None) -> str | None:
    """Commitment-match label: W if registered words agree else NO_MATCH.

    Model-invalid receiver output is a canonical pass and therefore NO_MATCH;
    an infrastructure-unobserved receiver answer (None) is unknown.
    """
    if receiver_canonical is None:
        return None
    if receiver_canonical.get("action") == "guess" and receiver_canonical.get("word") == w1:
        return w1
    return NO_MATCH
