"""Property tests: candidate monotonicity, target preservation, normalization,
observation noninterference and replay equivalence (spec 18)."""

import asyncio
import json

from hypothesis import given, settings, strategies as st

from contact_bench.engine.game import Game
from contact_bench.lexicon import normalize_word

from .helpers import lex
from contact_bench.config import ProtocolConfig

WORDS = ["ab", "abc", "abd", "abde", "ac", "acab", "ad", "ba", "bad", "bade", "bb", "bead", "cab", "cad", "dab"]
LEX = lex(WORDS)
ALLOWED_PUBLIC = {"turn", "type", "seat", "word", "clue", "blocklist", "blocklist_collected", "opened_guesses",
                  "prefix_after", "result", "terminal_reason", "hit_sources"}

word = st.sampled_from(WORDS + ["zz", "Ab ", "a b"])
g1_action = st.one_of(
    st.builds(lambda w, c: {"action": "clue", "word": w, "clue": c}, word,
              st.text(alphabet="abcde ?!-'", min_size=0, max_size=12)),
    st.builds(lambda w: {"action": "direct", "word": w, "clue": None}, word),
    st.just("garbage"),
)
g2_action = st.one_of(st.builds(lambda w: {"action": "guess", "word": w}, word), st.just({"action": "pass", "word": None}))
d_action = st.builds(lambda ws: {"action": "block", "words": ws}, st.lists(st.sampled_from(WORDS), max_size=4))
choice = st.sampled_from([{"action": "reveal"}, {"action": "cancel"}, "x"])
turn_plan = st.tuples(g1_action, g2_action, d_action, choice)


def play(secret, plan, L):
    g = Game(game_id="p", secret=secret, v_secret=LEX, v_contact=LEX,
             protocol=ProtocolConfig(turn_limit=L, initial_prefix_length=1, clue_max_characters=10))
    log = {}
    snapshots = []

    async def decide(spec):
        a = plan[(spec.turn - 1) % len(plan)]
        v = {"act": a[0], "respond": a[1], "block": a[2], "choice": a[3]}[spec.phase]
        log[spec.key] = (v, json.dumps(spec.observation, sort_keys=True))
        return v

    async def run():
        while not g.terminal:
            before = set(g.secret_candidates())
            used_before = set(g.used_words)
            await g.play_turn(decide)
            snapshots.append((before, set(g.secret_candidates()), used_before, set(g.used_words)))

    asyncio.run(run())
    return g, log, snapshots


@settings(max_examples=150, deadline=None)
@given(st.sampled_from([w for w in WORDS if len(w) > 1]), st.lists(turn_plan, min_size=1, max_size=4),
       st.integers(1, 6))
def test_invariants_and_replay(secret, plan, L):
    g, log, snaps = play(secret, plan, L)
    for before, after, ub, ua in snaps:
        assert ub <= ua  # used words only grow
        if not (g.outcome_status == "solved" and after == set()):
            assert after <= before  # candidate monotonicity
    if g.outcome_status != "solved":
        assert secret in g.secret_candidates()  # target preservation
    assert g.turns_used <= L
    for e in g.public_history:
        assert set(e) <= ALLOWED_PUBLIC
    # replay equivalence: same decisions -> identical state and observations
    g2 = Game(game_id="p", secret=secret, v_secret=LEX, v_contact=LEX,
              protocol=ProtocolConfig(turn_limit=L, initial_prefix_length=1, clue_max_characters=10))

    async def replay(spec):
        v, oh = log[spec.key]
        assert json.dumps(spec.observation, sort_keys=True) == oh
        return v

    asyncio.run(g2.play(replay))
    assert g2.summary() == g.summary() and g2.audit == g.audit and g2.public_history == g.public_history


@settings(max_examples=100, deadline=None)
@given(st.lists(turn_plan, min_size=1, max_size=3), st.integers(1, 4))
def test_attacker_view_independent_of_secret_until_public_difference(plan, L):
    """Two secrets that never get publicly hit give identical attacker observations."""
    a = play("bade", plan, L)
    b = play("bead", plan, L)
    if a[0].public_history == b[0].public_history:
        for k in a[1]:
            if "/defender/" in k or k not in b[1]:
                continue
            assert a[1][k][1] == b[1][k][1]


@given(st.text(max_size=8))
def test_normalization(s):
    w = normalize_word(s)
    if w is not None:
        assert w.isascii() and w.isalpha() and w == w.lower()
        assert normalize_word(w) == w
