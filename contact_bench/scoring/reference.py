"""Character-budget enumeration reference and completion scoring (spec Section 7).

The primary reference policy ("fresh shuffle character packing") repeatedly
draws a fresh uniform random ordering of the remaining public target
candidates, takes the maximal feasible initial segment under the combined
clue-plus-two-guess packing rule, and tests it with an empty defender and
always-reveal behaviour.

R_C(S, s) depends only on the length histogram h of S and the target length.
This module provides:

* exact shortcuts (all-fit, equal length, constant capacity),
* an exact rational small-state oracle,
* a reproducible length-class Monte Carlo estimator with exact rational sample
  means, rollout-level standard errors and a resumable on-disk cache.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from .. import PACKING_VERSION, RNG_VERSION

Histogram = tuple[tuple[int, int], ...]  # sorted ((length, count), ...), counts > 0


# --------------------------------------------------------------------------
# Histograms and packing
# --------------------------------------------------------------------------

def histogram_of(words: Iterable[str]) -> Histogram:
    c = Counter(len(w) for w in words)
    return tuple(sorted((l, n) for l, n in c.items() if n > 0))


def hist_total(h: Histogram) -> int:
    return sum(n for _, n in h)


def hist_key(h: Histogram) -> str:
    return ",".join(f"{l}:{n}" for l, n in h)


def batch_feasible_lengths(lengths: Sequence[int], C: int) -> bool:
    """Exact feasibility of testing a candidate batch in one combined turn.

    Two longest words go to the guess slots; the rest are listed in the clue
    separated by single spaces.  With weights a(w)=len(w)+1 and Q=C+1, a batch
    of three or more words is feasible iff sum(a) - two largest a <= Q.
    Batches of one or two words are always feasible (direct guess, or clue "?"
    plus two distinct registered guesses).
    """
    if len(lengths) <= 2:
        return True
    ws = sorted((l + 1 for l in lengths), reverse=True)
    return sum(ws) - ws[0] - ws[1] <= C + 1


class _BatchAccumulator:
    """Incremental feasibility test for a growing batch."""

    __slots__ = ("Q", "total", "u1", "u2", "k")

    def __init__(self, C: int):
        self.Q = C + 1
        self.total = 0
        self.u1 = 0
        self.u2 = 0
        self.k = 0

    def try_add(self, length: int) -> bool:
        w = length + 1
        if w >= self.u1:
            nu1, nu2 = w, self.u1
        elif w > self.u2:
            nu1, nu2 = self.u1, w
        else:
            nu1, nu2 = self.u1, self.u2
        nt = self.total + w
        if self.k + 1 >= 3 and nt - nu1 - nu2 > self.Q:
            return False
        self.total, self.u1, self.u2, self.k = nt, nu1, nu2, self.k + 1
        return True


def maximal_feasible_prefix(words_in_order: Sequence[str], C: int) -> list[str]:
    """Longest initial segment of the ordering that is feasible.

    Stops at the first word that would make the segment infeasible; later
    words are not skipped in to fill space.
    """
    acc = _BatchAccumulator(C)
    out = []
    for w in words_in_order:
        if not acc.try_add(len(w)):
            break
        out.append(w)
    return out


@dataclass(frozen=True)
class CombinedBatchAction:
    guesses: tuple[str, ...]  # 0 (never), 1 (direct) or 2 registered guesses
    clue_words: tuple[str, ...]
    clue: str | None

    @property
    def tested(self) -> tuple[str, ...]:
        return self.clue_words + self.guesses


def combined_batch_action(batch: Sequence[str], C: int) -> CombinedBatchAction:
    """Assign the two longest words to guess slots and list the rest literally."""
    if not batch:
        raise ValueError("empty batch")
    if len(batch) == 1:
        return CombinedBatchAction((batch[0],), (), None)
    # Deterministic tie-break: longer first, then alphabetical.
    ranked = sorted(batch, key=lambda w: (-len(w), w))
    guesses = (ranked[0], ranked[1])
    rest = [w for w in batch if w not in guesses]
    clue = " ".join(rest) if rest else "?"
    if len(clue) > C:
        raise ValueError("infeasible combined batch")
    return CombinedBatchAction(guesses, tuple(rest), clue)


def clue_only_chunks(words_in_order: Sequence[str], C: int) -> list[list[str]]:
    """Clue-only listing: consecutive whole words per clue, one space apart."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for w in words_in_order:
        if len(w) > C:
            raise ValueError(f"word of length {len(w)} cannot be listed within C={C}")
        add = len(w) if not cur else len(w) + 1
        if cur and cur_len + add > C:
            chunks.append(cur)
            cur, cur_len = [w], len(w)
        else:
            cur.append(w)
            cur_len += add
    if cur:
        chunks.append(cur)
    return chunks


