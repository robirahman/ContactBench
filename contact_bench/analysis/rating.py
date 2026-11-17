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


def fit_anchored(
    fixed_elo: dict[str, float],
    results: Sequence[tuple[str, str, float]],
    free: Sequence[str],
    *,
    penalty_scale: float = 2.5,
    elo_center: float = 1500.0,
    max_iter: int = 100,
    tol: float = 1e-10,
) -> dict:
    """Rate ``free`` players against opponents whose Elo is held fixed.

    Same likelihood and the same Gaussian penalty (centred on ``elo_center``)
    as :func:`fit_ratings`, but only the free strengths are fitted, so adding a
    player never moves the published model ratings.  Opponents must be in
    ``fixed_elo``; results between two fixed players are constant and ignored.
    """
    scale = 400.0 / math.log(10)
    free = list(free)
    fidx = {m: i for i, m in enumerate(free)}
    for a, b, _ in results:
        for m in (a, b):
            if m not in fidx and m not in fixed_elo:
                raise ValueError(f"{m!r} is neither free nor in the anchor ratings")
    results = [x for x in results if x[0] in fidx or x[1] in fidx]
    n = len(free)
    r = [0.0] * n
    inv = 1.0 / (penalty_scale * penalty_scale)

    def strength(m, r):
        return r[fidx[m]] if m in fidx else (fixed_elo[m] - elo_center) / scale

    def lgh(r):
        loss = sum(x * x for x in r) * inv / 2
        g = [x * inv for x in r]
        H = [[(inv if i == j else 0.0) for j in range(n)] for i in range(n)]
        for a, b, y in results:
            p = _sigmoid(strength(a, r) - strength(b, r))
            p = min(max(p, 1e-300), 1 - 1e-16)
            loss -= y * math.log(p) + (1 - y) * math.log(1 - p)
            d, w = p - y, p * (1 - p)
            ia, ib = fidx.get(a), fidx.get(b)
            if ia is not None:
                g[ia] += d
                H[ia][ia] += w
            if ib is not None:
                g[ib] -= d
                H[ib][ib] += w
            if ia is not None and ib is not None:
                H[ia][ib] -= w
                H[ib][ia] -= w
        return loss, g, H

    converged, it, gnorm, loss = False, 0, float("inf"), float("nan")
    for it in range(1, max_iter + 1):
        loss, g, H = lgh(r)
        gnorm = math.sqrt(sum(x * x for x in g))
        if gnorm < tol:
            converged = True
            break
        step = _solve(H, g)
        r = [x - s for x, s in zip(r, step)]
    else:
        converged = gnorm < 1e-6
    _, _, H = lgh(r)
    # Approximate standard errors from the penalised Hessian (Laplace).
    se = {}
    for m in free:
        e = [1.0 if j == fidx[m] else 0.0 for j in range(n)]
        try:
            se[m] = scale * math.sqrt(max(_solve(H, e)[fidx[m]], 0.0))
        except ZeroDivisionError:
            se[m] = None
    return {
        "method": "anchored batch Elo-style rating (opponents fixed, same penalty)",
        "free": free,
        "elo": {m: elo_center + scale * r[fidx[m]] for m in free},
        "elo_se_approx": se,
        "fixed_elo": {m: fixed_elo[m] for m in sorted({x for a, b, _ in results for x in (a, b)} - set(free))},
        "results": len(results),
        "converged": converged,
        "iterations": it,
        "gradient_norm": gnorm,
        "loss": loss,
        "penalty_scale": penalty_scale,
    }


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


# ---------------------------------------------------------------------------
# Additive role ratings (mixed-model attacking teams)
# ---------------------------------------------------------------------------
ROLES = ("g1", "g2", "d")  # clue-giver (Guesser 1), receiver (Guesser 2), defender


@dataclass
class RoleFit:
    models: list[str]
    theta: dict[str, dict[str, float]]  # model -> role -> logit strength
    composite: dict[str, float]  # g1 + g2 + d, recentred to mean zero
    elo: dict[str, float]
    covariance: list[list[float]]  # Laplace covariance of the stacked parameters
    converged: bool
    iterations: int
    penalty_scale: float
    n_fixtures: int

    def index(self, model: str, role: str) -> int:
        return 3 * self.models.index(model) + ROLES.index(role)

    def variance(self, x: dict[int, float]) -> float:
        return sum(a * self.covariance[i][j] * b for i, a in x.items() for j, b in x.items())

    def to_json(self) -> dict:
        scale = 400.0 / math.log(10)
        return {
            "method": "additive role ratings: leg strength g1[G1] + g2[G2] - d[D]; "
                      "fixture P(first leg cheaper) = sigmoid(strength difference); half-point draws",
            "models": self.models,
            "components_logit": self.theta,
            "components_elo_points": {m: {r: scale * v for r, v in t.items()} for m, t in self.theta.items()},
            "composite_logit": self.composite,
            "elo": self.elo,
            "converged": self.converged,
            "iterations": self.iterations,
            "penalty_scale": self.penalty_scale,
            "fixtures": self.n_fixtures,
        }


Leg = tuple[str, str, str]  # (guesser1 model, guesser2 model, defender model)


def leg_features(models: Sequence[str], leg: Leg, sign: float = 1.0) -> dict[int, float]:
    idx = {m: i for i, m in enumerate(models)}
    g1, g2, d = leg
    x: dict[int, float] = {}
    for k, v in ((3 * idx[g1] + 0, sign), (3 * idx[g2] + 1, sign), (3 * idx[d] + 2, -sign)):
        x[k] = x.get(k, 0.0) + v
    return x


