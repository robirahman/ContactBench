"""Engine, admission and information-boundary acceptance tests (spec 18.1)."""

import asyncio
import json

import pytest

from contact_bench.engine.game import EngineInvariantError, GameSetupError
from contact_bench.fixtures import MECHANICS_DECISIONS, mechanics_game, table_decider
from contact_bench.lexicon import mentioned_words, normalize_word

from .helpers import (
    CANCEL, PASS, REVEAL, UNAVAILABLE, block, clue, direct, guess, make_game, run_all, run_turn,
)

W = ["cable", "camera", "candle", "candy", "canoe", "carrot", "castle", "cobra", "comet", "crane"]
PUBLIC_EVENT_KEYS = {"turn", "type", "clue", "blocklist", "opened_guesses", "prefix_after", "result"}


def test_worked_fixture_6_6():
    g = mechanics_game()
    asyncio.run(g.play(table_decider(MECHANICS_DECISIONS)))
    assert g.outcome_status == "solved" and g.winning_turn == 3
    assert g.terminal_reason == "public_target_utterance"
    e1 = g.public_history[0]
    assert e1["blocklist"] == ["camera", "carrot"] and e1["opened_guesses"] == []
    assert set(e1) == PUBLIC_EVENT_KEYS
    # turn-1 audit: castle preserved, 8 candidates remained
    assert g.audit[0]["secret_candidates_after"] == 8
    assert g.audit[1]["contact"] is True and g.audit[1]["prefix_after"] == "ca"


def test_correct_direct_wins_without_responders_wrong_enters_used():
    g = make_game(W, "candle")
    s = run_turn(g, {("guesser1", "act"): direct("candy")})
    assert s.phases() == [("guesser1", "act")]
    assert "candy" in g.used_words and g.outcome_status == "ongoing"
    s = run_turn(g, {("guesser1", "act"): direct("candle")})
    assert g.outcome_status == "solved" and g.hit_sources == ["direct"]
    assert s.phases() == [("guesser1", "act")]


def test_direct_on_used_word_is_invalid():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): direct("candy")})
    run_turn(g, {("guesser1", "act"): direct("candy")})
    assert g.public_history[-1] == {"turn": 2, "type": "invalid_action", "seat": "guesser1"}
    assert g.turns_used == 2


def test_private_registration_of_secret_does_not_win_and_cancel_regression():
    # Section 6.6 regression: w1=candle (secret), w2=carrot blocked, G1 cancels.
    g = make_game(W, "candle")
    s = run_turn(g, {
        ("guesser1", "act"): clue("candle", "Wax surrounding a wick"),
        ("guesser2", "respond"): guess("carrot"),
        ("defender", "block"): block("carrot"),
        ("guesser1", "choice"): CANCEL,
    })
    assert g.outcome_status == "ongoing"
    assert "candle" in g.secret_candidates() and "candle" not in g.used_words
    assert ("guesser1", "choice") in s.phases()


def test_revealing_instead_wins():
    g = make_game(W, "candle")
    run_turn(g, {
        ("guesser1", "act"): clue("candle", "Wax surrounding a wick"),
        ("guesser2", "respond"): guess("carrot"),
        ("defender", "block"): block("carrot"),
        ("guesser1", "choice"): REVEAL,
    })
    assert g.outcome_status == "solved" and g.hit_sources == ["guesser1_opened"]


@pytest.mark.parametrize("w1,w2,src", [("candle", "candy", "guesser1_opened"), ("candy", "candle", "guesser2_opened")])
def test_either_opened_guess_wins_on_mismatch(w1, w2, src):
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue(w1, "x"), ("guesser2", "respond"): guess(w2),
                 ("defender", "block"): block()})
    assert g.outcome_status == "solved" and g.hit_sources == [src]


def test_clue_mention_wins_and_responders_still_collected():
    g = make_game(W, "candle")
    s = run_turn(g, {("guesser1", "act"): clue("canoe", "Candle!"), ("guesser2", "respond"): guess("canoe"),
                     ("defender", "block"): block("canoe")})
    assert g.outcome_status == "solved" and g.hit_sources == ["clue"]
    assert ("guesser2", "respond") in s.phases() and ("defender", "block") in s.phases()


def test_early_stop_condition_skips_responders():
    g = make_game(W, "candle", initial_response_collection="early_stop_on_public_clue_hit")
    s = run_turn(g, {("guesser1", "act"): clue("canoe", "candle")})
    assert g.outcome_status == "solved" and s.phases() == [("guesser1", "act")]


def test_blocklist_containing_secret_loses_for_defender():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("canoe", "x"), ("guesser2", "respond"): guess("canoe"),
                 ("defender", "block"): block("candle", "canoe")})
    assert g.outcome_status == "solved" and g.hit_sources == ["blocklist"]


