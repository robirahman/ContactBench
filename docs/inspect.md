# ContactBench in Inspect

ContactBench's arena rates models against each other. For a per-model score that any lab can reproduce with
one standalone run (for example for an index such as the Epoch Capabilities Index), the benchmark is also an
[Inspect](https://inspect.aisi.org.uk) task: the evaluated model plays fixtures against a **fixed reference
panel**, and its Elo is fitted with the panel's ratings held fixed. That is the same anchored fit used for
human challenges, so the result lands on the main C=50 leaderboard's scale without moving any model rating.

## Running it

```bash
pip install -e '.[inspect]'          # from a checkout of this repository (configs and lexicons are read from it)
export OPENAI_API_KEY=... GOOGLE_API_KEY=...   # the default panel uses OpenAI and Google models
inspect eval contact_bench/contact_bench --model anthropic/claude-opus-5-5 --reasoning-effort low \
    -T secrets_per_opponent=4
```

Task options (`-T`):

| Option | Default | Meaning |
|---|---|---|
| `panel` | `c50_api_v1` | Panel name in `contact_bench/inspect_task/panels/`, or a path to a panel JSON |
| `secrets_per_opponent` | 4 | Fixtures (fresh secrets) per panel opponent |
| `seed` | 20261120 | Secret-generation seed; secrets are uniform draws from the ENABLE support |
| `opponents` | all | Comma-separated subset of the panel |
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

`c50_api_v1` (frozen 2026-11-20 from the published combined C=50 board, run `combined-overall-c50-all`):

| Opponent | Model and setting | Frozen Elo | 95% CI | Board fixtures |
|---|---|---|---|---|
| `luna` | GPT-6 Luna (Medium, provider default) | 1615.5 | 1497–1731 | 53 |
| `hydrogen` | Gemini 4 Hydrogen (Low) | 1724.4 | 1660–1842 | 98 |
| `terra` | GPT-6.1 Terra (Low) | 1789.7 | 1716–1906 | 87 |
| `carbon` | Gemini 4 Carbon (Low) | 1965.5 | 1782–2251 | 26 |

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
