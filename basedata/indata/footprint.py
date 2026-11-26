"""The real footprint of a data set: where the data actually is, not just its bounding box.

Coordinates from the file (points, vertices, valid raster cells) are put on an occupancy grid, the grid is
widened by one cell so nearby features join up, and the outline of the occupied cells is traced and
simplified. A handful of scattered coordinates (boreholes, manholes, model placement points) is kept as
points instead. Result, in the file's own coordinate system:

    {"kind": "features", "points": [[x, y], ...], "lines": [[[x, y], ...], ...], "polygons": [[[x, y], ...], ...]}
        the real geometry of vector data (points as points, lines as lines), simplified to a vertex budget
    {"kind": "outline", "rings": [[[x, y], ...], ...], "cell": 25.0, "source": "..."}
        the outline of dense data (point clouds, rasters) or of vector data too big to draw
    {"kind": "points", "points": [[x, y], ...], "source": "..."}
    {"kind": "box", "rings": [[4 corners]], "source": "..."}
"""

from __future__ import annotations

import math

import numpy as np

MAX_CELLS = 140          # grid cells along the longest side
MAX_POINTS = 150         # at or below this many coordinates, keep them as points
MAX_VERTICES = 1500      # total vertices kept across all rings
FEATURE_BUDGET = 5000    # vertices kept for real geometry before falling back to an outline


def features(points: list, lines: list, polygons: list, source: str) -> dict | None:
    """Real geometry for vector data. Lines and polygons are simplified until they fit the vertex budget;
    if they still do not, the outline of all coordinates is used instead."""
    pts = [[round(p[0], 2), round(p[1], 2)] for p in points if _finite(p)]
    ln = [[p for p in l if _finite(p)] for l in lines]
    pg = [[p for p in r if _finite(p)] for r in polygons]
    ln = [l for l in ln if len(l) >= 2]
    pg = [r for r in pg if len(r) >= 3]
    allc = pts + [p for l in ln for p in l] + [p for r in pg for p in r]
    if not allc:
        return None
    xs, ys = [p[0] for p in allc], [p[1] for p in allc]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    if len(pts) > 3000:
        step = len(pts) / 3000
        pts = [pts[int(k * step)] for k in range(3000)]
    tol = 0.0
    for _ in range(8):
        n = len(pts) + sum(len(l) for l in ln) + sum(len(r) for r in pg)
        if n <= FEATURE_BUDGET:
            break
        tol = span / 2000 if tol == 0 else tol * 2.5
        ln = [_dp_open(l, tol) for l in ln]
        kept = []
        for r in pg:
            q = _dp_open(r + [r[0]], tol)[:-1]
            if len(q) >= 3:
                kept.append(q)
            else:  # a surface smaller than the tolerance is still there: keep it as a point
                pts.append([round(sum(v[0] for v in r) / len(r), 2), round(sum(v[1] for v in r) / len(r), 2)])
        pg = kept
    else:
        return from_xy(xs, ys, source)
    if len(pts) + sum(len(l) for l in ln) + sum(len(r) for r in pg) > FEATURE_BUDGET:
        return from_xy(xs, ys, source)
    rnd = lambda arr: [[round(p[0], 2), round(p[1], 2)] for p in arr]  # noqa: E731
    return {"kind": "features", "points": pts, "lines": [rnd(l) for l in ln], "polygons": [rnd(r) for r in pg],
            "source": source, **({"simplified_m": round(tol, 2)} if tol else {})}


def _finite(p) -> bool:
    return len(p) >= 2 and math.isfinite(p[0]) and math.isfinite(p[1])


def _dp_open(pts: list, tol: float) -> list:
    """Douglas–Peucker for an open polyline in map units (iterative)."""
    if len(pts) <= 2:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a][:2], pts[b][:2]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-9
        best, idx = -1.0, None
        for k in range(a + 1, b):
            d = abs(dy * pts[k][0] - dx * pts[k][1] + x2 * y1 - y2 * x1) / L
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def box(ext: dict, source: str = "utstrekning") -> dict:
    return {"kind": "box", "source": source,
            "rings": [[[ext["minx"], ext["miny"]], [ext["maxx"], ext["miny"]], [ext["maxx"], ext["maxy"]], [ext["minx"], ext["maxy"]]]]}


