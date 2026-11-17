"""Completion scoring and reference acceptance tests (spec 7.9, 18.2)."""

import asyncio
import itertools
import math
import random
from fractions import Fraction
from functools import lru_cache

import pytest

from contact_bench.analysis.rating import match_points
from contact_bench.config import ProtocolConfig
from contact_bench.engine.game import Game
from contact_bench.policies.scripted import ScriptedAgent
from contact_bench.scoring.cost import aggregate, score_game
from contact_bench.scoring.reference import (
    F_b, ReferenceScorer, all_fit, batch_distribution, batch_feasible_lengths, clue_only_chunks,
    combined_batch_action, combined_worst_case_bound, exact_reference, first_last_mean, histogram_of,
    maximal_feasible_prefix, simulate_rollout,
)

from .helpers import lex


def test_analytic_fixtures():
    assert first_last_mean(100) == Fraction(51, 2)
    assert first_last_mean(5) == Fraction(9, 5)
    assert F_b(100, 6) == Fraction(221, 25)
    assert F_b(100, 18) == Fraction(33, 10)
    for n in range(1, 30):
        assert F_b(n, 1) == Fraction(n + 1, 2)
        assert F_b(n, 2) == first_last_mean(n)
        assert F_b(n, 3) == Fraction(sum(math.ceil(r / 3) for r in range(1, n + 1)), n)


def test_equal_length_reference_uses_character_capacity():
    sc = ReferenceScorer(100)
    words20 = [("w%02d" % i).ljust(20, "x").replace("0", "a").replace("1", "b") for i in range(100)]
    h20 = ((20, 100),)
    assert sc.reference_hist(h20, 20).value == Fraction(221, 25)
    assert sc.reference_hist(((5, 100),), 5).value == Fraction(33, 10)


def test_mixed_histogram_exact_fixture():
    h = ((3, 2), (8, 3))
    r3, r8 = exact_reference(h, 3, 8), exact_reference(h, 8, 8)
    assert (r3, r8) == (Fraction(5, 4), Fraction(13, 10))
    assert (2 * r3 + 3 * r8) / 5 == Fraction(32, 25)


def test_clue_only_vs_combined_cat_dog_pig():
    assert len(clue_only_chunks(["cat", "dog", "pig"], 6)) == 3
    assert maximal_feasible_prefix(["cat", "dog", "pig"], 6) == ["cat", "dog", "pig"]
    act = combined_batch_action(["cat", "dog", "pig"], 6)
    assert len(act.guesses) == 2 and len(act.clue) <= 6 and set(act.tested) == {"cat", "dog", "pig"}


def test_all_fit_reference_is_exactly_one():
    sc = ReferenceScorer(100)
    words = ["cable", "camera", "candle", "candy", "canoe", "carrot", "castle", "cobra", "comet", "crane"]
    r = sc.reference(words, "candle")
    assert r.value == 1 and r.exact and r.method == "all_fit"
    assert sc.reference(["solo"], "solo").value == 1


def test_packing_rules():
    # two longest words reserved as guesses; one space separators
    act = combined_batch_action(["ant", "bee", "carrot", "dragonfly", "eel"], 100)
    assert act.guesses == ("dragonfly", "carrot") and act.clue == "ant bee eel"
    # maximal prefix stops at the first infeasible word, does not skip ahead
    assert maximal_feasible_prefix(["aaaa", "bbbb", "cccc", "dddd", "e"], 4) == ["aaaa", "bbbb", "cccc"]
    assert batch_feasible_lengths([4, 4, 4], 4) and not batch_feasible_lengths([4, 4, 4, 4], 4)
    assert combined_batch_action(["solo"], 10).guesses == ("solo",)
    assert combined_batch_action(["ab", "cd"], 1).clue == "?"


