"""Offline tests of the lookup-tool loop for OpenAI and Gemini adapters (mocked SDK clients)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from contact_bench.config import ModelConfig
from contact_bench.providers.base import (
    AttemptGate,
    DecisionRequest,
    InfrastructureError,
    RetryPolicy,
    ToolSpec,
)
from contact_bench.providers.google_adapter import GeminiGenerateContentAdapter, GeminiInteractionsAdapter
from contact_bench.providers.openai_adapter import OpenAIResponsesAdapter

FINAL = {"action": "clue", "word": "candle", "clue": "wax"}
SCHEMA = {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}
TOOLS = [
    ToolSpec(
        "list_words",
        "List dictionary words with a prefix.",
        {"type": "object", "properties": {"prefix": {"type": "string"}, "offset": {"type": "integer"},
                                          "limit": {"type": "integer"}}, "required": ["prefix"]},
    )
]


class Executor:
    def __init__(self):
        self.calls = []

    def __call__(self, name, args):
        self.calls.append((name, args))
        return {"result": ["cable", "candle"]}


def req(executor, max_tool_calls=5):
    return DecisionRequest(
        decision_id="d", seat="guesser1", phase="act", system_prompt="RULES", user_prompt="PROMPT",
        schema_name="contact_guesser1", json_schema=SCHEMA, max_output_tokens=100,
        tools=TOOLS, tool_executor=executor, max_tool_calls=max_tool_calls,
    )


def mc(provider, **kw):
    return ModelConfig(id=f"m_{provider}", provider=provider, model="model-x", max_output_tokens=512, **kw)


async def _nosleep(_d):
    return None


def adapter(cls, provider, client, **kw):
    return cls(mc(provider, **kw), client=client, retry=RetryPolicy(max_attempts=3, base_seconds=0), sleep=_nosleep)


class CountingGate(AttemptGate):
    def __init__(self):
        self.before_n = 0
        self.afters = []

    async def before(self):
        self.before_n += 1
        return self.before_n

    async def after(self, token, usage, ok, possibly_billed=True):  # type: ignore[override]
        self.afters.append((token, ok))


class Recorder:
    """Async callable returning scripted responses (or raising scripted errors)."""

    def __init__(self, script):
        self.script = list(script)
        self.kwargs = []

    async def __call__(self, **kwargs):
        self.kwargs.append(json.loads(json.dumps(kwargs, default=repr)))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def transient():
    return InfrastructureError("rate limited", category="rate_limit", retryable=True, retry_after=0.0)


# ---------------------------------------------------------------- OpenAI
def oa_usage(i, o):
    return {"input_tokens": i, "output_tokens": o, "total_tokens": i + o,
            "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 1}}


def oa_call(call_id="call_1"):
    return {
        "id": "r1", "model": "model-x", "status": "completed", "usage": oa_usage(10, 5),
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "ENC"},
            {"type": "function_call", "id": "fc_1", "call_id": call_id, "name": "list_words",
             "arguments": json.dumps({"prefix": "ca"}), "status": "completed"},
        ],
    }


def oa_final():
    return {
        "id": "r2", "model": "model-x", "status": "completed", "usage": oa_usage(20, 7),
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(FINAL)}]}],
    }


def oa_client(script):
    rec = Recorder(script)
    return SimpleNamespace(responses=SimpleNamespace(create=rec)), rec


def test_openai_two_turn_loop():
    client, rec = oa_client([oa_call(), oa_final()])
    ex = Executor()
    resp = asyncio.run(adapter(OpenAIResponsesAdapter, "openai", client).decide(req(ex)))
    assert json.loads(resp.output_text) == FINAL
    assert ex.calls == [("list_words", {"prefix": "ca"})]
    assert resp.usage.input_tokens == 30 and resp.usage.output_tokens == 12 and resp.usage.reasoning_tokens == 2
    assert resp.model_turns == 2 and resp.tool_trace[0]["name"] == "list_words"
    first, second = rec.kwargs
    assert first["store"] is False and "previous_response_id" not in first
    assert first["tool_choice"] == "auto" and first["tools"][0]["type"] == "function"
    assert first["text"]["format"]["type"] == "json_schema"
    assert "reasoning.encrypted_content" in first["include"]
    items = second["input"]
    assert items[0] == {"role": "user", "content": "PROMPT"}
    assert items[1]["type"] == "reasoning" and items[1]["encrypted_content"] == "ENC"
    assert items[2]["type"] == "function_call"
    assert items[3] == {"type": "function_call_output", "call_id": "call_1",
                        "output": json.dumps({"result": ["cable", "candle"]})}


def test_openai_limit_path_and_no_tools_setting():
    # model keeps calling tools forever
    client, rec = oa_client([oa_call(f"c{i}") for i in range(10)])
    ex = Executor()
    resp = asyncio.run(adapter(OpenAIResponsesAdapter, "openai", client).decide(req(ex, max_tool_calls=1)))
    assert len(ex.calls) == 1  # executor not called past the limit
    errs = [t for t in resp.tool_trace if "error" in t["result"]]
    assert errs and "limit" in errs[0]["result"]["error"]
    assert resp.output_text is None and resp.finish_reason == "tool_loop_limit" and resp.incomplete
    assert rec.kwargs[0]["tool_choice"] == "auto"
    assert all(k["tool_choice"] == "none" for k in rec.kwargs[1:])


def test_openai_gate_counts_every_attempt_including_retry():
    client, _ = oa_client([oa_call(), transient(), oa_final()])
    gate = CountingGate()
    resp = asyncio.run(adapter(OpenAIResponsesAdapter, "openai", client).decide(req(Executor()), gate=gate))
    assert json.loads(resp.output_text) == FINAL
    assert gate.before_n == 3 and len(gate.afters) == 3
    assert [ok for _, ok in gate.afters] == [True, False, True]
    assert len(resp.attempts) == 3


# ---------------------------------------------------------------- Interactions
def gi_usage(i, o):
    return {"total_input_tokens": i, "total_output_tokens": o, "total_tokens": i + o, "total_thought_tokens": 2}


def gi_call(cid="fc1"):
    return {
        "id": "", "model": "model-x", "status": "requires_action", "usage": gi_usage(10, 4),
        "steps": [
            {"type": "user_input", "content": [{"type": "text", "text": "PROMPT"}]},
            {"type": "thought", "signature": "SIG"},
            {"type": "function_call", "id": cid, "name": "list_words", "arguments": {"prefix": "ca"}},
        ],
    }


def gi_final():
    return {"id": "", "model": "model-x", "status": "completed", "usage": gi_usage(20, 6),
            "output_text": json.dumps(FINAL),
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": json.dumps(FINAL)}]}]}


def gi_client(script):
    rec = Recorder(script)
    return SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=rec))), rec


def test_interactions_two_turn_loop():
    # Gemini: lookup turns run without response_format; a final turn with
    # tools disabled re-requests the schema-constrained answer.
    client, rec = gi_client([gi_call(), gi_final(), gi_final()])
    ex = Executor()
    resp = asyncio.run(adapter(GeminiInteractionsAdapter, "google", client).decide(req(ex)))
    assert json.loads(resp.output_text) == FINAL and ex.calls == [("list_words", {"prefix": "ca"})]
    assert resp.usage.input_tokens == 50 and resp.usage.output_tokens == 16 and resp.usage.reasoning_tokens == 6
    first, second, third = rec.kwargs
    assert "response_format" not in first and "response_format" not in second
    assert third["response_format"]["schema"] == SCHEMA and third["generation_config"]["tool_choice"] == "none"
    assert third["input"][-1]["type"] == "user_input"
    assert first["store"] is False and "previous_interaction_id" not in first
    assert first["automatic_continuation"] is False
    assert first["generation_config"]["tool_choice"] == "auto"
    assert first["tools"][0] == {"type": "function", "name": "list_words", "description": TOOLS[0].description,
                                 "parameters": TOOLS[0].parameters}
    steps = second["input"]
    assert [s["type"] for s in steps] == ["user_input", "thought", "function_call", "function_result"]
    assert steps[1]["signature"] == "SIG"
    assert steps[3]["call_id"] == "fc1" and json.loads(steps[3]["result"]) == {"result": ["cable", "candle"]}


def test_interactions_limit_and_none_mode():
    client, rec = gi_client([gi_call(f"f{i}") for i in range(10)])
    ex = Executor()
    resp = asyncio.run(adapter(GeminiInteractionsAdapter, "google", client).decide(req(ex, max_tool_calls=1)))
    assert len(ex.calls) == 1 and resp.output_text is None and resp.finish_reason == "tool_loop_limit"
    assert all(k["generation_config"]["tool_choice"] == "none" for k in rec.kwargs[1:])
    assert any(s.get("is_error") for s in rec.kwargs[-1]["input"] if s["type"] == "function_result")


def test_interactions_gate_with_retry():
    client, _ = gi_client([gi_call(), transient(), gi_final(), gi_final()])
    gate = CountingGate()
    asyncio.run(adapter(GeminiInteractionsAdapter, "google", client).decide(req(Executor()), gate=gate))
    assert gate.before_n == 4 and [ok for _, ok in gate.afters] == [True, False, True, True]


# ---------------------------------------------------------------- generateContent
def gc_usage(i, o):
    return {"prompt_token_count": i, "candidates_token_count": o, "total_token_count": i + o,
            "thoughts_token_count": 1}


def gc_call(cid="fc1"):
    return {
        "response_id": "x", "model_version": "model-x", "usage_metadata": gc_usage(10, 3),
        "candidates": [{"finish_reason": "STOP", "content": {"role": "model", "parts": [
            {"function_call": {"id": cid, "name": "list_words", "args": {"prefix": "ca"}}, "thought_signature": "SIG"}
        ]}}],
    }


def gc_final():
    return {
        "response_id": "y", "model_version": "model-x", "usage_metadata": gc_usage(20, 5),
        "candidates": [{"finish_reason": "STOP", "content": {"role": "model", "parts": [{"text": json.dumps(FINAL)}]}}],
    }


def gc_client(script):
    rec = Recorder(script)
    return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=rec))), rec


def test_generate_content_two_turn_loop():
    client, rec = gc_client([gc_call(), gc_final(), gc_final()])
    ex = Executor()
    resp = asyncio.run(adapter(GeminiGenerateContentAdapter, "google", client, api_family="generate_content")
                       .decide(req(ex)))
    assert json.loads(resp.output_text) == FINAL and ex.calls == [("list_words", {"prefix": "ca"})]
    assert resp.usage.input_tokens == 50 and resp.usage.output_tokens == 13
    first, second, third = rec.kwargs
    assert "response_json_schema" not in first["config"] and "response_json_schema" not in second["config"]
    assert third["config"]["response_json_schema"] == SCHEMA
    assert third["config"]["tool_config"]["function_calling_config"]["mode"] == "NONE"
    cfg = first["config"]
    assert cfg["tool_config"]["function_calling_config"]["mode"] == "AUTO"
    assert cfg["automatic_function_calling"] == {"disable": True}
    assert cfg["tools"][0]["function_declarations"][0]["name"] == "list_words"
    contents = second["contents"]
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model" and contents[1]["parts"][0]["thought_signature"] == "SIG"
    fr = contents[2]["parts"][0]["function_response"]
    assert fr == {"name": "list_words", "id": "fc1", "response": {"result": {"result": ["cable", "candle"]}}}


def test_generate_content_limit_and_none_mode():
    client, rec = gc_client([gc_call(f"f{i}") for i in range(10)])
    ex = Executor()
    resp = asyncio.run(adapter(GeminiGenerateContentAdapter, "google", client, api_family="generate_content")
                       .decide(req(ex, max_tool_calls=1)))
    assert len(ex.calls) == 1 and resp.output_text is None and resp.finish_reason == "tool_loop_limit"
    assert all(k["config"]["tool_config"]["function_calling_config"]["mode"] == "NONE" for k in rec.kwargs[1:])


def test_generate_content_gate_with_retry():
    client, _ = gc_client([gc_call(), transient(), gc_final(), gc_final()])
    gate = CountingGate()
    asyncio.run(adapter(GeminiGenerateContentAdapter, "google", client, api_family="generate_content")
                .decide(req(Executor()), gate=gate))
    assert gate.before_n == 4 and [ok for _, ok in gate.afters] == [True, False, True, True]


@pytest.mark.parametrize("cls,provider,kw", [
    (OpenAIResponsesAdapter, "openai", {}),
    (GeminiInteractionsAdapter, "google", {}),
    (GeminiGenerateContentAdapter, "google", {"api_family": "generate_content"}),
])
def test_without_tools_single_call_unchanged(cls, provider, kw):
    script = {"openai": oa_final(), "google": gi_final() if cls is GeminiInteractionsAdapter else gc_final()}[provider]
    if cls is OpenAIResponsesAdapter:
        client, rec = oa_client([script])
    elif cls is GeminiInteractionsAdapter:
        client, rec = gi_client([script])
    else:
        client, rec = gc_client([script])
    r = DecisionRequest(decision_id="d", seat="guesser1", phase="act", system_prompt="S", user_prompt="P",
                        schema_name="n", json_schema=SCHEMA, max_output_tokens=10)
    resp = asyncio.run(adapter(cls, provider, client, **kw).decide(r))
    assert json.loads(resp.output_text) == FINAL and len(rec.kwargs) == 1
    k = rec.kwargs[0]
    assert "tools" not in k and "tools" not in k.get("config", {})