def from_xy(xs, ys, source: str, min_cell: float = 1.0) -> dict | None:
    """Footprint from coordinates (any number; large inputs are sampled)."""
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size == 0:
        return None
    if x.size <= MAX_POINTS:
        pts = np.unique(np.round(np.stack([x, y], axis=1), 2), axis=0)
        return {"kind": "points", "points": pts.tolist(), "source": source}
    if x.size > 400_000:
        idx = np.random.default_rng(0).choice(x.size, 400_000, replace=False)
        x, y = x[idx], y[idx]
    span = max(x.max() - x.min(), y.max() - y.min(), min_cell)
    cell = max(min_cell, span / MAX_CELLS)
    x0, y0 = x.min() - cell, y.min() - cell
    nx = int((x.max() - x0) / cell) + 2
    ny = int((y.max() - y0) / cell) + 2
    grid = np.zeros((ny, nx), dtype=bool)
    grid[((y - y0) / cell).astype(int), ((x - x0) / cell).astype(int)] = True
    return from_mask(grid, x0, y0, cell, source, grow=1)


def from_mask(mask: np.ndarray, x0: float, y0: float, cell: float, source: str, grow: int = 0) -> dict | None:
    """Footprint from a boolean grid (row 0 = southern edge) with lower-left corner (x0, y0)."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return None
    while max(m.shape) > MAX_CELLS * 2:  # coarsen big rasters first
        h, w = (m.shape[0] + 1) // 2 * 2, (m.shape[1] + 1) // 2 * 2
        p = np.zeros((h, w), dtype=bool)
        p[: m.shape[0], : m.shape[1]] = m
        m = p.reshape(h // 2, 2, w // 2, 2).any(axis=(1, 3))
        cell *= 2
    m = np.pad(m, 1 + grow)
    x0, y0 = x0 - (1 + grow) * cell, y0 - (1 + grow) * cell
    for _ in range(grow):
        g = m.copy()
        g[1:, :] |= m[:-1, :]
        g[:-1, :] |= m[1:, :]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        m = g
    rings = _trace(m)
    if not rings:
        return None
    rings.sort(key=lambda r: -abs(_area(r)))
    out, budget = [], MAX_VERTICES
    for r in rings[:80]:
        r = _simplify(r, 0.6)
        if len(r) < 3 or budget <= 0:
            continue
        budget -= len(r)
        out.append([[round(x0 + i * cell, 2), round(y0 + j * cell, 2)] for i, j in r])
    return {"kind": "outline", "rings": out, "cell": round(cell, 2), "source": source}


def _trace(m: np.ndarray) -> list[list[tuple[int, int]]]:
    """Boundary rings of the occupied cells, as grid-vertex coordinates (counter-clockwise outer rings)."""
    ny, nx = m.shape
    nxt: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def edge(a, b):
        nxt.setdefault(a, []).append(b)

    ys, xs = np.nonzero(m)
    for j, i in zip(ys.tolist(), xs.tolist()):
        if j == 0 or not m[j - 1, i]:
            edge((i, j), (i + 1, j))              # bottom, left to right
        if i == nx - 1 or not m[j, i + 1]:
            edge((i + 1, j), (i + 1, j + 1))      # right, upwards
        if j == ny - 1 or not m[j + 1, i]:
            edge((i + 1, j + 1), (i, j + 1))      # top, right to left
        if i == 0 or not m[j, i - 1]:
            edge((i, j + 1), (i, j))              # left, downwards
    rings = []
    while nxt:
        start = next(iter(nxt))
        ring, cur = [start], start
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            b = outs.pop()
            if not outs:
                del nxt[cur]
            if b == start:
                break
            ring.append(b)
            cur = b
        if len(ring) >= 4:
            rings.append(_collinear(ring))
    return rings


def _collinear(r):
    out = []
    n = len(r)
    for k in range(n):
        a, b, c = r[k - 1], r[k], r[(k + 1) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) != 0:
            out.append(b)
    return out


def _area(r) -> float:
    return sum(r[k - 1][0] * r[k][1] - r[k][0] * r[k - 1][1] for k in range(len(r))) / 2


def _simplify(r, tol: float):
    """Douglas–Peucker on a closed ring (tolerance in grid cells)."""
    if len(r) <= 8:
        return r
    pts = r + [r[0]]

    def dp(a, b):
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-9
        best, idx = -1.0, None
        for k in range(a + 1, b):
            d = abs(dy * pts[k][0] - dx * pts[k][1] + x2 * y1 - y2 * x1) / L
            if d > best:
                best, idx = d, k
        if idx is None or best <= tol:
            return [pts[a]]
        return dp(a, idx) + dp(idx, b)

    half = len(pts) // 2
    return dp(0, half) + dp(half, len(pts) - 1)