def fit_role_ratings(
    models: Sequence[str],
    fixtures: Sequence[tuple[Leg, Leg, float]],
    *,
    penalty_scale: float = 2.5,
    elo_center: float = 1500.0,
    max_iter: int = 100,
    tol: float = 1e-10,
) -> RoleFit:
    """MAP fit of role strengths from paired fixtures.

    Each fixture is (leg1, leg2, y) with y the first leg's match points.  Each
    role component has prior N(0, s^2/3), so a model's composite g1+g2+d has
    prior N(0, s^2): with only homogeneous fixtures (A+A vs B, B+B vs A) the
    composite equals the existing per-model Elo fit.
    """
    models = list(models)
    n = 3 * len(models)
    inv = 3.0 / (penalty_scale * penalty_scale)
    xs = []
    for l1, l2, y in fixtures:
        x = leg_features(models, l1)
        for k, v in leg_features(models, l2, -1.0).items():
            x[k] = x.get(k, 0.0) + v
        xs.append(({k: v for k, v in x.items() if v}, y))
    th = [0.0] * n

    def lgh(th):
        loss = sum(t * t for t in th) * inv / 2
        g = [t * inv for t in th]
        H = [[(inv if i == j else 0.0) for j in range(n)] for i in range(n)]
        for x, y in xs:
            z = sum(th[k] * v for k, v in x.items())
            p = min(max(_sigmoid(z), 1e-300), 1 - 1e-16)
            loss -= y * math.log(p) + (1 - y) * math.log(1 - p)
            w = p * (1 - p)
            for k, v in x.items():
                g[k] += (p - y) * v
                for k2, v2 in x.items():
                    H[k][k2] += w * v * v2
        return loss, g, H

    converged, it = False, 0
    H = None
    for it in range(1, max_iter + 1):
        loss, g, H = lgh(th)
        if math.sqrt(sum(v * v for v in g)) < tol:
            converged = True
            break
        step = _solve(H, g)
        th = [a - b for a, b in zip(th, step)]
    else:
        loss, g, H = lgh(th)
        converged = math.sqrt(sum(v * v for v in g)) < 1e-6
    cov = [_solve(H, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    theta = {m: {r: th[3 * i + k] for k, r in enumerate(ROLES)} for i, m in enumerate(models)}
    # Each role is identified only up to a common shift (e.g. +c to every g1
    # and -c to every g2 leaves all legs unchanged), so report components
    # centred within each role.  Team fixtures (same defender in both legs)
    # carry no information on d; defender components come from homogeneous
    # model-pair fixtures in the pool.
    for k, r in enumerate(ROLES):
        mu = sum(theta[m][r] for m in models) / len(models) if models else 0.0
        for m in models:
            theta[m][r] -= mu
    comp = {m: sum(theta[m].values()) for m in models}
    mean = sum(comp.values()) / len(models) if models else 0.0
    comp = {m: v - mean for m, v in comp.items()}
    scale = 400.0 / math.log(10)
    return RoleFit(models, theta, comp, {m: elo_center + scale * v for m, v in comp.items()}, cov,
                   converged, it, penalty_scale, len(fixtures))


def _rref_basis(rows: list[list[Fraction]]) -> list[tuple[int, list[Fraction]]]:
    """Reduced row-echelon basis of the row space: [(pivot column, row)]."""
    basis: list[tuple[int, list[Fraction]]] = []
    for row in rows:
        v = list(row)
        for p, b in basis:
            if v[p]:
                f = v[p]
                v = [x - f * y for x, y in zip(v, b)]
        piv = next((i for i, x in enumerate(v) if x), None)
        if piv is None:
            continue
        v = [x / v[piv] for x in v]
        basis = [(p, [x - b[piv] * y for x, y in zip(b, v)]) for p, b in basis]
        basis.append((piv, v))
    return basis


def _in_row_space(basis, c: list[Fraction]) -> bool:
    v = list(c)
    for p, b in basis:
        if v[p]:
            f = v[p]
            v = [x - f * y for x, y in zip(v, b)]
    return not any(v)


def role_estimability(models: Sequence[str], fixtures: Sequence[tuple[Leg, Leg, float]],
                      reference: Sequence[str] | None = None) -> dict[str, dict[str, bool]]:
    """Which reported quantities the fixture design identifies (exactly).

    Each fixture's likelihood depends on theta only through x = f(leg1) - f(leg2).
    A reported value c.theta is identified iff c lies in the row space of the
    design.  Components are centred within each role, so the reported g1 of
    model m is theta[m,g1] - mean_{k in reference} theta[k,g1] (reference
    defaults to all models); the composite is centred over all models.
    """
    ref = [models.index(k) for k in (reference or models)]
    n = len(models)
    rows = []
    seen = set()
    for l1, l2, _ in fixtures:
        x = [Fraction(0)] * (3 * n)
        for k, v in leg_features(models, l1, 1.0).items():
            x[k] += Fraction(v)
        for k, v in leg_features(models, l2, -1.0).items():
            x[k] += Fraction(v)
        key = tuple(x)
        if key not in seen and any(x):
            seen.add(key)
            rows.append(x)
    basis = _rref_basis(rows)

    def centred(m: int, roles: Sequence[int], over: Sequence[int]) -> list[Fraction]:
        c = [Fraction(0)] * (3 * n)
        for r in roles:
            for k in over:
                c[3 * k + r] -= Fraction(1, len(over))
            c[3 * m + r] += 1
        return c

    out = {}
    for i, m in enumerate(models):
        est = {role: _in_row_space(basis, centred(i, [j], ref)) for j, role in enumerate(ROLES)}
        est["composite"] = _in_row_space(basis, centred(i, [0, 1, 2], range(n)))
        out[m] = est
    return out
