"""Provider-independent adapter contract (spec Section 13.1).

An adapter obtains exactly one model response for one decision request.  The
engine validates and adjudicates; an adapter must never reinterpret, repair,
substitute or semantically retry an answer.  Only eligible infrastructure
errors are retried, with the same request, under a bounded policy.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

from ..config import ModelConfig


class AdapterConfigError(ValueError):
    """Preflight failure: unsupported parameter, missing credential, bad model settings."""


class InfrastructureError(Exception):
    """Transport/provider failure (not model behavior).

    category: one of transient, rate_limit, timeout, server, auth, invalid_model,
    unsupported_parameter, quota_exhausted, bad_request, unknown.
    retryable: whether the same request may be re-sent.
    fatal: halts or pauses the affected run (auth, invalid model, quota, ...).
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",
        retryable: bool = False,
        fatal: bool = False,
        retry_after: float | None = None,
        possibly_billed: bool = False,
    ):
        super().__init__(sanitize(message))
        self.category = category
        self.retryable = retryable
        self.fatal = fatal
        self.retry_after = retry_after
        self.possibly_billed = possibly_billed


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-~+/=]+"),
    re.compile(r"(?i)(api[_-]?key|authorization|x-api-key|x-goog-api-key)\s*[:=]\s*(bearer\s+)?\S+"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
]


def sanitize(text: str, extra_secrets: tuple[str, ...] = ()) -> str:
    """Remove credentials from error text before it is logged or exported."""
    s = str(text)
    for v in extra_secrets:
        if v:
            s = s.replace(v, "[REDACTED]")
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        v = os.environ.get(env)
        if v:
            s = s.replace(v, "[REDACTED]")
    for p in _SECRET_PATTERNS:
        s = p.sub("[REDACTED]", s)
    return s[:2000]


