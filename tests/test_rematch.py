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


def test_no_progress_draws_trigger_recursive_rematches(tmp_path):
    c = _cfg()
    st = asyncio.run(Runner(c, tmp_path / "r").run())
    sched = json.loads((tmp_path / "r" / "schedule.json").read_text())
    tasks = {json.loads(l)["task_id"]: json.loads(l)["secret"]
             for l in (tmp_path / "r" / "private" / "tasks_private.jsonl").read_text().splitlines()}
    base = [f for f in sched["fixtures"] if not f["rematch_of"]]
    rm = [f for f in sched["fixtures"] if f["rematch_of"]]
    # wasted_turns never earns a letter, so every level draws until the revealed
    # prefix would reach the secret: rematches at 1 .. len(secret)-1 letters.
    expected = sum(len(tasks[f["task_id"]]) - 1 for f in base)
    assert len(rm) == expected
    for f in base:
        chain = sorted(x["initial_prefix_length"] for x in rm if x["task_id"] == f["task_id"])
        assert chain == list(range(1, len(tasks[f["task_id"]])))
    assert st["complete_games"] == st["planned_games"] == 2 * (len(base) + len(rm))
    g = json.loads((tmp_path / "r" / "games" / f"{rm[0]['game_ab']}.json").read_text())
    assert g["summary"]["initial_prefix"] == g["summary"]["secret"][:rm[0]["initial_prefix_length"]]
    # idempotent: resuming schedules nothing new and replays identically
    st2 = asyncio.run(Runner(c, tmp_path / "r").run())
    assert st2["planned_games"] == st["planned_games"]
    assert asyncio.run(Runner(c, tmp_path / "r", replay_only=True).replay())["equivalent"]
    rr = Runner(c, tmp_path / "r", replay_only=True)
    rr.prepare()
    recs = [asyncio.run(rr.play(x)) for x in rr.games]
    res = analyze(tmp_path / "r", recs, resamples=5, seed=1, penalty_scale=2.5, elo_center=1500)
    assert res["rematch_fixtures"] == expected and res["no_progress_draws"] == len(base) + expected
    assert all(f["points_a"] == 0.5 for f in res["fixtures"])
    assert abs(res["rating"]["elo"]["waste1"] - res["rating"]["elo"]["waste2"]) < 1e-6


def test_non_recursive_rematches_stop_after_one_level(tmp_path):
    c = _cfg(rematch_recursive=False)
    asyncio.run(Runner(c, tmp_path / "r").run())
    sched = json.loads((tmp_path / "r" / "schedule.json").read_text())
    rm = [f for f in sched["fixtures"] if f["rematch_of"]]
    assert len(rm) == 2 and all(f["initial_prefix_length"] == 1 for f in rm)


def test_rule_can_be_disabled(tmp_path):
    c = _cfg(no_progress_draws=False, rematch_on_no_progress_draw=False)
    st = asyncio.run(Runner(c, tmp_path / "r").run())
    assert st["planned_games"] == 4


def test_plan_maxima_include_possible_rematches():
    from contact_bench.runner.run import load_lexicons
    from contact_bench.runner.schedule import build_schedule, run_plan
    from contact_bench.runner.tasks import generate_tasks

    for rematch, factor in ((True, 2), (False, 1)):
        c = _cfg(rematch_on_no_progress_draw=rematch)
        vs, vc = load_lexicons(c)
        tasks = generate_tasks(v_secret=vs, v_contact=vc, count=2, seed=1, split="development",
                               initial_prefix_length=0, turn_limit=2, clue_max_characters=100)
        _, games = build_schedule(c, tasks)
        plan = run_plan(c, tasks, games)
        assert plan["maximum_game_decisions_total"] == 4 * 2 * len(games) * factor
        assert plan["maximum_rematch_games"] == len(games) * (factor - 1)


def test_draw_rule_is_part_of_condition_key(tmp_path):
    from contact_bench.export.public import export_public
    keys = []
    for i, rule in enumerate((True, False)):
        c = _cfg(no_progress_draws=rule, rematch_on_no_progress_draw=False)
        d = tmp_path / f"r{i}"
        asyncio.run(Runner(c, d).run())
        rr = Runner(c, d, replay_only=True)
        rr.prepare()
        recs = [asyncio.run(rr.play(x)) for x in rr.games]
        res = analyze(d, recs, resamples=0, seed=1, penalty_scale=2.5, elo_center=1500)
        out = export_public(d, tmp_path / f"e{i}", res, recs)
        keys.append(json.loads((out / "manifest.json").read_text())["condition_key"])
    assert keys[0] != keys[1]


def test_legacy_snapshots_have_rematches_disabled():
    from contact_bench.config import snapshot_with_legacy_defaults
    legacy = {"tournament": {"schedule": "balanced_round_robin"}}
    assert snapshot_with_legacy_defaults(legacy)["tournament"]["rematch_on_no_progress_draw"] is False
    # a legacy run whose recorded schedule contains rematch fixtures had them enabled
    assert snapshot_with_legacy_defaults(legacy, True)["tournament"]["rematch_on_no_progress_draw"] is True
    new = {"tournament": {"rematch_on_no_progress_draw": True}}
    assert snapshot_with_legacy_defaults(new)["tournament"]["rematch_on_no_progress_draw"] is True


def test_rematch_ids_cannot_collide_with_model_ids():
    from contact_bench.runner.schedule import Fixture, rematch_fixture
    import pytest
    from contact_bench.config import ModelConfig
    f = Fixture("t-r0-a~b", "t", 0, "a", "b", "t-r0-a-atk-b", "t-r0-b-atk-a")
    _, games = rematch_fixture(f, 1)
    assert all("~" in g.game_id for g in games)
    with pytest.raises(ValueError):
        ModelConfig(id="b~rematch", provider="scripted")


def test_rematch_execution_order_is_shuffled_deterministically(tmp_path):
    import hashlib
    c = _cfg()
    r = Runner(c, tmp_path / "r")
    played = []
    orig = r.play

    async def spy(g):
        played.append(g.game_id)
        return await orig(g)

    r.play = spy
    asyncio.run(r.run())
    rm = [x for x in played if x.endswith("~rematch") and "~rematch~" not in x]  # first level
    key = lambda gid: hashlib.sha256(f"rematch-order|{c.tournament.order_seed}|{gid}".encode()).hexdigest()
    assert rm and rm == sorted(rm, key=key)


def test_pairs_schedule_plays_only_listed_pairs(tmp_path):
    import pytest
    c = BenchConfig.model_validate({
        "name": "pairs", "base_dir": str(REPO), "lexicon": {"manifest": "lexicons/mechanics_fixture_manifest.json"},
        "protocol": {"turn_limit": 2}, "scoring": {"development_rollouts": 16, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": 2}, "tournament": {"schedule": "pairs", "pairs": [["a", "c"], ["b", "c"]]},
        "models": [{"id": x, "provider": "scripted"} for x in ("a", "b", "c")],
    })
    asyncio.run(Runner(c, tmp_path / "r").run())
    sched = json.loads((tmp_path / "r" / "schedule.json").read_text())
    assert {(f["model_a"], f["model_b"]) for f in sched["fixtures"]} == {("a", "c"), ("b", "c")}
    assert len(sched["games"]) == 2 * 2 * 2
    for bad in ([["a", "a"]], [["a", "zz"]], [["a", "c"], ["c", "a"]], []):
        with pytest.raises(Exception):
            BenchConfig.model_validate({**c.model_dump(), "tournament": {"schedule": "pairs", "pairs": bad}})
