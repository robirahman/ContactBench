"""Scripted baseline policies (spec Sections 7.1-7.3 and 11).

Scripted seats use only their own observation.  Teammate coordination is a
declared public algorithm; when a live scripted baseline needs a common
randomized plan it uses a target-independent policy seed exposed to every
scripted seat (including the defender).  No scripted offense code reads the
secret.
"""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any

from ..engine.game import DecisionSpec
from ..lexicon import extract_alpha_runs
from ..scoring.reference import clue_only_chunks, combined_batch_action, maximal_feasible_prefix


def _rng(*parts: Any) -> random.Random:
    s = "|".join(str(p) for p in parts)
    return random.Random(int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big"))


def _hash_order(words: list[str], *parts: Any) -> list[str]:
    salt = "|".join(str(p) for p in parts)
    return sorted(words, key=lambda w: hashlib.sha256(f"{salt}|{w}".encode()).digest())


class ScriptedAgent:
    """A scripted policy for one seat in one game."""

    def __init__(
        self,
        *,
        seat: str,
        offense_policy: str = "first_last_two_guess",
        defender_policy: str = "empty",
        choice_policy: str = "always_reveal",
        policy_seed: int = 0,
        ambiguity: int = 2,
        secret_dictionary=None,
        contact_dictionary=None,
    ):
        self.seat = seat
        self.offense = offense_policy
        self.defense = defender_policy
        self.choice = choice_policy
        self.policy_seed = policy_seed
        self.ambiguity = ambiguity
        # In closed-book / lookup-tool conditions observations carry no lists;
        # scripted reference algorithms then enumerate the public dictionary
        # through the same deterministic lookup interface the models may use.
        self.secret_dictionary = secret_dictionary
        self.contact_dictionary = contact_dictionary or secret_dictionary

    async def decide(self, spec: DecisionSpec) -> Any:
        return self.act(spec)

    # synchronous core, convenient for tests
    @staticmethod
    def _used_set(obs: dict):
        used = set(obs["used_words"])
        ranges = obs.get("used_ranges") or []

        def is_used(w: str) -> bool:
            return w in used or any(a <= w <= b for a, b in ranges)

        return is_used

    def _with_lists(self, obs: dict) -> dict:
        if "secret_candidates" in obs:
            return obs
        if self.secret_dictionary is None:
            raise ValueError("scripted policy needs a dictionary service in this condition")
        prefix, is_used = obs["prefix"], self._used_set(obs)
        obs = dict(obs)
        obs["secret_candidates"] = [w for w in self.secret_dictionary.all_words(prefix)
                                    if not is_used(w) and len(w) > len(prefix)]
        obs["contact_candidates"] = [w for w in self.contact_dictionary.all_words(prefix)
                                     if not is_used(w) and len(w) > len(prefix)]
        return obs

    def act(self, spec: DecisionSpec) -> Any:
        obs = self._with_lists(spec.observation)
        if spec.phase == "choice":
            return {"action": "reveal" if self.choice == "always_reveal" else "cancel"}
        if spec.seat == "defender":
            return self._defend(obs)
        return self._offend(spec.seat, obs)

    # ---------------------------------------------------------------- offense
    def _order(self, cands: list[str], turn: int) -> list[str]:
        p = self.offense
        if p.endswith("alphabetical"):
            return list(cands)
        if p.endswith("reverse"):
            return list(reversed(cands))
        if p in ("combined_fixed_shuffle", "clue_only_shuffled"):
            # One fixed pseudo-random permutation of the whole vocabulary,
            # restricted to the current candidates (shared by both seats).
            return _hash_order(cands, "fixed", self.policy_seed)
        if p == "combined_fresh_shuffle":
            # A fresh permutation on every turn.
            return _hash_order(cands, "fresh", self.policy_seed, turn)
        raise ValueError(p)

    def _offend(self, seat: str, obs: dict) -> Any:
        cands: list[str] = obs["secret_candidates"]
        turn = obs["turn"]
        C = obs["clue_max_characters"]
        p = self.offense
        g1 = seat == "guesser1"

        if p == "wasted_turns":
            return {"action": "invalid"} if g1 else {"action": "pass", "word": None}

        if len(cands) == 1:
            # The final singleton is guessed directly (Guesser 1 only acts).
            return {"action": "direct", "word": cands[0], "clue": None} if g1 else {"action": "pass", "word": None}

        if p == "first_last_two_guess":
            if g1:
                return {"action": "clue", "word": cands[0], "clue": "?"}
            return {"action": "guess", "word": cands[-1]}

        if p in ("alphabetical_direct", "reverse_direct"):
            w = cands[0] if p == "alphabetical_direct" else cands[-1]
            return {"action": "direct", "word": w, "clue": None} if g1 else {"action": "pass", "word": None}

        if p.startswith("clue_only_"):
            if not g1:
                return {"action": "pass", "word": None}
            chunk = clue_only_chunks(self._order(cands, turn), C)[0]
            return {"action": "clue", "word": chunk[0], "clue": " ".join(chunk)}

        if p.startswith("combined_"):
            batch = maximal_feasible_prefix(self._order(cands, turn), C)
            act = combined_batch_action(batch, C)
            if len(act.guesses) == 1:
                return {"action": "direct", "word": act.guesses[0], "clue": None} if g1 else {"action": "pass", "word": None}
            if g1:
                return {"action": "clue", "word": act.guesses[0], "clue": act.clue}
            return {"action": "guess", "word": act.guesses[1]}

        if p == "public_index_ambiguity":
            contact: list[str] = obs["contact_candidates"]
            options = [w for w in cands[: self.ambiguity]]
            if g1:
                idx = [contact.index(w) + 1 for w in options]
                w = _rng("private", self.policy_seed, seat, turn).choice(options)
                return {"action": "clue", "word": w, "clue": " ".join(f"#{i}" for i in idx)}
            clue = obs["current_clue"]
            picks = [int(m) for m in re.findall(r"#(\d+)", clue)]
            picks = [contact[i - 1] for i in picks if 1 <= i <= len(contact)]
            if not picks:
                return {"action": "pass", "word": None}
            return {"action": "guess", "word": _rng("private", self.policy_seed, seat, turn).choice(picks)}

        raise ValueError(f"unknown offense policy {p}")

    # ---------------------------------------------------------------- defense
    def _defend(self, obs: dict) -> Any:
        out = self._defend_words(obs)
        if obs.get("blocklist_encoding") == "words_and_ranges":
            out["ranges"] = []
        return out

    def _defend_words(self, obs: dict) -> Any:
        secret = obs["secret"]
        contact: list[str] = obs["contact_candidates"]
        d = self.defense
        if d == "empty":
            return {"action": "block", "words": []}
        if d == "literal_clue_words":
            known = set(contact) | set(obs["used_words"]) | set(obs["secret_candidates"])
            named = sorted({t for t in extract_alpha_runs(obs["current_clue"]) if t in known})
            return {"action": "block", "words": named}
        if d.startswith("random_"):
            k = int(d.split("_")[1])
            pool = [w for w in contact if w != secret]
            rng = _rng("defender", self.policy_seed, obs["turn"])
            return {"action": "block", "words": sorted(rng.sample(pool, min(k, len(pool))))}
        if d == "all_nonsecret":
            return {"action": "block", "words": [w for w in contact if w != secret]}
        if d == "index_decoder":
            picks = [int(m) for m in re.findall(r"#(\d+)", obs["current_clue"])]
            words = sorted({contact[i - 1] for i in picks if 1 <= i <= len(contact)} - {secret})
            return {"action": "block", "words": words}
        raise ValueError(f"unknown defender policy {d}")
