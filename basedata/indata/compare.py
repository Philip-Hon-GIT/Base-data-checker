"""Compare a new height surface with an approved reference surface.

Reports the systematic height offset, the spread, how much area has changed, a horizontal shift if
the data fits better when moved, a small difference map and a histogram. The rule R-REF-01 turns
these numbers into a result using tolerances from the rule set.
"""

from __future__ import annotations

import math

import numpy as np

from basedata.indata.surface import Surface

SHIFT_CELLS = 3
THRESHOLDS = [0.1, 0.25, 0.5, 1.0, 2.0]
MAP_MAX = 64
HIST_EDGES = [round(-0.5 + 0.05 * i, 2) for i in range(21)]  # −0,5 … +0,5 m in 5 cm steps
DIRECTIONS = ["øst", "nordøst", "nord", "nordvest", "vest", "sørvest", "sør", "sørøst"]


def _window(s: Surface, cell: float, gx0: float, gy0: float, nx: int, ny: int) -> np.ndarray:
    """Mean of `s` on the target grid (origin gx0, gy0; nx × ny cells of `cell`), NaN where empty."""
    out = np.full((ny, nx), np.nan, dtype=np.float64)
    c0 = max(0, int(math.floor((gx0 - s.x0) / s.cell)))
    c1 = min(s.nx, int(math.ceil((gx0 + nx * cell - s.x0) / s.cell)))
    r0 = max(0, int(math.floor((gy0 - s.y0) / s.cell)))
    r1 = min(s.ny, int(math.ceil((gy0 + ny * cell - s.y0) / s.cell)))
    if c1 <= c0 or r1 <= r0:
        return out
    sub = s.z[r0:r1, c0:c1].astype(np.float64)
    xc = s.x0 + (np.arange(c0, c1) + 0.5) * s.cell
    yc = s.y0 + (np.arange(r0, r1) + 0.5) * s.cell
    ix = np.floor((xc - gx0) / cell).astype(np.int64)
    iy = np.floor((yc - gy0) / cell).astype(np.int64)
    okx, oky = (ix >= 0) & (ix < nx), (iy >= 0) & (iy < ny)
    sub = sub[np.ix_(oky, okx)]
    idx = (iy[oky][:, None] * nx + ix[okx][None, :]).ravel()
    zf = sub.ravel()
    ok = np.isfinite(zf)
    s_ = np.bincount(idx[ok], weights=zf[ok], minlength=nx * ny)
    n_ = np.bincount(idx[ok], minlength=nx * ny)
    flat = out.ravel()
    has = n_ > 0
    flat[has] = s_[has] / n_[has]
    return flat.reshape(ny, nx)


def _direction(de: float, dn: float) -> str:
    ang = math.degrees(math.atan2(dn, de)) % 360
    return DIRECTIONS[int(((ang + 22.5) % 360) // 45)]


def _downsample(d: np.ndarray) -> tuple[list, int]:
    ny, nx = d.shape
    f = max(1, math.ceil(max(nx, ny) / MAP_MAX))
    py, px = (-ny) % f, (-nx) % f
    padded = np.pad(d, ((0, py), (0, px)), constant_values=np.nan)
    blocks = padded.reshape(padded.shape[0] // f, f, padded.shape[1] // f, f)
    with np.errstate(invalid="ignore"):
        cnt = np.isfinite(blocks).sum(axis=(1, 3))
        tot = np.nansum(blocks, axis=(1, 3))
        mean = np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)
    rows = [[None if not np.isfinite(v) else round(float(v), 2) for v in row] for row in mean[::-1]]  # north first
    return rows, f


def compare(new: Surface, ref: Surface) -> dict:
    """Statistics of new − reference over their overlap."""
    cell = max(new.cell, ref.cell)
    minx, maxx = max(new.x0, ref.x0), min(new.x0 + new.nx * new.cell, ref.x0 + ref.nx * ref.cell)
    miny, maxy = max(new.y0, ref.y0), min(new.y0 + new.ny * new.cell, ref.y0 + ref.ny * ref.cell)
    if maxx <= minx or maxy <= miny:
        return {"status": "no_overlap"}
    gx0, gy0 = math.floor(minx / cell) * cell, math.floor(miny / cell) * cell
    nx, ny = int(math.ceil((maxx - gx0) / cell)), int(math.ceil((maxy - gy0) / cell))
    a = _window(new, cell, gx0, gy0, nx, ny)
    k = SHIFT_CELLS
    bpad = _window(ref, cell, gx0 - k * cell, gy0 - k * cell, nx + 2 * k, ny + 2 * k)
    b = bpad[k:k + ny, k:k + nx]
    valid = np.isfinite(a) & np.isfinite(b)
    n = int(valid.sum())
    new_cells = int(np.isfinite(a).sum())
    if n < 10:
        return {"status": "no_overlap"}
    d = np.where(valid, a - b, np.nan)
    dv = d[valid]
    absd = np.abs(dv)
    mean, std = float(dv.mean()), float(dv.std())
    imax = int(np.argmax(absd))
    stats = {
        "cell_m": cell, "cells": n, "area_m2": round(n * cell * cell, 1),
        "overlap_share": round(n / max(new_cells, 1), 3),
        "mean_m": round(mean, 3), "median_m": round(float(np.median(dv)), 3), "std_m": round(std, 3),
        "rmse_m": round(float(np.sqrt((dv ** 2).mean())), 3), "p95_abs_m": round(float(np.percentile(absd, 95)), 3),
        "max_m": round(float(dv[imax]), 3),
        "area_over_m2": {str(t): round(float((absd > t).sum()) * cell * cell, 1) for t in THRESHOLDS},
    }

    # Horizontal shift: does the new data fit better when moved by whole cells? Spread after removing the
    # mean is used, so a pure height offset does not count. Up to 200 000 cells are sampled for speed.
    iy, ix = np.nonzero(valid)
    if len(iy) > 200_000:
        pick = np.random.default_rng(0).choice(len(iy), 200_000, replace=False)
        iy, ix = iy[pick], ix[pick]
    av = a[iy, ix]
    best = (0, 0, float(np.std(av - b[iy, ix])))
    std0 = best[2]
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            if dx == 0 and dy == 0:
                continue
            bv = bpad[iy + k + dy, ix + k + dx]
            ok = np.isfinite(bv)
            if ok.sum() < 0.5 * len(iy):
                continue
            s = float(np.std(av[ok] - bv[ok]))
            if s < best[2]:
                best = (dx, dy, s)
    dx, dy, sbest = best
    de, dn = -dx * cell, -dy * cell
    suspected = (dx, dy) != (0, 0) and std0 > 0.03 and sbest < 0.6 * std0
    stats["shift"] = {"suspected": bool(suspected), "east_m": de, "north_m": dn,
                      "distance_m": round(math.hypot(de, dn), 2), "direction": _direction(de, dn) if suspected else "",
                      "std_before_m": round(std0, 3), "std_after_m": round(sbest, 3)}

    rows, f = _downsample(d)
    stats["map"] = {"values": rows, "cell_m": cell * f, "x0": gx0, "y0": gy0,
                    "width_m": nx * cell, "height_m": ny * cell}
    inside = dv[(dv >= HIST_EDGES[0]) & (dv < HIST_EDGES[-1])]
    counts, _ = np.histogram(inside, bins=HIST_EDGES)
    stats["hist"] = {"edges": HIST_EDGES, "counts": [int(c) for c in counts],
                     "below": int((dv < HIST_EDGES[0]).sum()), "above": int((dv >= HIST_EDGES[-1]).sum())}
    stats["status"] = "done"
    return stats
