"""Forecast diagnostic tests (spec 18.3)."""

import math

import pytest

from contact_bench.forecasts.scoring import (
    NO_MATCH, ForecastError, brier, dense_brier, log_score, match_label, parse_sparse,
)

SUPPORT = ["candle", "candy", "canoe", "cable", "camera"]


def test_sparse_tail_equals_dense():
    fc = parse_sparse({"entries": [{"word": "candle", "probability": 0.6}, {"word": "candy", "probability": 0.2}],
                       "other_mass": 0.2}, SUPPORT)
    dense = fc.dense(SUPPORT)
    for truth in SUPPORT:
        assert math.isclose(brier(fc, truth), dense_brier(dense, truth))
    # omitted truth receives other_mass/(M-h), not all OTHER mass
    assert math.isclose(fc.prob("canoe"), 0.2 / 3)


def test_uniform_and_extremes():
    u = parse_sparse({"entries": [], "other_mass": 1.0}, SUPPORT)
    assert math.isclose(brier(u, "candy"), 1 / 5)
    sure = parse_sparse({"entries": [{"word": "candy", "probability": 1}], "other_mass": 0}, SUPPORT)
    assert brier(sure, "candy") == 1 and brier(sure, "candle") == -1


@pytest.mark.parametrize("bad", [
    {"entries": [{"word": "zebra", "probability": 1}], "other_mass": 0},
    {"entries": [{"word": "candy", "probability": 0.5}, {"word": "candy", "probability": 0.5}], "other_mass": 0},
    {"entries": [{"word": "candy", "probability": float("nan")}], "other_mass": 0},
    {"entries": [{"word": "candy", "probability": -0.1}], "other_mass": 1.1},
    {"entries": [{"word": "candy", "probability": 0.5}], "other_mass": 0.3},
    {"entries": [], "other_mass": 1, "extra": 1},
])
def test_invalid_reports_rejected(bad):
    with pytest.raises(ForecastError):
        parse_sparse(bad, SUPPORT)


def test_full_support_requires_zero_residual_and_small_tolerance_renormalizes():
    full = [{"word": w, "probability": 0.2} for w in SUPPORT]
    with pytest.raises(ForecastError):
        parse_sparse({"entries": full, "other_mass": 0.1}, SUPPORT)
    fc = parse_sparse({"entries": [{"word": "candy", "probability": 0.5000004}], "other_mass": 0.5}, SUPPORT)
    assert math.isclose(sum(fc.dense(SUPPORT).values()), 1.0)


def test_brier_expected_identity_and_linear_counterexample():
    p = {"candle": 0.6, "candy": 0.4}
    sup = ["candle", "candy"]
    for q in ({"candle": 0.6, "candy": 0.4}, {"candle": 1.0, "candy": 0.0}, {"candle": 0.5, "candy": 0.5}):
        exp = sum(p[w] * dense_brier(q, w) for w in sup)
        ident = sum(v * v for v in p.values()) - sum((p[w] - q[w]) ** 2 for w in sup)
        assert math.isclose(exp, ident)
    honest_linear = 0.6 * 0.6 + 0.4 * 0.4
    false_linear = 0.6 * 1.0
    assert math.isclose(honest_linear, 0.52) and false_linear > honest_linear


def test_zero_log_probability_explicit():
    fc = parse_sparse({"entries": [{"word": "candy", "probability": 1}], "other_mass": 0}, SUPPORT)
    v, zero = log_score(fc, "candle")
    assert v == float("-inf") and zero


def test_commitment_match_labels():
    assert match_label("candle", {"action": "guess", "word": "candle"}) == "candle"
    assert match_label("candle", {"action": "guess", "word": "candy"}) == NO_MATCH
    assert match_label("candle", {"action": "pass", "word": None}) == NO_MATCH  # includes model-invalid pass
    assert match_label("candle", None) is None  # infrastructure-unobserved: unknown
