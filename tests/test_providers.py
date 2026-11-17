"""Offline provider adapter tests: no network access and no real credentials."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pytest
from google.genai import errors as genai_errors

from contact_bench.config import ModelConfig
from contact_bench.providers.anthropic_adapter import AnthropicMessagesAdapter
from contact_bench.providers.base import (
    AdapterConfigError,
    CredentialSource,
    DecisionRequest,
    InfrastructureError,
    NormalizedUsage,
    RetryPolicy,
    sanitize,
)
from contact_bench.providers.fake import FakeAdapter, legal_action
from contact_bench.providers.google_adapter import (
    GeminiGenerateContentAdapter,
    GeminiInteractionsAdapter,
    map_google_error,
)
from contact_bench.providers.openai_adapter import OpenAIResponsesAdapter
from contact_bench.providers.registry import make_adapter
from contact_bench.providers.registry import tested_sdk_versions as sdk_versions

FAKE_KEY = "sk-SYNTHETICTESTKEY1234567890abcdef"
SCHEMA = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"], "additionalProperties": False}


def run(coro):
    return asyncio.run(coro)


def obs(role="guesser1", phase="act", cands=("cable", "camera", "candle"), forecast=False):
    return {
        "role": role,
        "phase": phase,
        "secret_candidates": list(cands),
        "contact_candidates": list(cands),
        "forecast_reports_requested": forecast,
    }


def req(o=None, decision_id="g1/t001/guesser1/act"):
    o = o or obs()
    return DecisionRequest(
        decision_id=decision_id,
        seat=o["role"],
        phase=o["phase"],
        system_prompt="RULES",
        user_prompt="guidance\n\nOBSERVATION (JSON):\n\n" + json.dumps(o),
        schema_name="contact_guesser1",
        json_schema=SCHEMA,
        max_output_tokens=None,
    )


def mc(provider, **kw):
    base = dict(id=f"m_{provider}", provider=provider, model="model-x", max_output_tokens=512)
    base.update(kw)
    return ModelConfig(**base)


class NoSleep:
    def __init__(self):
        self.delays = []

    async def __call__(self, d):
        self.delays.append(d)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def creds():
    return CredentialSource({"OPENAI_API_KEY": FAKE_KEY, "ANTHROPIC_API_KEY": FAKE_KEY, "GEMINI_API_KEY": FAKE_KEY})


# --------------------------------------------------------------------- mocks
class Recorder:
    def __init__(self, result=None, exc=None):
        self.calls = []
        self.result = result
        self.exc = exc

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            e = self.exc.pop(0) if isinstance(self.exc, list) else self.exc
            if e is not None:
                raise e
        return self.result


def openai_client(rec):
    return SimpleNamespace(responses=SimpleNamespace(create=rec))


def anthropic_client(rec):
    return SimpleNamespace(messages=SimpleNamespace(create=rec))


def google_client(rec, gen=None):
    return SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=rec), models=SimpleNamespace(generate_content=gen or rec)))


def openai_response(text='{"action":"x"}', status="completed", refusal=False, usage=True):
    content = [{"type": "refusal", "refusal": "no"}] if refusal else [{"type": "output_text", "text": text}]
    u = {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "input_tokens_details": {"cached_tokens": 20, "cache_write_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 30},
    }
    return {
        "id": "resp_1",
        "model": "model-x-2026",
        "status": status,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "output": [{"type": "reasoning"}, {"type": "message", "content": content}],
        "usage": u if usage else None,
    }


def http_response(status, headers=None):
    request = httpx2.Request("POST", "https://example.invalid/v1")
    return httpx2.Response(status, headers=headers or {}, request=request)


# ---------------------------------------------------------------- base/retry
def test_sanitize_removes_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    s = sanitize(f"failed with key {FAKE_KEY} and Authorization: Bearer abc.def")
    assert FAKE_KEY not in s and "abc.def" not in s


def test_offline_preflight_needs_no_keys(monkeypatch):
    for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    for p in ("openai", "anthropic", "google"):
        a = make_adapter(mc(p))
        a.preflight()
        with pytest.raises(AdapterConfigError, match="missing credential"):
            a.preflight(require_credentials=True)


def test_preflight_rejects_unsupported_and_placeholders():
    with pytest.raises(AdapterConfigError, match="unsupported parameters"):
        make_adapter(mc("anthropic", parameters={"temperature": 0})).preflight()
    with pytest.raises(AdapterConfigError, match="unsupported parameters"):
        make_adapter(mc("openai", parameters={"frequency_penalty": 1})).preflight()
    with pytest.raises(AdapterConfigError, match="placeholders"):
        make_adapter(mc("openai", model="REPLACE_WITH_VERIFIED_MODEL_ID")).preflight()
    with pytest.raises(AdapterConfigError, match="max_output_tokens"):
        make_adapter(mc("google", max_output_tokens=None)).preflight()


def test_registry_selects_google_family():
    assert isinstance(make_adapter(mc("google")), GeminiInteractionsAdapter)
    assert isinstance(make_adapter(mc("google", api_family="generate_content")), GeminiGenerateContentAdapter)
    with pytest.raises(AdapterConfigError):
        make_adapter(ModelConfig(id="s", provider="scripted"))
    v = sdk_versions()
    assert set(v) == {"openai", "anthropic", "google-genai"} and all(v.values())


def test_retry_bounded_and_respects_retry_after():
    sleep, clock = NoSleep(), FakeClock()
    # The fake's transient error is a rate limit, which gets its own (larger) bound.
    a = FakeAdapter(mc("fake", fake_behavior="always_transient"),
                    retry=RetryPolicy(max_attempts=3, rate_limit_attempts=5), sleep=sleep, clock=clock)
    with pytest.raises(InfrastructureError) as ei:
        run(a.decide(req()))
    assert a.calls == 5
    assert sleep.delays == [0.0] * 4  # Retry-After=0 honored instead of backoff
    assert len(ei.value.attempts) == 5 and not ei.value.retryable


def test_retry_then_success_and_no_semantic_retry():
    sleep = NoSleep()
    a = FakeAdapter(mc("fake", fake_behavior="transient_then_ok"), sleep=sleep, clock=FakeClock())
    r = run(a.decide(req()))
    assert a.calls == 2 and [x.outcome for x in r.attempts] == ["error", "ok"]
    # A legal-but-unhelpful or invalid answer is returned, never retried.
    b = FakeAdapter(mc("fake", fake_behavior="invalid_json"), sleep=sleep, clock=FakeClock())
    r2 = run(b.decide(req()))
    assert b.calls == 1 and r2.output_text.startswith("I think")


def test_fatal_not_retried():
    a = FakeAdapter(mc("fake", fake_behavior="auth_error"), sleep=NoSleep(), clock=FakeClock())
    with pytest.raises(InfrastructureError) as ei:
        run(a.decide(req()))
    assert a.calls == 1 and ei.value.fatal and ei.value.category == "auth"


def test_exponential_backoff_without_retry_after():
    sleep = NoSleep()

    class Flaky(FakeAdapter):
        async def send_once(self, request):
            self.calls += 1
            raise InfrastructureError("boom", category="server", retryable=True)

    a = Flaky(mc("fake"), retry=RetryPolicy(max_attempts=3, base_seconds=1.0), sleep=sleep, clock=FakeClock())
    with pytest.raises(InfrastructureError):
        run(a.decide(req()))
    assert len(sleep.delays) == 2 and 0.5 <= sleep.delays[0] <= 1.5 and 1.0 <= sleep.delays[1] <= 3.0


# --------------------------------------------------------------------- fake
def test_fake_legal_policy_and_forecast_envelope():
    assert legal_action(obs()) == {"action": "clue", "word": "cable", "clue": "?"}
    assert legal_action(obs(cands=("candle",))) == {"action": "direct", "word": "candle", "clue": None}
    assert legal_action(obs("guesser2", "respond")) == {"action": "guess", "word": "candle"}
    assert legal_action(obs("defender", "block")) == {"action": "block", "words": []}
    assert legal_action(obs("guesser2", "choice")) == {"action": "reveal"}
    env = legal_action(obs("defender", "block", forecast=True))
    f = env["diagnostics"]["intended_word_forecast"]
    assert env["gameplay"]["action"] == "block"
    assert abs(sum(e["probability"] for e in f["entries"]) + f["other_mass"] - 1) < 1e-9


@pytest.mark.parametrize(
    "behavior,check",
    [
        ("refusal", lambda r: r.refusal and r.output_text is None and r.finish_reason == "refusal"),
        ("truncation", lambda r: r.incomplete and r.output_text and not r.output_text.endswith("}")),
        ("missing_usage", lambda r: r.usage == NormalizedUsage() and r.raw_usage is None),
        ("legal", lambda r: json.loads(r.output_text)["action"] == "clue" and r.usage.input_tokens > 0),
    ],
)
def test_fake_behaviors(behavior, check):
    a = FakeAdapter(mc("fake", fake_behavior=behavior))
    assert check(run(a.decide(req())))


# --------------------------------------------------------------------- openai
def test_openai_request_and_parse():
    rec = Recorder(result=openai_response())
    a = OpenAIResponsesAdapter(mc("openai", parameters={"reasoning": {"effort": "low"}}), client=openai_client(rec), credentials=creds())
    r = run(a.decide(req()))
    kw = rec.calls[0]
    assert kw["store"] is False and kw["max_output_tokens"] == 512
    assert kw["text"]["format"] == {"type": "json_schema", "name": "contact_guesser1", "schema": SCHEMA, "strict": True}
    assert kw["reasoning"] == {"effort": "low"} and "temperature" not in kw
    assert r.output_text == '{"action":"x"}' and r.returned_model == "model-x-2026"
    u = r.usage
    assert (u.input_tokens, u.output_tokens, u.cached_input_tokens, u.reasoning_tokens) == (100, 50, 20, 30)
    assert u.reasoning_included_in_output is True and u.billable_output_tokens() == 50  # no double count


def test_openai_refusal_incomplete_and_missing_usage():
    a = OpenAIResponsesAdapter(mc("openai"), client=openai_client(Recorder(result=openai_response(refusal=True))), credentials=creds())
    r = run(a.decide(req()))
    assert r.refusal and r.output_text is None
    a = OpenAIResponsesAdapter(mc("openai"), client=openai_client(Recorder(result=openai_response(status="incomplete", usage=False))), credentials=creds())
    r = run(a.decide(req()))
    assert r.incomplete and r.finish_reason == "max_output_tokens"
    assert r.usage.input_tokens is None and r.usage.reasoning_included_in_output is None


def _openai_err(cls, status, body=None, headers=None):
    return cls(f"error with {FAKE_KEY}", response=http_response(status, headers), body=body)


@pytest.mark.parametrize(
    "exc,category,retryable,fatal",
    [
        (lambda: _openai_err(openai.RateLimitError, 429, headers={"retry-after": "7"}), "rate_limit", True, False),
        (lambda: _openai_err(openai.RateLimitError, 429, body={"error": {"code": "insufficient_quota"}}), "quota_exhausted", False, True),
        (lambda: openai.APITimeoutError(request=httpx2.Request("POST", "https://x.invalid")), "timeout", True, False),
        (lambda: openai.APIConnectionError(request=httpx2.Request("POST", "https://x.invalid")), "transient", True, False),
        (lambda: _openai_err(openai.InternalServerError, 500), "server", True, False),
        (lambda: _openai_err(openai.AuthenticationError, 401), "auth", False, True),
        (lambda: _openai_err(openai.PermissionDeniedError, 403), "auth", False, True),
        (lambda: _openai_err(openai.NotFoundError, 404), "invalid_model", False, True),
        (lambda: _openai_err(openai.BadRequestError, 400), "bad_request", False, True),
    ],
)
def test_openai_error_mapping(exc, category, retryable, fatal):
    e = exc()
    a = OpenAIResponsesAdapter(mc("openai"), client=openai_client(Recorder(exc=e)), credentials=creds())
    with pytest.raises(InfrastructureError) as ei:
        run(a.send_once(req()))
    err = ei.value
    assert (err.category, err.retryable, err.fatal) == (category, retryable, fatal)
    assert FAKE_KEY not in str(err)
    if category == "rate_limit":
        assert err.retry_after == 7.0
    if category == "timeout":
        assert err.possibly_billed


def test_openai_client_disables_sdk_retries(monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(openai, "AsyncOpenAI", Fake)
    a = OpenAIResponsesAdapter(mc("openai"), credentials=creds())
    a._get_client()
    assert seen["max_retries"] == 0 and seen["api_key"] == FAKE_KEY


def test_decide_retries_rate_limit_then_succeeds():
    rec = Recorder(result=openai_response(), exc=[_openai_err(openai.RateLimitError, 429, headers={"retry-after": "2"}), None])
    sleep = NoSleep()
    a = OpenAIResponsesAdapter(mc("openai"), client=openai_client(rec), credentials=creds(), sleep=sleep, clock=FakeClock())
    r = run(a.decide(req()))
    assert len(rec.calls) == 2 and sleep.delays == [2.0] and r.output_text


# ------------------------------------------------------------------ anthropic
def anthropic_message(stop="end_turn", thinking=None):
    usage = {"input_tokens": 80, "output_tokens": 40, "cache_read_input_tokens": 10, "cache_creation_input_tokens": None}
    if thinking is not None:
        usage["output_tokens_details"] = {"thinking_tokens": thinking}
    return {
        "id": "msg_1",
        "model": "claude-x",
        "stop_reason": stop,
        "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": '{"action":'}, {"type": "text", "text": '"x"}'}],
        "usage": usage,
    }


def test_anthropic_request_and_parse():
    rec = Recorder(result=anthropic_message(thinking=12))
    a = AnthropicMessagesAdapter(
        mc("anthropic", parameters={"thinking": {"type": "adaptive"}, "effort": "low"}),
        client=anthropic_client(rec),
        credentials=creds(),
    )
    r = run(a.decide(req()))
    kw = rec.calls[0]
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "low"}
    assert kw["thinking"] == {"type": "adaptive"} and kw["max_tokens"] == 512
    assert kw["messages"] == [{"role": "user", "content": req().user_prompt}] and kw["system"] == "RULES"
    assert not {"temperature", "top_p", "top_k", "effort"} & set(kw)
    assert r.output_text == '{"action":"x"}'
    assert r.usage.cached_input_tokens == 10 and r.usage.cache_write_tokens is None
    assert r.usage.reasoning_tokens == 12 and r.usage.billable_output_tokens() == 40


def test_anthropic_refusal_and_max_tokens():
    for stop, attr in (("refusal", "refusal"), ("max_tokens", "incomplete")):
        a = AnthropicMessagesAdapter(mc("anthropic"), client=anthropic_client(Recorder(result=anthropic_message(stop))), credentials=creds())
        r = run(a.decide(req()))
        assert getattr(r, attr) and r.finish_reason == stop
    r = run(AnthropicMessagesAdapter(mc("anthropic"), client=anthropic_client(Recorder(result=anthropic_message())), credentials=creds()).decide(req()))
    assert r.usage.reasoning_tokens is None and r.usage.reasoning_included_in_output is None


@pytest.mark.parametrize(
    "cls,status,category,retryable",
    [
        (anthropic.RateLimitError, 429, "rate_limit", True),
        (anthropic.InternalServerError, 529, "server", True),
        (anthropic.AuthenticationError, 401, "auth", False),
        (anthropic.NotFoundError, 404, "invalid_model", False),
        (anthropic.BadRequestError, 400, "bad_request", False),
    ],
)
def test_anthropic_error_mapping(cls, status, category, retryable):
    e = cls(f"bad {FAKE_KEY}", response=http_response(status), body=None)
    a = AnthropicMessagesAdapter(mc("anthropic"), client=anthropic_client(Recorder(exc=e)), credentials=creds())
    with pytest.raises(InfrastructureError) as ei:
        run(a.send_once(req()))
    assert (ei.value.category, ei.value.retryable) == (category, retryable)
    assert FAKE_KEY not in str(ei.value)


def test_anthropic_client_disables_sdk_retries(monkeypatch):
    seen = {}
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: seen.update(kw) or object())
    AnthropicMessagesAdapter(mc("anthropic"), credentials=creds())._get_client()
    assert seen["max_retries"] == 0


# --------------------------------------------------------------------- google
def test_gemini_interactions_request_and_parse():
    resp = {
        "id": "int_1",
        "model": "gemini-x",
        "status": "completed",
        "output_text": '{"action":"x"}',
        "usage": {"total_input_tokens": 90, "total_output_tokens": 20, "total_thought_tokens": 15, "total_tokens": 125, "total_cached_tokens": 5},
    }
    rec = Recorder(result=resp)
    a = GeminiInteractionsAdapter(mc("google", parameters={"thinking_level": "low", "service_tier": "flex"}), client=google_client(rec), credentials=creds())
    r = run(a.decide(req()))
    kw = rec.calls[0]
    assert kw["store"] is False and kw["automatic_continuation"] is False
    assert kw["response_format"] == {"type": "text", "mime_type": "application/json", "schema": SCHEMA}
    assert kw["generation_config"] == {"max_output_tokens": 512, "thinking_level": "low"}
    assert kw["service_tier"] == "flex" and kw["system_instruction"] == "RULES"
    assert r.output_text == '{"action":"x"}'
    assert r.usage.reasoning_included_in_output is False and r.usage.billable_output_tokens() == 35


def test_gemini_interactions_incomplete_and_failed():
    a = GeminiInteractionsAdapter(mc("google"), client=google_client(Recorder(result={"status": "incomplete", "output_text": "{"})), credentials=creds())
    r = run(a.decide(req()))
    assert r.incomplete and r.usage.input_tokens is None
    a = GeminiInteractionsAdapter(mc("google"), client=google_client(Recorder(result={"status": "failed"})), credentials=creds())
    with pytest.raises(InfrastructureError) as ei:
        run(a.send_once(req()))
    assert ei.value.retryable


def test_gemini_generate_content_parse():
    resp = {
        "response_id": "r1",
        "model_version": "gemini-x-001",
        "candidates": [{"finish_reason": "STOP", "content": {"parts": [{"text": "thinking...", "thought": True}, {"text": '{"action":"x"}'}]}}],
        "usage_metadata": {"prompt_token_count": 10, "candidates_token_count": 5, "thoughts_token_count": 7, "total_token_count": 22},
    }
    rec = Recorder(result=resp)
    a = GeminiGenerateContentAdapter(mc("google", api_family="generate_content"), client=google_client(rec, gen=rec), credentials=creds())
    r = run(a.decide(req()))
    cfg = rec.calls[0]["config"]
    assert cfg["response_mime_type"] == "application/json" and cfg["response_json_schema"] == SCHEMA
    assert r.output_text == '{"action":"x"}' and r.usage.reasoning_tokens == 7
    blocked = {"prompt_feedback": {"block_reason": "PROHIBITED_CONTENT"}, "candidates": []}
    a = GeminiGenerateContentAdapter(mc("google", api_family="generate_content"), client=google_client(Recorder(result=blocked)), credentials=creds())
    r = run(a.decide(req()))
    assert r.refusal and r.output_text is None


@pytest.mark.parametrize(
    "code,category,retryable",
    [(429, "rate_limit", True), (500, "server", True), (503, "server", True), (401, "auth", False), (404, "invalid_model", False), (400, "bad_request", False)],
)
def test_google_error_mapping(code, category, retryable):
    e = genai_errors.APIError(code, {"error": {"message": f"oops {FAKE_KEY}", "status": "X"}})
    err = map_google_error(e, (FAKE_KEY,))
    assert (err.category, err.retryable) == (category, retryable) and FAKE_KEY not in str(err)


def test_google_client_disables_sdk_retries():
    a = GeminiInteractionsAdapter(mc("google"), credentials=creds())
    client = a._get_client()  # constructing the client makes no network call
    assert client.aio.interactions.sdk_configuration.retry_config.max_retries == 0
