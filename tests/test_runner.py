"""Runner, recovery, replay, analysis and export tests (spec 18.2/18.4)."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from contact_bench.analysis.analyze import analyze
from contact_bench.analysis.rating import connected_components, fit_ratings, match_points
from contact_bench.config import BenchConfig, ModelConfig
from contact_bench.export.public import ExportLeakError, export_public, scan_for_secrets
from contact_bench.forecasts.audit import build_item_bank, run_shadow_audit
from contact_bench.providers.base import (
    AdapterResponse, InfrastructureError, NormalizedUsage, ProviderAdapter, RetryPolicy,
)
from contact_bench.providers.fake import FakeAdapter, legal_action, parse_observation
from contact_bench.runner.run import LiveModeError, Runner, validate_config
from contact_bench.runner.store import RunStore

REPO = Path(__file__).resolve().parents[1]


def cfg(models, *, tasks=3, L=6, schedule="balanced_round_robin", lexicon="lexicons/dev_fixture_manifest.json",
        **extra) -> BenchConfig:
    return BenchConfig.model_validate({
        "name": "t", "base_dir": str(REPO), "lexicon": {"manifest": lexicon},
        "protocol": {"turn_limit": L}, "scoring": {"development_rollouts": 64, "cache_dir": ".cache/test_reference"},
        "tasks": {"tasks_per_pair": tasks, "generation_seed": 5}, "tournament": {"schedule": schedule},
        "models": models, "execution": {"game_concurrency": 4, "backoff_base_seconds": 0.0}, **extra,
    })


SCRIPTED = [
    {"id": "fl", "provider": "scripted", "policy": "first_last_two_guess"},
    {"id": "pack", "provider": "scripted", "policy": "combined_fresh_shuffle", "defender_policy": "random_3"},
]


class Programmable(ProviderAdapter):
    """Offline adapter whose behaviour is a function of the request."""

    provider = "fake"
    api_family = "fake"

    def __init__(self, model_config, fn, **kw):
        super().__init__(model_config, retry=RetryPolicy(max_attempts=2, base_seconds=0, deadline_seconds=5), **kw)
        self.fn = fn
        self.calls = []

    def preflight(self, *, require_credentials=False):
        return {}

    async def send_once(self, request):
        self.calls.append((request.decision_id, request.seat, request.phase))
        out = self.fn(request)
        if isinstance(out, Exception):
            raise out
        return AdapterResponse(output_text=json.dumps(out), provider="fake", api_family="fake",
                               usage=NormalizedUsage(input_tokens=10, output_tokens=5))


def test_offline_round_robin_replay_and_analysis(tmp_path):
    c = cfg(SCRIPTED + [{"id": "fake", "provider": "fake", "model": "fake-1", "max_output_tokens": 9000}])
    r = Runner(c, tmp_path / "run1")
    st = asyncio.run(r.run())
    assert st["planned_games"] == 3 * 2 * 3 and st["complete_games"] == st["planned_games"]
    rep = asyncio.run(Runner(c, tmp_path / "run1", replay_only=True).replay())
    assert rep["equivalent"]
    rr = Runner(c, tmp_path / "run1", replay_only=True)
    rr.prepare()
    recs = [asyncio.run(rr.play(g)) for g in rr.games]
    res = analyze(tmp_path / "run1", recs, resamples=20, seed=1, penalty_scale=2.5, elo_center=1500)
    assert res["balanced_complete"] and res["rating"]["converged"]
    assert abs(sum(res["rating"]["elo"].values()) - 1500 * 3) < 1e-6
    for f in res["fixtures"]:
        assert f["points_a"] + f["points_b"] == 1.0
    adv = [res["model_stats"][m]["mean_paired_cost_advantage"]["value"] for m in res["models"]]
    assert abs(sum(adv)) < 1e-9  # balanced schedule sums to zero
    assert (tmp_path / "run1" / "analysis" / "report.md").exists()
    rd = res["role_diagnostics"]
    m = next(iter(rd))
    assert "intended_word_blocked_per_clue_turn" in rd[m]["defense"]["rates"]
    assert "matches_blocked_per_registered_match" in rd[m]["offense"]["rates"]
    assert "Gameplay metrics" in (tmp_path / "run1" / "analysis" / "report.md").read_text()
    for m, v in rd.items():
        for k, x in ((v.get("seat") or {}).get("self_contained") or {}).items():
            if x is not None and not k.endswith(("_n", "_turns")):
                assert 0.0 <= x <= 1.0
    # export contains no credentials and no credential env names
    out = export_public(tmp_path / "run1", tmp_path / "exp", res, recs)
    assert not scan_for_secrets(out)
    assert "credential_env" not in (out / "manifest.json").read_text()


def test_offline_refuses_paid_models_and_live_requires_budget(tmp_path):
    m = SCRIPTED + [{"id": "oa", "provider": "openai", "model": "some-model", "max_output_tokens": 9000,
                     "credential_env": "OPENAI_API_KEY"}]
    with pytest.raises(LiveModeError):
        Runner(cfg(m), tmp_path / "x")
    with pytest.raises(LiveModeError):
        Runner(cfg(m), tmp_path / "y", live=True)


def test_live_placeholder_rejected(tmp_path):
    from contact_bench.providers.base import AdapterConfigError
    m = SCRIPTED + [{"id": "oa", "provider": "openai", "model": "REPLACE_WITH_VERIFIED_MODEL_ID",
                     "max_output_tokens": 9000, "credential_env": "OPENAI_API_KEY"}]
    with pytest.raises(AdapterConfigError):
        validate_config(cfg(m), live=True)


def test_blocklist_output_capacity_preflight():
    from contact_bench.providers.base import AdapterConfigError
    m = SCRIPTED + [{"id": "fk", "provider": "fake", "model": "f", "max_output_tokens": 50}]
    with pytest.raises(AdapterConfigError):
        validate_config(cfg(m))


def _two_model_cfg(tasks=1, L=4):
    return cfg([{"id": "atk", "provider": "fake", "model": "p", "max_output_tokens": 9000},
                {"id": "def", "provider": "fake", "model": "q", "max_output_tokens": 9000}],
               tasks=tasks, L=L, lexicon="lexicons/mechanics_fixture_manifest.json")


def _choice_world(fail_choice: dict):
    """Attackers play first/last; defender blocks only Guesser 1's first candidate."""

    def play(req):
        obs = parse_observation(req.user_prompt)
        if req.seat == "defender":
            c = obs["secret_candidates"][0]
            return {"action": "block", "words": [c] if c != obs["secret"] else []}
        if req.phase == "choice" and fail_choice["on"]:
            return InfrastructureError("timeout", category="timeout", retryable=True)
        return legal_action(obs)

    return play, play


