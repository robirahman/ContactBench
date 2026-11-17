"""Lexicons, word normalization and literal clue mentions (spec Section 4)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

WORD_RE = re.compile(r"^[a-z]+$")
ALPHA_RUN_RE = re.compile(r"[A-Za-z]+")
ASCII_WS = " \t\n\r\x0b\x0c"


class LexiconError(ValueError):
    pass


def normalize_word(raw: object) -> str | None:
    """Normalize a registered word or block entry.

    Strip surrounding ASCII whitespace, lowercase ASCII A-Z and require a single
    [a-z]+ token.  Returns None when the value is not a single word.  Membership
    in a vocabulary is checked separately.  No stemming, spelling repair or
    synonym matching is performed.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip(ASCII_WS)
    # Lowercase ASCII letters only; non-ASCII letters are rejected by WORD_RE.
    s = "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)
    if not WORD_RE.match(s):
        return None
    return s


def extract_alpha_runs(text: str) -> list[str]:
    """Maximal ASCII alphabetic runs, lowercased (in order, with repeats)."""
    return [m.group(0).lower() for m in ALPHA_RUN_RE.finditer(text)]


def mentioned_words(text: str, vocabulary: frozenset[str] | set[str]) -> frozenset[str]:
    """Dictionary words literally mentioned in decoded clue text.

    "Art!" mentions art; "artist" does not; hyphens and apostrophes separate
    runs.
    """
    return frozenset(t for t in extract_alpha_runs(text) if t in vocabulary)


def sha256_of_words(words: Iterable[str]) -> str:
    h = hashlib.sha256()
    for w in words:
        h.update(w.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


@dataclass(frozen=True)
class Lexicon:
    """A frozen, sorted, unique, normalized word list."""

    name: str
    words: tuple[str, ...]
    sha256: str
    source: str = ""
    license: str = ""
    source_revision: str = ""
    preprocessing: tuple[str, ...] = ()
    exclusions: str = ""
    min_length: int = 1
    max_length: int = 64
    _set: frozenset[str] = field(default=frozenset(), compare=False, repr=False)

    @staticmethod
    def from_words(
        name: str,
        words: Iterable[str],
        *,
        min_length: int = 1,
        max_length: int = 64,
        **meta,
    ) -> "Lexicon":
        ws = sorted(set(words))
        for w in ws:
            if not WORD_RE.match(w):
                raise LexiconError(f"lexicon {name!r}: word {w!r} is not normalized [a-z]+")
            if not (min_length <= len(w) <= max_length):
                raise LexiconError(
                    f"lexicon {name!r}: word {w!r} length outside [{min_length},{max_length}]"
                )
        if not ws:
            raise LexiconError(f"lexicon {name!r} is empty")
        lex = Lexicon(
            name=name,
            words=tuple(ws),
            sha256=sha256_of_words(ws),
            min_length=min_length,
            max_length=max_length,
            **{k: (tuple(v) if k == "preprocessing" else v) for k, v in meta.items()},
        )
        object.__setattr__(lex, "_set", frozenset(ws))
        return lex

    @property
    def word_set(self) -> frozenset[str]:
        return self._set

    def __contains__(self, w: object) -> bool:
        return w in self._set

    def __len__(self) -> int:
        return len(self.words)

    @property
    def max_word_length(self) -> int:
        return max(len(w) for w in self.words)

    def manifest(self) -> dict:
        return {
            "name": self.name,
            "word_count": len(self.words),
            "sha256": self.sha256,
            "source": self.source,
            "license": self.license,
            "source_revision": self.source_revision,
            "preprocessing": list(self.preprocessing),
            "exclusions": self.exclusions,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "max_word_length_observed": self.max_word_length,
        }


def load_lexicon_manifest(path: str | Path) -> Lexicon:
    """Load a lexicon from its JSON manifest and verify the word file hash.

    Manifest keys: name, words_file (relative to manifest), sha256, word_count,
    source, license, source_revision, preprocessing, exclusions, min_length,
    max_length.
    """
    path = Path(path)
    meta = json.loads(path.read_text())
    words_path = (path.parent / meta["words_file"]).resolve()
    raw = [ln.strip() for ln in words_path.read_text().splitlines()]
    raw = [w for w in raw if w and not w.startswith("#")]
    if raw != sorted(set(raw)):
        raise LexiconError(f"{words_path}: words must be sorted, unique and normalized")
    lex = Lexicon.from_words(
        meta["name"],
        raw,
        min_length=int(meta.get("min_length", 1)),
        max_length=int(meta.get("max_length", 64)),
        source=meta.get("source", ""),
        license=meta.get("license", ""),
        source_revision=meta.get("source_revision", ""),
        preprocessing=meta.get("preprocessing", []),
        exclusions=meta.get("exclusions", ""),
    )
    if meta.get("sha256") and meta["sha256"] != lex.sha256:
        raise LexiconError(
            f"{path}: sha256 mismatch (manifest {meta['sha256']}, computed {lex.sha256})"
        )
    if meta.get("word_count") is not None and int(meta["word_count"]) != len(lex):
        raise LexiconError(f"{path}: word_count mismatch")
    return lex


def build_lexicon_from_source(
    source_path: str | Path,
    out_dir: str | Path,
    *,
    name: str,
    source: str,
    license: str,
    source_revision: str,
    min_length: int = 3,
    max_length: int = 20,
    exclude_path: str | Path | None = None,
) -> Path:
    """Preprocess a researcher-supplied word list into a versioned lexicon.

    Preprocessing: strip whitespace, ASCII-lowercase, keep only [a-z]+ tokens
    within [min_length, max_length], drop excluded words, sort, deduplicate.
    Returns the manifest path.  The caller is responsible for the source's
    redistribution rights.
    """
    source_path, out_dir = Path(source_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    excluded: set[str] = set()
    if exclude_path:
        excluded = {
            w for w in (normalize_word(x) for x in Path(exclude_path).read_text().splitlines()) if w
        }
    kept = set()
    dropped = 0
    for line in source_path.read_text(errors="replace").splitlines():
        w = normalize_word(line)
        if w is None or not (min_length <= len(w) <= max_length) or w in excluded:
            dropped += 1
            continue
        kept.add(w)
    words = sorted(kept)
    words_file = out_dir / f"{name}.txt"
    words_file.write_text("\n".join(words) + "\n")
    lex = Lexicon.from_words(name, words, min_length=min_length, max_length=max_length)
    manifest = {
        "name": name,
        "words_file": words_file.name,
        "sha256": lex.sha256,
        "word_count": len(words),
        "source": source,
        "license": license,
        "source_revision": source_revision,
        "preprocessing": [
            "strip surrounding ASCII whitespace",
            "lowercase ASCII A-Z",
            "keep tokens matching ^[a-z]+$",
            f"keep lengths {min_length}..{max_length}",
            "remove excluded words" if exclude_path else "no exclusion list",
            "sort and deduplicate",
        ],
        "exclusions": str(exclude_path) if exclude_path else "",
        "lines_dropped": dropped,
        "min_length": min_length,
        "max_length": max_length,
    }
    mpath = out_dir / f"{name}_manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2) + "\n")
    return mpath
