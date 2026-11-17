"""Seat observations built from an explicit allowlist of fields (spec 5.2).

Observations are never derived by redacting a complete referee state.  Phase
scheduling, request identifiers, timing, audit counters and hidden branch
labels never enter them.
"""

from __future__ import annotations

from typing import Any


ALLOWED_EXTRAS = {
    "guesser1": {
        "act": set(),
        "choice": {"current_clue", "published_blocklist", "own_committed_word", "partner_word_blocked"},
    },
    "guesser2": {
        "respond": {"current_clue"},
        "choice": {"current_clue", "published_blocklist", "own_committed_word", "partner_word_blocked"},
    },
    "defender": {"block": {"current_clue"}},
}


class ObservationError(ValueError):
    pass


def build_observation(
    *,
    public: dict,
    seat: str,
    phase: str,
    turn: int,
    clue_max_characters: int,
    secret_candidates: list[str],
    contact_candidates: list[str],
    own_private_history: list[dict],
    secret: str | None,
    offense_condition: str,
    joint_live: bool,
    protocol_version: str = "contact-v0.5",
    dictionary_access: str = "full_candidate_lists",
    dictionary_identity: dict | None = None,
    **extras: Any,
) -> dict:
    if seat not in ALLOWED_EXTRAS or phase not in ALLOWED_EXTRAS[seat]:
        raise ObservationError(f"no observation defined for seat={seat} phase={phase}")
    allowed = ALLOWED_EXTRAS[seat][phase]
    unexpected = set(extras) - allowed
    if unexpected:
        raise ObservationError(f"fields {sorted(unexpected)} not permitted for {seat}/{phase}")
    if (secret is not None) != (seat == "defender"):
        raise ObservationError("only the defender receives the labeled secret")
    obs: dict[str, Any] = {
        "protocol": protocol_version,
        "role": seat,
        "phase": phase,
        "turn": turn,
        "turn_limit": public["turn_limit"],
        "turns_used_before_this_turn": public["turns_used"],
        "clue_max_characters": clue_max_characters,
        "prefix": public["prefix"],
        "used_words": list(public["used_words"]),
        "public_history": list(public["public_history"]),
        "own_private_history": list(own_private_history),
        "offense_condition": offense_condition,
        "forecast_reports_requested": bool(joint_live and seat in ("guesser2", "defender") and phase != "choice"),
    }
    if dictionary_access == "full_candidate_lists":
        obs["secret_candidates"] = list(secret_candidates)
        obs["contact_candidates"] = list(contact_candidates)
    else:
        # Closed-book and lookup-tool conditions: identity only, no lists or counts.
        obs["dictionary_access"] = dictionary_access
        obs["dictionary"] = dict(dictionary_identity or {})
    if seat == "defender":
        obs["secret"] = secret
    for k in sorted(allowed):
        if k in extras:
            obs[k] = extras[k]
    return obs
