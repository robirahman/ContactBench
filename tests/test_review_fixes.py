"""Regression tests for the Codex review findings on PR #1."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from contact_bench.config import ModelConfig, PriceTable
from contact_bench.providers.anthropic_adapter import AnthropicMessagesAdapter
from contact_bench.providers.base import (
    AdapterResponse, DecisionRequest, InfrastructureError, NormalizedUsage, ProviderAdapter, RetryPolicy,
)
from contact_bench.runner.budget import Budget, BudgetExhausted, BudgetGate, estimate_cost
from contact_bench.runner.run import Runner
from contact_bench.runner.store import RunStore
from contact_bench.runner.tasks import load_tasks, save_tasks

from .test_runner import SCRIPTED, cfg

M = ModelConfig(id="m", provider="fake", model="x", max_output_tokens=10)


def test_torn_jsonl_tail_is_repaired_before_append(tmp_path):
    s = RunStore(tmp_path)
    s.record_decision({"decision_id": "a", "raw_output": 1})
    with (tmp_path / "decisions.jsonl").open("a") as f:
        f.write('{"decision_id": "b", "raw_out')  # crash mid-write
    s2 = RunStore(tmp_path)
    assert set(s2.decisions()) == {"a"}
    assert s2.record_decision({"decision_id": "c", "raw_output": 3})
    s3 = RunStore(tmp_path)
    assert set(s3.decisions()) == {"a", "c"}  # the new record survives a restart
    assert "raw_out" in (tmp_path / "decisions.jsonl.torn").read_text()


class Flaky(ProviderAdapter):
    provider = "fake"
    api_family = "fake"

    def __init__(self, fails):
        super().__init__(M, retry=RetryPolicy(max_attempts=3, base_seconds=0, deadline_seconds=5))
        self.fails = fails
        self.sent = 0

    async def send_once(self, request):
        self.sent += 1
        if self.sent <= self.fails:
            raise InfrastructureError("503", category="server", retryable=True, retry_after=0)
        return AdapterResponse(output_text="{}", usage=NormalizedUsage(input_tokens=1, output_tokens=1))


def _req():
    return DecisionRequest("d", "guesser1", "act", "s", "u", "n", {})


def test_request_budget_is_enforced_per_transport_attempt():
    a = Flaky(fails=5)
    b = Budget(max_requests=1, max_usd=None)
    with pytest.raises(BudgetExhausted):
        asyncio.run(a.decide(_req(), gate=BudgetGate(b, M, 10)))
    assert a.sent == 1 and b.requests_used == 1  # the retry was never sent


def test_retries_within_budget_each_count():
    a = Flaky(fails=2)
    b = Budget(max_requests=3, max_usd=None)
    asyncio.run(a.decide(_req(), gate=BudgetGate(b, M, 10)))
    assert a.sent == 3 and b.requests_used == 3


def test_shadow_audit_respects_request_cap_across_retries():
    from contact_bench.forecasts.audit import run_shadow_audit

    obs = {"clue_max_characters": 100, "turn_limit": 5, "contact_candidates": ["aa", "bb"]}
    items = [{"item_id": f"i{k}", "receiver_observation": obs, "defender_observation": obs,
              "answer_intended_word": "aa"} for k in range(3)]
    a = Flaky(fails=100)
    b = Budget(max_requests=2, max_usd=None)
    res = asyncio.run(run_shadow_audit(items, a, gate=BudgetGate(b, M, 10)))
    assert a.sent == 2 and b.requests_used == 2
    assert all(r.get("unavailable") for r in res["results"])


def test_anthropic_cache_tokens_included_in_input_and_cost():
    ad = AnthropicMessagesAdapter(ModelConfig(id="a", provider="anthropic", model="m", max_output_tokens=100,
                                              credential_env="ANTHROPIC_API_KEY"))
    msg = {"content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn", "model": "m",
           "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 1000,
                     "cache_creation_input_tokens": 200}}
    r = ad.parse_response(msg, {"max_tokens": 100})
    assert r.usage.input_tokens == 1210 and r.usage.cached_input_tokens == 1000
    p = PriceTable(as_of="2026-11-03", input_per_mtok=1.0, output_per_mtok=1.0, cached_input_per_mtok=0.1,
                   cache_write_per_mtok=1.25)
    cost = estimate_cost(p, r.usage)
    assert cost == pytest.approx((10 * 1.0 + 1000 * 0.1 + 200 * 1.25 + 5 * 1.0) / 1e6)


def test_task_manifest_provenance_validated(tmp_path):
    c = cfg(SCRIPTED, tasks=2)
    r = Runner(c, tmp_path / "gen")
    r.prepare()
    tasks = load_tasks(tmp_path / "gen" / "private" / "tasks_private.jsonl")
    for field, val in [("turn_limit", 99), ("contact_lexicon_sha256", "0" * 64), ("clue_max_characters", 7),
                       ("initial_prefix_length", 2)]:
        p = tmp_path / f"tasks_{field}.jsonl"
        save_tasks(p, [replace(tasks[0], **{field: val})])
        c2 = cfg(SCRIPTED, tasks=2).model_copy(update={"tasks": c.tasks.model_copy(update={"manifest": str(p)})})
        with pytest.raises(ValueError, match="provenance"):
            Runner(c2, tmp_path / f"run_{field}").prepare()


def test_per_provider_dollar_cap():
    pt = PriceTable(as_of="x", input_per_mtok=1.0, output_per_mtok=1.0)
    ma = ModelConfig(id="a", provider="anthropic", model="m", max_output_tokens=1000, prices=pt,
                     credential_env="ANTHROPIC_API_KEY")
    mg = ModelConfig(id="g", provider="google", model="m", max_output_tokens=1000, prices=pt)
    b = Budget(None, None, max_usd_by_provider={"google": 0.0025})

    async def go():
        t = await b.reserve(mg, 1000)  # reserves 0.002
        with pytest.raises(BudgetExhausted):
            await b.reserve(mg, 1000)
        await b.reserve(ma, 1000)  # other provider unaffected
        await b.commit(mg, t, NormalizedUsage(input_tokens=500, output_tokens=0), 1)
        assert b.usd_spent_by_provider["google"] == pytest.approx(0.0005)
    asyncio.run(go())


def test_unbilled_failures_not_charged_and_provider_cap_is_local():
    pt = PriceTable(as_of="x", input_per_mtok=1.0, output_per_mtok=1.0)
    m = ModelConfig(id="g", provider="google", model="m", max_output_tokens=1000, prices=pt)
    b = Budget(None, None, max_usd_by_provider={"google": 1.0})
    gate = BudgetGate(b, m, 1000)

    async def go():
        t = await gate.before()
        await gate.after(t, None, False, possibly_billed=False)  # e.g. HTTP 402 before generation
        assert b.usd_spent == 0 and b.requests_used == 1
        t = await gate.before()
        await gate.after(t, None, False, possibly_billed=True)  # e.g. timeout: conservatively charged
        assert b.usd_spent == pytest.approx(0.002)
        b.max_usd_by_provider["google"] = 0.0
        with pytest.raises(BudgetExhausted) as ei:
            await gate.before()
        assert ei.value.provider == "google"
    asyncio.run(go())


def test_anthropic_midstream_network_error_is_retryable():
    import httpx2
    from types import SimpleNamespace

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get_final_message(self):
            raise httpx2.ReadError("connection reset")

    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Stream()))
    ad = AnthropicMessagesAdapter(ModelConfig(id="a", provider="anthropic", model="m", max_output_tokens=32000,
                                              credential_env="ANTHROPIC_API_KEY"), client=client)
    with pytest.raises(InfrastructureError) as ei:
        asyncio.run(ad._call({"max_tokens": 32000}))
    assert ei.value.retryable and ei.value.possibly_billed and ei.value.category == "transient"


def test_non_rate_limit_errors_keep_the_normal_bound():
    a = Flaky(fails=100)  # "server" errors
    a.retry = RetryPolicy(max_attempts=3, rate_limit_attempts=8, base_seconds=0, deadline_seconds=5)
    with pytest.raises(InfrastructureError):
        asyncio.run(a.decide(_req()))
    assert a.sent == 3


def test_stainless_402_is_provider_wide_quota_failure():
    import anthropic
    import httpx2
    from contact_bench.providers._stainless import map_stainless_error

    resp = httpx2.Response(402, request=httpx2.Request("POST", "https://api.example.com/v1/messages"),
                           json={"error": {"message": "credit balance too low"}})
    err = anthropic.APIStatusError("payment required", response=resp, body=None)
    mapped = map_stainless_error(err, anthropic, ())
    assert mapped.category == "quota_exhausted" and mapped.fatal

    from contact_bench.runner.run import PROVIDER_WIDE_FATAL
    assert mapped.category in PROVIDER_WIDE_FATAL


def test_budget_exhaustion_handler_is_provider_local(tmp_path):
    from .test_runner import cfg as rcfg, SCRIPTED
    r = Runner(rcfg(SCRIPTED, tasks=1, L=2, lexicon="lexicons/mechanics_fixture_manifest.json"), tmp_path / "r")
    r.prepare()
    r._on_budget_exhausted(BudgetExhausted("google cap", provider="google"), "fork/x")
    assert r.halted_providers == {"google": "budget: google cap"} and not r.budget_stopped
    r._on_budget_exhausted(BudgetExhausted("global cap"), "d/y")
    assert r.budget_stopped


def test_fork_path_uses_provider_local_budget_handler():
    import inspect
    from contact_bench.runner.run import Runner as R
    src = inspect.getsource(R._schedule_fork)
    assert "_on_budget_exhausted" in src and "budget_stopped = True" not in src


def test_concurrency_overrides_must_be_positive(tmp_path):
    from contact_bench.cli import main as cli
    from .test_runner import cfg as rcfg, SCRIPTED
    import types
    c = rcfg(SCRIPTED)
    for bad in (0, -1):
        with pytest.raises(ValueError):
            cli._with_concurrency(c, types.SimpleNamespace(game_concurrency=bad, provider_concurrency=None))
    ok = cli._with_concurrency(c, types.SimpleNamespace(game_concurrency=3, provider_concurrency=2))
    assert ok.execution.game_concurrency == 3 and ok.execution.per_provider_concurrency == 2


def test_ambiguous_transport_failures_are_charged_conservatively():
    from contact_bench.providers.base import possibly_billed
    assert possibly_billed(InfrastructureError("conn reset", category="transient", retryable=True))
    assert possibly_billed(InfrastructureError("?", category="unknown", fatal=True))
    assert possibly_billed(InfrastructureError("502", category="server", retryable=True))
    assert not possibly_billed(InfrastructureError("402", category="quota_exhausted", fatal=True))
    assert not possibly_billed(InfrastructureError("429", category="rate_limit", retryable=True))
    # through the gate: a server error is charged the reservation, a 402 is not
    pt = PriceTable(as_of="x", input_per_mtok=1.0, output_per_mtok=1.0)
    m = ModelConfig(id="g", provider="google", model="m", max_output_tokens=1000, prices=pt)
    b = Budget(None, 100.0)  # a monetary cap makes reservations non-zero
    a = Flaky(fails=1)  # one "server" error then success
    a.config = m
    asyncio.run(a.decide(_req(), gate=BudgetGate(b, m, 1000)))
    assert b.usd_uncertain == 1


def test_failure_after_a_long_attempt_is_still_retried():
    # A max-effort call that fails after 700 s (longer than the 300 s deadline)
    # must still be retried: the deadline bounds backoff, not time inside attempts.
    now = [0.0]

    class Slow(Flaky):
        async def send_once(self, request):
            now[0] += 700.0
            return await super().send_once(request)

    a = Slow(fails=1)
    a.retry = RetryPolicy(max_attempts=3, base_seconds=1, deadline_seconds=300)
    a._clock = lambda: now[0]

    async def no_sleep(d):
        now[0] += d

    a._sleep = no_sleep
    resp = asyncio.run(a.decide(_req()))
    assert a.sent == 2 and resp.output_text == "{}"
