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
