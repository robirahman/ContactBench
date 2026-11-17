"""Live forecast forks (forecast mode ``fork``).

After a model makes a gameplay decision, its transcript is branched: the
model's own final answer stays in place and a new private user turn asks for
a probability report.  The branch never flows back into the game, so gameplay
prompts are identical to forecast mode ``off``.

Fork kinds
- ``intended_word`` (Guesser 2 after responding; Defender after blocking):
  distribution over Guesser 1's committed intended word W.
- ``guesser1`` (Guesser 1 after a valid clue action):
  ``receiver_word_forecast`` — distribution over the word Guesser 2 registers
  (or ``PASS``), and ``block_probability`` — P(Defender's blocklist covers W).

Answer keys come from the referee audit after the turn resolves.  These are
elicited reports, not token log-probabilities (which the APIs do not expose
uniformly; Anthropic exposes none).
"""

from __future__ import annotations

import bisect
import json
import math
from typing import Any

from ..engine.actions import forecast_schema
from ..lexicon import Lexicon
from .scoring import ForecastError, Support, brier, log_score, parse_sparse

PASS = "PASS"
FORK_PROMPT_VERSION = "forecast-fork-v1"

_SUPPORT_TEXT = (
    "The support is every contact-eligible word at the START of this turn: dictionary words that begin with the "
    "prefix {prefix!r}, are longer than it, and were not already used before this turn{extra}."
)

INTENDED_PROMPT = """PRIVATE FORECAST — a counterfactual branch of your transcript. Nothing you write here is said in the game, shown to any other player, or shown to you later, and it cannot change your action above.

Guesser 1 privately registered an intended word together with the clue {clue!r}. Report your probability distribution over Guesser 1's intended word.
""" + _SUPPORT_TEXT + """
Reply with exactly {{"entries": [{{"word": w, "probability": p}}, ...at most {k} entries], "other_mass": m}}. Probabilities must sum to 1; every unlisted support word receives an equal share of other_mass. Listing a word outside the support makes the whole report invalid."""

GUESSER1_PROMPT = """PRIVATE FORECAST — a counterfactual branch of your transcript. Nothing you write here is said in the game, shown to any other player, or shown to you later, and it cannot change your action above.

You registered the intended word {w1!r} with the clue {clue!r}. Guesser 2 and the Defender are now responding, sealed.
1. receiver_word_forecast: your probability distribution over the word Guesser 2 registers in response to your clue. Use the label "PASS" for a pass. """ + _SUPPORT_TEXT + """
2. block_probability: the probability that the Defender's blocklist includes your intended word {w1!r}.
Reply with exactly {{"receiver_word_forecast": {{"entries": [{{"word": w, "probability": p}}, ...at most {k} entries], "other_mass": m}}, "block_probability": p}}. Probabilities in the distribution must sum to 1; unlisted support words share other_mass equally; a word outside the support (other than "PASS") makes the report invalid."""


def fork_schema(kind: str) -> tuple[str, dict]:
    if kind == "intended_word":
        return "contact_fork_intended_word", forecast_schema()
    if kind == "guesser1":
        return "contact_fork_guesser1", {
            "type": "object",
            "properties": {
                "receiver_word_forecast": forecast_schema(),
                "block_probability": {"type": "number"},
            },
            "required": ["block_probability", "receiver_word_forecast"],
            "additionalProperties": False,
        }
    raise ValueError(kind)


def fork_prompt(kind: str, *, prefix: str, clue: str, w1: str | None = None, k: int = 20,
                pass_label: bool = False) -> str:
    extra = ' (plus the special label "PASS")' if pass_label else ""
    if kind == "intended_word":
        return INTENDED_PROMPT.format(clue=clue, prefix=prefix, extra=extra, k=k)
    return GUESSER1_PROMPT.format(clue=clue, w1=w1, prefix=prefix, extra=extra, k=k)


# --------------------------------------------------------------- support

def support_descriptor(prefix: str, used_view: dict, size: int) -> dict:
    """Compact, referee-side description of the pre-turn contact support."""
    return {"prefix": prefix, "used_words": list(used_view.get("used_words", [])),
            "used_ranges": [list(r) for r in used_view.get("used_ranges", []) or []], "size": size}


