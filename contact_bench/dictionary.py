"""Deterministic dictionary lookup interface (dictionary-assisted condition).

Every seat in the ``lookup_tools`` condition gets exactly this interface over
the same frozen lexicon.  Lookups are static (they do not reflect used words or
game state), private, and never count as gameplay utterances.
"""

from __future__ import annotations

import bisect
from typing import Any

from .lexicon import Lexicon, normalize_word
from .providers.base import ToolSpec

MAX_LIMIT = 100
_PREFIX_SCHEMA = {"type": "string", "description": "Lowercase a-z prefix; empty string matches every word."}


class DictionaryService:
    def __init__(self, lexicon: Lexicon):
        self.lexicon = lexicon
        self.words = lexicon.words  # sorted

    # -- interface -------------------------------------------------------------
    def is_legal_word(self, word: str) -> bool:
        w = normalize_word(word)
        return w is not None and w in self.lexicon

    def _range(self, prefix: str) -> tuple[int, int]:
        lo = bisect.bisect_left(self.words, prefix)
        hi = bisect.bisect_left(self.words, prefix + "\x7f")
        return lo, hi

    def count_words(self, prefix: str) -> int:
        lo, hi = self._range(prefix)
        return hi - lo

    def list_words(self, prefix: str, offset: int = 0, limit: int = 100) -> list[str]:
        lo, hi = self._range(prefix)
        start = lo + offset
        return list(self.words[start:min(hi, start + limit)])

    def all_words(self, prefix: str) -> list[str]:
        lo, hi = self._range(prefix)
        return list(self.words[lo:hi])

    # -- metadata --------------------------------------------------------------
    def identity(self) -> dict:
        return {
            "name": self.lexicon.name,
            "word_count": len(self.lexicon),
            "sha256": self.lexicon.sha256,
            "source": self.lexicon.source,
            "word_rules": f"lowercase a-z only, {self.lexicon.min_length}-{self.lexicon.max_length} letters",
        }

    # -- tool calling ----------------------------------------------------------
    @staticmethod
    def tool_specs() -> list[ToolSpec]:
        return [
            ToolSpec(
                "is_legal_word",
                "Return true iff the word is in the game dictionary (exact match after lowercasing).",
                {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"],
                 "additionalProperties": False},
            ),
            ToolSpec(
                "list_words",
                f"List dictionary words starting with prefix, in alphabetical order, from position offset, "
                f"at most limit (1..{MAX_LIMIT}) words. Does not exclude words already used in the game.",
                {"type": "object",
                 "properties": {"prefix": _PREFIX_SCHEMA,
                                "offset": {"type": "integer", "minimum": 0},
                                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT}},
                 "required": ["prefix"], "additionalProperties": False},
            ),
            ToolSpec(
                "count_words",
                "Count dictionary words starting with prefix. Does not exclude words already used in the game.",
                {"type": "object", "properties": {"prefix": _PREFIX_SCHEMA}, "required": ["prefix"],
                 "additionalProperties": False},
            ),
        ]

    def execute(self, name: str, args: Any) -> Any:
        """Deterministic tool execution; invalid arguments yield {"error": ...}."""
        if not isinstance(args, dict):
            return {"error": "arguments must be an object"}

        def prefix_arg() -> str | None:
            p = args.get("prefix", "")
            if not isinstance(p, str) or (p and normalize_word(p) != p):
                return None
            return p

        def int_arg(key: str, default: int, lo: int, hi: int | None) -> int | None:
            v = args.get(key, default)
            if isinstance(v, bool) or not isinstance(v, int) or v < lo or (hi is not None and v > hi):
                return None
            return v

        if name == "is_legal_word":
            if set(args) != {"word"} or not isinstance(args["word"], str):
                return {"error": "is_legal_word takes exactly {word: string}"}
            return {"result": self.is_legal_word(args["word"])}
        if name == "count_words":
            p = prefix_arg()
            if p is None or set(args) - {"prefix"}:
                return {"error": "count_words takes {prefix: lowercase a-z string}"}
            return {"result": self.count_words(p)}
        if name == "list_words":
            p = prefix_arg()
            off = int_arg("offset", 0, 0, None)
            lim = int_arg("limit", MAX_LIMIT, 1, MAX_LIMIT)
            if p is None or off is None or lim is None or set(args) - {"prefix", "offset", "limit"}:
                return {"error": f"list_words takes {{prefix: a-z string, offset: int>=0, limit: 1..{MAX_LIMIT}}}"}
            return {"result": self.list_words(p, off, lim)}
        return {"error": f"unknown tool {name!r}"}
