"""contact-bench command-line interface (spec Section 15)."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from fractions import Fraction
from pathlib import Path

from .. import PROTOCOL_VERSION
from ..config import BenchConfig, ConfigError, load_config


def _runs_dir(args) -> Path:
    return Path(args.runs_dir)


def _config_from_run(run_dir: Path) -> BenchConfig:
    manifest = json.loads((run_dir / "run.json").read_text())
    data = dict(manifest["config"])
    data["base_dir"] = str(Path.cwd())
    return BenchConfig.model_validate(data)


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_validate(args) -> int:
    from ..runner.run import validate_config

    cfg = load_config(args.config)
    report = validate_config(cfg, live=args.live)
    _print(report)
    return 0


def cmd_plan(args) -> int:
    from ..runner.run import load_lexicons
    from ..runner.schedule import build_schedule, run_plan
    from ..runner.tasks import generate_tasks

    cfg = load_config(args.config)
    vs, vc = load_lexicons(cfg)
    tasks = generate_tasks(
        v_secret=vs, v_contact=vc, count=cfg.tasks.tasks_per_pair, seed=cfg.tasks.generation_seed,
        split=cfg.tasks.split, initial_prefix_length=cfg.protocol.initial_prefix_length,
        turn_limit=cfg.protocol.turn_limit, clue_max_characters=cfg.protocol.clue_max_characters,
    )
    _, games = build_schedule(cfg, tasks)
    plan = run_plan(cfg, tasks, games)
    # Optional cost estimate from user-supplied price tables.
    est = 0.0
    have = False
    for m in cfg.models:
        if m.prices and m.max_output_tokens:
            have = True
            calls = plan["maximum_paid_decisions_by_model"].get(m.id, 0)
            est += calls * (6000 * m.prices.input_per_mtok + m.max_output_tokens * m.prices.output_per_mtok) / 1e6
    plan["estimated_cost"] = (
        {"upper_bound_usd_estimate": round(est, 2), "assumptions": "6000 input tokens/decision; full max_output_tokens"}
        if have else None
    )
    _print(plan)
    return 0


def _new_run_id(cfg: BenchConfig) -> str:
    return f"{cfg.name}-{time.strftime('%Y%m%d-%H%M%S')}"


def _provider_caps(items) -> dict[str, float]:
    caps = {}
    for it in items or []:
        k, _, v = it.partition("=")
        caps[k.strip()] = float(v)
    return caps


def _run(cfg: BenchConfig, run_dir: Path, *, live: bool, max_requests, max_usd, progress=True, provider_caps=None) -> dict:
    from ..runner.run import Runner

    runner = Runner(cfg, run_dir, live=live, max_requests=max_requests, max_usd=max_usd, progress=progress,
                    max_usd_by_provider=provider_caps)
    status = asyncio.run(runner.run())
    return status


def cmd_run(args) -> int:
    cfg = _with_concurrency(load_config(args.config), args)
    if args.live == args.offline:
        print("error: choose exactly one of --offline or --live", file=sys.stderr)
        return 2
    if args.live and not (args.max_requests or args.max_usd):
        print("error: --live requires --max-requests N and/or --max-usd X", file=sys.stderr)
        return 2
    run_id = args.run_id or _new_run_id(cfg)
    run_dir = _runs_dir(args) / run_id
    print(f"run {run_id} -> {run_dir}")
    status = _run(cfg, run_dir, live=args.live, max_requests=args.max_requests, max_usd=args.max_usd,
                  provider_caps=_provider_caps(args.max_usd_provider))
    _print(status)
    return 0 if not (status.get("halted") or status.get("fatal_failures")) else 3


def _with_concurrency(cfg: BenchConfig, args) -> BenchConfig:
    """Operational overrides (never scored; execution settings are not frozen)."""
    for name in ("game_concurrency", "provider_concurrency"):
        v = getattr(args, name, None)
        if v is not None and v < 1:
            raise ValueError(f"--{name.replace('_', '-')} must be a positive integer")
    upd = {}
    if getattr(args, "game_concurrency", None):
        upd["game_concurrency"] = args.game_concurrency
    if getattr(args, "provider_concurrency", None):
        upd["per_provider_concurrency"] = args.provider_concurrency
        upd["global_concurrency"] = max(cfg.execution.global_concurrency, 3 * args.provider_concurrency)
    if not upd:
        return cfg
    return cfg.model_copy(update={"execution": cfg.execution.model_copy(update=upd)})


def cmd_resume(args) -> int:
    run_dir = _runs_dir(args) / args.run_id
    cfg = _with_concurrency(_config_from_run(run_dir), args)
    if args.live == args.offline:
        print("error: choose exactly one of --offline or --live", file=sys.stderr)
        return 2
    if args.live and not (args.max_requests or args.max_usd):
        print("error: --live requires --max-requests N and/or --max-usd X", file=sys.stderr)
        return 2
    status = _run(cfg, run_dir, live=args.live, max_requests=args.max_requests, max_usd=args.max_usd,
                  provider_caps=_provider_caps(args.max_usd_provider))
    _print(status)
    return 0 if not (status.get("halted") or status.get("fatal_failures")) else 3


def cmd_replay(args) -> int:
    from ..runner.run import Runner

    run_dir = _runs_dir(args) / args.run_id
    cfg = _config_from_run(run_dir)
    runner = Runner(cfg, run_dir, replay_only=True)
    report = asyncio.run(runner.replay())
    _print(report)
    return 0 if report["equivalent"] else 4


async def _replayed_records(run_dir: Path) -> list[dict]:
    from ..runner.run import Runner

    cfg = _config_from_run(run_dir)
    runner = Runner(cfg, run_dir, replay_only=True)
    runner.prepare()
    return [await runner.play(g) for g in sorted(runner.games, key=lambda g: g.game_id)]


def cmd_analyze(args) -> int:
    from ..analysis.analyze import analyze

    run_dir = _runs_dir(args) / args.run_id
    cfg = _config_from_run(run_dir)
    # Recompute from immutable decision logs (replay), not from editable files.
    records = asyncio.run(_replayed_records(run_dir))
    res = analyze(
        run_dir, records,
        resamples=args.bootstrap if args.bootstrap is not None else cfg.analysis.resamples,
        seed=cfg.analysis.bootstrap_seed, penalty_scale=cfg.analysis.logit_penalty_scale,
        elo_center=cfg.analysis.elo_center,
    )
    print((run_dir / "analysis" / "report.md").read_text())
    print(f"analysis written to {run_dir / 'analysis'}")
    return 0


def cmd_export(args) -> int:
    from ..export.public import export_public

    if not args.public:
        print("error: only --public exports are supported by this command", file=sys.stderr)
        return 2
    run_dir = _runs_dir(args) / args.run_id
    ap = run_dir / "analysis" / "analysis.json"
    if not ap.exists():
        print("error: run `contact-bench analyze` first", file=sys.stderr)
        return 2
    analysis = json.loads(ap.read_text())
    records = asyncio.run(_replayed_records(run_dir))
    out = Path(args.out) if args.out else Path("exports") / args.run_id
    export_public(run_dir, out, analysis, records, include_audit=args.include_audit, max_replays=args.max_replays,
                  release_label=args.label)
    print(f"public export written to {out}")
    return 0


def cmd_build_site(args) -> int:
    from ..site.build import build_site

    out = build_site([Path(p) for p in args.export_dirs], Path(args.out))
    print(f"static site written to {out}; preview with: python -m http.server -d {out} 8000")
    return 0


def cmd_show(args) -> int:
    from ..fixtures import render_views

    run_dir = _runs_dir(args) / args.run_id
    rec = json.loads((run_dir / "games" / f"{args.game_id}.json").read_text())
    print(render_views(rec["public_history"], rec["private_histories"], rec["referee_audit"],
                       rec["summary"]["secret"], args.view))
    return 0


def cmd_reference(args) -> int:
    from ..scoring.reference import ReferenceScorer

    h = tuple(sorted((int(a), int(b)) for a, b in (p.split(":") for p in args.hist.split(","))))
    sc = ReferenceScorer(args.C, rollouts=args.rollouts, exact_small_state_limit=args.exact_limit)
    _print({str(l): v.to_json() for l, v in sc.all_lengths(h).items()})
    return 0


def cmd_build_lexicon(args) -> int:
    from ..lexicon import build_lexicon_from_source

    p = build_lexicon_from_source(
        args.source, args.out_dir, name=args.name, source=args.source_description, license=args.license,
        source_revision=args.source_revision, min_length=args.min_length, max_length=args.max_length,
        exclude_path=args.exclude,
    )
    print(f"lexicon manifest written to {p}")
    return 0


def cmd_smoke(args) -> int:
    """One tiny budgeted live game per selected-provider model vs a scripted defender."""
    cfg = load_config(args.config)
    if not args.live:
        print("error: smoke tests are live by definition; pass --live and --max-requests", file=sys.stderr)
        return 2
    if not args.max_requests:
        print("error: --max-requests is required", file=sys.stderr)
        return 2
    models = [m for m in cfg.models if m.provider == args.provider]
    if not models:
        print(f"error: no {args.provider} models in config", file=sys.stderr)
        return 2
    data = cfg.model_dump(mode="json")
    data.update(
        name=f"smoke-{args.provider}",
        fixture_data=True,
        lexicon={"manifest": "lexicons/mechanics_fixture_manifest.json"},
        protocol={**data["protocol"], "turn_limit": 2},
        tasks={**data["tasks"], "tasks_per_pair": 1, "manifest": None},
        tournament={**data["tournament"], "schedule": "balanced_round_robin", "repetitions": 1},
        models=[{"id": "smoke_defender", "provider": "scripted", "policy": "first_last_two_guess"}]
        + [m.model_dump(mode="json") for m in models],
    )
    scfg = BenchConfig.model_validate(data)
    run_dir = _runs_dir(args) / _new_run_id(scfg)
    status = _run(scfg, run_dir, live=True, max_requests=args.max_requests, max_usd=args.max_usd)
    _print(status)
    print(f"smoke run directory: {run_dir} (resume it to test recovery: contact-bench resume {run_dir.name} --live ...)")
    return 0 if not (status.get("halted") or status.get("fatal_failures")) else 3


def cmd_audit(args) -> int:
    from ..forecasts.audit import build_item_bank, run_shadow_audit
    from ..providers.registry import make_adapter
    from ..runner.run import Runner

    run_dir = _runs_dir(args) / args.run_id
    cfg = _config_from_run(run_dir)
    runner = Runner(cfg, run_dir, replay_only=True)
    items = asyncio.run(build_item_bank(runner, rate=args.rate, seed=args.seed, max_items=args.max_items))
    bank_path = run_dir / "private" / "forecast_item_bank.jsonl"
    bank_path.write_text("".join(json.dumps(i, sort_keys=True) + "\n" for i in items))
    print(f"frozen item bank: {len(items)} items -> {bank_path}")
    if not args.model:
        return 0
    m = next((x for x in cfg.models if x.id == args.model), None)
    if m is None or not m.is_llm:
        print("error: --model must name an LLM/fake model in the run config", file=sys.stderr)
        return 2
    if m.provider != "fake" and not args.live:
        print("error: paid audit calls need --live", file=sys.stderr)
        return 2
    if args.live and m.provider != "fake" and not (args.max_requests or args.max_usd):
        print("error: paid audits need --max-requests and/or --max-usd", file=sys.stderr)
        return 2
    from ..runner.budget import Budget, BudgetGate

    adapter = make_adapter(m)
    adapter.preflight(require_credentials=m.provider != "fake")
    # The budget gate is enforced per transport attempt, so retries count too.
    gate = BudgetGate(Budget(args.max_requests, args.max_usd), m, 8000) if m.provider != "fake" else None
    res = asyncio.run(run_shadow_audit(items, adapter, max_entries=cfg.forecasts.sparse_max_entries,
                                       tolerance=cfg.forecasts.mass_tolerance,
                                       invalid_score=cfg.forecasts.invalid_audit_score,
                                       item_bank_id=run_dir.name, gate=gate,
                                       dictionary=runner.contact_dictionary,
                                       max_tool_calls=cfg.protocol.max_tool_calls_per_decision))
    out = run_dir / "analysis" / f"forecast_audit_{m.id}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=2) + "\n")
    _print(res["summary"])
    return 0


def cmd_demo(args) -> int:
    from .demo import run_demo

    if not args.offline:
        print("error: the demo is offline-only; pass --offline", file=sys.stderr)
        return 2
    return run_demo(Path(args.out))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="contact-bench", description=f"ContactBench ({PROTOCOL_VERSION})")
    p.add_argument("--runs-dir", default="runs")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate"); s.add_argument("config"); s.add_argument("--live", action="store_true")
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("plan"); s.add_argument("config"); s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("demo"); s.add_argument("--offline", action="store_true"); s.add_argument("--out", default="demo_output")
    s.set_defaults(fn=cmd_demo)
    for name, fn in (("run", cmd_run),):
        s = sub.add_parser(name); s.add_argument("config")
        s.add_argument("--offline", action="store_true"); s.add_argument("--live", action="store_true")
        s.add_argument("--max-requests", type=int); s.add_argument("--max-usd", type=float)
        s.add_argument("--run-id")
        s.add_argument("--max-usd-provider", action="append", metavar="PROVIDER=USD",
                       help="per-provider dollar cap, e.g. --max-usd-provider google=4.5 (repeatable)")
        s.add_argument("--game-concurrency", type=int)
        s.add_argument("--provider-concurrency", type=int)
        s.set_defaults(fn=fn)
    s = sub.add_parser("smoke"); s.add_argument("config"); s.add_argument("--provider", required=True,
                                                                         choices=["openai", "anthropic", "google"])
    s.add_argument("--live", action="store_true"); s.add_argument("--max-requests", type=int)
    s.add_argument("--max-usd", type=float); s.set_defaults(fn=cmd_smoke)
    s = sub.add_parser("resume"); s.add_argument("run_id")
    s.add_argument("--offline", action="store_true"); s.add_argument("--live", action="store_true")
    s.add_argument("--max-requests", type=int); s.add_argument("--max-usd", type=float)
    s.add_argument("--max-usd-provider", action="append", metavar="PROVIDER=USD")
    s.add_argument("--game-concurrency", type=int); s.add_argument("--provider-concurrency", type=int)
    s.set_defaults(fn=cmd_resume)
    s = sub.add_parser("replay"); s.add_argument("run_id"); s.set_defaults(fn=cmd_replay)
    s = sub.add_parser("analyze"); s.add_argument("run_id"); s.add_argument("--bootstrap", type=int)
    s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("export"); s.add_argument("run_id"); s.add_argument("--public", action="store_true")
    s.add_argument("--out"); s.add_argument("--include-audit", action="store_true")
    s.add_argument("--max-replays", type=int)
    s.add_argument("--label", help="release notice shown on the site, e.g. 'Pilot: 5 secrets, not confirmatory'")
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("build-site"); s.add_argument("export_dirs", nargs="+"); s.add_argument("--out", default="site_build")
    s.set_defaults(fn=cmd_build_site)
    s = sub.add_parser("show", help="print a game transcript in one information view")
    s.add_argument("run_id"); s.add_argument("game_id")
    s.add_argument("--view", default="public", choices=["public", "guesser1", "guesser2", "defender", "audit"])
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("reference", help="compute R_C(h, ell) for a length histogram like 3:2,8:3")
    s.add_argument("--hist", required=True); s.add_argument("--C", type=int, default=100)
    s.add_argument("--rollouts", type=int, default=2048); s.add_argument("--exact-limit", type=int, default=12)
    s.set_defaults(fn=cmd_reference)
    s = sub.add_parser("build-lexicon"); s.add_argument("source"); s.add_argument("--out-dir", default="lexicons")
    s.add_argument("--name", required=True); s.add_argument("--source-description", required=True)
    s.add_argument("--license", required=True); s.add_argument("--source-revision", required=True)
    s.add_argument("--min-length", type=int, default=3); s.add_argument("--max-length", type=int, default=20)
    s.add_argument("--exclude"); s.set_defaults(fn=cmd_build_lexicon)
    s = sub.add_parser("audit", help="build a frozen forecast item bank and optionally run a shadow audit")
    s.add_argument("run_id"); s.add_argument("--rate", type=float, default=1.0); s.add_argument("--seed", type=int, default=0)
    s.add_argument("--max-items", type=int); s.add_argument("--model"); s.add_argument("--live", action="store_true")
    s.add_argument("--max-requests", type=int); s.add_argument("--max-usd", type=float); s.set_defaults(fn=cmd_audit)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        from ..providers.base import AdapterConfigError
        from ..runner.run import LiveModeError

        if isinstance(e, (AdapterConfigError, LiveModeError, ValueError)):
            print(f"error: {e}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
