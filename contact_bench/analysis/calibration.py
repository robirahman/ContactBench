"""Calibration of live forecast forks (forecast mode ``fork``).

Metrics per model and forecast target:
- intended_word@guesser2 / intended_word@defender: distribution over Guesser 1's
  committed word W (proper Brier 2q(W)-Σq², log score, q(W), top-1 accuracy).
- receiver_word@guesser1: Guesser 1's distribution over what Guesser 2 registers.
- block_probability@guesser1: P(Defender blocks W) (binary Brier, log score).
Each also gets a reliability table and expected calibration error (ECE):
top-1 confidence vs top-1 correctness for distributions, p vs outcome for the
binary target.  Invalid reports score -1 in the overall Brier mean; valid-only
means and coverage are reported separately.  Unavailable (infrastructure)
forks are counted but never scored.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

BINS = 10


def _reliability(pairs: list[tuple[float, float]]) -> tuple[list[dict], float | None]:
    """pairs: (confidence, correctness in [0, 1]; fractional for tied modes)."""
    if not pairs:
        return [], None
    bins: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for p, y in pairs:
        bins[min(BINS - 1, int(p * BINS))].append((p, y))
    table = []
    ece = 0.0
    for b in sorted(bins):
        xs = bins[b]
        conf = mean(p for p, _ in xs)
        freq = mean(float(y) for _, y in xs)
        ece += len(xs) / len(pairs) * abs(conf - freq)
        table.append({"bin": f"{b / BINS:.1f}-{(b + 1) / BINS:.1f}", "n": len(xs),
                      "mean_confidence": conf, "observed_frequency": freq})
    return table, ece


def _summarize(items: list[dict], binary: bool) -> dict:
    sched = len(items)
    unavailable = sum(1 for s in items if s is None)
    obs = [s for s in items if s is not None]
    labeled = [s for s in obs if s.get("brier") is not None]
    valid = [s for s in labeled if s.get("valid")]
    out: dict[str, Any] = {
        "scheduled": sched,
        "unavailable": unavailable,
        "observed": len(obs),
        "observed_with_answer": len(labeled),
        "valid": len(valid),
        "coverage_valid_per_observed": len([s for s in obs if s.get("valid")]) / len(obs) if obs else None,
        "mean_brier_invalid_as_minus_one": mean(s["brier"] for s in labeled) if labeled else None,
        "mean_brier_valid_only": mean(s["brier"] for s in valid) if valid else None,
        "mean_log_valid_nonzero": mean(s["log"] for s in valid if s.get("log") is not None)
        if any(s.get("log") is not None for s in valid) else None,
        "zero_probability_failures": sum(1 for s in valid if s.get("zero_probability")),
    }
    if binary:
        pairs = [(s["p"], s["y"]) for s in valid]
        table, ece = _reliability(pairs)
        out.update(mean_p=mean(p for p, _ in pairs) if pairs else None,
                   base_rate=mean(1.0 if y else 0.0 for _, y in pairs) if pairs else None,
                   ece=ece, reliability=table)
    else:
        # Every valid report has a top-1 confidence (ties included), so top-1
        # accuracy and ECE are computed over the same reports.
        pairs = [(s["top_probability"], float(s["top_correct"])) for s in valid]
        table, ece = _reliability(pairs)
        out.update(mean_q_truth=mean(s["q_truth"] for s in valid) if valid else None,
                   top1_accuracy=mean(float(s["top_correct"]) for s in valid) if valid else None,
                   mean_top1_confidence=mean(p for p, _ in pairs) if pairs else None,
                   top1_ece=ece, reliability=table)
    return out


def forecast_calibration(records: list[dict]) -> dict:
    """``records``: game records (with a ``forecasts`` list) from a fork-mode run."""
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for rec in records:
        for f in rec.get("forecasts") or []:
            m = f["model_id"]
            sc = f.get("scores")
            if f["kind"] == "intended_word":
                groups[(m, f"intended_word@{f['seat']}")].append(sc["intended_word"] if sc else None)
            else:
                groups[(m, "receiver_word@guesser1")].append(sc["receiver_word"] if sc else None)
                groups[(m, "block_probability@guesser1")].append(sc["block_probability"] if sc else None)
    out: dict[str, dict] = defaultdict(dict)
    for (m, target), items in sorted(groups.items()):
        out[m][target] = _summarize(items, binary=target.startswith("block_probability"))
    return dict(out)


def render_calibration(cal: dict) -> str:
    if not cal:
        return ""
    lines = ["## Forecast calibration (live transcript forks)\n",
             "| Model | Target | Valid / scheduled | Brier (invalid = -1) | Brier (valid only) | q(true) or mean p | Top-1 acc. or base rate | ECE |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]

    def f(x):
        return "—" if x is None else f"{x:.3f}"

    for m, targets in cal.items():
        for t, s in targets.items():
            binary = t.startswith("block_probability")
            lines.append(
                f"| {m} | {t} | {s['valid']}/{s['scheduled']} | {f(s['mean_brier_invalid_as_minus_one'])} | "
                f"{f(s['mean_brier_valid_only'])} | {f(s['mean_p'] if binary else s['mean_q_truth'])} | "
                f"{f(s['base_rate'] if binary else s['top1_accuracy'])} | {f(s['ece'] if binary else s['top1_ece'])} |")
    lines.append("\nBrier scores are higher-is-better (1 = perfect). For distributions, ECE compares top-1 "
                 "confidence with top-1 correctness; for block probability it compares p with the observed "
                 "block rate.\n")
    return "\n".join(lines) + "\n"
