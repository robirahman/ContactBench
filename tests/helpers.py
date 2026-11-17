from __future__ import annotations

import asyncio
from typing import Any

from contact_bench.config import ProtocolConfig
from contact_bench.engine.game import DecisionSpec, Game, Unavailable
from contact_bench.lexicon import Lexicon


def lex(words, name="t") -> Lexicon:
    return Lexicon.from_words(name, words, min_length=1, max_length=64)


def make_game(words, secret, *, L=4, k=1, contact_words=None, joint_live=False, **proto) -> Game:
    vs = lex(words)
    vc = lex(contact_words, "c") if contact_words else vs
    return Game(
        game_id="g",
        secret=secret,
        v_secret=vs,
        v_contact=vc,
        protocol=ProtocolConfig(turn_limit=L, initial_prefix_length=k, **proto),
        joint_live=joint_live,
    )


class Script:
    """Decision table keyed by (turn, seat, phase); records requested specs."""

    def __init__(self, table: dict[tuple[int, str, str], Any]):
        self.table = table
        self.requested: list[DecisionSpec] = []

    async def __call__(self, spec: DecisionSpec):
        self.requested.append(spec)
        key = (spec.turn, spec.seat, spec.phase)
        if key not in self.table:
            raise AssertionError(f"unexpected decision request {key}")
        v = self.table[key]
        return v

    def phases(self, turn=None):
        return [(s.seat, s.phase) for s in self.requested if turn is None or s.turn == turn]

    def obs(self, turn, seat, phase):
        for s in self.requested:
            if (s.turn, s.seat, s.phase) == (turn, seat, phase):
                return s.observation
        raise KeyError((turn, seat, phase))


def clue(word, text):
    return {"action": "clue", "word": word, "clue": text}


def direct(word):
    return {"action": "direct", "word": word, "clue": None}


def guess(word):
    return {"action": "guess", "word": word}


PASS = {"action": "pass", "word": None}


def block(*words):
    return {"action": "block", "words": list(words)}


REVEAL = {"action": "reveal"}
CANCEL = {"action": "cancel"}
UNAVAILABLE = Unavailable("test")


def run_turn(game: Game, table: dict, turn: int | None = None) -> Script:
    t = turn or game.turns_used + 1
    s = Script({(t, *k): v for k, v in table.items()})
    asyncio.run(game.play_turn(s))
    return s


def run_all(game: Game, table: dict) -> Script:
    s = Script(table)
    asyncio.run(game.play(s))
    return s
