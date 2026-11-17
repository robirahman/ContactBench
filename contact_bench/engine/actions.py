"""Gameplay action schemas and admission (spec Sections 4.4, 6.1, 6.5, 8.3).

Admission validates a submission against public rules *before* any of its
content is broadcast or tested against the secret.  Validity never depends on
whether a word equals the secret.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..lexicon import normalize_word

SEATS = ("guesser1", "guesser2", "defender")
PHASES = ("act", "respond", "block", "choice")

ASCII_WS = " \t\n\r\x0b\x0c"


@dataclass(frozen=True)
class Admission:
    """Result of admitting one gameplay decision.

    ``canonical`` is the canonical gameplay action actually applied (an
    invalid receiver output becomes pass, an invalid blocklist becomes empty,
    an invalid choice becomes cancel).  ``reason`` is a generic, non-echoing
    description suitable for the owner's private history.
    """

    valid: bool
    canonical: dict
    reason: str | None = None
    diagnostics: Any = None  # joint-live diagnostic payload (validated separately)
    diagnostics_present: bool = False


def _load(raw: Any) -> tuple[Any, str | None]:
    if isinstance(raw, (dict, list)):
        return raw, None
    if raw is None:
        return None, "empty response"
    if not isinstance(raw, str):
        return None, "response is not text"
    try:
        return json.loads(raw), None
    except (json.JSONDecodeError, RecursionError):
        return None, "response is not valid JSON"


def unwrap(raw: Any, joint_live: bool) -> tuple[Any, Any, bool, str | None]:
    """Parse JSON and, in joint-live mode, split the gameplay/diagnostics envelope.

    Returns (gameplay_object, diagnostics, diagnostics_present, error).
    """
    obj, err = _load(raw)
    if err:
        return None, None, False, err
    if not joint_live:
        return obj, None, False, None
    if not isinstance(obj, dict) or set(obj) != {"gameplay", "diagnostics"}:
        return None, None, False, "joint-live envelope must have exactly gameplay and diagnostics"
    return obj["gameplay"], obj["diagnostics"], True, None


def _exact_keys(obj: Any, keys: set[str]) -> str | None:
    if not isinstance(obj, dict):
        return "action must be a JSON object"
    if set(obj) != keys:
        return f"action must have exactly the fields {sorted(keys)}"
    return None


def validate_clue_text(clue: Any, max_chars: int) -> tuple[str | None, str | None]:
    if not isinstance(clue, str):
        return None, "clue must be a string"
    s = clue.strip(ASCII_WS)
    if not s:
        return None, "clue is empty after trimming"
    if any(not (0x20 <= ord(c) <= 0x7E) for c in s):
        return None, "clue must be printable ASCII"
    if len(s) > max_chars:
        return None, f"clue exceeds {max_chars} characters"
    return s, None


INVALID_G1 = {"action": "invalid"}


def admit_guesser1(
    raw: Any,
    *,
    pre_secret: frozenset[str],
    pre_contact: frozenset[str],
    max_chars: int,
    joint_live: bool = False,
    direct_allowed: bool = True,
    clue_allowed: bool = True,
) -> Admission:
    obj, diag, has_diag, err = unwrap(raw, joint_live)
    if err:
        return Admission(False, INVALID_G1, err)
    err = _exact_keys(obj, {"action", "word", "clue"})
    if err:
        return Admission(False, INVALID_G1, err, diag, has_diag)
    action = obj["action"]
    word = normalize_word(obj["word"])
    if action == "direct":
        if not direct_allowed:
            return Admission(False, INVALID_G1, "direct actions are not allowed in this condition", diag, has_diag)
        if obj["clue"] is not None:
            return Admission(False, INVALID_G1, "direct action requires clue null", diag, has_diag)
        if word is None or word not in pre_secret:
            return Admission(False, INVALID_G1, "direct word is not a current secret candidate", diag, has_diag)
        return Admission(True, {"action": "direct", "word": word, "clue": None}, None, diag, has_diag)
    if action == "clue":
        if not clue_allowed:
            return Admission(False, INVALID_G1, "clue actions are not allowed in this condition", diag, has_diag)
        if word is None or word not in pre_contact:
            return Admission(False, INVALID_G1, "intended word is not a current contact candidate", diag, has_diag)
        clue, cerr = validate_clue_text(obj["clue"], max_chars)
        if cerr:
            return Admission(False, INVALID_G1, cerr, diag, has_diag)
        return Admission(True, {"action": "clue", "word": word, "clue": clue}, None, diag, has_diag)
    return Admission(False, INVALID_G1, "action must be clue or direct", diag, has_diag)


CANONICAL_PASS = {"action": "pass", "word": None}


def admit_guesser2(raw: Any, *, pre_contact: frozenset[str], joint_live: bool = False) -> Admission:
    obj, diag, has_diag, err = unwrap(raw, joint_live)
    if err:
        return Admission(False, CANONICAL_PASS, err)
    err = _exact_keys(obj, {"action", "word"})
    if err:
        return Admission(False, CANONICAL_PASS, err, diag, has_diag)
    if obj["action"] == "pass":
        if obj["word"] is not None:
            return Admission(False, CANONICAL_PASS, "pass requires word null", diag, has_diag)
        return Admission(True, dict(CANONICAL_PASS), None, diag, has_diag)
    if obj["action"] == "guess":
        w = normalize_word(obj["word"])
        if w is None or w not in pre_contact:
            return Admission(False, CANONICAL_PASS, "word is not a current contact candidate", diag, has_diag)
        return Admission(True, {"action": "guess", "word": w}, None, diag, has_diag)
    return Admission(False, CANONICAL_PASS, "action must be guess or pass", diag, has_diag)


EMPTY_BLOCK = {"action": "block", "words": []}


def admit_defender(raw: Any, *, contact_vocab: frozenset[str], joint_live: bool = False) -> Admission:
    obj, diag, has_diag, err = unwrap(raw, joint_live)
    if err:
        return Admission(False, dict(EMPTY_BLOCK), err)
    err = _exact_keys(obj, {"action", "words"})
    if err:
        return Admission(False, dict(EMPTY_BLOCK), err, diag, has_diag)
    if obj["action"] != "block" or not isinstance(obj["words"], list):
        return Admission(False, dict(EMPTY_BLOCK), "action must be block with a words array", diag, has_diag)
    out: list[str] = []
    seen: set[str] = set()
    for entry in obj["words"]:
        w = normalize_word(entry)
        if w is None or w not in contact_vocab:
            return Admission(False, dict(EMPTY_BLOCK), "blocklist entry is not a dictionary word", diag, has_diag)
        if w not in seen:
            seen.add(w)
            out.append(w)
    # Canonical blocklist is sorted for stable public display.
    return Admission(True, {"action": "block", "words": sorted(out)}, None, diag, has_diag)


def admit_choice(raw: Any) -> Admission:
    obj, _, _, err = unwrap(raw, False)
    if err:
        return Admission(False, {"action": "cancel"}, err)
    err = _exact_keys(obj, {"action"})
    if err:
        return Admission(False, {"action": "cancel"}, err)
    if obj["action"] in ("reveal", "cancel"):
        return Admission(True, {"action": obj["action"]})
    return Admission(False, {"action": "cancel"}, "action must be reveal or cancel")


# JSON Schemas supplied to providers (structured output).  Provider schema
# enforcement does not replace the local validation above.

def guesser1_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["clue", "direct"]},
            "word": {"type": "string"},
            "clue": {"type": ["string", "null"]},
        },
        "required": ["action", "word", "clue"],
        "additionalProperties": False,
    }


def guesser2_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["guess", "pass"]},
            "word": {"type": ["string", "null"]},
        },
        "required": ["action", "word"],
        "additionalProperties": False,
    }


def defender_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["block"]},
            "words": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action", "words"],
        "additionalProperties": False,
    }


def choice_schema() -> dict:
    return {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["reveal", "cancel"]}},
        "required": ["action"],
        "additionalProperties": False,
    }


def forecast_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "word": {"type": "string"},
                        "probability": {"type": "number"},
                    },
                    "required": ["word", "probability"],
                    "additionalProperties": False,
                },
            },
            "other_mass": {"type": "number"},
        },
        "required": ["entries", "other_mass"],
        "additionalProperties": False,
    }


def joint_schema(gameplay: dict, seat: str) -> dict:
    nullable_forecast = {"anyOf": [forecast_schema(), {"type": "null"}]}
    diag_props = {"intended_word_forecast": nullable_forecast}
    if seat in ("guesser2", "defender"):
        diag_props["commitment_match_forecast"] = nullable_forecast
    return {
        "type": "object",
        "properties": {
            "gameplay": gameplay,
            "diagnostics": {
                "type": "object",
                "properties": diag_props,
                "required": sorted(diag_props),
                "additionalProperties": False,
            },
        },
        "required": ["gameplay", "diagnostics"],
        "additionalProperties": False,
    }


def schema_for(seat: str, phase: str, joint_live: bool = False) -> tuple[str, dict]:
    if phase == "choice":
        return "contact_choice", choice_schema()
    base = {
        "guesser1": ("contact_guesser1", guesser1_schema),
        "guesser2": ("contact_guesser2", guesser2_schema),
        "defender": ("contact_defender", defender_schema),
    }[seat]
    name, fn = base
    schema = fn()
    if joint_live and seat in ("guesser2", "defender"):
        return name + "_joint", joint_schema(schema, seat)
    return name, schema
