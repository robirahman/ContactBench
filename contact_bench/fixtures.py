"""Worked mechanics fixtures (spec Section 6.6) and replay views."""

from __future__ import annotations

import json
from typing import Any

from .config import ProtocolConfig
from .engine.game import DecisionSpec, Game
from .lexicon import Lexicon

MECHANICS_WORDS = ["cable", "camera", "candle", "candy", "canoe", "carrot", "castle", "cobra", "comet", "crane"]

# Decisions keyed by (turn, seat, phase) for the Section 6.6 worked example.
MECHANICS_DECISIONS: dict[tuple[int, str, str], Any] = {
    (1, "guesser1", "act"): {"action": "clue", "word": "carrot", "clue": "An orange root vegetable"},
    (1, "guesser2", "respond"): {"action": "guess", "word": "castle"},
    (1, "defender", "block"): {"action": "block", "words": ["camera", "carrot"]},
    (1, "guesser2", "choice"): {"action": "cancel"},
    (2, "guesser1", "act"): {"action": "clue", "word": "castle", "clue": "A fortified home with towers"},
    (2, "guesser2", "respond"): {"action": "guess", "word": "castle"},
    (2, "defender", "block"): {"action": "block", "words": ["comet"]},
    (3, "guesser1", "act"): {"action": "clue", "word": "candle", "clue": "Wax surrounding a wick"},
    (3, "guesser2", "respond"): {"action": "guess", "word": "candy"},
    (3, "defender", "block"): {"action": "block", "words": []},
}


def mechanics_game() -> Game:
    lex = Lexicon.from_words("mechanics_fixture", MECHANICS_WORDS, min_length=3, max_length=20)
    return Game(
        game_id="mechanics-6.6",
        secret="candle",
        v_secret=lex,
        v_contact=lex,
        protocol=ProtocolConfig(turn_limit=4),
    )


def table_decider(table: dict[tuple[int, str, str], Any], log: list[DecisionSpec] | None = None):
    async def decide(spec: DecisionSpec):
        if log is not None:
            log.append(spec)
        return table[(spec.turn, spec.seat, spec.phase)]

    return decide


def render_views(public_history: list[dict], private: dict[str, list[dict]], audit: list[dict],
                 secret: str, view: str) -> str:
    """Text transcript for one information view.

    public   — what everyone (and the defender's replay view) sees.
    guesser1 / guesser2 / defender — public events plus that seat's own record.
    audit    — omniscient referee audit (post-game only).
    """
    lines = []
    if view == "audit":
        lines.append(f"[OMNISCIENT AUDIT — post-game only] secret={secret}")
        for t in audit:
            lines.append(json.dumps({k: v for k, v in t.items() if k not in ("guesser1", "guesser2", "defender")}, sort_keys=True))
        return "\n".join(lines)
    lines.append(f"[{view.upper()} VIEW]" + (f" secret={secret}" if view == "defender" else ""))
    for e in public_history:
        lines.append("public: " + json.dumps(e, sort_keys=True))
        if view in ("guesser1", "guesser2", "defender"):
            for p in private.get(view, []):
                if p["turn"] == e["turn"]:
                    lines.append(f"  own private ({view}): " + json.dumps(p, sort_keys=True))
    return "\n".join(lines)
