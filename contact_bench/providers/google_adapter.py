"""Google Gemini adapters (spec Section 13.2).

Primary: Interactions API (``client.aio.interactions.create``) with a text
``response_format`` carrying the JSON schema, ``store=False`` and
``automatic_continuation=False`` (a continuation hop would be a second
generation).  Compatibility: ``generateContent`` (api_family
"generate_content") with ``response_json_schema``.  The two families use
different usage-field conventions and are kept separate.

SDK retries are disabled explicitly: the Interactions client otherwise
defaults to several attempts even when ``retry_options`` is unset.
"""

from __future__ import annotations

import json
from typing import Any

from ._util import get, int_or_none, to_plain
from .base import (
    AdapterResponse,
    DecisionRequest,
    InfrastructureError,
    NormalizedUsage,
    ProviderAdapter,
    ToolCall,
    sanitize,
)

REFUSAL_FINISH = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}


def map_google_error(e: BaseException, secrets: tuple[str, ...]) -> InfrastructureError:
    msg = sanitize(f"{type(e).__name__}: {e}", secrets)
    code = getattr(e, "code", None)
    if not isinstance(code, int):
        code = getattr(e, "status_code", None)
    name = type(e).__name__.lower()

    def mk(category: str, *, retryable: bool = False, fatal: bool = False, billed: bool = False):
        return InfrastructureError(msg, category=category, retryable=retryable, fatal=fatal, possibly_billed=billed)

    if "timeout" in name:
        return mk("timeout", retryable=True, billed=True)
    if isinstance(code, int):
        if code == 429:
            # RESOURCE_EXHAUSTED may be a per-minute rate limit or an exhausted
            # project quota; quotas can apply at project scope.  Retry boundedly.
            return mk("rate_limit", retryable=True)
        if code in (401, 403):
            return mk("auth", fatal=True)
        if code == 404:
            return mk("invalid_model", fatal=True)
        if code in (408, 409):
            return mk("transient", retryable=True)
        if code == 400:
            low = msg.lower()
            if "unknown name" in low or "unsupported" in low or "invalid json payload" in low:
                return mk("unsupported_parameter", fatal=True)
            return mk("bad_request", fatal=True)
        if code >= 500:
            return mk("server", retryable=True)
        return mk("unknown", fatal=True)
    if "connect" in name or "network" in name or "transport" in name:
        return mk("transient", retryable=True)
    return mk("unknown", fatal=True)


class _GoogleBase(ProviderAdapter):
    provider = "google"
    default_credential_env = "GEMINI_API_KEY"

    def __init__(self, model_config, *, client: Any = None, **kwargs: Any):
        super().__init__(model_config, **kwargs)
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.credentials.require(self.credential_env),
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
            )
        return self._client

    def _secrets(self) -> tuple[str, ...]:
        return tuple(s for s in (self.credentials.get(self.credential_env or ""),) if s)


