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
