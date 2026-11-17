"""Batch Elo-style rating with half-point draws (spec Section 9.3)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Sequence


def match_points(cost_ab: Fraction, cost_ba: Fraction) -> float:
    """A's points: 1 if A's attacking cost is lower than B's, 0.5 if equal."""
    if cost_ab < cost_ba:
        return 1.0
    if cost_ab == cost_ba:
        return 0.5
    return 0.0


@dataclass
class RatingFit:
    models: list[str]
    strengths: dict[str, float]
    elo: dict[str, float]
    converged: bool
    iterations: int
    gradient_norm: float
    loss: float
    penalty_scale: float
    components: list[list[str]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "method": "batch Elo-style rating with half-point draws",
            "models": self.models,
            "strengths_logit": self.strengths,
            "elo": self.elo,
            "converged": self.converged,
            "iterations": self.iterations,
            "gradient_norm": self.gradient_norm,
            "loss": self.loss,
            "penalty_scale": self.penalty_scale,
            "connected_components": self.components,
        }


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def connected_components(models: Sequence[str], pairs: Sequence[tuple[str, str]]) -> list[list[str]]:
    parent = {m: m for m in models}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    comps: dict[str, list[str]] = {}
    for m in models:
        comps.setdefault(find(m), []).append(m)
    return sorted((sorted(c) for c in comps.values()), key=lambda c: c[0])


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        if abs(piv) < 1e-300:
            raise ZeroDivisionError("singular Hessian")
        for r in range(n):
            if r != c:
                f = M[r][c] / piv
                if f:
                    for k in range(c, n + 1):
                        M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def fit_ratings(
    models: Sequence[str],
    results: Sequence[tuple[str, str, float]],
    *,
    penalty_scale: float = 2.5,
    elo_center: float = 1500.0,
    max_iter: int = 100,
    tol: float = 1e-10,
) -> RatingFit:
    """Minimize cross-entropy over paired fixtures plus sum(r^2)/(2 s^2).

    ``results`` holds (A, B, y) with y the A match points in {0, 0.5, 1}.
    Newton's method on a strictly convex objective; strengths are recentred
    to sum zero (the penalised optimum already has zero sum).
    """
    models = list(models)
    idx = {m: i for i, m in enumerate(models)}
    n = len(models)
    r = [0.0] * n
    inv = 1.0 / (penalty_scale * penalty_scale)

    def loss_grad_hess(r):
        loss = sum(x * x for x in r) * inv / 2
        g = [x * inv for x in r]
        H = [[(inv if i == j else 0.0) for j in range(n)] for i in range(n)]
        for a, b, y in results:
            i, j = idx[a], idx[b]
            p = _sigmoid(r[i] - r[j])
            p = min(max(p, 1e-300), 1 - 1e-16)
            loss -= y * math.log(p) + (1 - y) * math.log(1 - p)
            d = p - y
            g[i] += d
            g[j] -= d
            w = p * (1 - p)
            H[i][i] += w
            H[j][j] += w
            H[i][j] -= w
            H[j][i] -= w
        return loss, g, H

    converged = False
    it = 0
    gnorm = float("inf")
    loss = float("nan")
    for it in range(1, max_iter + 1):
        loss, g, H = loss_grad_hess(r)
        gnorm = math.sqrt(sum(x * x for x in g))
        if gnorm < tol:
            converged = True
            break
        step = _solve(H, g)
        r = [x - s for x, s in zip(r, step)]
    else:
        loss, g, _ = loss_grad_hess(r)
        gnorm = math.sqrt(sum(x * x for x in g))
        converged = gnorm < 1e-6
    mean = sum(r) / n if n else 0.0
    r = [x - mean for x in r]
    scale = 400.0 / math.log(10)
    comps = connected_components(models, [(a, b) for a, b, _ in results])
    return RatingFit(
        models=models,
        strengths={m: r[idx[m]] for m in models},
        elo={m: elo_center + scale * r[idx[m]] for m in models},
        converged=converged,
        iterations=it,
        gradient_norm=gnorm,
        loss=loss,
        penalty_scale=penalty_scale,
        components=comps,
    )
