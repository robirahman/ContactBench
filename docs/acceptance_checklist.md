# Implementation acceptance checklist (spec Section 18)

Run `.venv/bin/python -m pytest` to execute every test listed here. All of them run offline, with no keys.

## 18.1 Engine, admission and information

| Requirement | Test(s) |
|---|---|
| Correct direct wins without responders; wrong one enters used_words | `test_engine::test_correct_direct_wins_without_responders_wrong_enters_used` |
| Private registration of the secret does not win | `test_private_registration_of_secret_does_not_win_and_cancel_regression` |
| Either opened guess equal to the secret wins | `test_either_opened_guess_wins_on_mismatch` |
| Whole-word clue mention wins | `test_clue_mention_wins_and_responders_still_collected`, `test_whole_word_mentions` |
| Blocklist containing the secret wins for offense | `test_blocklist_containing_secret_loses_for_defender` |
| Private histories, forecasts and dictionaries are not hits | `test_joint_live_forecast_never_counts_as_utterance`, `test_malformed_and_refusal_text_not_public` |
| Both blocked: open neither, retire blocklist, hide labels | `test_both_blocked_hides_identities_and_retires_blocklist` |
| Neither blocked: open both; mismatch no letter; fresh match letter | `test_neither_blocked_mismatch_no_letter_and_match_gives_letter` |
| Exactly one blocked: only the unblocked seat is offered a choice | `test_exactly_one_blocked_offers_only_unblocked_seat` |
| Reveal opens only the existing word; wrong retires; correct wins | `test_exactly_one_blocked_offers_only_unblocked_seat`, `test_revealing_instead_wins` |
| Cancel opens neither; no extra turn; word stays eligible | `test_cancel_preserves_word_no_extra_turn_and_reuse_later` |
| Canceled secret commitment remains possible (§6.6 regression) | `test_private_registration_of_secret_does_not_win_and_cancel_regression` |
| Cancel cannot preserve a clue/block/prefix-named word | `test_cancel_cannot_preserve_word_named_in_clue`, `test_displayed_prefix_art_retired_for_artist` |
| Hidden blocked word retired through blocklist | `test_both_blocked_hides_identities_and_retires_blocklist` |
| Preserved canceled word reused later as contact | `test_cancel_preserves_word_no_extra_turn_and_reuse_later` |
| Receiver pass branches; no cancellation call | `test_receiver_pass_branches_and_no_choice_call` |
| Conditional action cannot replace the word | `test_conditional_action_cannot_replace_word` |
| Emitted words excluded; unopened commitments not pruned | `test_cancel_preserves_word...`, `test_properties::test_invariants_and_replay` |
| Every fresh wrong block eliminated | `test_both_blocked_hides_identities_and_retires_blocklist` |
| Registration pre-turn; contact needs current-clue freshness | `test_contact_requires_freshness_against_current_clue` |
| Covered mismatch / public-hit / clue-spelled match not "prevented" | `test_blocked_contact_diagnostics`, `test_covered_match_with_public_hit_not_counted` |
| Empty and duplicate blocklists | `test_empty_and_duplicate_blocklists` |
| Block all but secret: singleton, no auto-win; same-turn reveal wins | `test_block_all_but_secret_singleton_no_autowin_then_same_turn_reveal` |
| art/arch final-letter win; artist retires art | `test_final_letter_contact_wins_art_arch`, `test_displayed_prefix_art_retired_for_artist` |
| Dictionary-valued initial prefix used; prefix = secret rejected | `test_initial_dictionary_prefix_used_and_setup_rejections` |
| Overlong dumps rejected before target detection; many-word clues legal | `test_overlong_clue_rejected_before_target_detection`, `test_many_word_clue_within_budget_is_legal` |
| Malformed/refusal text not a covert clue | `test_malformed_and_refusal_text_not_public`, `test_runner::test_fake_refusal_counts_as_invalid_action` |
| Invalid G1 consumes turn; responders → pass/empty; choice → cancel | `test_direct_on_used_word_is_invalid`, `test_invalid_responder_and_choice_canonicalization_hidden_publicly` |
| Roles fixed; turn L fully resolved; no turn L+1 | `test_roles_fixed_and_turn_cap_resolution_with_final_reveal`, `test_final_letter_contact_at_cap` |
| Sealed responders; scheduling independent of hidden equality | `test_sealed_responders_and_initial_noninterference`, `test_clue_mention_wins_and_responders_still_collected` |
| Noninterference (vary hidden word; vary secret; both-blocked vs cancel) | `test_sealed_responders_and_initial_noninterference`, `test_attacker_observations_independent_of_secret`, `test_both_blocked_vs_cancel_indistinguishable_to_defender`, `test_properties::test_attacker_view_independent_of_secret_until_public_difference` |

