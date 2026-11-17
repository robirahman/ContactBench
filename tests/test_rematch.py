"""No-progress draw rule and rematch fixtures."""

import asyncio
import json
from pathlib import Path

from contact_bench.analysis.analyze import analyze
from contact_bench.config import BenchConfig
from contact_bench.runner.run import Runner

REPO = Path(__file__).resolve().parents[1]


def _cfg(**tour):
    # wasted_turns attackers never earn a letter, so every fixture between two
    # of them is a no-progress draw; first_last can solve (not a draw).
    return BenchConfig.model_validate({
        "name": "rm", "base_dir": str(REPO), "lexicon": {"manifest": "lexicons/dev_fixture_manifest.json"},
        "protocol": {"version": "contact-v0.5", "initial_prefix_length": 0, "turn_limit": 2,
                     "blocklist_encoding": "words_and_ranges"},
        "scoring": {"development_rollouts": 16, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": 2, "generation_seed": 4},
        "tournament": tour,
        "models": [{"id": "waste1", "provider": "scripted", "policy": "wasted_turns"},
                   {"id": "waste2", "provider": "scripted", "policy": "wasted_turns"}],
    })


def test_no_progress_draws_trigger_rematches_and_score_half(tmp_path):
    c = _cfg()
    st = asyncio.run(Runner(c, tmp_path / "r").run())
    sched = json.loads((tmp_path / "r" / "schedule.json").read_text())
    rm = [f for f in sched["fixtures"] if f["rematch_of"]]
    assert len(rm) == 2 and all(f["initial_prefix_length"] == 1 for f in rm)
    assert st["complete_games"] == st["planned_games"] == 8
    g = json.loads((tmp_path / "r" / "games" / f"{rm[0]['game_ab']}.json").read_text())
    assert g["summary"]["initial_prefix"] == g["summary"]["secret"][:1]
    # idempotent: resuming schedules nothing new and replays identically
    st2 = asyncio.run(Runner(c, tmp_path / "r").run())
    assert st2["planned_games"] == 8
    assert asyncio.run(Runner(c, tmp_path / "r", replay_only=True).replay())["equivalent"]
    rr = Runner(c, tmp_path / "r", replay_only=True)
    rr.prepare()
    recs = [asyncio.run(rr.play(x)) for x in rr.games]
    res = analyze(tmp_path / "r", recs, resamples=5, seed=1, penalty_scale=2.5, elo_center=1500)
    assert res["rematch_fixtures"] == 2 and res["no_progress_draws"] == 4  # rematches also draw; no chain
    assert all(f["points_a"] == 0.5 for f in res["fixtures"])
    assert abs(res["rating"]["elo"]["waste1"] - res["rating"]["elo"]["waste2"]) < 1e-6


def test_rule_can_be_disabled(tmp_path):
    c = _cfg(no_progress_draws=False, rematch_on_no_progress_draw=False)
    st = asyncio.run(Runner(c, tmp_path / "r").run())
    assert st["planned_games"] == 4