def test_combined_worst_case_bound_small_states():
    rng = random.Random(3)
    for _ in range(300):
        n = rng.randint(1, 12)
        lengths = [rng.randint(1, 9) for _ in range(n)]
        C = rng.randint(1, 20)
        words = [chr(97 + i) * l for i, l in enumerate(lengths)]
        remaining = list(words)
        turns = 0
        while remaining:
            rng.shuffle(remaining)
            b = maximal_feasible_prefix(remaining, C)
            assert b
            remaining = remaining[len(b):]
            turns += 1
        assert turns <= combined_worst_case_bound(lengths, C)


def test_forward_reverse_fixed_b_regression():
    words = ["aaa", "bbb", "ccc", "ddd", "eee"]  # equal length 3, C=1 -> capacity b=2

    def ranks(order):
        out, rem, t = {}, list(order), 0
        while rem:
            t += 1
            b = maximal_feasible_prefix(rem, 1)
            for w in b:
                out[w] = t
            rem = rem[len(b):]
        return out

    f, r = ranks(words), ranks(list(reversed(words)))
    assert [Fraction(f[w] + r[w], 2) for w in words] == [2, Fraction(3, 2), 2, Fraction(3, 2), 2]
    assert F_b(5, 2) == Fraction(9, 5)


def _set_reference(words: tuple[str, ...], target: str, C: int) -> Fraction:
    """Independent brute force: average over all permutations of word identities."""

    @lru_cache(maxsize=None)
    def R(S: frozenset) -> Fraction:
        perms = list(itertools.permutations(sorted(S)))
        tot = Fraction(0)
        for p in perms:
            b = maximal_feasible_prefix(p, C)
            if target in b:
                tot += 1
            else:
                tot += 1 + R(S - frozenset(b))
        return tot / len(perms)

    return R(frozenset(words))


@pytest.mark.parametrize("words,C", [
    (("ab", "cd", "efgh", "ijklm", "no"), 4),
    (("a", "bb", "ccc", "dddd", "eeeee", "ff"), 5),
    (("aaa", "bbb", "cccccccc", "dddddddd", "eeeeeeee"), 8),
])
def test_exact_oracle_matches_permutation_brute_force(words, C):
    h = histogram_of(words)
    for w in words:
        assert exact_reference(h, len(w), C) == _set_reference(words, w, C)


def test_batch_distribution_matches_permutations():
    words = ("ab", "cd", "efgh", "ijklm", "no")
    C = 4
    h = histogram_of(words)
    lengths = [l for l, _ in h]
    dist = batch_distribution(h, C)
    counts = {}
    perms = list(itertools.permutations(words))
    for p in perms:
        b = maximal_feasible_prefix(p, C)
        v = tuple(sum(1 for w in b if len(w) == l) for l in lengths)
        counts[v] = counts.get(v, 0) + 1
    assert {v: Fraction(c, len(perms)) for v, c in counts.items()} == dist


def test_cap_consistency_of_fresh_shuffle_hybrid():
    """Ideal reference for k turns followed by the same ideal fallback costs R."""
    words = ("ab", "cd", "efgh", "ijklm", "no")
    C = 4
    for target in words:
        R0 = _set_reference(words, target, C)

        @lru_cache(maxsize=None)
        def G(S: frozenset, k: int) -> Fraction:
            if k == 0:
                return _set_reference(tuple(sorted(S)), target, C)
            perms = list(itertools.permutations(sorted(S)))
            tot = Fraction(0)
            for p in perms:
                b = maximal_feasible_prefix(p, C)
                tot += 1 if target in b else 1 + G(S - frozenset(b), k - 1)
            return tot / len(perms)

        for k in (1, 2, 3):
            assert G(frozenset(words), k) == R0


def test_ideal_monotonicity_under_nontarget_deletion():
    words = ("a", "bb", "ccc", "dddd", "eeeee", "ff")
    C = 5
    for target in words:
        full = exact_reference(histogram_of(words), len(target), C)
        for x in words:
            if x != target:
                sub = tuple(w for w in words if w != x)
                assert exact_reference(histogram_of(sub), len(target), C) <= full


