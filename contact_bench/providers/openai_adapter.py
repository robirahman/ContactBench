"""OpenAI Responses API adapter (spec Section 13.2).

Structured output via ``text.format`` JSON schema (strict), ``store=False``,
stateless single-turn input built from the filtered seat observation.  SDK
retries are disabled (``max_retries=0``); ProviderAdapter.decide owns retries.
"""

from __future__ import annotations

import json
from typing import Any

from ._stainless import map_stainless_error
from ._util import get, int_or_none, to_plain
from .base import AdapterResponse, DecisionRequest, NormalizedUsage, ProviderAdapter, ToolCall


class OpenAIResponsesAdapter(ProviderAdapter):
    provider = "openai"
    api_family = "responses"
    default_credential_env = "OPENAI_API_KEY"
    # Parameters forwarded verbatim to responses.create.  Anything else is rejected at preflight.
    supported_parameters = frozenset(
        {"reasoning", "temperature", "top_p", "service_tier", "prompt_cache_key", "prompt_cache_retention", "truncation"}
    )

    def __init__(self, model_config, *, client: Any = None, **kwargs: Any):
        super().__init__(model_config, **kwargs)
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import openai

            self._client = openai.AsyncOpenAI(api_key=self.credentials.require(self.credential_env), max_retries=0)
        return self._client

    def build_request(self, request: DecisionRequest, input_items: Any = None) -> dict:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "instructions": request.system_prompt,
            "input": request.user_prompt if input_items is None else input_items,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name,
                    "schema": request.json_schema,
                    "strict": True,
                }
            },
            "store": False,
            "max_output_tokens": request.max_output_tokens or self.config.max_output_tokens,
        }
        for k, v in self.config.parameters.items():
            kwargs[k] = v
        return kwargs

    async def _create(self, kwargs: dict) -> Any:
        import openai

        client = self._get_client()
        secrets = tuple(s for s in (self.credentials.get(self.credential_env or ""),) if s)
        try:
            return await client.responses.create(**kwargs)
        except openai.OpenAIError as e:
            raise map_stainless_error(e, openai, secrets) from None

    async def send_once(self, request: DecisionRequest) -> AdapterResponse:
        kwargs = self.build_request(request)
        resp = await self._create(kwargs)
        return self.parse_response(resp, kwargs)

    # -- lookup tools ----------------------------------------------------------
    # store=False means no previous_response_id: the full input item list is
    # carried by the caller.  Reasoning items are replayed with their
    # encrypted_content, which must be requested via ``include``.
    def tool_conversation_start(self, request: DecisionRequest) -> list:
        return [{"role": "user", "content": request.user_prompt}]

    def tool_kwargs(self, request: DecisionRequest, state: list, allow_tools: bool) -> dict:
        kwargs = self.build_request(request, input_items=list(state))
        kwargs["tools"] = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "strict": False,  # optional arguments (offset/limit) are not strict-compatible
            }
            for t in request.tools
        ]
        kwargs["tool_choice"] = "auto" if allow_tools else "none"
        kwargs["include"] = ["reasoning.encrypted_content"]
        return kwargs

    async def send_tool_turn(self, request: DecisionRequest, state: list, allow_tools: bool):
        kwargs = self.tool_kwargs(request, state, allow_tools)
        raw = await self._create(kwargs)
        resp = self.parse_response(raw, kwargs)
        calls: list[ToolCall] = []
        appended: list[dict] = []
        for item in get(raw, "output", None) or []:
            plain = to_plain(item)
            if isinstance(plain, dict):
                plain = {k: v for k, v in plain.items() if v is not None}
            appended.append(plain)
            if get(item, "type") == "function_call":
                raw_args = get(item, "arguments") or "{}"
                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        args = {"_unparseable_arguments": raw_args}
                except (TypeError, json.JSONDecodeError):
                    args = {"_unparseable_arguments": raw_args}
                calls.append(ToolCall(id=get(item, "call_id") or get(item, "id") or "", name=get(item, "name") or "", arguments=args))
        return resp, calls, list(state) + appended

    def tool_conversation_append(self, state: list, calls: list[ToolCall], results: list[Any]) -> list:
        out = list(state)
        for c, r in zip(calls, results):
            out.append({"type": "function_call_output", "call_id": c.id, "output": json.dumps(r)})
        return out

    def parse_response(self, resp: Any, kwargs: dict) -> AdapterResponse:
        texts: list[str] = []
        refusal = False
        for item in get(resp, "output", None) or []:
            if get(item, "type") != "message":
                continue
            for c in get(item, "content", None) or []:
                t = get(c, "type")
                if t == "output_text":
                    texts.append(get(c, "text", "") or "")
                elif t == "refusal":
                    refusal = True
        status = get(resp, "status")
        incomplete = status == "incomplete"
        reason = get(get(resp, "incomplete_details"), "reason")
        finish = "refusal" if refusal else (reason or status)
        u = get(resp, "usage")
        usage = NormalizedUsage(
            input_tokens=int_or_none(get(u, "input_tokens")),
            output_tokens=int_or_none(get(u, "output_tokens")),
            total_tokens=int_or_none(get(u, "total_tokens")),
            cached_input_tokens=int_or_none(get(get(u, "input_tokens_details"), "cached_tokens")),
            cache_write_tokens=int_or_none(get(get(u, "input_tokens_details"), "cache_write_tokens")),
            reasoning_tokens=int_or_none(get(get(u, "output_tokens_details"), "reasoning_tokens")),
            # OpenAI reports reasoning tokens as a breakdown of output_tokens.
            reasoning_included_in_output=True if u is not None else None,
        )
        effective = {k: v for k, v in kwargs.items() if k in self.supported_parameters}
        effective.update(store=False, max_output_tokens=kwargs["max_output_tokens"])
        return AdapterResponse(
            output_text=("".join(texts) if texts else None),
            provider=self.provider,
            api_family=self.api_family,
            response_id=get(resp, "id"),
            request_id=getattr(resp, "_request_id", None),
            requested_model=self.config.model,
            returned_model=get(resp, "model"),
            finish_reason=finish,
            refusal=refusal,
            incomplete=incomplete,
            raw_usage=to_plain(u) if u is not None else None,
            usage=usage,
            requested_parameters=dict(self.config.parameters),
            effective_parameters=effective,
        )
