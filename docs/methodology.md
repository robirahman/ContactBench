# Methodology (protocol contact-v0.4, as implemented)

The authoritative rules are in `CONTACT_BENCHMARK_SPEC.md`. This page describes how the code implements them.

## Game

- **State.** The referee holds the secret `s`, the vocabularies `V_secret ⊆ V_contact` (identical in the primary
  profile), and the public state: prefix, turns used, cap `L`, used words, public history and outcome. Candidate sets
  are computed fresh each time:
  `C_secret = {w ∈ V_secret : w starts with prefix} − used_words`, and `C_contact` the same way.
- **Turn.** Guesser 1 either makes a *direct* guess, which is a public utterance with no responders, or gives a *clue*
  (printable ASCII, 1..C characters after trimming) and privately registers an intended word from pre-turn
  `C_contact`. Guesser 2 (word or pass) and the defender (blocklist) are then collected **sealed and concurrently**
  from the same pre-resolution observation. Both are collected even when the clue already contains the secret
  (`complete_even_on_public_clue_hit`). `early_stop_on_public_clue_hit` is available as a separate condition.
- **Opening table.**

  | Case | Opened |
  |---|---|
  | Neither blocked | both, at the same time |
  | Both blocked | neither (no extra call) |
  | Exactly one blocked | the unblocked seat privately chooses reveal or cancel |
  | Receiver passed | Guesser 1, if unblocked |

- **Wins.** Saying `s` publicly through any gameplay channel wins: clue tokens, an opened guess, a direct guess or a
  blocklist entry. A *contact*, meaning both guesses opened, equal to each other, absent from the pre-turn used words
  and not named in the current clue, reveals the next actual letter. If that letter completes `s`, the game ends with
  `terminal_reason=prefix_completed`. A private registration never tests the target.
- **Retirement.** Every public emission becomes a used word: clue mentions, block entries and opened guesses. So does
  every complete displayed prefix that is a dictionary word, including the initial prefix. Canceled words that were
  not otherwise emitted stay available.
- **Clue mentions** are maximal ASCII-alphabetic runs, lowercased, then intersected with `V_secret ∪ V_contact`. So
  `Art!` mentions *art* and `artist` does not. Hyphens and apostrophes split runs.
- **Admission before broadcast.** Every action is validated against public rules before any of its content is tested
  against the secret. An invalid Guesser 1 action wastes the turn and publishes only `invalid_action`. An invalid
  Guesser 2 action becomes a private pass. An invalid blocklist becomes empty. An invalid choice becomes cancel.
  Rejected raw text never enters public history.
- **Information boundaries.** Observations are built from an explicit allowlist (`observations/builder.py`). Public
  history records the clue, the full blocklist, only the guesses actually opened, and the prefix/result. It never
  records hidden match flags, blocked-seat flags, pass/validity status or the cancellation actor. Each seat keeps only
  its own private history.

## Score

- **Reference policy** `R_C(S, s)`, "fresh-shuffle character packing". Each turn it takes a fresh uniform order of the
  public candidates and the longest feasible prefix of that order. The two longest words in that prefix go to the
  guess slots and the rest are listed in the clue with one space between words. With weights `a(w)=len(w)+1` and
  `Q=C+1`, a batch of 3 or more words is feasible iff `Σa − (two largest) ≤ Q`. The policy plays against an empty
  defender and always reveals.
- **Numerics.** Exact shortcuts cover the all-fit, equal-length and constant-capacity cases (`F_b(n)`). An exact
  rational oracle covers states up to `exact_small_state_limit` candidates. Larger states use a length-class Monte
  Carlo estimator: `K` complete rollouts, rank sums by length class, an exact rational sample mean
  (`rank_total / (K·h[ℓ])`) and a rollout-level MCSE. Rollout seeds are
  `sha256(rng_version | packing_version | root_seed | C | histogram | r)`. They never depend on the target, model or
  score. Results are cached by histogram and accumulate in a resumable way.
- **Game cost.** `B = R_C(S0, s)`. The cost `C` is the winning turn `t`, or `L + R_C(S_L, s)` if the game is still
  unsolved after turn `L` has fully resolved. Infrastructure-incomplete games get no cost.
- **Aggregates** are ratios of totals: `aggregate_speedup = ΣB/ΣC`. Per-game ratios are never averaged.
- **Robust summaries.** An unsolved game in a large-dictionary state is charged thousands of fallback turns, so
  means are dominated by whether the first letter fell. Analysis therefore also reports the median and
  geometric-mean effective cost per attacker, and the median cost imposed per defender, with bootstrap intervals.

## Competitive rating

- For each unordered pair (A, B), each task and each repetition: A+A attack B, and B+B attack A, on the same secret.
  A's match points are 1, ½ or 0 according to an exact rational comparison of `C_AB` and `C_BA`.
- **Batch Elo-style rating with half-point draws.** Newton's method minimizes the cross-entropy plus
  `Σr²/(2·2.5²)`. Strengths are recentred to sum to zero and reported as `Elo = 1500 + 400/ln10 · r`. The run records
  convergence, connected components and sensitivity to the penalty scale (1, 2.5, 5).
- **Uncertainty.** The bootstrap resamples whole task (secret) clusters, keeping both legs and all pairings, and
  refits the rating in every resample. It reports 95% intervals for Elo, rank, offensive speedup, mean paired cost
  advantage and defensive cost ratio.
- **Rating is not efficiency.** The 24-target counterexample is in `tests/test_reference.py`: both policies have mean
  cost 2.5, yet one earns 62.5% of match points. Efficiency (`ΣB/ΣC`, mean paired cost advantage
  `A_i = mean_j mean_tasks(C_ji − C_ij)`, defensive cost ratio, deadline hold rate) is reported separately from the
  rating.

## Forecast diagnostics (optional)

These use a sparse report with up to 20 entries plus `other_mass`, which is spread uniformly over the unlisted support.
The primary score is the higher-is-better Brier score `2q(W) − Σq²`. The log score records zero-probability failures
explicitly. A scheduled report that is model-invalid scores −1. The answer key is Guesser 1's committed intended word
`W`, which is scoreable even when it is never opened. `contact-bench audit` builds a frozen item bank from replayed
pre-resolution observations, using a hash rule fixed in advance that does not depend on branch or outcome, and runs
isolated shadow-audit calls. `joint_live` mode stores the envelopes privately. They never affect gameplay.

## Limitations

- Mechanical legality is not semantic naturalness. Literal enumeration and index encodings are legal (see the
  `public_index_ambiguity` baseline).
- Monte Carlo fallbacks have numerical error, reported as MCSE and as a per-fixture cost-difference MCSE. An exact
  comparison of fractions makes the computation reproducible. It does not prove the ideal expectations are ordered the
  same way.
- Field-conditional statistics depend on the opponent population.
- Live provider behavior has not been exercised by the offline tests.