def test_whole_word_mentions():
    v = frozenset({"art", "artist", "arch"})
    assert mentioned_words("Art!", v) == {"art"}
    assert mentioned_words("artist", v) == {"artist"}
    assert mentioned_words("art-ist's arch", v) == {"art", "arch"}
    assert normalize_word(" Candle ") == "candle"
    assert normalize_word("can dle") is None and normalize_word("candle,") is None


def test_both_blocked_hides_identities_and_retires_blocklist():
    g = make_game(W, "candle")
    s = run_turn(g, {("guesser1", "act"): clue("carrot", "orange"), ("guesser2", "respond"): guess("castle"),
                     ("defender", "block"): block("carrot", "castle", "cobra")})
    assert ("guesser1", "choice") not in s.phases() and ("guesser2", "choice") not in s.phases()
    e = g.public_history[-1]
    assert e["opened_guesses"] == [] and set(e) == PUBLIC_EVENT_KEYS
    assert {"carrot", "castle", "cobra"} <= g.used_words
    dump = json.dumps(g.public_view())
    assert "blocked_guesser" not in dump and "registered_match" not in dump


def test_neither_blocked_mismatch_no_letter_and_match_gives_letter():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                 ("defender", "block"): block()})
    assert g.prefix == "c" and {"crane", "cobra"} <= g.used_words
    run_turn(g, {("guesser1", "act"): clue("canoe", "boat"), ("guesser2", "respond"): guess("canoe"),
                 ("defender", "block"): block()})
    assert g.prefix == "ca" and g.public_history[-1]["result"] == "prefix_extended"


def test_exactly_one_blocked_offers_only_unblocked_seat():
    g = make_game(W, "candle")
    s = run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                     ("defender", "block"): block("crane"), ("guesser2", "choice"): REVEAL})
    assert s.phases()[-1] == ("guesser2", "choice")
    assert g.public_history[-1]["opened_guesses"] == [{"seat": "guesser2", "word": "cobra"}]
    assert "cobra" in g.used_words  # wrong reveal retires it


def test_cancel_preserves_word_no_extra_turn_and_reuse_later():
    g = make_game(W, "candle", L=5)
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("canoe"),
                 ("defender", "block"): block("crane"), ("guesser2", "choice"): CANCEL})
    assert g.turns_used == 1 and "canoe" not in g.used_words and "canoe" in g.contact_candidates()
    # preserved word reused as a contact later
    run_turn(g, {("guesser1", "act"): clue("canoe", "paddle boat"), ("guesser2", "respond"): guess("canoe"),
                 ("defender", "block"): block()})
    assert g.prefix == "ca"


def test_cancel_cannot_preserve_word_named_in_clue():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("canoe", "canoe or crane"), ("guesser2", "respond"): guess("cobra"),
                 ("defender", "block"): block("cobra"), ("guesser1", "choice"): CANCEL})
    assert "canoe" in g.used_words and "crane" in g.used_words


def test_receiver_pass_branches_and_no_choice_call():
    g = make_game(W, "candle")
    s = run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): PASS,
                     ("defender", "block"): block()})
    assert g.public_history[-1]["opened_guesses"] == [{"seat": "guesser1", "word": "crane"}]
    s = run_turn(g, {("guesser1", "act"): clue("cobra", "snake"), ("guesser2", "respond"): PASS,
                     ("defender", "block"): block("cobra")})
    assert g.public_history[-1]["opened_guesses"] == []
    assert all(p != "choice" for _, p in s.phases())


def test_conditional_action_cannot_replace_word():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("candle"),
                 ("defender", "block"): block("crane"),
                 ("guesser2", "choice"): {"action": "reveal", "word": "canoe"}})
    a = g.audit[-1]
    assert a["choice"] == "cancel" and a["choice_valid"] is False
    assert g.outcome_status == "ongoing" and "canoe" not in g.used_words


def test_contact_requires_freshness_against_current_clue():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("canoe", "canoe"), ("guesser2", "respond"): guess("canoe"),
                 ("defender", "block"): block()})
    a = g.audit[-1]
    assert a["registered_match"] and not a["fresh_for_contact"] and not a["contact"]
    assert g.prefix == "c"


def test_blocked_contact_diagnostics():
    g = make_game(W, "candle")
    # covered match on fresh word -> prevented contact
    run_turn(g, {("guesser1", "act"): clue("canoe", "boat"), ("guesser2", "respond"): guess("canoe"),
                 ("defender", "block"): block("canoe")})
    assert g.audit[-1]["blocked_contact"] is True
    # covered intended word during mismatch -> not a prevented contact
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                 ("defender", "block"): block("crane", "cobra")})
    assert g.audit[-1]["blocked_contact"] is False
    # covered match on a word spelled in the clue -> not prevented
    run_turn(g, {("guesser1", "act"): clue("cable", "cable"), ("guesser2", "respond"): guess("cable"),
                 ("defender", "block"): block("cable")})
    assert g.audit[-1]["blocked_contact"] is False


