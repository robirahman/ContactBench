"""ProviderAdapter backed by an Inspect model.

The engine, prompts, admission and scoring are unchanged; only the transport
is Inspect's model API, so every call appears in the Inspect eval log.
Inspect owns retries (``GenerateConfig.max_retries``); this adapter makes one
attempt per call.  Structured output is combined with lookup tools exactly as
in the arena adapters: OpenAI and Anthropic get the JSON schema on every turn;
for other providers (Google, open-weight servers) lookup turns run without the
schema and the final answer is requested with tools disabled and the schema
enforced.
"""

from __future__ import annotations

import json
import time
from typing import Any

from inspect_ai.model import (
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    ResponseSchema,
)
from inspect_ai.tool import ToolInfo, ToolParams
from inspect_ai.util import JSONSchema

from contact_bench.config import ModelConfig
from contact_bench.providers.base import (
    AdapterResponse,
    DecisionRequest,
    InfrastructureError,
    NormalizedUsage,
    ProviderAdapter,
    RetryPolicy,
    ToolCall,
)


def _usage(out: ModelOutput) -> NormalizedUsage:
    u = out.usage
    if u is None:
        return NormalizedUsage()
    cached = (u.input_tokens_cache_read or 0) or None
    write = (u.input_tokens_cache_write or 0) or None
    # NormalizedUsage counts cache reads/writes inside input_tokens.
    total_in = (u.input_tokens or 0) + (u.input_tokens_cache_read or 0) + (u.input_tokens_cache_write or 0)
    return NormalizedUsage(input_tokens=total_in, output_tokens=u.output_tokens, total_tokens=u.total_tokens,
                           cached_input_tokens=cached, cache_write_tokens=write,
                           reasoning_tokens=u.reasoning_tokens)


class InspectAdapter(ProviderAdapter):
    provider = "inspect"
    api_family = "inspect"
    structured_output_with_tools = False

    def __init__(self, model_config: ModelConfig, model: Model, config: GenerateConfig | None = None):
        super().__init__(model_config, retry=RetryPolicy(max_attempts=1, base_seconds=0, deadline_seconds=0))
        self.model = model
        self.base_config = config or GenerateConfig()
        # Matches the arena: schema alongside tools for OpenAI/Anthropic only.
        self.structured_output_with_tools = str(model).split("/")[0] in ("openai", "anthropic")

    # -- helpers ---------------------------------------------------------------
    def _config(self, request: DecisionRequest, with_schema: bool) -> GenerateConfig:
        extra: dict[str, Any] = {}
        if request.max_output_tokens:
            extra["max_tokens"] = request.max_output_tokens
        if with_schema:
            extra["response_schema"] = ResponseSchema(
                name=request.schema_name, json_schema=JSONSchema.model_validate(request.json_schema), strict=True)
        return self.base_config.merge(GenerateConfig(**extra))

    @staticmethod
    def _tools(request: DecisionRequest) -> list[ToolInfo]:
        return [ToolInfo(name=t.name, description=t.description, parameters=ToolParams.model_validate(t.parameters))
                for t in request.tools]

    async def _generate(self, request: DecisionRequest, messages: list, *, tools: list, with_schema: bool):
        t0 = time.monotonic()
        try:
            out = await self.model.generate(messages, tools=tools, tool_choice="auto" if tools else None,
                                            config=self._config(request, with_schema))
        except Exception as e:  # Inspect has already applied its own retries.
            raise InfrastructureError(f"{type(e).__name__}: {e}", category="unknown", fatal=True) from e
        msg = out.message
        calls = [ToolCall(c.id, c.function, c.arguments if isinstance(c.arguments, dict) else {})
                 for c in (msg.tool_calls or [])] if tools else []
        resp = AdapterResponse(
            output_text=None if calls else (out.completion or None),
            provider="inspect", api_family=str(self.model.api.__class__.__name__),
            requested_model=str(self.model), returned_model=out.model,
            finish_reason=str(out.stop_reason) if out.choices else None,
            refusal=bool(out.choices and out.stop_reason == "content_filter"),
            incomplete=bool(out.choices and out.stop_reason == "max_tokens"),
            usage=_usage(out), latency_s=time.monotonic() - t0,
            effective_parameters={k: v for k, v in self._config(request, with_schema).model_dump(
                exclude_none=True).items() if k != "response_schema"},
        )
        return resp, calls, msg

    # -- ProviderAdapter -------------------------------------------------------
    async def send_once(self, request: DecisionRequest) -> AdapterResponse:
        msgs = [ChatMessageSystem(content=request.system_prompt), ChatMessageUser(content=request.user_prompt)]
        resp, _, _ = await self._generate(request, msgs, tools=[], with_schema=True)
        return resp

    def tool_conversation_start(self, request: DecisionRequest) -> Any:
        return [ChatMessageSystem(content=request.system_prompt), ChatMessageUser(content=request.user_prompt)]

    async def send_tool_turn(self, request: DecisionRequest, state: Any, allow_tools: bool):
        resp, calls, msg = await self._generate(request, state, tools=self._tools(request) if allow_tools else [],
                                                with_schema=self.structured_output_with_tools or not allow_tools)
        return resp, calls, list(state) + [msg]

    def tool_conversation_append(self, state: Any, calls: list[ToolCall], results: list[Any]) -> Any:
        return list(state) + [ChatMessageTool(content=json.dumps(r), tool_call_id=c.id, function=c.name)
                              for c, r in zip(calls, results)]
