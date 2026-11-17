"""Combining runs with an identical condition into one rating pool."""

import asyncio
import json
from pathlib import Path

import pytest

from contact_bench.analysis.combined import CombineError, combine
from contact_bench.cli.main import main as cli_main
from contact_bench.config import BenchConfig
from contact_bench.runner.run import Runner

REPO = Path(__file__).resolve().parents[1]
M = {"a": {"id": "a", "provider": "scripted", "policy": "first_last_two_guess"},
     "b": {"id": "b", "provider": "scripted", "policy": "combined_fresh_shuffle"},
     "c": {"id": "c", "provider": "scripted", "policy": "alphabetical_direct"}}


def _cfg(name, models, tour, turn_limit=4, tasks=2):
    return BenchConfig.model_validate({
        "name": name, "base_dir": str(REPO), "lexicon": {"manifest": "lexicons/dev_fixture_manifest.json"},
        "protocol": {"turn_limit": turn_limit}, "scoring": {"development_rollouts": 16, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": tasks, "generation_seed": 9}, "tournament": tour,
        "models": [M[m] for m in models],
    })


def test_combined_rating_spans_runs(tmp_path):
    rr = _cfg("rr", "ab", {"schedule": "balanced_round_robin"})
    cross = _cfg("x", "abc", {"schedule": "pairs", "pairs": [["a", "c"], ["b", "c"]]}, tasks=1)
    asyncio.run(Runner(rr, tmp_path / "rr").run())
    asyncio.run(Runner(cross, tmp_path / "x").run())
    rc = cli_main(["--runs-dir", str(tmp_path), "analyze-combined", "all", "rr", "x", "--bootstrap", "5"])
    assert rc == 0
    res = json.loads((tmp_path / "combined-all" / "analysis" / "analysis.json").read_text())
    assert set(res["models"]) == {"a", "b", "c"}
    assert res["rating"]["connected_components"] == [["a", "b", "c"]]
    # rr: 2 tasks; x: 2 pairs x 1 task; plus any no-progress rematch fixtures
    assert res["complete_fixtures"] == res["planned_fixtures"] == 4 + res["rematch_fixtures"]
    rc = cli_main(["--runs-dir", str(tmp_path), "export", "combined-all", "--public",
                   "--out", str(tmp_path / "exp")])
    assert rc == 0 and json.loads((tmp_path / "exp" / "manifest.json").read_text())["run_id"] == "combined-all"


def test_combine_rejects_mismatched_conditions(tmp_path):
    asyncio.run(Runner(_cfg("rr", "ab", {"schedule": "balanced_round_robin"}), tmp_path / "rr").run())
    asyncio.run(Runner(_cfg("cap", "ab", {"schedule": "balanced_round_robin"}, turn_limit=5), tmp_path / "cap").run())
    with pytest.raises(CombineError, match="protocol"):
        combine("bad", [tmp_path / "rr", tmp_path / "cap"], tmp_path)
    other_b = dict(M["b"], policy="combined_alphabetical")
    cfg2 = BenchConfig.model_validate({**_cfg("rr2", "ab", {"schedule": "balanced_round_robin"}).model_dump(),
                                       "models": [M["a"], other_b], "base_dir": str(REPO)})
    asyncio.run(Runner(cfg2, tmp_path / "rr2").run())
    with pytest.raises(CombineError):
        combine("bad2", [tmp_path / "rr", tmp_path / "rr2"], tmp_path)
