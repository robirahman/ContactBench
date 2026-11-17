"""Closed-book and dictionary-assisted (lookup_tools) conditions (protocol v0.5)."""

import asyncio
import json
from pathlib import Path

import pytest

from contact_bench.config import BenchConfig, ProtocolConfig
from contact_bench.dictionary import DictionaryService
from contact_bench.runner.run import Runner
from contact_bench.runner.store import RunStore

from .helpers import clue, guess, block, lex, make_game, run_turn

REPO = Path(__file__).resolve().parents[1]
W = ["cable", "camera", "candle", "candy", "canoe", "carrot", "castle", "cobra", "comet", "crane"]


def test_dictionary_service_interface():
    d = DictionaryService(lex(W + ["dog"]))
    assert d.is_legal_word("Candle") and not d.is_legal_word("candles")
    assert d.count_words("ca") == 7 and d.count_words("") == 11
    assert d.list_words("ca", 2, 3) == ["candle", "candy", "canoe"]
    assert d.list_words("ca", 100) == []
    assert d.execute("list_words", {"prefix": "co"}) == {"result": ["cobra", "comet"]}
    assert d.execute("count_words", {"prefix": "c"}) == {"result": 10}
    assert d.execute("is_legal_word", {"word": "crane"}) == {"result": True}
    for bad in [("list_words", {"prefix": "C!"}), ("list_words", {"prefix": "c", "limit": 101}),
                ("list_words", {"prefix": "c", "offset": -1}), ("count_words", {"prefix": 3}),
                ("is_legal_word", {}), ("delete_word", {"word": "x"}), ("count_words", "c")]:
        assert "error" in d.execute(*bad)


@pytest.mark.parametrize("mode", ["closed_book", "lookup_tools"])
def test_observations_carry_identity_not_lists(mode):
    g = make_game(W, "candle", version="contact-v0.5", dictionary_access=mode)
    s = run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                     ("defender", "block"): block()})
    for seat, phase in [("guesser1", "act"), ("guesser2", "respond"), ("defender", "block")]:
        o = s.obs(1, seat, phase)
        assert "secret_candidates" not in o and "contact_candidates" not in o
        assert o["dictionary_access"] == mode and o["dictionary"]["word_count"] == len(W)
        assert "candle" not in json.dumps({k: v for k, v in o.items() if k != "secret"})
    # engine still validates membership against the frozen list
    run_turn(g, {("guesser1", "act"): {"action": "direct", "word": "candlex", "clue": None}})
    assert g.public_history[-1]["type"] == "invalid_action"


def test_v04_rejects_new_modes():
    with pytest.raises(ValueError):
        ProtocolConfig(version="contact-v0.4", dictionary_access="closed_book")


def _cfg(mode, models, lexicon="lexicons/dev_fixture_manifest.json"):
    return BenchConfig.model_validate({
        "name": "dm", "base_dir": str(REPO), "lexicon": {"manifest": lexicon},
        "protocol": {"version": "contact-v0.5", "dictionary_access": mode, "turn_limit": 6,
                     "max_tool_calls_per_decision": 5},
        "scoring": {"development_rollouts": 64, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": 2, "generation_seed": 3}, "models": models,
    })


def test_lookup_tools_offline_tournament_and_replay(tmp_path):
    c = _cfg("lookup_tools", [{"id": "fake", "provider": "fake", "model": "f", "max_output_tokens": 9000},
                              {"id": "pack", "provider": "scripted", "policy": "combined_fresh_shuffle"}])
    st = asyncio.run(Runner(c, tmp_path / "r").run())
    assert st["complete_games"] == st["planned_games"] == 4
    reqs = RunStore(tmp_path / "r").requests()
    traces = [q["response"]["tool_trace"] for q in reqs if q["status"] == "ok"]
    assert any(t and t[0]["name"] == "list_words" for t in traces)
    rep = asyncio.run(Runner(c, tmp_path / "r", replay_only=True).replay())
    assert rep["equivalent"]
    # fake attackers with lookup found real words: no invalid G1 actions
    g = json.loads(next((tmp_path / "r" / "games").glob("*fake-atk-pack.json")).read_text())
    assert all(e["type"] != "invalid_action" for e in g["public_history"])


def test_closed_book_scripted_baselines_use_dictionary(tmp_path):
    c = _cfg("closed_book", [{"id": "fl", "provider": "scripted", "policy": "first_last_two_guess"},
                             {"id": "pack", "provider": "scripted", "policy": "combined_fresh_shuffle"}])
    st = asyncio.run(Runner(c, tmp_path / "r").run())
    assert st["complete_games"] == 4
