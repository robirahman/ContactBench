"""Dependency-free SVG figures for papers and reports (spec 17.1)."""

from __future__ import annotations

from html import escape
from pathlib import Path


def _svg(w: int, h: int, body: list[str]) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        'font-family="Helvetica, Arial, sans-serif" font-size="12">'
        f'<rect width="{w}" height="{h}" fill="white"/>' + "".join(body) + "</svg>\n"
    )


def forest_plot(rows: list[tuple[str, float, float | None, float | None]], title: str, ref: float | None = None) -> str:
    """rows: (label, point, lo, hi)."""
    rows = [r for r in rows if r[1] is not None]
    left, right, top, rh = 210, 40, 40, 22
    w, h = 720, top + rh * len(rows) + 40
    vals = [v for r in rows for v in r[1:] if v is not None] + ([ref] if ref is not None else [])
    lo, hi = (min(vals), max(vals)) if vals else (0, 1)
    pad = (hi - lo) * 0.05 or 1
    lo, hi = lo - pad, hi + pad
    X = lambda v: left + (v - lo) / (hi - lo) * (w - left - right)
    b = [f'<text x="{w/2}" y="20" text-anchor="middle" font-weight="bold">{escape(title)}</text>']
    if ref is not None:
        b.append(f'<line x1="{X(ref):.1f}" y1="{top-8}" x2="{X(ref):.1f}" y2="{h-30}" stroke="#999" stroke-dasharray="4 3"/>')
    for i, (lab, p, l, u) in enumerate(rows):
        y = top + i * rh + rh / 2
        b.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end">{escape(lab)}</text>')
        if l is not None and u is not None:
            b.append(f'<line x1="{X(l):.1f}" y1="{y:.1f}" x2="{X(u):.1f}" y2="{y:.1f}" stroke="#4a6fa5" stroke-width="2"/>')
        b.append(f'<circle cx="{X(p):.1f}" cy="{y:.1f}" r="4" fill="#1f3b63"/>')
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        b.append(f'<text x="{X(v):.1f}" y="{h-12}" text-anchor="middle" fill="#555">{v:.3g}</text>')
    return _svg(w, h, b)


def histogram(values: list[float], title: str, bins: int = 20) -> str:
    w, h, left, bottom = 720, 320, 50, 40
    b = [f'<text x="{w/2}" y="20" text-anchor="middle" font-weight="bold">{escape(title)}</text>']
    if not values:
        return _svg(w, h, b)
    lo, hi = min(values), max(values)
    width = (hi - lo) / bins or 1
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int((v - lo) / width))] += 1
    m = max(counts)
    bw = (w - left - 20) / bins
    for i, c in enumerate(counts):
        bh = (h - bottom - 40) * c / m
        b.append(f'<rect x="{left + i*bw:.1f}" y="{h-bottom-bh:.1f}" width="{bw-1:.1f}" height="{bh:.1f}" fill="#4a6fa5"/>')
    b.append(f'<text x="{left}" y="{h-20}" fill="#555">{lo:.3g}</text>')
    b.append(f'<text x="{w-20}" y="{h-20}" text-anchor="end" fill="#555">{hi:.3g}</text>')
    b.append(f'<text x="12" y="{h/2}" fill="#555" transform="rotate(-90 12 {h/2})">count (max {m})</text>')
    return _svg(w, h, b)


def write_figures(out: Path, result: dict, costs_by_attacker: dict[str, list[float]]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    boot = (result.get("bootstrap") or {}).get("intervals_95", {})
    models = sorted(result["models"], key=lambda m: -result["rating"]["elo"][m])
    paths = []
    rows = [(m, result["rating"]["elo"][m], boot.get(m, {}).get("elo", {}).get("lo"),
             boot.get(m, {}).get("elo", {}).get("hi")) for m in models]
    p = out / "rating_forest.svg"
    p.write_text(forest_plot(rows, "Paired rating (batch Elo-style, half-point draws) with 95% cluster-bootstrap CI",
                             ref=1500))
    paths.append(p)
    rows = []
    for m in models:
        sp = result["model_stats"][m]["offense_aggregate_speedup"]
        ci = boot.get(m, {}).get("offense_aggregate_speedup", {})
        if sp:
            rows.append((m, sp["value"], ci.get("lo"), ci.get("hi")))
    p = out / "offense_speedup_forest.svg"
    p.write_text(forest_plot(rows, "Offensive aggregate speedup ΣB/ΣC (1 = reference policy)", ref=1.0))
    paths.append(p)
    for m, vals in sorted(costs_by_attacker.items()):
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in m)
        p = out / f"effective_cost_hist_{safe}.svg"
        p.write_text(histogram(vals, f"Effective cost distribution — attacker {m}"))
        paths.append(p)
    return paths
