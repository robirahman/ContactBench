"""Offline tests of transcript forking (keep_conversation + fork) for OpenAI and Gemini adapters."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from contact_bench.providers.base import DecisionRequest
from contact_bench.providers.google_adapter import GeminiGenerateContentAdapter, GeminiInteractionsAdapter
from contact_bench.providers.openai_adapter import OpenAIResponsesAdapter

from .test_provider_tools import (
    FINAL, SCHEMA, CountingGate, Executor, adapter, gc_call, gc_client, gc_final, gc_usage, gi_call, gi_client,
    gi_final, gi_usage, oa_call, oa_client, oa_final, oa_usage, req,
)

FORK_SCHEMA = {"type": "object", "properties": {"entries": {"type": "array"}, "other_mass": {"type": "number"}},
               "required": ["entries", "other_mass"]}
FORECAST = {"entries": [{"word": "candle", "probability": 0.7}], "other_mass": 0.3}


def base_req():
    return DecisionRequest(decision_id="d", seat="guesser1", phase="act", system_prompt="RULES",
                           user_prompt="PROMPT", schema_name="contact_guesser1", json_schema=SCHEMA,
                           max_output_tokens=100, keep_conversation=True)


def fork_req():
    return DecisionRequest(decision_id="d/fork", seat="guesser1", phase="fork", system_prompt="RULES",
                           user_prompt="FORK QUESTION", schema_name="contact_fork", json_schema=FORK_SCHEMA,
                           max_output_tokens=100)


def tool_req():
    r = req(Executor())
    r.keep_conversation = True
    return r


# ---------------------------------------------------------------- OpenAI
def oa_reasoned_final():
    return {"id": "r0", "model": "model-x", "status": "completed", "usage": oa_usage(10, 5),
            "output": [{"type": "reasoning", "id": "rs_0", "summary": [], "encrypted_content": "ENC0"},
                       {"type": "message", "id": "msg_0", "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(FINAL)}]}]}


def oa_fork_answer():
    return {"id": "r9", "model": "model-x", "status": "completed", "usage": oa_usage(30, 4),
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(FORECAST)}]}]}


def test_openai_keep_and_fork_no_tools():
    client, rec = oa_client([oa_reasoned_final(), oa_fork_answer()])
    a = adapter(OpenAIResponsesAdapter, "openai", client)
    resp = asyncio.run(a.decide(base_req()))
    assert json.loads(resp.output_text) == FINAL and len(rec.kwargs) == 1
    first = rec.kwargs[0]
    assert "tools" not in first and "tool_choice" not in first
    assert first["store"] is False and first["text"]["format"]["schema"] == SCHEMA
    conv = resp.conversation
    snapshot = copy.deepcopy(conv)
    gate = CountingGate()
    fr = asyncio.run(a.fork(fork_req(), conv, gate=gate))
    assert json.loads(fr.output_text) == FORECAST
    assert conv == snapshot  # original transcript not mutated
    sent = rec.kwargs[1]
    items = sent["input"]
    assert items[0] == {"role": "user", "content": "PROMPT"}
    assert items[1]["type"] == "reasoning" and items[1]["encrypted_content"] == "ENC0"
    assert items[2]["type"] == "message" and items[2]["content"][0]["text"] == json.dumps(FINAL)
    assert items[3] == {"role": "user", "content": "FORK QUESTION"}
    assert sent["text"]["format"]["schema"] == FORK_SCHEMA and sent["text"]["format"]["name"] == "contact_fork"
    assert "tools" not in sent and sent["store"] is False
    assert gate.before_n == 1 and fr.usage.input_tokens == 30 and len(fr.attempts) == 1


def test_openai_fork_after_tool_loop():
    client, rec = oa_client([oa_call(), oa_final(), oa_fork_answer()])
    a = adapter(OpenAIResponsesAdapter, "openai", client)
    resp = asyncio.run(a.decide(tool_req()))
    asyncio.run(a.fork(fork_req(), resp.conversation))
    types = [i.get("type", i.get("role")) for i in rec.kwargs[2]["input"]]
    assert types == ["user", "reasoning", "function_call", "function_call_output", "message", "user"]


# ---------------------------------------------------------------- Interactions
def gi_reasoned_final():
    return {"id": "", "model": "model-x", "status": "completed", "usage": gi_usage(10, 4),
            "output_text": json.dumps(FINAL),
            "steps": [{"type": "user_input", "content": [{"type": "text", "text": "PROMPT"}]},
                      {"type": "thought", "signature": "SIG0"},
                      {"type": "model_output", "content": [{"type": "text", "text": json.dumps(FINAL)}]}]}


def gi_fork_answer():
    return {"id": "", "model": "model-x", "status": "completed", "usage": gi_usage(25, 3),
            "output_text": json.dumps(FORECAST),
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": json.dumps(FORECAST)}]}]}


def test_interactions_keep_and_fork_no_tools():
    client, rec = gi_client([gi_reasoned_final(), gi_fork_answer()])
    a = adapter(GeminiInteractionsAdapter, "google", client)
    resp = asyncio.run(a.decide(base_req()))
    assert json.loads(resp.output_text) == FINAL and len(rec.kwargs) == 1
    first = rec.kwargs[0]
    assert "tools" not in first and "tool_choice" not in first["generation_config"]
    assert first["store"] is False and first["response_format"]["schema"] == SCHEMA
    conv = resp.conversation
    snapshot = copy.deepcopy(conv)
    gate = CountingGate()
    fr = asyncio.run(a.fork(fork_req(), conv, gate=gate))
    assert json.loads(fr.output_text) == FORECAST and conv == snapshot
    steps = rec.kwargs[1]["input"]
    assert steps[0] == {"type": "user_input", "content": [{"type": "text", "text": "PROMPT"}]}
    assert steps[1] == {"type": "thought", "signature": "SIG0"}
    assert steps[2]["type"] == "model_output"
    assert steps[3] == {"type": "user_input", "content": [{"type": "text", "text": "FORK QUESTION"}]}
    assert len(steps) == 4  # echoed user_input in the response is not duplicated
    assert rec.kwargs[1]["response_format"]["schema"] == FORK_SCHEMA and "tools" not in rec.kwargs[1]
    assert gate.before_n == 1 and fr.usage.input_tokens == 25


def test_interactions_fork_after_tool_loop():
    # Gemini: lookup turns run without the schema, then one forced final turn
    # (tools off, schema on) precedes the fork (structured_output_with_tools=False).
    client, rec = gi_client([gi_call(), gi_final(), gi_final(), gi_fork_answer()])
    a = adapter(GeminiInteractionsAdapter, "google", client)
    resp = asyncio.run(a.decide(tool_req()))
    asyncio.run(a.fork(fork_req(), resp.conversation))
    types = [s["type"] for s in rec.kwargs[3]["input"]]
    assert types[:5] == ["user_input", "thought", "function_call", "function_result", "model_output"]
    assert types[-1] == "user_input" and rec.kwargs[3]["input"][-1]["content"][0]["text"] == "FORK QUESTION"
    assert "tools" not in rec.kwargs[3]


# ---------------------------------------------------------------- generateContent
def gc_reasoned_final():
    return {"response_id": "x", "model_version": "model-x", "usage_metadata": gc_usage(10, 3),
            "candidates": [{"finish_reason": "STOP", "content": {"role": "model", "parts": [
                {"text": json.dumps(FINAL), "thought_signature": "SIG0"}]}}]}


def gc_fork_answer():
    return {"response_id": "z", "model_version": "model-x", "usage_metadata": gc_usage(22, 2),
            "candidates": [{"finish_reason": "STOP", "content": {"role": "model", "parts": [
                {"text": json.dumps(FORECAST)}]}}]}


def test_generate_content_keep_and_fork_no_tools():
    client, rec = gc_client([gc_reasoned_final(), gc_fork_answer()])
    a = adapter(GeminiGenerateContentAdapter, "google", client, api_family="generate_content")
    resp = asyncio.run(a.decide(base_req()))
    assert json.loads(resp.output_text) == FINAL and len(rec.kwargs) == 1
    cfg = rec.kwargs[0]["config"]
    assert "tools" not in cfg and "tool_config" not in cfg and "automatic_function_calling" not in cfg
    assert cfg["response_json_schema"] == SCHEMA
    conv = resp.conversation
    snapshot = copy.deepcopy(conv)
    gate = CountingGate()
    fr = asyncio.run(a.fork(fork_req(), conv, gate=gate))
    assert json.loads(fr.output_text) == FORECAST and conv == snapshot
    contents = rec.kwargs[1]["contents"]
    assert contents[0] == {"role": "user", "parts": [{"text": "PROMPT"}]}
    assert contents[1]["role"] == "model" and contents[1]["parts"][0]["thought_signature"] == "SIG0"
    assert contents[2] == {"role": "user", "parts": [{"text": "FORK QUESTION"}]}
    assert rec.kwargs[1]["config"]["response_json_schema"] == FORK_SCHEMA
    assert gate.before_n == 1 and fr.usage.input_tokens == 22


def get_role(c):
    return c["role"] if isinstance(c, dict) else c.role


def test_generate_content_fork_after_tool_loop():
    client, rec = gc_client([gc_call(), gc_final(), gc_final(), gc_fork_answer()])
    a = adapter(GeminiGenerateContentAdapter, "google", client, api_family="generate_content")
    resp = asyncio.run(a.decide(tool_req()))
    asyncio.run(a.fork(fork_req(), resp.conversation))
    contents = rec.kwargs[3]["contents"]
    assert [get_role(c) for c in contents] == ["user", "model", "user", "model", "user", "model", "user"]
    assert "function_call" in contents[1]["parts"][0] and "function_response" in contents[2]["parts"][0]
    assert contents[-1] == {"role": "user", "parts": [{"text": "FORK QUESTION"}]}
    assert "tools" not in rec.kwargs[3]["config"]


@pytest.mark.parametrize("cls,provider,kw,client_fn,script", [
    (OpenAIResponsesAdapter, "openai", {}, oa_client, oa_reasoned_final),
    (GeminiInteractionsAdapter, "google", {}, gi_client, gi_reasoned_final),
    (GeminiGenerateContentAdapter, "google", {"api_family": "generate_content"}, gc_client, gc_reasoned_final),
])
def test_conversation_not_serialized(cls, provider, kw, client_fn, script):
    client, _ = client_fn([script()])
    resp = asyncio.run(adapter(cls, provider, client, **kw).decide(base_req()))
    assert resp.conversation is not None
    d = resp.to_json()
    assert d["conversation"] is None and resp.conversation is not None
    json.dumps(d, default=str)
