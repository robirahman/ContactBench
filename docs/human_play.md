# Play ContactBench yourself

`contact-bench play` lets a person play the benchmark's games against the models and get a score on the
same scale. It runs **on your own machine**: a small server on `127.0.0.1` serves the play page and calls the
models with your own API keys. Nothing on the public site can start a game or spend money.

## Quick start

```bash
pip install -e .
export ANTHROPIC_API_KEY=... OPENAI_API_KEY=... GEMINI_API_KEY=...
contact-bench play configs/human_challenge.yaml --player "Your Name" --live \
    --max-usd-provider anthropic=1 --max-usd-provider openai=1 --max-usd-provider google=1
```

The command prints a `http://127.0.0.1:PORT/#TOKEN` link and opens it. The part after `#` is a private
session token, so don't share the link. To pause, click **Pause and save** (or press Ctrl-C), then resume
with `contact-bench play --resume RUN_ID` and the same budget flags. Every move is recorded as soon as you
submit it.

## What you play

The default config is 4 games, with one secret each against GPT-6 Luna and Gemini 4 Hydrogen (edit
`tasks_per_pair` and `opponents` in `configs/human_challenge.yaml` for more). For each opponent O and secret, you
play a **fixture** of two games:

1. **Attack:** you are Guesser 1, O is your Guesser 2, and O defends. You give clues and choose intended
   words, or guess the secret directly. Your teammate is a separate instance of O, so it doesn't know your word.
2. **Defend:** two instances of O attack and you are the Defender. You see the secret and publish a
   blocklist of words and alphabetical ranges each turn.

The rules match the leaderboard's lookup-tool condition exactly: the ENABLE dictionary, an empty starting
prefix, clues of up to 100 printable ASCII characters, range blocks and a 30-turn cap. As a player you also get
the same three lookups the models get (`is_legal_word`, `count_words` and `list_words`), with the same
limit of 8 per move. There's no time limit, but your think time is recorded; it isn't scored.

You win a fixture when your team's attacking cost is lower than the model team's on the same secret. If both
games hit the cap with no letters earned, the fixture is a draw. Unlike in model runs, there are no
rematches, because a rematch would replay a secret you've already seen.

Fair-play safeguards:

- Every secret is used in **one fixture only**, and you always attack before you defend. You never attack a
  secret you've seen.
- Each run draws its secrets from a fresh random seed, so published transcripts can't help.
- The page only shows your own seat's view, which the engine builds from the same allowlist the models get.
  It never shows referee state or the other seats' private notes.
- If the referee would reject a move (a typo, a used word, an over-long clue), the page tells you the reason
  and lets you fix it, so you don't lose the turn. The move is still validated by the engine as usual.
- It's an honor system: the run directory on your disk contains the secrets, so don't open
  `runs/<RUN_ID>/private/` while playing.

## Scoring and publishing

```bash
contact-bench analyze RUN_ID --anchor lb-latest-small-10    # an analyzed model run, or an export directory
contact-bench export RUN_ID --public --label "Human challenge: Your Name"
```

`--anchor` fits an **anchored Elo**: the opponents' ratings are held fixed at the anchor run's values, and only
your rating is fitted, with the same likelihood and penalty as the model fit. This puts you on the model
leaderboard's scale without ever moving the model ratings. The anchor must have been played under the same
protocol, dictionary, scoring and prompts, with identically configured opponents. Otherwise `analyze`
refuses it. Without `--anchor`, the report shows an unanchored fit, labeled as such.

A human-challenge export is its own condition. Its condition key includes the human player and the mixed
team composition. On the site it appears as **Human challenge: NAME**, with a separate human board. It's
never pooled with model runs: `analyze-combined` rejects any mix of human-challenge and model runs.

Several challenges by the same player (against different opponents, on different secrets, under the same
condition) pool into one rating, so the player appears as a single row:

```bash
contact-bench analyze-combined human-NAME-c50 RUN_ID_1 RUN_ID_2 --anchor ANCHOR --human-tools yes
contact-bench export combined-human-NAME-c50 --public --label "Human challenge: Your Name"
```

`--human-tools yes|no` records whether the player used outside tools such as a calculator. You can also set
`tournament.human_challenge.tools` in the config before playing. The site shows the player as
**NAME (human, with tools)**, **NAME (human, no tools)**, or **NAME (human)** when tool use wasn't recorded.
If several exports rate the same player against a board, the site shows only the one with the most fixtures.
Publish only the pooled export.

To publish, copy the export to `leaderboard/exports/` and push to main.