def test_resume_pending_choice_without_resampling(tmp_path):
    c = _two_model_cfg()
    flag = {"on": True}
    atk_fn, def_fn = _choice_world(flag)
    a1, d1 = Programmable(c.models[0], atk_fn), Programmable(c.models[1], def_fn)
    r = Runner(c, tmp_path / "run", adapters={"atk": a1, "def": d1})
    st = asyncio.run(r.run())
    assert st["pending_games"] >= 1
    store = RunStore(tmp_path / "run")
    n_before = len(store.decisions())
    rows = {x["game_id"]: x for x in store.game_rows()}
    assert any(x["outcome_status"] == "infrastructure_incomplete" for x in rows.values())
    # resume: choice now succeeds; earlier phases are reused, not re-requested
    flag["on"] = False
    a2, d2 = Programmable(c.models[0], atk_fn), Programmable(c.models[1], def_fn)
    r2 = Runner(c, tmp_path / "run", adapters={"atk": a2, "def": d2})
    st2 = asyncio.run(r2.run())
    assert st2["pending_games"] == 0
    resumed = {d for d, _, p in a2.calls + d2.calls}
    before = set(list(store.decisions())[:n_before])
    # every phase requested on resume was genuinely pending (never re-sampled)
    assert resumed and not (resumed & before)
    assert any(p == "choice" for _, _, p in a2.calls + d2.calls)
    assert not RunStore(tmp_path / "run").duplicate_decisions
    rep = asyncio.run(Runner(c, tmp_path / "run", replay_only=True).replay())
    assert rep["equivalent"]


def test_decision_ids_distinguish_phases(tmp_path):
    c = _two_model_cfg()
    atk_fn, def_fn = _choice_world({"on": False})
    r = Runner(c, tmp_path / "run", adapters={"atk": Programmable(c.models[0], atk_fn),
                                              "def": Programmable(c.models[1], def_fn)})
    asyncio.run(r.run())
    ids = list(RunStore(tmp_path / "run").decisions())
    choice = [i for i in ids if i.endswith("/choice")]
    assert choice
    for i in choice:
        assert i.replace("/choice", "/respond") in ids or i.replace("/choice", "/act") in ids


def test_budget_stop_then_resume(tmp_path):
    c = _two_model_cfg(tasks=2)
    atk_fn, def_fn = _choice_world({"on": False})
    ad = lambda: {"atk": Programmable(c.models[0], atk_fn), "def": Programmable(c.models[1], def_fn)}
    r = Runner(c, tmp_path / "run", live=True, max_requests=3, adapters=ad())
    st = asyncio.run(r.run())
    assert st["budget_stopped"] and st["pending_games"] > 0
    assert r.budget.requests_used <= 3
    r2 = Runner(c, tmp_path / "run", live=True, max_requests=1000, adapters=ad())
    st2 = asyncio.run(r2.run())
    assert st2["pending_games"] == 0