def test_covered_match_with_public_hit_not_counted():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("canoe", "candle"), ("guesser2", "respond"): guess("canoe"),
                 ("defender", "block"): block("canoe")})
    assert g.outcome_status == "solved"
    assert not g.audit[-1].get("blocked_contact")


def test_empty_and_duplicate_blocklists():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                 ("defender", "block"): block("Comet", "comet ", "comet")})
    assert g.public_history[-1]["blocklist"] == ["comet"]


def test_block_all_but_secret_singleton_no_autowin_then_same_turn_reveal():
    g = make_game(W, "candle")
    others = [w for w in W if w != "candle"]
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                 ("defender", "block"): block(*others)})
    assert g.outcome_status == "ongoing" and g.secret_candidates() == ["candle"]
    g2 = make_game(W, "candle")
    run_turn(g2, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("candle"),
                  ("defender", "block"): block(*others), ("guesser2", "choice"): REVEAL})
    assert g2.outcome_status == "solved"


def test_final_letter_contact_wins_art_arch():
    words = ["arch", "art", "artist", "ash"]
    g = make_game(words, "art", k=2)
    run_turn(g, {("guesser1", "act"): clue("arch", "curve"), ("guesser2", "respond"): guess("arch"),
                 ("defender", "block"): block()})
    assert g.outcome_status == "solved" and g.terminal_reason == "prefix_completed" and g.winning_turn == 1


def test_displayed_prefix_art_retired_for_artist():
    words = ["arch", "art", "artist", "arts", "ash"]
    g = make_game(words, "artist", k=2)
    run_turn(g, {("guesser1", "act"): clue("arch", "curve"), ("guesser2", "respond"): guess("arch"),
                 ("defender", "block"): block()})
    assert g.prefix == "art" and g.outcome_status == "ongoing"
    assert "art" in g.used_words and "art" not in g.secret_candidates() and "art" not in g.contact_candidates()
    assert g.prefix_events[-1] == {"turn": 1, "prefix": "art"}


def test_initial_dictionary_prefix_used_and_setup_rejections():
    g = make_game(["a", "able", "acid"], "able", k=1)
    assert "a" in g.used_words and "a" not in g.secret_candidates()
    with pytest.raises(GameSetupError):
        make_game(["ab", "able"], "ab", k=2)


def test_overlong_clue_rejected_before_target_detection():
    g = make_game(W, "candle", clue_max_characters=10)
    run_turn(g, {("guesser1", "act"): clue("canoe", "candle candy canoe")})
    assert g.outcome_status == "ongoing" and g.turns_used == 1
    assert g.public_history[-1] == {"turn": 1, "type": "invalid_action", "seat": "guesser1"}
    assert "candle" not in g.used_words


def test_many_word_clue_within_budget_is_legal():
    g = make_game(W, "candle")
    text = "cable camera candy canoe carrot castle cobra comet"
    run_turn(g, {("guesser1", "act"): clue("crane", text), ("guesser2", "respond"): guess("candle"),
                 ("defender", "block"): block()})
    assert g.outcome_status == "solved" and g.hit_sources == ["guesser2_opened"]


def test_malformed_and_refusal_text_not_public():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): "I refuse. The answer might be candle."})
    assert g.outcome_status == "ongoing"
    assert "candle" not in json.dumps(g.public_history)
    assert g.private_history["guesser1"][-1]["validity"] == "invalid"
    assert "candle" not in json.dumps(g.private_history["guesser1"])


def test_invalid_responder_and_choice_canonicalization_hidden_publicly():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): "nonsense",
                 ("defender", "block"): {"action": "block", "words": ["notaword"]}})
    a = g.audit[-1]
    assert a["guesser2"]["valid"] is False and a["guesser2"]["canonical"] == PASS
    assert a["defender"]["valid"] is False and a["blocklist"] == []
    assert g.public_history[-1]["opened_guesses"] == [{"seat": "guesser1", "word": "crane"}]
    assert "valid" not in json.dumps(g.public_history)


def test_roles_fixed_and_turn_cap_resolution_with_final_reveal():
    g = make_game(W, "candle", L=2)
    run_turn(g, {("guesser1", "act"): direct("cable")})
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("candle"),
                 ("defender", "block"): block("crane"), ("guesser2", "choice"): REVEAL})
    assert g.outcome_status == "solved" and g.winning_turn == 2
    g = make_game(W, "candle", L=1)
    run_all(g, {(1, "guesser1", "act"): direct("cable")})
    assert g.outcome_status == "capped" and g.turns_used == 1


