"""Empty initial prefix and range-encoded blocklists (protocol v0.5)."""

import asyncio
import json
from pathlib import Path

import pytest

from contact_bench.config import BenchConfig, ProtocolConfig
from contact_bench.engine.actions import admit_defender, decode_blocklist
from contact_bench.runner.run import Runner, validate_config

from .helpers import block, clue, guess, make_game, run_turn, PASS

REPO = Path(__file__).resolve().parents[1]
W = ["able", "acid", "bake", "cable", "camera", "candle", "candy", "canoe", "dog", "dove"]
V5 = dict(version="contact-v0.5", blocklist_encoding="words_and_ranges")


def rb(words=(), ranges=()):
    return {"action": "block", "words": list(words), "ranges": [{"from": a, "to": b} for a, b in ranges]}


def test_range_admission_and_decoding():
    v = frozenset(W)
    a = admit_defender(rb(["dog"], [("cable", "candy")]), contact_vocab=v, allow_ranges=True)
    assert a.valid and a.canonical["ranges"] == [["cable", "candy"]]
    assert decode_blocklist(a.canonical, tuple(W)) == {"dog", "cable", "camera", "candle", "candy"}
    for bad in [rb([], [("candy", "cable")]), rb([], [("cab", "candy")]), {"action": "block", "words": []},
                {"action": "block", "words": [], "ranges": [{"from": "able"}]}]:
        assert not admit_defender(bad, contact_vocab=v, allow_ranges=True).valid
    # words-only encoding still rejects a ranges field
    assert not admit_defender(rb(), contact_vocab=v).valid


def test_empty_prefix_game_first_contact_reveals_first_letter():
    g = make_game(W, "candle", k=0, **V5)
    assert g.prefix == "" and len(g.secret_candidates()) == len(W)
    run_turn(g, {("guesser1", "act"): clue("dog", "pet"), ("guesser2", "respond"): guess("dog"),
                 ("defender", "block"): rb()})
    assert g.prefix == "c" and g.public_history[-1]["result"] == "prefix_extended"


def test_range_containing_secret_loses_and_ranges_retire_words():
    g = make_game(W, "candle", k=0, **V5)
    run_turn(g, {("guesser1", "act"): clue("dog", "pet"), ("guesser2", "respond"): guess("dog"),
                 ("defender", "block"): rb([], [("cable", "candy")])})
    assert g.outcome_status == "solved" and g.hit_sources == ["blocklist"]
    g = make_game(W, "candle", k=0, **V5)
    s = run_turn(g, {("guesser1", "act"): clue("dog", "pet"), ("guesser2", "respond"): guess("dog"),
                     ("defender", "block"): rb(["acid"], [("able", "able"), ("dog", "dove")])})
    assert g.outcome_status == "ongoing" and {"able", "dog", "dove", "acid"} <= g.used_words
    e = g.public_history[-1]
    assert e["blocked_ranges"] == [["able", "able"], ["dog", "dove"]] and e["blocked_word_count"] == 4
    s2 = run_turn(g, {("guesser1", "act"): clue("bake", "oven"), ("guesser2", "respond"): PASS,
                      ("defender", "block"): rb()})
    o = s2.obs(2, "defender", "block")
    assert o["used_ranges"] == [["able", "able"], ["dog", "dove"]]
    assert o["used_words"] == ["acid"]  # range-covered words are not repeated explicitly
    assert o["blocklist_encoding"] == "words_and_ranges"


def test_v04_rejects_ranges():
    with pytest.raises(ValueError):
        ProtocolConfig(version="contact-v0.4", blocklist_encoding="words_and_ranges")


def test_prefix0_enable_preflight_and_offline_run(tmp_path):
    c = BenchConfig.model_validate({
        "name": "p0", "base_dir": str(REPO), "lexicon": {"manifest": "lexicons/dev_fixture_manifest.json"},
        "protocol": {"version": "contact-v0.5", "dictionary_access": "lookup_tools", "initial_prefix_length": 0,
                     "blocklist_encoding": "words_and_ranges", "turn_limit": 6},
        "scoring": {"development_rollouts": 32, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": 2, "generation_seed": 3},
        "models": [{"id": "fake", "provider": "fake", "model": "f", "max_output_tokens": 100},
                   {"id": "pack", "provider": "scripted", "policy": "combined_fresh_shuffle"}],
    })
    rep = validate_config(c)
    assert rep["full_blocklist_estimated_output_tokens"] == 64 and rep["largest_initial_contact_set"] == 747
    st = asyncio.run(Runner(c, tmp_path / "r").run())
    assert st["complete_games"] == st["planned_games"]
    assert asyncio.run(Runner(c, tmp_path / "r", replay_only=True).replay())["equivalent"]
