"""Fixed model ratings for anchoring a human-challenge run.

An anchor is a model run (a run directory or run id with ``analysis/``; a
combined run works too) or a public export directory.  Its Elo values only
mean something for the challenge if the game was the same, so the anchor must
match the challenge run's protocol, lexicons, scoring and prompt templates,
and every opponent's inference profile.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import ProtocolConfig

# Inference-profile fields compared for each opponent (as in public exports).
PROFILE_KEYS = ["provider", "api_family", "model", "parameters", "max_output_tokens", "prompt_version",
                "offense_mode"]


class AnchorError(ValueError):
    pass


def _protocol(p: dict) -> dict:
    return ProtocolConfig.model_validate(p).model_dump(mode="json")


def _profile(m: dict) -> dict:
    defaults = {"parameters": {}, "prompt_version": "prompts-v1", "offense_mode": "full"}
    return {k: m.get(k, defaults.get(k)) for k in PROFILE_KEYS}


def _resolve(ref: str, runs_dir: Path) -> Path:
    for p in (Path(ref), Path(runs_dir) / ref):
        if p.is_dir():
            return p
    raise AnchorError(f"--anchor {ref!r}: not a run directory, run id or export directory")


def load_anchor(ref: str, runs_dir: Path, run_dir: Path) -> dict:
    """Return {"elo": {...}, "run_id": ...} after checking compatibility."""
    d = _resolve(ref, runs_dir)
    run = json.loads((Path(run_dir) / "run.json").read_text())
    rcfg = run["config"]
    opponents = {m["id"]: m for m in rcfg["models"] if m.get("provider") != "human"}
    problems: list[str] = []
    if (d / "run.json").exists():
        a_path = d / "analysis" / "analysis.json"
        if not a_path.exists():
            raise AnchorError(f"--anchor {ref!r}: run has no analysis (run `contact-bench analyze` on it first)")
        man = json.loads((d / "run.json").read_text())
        acfg = man["config"]
        if _protocol(acfg["protocol"]) != _protocol(rcfg["protocol"]):
            problems.append("protocol")
        if acfg.get("scoring") != rcfg.get("scoring"):
            problems.append("scoring")
        for k in ("secret_lexicon", "contact_lexicon"):
            if (man.get(k) or {}).get("sha256") != (run.get(k) or {}).get("sha256"):
                problems.append(k)
        if man.get("prompt_hash") != run.get("prompt_hash"):
            problems.append("prompt templates")
        a_models = {m["id"]: m for m in acfg["models"]}
        analysis = json.loads(a_path.read_text())
        run_id = man.get("run_id")
    elif (d / "manifest.json").exists() and (d / "leaderboard.json").exists():
        man = json.loads((d / "manifest.json").read_text())
        cond = man.get("condition") or {}
        if cond.get("human_challenge"):
            raise AnchorError(f"--anchor {ref!r}: a human-challenge export cannot anchor another")
        if _protocol(cond.get("protocol") or {}) != _protocol(rcfg["protocol"]):
            problems.append("protocol")
        if cond.get("lexicon_sha256") != run["secret_lexicon"]["sha256"]:
            problems.append("lexicon")
        sc = rcfg.get("scoring") or {}
        rollouts = sc.get("proposed_final_rollouts") if sc.get("use_final_rollouts") else sc.get("development_rollouts")
        if cond.get("resolver") != sc.get("resolver") or cond.get("numerical_rollouts") != rollouts:
            problems.append("scoring")
        if man.get("prompt_hash") != run.get("prompt_hash"):
            problems.append("prompt templates")
        a_models = {m["id"]: m for m in man.get("models") or []}
        analysis = json.loads((d / "leaderboard.json").read_text())
        run_id = man.get("run_id")
    else:
        raise AnchorError(f"--anchor {ref!r}: expected a run (run.json + analysis/) or an export directory")
    if any(m.get("provider") == "human" for m in a_models.values()):
        raise AnchorError(f"--anchor {ref!r}: a human-challenge run cannot anchor another")
    for mid, m in opponents.items():
        if mid not in a_models:
            problems.append(f"opponent {mid} not in anchor")
        elif _profile(a_models[mid]) != _profile(m):
            problems.append(f"opponent {mid} configured differently")
    elo = (analysis.get("rating") or {}).get("elo") or {}
    for mid in opponents:
        if mid in a_models and mid not in elo:
            problems.append(f"no Elo for {mid}")
    if problems:
        raise AnchorError(f"--anchor {ref!r} is incompatible with this run: " + "; ".join(problems))
    return {"elo": {m: elo[m] for m in opponents}, "run_id": run_id}