def test_final_letter_contact_at_cap():
    words = ["arch", "art", "ash"]
    g = make_game(words, "art", k=2, L=1)
    run_all(g, {(1, "guesser1", "act"): clue("arch", "curve"), (1, "guesser2", "respond"): guess("arch"),
                (1, "defender", "block"): block()})
    assert g.outcome_status == "solved" and g.winning_turn == 1 and g.terminal_reason == "prefix_completed"


def test_sealed_responders_and_initial_noninterference():
    obs = {}
    for w1 in ("crane", "cobra"):
        g = make_game(W, "candle")
        s = run_turn(g, {("guesser1", "act"): clue(w1, "something"), ("guesser2", "respond"): PASS,
                         ("defender", "block"): block()})
        obs[w1] = (s.obs(1, "guesser2", "respond"), s.obs(1, "defender", "block"))
    assert obs["crane"] == obs["cobra"]
    g2_obs, d_obs = obs["crane"]
    assert "w1" not in json.dumps(g2_obs) and "own_committed_word" not in g2_obs
    assert "secret" not in g2_obs and d_obs["secret"] == "candle"


def test_attacker_observations_independent_of_secret():
    a = []
    for secret in ("candle", "canoe"):
        g = make_game(W, secret)
        s = run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                         ("defender", "block"): block("comet")})
        s2 = run_turn(g, {("guesser1", "act"): direct("cable")})
        a.append((s.obs(1, "guesser1", "act"), s.obs(1, "guesser2", "respond"), s2.obs(2, "guesser1", "act")))
    assert a[0] == a[1]


def test_both_blocked_vs_cancel_indistinguishable_to_defender():
    views = []
    for w2, extra in (("cobra", {}), ("canoe", {("guesser2", "choice"): CANCEL})):
        g = make_game(W, "candle")
        run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess(w2),
                     ("defender", "block"): block("crane", "cobra"), **extra})
        s = run_turn(g, {("guesser1", "act"): clue("cable", "rope"), ("guesser2", "respond"): PASS,
                         ("defender", "block"): block()})
        views.append((s.obs(2, "defender", "block"), s.obs(2, "guesser1", "act"), g.public_view()))
    # identical public summaries and defender observations; G1's own history identical too
    assert views[0][0] == views[1][0]
    assert views[0][2] == views[1][2]
    assert views[0][1] == views[1][1]


def test_choice_prompt_contents():
    g = make_game(W, "candle")
    s = run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                     ("defender", "block"): block("crane"), ("guesser2", "choice"): CANCEL})
    o = s.obs(1, "guesser2", "choice")
    assert o["own_committed_word"] == "cobra" and o["partner_word_blocked"] is True
    assert "crane" not in json.dumps({k: v for k, v in o.items() if k not in ("published_blocklist", "contact_candidates", "secret_candidates")})


def test_unavailable_responder_with_public_clue_hit_is_known_win():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("canoe", "candle"), ("guesser2", "respond"): UNAVAILABLE,
                 ("defender", "block"): block()})
    assert g.outcome_status == "solved" and g.collection_status == "incomplete"


def test_unavailable_defender_private_secret_not_a_win():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("candle", "wax"), ("guesser2", "respond"): guess("candle"),
                 ("defender", "block"): UNAVAILABLE})
    assert g.outcome_status == "infrastructure_incomplete" and g.pending["phase"] == "sealed_responses"


def test_unavailable_choice_is_pending_not_cancel():
    g = make_game(W, "candle")
    run_turn(g, {("guesser1", "act"): clue("crane", "bird"), ("guesser2", "respond"): guess("cobra"),
                 ("defender", "block"): block("crane"), ("guesser2", "choice"): UNAVAILABLE})
    assert g.outcome_status == "infrastructure_incomplete" and g.pending["phase"] == "choice"


def test_joint_live_forecast_never_counts_as_utterance():
    g = make_game(W, "candle", joint_live=True)
    fc = {"entries": [{"word": "candle", "probability": 1.0}], "other_mass": 0.0}
    run_turn(g, {
        ("guesser1", "act"): clue("crane", "bird"),
        ("guesser2", "respond"): {"gameplay": guess("cobra"),
                                  "diagnostics": {"intended_word_forecast": fc, "commitment_match_forecast": None}},
        ("defender", "block"): {"gameplay": block(),
                                "diagnostics": {"intended_word_forecast": fc, "commitment_match_forecast": None}},
    })
    assert g.outcome_status == "ongoing" and "candle" not in g.used_words
    assert len(g.diagnostics) == 2
    assert "candle" not in json.dumps(g.public_history)


def test_secret_preserved_invariant():
    g = make_game(W, "candle", L=10)
    run_turn(g, {("guesser1", "act"): clue("crane", "camera cable"), ("guesser2", "respond"): guess("cobra"),
                 ("defender", "block"): block("comet")})
    assert "candle" in g.secret_candidates()
