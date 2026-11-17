# Decision log

Protocol version: **contact-v0.5**. It adds the `dictionary_access` condition (below). With the default
`full_candidate_lists` it behaves exactly like v0.4, and v0.4 configurations still load. This log records the implementation choices made where the spec left
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

## Protocol v0.5: dictionary access conditions (2026-11-17)

`protocol.dictionary_access` selects how players learn the dictionary. It is a non-poolable leaderboard condition.

| Value | Player observation | Notes |
|---|---|---|
| `full_candidate_lists` | Complete pre-turn secret and contact lists (spec §4.5) | v0.4 behaviour; only practical for small lexicons |
| `closed_book` | Only the dictionary's identity: name, size, SHA-256, source, word rules. No lists or counts | Players rely on their own knowledge; the engine still validates against the frozen list |
| `lookup_tools` | Identity, plus the same deterministic functions for every seat: `is_legal_word(word)`, `list_words(prefix, offset=0, limit≤100)`, `count_words(prefix)` | At most `max_tool_calls_per_decision` calls (default 20), then the model must answer |

The design choices behind these conditions:
- **Static lookups.** Lookups query the frozen lexicon only. They ignore game state, so used words are still returned.
  The `used_words` list is in every observation. Lookups are private and are never gameplay utterances.
- **Tool trace.** The trace is recorded in the request log. Replay does not need it, because the final decision is
  what is recorded.
- **Budgets.** Each model call in a tool loop is a separate transport attempt for retries and budgets.
- **Scripted baselines.** In both new conditions, scripted reference algorithms enumerate the dictionary through the
  same lookup service. They are public algorithms over the public dictionary, not models, and are labeled that way.
- **Large dictionaries.** The full-blocklist capacity preflight covers the largest initial prefix group. For
  `enable` (s-words: 18,982 entries, 244,147 JSON characters) Haiku's `count_tokens` measured 109,130 tokens, so
  a 128K output allowance can represent every legal blocklist. The Anthropic adapter streams whenever
  `max_tokens > 16000`, because the SDK requires streaming for long calls.
- **Shadow audit.** The forecast support is still read from observation lists, so the shadow audit currently
  requires `full_candidate_lists`. This is a known gap.

## Empty initial prefix and range-encoded blocklists (2026-11-17)

- **Empty prefix.** `initial_prefix_length: 0` is supported. The secret can be any dictionary word, and the first
  contact reveals its first letter. This departs from traditional Contact on purpose, to make the benchmark harder.
  With ENABLE the initial candidate set is all 172,608 words, and the reference cost `B` is about 6,900 turns.
- **Range-encoded blocklists.** With an empty prefix, a full explicit blocklist would be about 1M tokens, so the spec
  §4.4 capacity requirement fails for every model. `blocklist_encoding: words_and_ranges` adds the dictionary-ID
  encoding that the spec allows. A blocklist is `{"action": "block", "words": [...], "ranges": [{"from": w1, "to": w2}]}`,
  and each range blocks every `V_contact` word alphabetically between two dictionary words, inclusive. Its decoded
  effect is identical to listing those words: they become public and used, and a range that contains the secret
  loses for the defender.
- **Public record of ranges.** Public history records the explicit words, the ranges and `blocked_word_count`.
  Observations list `used_ranges` (merged), and `used_words` omits the words those ranges cover, so a huge block
  cannot overflow later prompts.
- **Pilot configuration.** The self-play pilot used `turn_limit: 20` and 256 reference rollouts per histogram. One
  rollout over the full dictionary takes about 0.11 s.

## Gemini tool loop and per-provider caps (2026-11-17)

- **Gemini tool loop.** In live tests on 2026-11-17, `gemini-3.8-flash` re-called lookup tools until the call limit
  whenever `response_format` was sent together with function tools. This happened on both Interactions and
  generateContent. Without the format it calls tools sensibly, but it wraps its answer in a Markdown code fence.
  The Gemini adapters therefore set `structured_output_with_tools = False`. Lookup turns omit the output schema.
  When the model stops calling tools, one final turn runs with tools disabled and the schema enforced, preceded by
  a fixed user nudge (`FINAL_ANSWER_NUDGE`). So the final answer is still strictly validated, and the extra call
  is counted against the budget like any other.
- **Per-provider caps.** `--max-usd-provider PROVIDER=USD` (repeatable) caps spend per API key, on both `run` and
  `resume`.

