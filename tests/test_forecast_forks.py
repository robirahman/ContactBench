"""Live transcript forks for forecasts (forecast mode ``fork``)."""

import asyncio
import json
from pathlib import Path

import pytest

from contact_bench.analysis.analyze import analyze
from contact_bench.analysis.calibration import forecast_calibration
from contact_bench.config import BenchConfig, ModelConfig
from contact_bench.forecasts.forks import PASS, build_support, score_fork, support_descriptor
from contact_bench.providers.anthropic_adapter import AnthropicMessagesAdapter
from contact_bench.providers.base import DecisionRequest
from contact_bench.runner.run import Runner
from contact_bench.runner.store import RunStore

from .helpers import lex

REPO = Path(__file__).resolve().parents[1]


def _cfg(mode, access="full_candidate_lists", **proto):
    return BenchConfig.model_validate({
        "name": "fk", "base_dir": str(REPO), "lexicon": {"manifest": "lexicons/dev_fixture_manifest.json"},
        "protocol": {"version": "contact-v0.5", "dictionary_access": access, "turn_limit": 5, **proto},
        "scoring": {"development_rollouts": 32, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": 2, "generation_seed": 9}, "forecasts": {"mode": mode},
        "models": [{"id": "fa", "provider": "fake", "model": "a", "max_output_tokens": 9000},
                   {"id": "fb", "provider": "fake", "model": "b", "max_output_tokens": 9000}],
    })


@pytest.mark.parametrize("access", ["full_candidate_lists", "lookup_tools"])
def test_forks_do_not_change_gameplay_or_observations(tmp_path, access):
    recs = {}
    for mode in ("off", "fork"):
        r = Runner(_cfg(mode, access), tmp_path / mode)
        asyncio.run(r.run())
        recs[mode] = {p.name: json.loads(p.read_text()) for p in (tmp_path / mode / "games").glob("*.json")}
        recs[mode + "_obs"] = {k.split("/", 1)[1]: v["observation_sha256"]
                               for k, v in RunStore(tmp_path / mode).decisions().items()}
    assert recs["off_obs"] == recs["fork_obs"]
    for name, off in recs["off"].items():
        fk = recs["fork"][name]
        for key in ("summary", "public_history", "referee_audit", "private_histories", "score"):
            assert off[key] == fk[key], (name, key)
    assert not (tmp_path / "off" / "forecasts.jsonl").exists()


def test_fork_records_labels_and_calibration(tmp_path):
    r = Runner(_cfg("fork"), tmp_path / "r")
    asyncio.run(r.run())
    forks = RunStore(tmp_path / "r").forecasts()
    kinds = {(f["seat"], f["kind"]) for f in forks}
    assert kinds == {("guesser1", "guesser1"), ("guesser2", "intended_word"), ("defender", "intended_word")}
    assert all(f["status"] == "ok" for f in forks)
    recs = [json.loads(p.read_text()) for p in (tmp_path / "r" / "games").glob("*.json")]
    scored = [f for rec in recs for f in rec["forecasts"]]
    iw = [f for f in scored if f["kind"] == "intended_word"]
    assert iw and all(f["answer"] and f["scores"]["intended_word"]["valid"] for f in iw)
    # the fake reports uniform intended-word forecasts: Brier = 1/M
    for f in iw:
        s = f["scores"]["intended_word"]
        assert s["brier"] == pytest.approx(1 / s["support_size"])
    g1 = [f for f in scored if f["kind"] == "guesser1"]
    assert all(f["scores"]["block_probability"]["p"] == 0.25 for f in g1)
    assert all(f["answer"]["receiver_word"] is not None for f in g1)
    cal = forecast_calibration(recs)
    assert set(cal["fa"]) == {"intended_word@guesser2", "intended_word@defender", "receiver_word@guesser1",
                              "block_probability@guesser1"}
    rr = Runner(_cfg("fork"), tmp_path / "r", replay_only=True)
    rr.prepare()
    replayed = [asyncio.run(rr.play(g)) for g in rr.games]
    res = analyze(tmp_path / "r", replayed, resamples=5, seed=1, penalty_scale=2.5, elo_center=1500)
    assert res["forecast_calibration"]["fa"]["block_probability@guesser1"]["valid"] > 0
    assert "Forecast calibration" in (tmp_path / "r" / "analysis" / "report.md").read_text()


def _support(words, prefix="ca", used=(), ranges=()):
    lx = lex(words)
    return lx, support_descriptor(prefix, {"used_words": list(used), "used_ranges": [list(r) for r in ranges]},
                                  sum(1 for w in words if w.startswith(prefix) and len(w) > len(prefix)
                                      and w not in used and not any(a <= w <= b for a, b in ranges)))


def test_support_membership_with_used_words_and_ranges():
    lx, d = _support(["cab", "cable", "camel", "candy", "cobra"], used=["cab"], ranges=[("camel", "camel")])
    s = build_support(d, lx)
    assert "cable" in s and "candy" in s and "cab" not in s and "camel" not in s and "cobra" not in s
    assert len(s) == 2
    assert PASS in build_support(d, lx, special=(PASS,))


def test_score_fork_labels_and_invalid_reports():
    lx, d = _support(["cable", "candle", "candy", "canoe"])
    rec = {"fork_id": "x", "status": "ok", "kind": "guesser1", "turn": 1, "support": d,
           "raw_output": json.dumps({"receiver_word_forecast": {"entries": [{"word": "candle", "probability": 0.7},
                                                                            {"word": "PASS", "probability": 0.1}],
                                                                "other_mass": 0.2},
                                     "block_probability": 0.8})}
    audit = {"turn": 1, "w1": "candle", "guesser2": {"canonical": {"action": "pass", "word": None}},
             "defender": {"canonical": {}}, "blocked_guesser1": True}
    out = score_fork(rec, audit, lx)
    assert out["answer"] == {"receiver_word": PASS, "intended_blocked": True}
    assert out["scores"]["receiver_word"]["q_truth"] == pytest.approx(0.1)
    assert out["scores"]["block_probability"]["brier"] == pytest.approx(1 - 2 * 0.2 ** 2)
    bad = dict(rec, raw_output=json.dumps({"receiver_word_forecast": {"entries": [{"word": "zebra", "probability": 1}],
                                                                      "other_mass": 0}, "block_probability": 2}))
    o2 = score_fork(bad, audit, lx)
    assert o2["scores"]["receiver_word"]["brier"] == -1 and o2["scores"]["block_probability"]["brier"] == -1
    iw = {"fork_id": "y", "status": "ok", "kind": "intended_word", "turn": 1, "support": d,
          "raw_output": json.dumps({"entries": [{"word": "candy", "probability": 1.0}], "other_mass": 0.0})}
    o3 = score_fork(iw, audit, lx)
    assert o3["answer"] == "candle" and o3["scores"]["intended_word"]["brier"] == -1  # confident and wrong
    # infrastructure-unavailable: counted, never scored
    o4 = score_fork({**iw, "status": "unavailable"}, audit, lx)
    assert o4["scores"] is None
    cal = forecast_calibration([{"forecasts": [dict(o3, model_id="m", seat="defender"),
                                               dict(o4, model_id="m", seat="defender")]}])
    s = cal["m"]["intended_word@defender"]
    assert s["scheduled"] == 2 and s["unavailable"] == 1 and s["top1_accuracy"] == 0.0


class _Msgs:
    def __init__(self):
        self.calls = []

    async def create(self, **kw):
        self.calls.append(kw)
        text = '{"action": "clue", "word": "cable", "clue": "rope"}' if len(self.calls) == 1 else \
            '{"entries": [], "other_mass": 1.0}'
        return {"id": f"m{len(self.calls)}", "model": "x", "stop_reason": "end_turn",
                "content": [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": text}],
                "usage": {"input_tokens": 10, "output_tokens": 3}}


class _Client:
    def __init__(self):
        self.messages = _Msgs()


def test_anthropic_fork_replays_own_answer_then_asks():
    c = _Client()
    ad = AnthropicMessagesAdapter(ModelConfig(id="a", provider="anthropic", model="m", max_output_tokens=100,
                                              credential_env="ANTHROPIC_API_KEY"), client=c)
    req = DecisionRequest("d", "guesser1", "act", "SYS", "PLAY", "g1", {"type": "object"}, 100,
                          keep_conversation=True)
    r = asyncio.run(ad.decide(req))
    assert "tools" not in c.messages.calls[0] and r.conversation[-1]["role"] == "assistant"
    before = json.dumps(r.conversation)
    fr = DecisionRequest("d/fork", "guesser1", "fork_guesser1", "SYS", "FORECAST?", "f", {"type": "object"}, 100)
    asyncio.run(ad.fork(fr, r.conversation))
    msgs = c.messages.calls[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"][0]["signature"] == "sig" and msgs[2]["content"] == "FORECAST?"
    assert c.messages.calls[1]["output_config"]["format"]["schema"] == {"type": "object"}
    assert json.dumps(r.conversation) == before  # original transcript untouched


# ---- Codex review fixes on PR #2 -------------------------------------------------

def test_scheduled_fork_without_result_reported_as_interrupted(tmp_path):
    from contact_bench.runner.store import RunStore

    s = RunStore(tmp_path)
    lx, d = _support(["cable", "candle"])
    base = {"fork_id": "g/t001/guesser2/respond/fork", "game_id": "g", "turn": 1, "seat": "guesser2",
            "kind": "intended_word", "model_id": "m", "support": d}
    s.append_forecast({**base, "status": "scheduled"})          # crash before the fork result
    s.append_forecast({**base, "fork_id": "other", "status": "scheduled"})
    s.append_forecast({**base, "fork_id": "other", "status": "ok",
                       "raw_output": '{"entries": [], "other_mass": 1.0}'})
    recs = {r["fork_id"]: r for r in RunStore(tmp_path).forecasts("g")}
    assert recs["g/t001/guesser2/respond/fork"]["status"] == "unavailable"
    assert recs["g/t001/guesser2/respond/fork"]["error"] == "interrupted"
    assert recs["other"]["status"] == "ok"
    cal = forecast_calibration([{"forecasts": [dict(score_fork(r, {"turn": 1, "w1": "candle"}, lx), seat="guesser2")
                                               for r in recs.values()]}])
    assert cal["m"]["intended_word@guesser2"]["scheduled"] == 2
    assert cal["m"]["intended_word@guesser2"]["unavailable"] == 1


def test_markers_written_before_decisions(tmp_path):
    r = Runner(_cfg("fork"), tmp_path / "r")
    asyncio.run(r.run())
    lines = [json.loads(l) for l in (tmp_path / "r" / "forecasts.jsonl").read_text().splitlines()]
    sched = {l["fork_id"] for l in lines if l["status"] == "scheduled"}
    final = {l["fork_id"] for l in lines if l["status"] != "scheduled"}
    assert sched == final and sched


def test_malformed_report_without_outcomes_is_not_scored():
    lx, d = _support(["cable", "candle"])
    rec = {"fork_id": "x", "status": "ok", "kind": "guesser1", "turn": 1, "support": d, "raw_output": "nonsense"}
    # sealed responses never collected (e.g. early stop on a public clue hit)
    out = score_fork(rec, {"turn": 1, "w1": "candle"}, lx)
    assert out["answer"] == {"receiver_word": None, "intended_blocked": None}
    assert out["scores"]["receiver_word"]["brier"] is None
    assert out["scores"]["block_probability"]["brier"] is None
    s = forecast_calibration([{"forecasts": [dict(out, model_id="m", seat="guesser1")]}])["m"]
    assert s["receiver_word@guesser1"]["observed_with_answer"] == 0
    assert s["receiver_word@guesser1"]["mean_brier_invalid_as_minus_one"] is None


def test_fork_context_overflow_raised_before_sending():
    from contact_bench.engine.game import DecisionSpec
    from contact_bench.policies.llm import ContextOverflowError, Limiters, LLMAgent
    from contact_bench.providers.fake import FakeAdapter

    m = ModelConfig(id="f", provider="fake", model="f", max_output_tokens=1000, context_window_tokens=6000)
    ad = FakeAdapter(m)
    sent = []
    orig = ad.fork

    async def spy(*a, **k):
        sent.append(1)
        return await orig(*a, **k)

    ad.fork = spy
    agent = LLMAgent(model=m, adapter=ad, seat="guesser2", clue_max_characters=100, turn_limit=5,
                     limiters=Limiters(1, 1))
    spec = DecisionSpec("g", 1, "guesser2", "respond",
                        {"role": "guesser2", "phase": "respond", "prefix": "", "used_words": []}, "s", {})
    huge = {"obs": {}, "history": "x" * 30000}  # retained transcript far beyond the window
    with pytest.raises(ContextOverflowError):
        asyncio.run(agent.fork(spec, "g/fork", huge, kind="intended_word", prompt="Q"))
    assert not sent


def test_fork_context_overflow_recorded_unavailable(tmp_path, monkeypatch):
    from contact_bench.policies.llm import ContextOverflowError, LLMAgent
    from contact_bench.runner.store import RunStore

    async def boom(self, *a, **k):
        raise ContextOverflowError("too big")

    monkeypatch.setattr(LLMAgent, "fork", boom)
    st = asyncio.run(Runner(_cfg("fork"), tmp_path / "r").run())
    assert not st["halted"] and st["complete_games"] == st["planned_games"]
    forks = RunStore(tmp_path / "r").forecasts()
    assert forks and all(f["status"] == "unavailable" and f["error"].startswith("context_overflow") for f in forks)


def test_plan_counts_fork_calls():
    from contact_bench.runner.run import load_lexicons
    from contact_bench.runner.schedule import build_schedule, run_plan
    from contact_bench.runner.tasks import generate_tasks

    def plan(mode):
        c = _cfg(mode)
        vs, vc = load_lexicons(c)
        tasks = generate_tasks(v_secret=vs, v_contact=vc, count=2, seed=1, split="development",
                               initial_prefix_length=1, turn_limit=5, clue_max_characters=100)
        return run_plan(c, tasks, build_schedule(c, tasks)[1])

    off, fk = plan("off"), plan("fork")
    L, games = 5, off["raw_games"]
    assert off["maximum_paid_decisions"] == 4 * L * games
    assert fk["maximum_paid_decisions"] == 7 * L * games and fk["forecast_fork_calls_included"]


def test_resources_include_fork_calls(tmp_path):
    asyncio.run(Runner(_cfg("fork"), tmp_path / "r").run())
    rr = Runner(_cfg("fork"), tmp_path / "r", replay_only=True)
    rr.prepare()
    res = analyze(tmp_path / "r", [asyncio.run(rr.play(g)) for g in rr.games], resamples=0, seed=1,
                  penalty_scale=2.5, elo_center=1500)
    n_forks = len(RunStore(tmp_path / "r").forecasts())
    fork_reqs = sum(v["requests"] for m in res["resources"].values() for s, v in m.items() if s.endswith("/fork"))
    assert n_forks and fork_reqs == n_forks
    assert all(v.get("input_tokens", 0) > 0 for m in res["resources"].values() for s, v in m.items()
               if s.endswith("/fork"))


def test_failed_fork_accounting(tmp_path, monkeypatch):
    from contact_bench.policies.llm import ContextOverflowError, LLMAgent
    from contact_bench.providers.base import InfrastructureError, TransportAttempt

    calls = {"n": 0}

    async def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] % 2:
            raise ContextOverflowError("too big")       # never sent
        e = InfrastructureError("503", category="server")
        # two successful lookup turns, then a final turn failing three times:
        # the error carries only the final turn's attempts
        e.attempts = [TransportAttempt(i, 0.0, 0.1, "error", "server") for i in (1, 2, 3)]
        e.fork_requests_sent, e.fork_cost = 5, 0.03
        raise e

    monkeypatch.setattr(LLMAgent, "fork", flaky)
    asyncio.run(Runner(_cfg("fork"), tmp_path / "r").run())
    rr = Runner(_cfg("fork"), tmp_path / "r", replay_only=True)
    rr.prepare()
    res = analyze(tmp_path / "r", [asyncio.run(rr.play(g)) for g in rr.games], resamples=0, seed=1,
                  penalty_scale=2.5, elo_center=1500)
    forks = RunStore(tmp_path / "r").forecasts()
    sent = [f for f in forks if f.get("requests_sent")]
    unsent = [f for f in forks if not f.get("requests_sent")]
    assert sent and unsent
    roles = [v for m in res["resources"].values() for s, v in m.items() if s.endswith("/fork")]
    assert sum(v.get("requests", 0) for v in roles) == len(sent)
    assert sum(v.get("transport_attempts", 0) for v in roles) == 5 * len(sent)
    assert sum(v.get("cost_estimate", 0) for v in roles) == pytest.approx(0.03 * len(sent))
    assert sum(v.get("forks_not_sent", 0) for v in roles) == len(unsent)
