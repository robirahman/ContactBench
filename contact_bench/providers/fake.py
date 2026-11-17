"""Offline fake adapter with canned fixture behaviours (spec Section 13.3).

FakeAdapter never touches the network or credentials.  It reads the seat
observation embedded in the user prompt and plays a legal first/last-style
policy, or reproduces a selected failure fixture.
"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    AdapterResponse,
    DecisionRequest,
    InfrastructureError,
    NormalizedUsage,
    ProviderAdapter,
    ToolCall,
)

OBS_MARKER = "OBSERVATION (JSON):"

FAKE_BEHAVIORS = {
    None,
    "legal",
    "refusal",
    "truncation",
    "invalid_json",
    "transient_then_ok",
    "always_transient",
    "auth_error",
    "missing_usage",
}


def parse_observation(user_prompt: str) -> dict:
    idx = user_prompt.rfind(OBS_MARKER)
    if idx < 0:
        raise ValueError("user prompt contains no observation block")
    return json.loads(user_prompt[idx + len(OBS_MARKER):].strip())


def _forecast(obs: dict) -> dict:
    support = obs.get("contact_candidates") or []
    if len(support) <= 1:
        return {"entries": [{"word": support[0], "probability": 1.0}] if support else [], "other_mass": 0.0 if support else 1.0}
    return {"entries": [{"word": support[0], "probability": 0.5}], "other_mass": 0.5}


def legal_action(obs: dict) -> dict:
    """First/last-style legal action for the observed seat and phase."""
    seat, phase = obs["role"], obs["phase"]
    cands = obs.get("secret_candidates") or []
    if not cands and "secret_candidates" not in obs and seat == "guesser1" and phase != "choice":
        # Closed book: the fake has no lexical knowledge; it emits a fixed
        # (usually illegal) word, which exercises the invalid-action path.
        return {"action": "direct", "word": obs["prefix"] + "zzz", "clue": None}
    if phase == "choice":
        return {"action": "reveal"}
    if seat == "guesser1":
        if len(cands) == 1:
            return {"action": "direct", "word": cands[0], "clue": None}
        return {"action": "clue", "word": cands[0], "clue": "?"}
    if seat == "guesser2":
        action = {"action": "guess", "word": cands[-1]} if cands else {"action": "pass", "word": None}
    else:
        action = {"action": "block", "words": []}
        if obs.get("blocklist_encoding") == "words_and_ranges":
            action["ranges"] = []
    if obs.get("forecast_reports_requested"):
        diag = {"intended_word_forecast": _forecast(obs), "commitment_match_forecast": None}
        return {"gameplay": action, "diagnostics": diag}
    return action


class FakeAdapter(ProviderAdapter):
    provider = "fake"
    api_family = "fake"
    supported_parameters = frozenset({"note"})

    def __init__(self, model_config, **kwargs: Any):
        super().__init__(model_config, **kwargs)
        behavior = model_config.fake_behavior
        if behavior not in FAKE_BEHAVIORS:
            raise ValueError(f"unknown fake_behavior {behavior!r}")
        self.behavior = behavior or "legal"
        self._failed_once: set[str] = set()
        self.calls = 0

    def preflight(self, *, require_credentials: bool = False) -> dict:
        unsupported = set(self.config.parameters) - set(self.supported_parameters)
        if unsupported:
            from .base import AdapterConfigError

            raise AdapterConfigError(f"fake: unsupported parameters {sorted(unsupported)}")
        return self.capabilities()

    def check_credentials(self) -> None:
        return None

    async def send_once(self, request: DecisionRequest) -> AdapterResponse:
        self.calls += 1
        b = self.behavior
        if b == "auth_error":
            raise InfrastructureError("fake authentication failure", category="auth", fatal=True)
        if b == "always_transient" or (b == "transient_then_ok" and request.decision_id not in self._failed_once):
            self._failed_once.add(request.decision_id)
            raise InfrastructureError(
                "fake rate limit", category="rate_limit", retryable=True, retry_after=0.0
            )
        obs = parse_observation(request.user_prompt)
        payload = _forecast(obs) if request.phase == "forecast" else legal_action(obs)
        return self._respond(request, payload)

    # -- lookup tools: one list_words call, then a first/last answer ----------
    def tool_conversation_start(self, request: DecisionRequest) -> Any:
        return {"obs": parse_observation(request.user_prompt), "words": None}

    async def send_tool_turn(self, request: DecisionRequest, state: Any, allow_tools: bool):
        self.calls += 1
        obs = state["obs"]
        if allow_tools and state["words"] is None and request.phase != "choice":
            call = ToolCall(id=f"call-{self.calls}", name="list_words",
                            arguments={"prefix": obs["prefix"], "offset": 0, "limit": 100})
            resp = self._respond(request, None)
            return resp, [call], state
        if state["words"] is not None and "secret_candidates" not in obs:
            used = set(obs["used_words"])
            rng = obs.get("used_ranges") or []
            cands = [w for w in state["words"] if w not in used and not any(a <= w <= b for a, b in rng)
                     and len(w) > len(obs["prefix"])]
            obs = {**obs, "secret_candidates": cands, "contact_candidates": cands}
        payload = _forecast(obs) if request.phase == "forecast" else legal_action(obs)
        return self._respond(request, payload), [], state

    def tool_conversation_append(self, state: Any, calls: list[ToolCall], results: list[Any]) -> Any:
        res = results[0] if results else {}
        return {**state, "words": res.get("result", []) if isinstance(res, dict) else []}

    def _respond(self, request: DecisionRequest, payload: Any) -> AdapterResponse:
        b = self.behavior
        text = json.dumps(payload, separators=(",", ":")) if payload is not None else None
        resp = AdapterResponse(
            output_text=text,
            provider=self.provider,
            api_family=self.api_family,
            response_id=f"fake-{request.decision_id}",
            request_id=f"fake-req-{self.calls}",
            requested_model=self.config.model or "fake-model",
            returned_model=self.config.model or "fake-model",
            finish_reason="stop",
            requested_parameters=dict(self.config.parameters),
            effective_parameters=dict(self.config.parameters),
        )
        if b == "refusal":
            resp.output_text = None
            resp.refusal = True
            resp.finish_reason = "refusal"
        elif b == "truncation":
            resp.output_text = text[: max(1, len(text) // 2)]
            resp.incomplete = True
            resp.finish_reason = "max_output_tokens"
        elif b == "invalid_json":
            resp.output_text = "I think the answer is " + text
        if payload is None:
            resp.output_text = None
        out = resp.output_text or ""
        if b == "missing_usage":
            resp.usage = NormalizedUsage()
            resp.raw_usage = None
        else:
            inp = (len(request.system_prompt) + len(request.user_prompt)) // 4
            o = max(1, len(out) // 4)
            resp.usage = NormalizedUsage(
                input_tokens=inp,
                output_tokens=o,
                total_tokens=inp + o,
                cached_input_tokens=0,
                cache_write_tokens=0,
                reasoning_tokens=0,
                reasoning_included_in_output=True,
            )
            resp.raw_usage = {"input_tokens": inp, "output_tokens": o}
        return resp
