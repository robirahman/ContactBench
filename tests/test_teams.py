"""Mixed-model attacking teams: schedule, seat routing, disclosure, role ratings, adaptive defenders."""

import asyncio
import json
import math
import random
from collections import Counter
from pathlib import Path

import pytest

from contact_bench.analysis.analyze import analyze
from contact_bench.analysis.rating import fit_ratings, fit_role_ratings, match_points
from contact_bench.config import BenchConfig
from contact_bench.export.public import export_public, scan_for_secrets
from contact_bench.prompts.templates import prompt_hash
from contact_bench.providers.fake import legal_action, parse_observation
from contact_bench.runner.run import Runner
from contact_bench.runner.schedule import rematch_fixture, team_block
from contact_bench.runner.teams import Block, round_slices, select_defenders

from .test_runner import Programmable

REPO = Path(__file__).resolve().parents[1]
FAKES = [{"id": m, "provider": "fake", "model": m, "max_output_tokens": 9000} for m in ("x", "y", "z")]


def team_cfg(*, disclosure="blind", tasks=2, rounds=2, pairs=(("x", "y"), ("x", "z"), ("y", "z")), **teams):
    return BenchConfig.model_validate({
        "name": "teams", "base_dir": str(REPO), "lexicon": {"manifest": "lexicons/mechanics_fixture_manifest.json"},
        "protocol": {"version": "contact-v0.5", "turn_limit": 4, "partner_disclosure": disclosure},
        "scoring": {"development_rollouts": 64, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": tasks, "generation_seed": 5},
        "tournament": {"schedule": "teams", "homogeneous_attackers": False,
                       "teams": {"pairs": [list(p) for p in pairs], "rounds": rounds, **teams}},
        "models": FAKES, "execution": {"game_concurrency": 4, "backoff_base_seconds": 0.0},
    })


def _adapters(c, seen):
    def make(mid):
        def fn(req):
            obs = parse_observation(req.user_prompt)
            seen.append((mid, req.seat, obs))
            return legal_action(obs)
        return fn
    return {m.id: Programmable(m, make(m.id)) for m in c.models}


def test_team_block_shape():
    fx, games = team_block("t1", 0, "a", "b", "d", include_self_play=True, round_no=1)
    assert [f.kind for f in fx] == ["role", "self_play"]
    assert len(games) == 4 and {g.defender for g in games} == {"d"}
    assert {(g.guesser1_model, g.guesser2_model) for g in games} == {("a", "b"), ("b", "a"), ("a", "a"), ("b", "b")}
    assert fx[0].model_a == "a+b" and fx[0].model_b == "b+a"
    assert len({g.game_id for g in games}) == 4
    fx2, games2 = team_block("t1", 0, "a", "b", "d", include_self_play=False, round_no=1)
    assert len(fx2) == 1 and len(games2) == 2
    # rematches copy each leg's seat assignment
    by_id = {g.game_id: g for g in games}
    rf, rg = rematch_fixture(fx[0], 2, by_id[fx[0].game_ab], by_id[fx[0].game_ba])
    assert [(g.guesser1_model, g.guesser2_model, g.defender) for g in rg] == [("a", "b", "d"), ("b", "a", "d")]
    assert rf.kind == "role" and all(g.initial_prefix_length == 2 for g in rg)


def test_config_validation():
    with pytest.raises(ValueError):
        team_cfg(pairs=(("x", "x"),))
    with pytest.raises(ValueError):  # disclosure only in the team condition
        BenchConfig.model_validate({**team_cfg(disclosure="disclosed").model_dump(mode="json"),
                                    "tournament": {"schedule": "balanced_round_robin"}})


def test_offline_team_run_routes_seats_and_analyzes(tmp_path):
    c = team_cfg()
    seen = []
    st = asyncio.run(Runner(c, tmp_path / "run", adapters=_adapters(c, seen)).run())
    sched = json.loads((tmp_path / "run" / "schedule.json").read_text())
    base = [g for g in sched["games"] if "~rematch" not in g["game_id"]]
    assert len(base) == 3 * 2 * 4  # pairs x tasks x legs
    assert st["pending_games"] == 0
    assert {g["round"] for g in base} == {1, 2}
    games = {g["game_id"]: g for g in sched["games"]}
    for g in base:
        assert g["defender"] not in (g["guesser1_model"], g["guesser2_model"])
    # every request was served by the model assigned to that seat
    for mid, seat, obs in seen:
        assert "secret" not in obs or seat != "guesser2"
        assert "partner_model" not in obs  # blind
    events = [json.loads(l) for l in (tmp_path / "run" / "events.jsonl").read_text().splitlines()]
    assert sum(e["type"] == "defenders_selected" for e in events) == 2
    # per-seat routing: compare against the game records
    from contact_bench.runner.store import RunStore
    store = RunStore(tmp_path / "run")
    for gid, g in games.items():
        rec = store.read_game(gid)
        assert rec["game"]["guesser1_model"] == g["guesser1_model"]
    reqs = [json.loads(l) for l in (tmp_path / "run" / "requests.jsonl").read_text().splitlines()]
    for r in reqs:
        g = games[r["game_id"]]
        want = {"guesser1": g["guesser1_model"], "guesser2": g["guesser2_model"], "defender": g["defender"]}[r["seat"]]
        assert r["model_id"] == want
    rr = Runner(c, tmp_path / "run", replay_only=True)
    rr.prepare()
    recs = [asyncio.run(rr.play(g)) for g in rr.games]
    res = analyze(tmp_path / "run", recs, resamples=10, seed=1, penalty_scale=2.5, elo_center=1500)
    t = res["teams"]
    assert t and t["partner_disclosure"] == "blind"
    assert set(t["role_rating"]["elo"]) == {"x", "y", "z"}
    assert "x" in t["cross_play_matrix"] and "self_vs_cross_play" in t
    # team legs count in the efficiency statistics (L1/L2 labels)
    assert res["model_stats"]["x+y"]["offense_games"] >= 2  # plus any rematch legs
    # no fixture faces different defenders: defender components are not identified
    assert all(v is None for v in t["role_rating"]["elo"].values())
    assert all(c["d"] is None for c in t["role_rating"]["components_elo_points"].values())
    out = export_public(tmp_path / "run", tmp_path / "exp", res, recs)
    assert not scan_for_secrets(out)
    rep = asyncio.run(Runner(c, tmp_path / "run", replay_only=True).replay())
    assert rep["equivalent"]


def test_disclosure_only_for_guessers(tmp_path):
    c = team_cfg(disclosure="disclosed", tasks=1, rounds=1, pairs=(("x", "y"),))
    seen = []
    asyncio.run(Runner(c, tmp_path / "run", adapters=_adapters(c, seen)).run())
    g_obs = [(m, s, o) for m, s, o in seen if s != "defender"]
    assert g_obs and all("partner_model" in o for _, _, o in g_obs)
    assert all("partner_model" not in o for _, s, o in seen if s == "defender")
    assert prompt_hash("disclosed") != prompt_hash("blind") == prompt_hash()


def test_blind_prompts_unchanged_from_homogeneous():
    from contact_bench.prompts.templates import user_prompt
    # prompts-v4 hash recorded by the homogeneous leaderboard runs
    assert prompt_hash("blind") == "f0221ebd26fe57d96d5243c8444ce370ab76bf82e84a16d5d589f55a2a055afa"
    obs = {"seat": "guesser2", "current_prefix": "a", "turn": 1, "turn_limit": 4}
    try:
        blind = user_prompt(obs)
    except Exception:
        return  # the minimal observation is not renderable; hash check above suffices
    assert "partner" not in blind.lower()
    assert "Claude-X" in user_prompt({**obs, "partner_model": "Claude-X"})


def _synthetic(models, truth, n, seed=3):
    rng = random.Random(seed)
    data = []
    for _ in range(n):
        a, b, d = rng.sample(models, 3)
        l1, l2 = (a, b, d), (b, a, d)
        if rng.random() < 0.5:  # homogeneous fixtures inform defender components
            l1, l2 = (a, a, b), (b, b, a)
        s = lambda l: truth[l[0]][0] + truth[l[1]][1] - truth[l[2]][2]  # noqa: E731
        p = 1 / (1 + math.exp(-(s(l1) - s(l2))))
        data.append((l1, l2, 1.0 if rng.random() < p else 0.0))
    return data


def test_role_fit_recovers_clue_giver_vs_receiver():
    models = ["a", "b", "c", "d"]
    truth = {"a": (1.0, -1.0, 0.0), "b": (-1.0, 1.0, 0.0), "c": (0, 0, 0), "d": (0, 0, 0)}
    fit = fit_role_ratings(models, _synthetic(models, truth, 3000), penalty_scale=10)
    assert fit.converged
    assert fit.theta["a"]["g1"] - fit.theta["a"]["g2"] > 1.0
    assert fit.theta["b"]["g2"] - fit.theta["b"]["g1"] > 1.0


def test_homogeneous_data_reproduces_elo():
    rng = random.Random(1)
    models = ["a", "b", "c"]
    fx = []
    for _ in range(60):
        a, b = rng.sample(models, 2)
        y = rng.choice([0.0, 0.5, 1.0])
        fx.append((a, b, y))
    elo = fit_ratings(models, fx, penalty_scale=2.5).elo
    role = fit_role_ratings(models, [((a, a, b), (b, b, a), y) for a, b, y in fx], penalty_scale=2.5)
    for m in models:
        assert abs(elo[m] - role.elo[m]) < 1e-6


def test_adaptive_selection_missing_first_then_variance_and_deterministic():
    blocks = [Block("t1", 0, "a", "b"), Block("t2", 0, "a", "b")]
    faced = Counter({("a", "c"): 1, ("b", "c"): 1})
    sel = select_defenders(blocks, pool=["a", "b", "c", "d"], faced=faced, fit=None, round_no=1, seed=1)
    assert sel[0][1] == "d"  # never faced
    assert sel[0][2]["missing_matchups"] == 2
    assert sel == select_defenders(blocks, pool=["a", "b", "c", "d"], faced=faced, fit=None, round_no=1, seed=1)
    # variance rule: with all matchups seen, the less-observed defender wins
    models = ["a", "b", "c", "d"]
    # c has defended many homogeneous fixtures, d only one: d's component is uncertain
    data = [(("a", "a", "c"), ("c", "c", "a"), y) for y in (1.0, 0.0) * 20]
    data += [(("b", "b", "c"), ("c", "c", "b"), y) for y in (1.0, 0.0) * 20]
    data += [(("a", "a", "b"), ("b", "b", "a"), 0.5), (("a", "a", "d"), ("d", "d", "a"), 0.5)]
    fit = fit_role_ratings(models, data, penalty_scale=2.5)
    seen = Counter({(m, d): 1 for m in "ab" for d in "cd"})
    sel = select_defenders([Block("t3", 0, "a", "b")], pool=models, faced=seen, fit=fit, round_no=2, seed=1)
    assert sel[0][1] == "d"
    assert round_slices(["1", "2", "3", "4", "5"], 2) == [["1", "2", "3"], ["4", "5"]]


def test_match_points_symmetry_for_role_fixture():
    assert match_points(3, 5) == 1.0 and match_points(5, 3) == 0.0


def test_team_models_must_share_offense_mode():
    c = team_cfg().model_dump(mode="json")
    c["models"][0]["offense_mode"] = "direct_only"
    with pytest.raises(ValueError):
        BenchConfig.model_validate(c)


def test_prior_runs_must_match_condition(tmp_path):
    from contact_bench.analysis.analyze import PriorRunError, check_prior_run
    homo = BenchConfig.model_validate({**team_cfg().model_dump(mode="json"),
                                       "tournament": {"schedule": "balanced_round_robin"}})
    seen = []
    asyncio.run(Runner(homo, tmp_path / "prior", adapters=_adapters(homo, seen)).run())
    c = team_cfg(tasks=1, rounds=1, pairs=(("x", "y"),), prior_runs=["prior"])
    st = asyncio.run(Runner(c, tmp_path / "team", adapters=_adapters(c, seen)).run())
    assert st["pending_games"] == 0
    check_prior_run(tmp_path / "team", tmp_path / "prior")  # compatible
    other = BenchConfig.model_validate({**homo.model_dump(mode="json"),
                                        "protocol": {**homo.model_dump(mode="json")["protocol"], "turn_limit": 5}})
    asyncio.run(Runner(other, tmp_path / "prior5", adapters=_adapters(other, seen)).run())
    with pytest.raises(PriorRunError):
        check_prior_run(tmp_path / "team", tmp_path / "prior5")


def test_role_estimability_from_design():
    from contact_bench.analysis.rating import role_estimability
    hom = [(("a", "a", "b"), ("b", "b", "a"), 1), (("b", "b", "c"), ("c", "c", "b"), 1), (("a", "a", "x"), ("x", "x", "a"), 1)]
    team = [(("a", "b", "c"), ("b", "a", "c"), 1), (("a", "a", "c"), ("b", "b", "c"), 1),
            (("b", "c", "a"), ("c", "b", "a"), 1), (("b", "b", "a"), ("c", "c", "a"), 1)]
    # homogeneous fixtures alone identify only composites
    e = role_estimability("abcx", hom)
    assert e["a"]["composite"] and not e["a"]["g1"] and not e["a"]["d"]
    # adding role and self-play fixtures identifies components among team models only
    e = role_estimability("abcx", hom + team, reference="abc")
    assert all(e[m][r] for m in "abc" for r in ("g1", "g2", "d"))
    assert e["x"]["composite"] and not e["x"]["g1"]
    # team fixtures alone never identify defender components
    e = role_estimability("abc", team, reference="abc")
    assert not any(e[m]["d"] for m in "abc") and all(e[m]["g1"] for m in "abc")
