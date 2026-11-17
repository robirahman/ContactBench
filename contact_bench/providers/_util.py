"""Small shared helpers for concrete provider adapters."""

from __future__ import annotations

from typing import Any


def get(obj: Any, name: str, default: Any = None) -> Any:
    """Read an attribute or mapping key, tolerating SDK objects and plain dicts."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def to_plain(obj: Any) -> Any:
    """Best-effort JSON-safe dump of an SDK object (for raw usage metadata)."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    for meth in ("model_dump", "to_dict", "dict"):
        f = getattr(obj, meth, None)
        if callable(f):
            try:
                return to_plain(f())
            except Exception:  # pragma: no cover - defensive
                pass
    if hasattr(obj, "__dict__"):
        return {k: to_plain(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return repr(obj)


def int_or_none(v: Any) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def retry_after_from_headers(headers: Any) -> float | None:
    if headers is None:
        return None
    try:
        v = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if v is None:
        return None
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return None