## 18.2 Completion scoring and statistics

| Requirement | Test(s) |
|---|---|
| First/last within ceil(n/2) under adversarial blocks; F_2 formulas | `test_reference::test_first_last_engine_mean_matches_F2`, `test_first_last_worst_case_under_adversarial_blocks`, `test_analytic_fixtures` |
| F_2(5)=9/5, F_2(100)=51/2, F_6(100)=221/25, F_18(100)=33/10 | `test_analytic_fixtures`, `test_equal_length_reference_uses_character_capacity` |
| Forward/reverse n=5, b=2 regression | `test_forward_reverse_fixed_b_regression` |
| F_1(n)=(n+1)/2 | `test_analytic_fixtures`, `test_single_word_direct_F1` |
| Exhaustive tiny states; batch law; simulator vs exact | `test_exact_oracle_matches_permutation_brute_force`, `test_batch_distribution_matches_permutations`, `test_monte_carlo_estimator_against_exact_and_properties` |
| Cap consistency of fresh-shuffle hybrid | `test_cap_consistency_of_fresh_shuffle_hybrid` |
| §7.9 fixtures and ratio-of-totals rule | `test_mixed_histogram_exact_fixture`, `test_ratio_of_totals_fixture`, `test_wasted_turns_cost_and_capped_singleton`, `test_final_letter_contact_at_cap_cost_L`, `test_dictionary_bound_example` |
| Packing rules (whole words, separators, maximal prefix, two longest, singleton direct) | `test_packing_rules`, `test_clue_only_vs_combined_cat_dog_pig` |
| Combined worst-case bound | `test_combined_worst_case_bound_small_states` |
| Length-class averaging, spelling invariance, rational storage, MCSE, cache reuse | `test_monte_carlo_estimator_against_exact_and_properties`, `test_mc_cache_resume_and_spelling_invariance` |
| Equal-length/all-fit exact; zero class variance | `test_all_fit_reference_is_exactly_one`, `test_equal_length_rollouts_have_zero_class_variance` |
| Seeds independent of target/model/score | `test_seeds_independent_of_target` |
| Secret preserved in surviving sets | `test_engine::test_secret_preserved_invariant`, property tests |
| Ideal monotonicity under nontarget deletion | `test_ideal_monotonicity_under_nontarget_deletion` |
| Match points complement; all-tied equal ratings; 24-target counterexample | `test_runner::test_rating_properties`, `test_equal_efficiency_different_elo_counterexample` |
| Cluster bootstrap; disconnected schedules; recompute from logs | `test_runner::test_offline_round_robin_replay_and_analysis`, `test_rating_properties` |

## 18.3 Forecast diagnostics

All in `tests/test_forecasts.py`, plus `test_engine::test_joint_live_forecast_never_counts_as_utterance` and
`test_runner::test_frozen_item_bank_and_shadow_audit`.

## 18.4 Adapters and runner

| Requirement | Test(s) |
|---|---|
| Schema support, refusal, truncation, nullable usage, unsupported settings | `tests/test_providers.py` |
| Bounded retries; no nested SDK retries; no semantic resampling | `tests/test_providers.py`, `test_runner::test_fatal_error_halts_and_retries_bounded` |
| Resume partial phases incl. pending choice without resampling | `test_runner::test_resume_pending_choice_without_resampling` |
| Phase-distinguished decision IDs | `test_runner::test_decision_ids_distinguish_phases` |
| Known win with missing irrelevant response; unopened private target not a win | `test_engine::test_unavailable_responder_with_public_clue_hit_is_known_win`, `test_unavailable_defender_private_secret_not_a_win`, `test_unavailable_choice_is_pending_not_cancel` |
| Live opt-in and budgets | `test_runner::test_offline_refuses_paid_models_and_live_requires_budget`, `test_budget_stop_then_resume` |
| Full blocklist representable; context fits | `test_runner::test_blocklist_output_capacity_preflight`, `test_context_overflow_halts` |
| Default tests make no network calls | the whole suite (no keys; fake/mocked clients only) |
| Export has no credentials | `test_runner::test_export_leak_detection`, `test_offline_round_robin_replay_and_analysis`, `tests/test_site.py` |
| No double-counting of reasoning tokens | `tests/test_providers.py` |
| Escape adversarial clue text in replays | `tests/test_site.py` |

## Milestone gates

- Offline end-to-end demo: `contact-bench demo --offline` ✔
- Replay equivalence from logs: `contact-bench replay RUN_ID` → `"equivalent": true` ✔
- Analysis, export, site build: ✔ (site rendered headlessly with jsdom; not checked in a real browser)
- Live commands: ready for credentials. **Not exercised against real providers.**