def test_monte_carlo_estimator_against_exact_and_properties(tmp_path):
    h = ((3, 2), (8, 3))
    sc = ReferenceScorer(8, rollouts=4000, exact_small_state_limit=0, cache_dir=tmp_path)
    for ell, exact in ((3, Fraction(5, 4)), (8, Fraction(13, 10))):
        r = sc.reference_hist(h, ell)
        assert not r.exact and r.method == "length_class_monte_carlo"
        assert r.value == Fraction(r.rank_total, r.denominator)
        assert r.denominator == 4000 * dict(h)[ell]
        assert abs(float(r.value - exact)) < 5 * r.mcse + 1e-9


def test_mc_cache_resume_and_spelling_invariance(tmp_path):
    words_a = ["ab", "cd", "efgh", "ijklm", "no", "pq", "rstu", "vwxyz", "zz", "yyyy", "xxxxx", "ww", "vv"]
    words_b = ["ba", "dc", "hgfe", "mlkji", "on", "qp", "utsr", "zyxwv", "aa", "bbbb", "ccccc", "dd", "ee"]
    s1 = ReferenceScorer(6, rollouts=300, exact_small_state_limit=0, cache_dir=tmp_path / "c1")
    ra = s1.reference(words_a, "efgh")
    rb = s1.reference(words_b, "hgfe")
    assert ra.value == rb.value and ra.cache_key == rb.cache_key
    # target identity within a length class does not matter
    assert s1.reference(words_a, "rstu").value == ra.value
    # resumable accumulation: 100 then 300 equals 300 directly
    s2 = ReferenceScorer(6, rollouts=100, exact_small_state_limit=0, cache_dir=tmp_path / "c2")
    s2.reference(words_a, "efgh")
    s2.K = 300
    assert s2.reference(words_a, "efgh").value == ra.value
    s3 = ReferenceScorer(6, rollouts=300, exact_small_state_limit=0, cache_dir=tmp_path / "c2")
    assert s3.reference(words_a, "efgh").value == ra.value and s3.stats["cache_hit"] >= 1


def test_equal_length_rollouts_have_zero_class_variance():
    h = ((4, 10),)
    for seed in range(5):
        rs = simulate_rollout(h, 9, seed)  # b = 2 + 10//5 = 4
        assert Fraction(rs[4], 10) == F_b(10, 4)


def test_seeds_independent_of_target():
    sc = ReferenceScorer(6, rollouts=50, exact_small_state_limit=0)
    words = ["ab", "cd", "efgh", "ijklm", "no", "pq", "rstu", "vwxyz", "zz", "yyyy", "xxxxx", "ww", "vv"]
    a = sc.reference(words, "ab").cache_key
    b = sc.reference(words, "vwxyz").cache_key
    assert a == b


def _run_policy(words, secret, policy, *, C=100, L=1000, defender="empty", choice="always_reveal"):
    v = lex(words)
    g = Game(game_id="x", secret=secret, v_secret=v, v_contact=v,
             protocol=ProtocolConfig(turn_limit=L, clue_max_characters=C, initial_prefix_length=0))
    agents = {s: ScriptedAgent(seat=s, offense_policy=policy, defender_policy=defender, choice_policy=choice,
                               policy_seed=1) for s in ("guesser1", "guesser2", "defender")}

    async def decide(spec):
        return agents[spec.seat].act(spec)

    asyncio.run(g.play(decide))
    return g


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 8, 9])
def test_first_last_engine_mean_matches_F2(n):
    words = ["w" + "".join(chr(97 + int(d)) for d in f"{i:03d}") for i in range(n)]
    costs = [_run_policy(words, s, "first_last_two_guess").winning_turn for s in words]
    assert Fraction(sum(costs), n) == first_last_mean(n)
    assert max(costs) == math.ceil(n / 2)