class GeminiInteractionsAdapter(_GoogleBase):
    api_family = "interactions"
    # Forwarded inside generation_config (except service_tier, top level).
    supported_parameters = frozenset({"thinking_level", "thinking_summaries", "temperature", "top_p", "seed", "service_tier"})

    def build_request(self, request: DecisionRequest, input_steps: Any = None) -> dict:
        gen: dict[str, Any] = {"max_output_tokens": request.max_output_tokens or self.config.max_output_tokens}
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "input": request.user_prompt if input_steps is None else input_steps,
            "system_instruction": request.system_prompt,
            "response_format": {"type": "text", "mime_type": "application/json", "schema": request.json_schema},
            "store": False,
        }
        for k, v in self.config.parameters.items():
            if k == "service_tier":
                kwargs[k] = v
            else:
                gen[k] = v
        kwargs["generation_config"] = gen
        return kwargs

    async def _create(self, kwargs: dict) -> Any:
        client = self._get_client()
        try:
            return await client.aio.interactions.create(automatic_continuation=False, **kwargs)
        except InfrastructureError:
            raise
        except Exception as e:  # SDK raises genai.errors.APIError and transport errors
            raise map_google_error(e, self._secrets()) from None

    async def send_once(self, request: DecisionRequest) -> AdapterResponse:
        kwargs = self.build_request(request)
        resp = await self._create(kwargs)
        return self.parse_response(resp, kwargs)

    # -- lookup tools ----------------------------------------------------------
    # store=False: no previous_interaction_id; history is carried as a list of
    # steps (user_input, the model's own thought/function_call/model_output
    # steps replayed verbatim including thought signatures, function_result).
    _MODEL_STEP_TYPES = {"thought", "function_call", "model_output"}

    def tool_conversation_start(self, request: DecisionRequest) -> list:
        return [{"type": "user_input", "content": [{"type": "text", "text": request.user_prompt}]}]

    def tool_kwargs(self, request: DecisionRequest, state: list, allow_tools: bool) -> dict:
        kwargs = self.build_request(request, input_steps=list(state))
        kwargs["tools"] = [
            {"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters}
            for t in request.tools
        ]
        kwargs["generation_config"]["tool_choice"] = "auto" if allow_tools else "none"
        return kwargs

    async def send_tool_turn(self, request: DecisionRequest, state: list, allow_tools: bool):
        kwargs = self.tool_kwargs(request, state, allow_tools)
        raw = await self._create(kwargs)
        resp = self.parse_response(raw, kwargs)
        calls: list[ToolCall] = []
        appended: list[Any] = []
        for step in get(raw, "steps", None) or []:
            stype = get(step, "type")
            if stype not in self._MODEL_STEP_TYPES:
                continue  # never re-send echoed user_input/function_result steps
            plain = to_plain(step)
            if isinstance(plain, dict):
                plain = {k: v for k, v in plain.items() if v is not None}
            appended.append(plain)
            if stype == "function_call":
                args = get(step, "arguments")
                calls.append(
                    ToolCall(
                        id=get(step, "id") or "",
                        name=get(step, "name") or "",
                        arguments=args if isinstance(args, dict) else {"_unparseable_arguments": to_plain(args)},
                    )
                )
        if calls:
            resp.incomplete = False  # a turn ending in tool calls is not a truncated answer
        return resp, calls, list(state) + appended

    def tool_conversation_append(self, state: list, calls: list[ToolCall], results: list[Any]) -> list:
        out = list(state)
        for c, r in zip(calls, results):
            step: dict[str, Any] = {"type": "function_result", "call_id": c.id, "name": c.name, "result": json.dumps(r)}
            if isinstance(r, dict) and "error" in r:
                step["is_error"] = True
            out.append(step)
        return out

    def parse_response(self, resp: Any, kwargs: dict) -> AdapterResponse:
        status = get(resp, "status")
        if status in ("failed", "cancelled"):
            raise InfrastructureError(
                sanitize(f"interaction status {status}: {to_plain(get(resp, 'errors'))}", self._secrets()),
                category="server",
                retryable=True,
                possibly_billed=True,
            )
        text = get(resp, "output_text")
        u = get(resp, "usage")
        usage = NormalizedUsage(
            input_tokens=int_or_none(get(u, "total_input_tokens")),
            output_tokens=int_or_none(get(u, "total_output_tokens")),
            total_tokens=int_or_none(get(u, "total_tokens")),
            cached_input_tokens=int_or_none(get(u, "total_cached_tokens")),
            cache_write_tokens=None,
            reasoning_tokens=int_or_none(get(u, "total_thought_tokens")),
            # Interactions reports thought tokens separately from output tokens.
            reasoning_included_in_output=False if get(u, "total_thought_tokens") is not None else None,
        )
        effective = dict(kwargs["generation_config"])
        effective.update(store=False, automatic_continuation=False)
        if "service_tier" in kwargs:
            effective["service_tier"] = kwargs["service_tier"]
        return AdapterResponse(
            output_text=text or None,
            provider=self.provider,
            api_family=self.api_family,
            response_id=get(resp, "id") or None,
            request_id=None,
            requested_model=self.config.model,
            returned_model=get(resp, "model"),
            finish_reason=status,
            refusal=False,
            incomplete=status in ("incomplete", "budget_exceeded", "requires_continuation"),
            raw_usage=to_plain(u) if u is not None else None,
            usage=usage,
            requested_parameters=dict(self.config.parameters),
            effective_parameters=effective,
        )


class GeminiGenerateContentAdapter(_GoogleBase):
    """Explicitly versioned generateContent compatibility adapter."""

    api_family = "generate_content"
    supported_parameters = frozenset({"thinking_config", "temperature", "top_p", "seed"})

    def build_request(self, request: DecisionRequest, contents: Any = None) -> dict:
        config: dict[str, Any] = {
            "system_instruction": request.system_prompt,
            "response_mime_type": "application/json",
            "response_json_schema": request.json_schema,
            "max_output_tokens": request.max_output_tokens or self.config.max_output_tokens,
        }
        config.update(self.config.parameters)
        return {
            "model": self.config.model,
            "contents": request.user_prompt if contents is None else contents,
            "config": config,
        }

    async def _create(self, kwargs: dict) -> Any:
        client = self._get_client()
        try:
            return await client.aio.models.generate_content(**kwargs)
        except InfrastructureError:
            raise
        except Exception as e:
            raise map_google_error(e, self._secrets()) from None

    async def send_once(self, request: DecisionRequest) -> AdapterResponse:
        kwargs = self.build_request(request)
        resp = await self._create(kwargs)
        return self.parse_response(resp, kwargs)

    # -- lookup tools ----------------------------------------------------------
    # History is a list of Content entries.  The model's candidate content is
    # replayed as the SDK object so thought_signature bytes survive intact.
    def tool_conversation_start(self, request: DecisionRequest) -> list:
        return [{"role": "user", "parts": [{"text": request.user_prompt}]}]

    def tool_kwargs(self, request: DecisionRequest, state: list, allow_tools: bool) -> dict:
        kwargs = self.build_request(request, contents=list(state))
        cfg = kwargs["config"]
        cfg["tools"] = [
            {
                "function_declarations": [
                    {"name": t.name, "description": t.description, "parameters_json_schema": t.parameters}
                    for t in request.tools
                ]
            }
        ]
        cfg["tool_config"] = {"function_calling_config": {"mode": "AUTO" if allow_tools else "NONE"}}
        # Only declarations are passed (no callables), so the SDK never runs
        # functions itself; disable automatic function calling explicitly.
        cfg["automatic_function_calling"] = {"disable": True}
        return kwargs

    async def send_tool_turn(self, request: DecisionRequest, state: list, allow_tools: bool):
        kwargs = self.tool_kwargs(request, state, allow_tools)
        raw = await self._create(kwargs)
        resp = self.parse_response(raw, kwargs)
        cands = get(raw, "candidates") or []
        content = get(cands[0], "content") if cands else None
        calls: list[ToolCall] = []
        for i, p in enumerate(get(content, "parts") or []):
            fc = get(p, "function_call")
            if fc is None:
                continue
            args = get(fc, "args")
            calls.append(
                ToolCall(
                    id=get(fc, "id") or f"call_{len(state)}_{i}",
                    name=get(fc, "name") or "",
                    arguments=dict(args) if isinstance(args, dict) else {},
                )
            )
        new_state = list(state) + ([content] if content is not None else [])
        return resp, calls, new_state

    def tool_conversation_append(self, state: list, calls: list[ToolCall], results: list[Any]) -> list:
        parts = []
        for c, r in zip(calls, results):
            fr: dict[str, Any] = {"name": c.name, "response": {"result": json.loads(json.dumps(r))}}
            if c.id and not c.id.startswith("call_"):
                fr["id"] = c.id
            parts.append({"function_response": fr})
        return list(state) + [{"role": "user", "parts": parts}]

    def parse_response(self, resp: Any, kwargs: dict) -> AdapterResponse:
        cands = get(resp, "candidates") or []
        finish = get(cands[0], "finish_reason") if cands else None
        finish = getattr(finish, "value", finish)
        block = get(get(resp, "prompt_feedback"), "block_reason")
        block = getattr(block, "value", block)
        texts: list[str] = []
        if cands:
            for p in get(get(cands[0], "content"), "parts") or []:
                if get(p, "thought"):
                    continue
                t = get(p, "text")
                if t:
                    texts.append(t)
        u = get(resp, "usage_metadata")
        usage = NormalizedUsage(
            input_tokens=int_or_none(get(u, "prompt_token_count")),
            output_tokens=int_or_none(get(u, "candidates_token_count")),
            total_tokens=int_or_none(get(u, "total_token_count")),
            cached_input_tokens=int_or_none(get(u, "cached_content_token_count")),
            cache_write_tokens=None,
            reasoning_tokens=int_or_none(get(u, "thoughts_token_count")),
            # generateContent reports thoughts_token_count separately from candidates_token_count.
            reasoning_included_in_output=False if get(u, "thoughts_token_count") is not None else None,
        )
        effective = {k: v for k, v in kwargs["config"].items() if k not in ("system_instruction", "response_json_schema")}
        return AdapterResponse(
            output_text="".join(texts) or None,
            provider=self.provider,
            api_family=self.api_family,
            response_id=get(resp, "response_id"),
            request_id=None,
            requested_model=self.config.model,
            returned_model=get(resp, "model_version"),
            finish_reason=str(block or finish) if (block or finish) else None,
            refusal=bool(block) or (finish in REFUSAL_FINISH),
            incomplete=finish == "MAX_TOKENS",
            raw_usage=to_plain(u) if u is not None else None,
            usage=usage,
            requested_parameters=dict(self.config.parameters),
            effective_parameters=effective,
        )
