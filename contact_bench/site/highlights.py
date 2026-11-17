"""Curated game highlights for the static site.

A selection file (YAML) names games by run and game id and adds a title and a
short commentary.  This module turns the referee records of those games into a
compact, public-safe JSON file for the highlights page.  It only includes
gameplay information that is already published in post-study replay exports
(the secret is revealed after the game; hidden commitments are shown as an
omniscient post-game view, clearly labelled on the page).

Usage:
    python -m contact_bench.site.highlights SELECTION.yaml RUNS_DIR OUT.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

MAX_BLOCK_WORDS = 12


def _turn(t: dict) -> dict:
    g1 = t.get("guesser1") or {}
    canon = g1.get("canonical") or {}
    out: dict = {"turn": t["turn"], "prefix_before": t.get("prefix_before", ""),
                 "prefix_after": t.get("prefix_after", t.get("prefix_before", ""))}
    if not g1.get("valid", True):
        out.update(kind="invalid", note=g1.get("reason"))
        return out
    if canon.get("action") == "direct":
        out.update(kind="direct", word=canon.get("word"), result=t.get("result"))
        return out
    words = list(t.get("blocklist") or [])
    out.update(
        kind="clue",
        clue=t.get("clue"),
        intended=t.get("w1"),
        receiver=t.get("w2"),
        block_words=words[:MAX_BLOCK_WORDS],
        block_words_total=len(words),
        block_ranges=[list(r) for r in (t.get("blocked_ranges") or [])],
        block_size=t.get("block_size", len(words)),
        opened=[o.get("word") for o in (t.get("opened") or [])],
        result=t.get("result"),
        contact=bool(t.get("contact")),
        prevented=bool(t.get("blocked_contact")),
        choice=({"seat": t.get("choice_actor"), "choice": t.get("choice")} if t.get("choice_actor") else None),
    )
    return out


def build(selection: Path, runs_dir: Path) -> dict:
    sel = yaml.safe_load(Path(selection).read_text())
    games = []
    for item in sel["games"]:
        run_dir = Path(runs_dir) / item["run"]
        rec = json.loads((run_dir / "games" / f"{item['game_id']}.json").read_text())
        if rec.get("run_status") not in (None, "complete") and not item.get("allow_incomplete"):
            raise ValueError(f"{item['game_id']} is not a complete game")
        manifest = json.loads((run_dir / "run.json").read_text())
        proto = manifest["config"]["protocol"]
        s, g = rec["summary"], rec["game"]
        audit = rec.get("referee_audit") or []
        games.append({
            "id": item["id"],
            "title": item["title"],
            "blurb": item["blurb"],
            "tags": item.get("tags", []),
            "run_id": manifest["run_id"],
            "game_id": g["game_id"],
            "attacker": g["attacker"],
            "defender": g["defender"],
            "secret": s["secret"],
            "initial_prefix": s["initial_prefix"],
            "final_prefix": s["final_prefix"],
            "outcome": s["outcome_status"],
            "terminal_reason": s["terminal_reason"],
            "turns_used": s["turns_used"],
            "turn_limit": s["turn_limit"],
            "contacts": sum(1 for t in audit if t.get("contact")),
            "prevented": sum(1 for t in audit if t.get("blocked_contact")),
            "rematch_level": g["game_id"].count("rematch"),
            "condition": {
                "dictionary_access": proto.get("dictionary_access"),
                "lexicon": manifest["secret_lexicon"]["name"],
                "lexicon_words": manifest["secret_lexicon"]["word_count"],
                "clue_max_characters": proto.get("clue_max_characters"),
            },
            "turns": [_turn(t) for t in audit],
        })
    return {"schema": "contactbench-highlights-1", "title": sel.get("title", "Highlights"),
            "intro": sel.get("intro", ""), "games": games}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m contact_bench.site.highlights")
    ap.add_argument("selection")
    ap.add_argument("runs_dir")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    data = build(Path(a.selection), Path(a.runs_dir))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(data, indent=1) + "\n")
    print(f"{len(data['games'])} highlighted games -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
