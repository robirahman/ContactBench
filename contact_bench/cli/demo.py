"""Offline end-to-end demonstration (no network, no keys)."""

from __future__ import annotations

import asyncio
import json
import shutil
from fractions import Fraction
from pathlib import Path

from ..config import load_config
from ..fixtures import MECHANICS_DECISIONS, mechanics_game, render_views, table_decider
from ..scoring.reference import F_b, ReferenceScorer, first_last_mean, clue_only_chunks


def _hr(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def run_demo(out: Path) -> int:
    repo = Path(__file__).resolve().parents[2]
    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    _hr("1. Worked mechanics fixture (spec 6.6): secret candle, prefix c, cap 4")
    g = mechanics_game()
    asyncio.run(g.play(table_decider(MECHANICS_DECISIONS)))
    for view in ("public", "guesser1", "guesser2", "defender", "audit"):
        print()
        print(render_views(g.public_history, g.private_history, g.audit, g.secret, view))
    sc = ReferenceScorer(100)
    B = sc.reference(g.initial_secret_candidates, g.secret)
    print(f"\noutcome={g.outcome_status} reason={g.terminal_reason} realized cost={g.winning_turn} "
          f"reference B={B.value} ({B.method})")

    _hr("2. Numerical reference fixtures (spec 7.9)")
    print(f"first/last F_2(100) = {first_last_mean(100)}, F_2(5) = {first_last_mean(5)}")
    print(f"clue-only cat/dog/pig, C=6 -> {len(clue_only_chunks(['cat', 'dog', 'pig'], 6))} clues")
    print(f"equal length 20, C=100, n=100: F_6 = {F_b(100, 6)};  length 5: F_18 = {F_b(100, 18)}")
    s8 = ReferenceScorer(8)
    h = ((3, 2), (8, 3))
    r3, r8 = s8.reference_hist(h, 3).value, s8.reference_hist(h, 8).value
    print(f"histogram {{3:2,8:3}}, C=8: R(3)={r3}, R(8)={r8}, uniform mean={(2 * r3 + 3 * r8) / 5}")

    _hr("3. Offline tournament: scripted baselines + offline fake LLM adapter")
    from ..analysis.analyze import analyze
    from ..export.public import export_public
    from ..runner.run import Runner

    cfg = load_config(repo / "configs" / "offline_example.yaml")
    cfg = cfg.model_copy(update={"base_dir": str(repo)})
    run_dir = out / "runs" / "demo-offline"
    runner = Runner(cfg, run_dir, live=False, progress=False)
    status = asyncio.run(runner.run())
    print(json.dumps({k: status[k] for k in ("planned_games", "complete_games", "pending_games")}))

    _hr("4. Replay from immutable logs (no providers)")
    rr = Runner(cfg, run_dir, replay_only=True)
    report = asyncio.run(rr.replay())
    print(json.dumps({k: report[k] for k in ("games_replayed", "complete", "equivalent")}))

    _hr("5. Analysis")
    rr2 = Runner(cfg, run_dir, replay_only=True)
    rr2.prepare()
    records = [asyncio.run(rr2.play(gs)) for gs in sorted(rr2.games, key=lambda x: x.game_id)]
    res = analyze(run_dir, records, resamples=cfg.analysis.resamples, seed=cfg.analysis.bootstrap_seed,
                  penalty_scale=cfg.analysis.logit_penalty_scale, elo_center=cfg.analysis.elo_center)
    print((run_dir / "analysis" / "report.md").read_text())

    _hr("6. Public export and static site")
    exp = export_public(run_dir, out / "export", res, records, include_audit=True)
    print(f"export: {exp}")
    try:
        from ..site.build import build_site

        site = build_site([exp], out / "site")
        print(f"site: {site}  (preview: python -m http.server -d {site} 8000)")
    except ImportError as e:  # pragma: no cover
        print(f"site builder unavailable: {e}")
    print("\nDEMO COMPLETE — all data above is synthetic fixture data, not benchmark results.")
    return 0