## No-progress draws and rematches (2026-11-17, researcher decision)

- **Draw rule.** A fixture where both legs hit the turn cap and neither attacker earned a letter beyond the
  starting prefix is scored ½–½ for the rating (`tournament.no_progress_draws`, default true). Between strong
  defenders such fixtures are common. Their fallback-cost difference reflects only incidental eliminations,
  not skill.
- **Rematch.** Each such draw schedules one rematch fixture, both legs, on the same secret with
  `rematch_extra_letters` (default 1) more letters revealed. The draw stands and the rematch is an additional
  result. Rematches never trigger rematches.
- **Schedule.** Rematch fixtures are appended to `schedule.json` once both original legs are complete. This is
  logged as a `rematches_scheduled` event and is idempotent on resume. Replay regenerates them from the logs.
- **Re-analysis.** The rule is applied when analysing, so older runs re-analysed with this code also score
  no-progress fixtures as draws.

## Live forecast forks (forecast mode `fork`, 2026-11-17)

`forecasts.mode: fork` adds a fourth collection mode. After each LLM gameplay decision, the runner branches
that seat's transcript: the model's own final answer stays in place, and a new private user turn asks for a
probability report under its own JSON schema. Nothing from the branch reaches the game. Gameplay prompts,
observations and outcomes are byte-identical to `off`, which a regression test checks.

| Seat (after its decision) | Question | Answer key |
|---|---|---|
| Guesser 2 (respond) | Distribution over Guesser 1's intended word W | W |
| Defender (block) | Distribution over W | W |
| Guesser 1 (valid clue only) | Distribution over what Guesser 2 registers, with `PASS` allowed | Guesser 2's canonical word, or `PASS` (an invalid reply counts as `PASS`) |
| Guesser 1 (valid clue only) | `block_probability`: the chance the blocklist covers W | Whether W is in the decoded blocklist |

How forks work:
- **Elicited, not sampled.** Forecasts are elicited reports, not token log-probabilities. The Anthropic API
  exposes no logprobs, and the other providers do not expose them uniformly, especially for reasoning models.
  Sampling each fork N times to estimate a distribution empirically would be possible but costs N times as much.
  It is not implemented.
- **Branch construction.** Each provider's native transcript is carried along: Anthropic message blocks with
  thinking signatures, OpenAI input items with encrypted reasoning, Gemini steps or contents with thought
  signatures. The branch is that transcript plus one new user turn. In the lookup-tool condition the branch
  keeps tool access.
- **Support.** The support is the pre-turn contact set, stored compactly as prefix plus used words and ranges, and
  scored without being materialized. A word outside the support, duplicate entries, more than
  `sparse_max_entries` entries, or a mass error beyond `mass_tolerance` (1e-6) makes the report invalid. It then
  scores -1 in the overall Brier mean, and valid-only means are reported separately.
- **Failures.** An infrastructure failure in a fork is recorded as `unavailable` and never scored. Forks are not
  retried on resume, because the live transcript cannot be rebuilt from the decision log.
- **Storage and analysis.** Records go to `forecasts.jsonl`. Game records hold the labeled, scored forks. `analyze`
  reports per-model, per-target Brier, log score, q(true), top-1 accuracy, reliability tables and ECE.
- **Pilot result.** In the 2026-11-17 Haiku pilot, 26 of 98 parseable reports had probabilities summing to between
  0.83 and 1.31, so they were invalid at the spec tolerance. Whether to declare a looser tolerance (for example
  0.02, followed by renormalization) is a research decision.

## Review fixes (Codex review of PR #1)

1. **Torn JSONL tail.** `RunStore` truncates a partial final line before its first append and saves the torn bytes
   to `<log>.torn`.
2. **Request and spend caps.** These are now enforced per transport attempt through `AttemptGate` / `BudgetGate`.
   That covers retries and tool-loop turns.
3. **Shadow audit budget.** The audit uses the same per-attempt gate (`--max-requests`, `--max-usd`).
4. **Anthropic input tokens.** The adapter now includes cache reads and writes in `input_tokens`, which is the
   documented normalized convention. `estimate_cost` prices uncached, cache-read and cache-write tokens separately.
5. **Task manifests.** A supplied manifest must match the contact-lexicon hash, prefix length, cap, clue budget,
   split and sampling as well as the secret-lexicon hash.

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
