# ContactBench in Inspect

ContactBench's arena rates models against each other. For a per-model score that any lab can reproduce with
one standalone run (for example for an index such as the Epoch Capabilities Index), the benchmark is also an
[Inspect](https://inspect.aisi.org.uk) task: the evaluated model plays fixtures against a **fixed reference
panel**, and its Elo is fitted with the panel's ratings held fixed. That is the same anchored fit used for
human challenges, so the result lands on the main C=50 leaderboard's scale without moving any model rating.

## Running it

```bash
pip install -e '.[inspect]'          # from a checkout of this repository (configs and lexicons are read from it)
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GOOGLE_API_KEY=...   # the default panel uses all three providers
inspect eval contact_bench/contact_bench --model anthropic/claude-sonnet-5-5 --reasoning-effort low \
    -T secrets_per_opponent=3
```

Task options (`-T`):

| Option | Default | Meaning |
|---|---|---|
| `panel` | `c50_api_v2` | Panel name in `contact_bench/inspect_task/panels/`, or a path to a panel JSON |
| `secrets_per_opponent` | 3 | Fixtures (fresh secrets) per panel opponent (24 fixtures with the default panel, plus rematches) |
| `seed` | 20261120 | Secret-generation seed; secrets are uniform draws from the ENABLE support |
| `opponents` | all | Comma-separated subset of the panel (leave out the evaluated model's own entry, e.g. when evaluating Sol) |
| `rematches` | true | Replay no-progress draws with one more letter revealed, as in the arena |

The evaluated model's own settings come from Inspect (`--model`, `--reasoning-effort`, `--max-tokens`, ...).
Record them: the same model at a different effort is a different leaderboard entry.

## What a sample is

One sample is one **fixture** on one secret against one panel opponent, exactly as in the arena:

- **Attack leg:** the evaluated model is Guesser 1 and Guesser 2 (separate instances); the opponent defends.
- **Defense leg:** two instances of the opponent attack; the evaluated model defends.

The fixture point goes to the side with the lower attacking cost; two capped legs with no letter earned are a
draw (½). With `rematches`, a draw is replayed on the same secret with one more letter revealed, recursively,
and every fixture counts. The engine, prompts, admission rules, lookup tools and cost scoring are the arena's
own code; only the model transport is Inspect (`contact_bench/inspect_task/adapter.py`), so every model call is
in the Inspect log. Lookup tools and structured output are combined as in the arena adapters (JSON schema on
every turn for OpenAI and Anthropic; a final schema-constrained turn for other providers). A game that
cannot be completed for infrastructure reasons fails the sample (use `--retry-on-error`); it is never scored.

## Scores

| Metric | Meaning |
|---|---|
| `anchored_elo` | Headline. Elo of the evaluated model with the panel's frozen ratings held fixed (same likelihood and penalty as the arena fit). |
| `anchored_elo_se` | Laplace standard error of that Elo. |
| `match_point_share` | Bounded companion in [0, 1]: mean fixture points against the panel. Comparable only for the same panel. |

Per-sample scores carry every fixture's points and both legs' costs in their metadata.

## The reference panel

`c50_api_v2` (frozen 2026-11-20 from the published combined C=50 board, run `combined-overall-c50-all`, 318
fixtures): eight opponents across three providers, so no single matchup dominates an evaluated model's score.

| Opponent | Model and setting | Frozen Elo | 95% CI | Board fixtures |
|---|---|---|---|---|
| `opus` | Claude Opus 5.5 (Low) | 1070.2 | 853–1257 | 35 |
| `sol` | GPT-6.2 Sol (Low) | 1456.2 | 1335–1562 | 52 |
| `luna` | GPT-6 Luna (Medium) | 1547.1 | 1432–1671 | 60 |
| `flash` | Gemini 3.8 Flash (Medium) | 1595.7 | 1449–1740 | 43 |
| `hydrogen` | Gemini 4 Hydrogen (Low) | 1690.7 | 1627–1819 | 108 |
| `argon` | Gemini 4 Argon (Low) | 1701.5 | 1605–1834 | 73 |
| `terra` | GPT-6.1 Terra (Low) | 1763.9 | 1695–1894 | 87 |
| `carbon` | Gemini 4 Carbon (Low) | 1972.7 | 1793–2248 | 26 |

Luna and Flash ran on the board without an effort parameter, at their provider default (Medium); the panel sets
Medium explicitly so a later change to a provider default cannot change them. `c50_api_v1` (four opponents) is
kept for reference and superseded.

**Why eight opponents.** A parity check rated GPT-6.2 Sol (Low) through this task against a four-model panel at
1623 ± 107, against 1362 on the board at the time. Arena games against the same opponents gave 1591 ± 86, so the
Inspect transport reproduces the arena; the gap was matchup-dependence (Sol does better against Luna and Hydrogen
than its board opponents predicted). Adding those games moved Sol to 1456 on the board. A broader panel reduces
how much one favourable or unfavourable matchup moves the score, but a panel score remains an approximation of
the full arena rating; expect differences of roughly 100–250 Elo for models with unusual matchups.

Caveats:

- **Ceiling.** A model that beats every opponent gets only a lower bound (the fit's prior keeps it finite).
  GPT-6.2 Astra at max effort already beats all of these in the arena; a stronger panel is needed to separate
  frontier models.
- **API drift.** Panel models are hosted APIs; if one is deprecated or changes, the panel must be recalibrated.
  An open-weight panel (pinned weights, any host) would remove that dependency but needs calibration games
  against the arena pool first.
- **Overrides.** `--model-role terra=...` re-binds an opponent. Its frozen Elo then no longer applies, so those
  samples are left out of `anchored_elo` (they still count in `match_point_share`); the log records the
  models actually used.