def combined_worst_case_bound(lengths: Sequence[int], C: int) -> int:
    n = len(lengths)
    A = sum(l + 1 for l in lengths)
    return min(math.ceil(n / 2), math.ceil(A / (C + 1)))


# --------------------------------------------------------------------------
# Analytic formulas
# --------------------------------------------------------------------------

def F_b(n: int, b: int) -> Fraction:
    """Mean of ceil(r/b) for uniform rank r in 1..n."""
    if n <= 0:
        raise ValueError("n must be positive")
    q, m = divmod(n, b)
    return Fraction(b * q * (q + 1) // 2 + m * (q + 1), n)


def first_last_mean(n: int) -> Fraction:
    """Uncapped uniform-target mean of the first/last two-guess policy."""
    if n % 2 == 0:
        return Fraction(n + 2, 4)
    return Fraction((n + 1) ** 2, 4 * n)


def equal_length_capacity(ell: int, C: int) -> int:
    return 2 + (C + 1) // (ell + 1)


def constant_capacity(h: Histogram, C: int) -> int | None:
    lmin = h[0][0]
    lmax = h[-1][0]
    a, b = (C + 1) // (lmin + 1), (C + 1) // (lmax + 1)
    return 2 + a if a == b else None


def all_fit(h: Histogram, C: int) -> bool:
    lengths = [l for l, n in h for _ in range(n)]
    return batch_feasible_lengths(lengths, C)


# --------------------------------------------------------------------------
# Exact rational oracle
# --------------------------------------------------------------------------

def batch_distribution(h: Histogram, C: int) -> dict[tuple[int, ...], Fraction]:
    """Exact law of the length-count vector of one fresh-shuffle batch."""
    lengths = tuple(l for l, _ in h)
    counts = tuple(n for _, n in h)
    Q = C + 1

    @lru_cache(maxsize=None)
    def from_state(v: tuple[int, ...]) -> tuple[tuple[tuple[int, ...], Fraction], ...]:
        rem = [c - x for c, x in zip(counts, v)]
        n = sum(rem)
        if n == 0:
            return ((v, Fraction(1)),)
        k = sum(v)
        cur = sorted((lengths[i] + 1 for i in range(len(v)) for _ in range(v[i])), reverse=True)
        out: dict[tuple[int, ...], Fraction] = {}
        for i, r in enumerate(rem):
            if r == 0:
                continue
            p = Fraction(r, n)
            ws = sorted(cur + [lengths[i] + 1], reverse=True)
            feasible = k + 1 <= 2 or sum(ws) - ws[0] - ws[1] <= Q
            if feasible:
                nv = list(v)
                nv[i] += 1
                for fv, fp in from_state(tuple(nv)):
                    out[fv] = out.get(fv, Fraction(0)) + p * fp
            else:
                out[v] = out.get(v, Fraction(0)) + p
        return tuple(out.items())

    return dict(from_state(tuple(0 for _ in counts)))


def exact_reference(h: Histogram, ell: int, C: int) -> Fraction:
    """Exact R_C(h, ell) via the continuation recursion (tiny states only)."""

    @lru_cache(maxsize=None)
    def R(hh: Histogram) -> Fraction:
        lengths = [l for l, _ in hh]
        hcount = dict(hh)[ell]
        idx = lengths.index(ell)
        total = Fraction(1)
        for v, p in batch_distribution(hh, C).items():
            if v[idx] < hcount:
                rest = tuple((l, n - x) for (l, n), x in zip(hh, v) if n - x > 0)
                total += p * (1 - Fraction(v[idx], hcount)) * R(rest)
        return total

    if ell not in dict(h):
        raise ValueError("target length not present in histogram")
    return R(h)


# --------------------------------------------------------------------------
# Monte Carlo estimator
# --------------------------------------------------------------------------

def rollout_seed(root_seed: int, C: int, h: Histogram, r: int) -> int:
    s = f"{RNG_VERSION}|{PACKING_VERSION}|root={root_seed}|C={C}|hist={hist_key(h)}|r={r}"
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big")


def simulate_rollout(h: Histogram, C: int, seed: int) -> dict[int, int]:
    """One complete reference enumeration; returns rank sums by length class.

    Sequential uniform draws without replacement within a turn until the first
    infeasible extension, which is returned to the untested pool.  The RNG is
    Python's MT19937 (random.Random) seeded with ``seed``; each draw uses
    randrange(k) for exact uniformity.
    """
    rng = random.Random(seed)
    pool = [l for l, n in h for _ in range(n)]
    m = len(pool)
    rank_sum: dict[int, int] = {l: 0 for l, _ in h}
    turn = 0
    Q = C + 1
    randrange = rng.randrange
    while m > 0:
        turn += 1
        total = u1 = u2 = 0
        i = 0
        while i < m:
            j = randrange(m - i)
            pos = m - 1 - i
            pool[j], pool[pos] = pool[pos], pool[j]
            w = pool[pos] + 1
            if w >= u1:
                nu1, nu2 = w, u1
            elif w > u2:
                nu1, nu2 = u1, w
            else:
                nu1, nu2 = u1, u2
            nt = total + w
            if i + 1 >= 3 and nt - nu1 - nu2 > Q:
                break
            total, u1, u2 = nt, nu1, nu2
            rank_sum[pool[pos]] += turn
            i += 1
        m -= i
    return rank_sum


@dataclass
class RefValue:
    """A reference completion expectation for one (histogram, target length)."""

    value: Fraction
    exact: bool
    method: str
    histogram: str
    target_length: int
    C: int
    mcse: float | None = None
    rollouts: int | None = None
    rank_total: int | None = None
    denominator: int | None = None
    cache_key: str | None = None

    def to_json(self) -> dict:
        return {
            "numerator": self.value.numerator,
            "denominator": self.value.denominator,
            "value": float(self.value),
            "exact": self.exact,
            "method": self.method,
            "histogram": self.histogram,
            "target_length": self.target_length,
            "C": self.C,
            "mcse": self.mcse,
            "rollouts": self.rollouts,
            "rank_total": self.rank_total,
            "rank_denominator": self.denominator,
            "cache_key": self.cache_key,
        }

    @staticmethod
    def from_json(d: dict) -> "RefValue":
        return RefValue(
            value=Fraction(d["numerator"], d["denominator"]),
            exact=d["exact"],
            method=d["method"],
            histogram=d["histogram"],
            target_length=d["target_length"],
            C=d["C"],
            mcse=d.get("mcse"),
            rollouts=d.get("rollouts"),
            rank_total=d.get("rank_total"),
            denominator=d.get("rank_denominator"),
            cache_key=d.get("cache_key"),
        )


class ReferenceScorer:
    """Computes and caches R_C(h, ell).

    Cache entries are keyed by canonical histogram, C, packing/RNG versions and
    root seed; each stores per-rollout integer rank sums, so a K-rollout
    estimate is reproducible and extending to more rollouts reuses the first K
    rollouts without duplication.
    """

    def __init__(
        self,
        C: int,
        *,
        rollouts: int = 2048,
        root_seed: int = 20261116,
        exact_small_state_limit: int = 12,
        cache_dir: str | Path | None = None,
    ):
        self.C = C
        self.K = rollouts
        self.root_seed = root_seed
        self.exact_limit = exact_small_state_limit
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._mem: dict[str, dict] = {}
        self.stats = Counter()

    # -- public API ---------------------------------------------------------
    def reference(self, candidates: Iterable[str], target: str) -> RefValue:
        """R_C(S, s) for a public candidate set S containing target s.

        Uses only the length histogram of S and the target's length class; the
        policy itself never sees the target.
        """
        cands = list(candidates)
        if target not in cands:
            raise ValueError("target must belong to the public candidate set")
        return self.reference_hist(histogram_of(cands), len(target))

    def reference_hist(self, h: Histogram, ell: int) -> RefValue:
        hk = hist_key(h)
        n = hist_total(h)
        if ell not in dict(h):
            raise ValueError("target length class absent from histogram")
        if all_fit(h, self.C):
            self.stats["all_fit"] += 1
            return RefValue(Fraction(1), True, "all_fit", hk, ell, self.C)
        if len(h) == 1:
            self.stats["equal_length"] += 1
            b = equal_length_capacity(ell, self.C)
            return RefValue(F_b(n, b), True, f"equal_length_F_{b}", hk, ell, self.C)
        b = constant_capacity(h, self.C)
        if b is not None:
            self.stats["constant_capacity"] += 1
            return RefValue(F_b(n, b), True, f"constant_capacity_F_{b}", hk, ell, self.C)
        if n <= self.exact_limit:
            self.stats["exact_oracle"] += 1
            return RefValue(exact_reference(h, ell, self.C), True, "exact_oracle", hk, ell, self.C)
        self.stats["monte_carlo"] += 1
        return self._mc(h, ell)

    def all_lengths(self, h: Histogram) -> dict[int, RefValue]:
        return {l: self.reference_hist(h, l) for l, _ in h}

    # -- Monte Carlo ----------------------------------------------------------
    def _cache_id(self, h: Histogram) -> str:
        key = f"{PACKING_VERSION}|{RNG_VERSION}|root={self.root_seed}|C={self.C}|hist={hist_key(h)}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    def _load(self, cid: str) -> dict | None:
        if cid in self._mem:
            return self._mem[cid]
        if self.cache_dir:
            p = self.cache_dir / f"{cid}.json"
            if p.exists():
                d = json.loads(p.read_text())
                self._mem[cid] = d
                return d
        return None

    def _save(self, cid: str, d: dict) -> None:
        self._mem[cid] = d
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(d, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.cache_dir / f"{cid}.json")

    def rollout_table(self, h: Histogram, K: int | None = None) -> dict:
        """Ensure at least K rollouts exist in the cache; return the entry."""
        K = K or self.K
        cid = self._cache_id(h)
        d = self._load(cid)
        if d is None:
            d = {
                "cache_id": cid,
                "packing_version": PACKING_VERSION,
                "rng_version": RNG_VERSION,
                "root_seed": self.root_seed,
                "C": self.C,
                "histogram": hist_key(h),
                "rollouts_done": 0,
                "rank_sums": {str(l): [] for l, _ in h},
            }
        else:
            self.stats["cache_hit"] += 1
        done = d["rollouts_done"]
        if done < K:
            for r in range(done, K):
                rs = simulate_rollout(h, self.C, rollout_seed(self.root_seed, self.C, h, r))
                for l, _ in h:
                    d["rank_sums"][str(l)].append(rs[l])
                d["rollouts_done"] = r + 1
                if self.cache_dir and (r + 1) % 512 == 0:
                    self._save(cid, d)  # resumable accumulation
            self._save(cid, d)
        return d

    def _mc(self, h: Histogram, ell: int) -> RefValue:
        K = self.K
        d = self.rollout_table(h, K)
        sums = d["rank_sums"][str(ell)][:K]
        hcount = dict(h)[ell]
        total = sum(sums)
        denom = K * hcount
        mean = Fraction(total, denom)
        # Rollout-level MCSE of Z_r = S_r / h[ell]
        zs = [Fraction(s, hcount) for s in sums]
        ss = sum((z - mean) ** 2 for z in zs)
        mcse = math.sqrt(float(ss / (K * (K - 1)))) if K > 1 else None
        return RefValue(
            mean,
            False,
            "length_class_monte_carlo",
            hist_key(h),
            ell,
            self.C,
            mcse=mcse,
            rollouts=K,
            rank_total=total,
            denominator=denom,
            cache_key=d["cache_id"],
        )
