"""Offline tests for the static leaderboard site builder."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from contact_bench.site.build import STATIC_DIR, SiteBuildError, build_site

MALICIOUS = "<script>alert(1)</script><img src=x onerror=alert(2)>"


def make_export(d: Path, *, run_id: str = "run-a", condition_key: str = "cond1", clue: str = MALICIOUS,
                fixture: bool = True) -> Path:
    (d / "replays").mkdir(parents=True)
    manifest = {
        "schema_version": "1.0.0",
        "protocol_version": "contact-v0.4",
        "run_id": run_id,
        "run_created_at": "2026-11-17T00:00:00Z",
        "exported_at": "2026-11-17T00:00:00Z",
        "fixture_data": fixture,
        "condition_key": condition_key,
        "condition": {"clue_max_characters": 100, "turn_limit": 20, "lexicon_name": "dev_fixture",
                      "lexicon_sha256": "ab" * 32, "resolver": "fresh_shuffle_character_packing"},
        "lexicon": {"name": "dev_fixture", "word_count": 10, "license": "CC0-1.0"},
        "models": [{"id": "a", "provider": "scripted"}, {"id": "b", "provider": "scripted"}],
    }
    lb = {
        "models": ["a", "b"],
        "rating": {"elo": {"a": 1510.0, "b": 1490.0}, "converged": True, "iterations": 4,
                   "connected_components": [["a", "b"]], "penalty_scale": 2.5},
        "model_stats": {"a": {"offense_aggregate_speedup": {"numerator": 1, "denominator": 1, "value": 1.0}},
                        "b": {}},
        "bootstrap": None,
        "pairwise_match_points": {"a": {"b": {"mean_points": 0.5, "fixtures": 1}}},
        "pairwise_mean_cost": {},
    }
    games = [{"game_id": "g1", "attacker": "a", "defender": "b", "outcome_status": "solved", "turns_used": 1,
              "initial_secret_candidate_count": 3, "score": {"cost": 1.0, "baseline": {"value": 1.0}}}]
    replay = {"game_id": "g1", "attacker": "a", "defender": "b", "secret": "cat", "initial_prefix": "c",
              "turn_limit": 20, "outcome_status": "solved",
              "public_history": [{"turn": 1, "type": "clue_round", "clue": clue, "blocklist": [],
                                  "opened_guesses": [], "result": "won", "prefix_after": "c"}]}
    (d / "manifest.json").write_text(json.dumps(manifest))
    (d / "leaderboard.json").write_text(json.dumps(lb))
    (d / "games.json").write_text(json.dumps(games))
    (d / "fixtures.json").write_text("[]")
    (d / "games.csv").write_text("game_id\ng1\n")
    (d / "replays" / "g1.json").write_text(json.dumps(replay))
    return d


def test_build_and_escaping(tmp_path):
    exp = make_export(tmp_path / "exp")
    out = build_site([exp], tmp_path / "site")
    app = (out / "assets" / "app.js").read_text()
    # No HTML-injecting sinks anywhere in the client code.
    for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML(", "document.write("):
        assert sink not in app
    assert "textContent" in app
    html = (out / "index.html").read_text()
    assert "<script>alert" not in html and "onerror" not in html
    # The malicious clue only exists inside JSON data, JSON-encoded.
    hits = [p for p in out.rglob("*") if p.is_file() and "onerror=alert(2)" in p.read_text(errors="replace")]
    assert hits and all(p.suffix == ".json" and "data" in p.parts for p in hits)
    data = json.loads(next(iter(hits)).read_text())
    assert data["public_history"][0]["clue"] == MALICIOUS
    # Fixture banner present and wired to manifest.fixture_data.
    assert 'id="fixture-banner"' in html and "fixture_data" in app
    idx = json.loads((out / "data" / "index.json").read_text())
    assert len(idx["conditions"]) == 1
    c = idx["conditions"][0]
    assert c["condition_key"] == "cond1" and c["fixture_data"] is True
    assert (out / "data" / c["entry_id"] / "replays" / "g1.json").exists()
    # No external network dependencies.
    assert not re.search(r"(src|href)=\"https?://", html)
    assert "http://" not in app and "https://" not in app


def test_same_condition_different_runs_not_pooled(tmp_path):
    e1 = make_export(tmp_path / "e1", run_id="run-1")
    e2 = make_export(tmp_path / "e2", run_id="run-2")
    out = build_site([e1, e2], tmp_path / "site")
    idx = json.loads((out / "data" / "index.json").read_text())
    entries = idx["conditions"]
    assert len(entries) == 2
    assert {e["run_id"] for e in entries} == {"run-1", "run-2"}
    assert len({e["entry_id"] for e in entries}) == 2


def test_credential_rejected(tmp_path):
    exp = make_export(tmp_path / "exp", clue="key sk-test-ABCDEFGHIJKLMNOP here")
    with pytest.raises(SiteBuildError):
        build_site([exp], tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_unknown_files_and_bad_manifest_rejected(tmp_path):
    exp = make_export(tmp_path / "exp")
    (exp / "tasks_private.jsonl").write_text("{}")
    with pytest.raises(SiteBuildError):
        build_site([exp], tmp_path / "site")
    exp2 = make_export(tmp_path / "exp2")
    m = json.loads((exp2 / "manifest.json").read_text())
    del m["schema_version"]
    (exp2 / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(SiteBuildError):
        build_site([exp2], tmp_path / "site2")


def test_static_assets_exist():
    for name in ("index.html", "app.js", "style.css"):
        assert (STATIC_DIR / name).exists()