def test_fatal_error_halts_provider_and_retries_bounded(tmp_path):
    c = _two_model_cfg()
    calls = {"n": 0}

    def boom(req):
        calls["n"] += 1
        return InfrastructureError("bad key", category="auth", fatal=True)

    r = Runner(c, tmp_path / "run", adapters={"atk": Programmable(c.models[0], boom),
                                              "def": Programmable(c.models[1], boom)})
    st = asyncio.run(r.run())
    assert st["halted_credentials"] and calls["n"] <= 2  # fatal: not retried, credential paused
    assert st["pending_games"] == st["planned_games"]


def test_fatal_billing_error_pauses_only_that_providers_games(tmp_path):
    # three models: two scripted (always available) and one failing LLM
    c = cfg(SCRIPTED + [{"id": "broke", "provider": "fake", "model": "f", "max_output_tokens": 9000}],
            tasks=1, L=3, lexicon="lexicons/mechanics_fixture_manifest.json")
    bad = Programmable(c.models[2], lambda req: InfrastructureError("402 credits depleted",
                                                                    category="quota_exhausted", fatal=True))
    st = asyncio.run(Runner(c, tmp_path / "run", adapters={"broke": bad}).run())
    assert "fake:broke" in st["halted_credentials"] and st["fatal_failures"] == ["credential:fake:broke"]
    rows = {r["game_id"]: r for r in RunStore(tmp_path / "run").game_rows()}
    for gid, r in rows.items():
        if "broke" not in gid:
            assert r["status"] == "complete" and r["collection_status"] == "complete"  # unaffected
        elif r["status"] == "complete":
            # only a publicly proven win may complete without the paused provider
            assert r["outcome_status"] == "solved" and r["collection_status"] == "incomplete"


def test_duplicate_decision_ignored(tmp_path):
    s = RunStore(tmp_path)
    assert s.record_decision({"decision_id": "a/b", "raw_output": 1})
    assert not s.record_decision({"decision_id": "a/b", "raw_output": 2})
    s2 = RunStore(tmp_path)
    assert s2.decisions()["a/b"]["raw_output"] == 1


def test_fake_refusal_counts_as_invalid_action(tmp_path):
    c = cfg([{"id": "ref", "provider": "fake", "model": "f", "max_output_tokens": 9000, "fake_behavior": "refusal"},
             {"id": "fl", "provider": "scripted"}], tasks=1, L=2, lexicon="lexicons/mechanics_fixture_manifest.json")
    r = Runner(c, tmp_path / "run")
    asyncio.run(r.run())
    g = [x for x in Path(tmp_path / "run" / "games").glob("*ref-atk-fl.json")][0]
    rec = json.loads(g.read_text())
    assert all(e["type"] == "invalid_action" for e in rec["public_history"])
    assert rec["summary"]["outcome_status"] == "capped"


def test_context_overflow_halts(tmp_path):
    c = cfg([{"id": "tiny", "provider": "fake", "model": "f", "max_output_tokens": 10, "context_window_tokens": 100},
             {"id": "fl", "provider": "scripted"}], tasks=1, L=2)
    r = Runner(c, tmp_path / "run")
    st = asyncio.run(r.run())
    assert st["halted"] and "context window" in st["halted"]


def test_export_leak_detection(tmp_path, monkeypatch):
    synthetic = "sk-test-SYNTHETICKEY1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", synthetic)
    c = cfg([{"id": "fk", "provider": "fake", "model": "f", "max_output_tokens": 9000,
              "parameters": {"note": synthetic}}, {"id": "fl", "provider": "scripted"}], tasks=1, L=2,
            lexicon="lexicons/mechanics_fixture_manifest.json")
    r = Runner(c, tmp_path / "run")
    asyncio.run(r.run())
    rr = Runner(c, tmp_path / "run", replay_only=True)
    rr.prepare()
    recs = [asyncio.run(rr.play(g)) for g in rr.games]
    res = analyze(tmp_path / "run", recs, resamples=5, seed=1, penalty_scale=2.5, elo_center=1500)
    with pytest.raises(ExportLeakError):
        export_public(tmp_path / "run", tmp_path / "exp", res, recs)
    assert not (tmp_path / "exp").exists()


