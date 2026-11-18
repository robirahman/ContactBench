"""Static leaderboard site builder (spec Section 17.2).

The site is built from one or more sanitized public exports.  Each export is
kept as its own entry (never pooled across conditions or runs).  The output
needs no API keys, paid inference or live backend.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ..export.public import scan_for_secrets

STATIC_DIR = Path(__file__).parent / "static"
KNOWN_FILES = {"manifest.json", "leaderboard.json", "fixtures.json", "games.json", "games.csv"}
KNOWN_DIRS = {"replays"}
SAFE_ID = re.compile(r"[^A-Za-z0-9_.\-]")


class SiteBuildError(RuntimeError):
    pass


def _validate_export(d: Path) -> dict:
    if not d.is_dir():
        raise SiteBuildError(f"{d} is not an export directory")
    for p in d.iterdir():
        if p.is_dir():
            if p.name not in KNOWN_DIRS:
                raise SiteBuildError(f"{d}: unexpected directory {p.name!r} in export")
            for q in p.iterdir():
                if not (q.is_file() and q.suffix == ".json"):
                    raise SiteBuildError(f"{d}: unexpected file {q.name!r} in {p.name}/")
        elif p.name not in KNOWN_FILES:
            raise SiteBuildError(f"{d}: unexpected file {p.name!r} in export")
    for name in ("manifest.json", "leaderboard.json", "games.json"):
        if not (d / name).exists():
            raise SiteBuildError(f"{d}: missing {name}")
    manifest = json.loads((d / "manifest.json").read_text())
    for k in ("schema_version", "protocol_version", "condition_key", "run_id"):
        if not manifest.get(k):
            raise SiteBuildError(f"{d}: manifest lacks {k}")
    return manifest


def _add_highlights(out_dir: Path, highlights: Path) -> None:
    """Copy the highlights page and its curated data (see site/highlights.py)."""
    data = json.loads(Path(highlights).read_text())
    if data.get("schema") != "contactbench-highlights-1" or not isinstance(data.get("games"), list):
        raise SiteBuildError(f"{highlights}: not a ContactBench highlights file")
    dest = out_dir / "highlights"
    shutil.copytree(STATIC_DIR / "highlights", dest)
    shutil.copy(highlights, dest / "highlights.json")


def build_site(export_dirs: list[Path], out_dir: Path, highlights: Path | None = None) -> Path:
    """Build the static site into ``out_dir`` and return it."""
    export_dirs = [Path(d) for d in export_dirs]
    out_dir = Path(out_dir)
    if not export_dirs:
        raise SiteBuildError("at least one export directory is required")
    manifests = [(d, _validate_export(d)) for d in export_dirs]
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "data").mkdir(parents=True)
    (out_dir / "assets").mkdir()
    entries = []
    seen: set[str] = set()
    for d, m in manifests:
        entry_id = SAFE_ID.sub("_", f"{m['condition_key']}__{m['run_id']}")
        if entry_id in seen:
            raise SiteBuildError(f"duplicate export for run {m['run_id']} and condition {m['condition_key']}")
        seen.add(entry_id)
        shutil.copytree(d, out_dir / "data" / entry_id)
        cond = m.get("condition") or {}
        entries.append({
            "entry_id": entry_id,
            "condition_key": m["condition_key"],
            "run_id": m["run_id"],
            "schema_version": m["schema_version"],
            "protocol_version": m["protocol_version"],
            "run_created_at": m.get("run_created_at"),
            "exported_at": m.get("exported_at"),
            "fixture_data": bool(m.get("fixture_data", True)),
            "release_label": m.get("release_label"),
            "headline": bool(m.get("headline", False)),
            "combined": str(m["run_id"]).startswith("combined-"),
            "condition": {k: cond.get(k) for k in (
                "clue_max_characters", "turn_limit", "lexicon_name", "lexicon_sha256", "resolver",
                "packing_version", "rng_version", "numerical_rollouts", "forecast_mode", "timing",
                "reveal_policy", "target_hit_scope", "count_cap", "dictionary_access",
                "blocklist_encoding", "initial_prefix_length", "human_challenge", "homogeneous_attackers",
                "partner_disclosure")},
        })
    # Headline exports (the main format) first; otherwise keep the given order.
    entries.sort(key=lambda e: not e["headline"])
    (out_dir / "data" / "index.json").write_text(json.dumps({"conditions": entries}, indent=2) + "\n")
    shutil.copy(STATIC_DIR / "index.html", out_dir / "index.html")
    for name in ("app.js", "style.css"):
        shutil.copy(STATIC_DIR / name, out_dir / "assets" / name)
    if highlights is not None:
        _add_highlights(out_dir, highlights)
    hits = scan_for_secrets(out_dir)
    if hits:
        shutil.rmtree(out_dir)
        raise SiteBuildError("site build aborted; credential-like content found: " + "; ".join(hits[:5]))
    return out_dir


def main(argv: list[str] | None = None) -> int:
    """Stdlib-only entry point (used by the GitHub Pages workflow)."""
    import argparse

    p = argparse.ArgumentParser(description="Build the ContactBench static leaderboard site")
    p.add_argument("export_dirs", nargs="+")
    p.add_argument("--out", default="site_build")
    p.add_argument("--highlights", help="curated highlights JSON (contact_bench.site.highlights)")
    a = p.parse_args(argv)
    print(build_site([Path(x) for x in a.export_dirs], Path(a.out),
                     Path(a.highlights) if a.highlights else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
