"""Cache-friendly prompt layout: append-only prefix and Anthropic breakpoints."""

from contact_bench.config import ModelConfig
from contact_bench.prompts.templates import user_prompt, user_prompt_parts
from contact_bench.providers.anthropic_adapter import AnthropicMessagesAdapter
from contact_bench.providers.base import DecisionRequest
from contact_bench.providers.fake import parse_observation

from .helpers import block, clue, guess, make_game, run_turn

W = ["cable", "camera", "candle", "candy", "canoe", "carrot", "castle", "cobra", "comet", "crane"]


def _two_turns():
    g = make_game(W, "candle", L=6)
    s1 = run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                      ("defender", "block"): block("comet")})
    s2 = run_turn(g, {("guesser1", "act"): clue("canoe", "boat"), ("guesser2", "respond"): guess("canoe"),
                      ("defender", "block"): block()})
    s3 = run_turn(g, {("guesser1", "act"): clue("cable", "wire"), ("guesser2", "respond"): guess("cobra"),
                      ("defender", "block"): block()})
    return s2, s3


def test_prefix_is_append_only_across_turns_and_shared_across_seats():
    s2, s3 = _two_turns()
    p_t2, n_t2 = user_prompt_parts(s2.obs(2, "guesser2", "respond"))
    p_t3, n_t3 = user_prompt_parts(s3.obs(3, "guesser2", "respond"))
    assert n_t3 == n_t2 + 1 and p_t3[:n_t2] == p_t2[:n_t2]  # previous prefix reused
    d_t3, nd = user_prompt_parts(s3.obs(3, "defender", "block"))
    assert d_t3[:nd] == p_t3[:n_t3]  # same prefix for every seat; no secret in it
    assert "candle" not in "".join(d_t3[:nd])
    assert "candle" in d_t3[-1]  # the defender's secret is only in the volatile tail


def test_joined_prompt_still_carries_full_observation():
    s2, _ = _two_turns()
    obs = s2.obs(2, "defender", "block")
    parsed = parse_observation(user_prompt(obs))
    assert parsed == {k: v for k, v in obs.items() if k != "public_history"}


def test_anthropic_cache_breakpoints():
    s2, _ = _two_turns()
    parts, n = user_prompt_parts(s2.obs(2, "guesser2", "respond"))
    ad = AnthropicMessagesAdapter(ModelConfig(id="a", provider="anthropic", model="m", max_output_tokens=100,
                                              credential_env="ANTHROPIC_API_KEY"))
    req = DecisionRequest("d", "guesser2", "respond", "SYSTEM", "\n\n".join(parts), "s", {},
                          user_prompt_parts=parts, cache_prefix_parts=n)
    kw = ad.build_request(req)
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    blocks = kw["messages"][0]["content"]
    marked = [i for i, b in enumerate(blocks) if "cache_control" in b]
    assert marked == [n - 1] and len(blocks) == len(parts)


def test_max_effort_uses_one_hour_cache_on_every_breakpoint():
    import asyncio

    s2, _ = _two_turns()
    parts, n = user_prompt_parts(s2.obs(2, "guesser2", "respond"))
    mc = ModelConfig(id="a", provider="anthropic", model="m", max_output_tokens=100,
                     credential_env="ANTHROPIC_API_KEY", parameters={"effort": "max"})
    ad = AnthropicMessagesAdapter(mc)
    req = DecisionRequest("d", "guesser2", "respond", "SYSTEM", "\n\n".join(parts), "s", {},
                          user_prompt_parts=parts, cache_prefix_parts=n)
    kw = ad.build_request(req)
    one_hour = {"type": "ephemeral", "ttl": "1h"}
    assert kw["system"][0]["cache_control"] == one_hour
    assert kw["messages"][0]["content"][n - 1]["cache_control"] == one_hour
    # tool-loop breakpoint on the growing conversation
    state = ad.tool_conversation_start(req) + [
        {"role": "assistant", "content": [{"type": "text", "text": "x"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}]
    sent = {}

    class C:
        class messages:
            @staticmethod
            async def create(**k):
                sent.update(k)
                raise RuntimeError("stop")

    ad._client = C
    ad._call = lambda k: C.messages.create(**k)
    try:
        asyncio.run(ad.send_tool_turn(req, state, False))
    except RuntimeError:
        pass
    assert sent["messages"][-1]["content"][-1]["cache_control"] == one_hour


def test_one_hour_cache_writes_are_priced_at_twice_base_input():
    from contact_bench.config import PriceTable
    from contact_bench.providers.base import NormalizedUsage
    from contact_bench.runner.budget import estimate_cost

    p = PriceTable(as_of="2026-11-19", source="t", input_per_mtok=8.0, output_per_mtok=40.0,
                   cached_input_per_mtok=0.2, cache_write_per_mtok=10.0)
    five = NormalizedUsage(input_tokens=1_000_000, output_tokens=0, cache_write_tokens=1_000_000)
    hour = NormalizedUsage(input_tokens=1_000_000, output_tokens=0, cache_write_tokens=1_000_000,
                           cache_write_1h_tokens=1_000_000)
    assert abs(estimate_cost(p, five) - 10.0) < 1e-9
    assert abs(estimate_cost(p, hour) - 16.0) < 1e-9


def test_parse_reports_one_hour_cache_writes():
    mc = ModelConfig(id="a", provider="anthropic", model="m", max_output_tokens=100,
                     credential_env="ANTHROPIC_API_KEY", parameters={"effort": "max"})
    msg = {"id": "m1", "model": "m", "stop_reason": "end_turn", "content": [{"type": "text", "text": "{}"}],
           "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100,
                     "cache_creation_input_tokens": 50,
                     "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 50}}}
    r = AnthropicMessagesAdapter(mc).parse_response(msg, {"max_tokens": 100})
    assert r.usage.input_tokens == 160 and r.usage.cache_write_tokens == 50 and r.usage.cache_write_1h_tokens == 50
