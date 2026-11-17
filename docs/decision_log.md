# Decision log

Protocol version: **contact-v0.4** (unchanged). This log records the implementation choices made where the spec left
room. It also lists the Section 20 research decisions that the researcher must freeze before a main run. None of the
entries below changes a game rule. If any of them is revised, update this log and the protocol version.

## Implementation choices (2026-11-17)

| # | Topic | Choice | Rationale / spec reference |
|---|---|---|---|
| 1 | Action JSON strictness | An action must be one JSON object with **exactly** the schema fields. There is no code-fence stripping or other text repair. | §6.1 "strict JSON objects with no extra gameplay fields"; §13.1 adapters must not repair answers |
| 2 | Invalid blocklist entry | Any entry that is not a single `V_contact` word invalidates the whole blocklist, which becomes empty. | §6.5 "invalid defender gameplay becomes an empty public blocklist" |
| 3 | Blocklist display order | Admitted blocklists are deduplicated and published in sorted order. | Stable public display; order carries no gameplay effect |
| 4 | Public event fields | `clue_round` events carry `clue`, `blocklist`, `opened_guesses`, `prefix_after`, `result ∈ {no_prefix, prefix_extended, won}`. Terminal events add `terminal_reason` and `hit_sources`. | §6.3 step 4; contact success is already public through the prefix change |
| 5 | Initial prefix display | Processed as a canonical appearance event at turn 0. | §4.3 |
| 6 | Scripted shared randomness | Fixed and fresh shuffles use `sha256(policy_seed, [turn], word)` sort keys. The policy seed comes from the game ID, which is target-independent, and every scripted seat has it. | §11 "expose its target-independent policy seed to all scripted seats" |
| 7 | `public_index_ambiguity` baseline | The clue lists `#i` indices (1-based, into the public contact list) of the first *k=2* secret candidates. Each guesser picks one index using its own private per-turn coin. The paired defender `index_decoder` blocks every indexed non-secret word. | §11 "test cheap communication under multiple blocks" |
| 8 | Combined packing tie-break | Guess slots go to the longest words, with ties broken alphabetically. | §7.3 any deterministic tie-break gives the same tested set |
| 9 | Reference RNG | Python `random.Random` (MT19937), seeded with the first 8 bytes of a SHA-256 of `(rng_version, packing_version, root_seed, C, histogram, rollout index)`. Draws use `randrange` for exact uniformity. | §7.6 publish the RNG specification |
| 10 | Exact-oracle limit | Default `exact_small_state_limit = 12` candidates. | §7.5 explicit computational limit; freeze before main run |
| 11 | MC cache | Per-histogram JSON files store the per-rollout integer rank sums. A K-rollout value always uses rollouts `0..K−1`, so refinement extends the sample and never replaces it. | §7.6, §14.3 |
| 12 | Request logging | The request log stores each observation's SHA-256 rather than the full prompt. Replay regenerates the exact observation, verifies the hash, and halts on divergence. | §16 "permitted observation or exact serialized prompt" |
| 13 | Request accounting | Every transport attempt counts against the request budget. When usage is unknown, the full worst-case reservation is charged to the dollar budget. | §14.1 conservative reservations |
| 14 | Token estimates | Context preflight uses about 3 characters per token. Blocklist output preflight uses about 2 characters per token. Both are conservative heuristics, not provider tokenizers. | §4.4, §4.5 |
| 15 | Prompts | Each request is stateless. The full permitted seat history is rebuilt from the observation, so no provider-side conversation state is used. OpenAI uses `store=false`. | §13.2 |
| 16 | Resume semantics | `resume` re-plays each unfinished game from the decision log and requests only genuinely missing phases. Games whose outcome is solved but whose collection is incomplete are retried to recover the missing responses, and their known cost is kept. | §6.5, §14.2 |
| 17 | `smoke` command | Plays one game per selected-provider model (as attacker and as defender) against a scripted first/last opponent, on the ten-word mechanics lexicon with `L=2`, under the given request budget. | §15, Phase 5 |
| 18 | Offense conditions | LLM models accept `offense_mode ∈ {full, direct_only, no_contact_batching}`. `direct_only` is enforced by admission: clue actions are invalid. `no_contact_batching` is a prompt condition only. | §11 |
| 19 | Fixture lexicons | `mechanics_fixture` (the 10 words from §6.6) and `dev_fixture` (747 hand-written common words), both dedicated CC0 by the authors. | §4.1 |
| 20 | Code license | **Not chosen.** The researcher must select one; `pyproject.toml` leaves it unset. | §16 |

## Known gaps

- Live provider calls have not been exercised. The adapters are verified only against mocked SDK clients and
  documentation (see `docs/providers.md`). Anthropic thinking-token accounting and the Gemini Interactions request
  shape must be confirmed in the first smoke run.
- `joint_live` diagnostics are collected and stored privately in the game record, but scoring them is not yet wired
  into `analyze`. The shadow-audit path (`contact-bench audit`) is scored. The shadow audit requests intended-word
  forecasts only. The defender commitment-match forecast is implemented in the scorer (`match_label`, the `NO_MATCH`
  support) but not yet requested.
- There is no semantic-clue condition or human audit tooling. Per §4.5 that is a separate track.
- The controlled clue-generation task from §8.6 (fixed intended word, fixed receiver/defender panel) is not
  implemented as a command.
- The site has been checked with a headless DOM (jsdom) and by unit tests, not in a real browser.

## Section 20 decisions to freeze before a main run

1. Production lexicon, its rights, normalization and target distribution (uniform by default).
2. Clue budget `C` (default 100; consider comparing with 240 on development data).
3. Reference details: `exact_small_state_limit`, rollouts (2,048 dev / 4,096 proposed), `root_seed`, refinement rule.
4. Main cap `L` (development sweeps 5/10/20/40), inference profiles, full-blocklist output feasibility
   (`contact-bench validate --live`).
5. Model configurations, opponent population, tasks per pair, repetitions.
6. Forecast mode (`off` + shadow audit recommended first).
7. Forecast format/scoring/item-bank sampling rule (`--rate`, `--seed`, `--max-items`).
8. Mechanical clues only, or an additional audited semantic condition.
9. Singleton, receiver-pass, reveal/cancel and feedback policies (the defaults are implemented). Also decide
   complete-collection vs early-stop timing.
10. Headline presentation: Elo vs efficiency.
11. Data, transcript and model-output release permissions (`export --include-audit` controls hidden-commitment
    release).
12. Paper claims and prior-art comparison.
