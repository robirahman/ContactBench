"""Task manifests (spec Section 10).  Referee-only: never shown to players."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from ..lexicon import Lexicon


@dataclass(frozen=True)
class Task:
    task_id: str
    index: int
    secret: str
    split: str
    initial_prefix_length: int
    turn_limit: int
    clue_max_characters: int
    secret_lexicon_sha256: str
    contact_lexicon_sha256: str
    sampling: str
    generation_seed: int


def target_support(v_secret: Lexicon, initial_prefix_length: int) -> list[str]:
    """Admissible targets: strictly longer than the initial prefix."""
    return [w for w in v_secret.words if len(w) > initial_prefix_length]


def generate_tasks(
    *,
    v_secret: Lexicon,
    v_contact: Lexicon,
    count: int,
    seed: int,
    split: str,
    initial_prefix_length: int,
    turn_limit: int,
    clue_max_characters: int,
) -> list[Task]:
    """Independent uniform draws from the admissible secret support."""
    support = target_support(v_secret, initial_prefix_length)
    if not support:
        raise ValueError("no admissible targets")
    rng = random.Random(f"tasks|{seed}|{split}|{v_secret.sha256}")
    tasks = []
    for i in range(count):
        s = support[rng.randrange(len(support))]
        tasks.append(
            Task(
                task_id=f"{split[:3]}{seed}-{i:04d}",
                index=i,
                secret=s,
                split=split,
                initial_prefix_length=initial_prefix_length,
                turn_limit=turn_limit,
                clue_max_characters=clue_max_characters,
                secret_lexicon_sha256=v_secret.sha256,
                contact_lexicon_sha256=v_contact.sha256,
                sampling="uniform_secret",
                generation_seed=seed,
            )
        )
    return tasks


def save_tasks(path: Path, tasks: list[Task]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for t in tasks:
            f.write(json.dumps(asdict(t), sort_keys=True) + "\n")


def load_tasks(path: Path) -> list[Task]:
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            out.append(Task(**json.loads(line)))
    return out