@dataclass
class NormalizedUsage:
    """Nullable usage fields.  Unknown is None, never zero.

    Convention: ``input_tokens`` counts ALL input tokens, including cache
    reads (``cached_input_tokens``) and cache writes (``cache_write_tokens``),
    which are subsets of it.  Adapters whose API reports them as disjoint
    fields (Anthropic) add them in.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    # True when reasoning tokens are already counted within output_tokens
    # (OpenAI); False when billed as a separate category; None if unknown.
    reasoning_included_in_output: bool | None = None

    def billable_output_tokens(self) -> int | None:
        if self.output_tokens is None:
            return None
        if self.reasoning_included_in_output is False and self.reasoning_tokens:
            return self.output_tokens + self.reasoning_tokens
        return self.output_tokens


@dataclass
class TransportAttempt:
    attempt: int
    started_at: float
    latency_s: float
    outcome: str  # ok | error
    error_category: str | None = None
    error_message: str | None = None
    retry_after: float | None = None
    possibly_billed: bool = False


@dataclass(frozen=True)
class ToolSpec:
    """A deterministic, side-effect-free lookup function offered to a model."""

    name: str
    description: str
    parameters: dict  # JSON Schema of the arguments object


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


# A tool executor maps (name, arguments) to a JSON-serializable result.  It
# must never raise: bad arguments produce {"error": ...}.
ToolExecutor = Callable[[str, dict], Any]


@dataclass
class DecisionRequest:
    decision_id: str
    seat: str
    phase: str
    system_prompt: str
    user_prompt: str
    schema_name: str
    json_schema: dict
    max_output_tokens: int | None = None
    tools: list[ToolSpec] = field(default_factory=list)
    tool_executor: ToolExecutor | None = None
    max_tool_calls: int = 0
    # Optional structured form of user_prompt for prefix caching:
    # "\n\n".join(user_prompt_parts) == user_prompt, and the first
    # cache_prefix_parts parts are an append-only, cacheable prefix.
    user_prompt_parts: list[str] = field(default_factory=list)
    cache_prefix_parts: int = 0
    # Keep the provider-native conversation (ending with the final assistant
    # turn) on the response so it can be forked for private forecast queries.
    keep_conversation: bool = False


class AttemptGate:
    """Hook around every transport attempt (budget reservation / accounting).

    ``before`` may raise (e.g. BudgetExhausted) to stop the decision before a
    request is sent; ``after`` is always called once per ``before``.
    """

    async def before(self) -> Any:  # pragma: no cover - interface
        return None

    async def after(self, token: Any, usage: "NormalizedUsage | None", ok: bool,
                    possibly_billed: bool = True) -> None:  # pragma: no cover
        return None


def sum_usage(usages: list["NormalizedUsage"]) -> "NormalizedUsage":
    """Sum usage across model turns; a field is None if any turn lacks it."""
    if len(usages) == 1:
        return usages[0]
    out = NormalizedUsage()
    for f in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
              "cache_write_tokens", "reasoning_tokens"):
        vals = [getattr(u, f) for u in usages]
        setattr(out, f, None if any(v is None for v in vals) else sum(vals))
    flags = {u.reasoning_included_in_output for u in usages}
    out.reasoning_included_in_output = flags.pop() if len(flags) == 1 else None
    return out


@dataclass
class AdapterResponse:
    output_text: str | None
    parsed: Any = None
    provider: str = ""
    api_family: str = ""
    response_id: str | None = None
    request_id: str | None = None
    requested_model: str | None = None
    returned_model: str | None = None
    finish_reason: str | None = None
    refusal: bool = False
    incomplete: bool = False
    raw_usage: dict | None = None
    usage: NormalizedUsage = field(default_factory=NormalizedUsage)
    latency_s: float | None = None
    attempts: list[TransportAttempt] = field(default_factory=list)
    requested_parameters: dict = field(default_factory=dict)
    effective_parameters: dict = field(default_factory=dict)
    # Lookup-tool trace (private diagnostics; never gameplay utterances).
    tool_trace: list[dict] = field(default_factory=list)
    model_turns: int = 1
    # Provider-native transcript for forking (never serialized or logged).
    conversation: Any = field(default=None, repr=False, compare=False)

    def to_json(self) -> dict:
        conv, self.conversation = self.conversation, None
        try:
            return asdict(self)
        finally:
            self.conversation = conv


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_seconds: float = 1.0
    max_seconds: float = 60.0
    deadline_seconds: float = 300.0
    # Rate limits (HTTP 429) are expected under concurrency and clear with
    # time, so they get a larger attempt budget within the same deadline.
    rate_limit_attempts: int = 8


class CredentialSource:
    """Reads credentials from the environment or an injected mapping.

    Credentials are never stored on adapter objects that get serialized, and
    never appear in configuration snapshots or logs.
    """

    def __init__(self, injected: Mapping[str, str] | None = None):
        self._injected = dict(injected or {})

    def get(self, name: str) -> str | None:
        return self._injected.get(name) or os.environ.get(name) or None

    def require(self, name: str | None) -> str:
        if not name:
            raise AdapterConfigError("credential_env is not configured for this model")
        v = self.get(name)
        if not v:
            raise AdapterConfigError(f"missing credential: environment variable {name} is not set")
        return v


class ProviderAdapter(ABC):
    provider: str = ""
    api_family: str = ""
    # Parameters this adapter knows how to send.  Anything else fails preflight.
    supported_parameters: frozenset[str] = frozenset()
    # False when the provider misbehaves if structured output and tools are
    # requested together.  The tool loop then runs lookup turns without the
    # output format and finishes with one extra turn that has tools disabled
    # and the JSON schema enforced, so the final answer is still strictly
    # validated.
    structured_output_with_tools: bool = True

    def __init__(
        self,
        model_config: ModelConfig,
        *,
        credentials: CredentialSource | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        jitter: random.Random | None = None,
    ):
        self.config = model_config
        self.credentials = credentials or CredentialSource()
        self.retry = retry or RetryPolicy()
        self._sleep = sleep or asyncio.sleep
        self._clock = clock
        self._jitter = jitter or random.Random(0)

    # Environment variable used when ModelConfig.credential_env is unset.
    default_credential_env: str | None = None

    @property
    def credential_env(self) -> str | None:
        return self.config.credential_env or self.default_credential_env

    def check_credentials(self) -> None:
        """Raise AdapterConfigError if the credential is unavailable (no network)."""
        self.credentials.require(self.credential_env)

    # -- preflight -----------------------------------------------------------
    def preflight(self, *, require_credentials: bool = False) -> dict:
        """Validate configuration without network access; return capability metadata.

        Offline preflight never needs keys; live runs pass require_credentials=True.
        """
        if require_credentials:
            self.check_credentials()
        unsupported = set(self.config.parameters) - set(self.supported_parameters)
        if unsupported:
            raise AdapterConfigError(
                f"{self.provider}/{self.api_family}: unsupported parameters {sorted(unsupported)}; "
                "remove them or extend the adapter (they are never silently dropped)"
            )
        bad = self.config.unresolved_placeholders()
        if bad:
            raise AdapterConfigError(f"model {self.config.id}: unresolved placeholders in {bad}")
        if not self.config.model:
            raise AdapterConfigError(f"model {self.config.id}: model identifier is required")
        if not self.config.max_output_tokens:
            raise AdapterConfigError(f"model {self.config.id}: max_output_tokens must be set explicitly")
        return self.capabilities()

    def capabilities(self) -> dict:
        return {
            "provider": self.provider,
            "api_family": self.api_family,
            "schema_mode": "json_schema",
            "max_output_tokens": self.config.max_output_tokens,
            "context_window_tokens": self.config.context_window_tokens,
            "provider_side_state": "disabled_or_unused",
            "supported_parameters": sorted(self.supported_parameters),
        }

    # -- transport -----------------------------------------------------------
    @abstractmethod
    async def send_once(self, request: DecisionRequest) -> AdapterResponse:
        """Exactly one transport attempt.  Raise InfrastructureError on failure."""

    async def decide(self, request: DecisionRequest, gate: AttemptGate | None = None) -> AdapterResponse:
        """Obtain one decision.

        Without tools this is one model call under the bounded retry policy.
        With tools it is a model/tool loop in which every model call is
        individually retried.  The first successfully received complete
        response of each call is used; there is no best-of-retries selection.
        SDK-internal retries must be disabled by concrete adapters.  ``gate``
        is invoked around every transport attempt, including retries and
        tool-loop turns, so request and spend caps hold per call.
        """
        if not request.tools and not request.keep_conversation:
            resp, attempts = await self._with_retries(lambda: self.send_once(request), gate)
            resp.attempts = attempts
            resp.latency_s = attempts[-1].latency_s
            return resp
        return await self._tool_loop(request, gate)

    async def fork(self, request: DecisionRequest, base_conversation: Any,
                   gate: AttemptGate | None = None) -> AdapterResponse:
        """Branch a finished transcript: append ``request.user_prompt`` as a new
        user turn after the model's own final answer and obtain a reply under
        ``request.json_schema``.  The original transcript is not modified and
        nothing from the branch flows back into the game."""
        if base_conversation is None:
            raise AdapterConfigError("fork requires a kept conversation (keep_conversation=True)")
        state = self.conversation_append_user(base_conversation, request.user_prompt)
        return await self._tool_loop(request, gate, initial_state=state)

    def conversation_append_user(self, state: Any, text: str) -> Any:
        raise AdapterConfigError(f"{self.provider}/{self.api_family}: transcript forking is not supported")

    async def _with_retries(self, fn: Callable[[], Any], gate: AttemptGate | None) -> tuple[Any, list[TransportAttempt]]:
        attempts: list[TransportAttempt] = []
        start = self._clock()
        last: InfrastructureError | None = None
        limit = self.retry.max_attempts
        i = 0
        while i < max(limit, self.retry.rate_limit_attempts):
            i += 1
            token = await gate.before() if gate is not None else None
            t0 = self._clock()
            try:
                out = await fn()
            except InfrastructureError as e:
                if gate is not None:
                    # Only failures that may have generated output (e.g. a
                    # timeout after sending) can have been billed.
                    await gate.after(token, None, False, possibly_billed=e.possibly_billed)
                attempts.append(
                    TransportAttempt(
                        i, t0, self._clock() - t0, "error", e.category, str(e), e.retry_after, e.possibly_billed
                    )
                )
                last = e
                if e.category == "rate_limit":
                    limit = max(limit, self.retry.rate_limit_attempts)
                if e.fatal or not e.retryable or i >= limit:
                    break
                delay = e.retry_after
                if delay is None:
                    delay = min(self.retry.max_seconds, self.retry.base_seconds * 2 ** (i - 1))
                    delay *= 0.5 + self._jitter.random()
                if self._clock() - start + delay > self.retry.deadline_seconds:
                    break
                await self._sleep(delay)
                continue
            except BaseException:
                if gate is not None:
                    await gate.after(token, None, False)
                raise
            resp = out[0] if isinstance(out, tuple) else out
            if gate is not None:
                await gate.after(token, resp.usage, True)
            attempts.append(TransportAttempt(i, t0, self._clock() - t0, "ok"))
            return out, attempts
        assert last is not None
        err = InfrastructureError(
            str(last), category=last.category, retryable=False, fatal=last.fatal, retry_after=last.retry_after
        )
        err.attempts = attempts  # type: ignore[attr-defined]
        raise err

    # -- lookup-tool loop -----------------------------------------------------
    def tool_conversation_start(self, request: DecisionRequest) -> Any:
        raise AdapterConfigError(f"{self.provider}/{self.api_family}: lookup tools are not supported")

    async def send_tool_turn(
        self, request: DecisionRequest, state: Any, allow_tools: bool
    ) -> tuple[AdapterResponse, list[ToolCall], Any]:
        """One model call.  Returns the response, requested tool calls and the
        conversation state with the assistant turn appended."""
        raise AdapterConfigError(f"{self.provider}/{self.api_family}: lookup tools are not supported")

    def tool_conversation_append(self, state: Any, calls: list[ToolCall], results: list[Any]) -> Any:
        raise AdapterConfigError(f"{self.provider}/{self.api_family}: lookup tools are not supported")

    async def _tool_loop(self, request: DecisionRequest, gate: AttemptGate | None,
                         initial_state: Any = None) -> AdapterResponse:
        assert request.tool_executor is not None or not request.tools, "tools require an executor"
        limit = max(0, request.max_tool_calls) if request.tools else 0
        state = initial_state if initial_state is not None else self.tool_conversation_start(request)
        trace: list[dict] = []
        attempts: list[TransportAttempt] = []
        usages: list[NormalizedUsage] = []
        n_calls = 0
        turns = 0
        force_final = False
        while True:
            turns += 1
            allow = n_calls < limit and not force_final
            (resp, calls, state), att = await self._with_retries(
                lambda s=state, a=allow: self.send_tool_turn(request, s, a), gate
            )
            attempts.extend(att)
            usages.append(resp.usage)
            done = not calls or resp.refusal or resp.incomplete
            if done and not calls and allow and not resp.refusal and not self.structured_output_with_tools:
                # Lookup phase ended without the schema; request the final,
                # schema-constrained answer with tools disabled.
                force_final = True
                continue
            if not done and turns > limit + 2:
                # The model kept requesting tools after being told to answer.
                resp.output_text = None
                resp.incomplete = True
                resp.finish_reason = "tool_loop_limit"
                done = True
            if done:
                resp.usage = sum_usage(usages)
                resp.attempts = attempts
                resp.latency_s = sum(a.latency_s for a in attempts)
                resp.tool_trace = trace
                resp.model_turns = turns
                resp.conversation = state
                return resp
            results = []
            for c in calls:
                if n_calls >= limit or request.tool_executor is None:
                    r = {"error": f"tool call limit ({limit}) reached; reply now with your final JSON answer"}
                else:
                    r = request.tool_executor(c.name, c.arguments)
                    n_calls += 1
                trace.append({"turn": turns, "name": c.name, "arguments": c.arguments, "result": r})
                results.append(r)
            state = self.tool_conversation_append(state, calls, results)


def requested_and_effective(config: ModelConfig, effective: dict) -> tuple[dict, dict]:
    return dict(config.parameters), dict(effective)
