"""Pure Contact game engine (spec Sections 3, 5, 6).

The engine owns the secret, vocabularies, private commitments and public
state.  It never performs I/O: decisions are obtained through an injected
``decide`` coroutine, which the runner backs with agents, a recorded decision
log (replay/resume) or both.  Given the same canonical decisions the engine is
fully deterministic.
"""

from __future__ import annotations

import asyncio
import bisect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..config import ProtocolConfig
from ..lexicon import Lexicon, mentioned_words
from . import actions as A


class EngineInvariantError(RuntimeError):
    """A bug: an engine invariant was violated.  Analysis must halt."""


class GameSetupError(ValueError):
    pass


@dataclass(frozen=True)
class Unavailable:
    """Infrastructure could not obtain a decision (not model behavior)."""

    reason: str = "unavailable"


@dataclass(frozen=True)
class DecisionSpec:
    game_id: str
    turn: int
    seat: str
    phase: str
    observation: dict
    schema_name: str
    schema: dict

    @property
    def key(self) -> str:
        return f"{self.game_id}/t{self.turn:03d}/{self.seat}/{self.phase}"


DecideFn = Callable[[DecisionSpec], Awaitable[Any]]

OUTCOME_ONGOING = "ongoing"
OUTCOME_SOLVED = "solved"
OUTCOME_CAPPED = "capped"
OUTCOME_INCOMPLETE = "infrastructure_incomplete"

TERMINAL_UTTERANCE = "public_target_utterance"
TERMINAL_PREFIX = "prefix_completed"
TERMINAL_CAP = "turn_cap"


def _prefix_range(words: tuple[str, ...], prefix: str) -> tuple[int, int]:
    lo = bisect.bisect_left(words, prefix)
    hi = bisect.bisect_left(words, prefix + "\x7f")
    return lo, hi


