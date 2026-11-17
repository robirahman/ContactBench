"""Adaptive defender selection for mixed-model attacking teams.

Each (team pair, task) block gets one defender from the pool (models not on the
team).  Rounds are scheduled sequentially from all data completed so far:

1. Missing matchups first: prefer defenders that neither team model has faced
   (in team legs, scheduled or completed, or in pooled homogeneous fixtures).
2. Then the defender whose block would inform the most uncertain quantities:
   the largest Var(g1_A+g2_B-d_D) + Var(g1_B+g2_A-d_D) under the current
   role-rating posterior (Laplace covariance of the penalised fit).
3. Ties broken by a seeded hash of (round, pair, task, defender), independent
   of outcomes.

Selection is a pure function of the logged data, so it can be recomputed from
the run's logs; every round is recorded as a ``defenders_selected`` event.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass

from ..analysis.rating import RoleFit, leg_features


@dataclass(frozen=True)
class Block:
    task_id: str
    repetition: int
    a: str
    b: str


def round_slices(task_ids: list[str], rounds: int) -> list[list[str]]:
    """Split tasks (in manifest order) into contiguous rounds."""
    k = len(task_ids)
    size = -(-k // rounds)
    return [task_ids[i:i + size] for i in range(0, k, size)]


def _tie(seed: int, round_no: int, block: Block, d: str) -> str:
    return hashlib.sha256(f"{seed}|{round_no}|{block.task_id}|{block.repetition}|{block.a}|{block.b}|{d}".encode()
                          ).hexdigest()


def select_defenders(
    blocks: list[Block],
    *,
    pool: list[str],
    faced: Counter,
    fit: RoleFit | None,
    round_no: int,
    seed: int,
) -> list[tuple[Block, str, dict]]:
    """Choose a defender per block.  ``faced[(model, defender)]`` counts prior
    matchups; it is updated greedily so blocks in one round spread out."""
    faced = Counter(faced)
    out = []
    for blk in blocks:
        cands = [d for d in pool if d not in (blk.a, blk.b)]
        scored = []
        for d in cands:
            missing = int(faced[(blk.a, d)] == 0) + int(faced[(blk.b, d)] == 0)
            var = 0.0
            if fit is not None and all(m in fit.models for m in (blk.a, blk.b, d)):
                var = (fit.variance(leg_features(fit.models, (blk.a, blk.b, d)))
                       + fit.variance(leg_features(fit.models, (blk.b, blk.a, d))))
            scored.append(((missing, round(var, 12), _tie(seed, round_no, blk, d)), d))
        (missing, var, _), best = max(scored)
        faced[(blk.a, best)] += 1
        faced[(blk.b, best)] += 1
        out.append((blk, best, {"missing_matchups": missing, "variance_score": var,
                                "candidates": [d for _, d in sorted(scored, reverse=True)]}))
    return out
