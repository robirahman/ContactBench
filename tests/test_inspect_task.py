"""Inspect integration (skipped unless inspect_ai is installed: pip install -e '.[inspect]')."""

import asyncio
import json
import math

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.model import ModelOutput, get_model  # noqa: E402

from contact_bench.config import ModelConfig  # noqa: E402
from contact_bench.inspect_task.adapter import InspectAdapter  # noqa: E402
from contact_bench.inspect_task.task import contact_bench, load_panel  # noqa: E402
from contact_bench.providers.base import DecisionRequest, ToolSpec  # noqa: E402

SCHEMA = {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"],
          "additionalProperties": False}


def _req(tools=True):
    calls = []

    def execute(name, args):
        calls.append((name, args))
        return {"result": args.get("word") == "apple"}

    return calls, DecisionRequest(
        decision_id="d", seat="guesser2", phase="respond", system_prompt="s", user_prompt="u",
        schema_name="guess", json_schema=SCHEMA, max_output_tokens=100,
        tools=[ToolSpec("is_legal_word", "check", {"type": "object", "properties": {"word": {"type": "string"}},
                                                    "required": ["word"], "additionalProperties": False})]
        if tools else [],
        tool_executor=execute if tools else None, max_tool_calls=8 if tools else 0)


def test_adapter_runs_the_lookup_tool_loop_and_returns_the_final_answer():
    model = get_model("mockllm/model", custom_outputs=[
        ModelOutput.for_tool_call("mockllm/model", "is_legal_word", {"word": "apple"}),
        ModelOutput.from_content("mockllm/model", '{"word": "apple"}'),
        # Non-OpenAI/Anthropic models get a final schema-constrained turn without tools.
        ModelOutput.from_content("mockllm/model", '{"word": "apple"}'),
    ])
    a = InspectAdapter(ModelConfig(id="m", provider="fake", model="m"), model)
    calls, req = _req()
    resp = asyncio.run(a.decide(req))
    assert calls == [("is_legal_word", {"word": "apple"})]
    assert json.loads(resp.output_text) == {"word": "apple"}
    assert resp.tool_trace and resp.tool_trace[0]["result"] == {"result": True}


def test_adapter_without_tools_is_one_call():
    model = get_model("mockllm/model", custom_outputs=[ModelOutput.from_content("mockllm/model", '{"word": "x"}')])
    a = InspectAdapter(ModelConfig(id="m", provider="fake", model="m"), model)
    _, req = _req(tools=False)
    assert json.loads(asyncio.run(a.decide(req)).output_text) == {"word": "x"}


def test_panel_ratings_and_dataset_are_deterministic():
    pan = load_panel("c50_api_v1")
    assert set(pan["opponents"]) == {"luna", "hydrogen", "terra", "carbon"}
    t1 = contact_bench(secrets_per_opponent=2, opponents="luna,terra")
    t2 = contact_bench(secrets_per_opponent=2, opponents="luna,terra")
    s1 = [(s.id, s.metadata["secret"]) for s in t1.dataset]
    assert s1 == [(s.id, s.metadata["secret"]) for s in t2.dataset] and len(s1) == 4
    with pytest.raises(ValueError):
        contact_bench(opponents="nobody")


def test_end_to_end_with_mock_models(tmp_path):
    # The mock model never produces a valid action, so both legs cap without a
    # letter: one no-progress draw (rematches off), scored 0.5.
    log = inspect_eval(contact_bench(secrets_per_opponent=1, opponents="luna", rematches=False),
                       model="mockllm/model", model_roles={"luna": "mockllm/model"},
                       log_dir=str(tmp_path), display="none")[0]
    assert log.status == "success"
    metrics = log.results.scores[0].metrics
    assert metrics["match_point_share"].value == 0.5
    # Luna was re-bound to the mock model, so its frozen Elo does not apply.
    assert math.isnan(metrics["anchored_elo"].value)
    sc = log.samples[0].scores["fixture_scorer"]
    assert sc.metadata["opponent_rebound"] and "excluded from anchored_elo" in sc.explanation
    fx = sc.metadata["fixtures"]
    assert len(fx) == 1 and fx[0]["no_progress_draw"] and fx[0]["points"] == 0.5


def _sample_score(points, rebound=False, opp="gpt_6_luna", elo=1615.5):
    from inspect_ai.scorer import SampleScore, Score

    return SampleScore(score=Score(value=points, metadata={
        "opponent_board_id": opp, "opponent_elo": elo, "opponent_rebound": rebound, "penalty_scale": 2.5,
        "elo_center": 1500.0, "fixtures": [{"points": points}]}), sample_id="x")


def test_anchored_metric_uses_only_calibrated_opponents():
    from contact_bench.inspect_task.task import _anchored, match_point_share

    draw = [_sample_score(0.5)]
    assert 1500 < _anchored(draw, "elo") < 1616  # a draw with Luna, pulled toward the prior centre
    mixed = draw + [_sample_score(1.0, rebound=True)]
    assert _anchored(mixed, "elo") == _anchored(draw, "elo")
    assert match_point_share()(mixed) == 0.75
