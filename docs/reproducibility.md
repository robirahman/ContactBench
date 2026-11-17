# Reproducibility guide

## Environment

- Python 3.13.5 was used for development. `requirements.lock` pins every dependency; its SHA-256 is recorded in
  each run's `run.json`.
- Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install -e . --no-deps`.

## What determines a result

| Component | Where it is recorded |
|---|---|
| Rules and condition | `run.json → config.protocol` (protocol `contact-v0.4`) |
| Lexicon | `run.json → secret_lexicon` (name, SHA-256, provenance, license, preprocessing) |
| Tasks | `private/tasks_private.jsonl` (referee-only; uniform draws from `tasks.generation_seed`) |
| Schedule / execution order | `schedule.json` (order seed is independent of secrets and outcomes) |
| Model decisions | `decisions.jsonl` (append-only, first response wins, keyed by `run/game/turn/seat/phase`) |
| Prompts | `prompt_version` and `prompt_hash` in `run.json`; resuming refuses changed prompts |
| Reference numerics | `packing_version`, `rng_version`, `scoring.root_seed`, rollouts; cache entries in `scoring.cache_dir` |
| Code | `code_revision` (git HEAD, `+dirty` if modified) |

## Replay and re-analysis

```bash
contact-bench replay RUN_ID     # regenerates every game from decisions.jsonl; verifies observation hashes; no providers
contact-bench analyze RUN_ID    # recomputes all statistics from the replayed records
```

`analyze` and `export` always work from replayed records, never from editable CSVs. If a replay diverges (an
observation hash mismatch), the command halts with `EngineInvariantError`.

## Numerical reference

Monte Carlo fallbacks are deterministic given `(root_seed, C, histogram, rollout index)`. The per-rollout rank sums
are cached, so the exact sample means and MCSEs can be audited. To refine, raise the rollout count under a rule you
declared in advance: earlier rollouts are reused and extended, never redrawn. Keep scoring seeds away from live
players. They never enter prompts.

## Release procedure (researcher)

1. `contact-bench analyze RUN_ID --bootstrap 2000` (use the final resample count).
2. `contact-bench export RUN_ID --public [--include-audit]`. Pass `--include-audit` only if the release policy allows
   publishing hidden commitments after the study.
3. `contact-bench build-site exports/RUN_ID --out site_build`. Then preview and deploy as described in
   `docs/website.md`.
4. Archive `runs/RUN_ID` (minus `private/` if the secrets are not yet released), `requirements.lock`, the lexicon
   manifest and the code revision.
