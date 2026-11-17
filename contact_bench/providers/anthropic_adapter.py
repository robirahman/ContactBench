"""Anthropic Messages API adapter (spec Section 13.2).

Structured output via ``output_config.format`` (json_schema).  The installed
SDK's ``messages.create`` exposes no temperature/top_p/top_k, consistent with
API version 2026-10-21 rejecting sampling parameters, so they are unsupported.
History is caller-supplied (a single filtered user message); SDK retries are
disabled (``max_retries=0``).
"""

from __future__ import annotations

from typing import Any

from ._stainless import map_stainless_error
from ._util import get, int_or_none, to_plain
from .base import AdapterResponse, DecisionRequest, NormalizedUsage, ProviderAdapter


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

    def build_request(self, request: DecisionRequest) -> dict:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": request.json_schema}}
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": request.max_output_tokens or self.config.max_output_tokens,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt}],
        }
        for k, v in self.config.parameters.items():
            if k == "effort":
                output_config["effort"] = v
            else:
                kwargs[k] = v
        kwargs["output_config"] = output_config
        return kwargs

    async def send_once(self, request: DecisionRequest) -> AdapterResponse:
        import anthropic

        kwargs = self.build_request(request)
        client = self._get_client()
        secrets = tuple(s for s in (self.credentials.get(self.credential_env or ""),) if s)
        try:
            msg = await client.messages.create(**kwargs)
        except anthropic.AnthropicError as e:
            raise map_stainless_error(e, anthropic, secrets) from None
        return self.parse_response(msg, kwargs)

    def parse_response(self, msg: Any, kwargs: dict) -> AdapterResponse:
        texts = [get(b, "text", "") or "" for b in (get(msg, "content", None) or []) if get(b, "type") == "text"]
        stop = get(msg, "stop_reason")
        u = get(msg, "usage")
        thinking = int_or_none(get(get(u, "output_tokens_details"), "thinking_tokens"))
        usage = NormalizedUsage(
            input_tokens=int_or_none(get(u, "input_tokens")),
            output_tokens=int_or_none(get(u, "output_tokens")),
            total_tokens=None,  # not reported by the Messages API
            cached_input_tokens=int_or_none(get(u, "cache_read_input_tokens")),
            cache_write_tokens=int_or_none(get(u, "cache_creation_input_tokens")),
            reasoning_tokens=thinking,
            # Thinking tokens are billed as output and reported within output_tokens.
            reasoning_included_in_output=True if thinking is not None else None,
        )
        if usage.input_tokens is not None and usage.output_tokens is not None:
            usage.total_tokens = (
                usage.input_tokens
                + usage.output_tokens
                + (usage.cached_input_tokens or 0)
                + (usage.cache_write_tokens or 0)
            )
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
