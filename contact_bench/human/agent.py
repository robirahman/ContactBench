"""Human seat agent and the public-information pre-check for human input."""

from __future__ import annotations

import bisect
from typing import Any

from ..engine import actions as A
from ..engine.game import DecisionSpec
from ..lexicon import normalize_word


class HumanStopped(RuntimeError):
    """The human paused the session; the game stays pending and resumable."""


def _used(word: str, obs: dict) -> bool:
    if word in obs.get("used_words", ()):
        return True
    ranges = obs.get("used_ranges") or []
    starts = [r[0] for r in ranges]
    i = bisect.bisect_right(starts, word) - 1
    return i >= 0 and word <= ranges[i][1]


def _candidate(word: str | None, obs: dict, dictionary) -> bool:
    """Current candidate from public information only: a dictionary word that
    starts with the shown prefix and is not used (exactly the engine's rule)."""
    return (word is not None and dictionary.is_legal_word(word) and word.startswith(obs["prefix"])
            and not _used(word, obs))


def precheck(spec: DecisionSpec | dict, action: Any, *, contact_dictionary, secret_dictionary=None) -> str | None:
    """Would the engine admit this action?  Returns the engine's reason or None.

    Uses only the deciding seat's observation and the public dictionary, and
    the engine's own admission functions, so the answer equals the engine's
    verdict.  It lets the page catch typos before a turn is lost; the action
    is still admitted by the engine as usual after submission.
    """
    s = spec if isinstance(spec, dict) else {"seat": spec.seat, "phase": spec.phase, "observation": spec.observation}
    obs, seat, phase = s["observation"], s["seat"], s["phase"]
    secret_dictionary = secret_dictionary or contact_dictionary
    if phase == "choice":
        return A.admit_choice(action).reason
    if seat == "guesser1":
        w = normalize_word(action.get("word")) if isinstance(action, dict) else None
        pre_contact = frozenset([w]) if _candidate(w, obs, contact_dictionary) else frozenset()
        pre_secret = frozenset([w]) if _candidate(w, obs, secret_dictionary) else frozenset()
        return A.admit_guesser1(action, pre_secret=pre_secret, pre_contact=pre_contact,
                                max_chars=obs["clue_max_characters"],
                                clue_allowed=obs.get("offense_condition") != "direct_only").reason
    if seat == "guesser2":
        w = normalize_word(action.get("word")) if isinstance(action, dict) else None
        pre_contact = frozenset([w]) if _candidate(w, obs, contact_dictionary) else frozenset()
        return A.admit_guesser2(action, pre_contact=pre_contact).reason
    if seat == "defender":
        return A.admit_defender(action, contact_vocab=contact_dictionary.lexicon.word_set,
                                allow_ranges=obs.get("blocklist_encoding") == "words_and_ranges").reason
    return "unknown seat"


class HumanAgent:
    """Fills one seat with decisions submitted by the local human player."""

    def __init__(self, model, seat: str, game, session, dictionary, *, max_lookups: int, dictionary_access: str):
        self.model = model
        self.seat = seat
        self.game = game
        self.session = session
        self.dictionary = dictionary
        self.max_lookups = max_lookups if dictionary_access == "lookup_tools" else 0

    async def decide(self, spec: DecisionSpec, decision_id: str) -> tuple[Any, dict]:
        """Wait for the human's action; returns (raw action, unscored metadata)."""
        if self.session is None:
            raise HumanStopped("no human session")
        return await self.session.ask(spec, decision_id, game=self.game, max_lookups=self.max_lookups)
