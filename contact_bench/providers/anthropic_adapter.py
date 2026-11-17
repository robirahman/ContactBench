"""Anthropic Messages API adapter (spec Section 13.2).

Structured output via ``output_config.format`` (json_schema).  The installed
SDK's ``messages.create`` exposes no temperature/top_p/top_k, consistent with
API version 2026-10-21 rejecting sampling parameters, so they are unsupported.
History is caller-supplied (a single filtered user message); SDK retries are
disabled (``max_retries=0``).
"""

from __future__ import annotations

from typing import Any

import json

from ._stainless import map_stainless_error
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

# Above this many output tokens the SDK requires streaming for a single call.
STREAMING_THRESHOLD = 16000


class AnthropicMessagesAdapter(ProviderAdapter):
    provider = "anthropic"
    api_family = "messages"
    default_credential_env = "ANTHROPIC_API_KEY"
    # "effort" is sent as output_config.effort; the others go to messages.create verbatim.
    supported_parameters = frozenset({"thinking", "effort", "service_tier", "speed", "inference_geo"})

    def __init__(self, model_config, *, client: Any = None, **kwargs: Any):
        super().__init__(model_config, **kwargs)
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(
                api_key=self.credentials.require(self.credential_env), max_retries=0
            )
        return self._client

    @staticmethod
    def user_content(request: DecisionRequest) -> Any:
        """User message content.  With prompt parts, each part is its own block
        and a cache breakpoint ends the append-only prefix (game header plus
        public history), so the next turn's request hits that cache entry."""
        if not request.user_prompt_parts:
            return request.user_prompt
        blocks: list[dict[str, Any]] = [{"type": "text", "text": p} for p in request.user_prompt_parts]
        if request.cache_prefix_parts > 0:
            blocks[request.cache_prefix_parts - 1]["cache_control"] = {"type": "ephemeral"}
        return blocks

    def build_request(self, request: DecisionRequest) -> dict:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": request.json_schema}}
        system: Any = request.system_prompt
        if request.user_prompt_parts:
            # The rules text is identical for every call in a condition.
            system = [{"type": "text", "text": request.system_prompt, "cache_control": {"type": "ephemeral"}}]
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": request.max_output_tokens or self.config.max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": self.user_content(request)}],
        }
        for k, v in self.config.parameters.items():
            if k == "effort":
                output_config["effort"] = v
            else:
                kwargs[k] = v
        kwargs["output_config"] = output_config
        return kwargs

    async def _call(self, kwargs: dict) -> Any:
        import anthropic

        client = self._get_client()
        secrets = tuple(s for s in (self.credentials.get(self.credential_env or ""),) if s)
        try:
            if kwargs["max_tokens"] > STREAMING_THRESHOLD:
                # Large output allowances (e.g. a full explicit blocklist over a
                # big dictionary) must stream; the final message is identical.
                async with client.messages.stream(**kwargs) as stream:
                    return await stream.get_final_message()
            return await client.messages.create(**kwargs)
        except anthropic.AnthropicError as e:
            raise map_stainless_error(e, anthropic, secrets) from None
        except Exception as e:
            # Network errors raised while iterating a stream are not wrapped by
            # the SDK (observed live: httpx2.ReadError mid-stream).  They are
            # transport failures; output may already have been generated.
            import httpx2

            if isinstance(e, (httpx2.TransportError, httpx2.StreamError)):
                raise InfrastructureError(
                    f"{type(e).__name__}: {sanitize(str(e), secrets)}", category="transient",
                    retryable=True, possibly_billed=True,
                ) from None
            raise

    async def send_once(self, request: DecisionRequest) -> AdapterResponse:
        kwargs = self.build_request(request)
        msg = await self._call(kwargs)
        return self.parse_response(msg, kwargs)

    # -- lookup-tool loop ------------------------------------------------------
    def tool_conversation_start(self, request: DecisionRequest) -> Any:
        return [{"role": "user", "content": self.user_content(request)}]

    async def send_tool_turn(self, request: DecisionRequest, state: Any, allow_tools: bool):
        kwargs = self.build_request(request)
        msgs = list(state)
        if request.user_prompt_parts and len(msgs) > 1 and isinstance(msgs[-1].get("content"), list) and msgs[-1]["content"]:
            # Third breakpoint: cache the growing tool-loop conversation.
            last = dict(msgs[-1])
            content = [dict(b) for b in last["content"]]
            content[-1]["cache_control"] = {"type": "ephemeral"}
            last["content"] = content
            msgs[-1] = last
        kwargs["messages"] = msgs
        kwargs["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in request.tools
        ]
        kwargs["tool_choice"] = {"type": "auto"} if allow_tools else {"type": "none"}
        msg = await self._call(kwargs)
        resp = self.parse_response(msg, kwargs)
        blocks = get(msg, "content", None) or []
        calls = [
            ToolCall(id=get(b, "id"), name=get(b, "name"), arguments=dict(get(b, "input", None) or {}))
            for b in blocks
            if get(b, "type") == "tool_use"
        ]
        # Pass every assistant block back unchanged (thinking blocks included).
        assistant = [to_plain(b) for b in blocks]
        new_state = list(state) + [{"role": "assistant", "content": assistant}]
        if calls:
            resp.output_text = None  # an intermediate turn is not a final answer
        return resp, calls, new_state

    def tool_conversation_append(self, state: Any, calls: list[ToolCall], results: list[Any]) -> Any:
        content = [
            {"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(r, separators=(",", ":"))}
            for c, r in zip(calls, results)
        ]
        return list(state) + [{"role": "user", "content": content}]

    def parse_response(self, msg: Any, kwargs: dict) -> AdapterResponse:
        texts = [get(b, "text", "") or "" for b in (get(msg, "content", None) or []) if get(b, "type") == "text"]
        stop = get(msg, "stop_reason")
        u = get(msg, "usage")
        thinking = int_or_none(get(get(u, "output_tokens_details"), "thinking_tokens"))
        # Normalized convention: input_tokens INCLUDES cache reads and writes
        # (Anthropic reports them as separate, disjoint fields).
        base_in = int_or_none(get(u, "input_tokens"))
        c_read = int_or_none(get(u, "cache_read_input_tokens"))
        c_write = int_or_none(get(u, "cache_creation_input_tokens"))
        usage = NormalizedUsage(
            input_tokens=None if base_in is None else base_in + (c_read or 0) + (c_write or 0),
            output_tokens=int_or_none(get(u, "output_tokens")),
            total_tokens=None,  # not reported by the Messages API
            cached_input_tokens=int_or_none(get(u, "cache_read_input_tokens")),
            cache_write_tokens=int_or_none(get(u, "cache_creation_input_tokens")),
            reasoning_tokens=thinking,
            # Thinking tokens are billed as output and reported within output_tokens.
            reasoning_included_in_output=True if thinking is not None else None,
        )
        if usage.input_tokens is not None and usage.output_tokens is not None:
            usage.total_tokens = usage.input_tokens + usage.output_tokens
        effective = {k: v for k, v in self.config.parameters.items()}
        effective["max_tokens"] = kwargs["max_tokens"]
        return AdapterResponse(
            output_text=("".join(texts) if texts else None),
            provider=self.provider,
            api_family=self.api_family,
            response_id=get(msg, "id"),
            request_id=getattr(msg, "_request_id", None),
            requested_model=self.config.model,
            returned_model=get(msg, "model"),
            finish_reason=stop,
            refusal=stop == "refusal",
            incomplete=stop in ("max_tokens", "model_context_window_exceeded", "pause_turn"),
            raw_usage=to_plain(u) if u is not None else None,
            usage=usage,
            requested_parameters=dict(self.config.parameters),
            effective_parameters=effective,
        )