def build_support(desc: dict, lexicon: Lexicon, special: tuple[str, ...] = ()) -> Support:
    prefix = desc["prefix"]
    used = set(desc["used_words"])
    ranges = sorted(tuple(r) for r in desc["used_ranges"])
    starts = [a for a, _ in ranges]

    def in_range(w: str) -> bool:
        i = bisect.bisect_right(starts, w) - 1
        return i >= 0 and w <= ranges[i][1]

    def contains(w: str) -> bool:
        return (w in lexicon and w.startswith(prefix) and len(w) > len(prefix)
                and w not in used and not in_range(w))

    return Support(contains, desc["size"], special)


# --------------------------------------------------------------- scoring

def _dist_scores(report: Any, support: Support, truth: str | None, *, max_entries: int, tolerance: float,
                 invalid_score: float) -> dict:
    out: dict[str, Any] = {"support_size": len(support)}
    try:
        fc = parse_sparse(report, support, max_entries=max_entries, tolerance=tolerance)
    except ForecastError as e:
        out.update(valid=False, error=str(e), brier=invalid_score if truth is not None else None)
        return out
    top = max(fc.listed, key=fc.listed.get) if fc.listed else None
    top_p = fc.listed[top] if top else None
    # If the residual share per unlisted word exceeds the top listed word, the
    # report's mode is an unlisted word; record top as None in that case.
    rest = len(support) - len(fc.listed)
    if top is not None and rest > 0 and fc.other_mass / rest > top_p:
        top, top_p = None, fc.other_mass / rest
    out.update(valid=True, listed=len(fc.listed), other_mass=fc.other_mass, top=top, top_probability=top_p)
    if truth is not None:
        ls, zero = log_score(fc, truth)
        out.update(brier=brier(fc, truth), log=None if zero else ls, zero_probability=zero,
                   q_truth=fc.prob(truth), top_correct=(top == truth))
    return out


def _binary_scores(p: Any, y: bool | None, invalid_score: float) -> dict:
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
        return {"valid": False, "error": "block_probability must be a number in [0,1]",
                "brier": invalid_score if y is not None else None}
    out: dict[str, Any] = {"valid": True, "p": float(p)}
    if y is not None:
        q = p if y else 1 - p
        out.update(y=bool(y), brier=1 - 2 * (p - (1.0 if y else 0.0)) ** 2,
                   log=math.log(q) if q > 0 else None, zero_probability=q <= 0)
    return out


def score_fork(record: dict, audit_turn: dict | None, lexicon: Lexicon, *, max_entries: int = 20,
               tolerance: float = 1e-6, invalid_score: float = -1.0) -> dict:
    """Attach answer keys and proper scores to one fork record."""
    out = dict(record)
    raw = record.get("raw_output")
    if record.get("status") != "ok":
        out["scores"] = None
        return out
    try:
        obj = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        obj = None
    t = audit_turn or {}
    if record["kind"] == "intended_word":
        truth = t.get("w1")
        out["answer"] = truth
        out["scores"] = {"intended_word": _dist_scores(
            obj, build_support(record["support"], lexicon), truth,
            max_entries=max_entries, tolerance=tolerance, invalid_score=invalid_score)}
        return out
    # guesser1 fork
    g2 = (t.get("guesser2") or {}).get("canonical")
    recv_truth = None if g2 is None else (g2.get("word") if g2.get("action") == "guess" else PASS)
    blocked = t.get("blocked_guesser1") if t.get("defender") is not None else None
    out["answer"] = {"receiver_word": recv_truth, "intended_blocked": blocked}
    if not isinstance(obj, dict) or set(obj) != {"receiver_word_forecast", "block_probability"}:
        bad = {"valid": False, "error": "report must have receiver_word_forecast and block_probability",
               "brier": invalid_score}
        out["scores"] = {"receiver_word": dict(bad), "block_probability": dict(bad)}
        return out
    sup = build_support(record["support"], lexicon, special=(PASS,))
    out["scores"] = {
        "receiver_word": _dist_scores(obj["receiver_word_forecast"], sup, recv_truth, max_entries=max_entries,
                                      tolerance=tolerance, invalid_score=invalid_score),
        "block_probability": _binary_scores(obj["block_probability"], blocked, invalid_score),
    }
    return out


def label_game_forks(records: list[dict], audit: list[dict], lexicon: Lexicon, **kw) -> list[dict]:
    by_turn = {t["turn"]: t for t in audit}
    return [score_fork(r, by_turn.get(r["turn"]), lexicon, **kw) for r in sorted(records, key=lambda r: r["fork_id"])]
