"""Combine runs played under one condition into a single rating pool.

Runs can only be combined when everything that defines the condition is
identical: protocol, lexicons, scoring, prompts, the tournament's scoring
rules, task secrets for shared task ids, and the configuration of every model
id that appears in more than one run.  Combining is how cross-tier matchups
(an explicit "pairs" run) join tier round robins into overall ratings.
Combined runs are never pooled with anything that differs on these fields.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from ..config import BenchConfig, schedule_rematch_flags, snapshot_with_legacy_defaults
from ..runner.store import atomic_write_json


class CombineError(ValueError):
    pass


CONDITION_SECTIONS = ("protocol", "lexicon", "scoring", "forecasts")
TOURNAMENT_RULES = ("no_progress_draws", "rematch_on_no_progress_draw", "rematch_extra_letters", "rematch_recursive")


def _normalized_config(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "run.json").read_text())
    sched = json.loads((run_dir / "schedule.json").read_text())
    data = snapshot_with_legacy_defaults(manifest["config"], *schedule_rematch_flags(sched.get("fixtures", [])))
    data["base_dir"] = "."
    return BenchConfig.model_validate(data).model_dump(mode="json", exclude={"base_dir"})


def is_combined(run_dir: Path) -> bool:
    p = Path(run_dir) / "run.json"
    return p.exists() and "combined_from" in json.loads(p.read_text())


def combine(name: str, run_dirs: list[Path], out_root: Path) -> Path:
    if len(run_dirs) < 2:
        raise CombineError("combine at least two runs")
    run_dirs = [Path(d) for d in run_dirs]
    manifests = [json.loads((d / "run.json").read_text()) for d in run_dirs]
    cfgs = [_normalized_config(d) for d in run_dirs]
    for d, c in zip(run_dirs, cfgs):
        if not c["tournament"].get("homogeneous_attackers", True):
            raise CombineError(f"{d.name}: mixed-team runs are a separate condition and are not combined "
                               "(use tournament.teams.prior_runs to inform defender selection)")
    ref, ref_m = cfgs[0], manifests[0]
    for d, c in zip(run_dirs, cfgs):
        if any(mc["provider"] == "human" for mc in c["models"]):
            # Human results are rated against fixed model ratings, never pooled.
            raise CombineError(f"{d.name}: human-challenge runs are never pooled with model runs")
    for d, c, m in zip(run_dirs[1:], cfgs[1:], manifests[1:]):
        for sec in CONDITION_SECTIONS:
            if c[sec] != ref[sec]:
                raise CombineError(f"{d.name}: section '{sec}' differs from {run_dirs[0].name}")
        for k in TOURNAMENT_RULES:
            if c["tournament"][k] != ref["tournament"][k]:
                raise CombineError(f"{d.name}: tournament rule '{k}' differs")
        if m.get("prompt_hash") != ref_m.get("prompt_hash"):
            raise CombineError(f"{d.name}: prompt templates differ")
        for k in ("engine_version", "packing_version", "rng_version", "protocol_version"):
            if m.get(k) != ref_m.get(k):
                raise CombineError(f"{d.name}: {k} differs ({m.get(k)} vs {ref_m.get(k)})")
        if m["secret_lexicon"]["sha256"] != ref_m["secret_lexicon"]["sha256"]:
            raise CombineError(f"{d.name}: secret lexicon differs")
        if (m.get("contact_lexicon") or {}).get("sha256") != (ref_m.get("contact_lexicon") or {}).get("sha256"):
            raise CombineError(f"{d.name}: contact lexicon differs")
    from ..runner.schedule import GameSpec

    scheds = [json.loads((d / "schedule.json").read_text()) for d in run_dirs]
    # A run's schedule can drop games (e.g. a model configuration that was replaced
    # mid-pilot); only models that play a scheduled game take part in the combine.
    played = [set().union(*(GameSpec(**g).models for g in s["games"])) if s["games"] else set() for s in scheds]
    models: dict[str, dict] = {}
    for d, c, pl in zip(run_dirs, cfgs, played):
        for mc in c["models"]:
            if mc["id"] not in pl:
                continue
            if mc["id"] in models and models[mc["id"]] != mc:
                raise CombineError(f"model '{mc['id']}' is configured differently in {d.name}")
            models.setdefault(mc["id"], mc)
    secrets: dict[str, str] = {}
    fixtures, games, game_ids = [], [], set()
    for d in run_dirs:
        for line in (d / "private" / "tasks_private.jsonl").read_text().splitlines():
            t = json.loads(line)
            if secrets.setdefault(t["task_id"], t["secret"]) != t["secret"]:
                raise CombineError(f"task {t['task_id']} has different secrets across runs")
    for d, sched in zip(run_dirs, scheds):
        for g in sched["games"]:
            if g["game_id"] in game_ids:
                raise CombineError(f"game id {g['game_id']} appears in more than one run")
            game_ids.add(g["game_id"])
            games.append(g)
        ids = {g["game_id"] for g in sched["games"]}
        # Fixtures whose games were dropped from the schedule are not part of the run.
        fixtures.extend(f for f in sched["fixtures"] if f["game_ab"] in ids and f["game_ba"] in ids)
    out = Path(out_root) / f"combined-{name}"
    o = out.resolve()
    for d in run_dirs:
        r = d.resolve()
        if r == o or o in r.parents or r in o.parents:
            raise CombineError(f"output {out.name} overlaps source {d.name}; choose a new combined name")
    if any(is_combined(d) for d in run_dirs):
        raise CombineError("combine source runs directly, not an existing combined run")
    if out.exists():
        shutil.rmtree(out)
    (out / "private").mkdir(parents=True)
    merged = dict(ref)
    merged["models"] = list(models.values())
    merged["name"] = f"combined-{name}"
    merged["tournament"] = {**ref["tournament"], "schedule": "pairs",
                            "pairs": sorted({tuple(sorted((f["model_a"], f["model_b"]))) for f in fixtures})}
    merged["tournament"]["pairs"] = [list(p) for p in merged["tournament"]["pairs"]]
    manifest = {
        **{k: ref_m[k] for k in ("schema_version", "protocol_version", "engine_version", "packing_version",
                                 "rng_version", "prompt_version", "prompt_hash", "secret_lexicon",
                                 "contact_lexicon", "target_distribution") if k in ref_m},
        "run_id": f"combined-{name}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "code_revision": ref_m.get("code_revision"),
        "config": merged,
        "fixture_data": any(m.get("fixture_data", True) for m in manifests),
        "combined_from": [{"run_id": m["run_id"], "run_dir": str(d.resolve()), "code_revision": m.get("code_revision"),
                           "created_at": m.get("created_at")} for d, m in zip(run_dirs, manifests)],
    }
    atomic_write_json(out / "run.json", manifest)
    atomic_write_json(out / "schedule.json", {"fixtures": fixtures, "games": games})
    for log in ("requests.jsonl", "forecasts.jsonl"):  # resource accounting reads both
        with (out / log).open("w") as f:
            for d in run_dirs:
                p = d / log
                if p.exists():
                    for line in p.read_text().splitlines(keepends=True):
                        try:
                            gid = json.loads(line).get("game_id")
                        except ValueError:
                            continue
                        if gid is None or gid in game_ids:  # skip requests of dropped games
                            f.write(line)
    with (out / "private" / "tasks_private.jsonl").open("w") as f:
        for d in run_dirs:
            for line in (d / "private" / "tasks_private.jsonl").read_text().splitlines():
                t = json.loads(line)
                if t["task_id"] in secrets:
                    f.write(line + "\n")
                    secrets.pop(t["task_id"])
    return out


def source_run_dirs(run_dir: Path) -> list[Path]:
    m = json.loads((Path(run_dir) / "run.json").read_text())
    return [Path(s["run_dir"]) for s in m["combined_from"]]
