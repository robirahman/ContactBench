"""Local human play mode: config, schedule, pre-check, anchored rating, server, end to end."""

import asyncio
import http.client
import json
import threading
import time
from pathlib import Path

import pytest

from contact_bench.analysis.analyze import analyze
from contact_bench.analysis.combined import CombineError, combine
from contact_bench.analysis.rating import fit_anchored, fit_ratings
from contact_bench.config import BenchConfig
from contact_bench.engine import actions as A
from contact_bench.human.agent import precheck
from contact_bench.human.server import PlayServer
from contact_bench.human.session import HumanSession
from contact_bench.runner.run import Runner, load_game_records
from contact_bench.runner.schedule import build_schedule

from .helpers import make_game

REPO = Path(__file__).resolve().parents[1]


def _data(**over):
    d = {
        "name": "hc", "base_dir": str(REPO), "lexicon": {"manifest": "lexicons/dev_fixture_manifest.json"},
        "protocol": {"version": "contact-v0.5", "initial_prefix_length": 0, "turn_limit": 2,
                     "blocklist_encoding": "words_and_ranges", "dictionary_access": "lookup_tools",
                     "max_tool_calls_per_decision": 3},
        "scoring": {"development_rollouts": 16, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": 2, "generation_seed": 9},
        "tournament": {"schedule": "human_challenge", "rematch_on_no_progress_draw": False,
                       "human_challenge": {"player": "me", "opponents": ["bot_a", "bot_b"]}},
        "models": [{"id": "me", "provider": "human", "display_name": "Me"},
                   {"id": "bot_a", "provider": "scripted", "policy": "first_last_two_guess",
                    "defender_policy": "literal_clue_words"},
                   {"id": "bot_b", "provider": "scripted", "policy": "wasted_turns"}],
        "execution": {"game_concurrency": 1},
    }
    d.update(over)
    return d


def _cfg(**over):
    return BenchConfig.model_validate(_data(**over))


def test_config_rules():
    _cfg()
    bad = _data()
    bad["tournament"] = {**bad["tournament"], "rematch_on_no_progress_draw": True}
    with pytest.raises(ValueError, match="rematch"):
        BenchConfig.model_validate(bad)
    bad = _data(execution={"game_concurrency": 2})
    with pytest.raises(ValueError, match="game_concurrency"):
        BenchConfig.model_validate(bad)
    bad = _data()
    bad["tournament"] = {"schedule": "balanced_round_robin"}
    with pytest.raises(ValueError, match="human"):
        BenchConfig.model_validate(bad)
    bad = _data()
    bad["tournament"]["human_challenge"]["opponents"] = ["nobody"]
    with pytest.raises(ValueError, match="opponent"):
        BenchConfig.model_validate(bad)


def test_schedule_disjoint_secrets_attack_first(tmp_path):
    cfg = _cfg()
    r = Runner(cfg, tmp_path / "r")
    r.prepare()
    assert len(r.tasks) == 4  # tasks_per_pair x opponents: every secret used once
    by_task = {}
    for f in r.fixtures:
        by_task.setdefault(f.task_id, []).append(f)
        assert f.model_a == "me"
    assert all(len(v) == 1 for v in by_task.values())
    order = [g.game_id for g in r.games]
    for f in r.fixtures:
        assert order.index(f.game_ab) + 1 == order.index(f.game_ba)  # attack leg immediately first
    ab = next(g for g in r.games if g.leg == "AB")
    assert ab.attacker == "me" and ab.attacker_g2 == ab.defender
    assert ab.seat_model("guesser1") == "me" and ab.seat_model("guesser2") == ab.defender
    ba = next(g for g in r.games if g.leg == "BA")
    assert ba.defender == "me" and ba.seat_model("guesser2") == ba.attacker


def test_without_a_player_human_games_stay_pending(tmp_path):
    st = asyncio.run(Runner(_cfg(), tmp_path / "r").run())
    assert st["complete_games"] == 0 and st["pending_games"] == 8
    # defend legs never start before the attack leg is complete
    assert not (tmp_path / "r" / "games").exists() or all(
        json.loads(p.read_text())["game"]["leg"] == "AB" for p in (tmp_path / "r" / "games").glob("*.json"))


def test_precheck_equals_engine_admission():
    g = make_game(["cat", "car", "cart", "dog", "dot"], "cart", L=3, k=1,
                  version="contact-v0.5", blocklist_encoding="words_and_ranges")
    obs = g.observation("guesser1", "act", 1)

    class D:
        lexicon = g.v_contact

        def is_legal_word(self, w):
            return w in g.v_contact

    spec = {"seat": "guesser1", "phase": "act", "observation": obs}
    pre_secret, pre_contact = frozenset(g.secret_candidates()), frozenset(g.contact_candidates())
    for action in [{"action": "clue", "word": "car", "clue": "vehicle"},
                   {"action": "clue", "word": "dog", "clue": "pet"},          # wrong prefix
                   {"action": "clue", "word": "cab", "clue": "taxi"},          # not a word
                   {"action": "clue", "word": "cat", "clue": "x" * 101},       # too long
                   {"action": "clue", "word": "cat", "clue": "café"},     # not ASCII
                   {"action": "direct", "word": "cart", "clue": None},
                   {"action": "direct", "word": "cart", "clue": "x"},
                   {"action": "pass"}, "not json"]:
        want = A.admit_guesser1(action, pre_secret=pre_secret, pre_contact=pre_contact, max_chars=100).reason
        assert precheck(spec, action, contact_dictionary=D()) == want
    dspec = {"seat": "defender", "phase": "block", "observation": g.observation("defender", "block", 1, current_clue="x")}
    assert precheck(dspec, {"action": "block", "words": ["cat"], "ranges": [{"from": "car", "to": "cart"}]},
                    contact_dictionary=D()) is None
    assert precheck(dspec, {"action": "block", "words": ["zzz"], "ranges": []}, contact_dictionary=D())


def test_anchored_fit_reproduces_joint_fit():
    res = [("a", "b", 1.0), ("a", "b", 0.5), ("b", "c", 1.0), ("a", "c", 1.0), ("c", "b", 0.5)]
    joint = fit_ratings(["a", "b", "c"], res)
    anch = fit_anchored({"b": joint.elo["b"], "c": joint.elo["c"]}, res, ["a"])
    assert abs(anch["elo"]["a"] - joint.elo["a"]) < 1e-6
    assert anch["converged"] and set(anch["fixed_elo"]) == {"b", "c"}
    # a draw against a 1500 opponent keeps the player at 1500
    assert abs(fit_anchored({"x": 1500.0}, [("h", "x", 0.5)], ["h"])["elo"]["h"] - 1500) < 1e-9
    with pytest.raises(ValueError):
        fit_anchored({"x": 1500.0}, [("h", "y", 1.0)], ["h"])


def _req(port, token, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": f"127.0.0.1:{port}"}
    if token is not None:
        headers["X-Play-Token"] = token
    data = None
    if body is not None:
        data = json.dumps(body)
        headers["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=headers)
    r = c.getresponse()
    out = r.status, json.loads(r.read() or b"null") if r.getheader("Content-Type", "").startswith("application/json") else None
    c.close()
    return out


def _human_bot(port, token, stop, seen):
    """Plays through the HTTP API with public information only."""
    while not stop.is_set():
        try:
            code, st = _req(port, token, "GET", "/api/state")
        except OSError:  # the server closed after the last game (--no-wait)
            return
        assert code == 200
        seen.append(st)
        p = st["pending"]
        if st["status"] == "finished":
            return
        if not p:
            time.sleep(0.02)
            continue
        obs, did = p["observation"], p["decision_id"]
        if p["phase"] == "choice":
            action = {"action": "reveal"}
        elif p["seat"] == "guesser1":
            code, lk = _req(port, token, "POST", "/api/lookup",
                            {"decision_id": did, "name": "list_words", "args": {"prefix": obs["prefix"]}})
            assert code == 200 and lk["remaining"] == p["max_lookups"] - 1
            used = set(obs["used_words"])
            word = next(w for w in lk["result"] if w not in used)
            # a typo is returned with the engine's reason instead of losing the turn
            code, r = _req(port, token, "POST", "/api/decide",
                           {"decision_id": did, "action": {"action": "direct", "word": "qqqq", "clue": None}})
            assert code == 200 and r["accepted"] is False and "candidate" in r["reason"]
            action = {"action": "direct", "word": word, "clue": None}
        else:
            assert "secret" in obs  # defender sees the secret
            action = {"action": "block", "words": [], "ranges": []}
        code, r = _req(port, token, "POST", "/api/decide", {"decision_id": did, "action": action})
        assert code == 200 and r["accepted"], r


def test_end_to_end_through_http(tmp_path):
    cfg = _cfg()
    runner = Runner(cfg, tmp_path / "r")
    runner.prepare()
    session = HumanSession(run_id=runner.run_id, player="me", display_name="Me",
                           model_names={m.id: m.id for m in cfg.models}, fixtures=runner.fixtures,
                           games=runner.games, contact_dictionary=runner.contact_dictionary)
    runner.human_session = session
    server = PlayServer(session).start()
    try:
        assert server.httpd.server_address[0] == "127.0.0.1"
        port, token = server.port, server.token
        # token and host checks
        assert _req(port, None, "GET", "/api/state")[0] == 403
        assert _req(port, "wrong", "GET", "/api/state")[0] == 403
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/api/state", headers={"Host": "evil.example:80", "X-Play-Token": token})
        assert c.getresponse().status == 403
        c.close()
        assert _req(port, None, "GET", "/")[0] == 200  # the page itself carries no data
        stop, seen = threading.Event(), []
        t = threading.Thread(target=_human_bot, args=(port, token, stop, seen), daemon=True)
        t.start()

        async def go():
            session.attach(asyncio.get_running_loop())
            return await runner.run()

        st = asyncio.run(go())
        session.mark_finished()
        t.join(10)
        stop.set()
    finally:
        server.close()
    assert st["complete_games"] == st["planned_games"] == 8
    # nothing outside the deciding seat's own observation and finished games leaks
    tasks = {json.loads(l)["task_id"]: json.loads(l)["secret"]
             for l in (tmp_path / "r" / "private" / "tasks_private.jsonl").read_text().splitlines()}
    finished = set()
    for s in seen:
        finished |= {r[k]["secret"] for r in s["fixtures"] for k in ("attack", "defend") if r[k]}
        text = json.dumps(s)
        assert "referee_audit" not in text and "private_histories" not in text
        p = s["pending"]
        for secret in set(tasks.values()) - finished:
            if p and p["seat"] == "defender" and p["observation"].get("secret") == secret:
                continue
            assert f'"{secret}"' not in text, secret
    # human decisions are recorded like any other, with unscored metadata
    decs = [json.loads(l) for l in (tmp_path / "r" / "decisions.jsonl").read_text().splitlines()]
    hum = [d for d in decs if d["model_id"] == "me"]
    assert hum and all("think_seconds" in d["human"] for d in hum)
    assert any(d["human"]["prechecks_rejected"] == 1 for d in hum if d["seat"] == "guesser1")
    assert {d["model_id"] for d in decs if d["seat"] == "guesser2"} <= {"bot_a", "bot_b"}
    # replay without the human reproduces every game
    rep = asyncio.run(Runner(cfg, tmp_path / "r", replay_only=True).replay())
    assert rep["equivalent"] and rep["complete"] == 8
    res = analyze(tmp_path / "r", load_game_records(tmp_path / "r"), resamples=0, seed=1, penalty_scale=2.5,
                  elo_center=1500, anchor={"elo": {"bot_a": 1550.0, "bot_b": 1450.0}, "run_id": "anchor"})
    assert res["complete_fixtures"] == 4
    assert res["anchored_rating"]["free"] == ["me"] and res["human_challenge"]["display_names"]["me"] == "Me"
    assert res["anchored_rating"]["fixed_elo"] == {"bot_a": 1550.0, "bot_b": 1450.0}
    # the headline rating holds the opponents fixed; the joint fit is kept aside
    assert res["rating"]["elo"]["bot_a"] == 1550.0 and res["rating"]["fixed"] == ["bot_a", "bot_b"]
    assert res["rating"]["elo"]["me"] == res["anchored_rating"]["elo"]["me"]
    assert "elo" in res["rating_joint_unanchored"]
    unanchored = analyze(tmp_path / "r", load_game_records(tmp_path / "r"), resamples=3, seed=1, penalty_scale=2.5,
                         elo_center=1500, write=False)
    assert unanchored["rating"]["unanchored"] is True
    assert all("elo" not in v for v in unanchored["bootstrap"]["intervals_95"].values())
    # the export is its own condition and is never combined with model runs
    from contact_bench.export.public import export_public

    out = export_public(tmp_path / "r", tmp_path / "exp", res, load_game_records(tmp_path / "r"))
    man = json.loads((out / "manifest.json").read_text())
    assert man["condition"]["human_challenge"]["display_name"] == "Me"
    assert json.loads((out / "leaderboard.json").read_text())["anchored_rating"]["free"] == ["me"]
    with pytest.raises(CombineError, match="human"):
        combine("x", [tmp_path / "r", tmp_path / "r"], tmp_path / "runs")


def test_stop_pauses_and_resume_continues(tmp_path):
    cfg = _cfg()
    runner = Runner(cfg, tmp_path / "r")
    runner.prepare()
    session = HumanSession(run_id=runner.run_id, player="me", display_name="Me", model_names={},
                           fixtures=runner.fixtures, games=runner.games,
                           contact_dictionary=runner.contact_dictionary)
    runner.human_session = session

    async def go():
        session.attach(asyncio.get_running_loop())
        task = asyncio.ensure_future(runner.run())
        while session.state()["pending"] is None:
            await asyncio.sleep(0.01)
        session.stop()
        return await task

    st = asyncio.run(go())
    assert st["complete_games"] == 0 and session.state()["status"] == "stopped"
    session.mark_paused("8 games still pending (paused).")
    assert session.state()["message"].startswith("8 games")
    # a later session resumes the same run
    runner2 = Runner(cfg, tmp_path / "r")
    runner2.prepare()
    s2 = HumanSession(run_id=runner2.run_id, player="me", display_name="Me", model_names={},
                      fixtures=runner2.fixtures, games=runner2.games, contact_dictionary=runner2.contact_dictionary)
    runner2.human_session = s2

    async def auto():
        s2.attach(asyncio.get_running_loop())
        task = asyncio.ensure_future(runner2.run())
        while not task.done():
            p = s2.state()["pending"]
            if p:
                obs = p["observation"]
                if p["phase"] == "choice":
                    a = {"action": "cancel"}
                elif p["seat"] == "guesser1":
                    w = next(w for w in runner2.contact_dictionary.list_words(obs["prefix"])
                             if w not in obs["used_words"])
                    a = {"action": "direct", "word": w, "clue": None}
                else:
                    a = {"action": "block", "words": [], "ranges": []}
                assert s2.submit(p["decision_id"], a)["accepted"]
            await asyncio.sleep(0.005)
        return task.result()

    st2 = asyncio.run(auto())
    assert st2["complete_games"] == 8


def test_play_command_end_to_end(tmp_path, monkeypatch):
    """`contact-bench play` wiring: player rename, fresh task seed, server, resume."""
    import yaml

    from contact_bench.cli import main as cli
    from contact_bench.human import server as srv

    data = _data()
    data.pop("base_dir")
    data["lexicon"]["manifest"] = str(REPO / "lexicons/dev_fixture_manifest.json")
    data["scoring"]["cache_dir"] = str(REPO / ".cache/test_reference")
    data["tasks"].pop("generation_seed")
    cfgp = tmp_path / "hc.yaml"
    cfgp.write_text(yaml.safe_dump(data))
    started = []
    orig = srv.PlayServer.start

    def start(self):
        started.append(self)
        return orig(self)

    monkeypatch.setattr(srv.PlayServer, "start", start)
    stop, seen = threading.Event(), []

    def bot():
        while not started:
            time.sleep(0.01)
        _human_bot(started[0].port, started[0].token, stop, seen)

    t = threading.Thread(target=bot, daemon=True)
    t.start()
    assert cli.main(["plan", str(cfgp)]) == 0  # plans need tasks_per_pair x opponents secrets
    rc = cli.main(["--runs-dir", str(tmp_path / "runs"), "play", str(cfgp), "--player", "Ada L.",
                   "--run-id", "h1", "--no-browser", "--no-wait"])
    stop.set()
    assert rc == 0
    man = json.loads((tmp_path / "runs" / "h1" / "run.json").read_text())
    assert man["config"]["tournament"]["human_challenge"]["player"] == "human_ada_l"
    assert any(m.get("display_name") == "Ada L." for m in man["config"]["models"])
    assert isinstance(man["config"]["tasks"]["generation_seed"], int)
    assert seen and seen[-1]["display_name"] == "Ada L."
    recs = load_game_records(tmp_path / "runs" / "h1")
    assert len(recs) == 8 and all(r["run_status"] == "complete" for r in recs)
    # resuming a finished run plays nothing new
    assert cli.main(["--runs-dir", str(tmp_path / "runs"), "play", "--resume", "h1", "--no-browser",
                     "--no-wait"]) == 0


def test_human_challenge_never_repeats_a_secret(tmp_path):
    from dataclasses import replace

    # 80 draws with replacement from a 747-word fixture almost surely collide
    d = _data()
    d["tasks"]["tasks_per_pair"] = 40
    r = Runner(BenchConfig.model_validate(d), tmp_path / "r")
    r.prepare()
    secrets = [t.secret for t in r.tasks.values()]
    assert len(secrets) == 80 and len(set(secrets)) == 80
    tasks = list(r.tasks.values())
    dup = [tasks[0], replace(tasks[1], secret=tasks[0].secret)] + tasks[2:]
    with pytest.raises(ValueError, match="distinct"):
        build_schedule(BenchConfig.model_validate(d), dup)


def test_anchor_must_match_the_challenge_condition(tmp_path):
    from contact_bench.analysis.anchor import AnchorError, load_anchor

    def model_run(name, **proto):
        d = _data()
        d["protocol"] = {**d["protocol"], **proto}
        d["tournament"] = {"schedule": "balanced_round_robin"}
        d["models"] = d["models"][1:]
        d.pop("execution")
        c = BenchConfig.model_validate(d)
        asyncio.run(Runner(c, tmp_path / name).run())
        analyze(tmp_path / name, load_game_records(tmp_path / name), resamples=0, seed=1, penalty_scale=2.5,
                elo_center=1500)
        return c

    model_run("anchor")
    model_run("other", turn_limit=3)
    ch = Runner(_cfg(), tmp_path / "challenge")
    ch.prepare()
    a = load_anchor("anchor", tmp_path, tmp_path / "challenge")
    assert set(a["elo"]) == {"bot_a", "bot_b"} and a["run_id"] == "anchor"
    with pytest.raises(AnchorError, match="protocol"):
        load_anchor("other", tmp_path, tmp_path / "challenge")
    (tmp_path / "challenge" / "analysis").mkdir()
    (tmp_path / "challenge" / "analysis" / "analysis.json").write_text(json.dumps({"rating": {"elo": {}}}))
    with pytest.raises(AnchorError, match="human-challenge"):
        load_anchor("challenge", tmp_path, tmp_path / "challenge")