class Game:
    """One Contact game with fixed seats guesser1, guesser2 and defender."""

    def __init__(
        self,
        *,
        game_id: str,
        secret: str,
        v_secret: Lexicon,
        v_contact: Lexicon,
        protocol: ProtocolConfig,
        offense_condition: str = "full",
        joint_live: bool = False,
    ):
        if secret not in v_secret:
            raise GameSetupError("secret is not in V_secret")
        k = protocol.initial_prefix_length
        if not k < len(secret):
            raise GameSetupError("initial prefix must be strictly shorter than the secret")
        if offense_condition not in ("full", "direct_only", "no_contact_batching"):
            raise GameSetupError(f"unknown offense condition {offense_condition!r}")
        self.game_id = game_id
        self._secret = secret
        self.v_secret = v_secret
        self.v_contact = v_contact
        self.vocab_union: frozenset[str] = v_secret.word_set | v_contact.word_set
        self.protocol = protocol
        self.offense_condition = offense_condition
        self.joint_live = joint_live
        self.turn_limit = protocol.turn_limit
        self.clue_max = protocol.clue_max_characters

        # public state
        self.prefix = secret[:k]
        self.initial_prefix = self.prefix
        self.turns_used = 0
        self.used_words: set[str] = set()
        self.public_history: list[dict] = []
        self.outcome_status = OUTCOME_ONGOING
        self.terminal_reason: str | None = None
        # operational state
        self.collection_status = "complete"
        self.pending: dict | None = None
        self.winning_turn: int | None = None
        self.hit_sources: list[str] = []
        self.hit_source_completeness = "complete"
        # private / referee state
        self.private_history: dict[str, list[dict]] = {s: [] for s in A.SEATS}
        self.audit: list[dict] = []
        self.prefix_events: list[dict] = []
        self.decision_count = 0
        self.diagnostics: list[dict] = []  # joint-live forecast payloads (private)

        self._display_prefix(turn=0)
        self.initial_secret_candidates = tuple(self.secret_candidates())
        self.initial_contact_candidates_count = len(self.contact_candidates())
        self._check_invariants()

    # ------------------------------------------------------------------ state
    @property
    def secret(self) -> str:
        """Referee-only access to the secret."""
        return self._secret

    @property
    def terminal(self) -> bool:
        return self.outcome_status in (OUTCOME_SOLVED, OUTCOME_CAPPED)

    def secret_candidates(self) -> list[str]:
        lo, hi = _prefix_range(self.v_secret.words, self.prefix)
        return [w for w in self.v_secret.words[lo:hi] if w not in self.used_words]

    def contact_candidates(self) -> list[str]:
        lo, hi = _prefix_range(self.v_contact.words, self.prefix)
        return [w for w in self.v_contact.words[lo:hi] if w not in self.used_words]

    def _display_prefix(self, turn: int) -> None:
        """Canonical prefix-display event: a dictionary-valued prefix is used."""
        if self.prefix in self.vocab_union and self.prefix not in self.used_words:
            self.used_words.add(self.prefix)
            self.prefix_events.append({"turn": turn, "prefix": self.prefix})

    def _check_invariants(self) -> None:
        if self.outcome_status == OUTCOME_ONGOING or self.outcome_status == OUTCOME_CAPPED:
            cands = self.secret_candidates()
            if self._secret not in cands:
                raise EngineInvariantError("secret missing from surviving candidate set")
            if any(len(w) <= len(self.prefix) for w in cands):
                raise EngineInvariantError("candidate not strictly longer than prefix")

    def public_view(self) -> dict:
        """Exactly the public state fields (no referee or private data)."""
        return {
            "prefix": self.prefix,
            "turns_used": self.turns_used,
            "turn_limit": self.turn_limit,
            "used_words": sorted(self.used_words),
            "public_history": [dict(e) for e in self.public_history],
            "outcome_status": self.outcome_status
            if self.outcome_status != OUTCOME_INCOMPLETE
            else OUTCOME_ONGOING,
        }

    # ----------------------------------------------------------- observations
    def observation(self, seat: str, phase: str, turn: int, **extras: Any) -> dict:
        from ..observations.builder import build_observation

        return build_observation(
            public=self.public_view(),
            seat=seat,
            phase=phase,
            turn=turn,
            clue_max_characters=self.clue_max,
            secret_candidates=self.secret_candidates(),
            contact_candidates=self.contact_candidates(),
            own_private_history=[dict(e) for e in self.private_history[seat]],
            secret=self._secret if seat == "defender" else None,
            offense_condition=self.offense_condition,
            joint_live=self.joint_live,
            **extras,
        )

    def _spec(self, seat: str, phase: str, turn: int, obs: dict) -> DecisionSpec:
        name, schema = A.schema_for(seat, phase, self.joint_live)
        return DecisionSpec(self.game_id, turn, seat, phase, obs, name, schema)

    # ----------------------------------------------------------------- driver
    async def play(self, decide: DecideFn) -> None:
        """Play until terminal, capped, or an infrastructure-pending phase."""
        while not self.terminal and self.outcome_status != OUTCOME_INCOMPLETE:
            await self.play_turn(decide)

    def _finish_turn(self, t: int) -> None:
        self.turns_used = t
        if not self.terminal and self.turns_used >= self.turn_limit:
            self.outcome_status = OUTCOME_CAPPED
            self.terminal_reason = TERMINAL_CAP
        self._check_invariants()

    def _win(self, t: int, reason: str, sources: list[str]) -> None:
        self.outcome_status = OUTCOME_SOLVED
        self.terminal_reason = reason
        self.winning_turn = t
        self.hit_sources = sources
        self.turns_used = t

    def _set_pending(self, t: int, phase: str, seats: list[str]) -> None:
        self.outcome_status = OUTCOME_INCOMPLETE
        self.collection_status = "incomplete"
        self.pending = {"turn": t, "phase": phase, "seats": seats}

    async def play_turn(self, decide: DecideFn) -> None:
        if self.terminal or self.outcome_status == OUTCOME_INCOMPLETE:
            raise EngineInvariantError("play_turn called on a finished or pending game")
        t = self.turns_used + 1
        pre_used = frozenset(self.used_words)
        pre_secret_list = self.secret_candidates()
        pre_secret = frozenset(pre_secret_list)
        pre_contact = frozenset(self.contact_candidates())
        prefix_before = self.prefix
        audit: dict[str, Any] = {
            "turn": t,
            "prefix_before": prefix_before,
            "secret_candidates_before": len(pre_secret),
            "contact_candidates_before": len(pre_contact),
            "decisions": 0,
        }

        # ---------------- Guesser 1
        obs = self.observation("guesser1", "act", t)
        r1 = await decide(self._spec("guesser1", "act", t, obs))
        if isinstance(r1, Unavailable):
            self._set_pending(t, "act", ["guesser1"])
            return
        self.decision_count += 1
        audit["decisions"] += 1
        adm1 = A.admit_guesser1(
            r1,
            pre_secret=pre_secret,
            pre_contact=pre_contact,
            max_chars=self.clue_max,
            joint_live=False,
            direct_allowed=True,
            clue_allowed=self.offense_condition != "direct_only",
        )
        audit["guesser1"] = {"valid": adm1.valid, "canonical": adm1.canonical, "reason": adm1.reason}

        if not adm1.valid:
            self.public_history.append({"turn": t, "type": "invalid_action", "seat": "guesser1"})
            self.private_history["guesser1"].append(
                {"turn": t, "action": "invalid", "validity": "invalid", "reason": adm1.reason}
            )
            audit.update(result="invalid_guesser1", opened=[], emissions=[])
            self._finish_turn(t)
            audit["prefix_after"] = self.prefix
            audit["secret_candidates_after"] = len(self.secret_candidates())
            self.audit.append(audit)
            return

        if adm1.canonical["action"] == "direct":
            w = adm1.canonical["word"]
            event: dict[str, Any] = {"turn": t, "type": "direct", "seat": "guesser1", "word": w}
            self.private_history["guesser1"].append(
                {"turn": t, "action": "direct", "word": w, "validity": "valid"}
            )
            audit.update(opened=[{"seat": "guesser1", "word": w}], emissions=[w])
            if w == self._secret:
                self._win(t, TERMINAL_UTTERANCE, ["direct"])
                event.update(result="won", terminal_reason=TERMINAL_UTTERANCE, hit_sources=["direct"])
                audit["result"] = "won"
            else:
                self.used_words.add(w)
                event["result"] = "no_prefix"
                audit["result"] = "wrong_direct"
            event["prefix_after"] = self.prefix
            self.public_history.append(event)
            self._finish_turn(t)
            audit["prefix_after"] = self.prefix
            audit["secret_candidates_after"] = len(self.secret_candidates())
            self.audit.append(audit)
            return

        # ---------------- clue round
        w1 = adm1.canonical["word"]
        clue = adm1.canonical["clue"]
        M = mentioned_words(clue, self.vocab_union)
        audit.update(w1=w1, clue=clue, mentions=sorted(M))
        g1_priv: dict[str, Any] = {
            "turn": t,
            "action": "clue",
            "committed_word": w1,
            "clue": clue,
            "validity": "valid",
        }
        self.private_history["guesser1"].append(g1_priv)

        if (
            self.protocol.initial_response_collection == "early_stop_on_public_clue_hit"
            and self._secret in M
        ):
            self._win(t, TERMINAL_UTTERANCE, ["clue"])
            self.public_history.append(
                {
                    "turn": t,
                    "type": "clue_round",
                    "clue": clue,
                    "blocklist": [],
                    "blocklist_collected": False,
                    "opened_guesses": [],
                    "prefix_after": self.prefix,
                    "result": "won",
                    "terminal_reason": TERMINAL_UTTERANCE,
                    "hit_sources": ["clue"],
                }
            )
            audit.update(result="won", hit_sources=["clue"], opened=[], emissions=sorted(M))
            self.audit.append(audit)
            return

        obs2 = self.observation("guesser2", "respond", t, current_clue=clue)
        obsd = self.observation("defender", "block", t, current_clue=clue)
        r2, rd = await asyncio.gather(
            decide(self._spec("guesser2", "respond", t, obs2)),
            decide(self._spec("defender", "block", t, obsd)),
        )
        missing = [s for s, r in (("guesser2", r2), ("defender", rd)) if isinstance(r, Unavailable)]

        adm2 = None
        admd = None
        if not isinstance(r2, Unavailable):
            self.decision_count += 1
            audit["decisions"] += 1
            adm2 = A.admit_guesser2(r2, pre_contact=pre_contact, joint_live=self.joint_live)
            self._record_diag(t, "guesser2", adm2, w1)
        if not isinstance(rd, Unavailable):
            self.decision_count += 1
            audit["decisions"] += 1
            admd = A.admit_defender(rd, contact_vocab=self.v_contact.word_set, joint_live=self.joint_live)
            self._record_diag(t, "defender", admd, w1)

        if missing:
            # Known public evidence can still prove a win (Section 6.5).
            sources = []
            if self._secret in M:
                sources.append("clue")
            if admd is not None and self._secret in admd.canonical["words"]:
                sources.append("blocklist")
            if sources:
                self.collection_status = "incomplete"
                self.hit_source_completeness = "partial"
                self._win(t, TERMINAL_UTTERANCE, sources)
                self.public_history.append(
                    {
                        "turn": t,
                        "type": "clue_round",
                        "clue": clue,
                        "blocklist": admd.canonical["words"] if admd else None,
                        "blocklist_collected": admd is not None,
                        "opened_guesses": [],
                        "prefix_after": self.prefix,
                        "result": "won",
                        "terminal_reason": TERMINAL_UTTERANCE,
                        "hit_sources": sources,
                    }
                )
                audit.update(
                    result="won",
                    hit_sources=sources,
                    missing=missing,
                    guesser2=_adm_audit(adm2),
                    defender=_adm_audit(admd),
                )
                self.audit.append(audit)
                return
            self._set_pending(t, "sealed_responses", missing)
            return

        assert adm2 is not None and admd is not None
        w2 = adm2.canonical["word"]  # None for pass
        H = frozenset(admd.canonical["words"])
        blocklist = admd.canonical["words"]
        audit.update(
            guesser2=_adm_audit(adm2),
            defender=_adm_audit(admd),
            w2=w2,
            blocklist=blocklist,
            block_size=len(H),
            block_fresh_secret_candidates=len(H & pre_secret),
            block_overlap_with_clue=len(H & M),
        )

        g2_priv: dict[str, Any] = {
            "turn": t,
            "action": adm2.canonical["action"],
            "committed_word": w2,
            "validity": "valid" if adm2.valid else "invalid",
        }
        if not adm2.valid:
            g2_priv["reason"] = adm2.reason
            g2_priv["canonical_action"] = "pass"
        self.private_history["guesser2"].append(g2_priv)
        d_priv: dict[str, Any] = {
            "turn": t,
            "validity": "valid" if admd.valid else "invalid",
            "canonical_blocklist": blocklist,
        }
        if not admd.valid:
            d_priv["reason"] = admd.reason
        self.private_history["defender"].append(d_priv)

        blocked1 = w1 in H
        blocked2 = (w2 in H) if w2 is not None else None
        audit.update(blocked_guesser1=blocked1, blocked_guesser2=blocked2)

        # A public hit in clue or blocklist ends the round before any choice.
        pre_hits = []
        if self._secret in M:
            pre_hits.append("clue")
        if self._secret in H:
            pre_hits.append("blocklist")
        opened: list[tuple[str, str]] = []
        choice_actor = None
        choice = None
        choice_valid = None
        if not pre_hits:
            if w2 is None:
                if not blocked1:
                    opened = [("guesser1", w1)]
            elif not blocked1 and not blocked2:
                opened = [("guesser1", w1), ("guesser2", w2)]
            elif blocked1 and blocked2:
                opened = []
            else:
                if w1 == w2:
                    raise EngineInvariantError("exactly-one-blocked with equal commitments")
                choice_actor = "guesser2" if blocked1 else "guesser1"
                actor_word = w2 if blocked1 else w1
                obsc = self.observation(
                    choice_actor,
                    "choice",
                    t,
                    current_clue=clue,
                    published_blocklist=blocklist,
                    own_committed_word=actor_word,
                    partner_word_blocked=True,
                )
                rc = await decide(self._spec(choice_actor, "choice", t, obsc))
                if isinstance(rc, Unavailable):
                    audit["choice_actor"] = choice_actor
                    self._set_pending(t, "choice", [choice_actor])
                    return
                self.decision_count += 1
                audit["decisions"] += 1
                admc = A.admit_choice(rc)
                choice = admc.canonical["action"]
                choice_valid = admc.valid
                entry = {"offered": True, "partner_word_blocked": True, "choice": choice,
                         "validity": "valid" if admc.valid else "invalid"}
                if not admc.valid:
                    entry["reason"] = admc.reason
                (g1_priv if choice_actor == "guesser1" else g2_priv)["conditional_choice"] = entry
                if choice == "reveal":
                    opened = [(choice_actor, actor_word)]

        opened_words = {w for _, w in opened}
        emissions = set(M) | set(H) | opened_words
        target_hit = self._secret in emissions
        hit_sources = list(pre_hits)
        for seat, w in opened:
            if w == self._secret:
                hit_sources.append(f"{seat}_opened")
        registered_match = w2 is not None and w1 == w2
        intended_covered = blocked1
        fresh = w1 not in pre_used and w1 not in M
        both_opened = len(opened) == 2
        contact = both_opened and registered_match and fresh
        covered_match = registered_match and intended_covered
        blocked_contact = (not target_hit) and covered_match and fresh
        audit.update(
            choice_actor=choice_actor,
            choice=choice,
            choice_valid=choice_valid,
            opened=[{"seat": s, "word": w} for s, w in opened],
            emissions=sorted(emissions),
            target_hit=target_hit,
            hit_sources=hit_sources,
            registered_match=registered_match,
            intended_covered=intended_covered,
            covered_match=covered_match,
            fresh_for_contact=fresh,
            contact=bool(contact and not target_hit),
            blocked_contact=blocked_contact,
        )

        event: dict[str, Any] = {
            "turn": t,
            "type": "clue_round",
            "clue": clue,
            "blocklist": blocklist,
            "opened_guesses": [{"seat": s, "word": w} for s, w in opened],
        }
        if target_hit:
            self._win(t, TERMINAL_UTTERANCE, hit_sources)
            event.update(result="won", terminal_reason=TERMINAL_UTTERANCE, hit_sources=hit_sources)
            audit["result"] = "won"
        else:
            self.used_words |= emissions
            if contact:
                self.prefix = self.prefix + self._secret[len(self.prefix)]
                if self.prefix == self._secret:
                    self._win(t, TERMINAL_PREFIX, [])
                    event.update(result="won", terminal_reason=TERMINAL_PREFIX, hit_sources=[])
                    audit["result"] = "won_prefix_completed"
                else:
                    self._display_prefix(turn=t)
                    event["result"] = "prefix_extended"
                    audit["result"] = "prefix_extended"
            else:
                event["result"] = "no_prefix"
                audit["result"] = "no_prefix"
        event["prefix_after"] = self.prefix
        self.public_history.append(event)
        self._finish_turn(t)
        audit["prefix_after"] = self.prefix
        audit["secret_candidates_after"] = (
            len(self.secret_candidates()) if not self.outcome_status == OUTCOME_SOLVED else None
        )
        self.audit.append(audit)

    def _record_diag(self, t: int, seat: str, adm: A.Admission, w1: str) -> None:
        if self.joint_live:
            self.diagnostics.append(
                {
                    "turn": t,
                    "seat": seat,
                    "present": adm.diagnostics_present,
                    "payload": adm.diagnostics,
                    "intended_word": w1,
                }
            )

    # --------------------------------------------------------------- summary
    def summary(self) -> dict:
        """Referee-side game summary (contains the secret)."""
        return {
            "game_id": self.game_id,
            "secret": self._secret,
            "initial_prefix": self.initial_prefix,
            "final_prefix": self.prefix,
            "turn_limit": self.turn_limit,
            "turns_used": self.turns_used,
            "outcome_status": self.outcome_status,
            "terminal_reason": self.terminal_reason,
            "collection_status": self.collection_status,
            "winning_turn": self.winning_turn,
            "hit_sources": self.hit_sources,
            "hit_source_completeness": self.hit_source_completeness,
            "pending": self.pending,
            "initial_secret_candidate_count": len(self.initial_secret_candidates),
            "final_secret_candidate_count": len(self.secret_candidates()),
            "decision_count": self.decision_count,
            "offense_condition": self.offense_condition,
        }


def _adm_audit(adm: A.Admission | None) -> dict | None:
    if adm is None:
        return None
    return {"valid": adm.valid, "canonical": adm.canonical, "reason": adm.reason}