@pytest.mark.parametrize("defender", ["random_3", "all_nonsecret", "random_10"])
def test_first_last_worst_case_under_adversarial_blocks(defender):
    words = ["w" + "".join(chr(97 + int(d)) for d in f"{i:03d}") for i in range(11)]
    for s in words:
        g = _run_policy(words, s, "first_last_two_guess", defender=defender)
        assert g.outcome_status == "solved" and g.winning_turn <= math.ceil(len(words) / 2)


def test_single_word_direct_F1():
    words = ["w" + chr(97 + i) for i in range(7)]
    costs = [_run_policy(words, s, "alphabetical_direct").winning_turn for s in words]
    assert Fraction(sum(costs), 7) == F_b(7, 1) == Fraction(4, 1)


def test_wasted_turns_cost_and_capped_singleton():
    words = ["aa", "bb", "cc"]
    sc = ReferenceScorer(100)
    g = _run_policy(words, "bb", "wasted_turns", L=3)
    assert g.outcome_status == "capped"
    s = score_game(outcome_status=g.outcome_status, winning_turn=None, turn_limit=3, secret="bb",
                   initial_candidates=g.initial_secret_candidates, final_candidates=g.secret_candidates(), scorer=sc)
    assert s.cost == 3 + s.baseline.value
    # unsolved singleton at cap costs L+1
    s2 = score_game(outcome_status="capped", winning_turn=None, turn_limit=5, secret="bb",
                    initial_candidates=words, final_candidates=["bb"], scorer=sc)
    assert s2.cost == 6


def test_ratio_of_totals_fixture():
    words = ["aaa", "bbb", "ccc", "ddd"]
    sc = ReferenceScorer(1)
    pairs = []
    for s in words:
        g = _run_policy(words, s, "combined_alphabetical", C=1, L=1)
        res = score_game(outcome_status=g.outcome_status, winning_turn=g.winning_turn, turn_limit=1, secret=s,
                         initial_candidates=g.initial_secret_candidates,
                         final_candidates=g.secret_candidates() if g.outcome_status == "capped" else None, scorer=sc)
        pairs.append((res.baseline.value, res.cost))
    assert [c for _, c in pairs] == [1, 1, 2, 2]
    assert all(b == Fraction(3, 2) for b, _ in pairs)
    agg = aggregate(pairs)
    assert agg.aggregate_speedup == 1
    assert sum(b / c for b, c in pairs) / 4 == Fraction(9, 8)


def test_final_letter_contact_at_cap_cost_L():
    from .helpers import make_game, run_all, clue, guess, block
    g = make_game(["arch", "art", "ash"], "art", k=2, L=1)
    run_all(g, {(1, "guesser1", "act"): clue("arch", "x"), (1, "guesser2", "respond"): guess("arch"),
                (1, "defender", "block"): block()})
    s = score_game(outcome_status=g.outcome_status, winning_turn=g.winning_turn, turn_limit=1, secret="art",
                   initial_candidates=g.initial_secret_candidates, final_candidates=None, scorer=ReferenceScorer(100))
    assert s.cost == 1 and g.terminal_reason == "prefix_completed"


def test_equal_efficiency_different_elo_counterexample():
    # 24 equally likely 20-char targets in four groups of 6; C=100 => b=6; L=3.
    A_order, B_order = "abc", "cab"
    fallback = 3 + F_b(6, 6)  # group d after the cap
    assert fallback == 4

    def cost(order, grp):
        return Fraction(order.index(grp) + 1) if grp in order else fallback

    pts, ca, cb = [], [], []
    for grp in "abcd":
        for _ in range(6):
            a, b = cost(A_order, grp), cost(B_order, grp)
            ca.append(a)
            cb.append(b)
            pts.append(match_points(a, b))
    assert sum(ca) / 24 == sum(cb) / 24 == F_b(24, 6) == Fraction(5, 2)
    assert pts.count(1.0) == 12 and pts.count(0.0) == 6 and pts.count(0.5) == 6
    assert sum(pts) / 24 == 0.625


def test_dictionary_bound_example():
    D, C = 1_000_000, 100
    assert math.ceil((D + 1) / (C + 1)) == 9901