def test_frozen_item_bank_and_shadow_audit(tmp_path):
    c = cfg(SCRIPTED + [{"id": "fake", "provider": "fake", "model": "f", "max_output_tokens": 9000}], tasks=2, L=4)
    asyncio.run(Runner(c, tmp_path / "run").run())
    items = asyncio.run(build_item_bank(Runner(c, tmp_path / "run", replay_only=True)))
    assert items and all("answer_intended_word" in i for i in items)
    branches = {i["provenance"]["branch"] for i in items}
    assert branches  # includes hidden branches when they occur; never filtered on outcome
    for i in items:
        assert "answer_intended_word" not in json.dumps(i["receiver_observation"])
    res = asyncio.run(run_shadow_audit(items[:5], FakeAdapter(ModelConfig(id="f", provider="fake", model="f",
                                                                          max_output_tokens=100))))
    s = res["summary"]["guesser2"]
    assert s["observed"] == 5 and s["mean_brier_overall_invalid_as_minus_one"] is not None


def test_rating_properties():
    m = ["a", "b", "c"]
    tied = [("a", "b", 0.5), ("b", "c", 0.5), ("a", "c", 0.5)] * 4
    fit = fit_ratings(m, tied)
    assert fit.converged and max(fit.elo.values()) - min(fit.elo.values()) < 1e-6
    unbeaten = [("a", "b", 1.0)] * 20
    f2 = fit_ratings(["a", "b"], unbeaten)
    assert f2.converged and abs(f2.strengths["a"]) < 20  # penalty bounds undefeated ratings
    assert connected_components(["a", "b", "c", "d"], [("a", "b"), ("c", "d")]) == [["a", "b"], ["c", "d"]]
    from fractions import Fraction
    assert match_points(Fraction(3), Fraction(4)) + match_points(Fraction(4), Fraction(3)) == 1


def test_median_and_geometric_mean_costs():
    from contact_bench.analysis.analyze import _geomean, _median
    assert _median([1.0, 3.0, 100.0]) == 3.0 and _median([1.0, 3.0, 5.0, 7000.0]) == 4.0
    assert _median([]) is None
    assert abs(_geomean([1.0, 100.0]) - 10.0) < 1e-9


def test_model_specific_fatal_error_pauses_only_that_model(tmp_path):
    c = cfg(SCRIPTED + [{"id": "badmodel", "provider": "fake", "model": "f", "max_output_tokens": 9000},
                        {"id": "goodmodel", "provider": "fake", "model": "g", "max_output_tokens": 9000}],
            tasks=1, L=3, lexicon="lexicons/mechanics_fixture_manifest.json")
    bad = Programmable(c.models[2], lambda req: InfrastructureError("404 no such model",
                                                                   category="invalid_model", fatal=True))
    st = asyncio.run(Runner(c, tmp_path / "run", adapters={"badmodel": bad}).run())
    assert "badmodel" in st["halted_models"] and not st["halted_providers"]
    assert st["fatal_failures"] == ["model:badmodel"]
    rows = RunStore(tmp_path / "run").game_rows()
    # the other model of the same provider kept playing
    assert any(r["status"] == "complete" and "goodmodel" in r["game_id"] for r in rows)


def test_cli_exit_code_reflects_fatal_failures(tmp_path, monkeypatch):
    from contact_bench.cli import main as cli
    monkeypatch.setattr(cli, "_run", lambda *a, **k: {"halted": None, "fatal_failures": ["provider:google"]})
    monkeypatch.setattr(cli, "load_config", lambda p: cfg(SCRIPTED))
    assert cli.main(["--runs-dir", str(tmp_path), "run", "x.yaml", "--offline"]) == 3
    monkeypatch.setattr(cli, "_run", lambda *a, **k: {"halted": None, "fatal_failures": []})
    assert cli.main(["--runs-dir", str(tmp_path), "run", "x.yaml", "--offline"]) == 0


def test_auth_failure_is_scoped_to_the_failing_credential(tmp_path):
    c = cfg(SCRIPTED + [{"id": "key_a", "provider": "openai", "model": "m", "max_output_tokens": 9000,
                         "credential_env": "KEY_A"},
                        {"id": "key_b", "provider": "openai", "model": "m", "max_output_tokens": 9000,
                         "credential_env": "KEY_B"}], tasks=1, L=3, lexicon="lexicons/mechanics_fixture_manifest.json")
    from contact_bench.providers.fake import legal_action, parse_observation
    bad = Programmable(c.models[2], lambda req: InfrastructureError("401", category="auth", fatal=True))
    good = Programmable(c.models[3], lambda req: legal_action(parse_observation(req.user_prompt)))
    st = asyncio.run(Runner(c, tmp_path / "run", live=True, max_requests=1000,
                            adapters={"key_a": bad, "key_b": good}).run())
    assert list(st["halted_credentials"]) == ["openai:KEY_A"]
    rows = RunStore(tmp_path / "run").game_rows()
    assert any(r["status"] == "complete" and "key_b" in r["game_id"] and "key_a" not in r["game_id"] for r in rows)
