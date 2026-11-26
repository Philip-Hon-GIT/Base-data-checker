"""Height surfaces: a regular grid of mean heights built from a terrain raster or a point cloud.

Every terrain model and point cloud gets one surface when it is registered. Surfaces are stored as
float32 bytes in their own GridFS bucket (basedata_surfaces) and used to compare new data with
approved earlier data. Grid cells are aligned to whole multiples of the cell size, so surfaces with
the same cell size line up exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from basedata.core import db as dblib

LADDER = [0.5, 1, 2, 5, 10, 20, 50, 100, 200]
MAX_CELLS = 9_000_000
BUCKET = "basedata_surfaces"


@dataclass
class Surface:
    """Mean heights on a grid. Row 0 is the southern edge; NaN where there is no data."""

    x0: float
    y0: float
    cell: float
    z: np.ndarray  # shape (ny, nx), float32
    source: str

    @property
    def nx(self) -> int:
        return int(self.z.shape[1])

    @property
    def ny(self) -> int:
        return int(self.z.shape[0])

    def info(self) -> dict:
        """Everything but the heights, for the file document."""
        valid = int(np.isfinite(self.z).sum())
        return {"x0": self.x0, "y0": self.y0, "cell": self.cell, "nx": self.nx, "ny": self.ny,
                "valid_cells": valid, "source": self.source}


def pick_cell(native: float, ext: dict) -> float:
    """The smallest ladder cell at least as coarse as the data that keeps the grid under MAX_CELLS."""
    w, h = ext["maxx"] - ext["minx"], ext["maxy"] - ext["miny"]
    for c in LADDER:
        if c >= native * 0.999 and (w / c + 2) * (h / c + 2) <= MAX_CELLS:
            return float(c)
    return float(LADDER[-1])


def _grid(xc: np.ndarray, yc: np.ndarray, z: np.ndarray, cell: float, source: str) -> Surface | None:
    ok = np.isfinite(z) & np.isfinite(xc) & np.isfinite(yc)
    if not ok.any():
        return None
    xc, yc, z = xc[ok], yc[ok], z[ok]
    x0 = math.floor(float(xc.min()) / cell) * cell
    y0 = math.floor(float(yc.min()) / cell) * cell
    ix = np.floor((xc - x0) / cell).astype(np.int64)
    iy = np.floor((yc - y0) / cell).astype(np.int64)
    nx, ny = int(ix.max()) + 1, int(iy.max()) + 1
    idx = iy * nx + ix
    s = np.bincount(idx, weights=z, minlength=nx * ny)
    n = np.bincount(idx, minlength=nx * ny)
    out = np.full(nx * ny, np.nan, dtype=np.float32)
    has = n > 0
    out[has] = (s[has] / n[has]).astype(np.float32)
    return Surface(x0, y0, cell, out.reshape(ny, nx), source)


def from_raster(path: Path, md: dict) -> Surface | None:
    """Surface from a single-band elevation raster (GeoTIFF)."""
    if (md.get("details") or {}).get("raster_kind") != "elevation grid" or not md.get("extent"):
        return None
    import tifffile

    arr = np.asarray(tifffile.imread(path), dtype=np.float32)
    if arr.ndim != 2:
        return None
    h, w = arr.shape
    ext = md["extent"]
    px, py = (ext["maxx"] - ext["minx"]) / w, (ext["maxy"] - ext["miny"]) / h
    nodata = (md.get("quality") or {}).get("nodata")
    try:
        if nodata not in (None, ""):
            arr = np.where(arr == float(nodata), np.nan, arr)
    except ValueError:
        pass
    cell = pick_cell(max(px, py), ext)
    xc = ext["minx"] + (np.arange(w) + 0.5) * px
    yc = ext["maxy"] - (np.arange(h) + 0.5) * py
    x0 = math.floor(float(xc.min()) / cell) * cell
    y0 = math.floor(float(yc.min()) / cell) * cell
    ix = np.floor((xc - x0) / cell).astype(np.int64)
    iy = np.floor((yc - y0) / cell).astype(np.int64)
    nx, ny = int(ix.max()) + 1, int(iy.max()) + 1
    idx = (iy[:, None] * nx + ix[None, :]).ravel()
    zf = arr.ravel()
    ok = np.isfinite(zf)
    s = np.bincount(idx[ok], weights=zf[ok], minlength=nx * ny)
    n = np.bincount(idx[ok], minlength=nx * ny)
    out = np.full(nx * ny, np.nan, dtype=np.float32)
    has = n > 0
    out[has] = (s[has] / n[has]).astype(np.float32)
    return Surface(x0, y0, cell, out.reshape(ny, nx), "terrengmodell")


def from_point_cloud(path: Path, md: dict) -> Surface | None:
    """Surface from LAS/LAZ ground points (class 2), or from all points when nothing is classified."""
    from basedata.indata.extract import pointcloud

    h = pointcloud.read_header(path)
    if h is None:
        return None
    pts = pointcloud.points(path, h)
    if pts is None:
        return None
    x, y, z, cls = pts
    ground = cls == 2
    source = "bakkepunkter (klasse 2)"
    if ground.sum() < 0.05 * len(cls):
        ground = np.ones(len(cls), dtype=bool)
        source = "alle punkter (ingen bakkeklasse)"
    x, y, z = np.asarray(x)[ground], np.asarray(y)[ground], np.asarray(z)[ground]
    if len(x) == 0:
        return None
    ext = {"minx": float(x.min()), "miny": float(y.min()), "maxx": float(x.max()), "maxy": float(y.max())}
    area = max((ext["maxx"] - ext["minx"]) * (ext["maxy"] - ext["miny"]), 1.0)
    density = len(x) / area
    cell = pick_cell(max(0.5, math.sqrt(2.0 / max(density, 1e-6))), ext)
    return _grid(x, y, z.astype(np.float64), cell, source)


def build(path: Path, md: dict) -> Surface | None:
    """A surface for terrain rasters and point clouds; None for anything else. Never raises."""
    try:
        ext = path.suffix.lower()
        if ext in (".las", ".laz"):
            return from_point_cloud(path, md)
        if ext in (".tif", ".tiff"):
            return from_raster(path, md)
    except Exception:  # a surface is a bonus; the file is still registered without it
        return None
    return None


def save(db, s: Surface, filename: str) -> dict:
    """Store the heights in GridFS and return the info to keep on the file document."""
    bucket = dblib.gridfs_bucket(db, BUCKET)
    info = s.info()
    info["id"] = bucket.upload_from_stream(f"{filename}.surface", s.z.astype("<f4").tobytes(), metadata=info)
    return info


def load(db, info: dict | None) -> Surface | None:
    """Read a stored surface back, or None."""
    if not info or not info.get("id"):
        return None
    try:
        stream = dblib.gridfs_bucket(db, BUCKET).open_download_stream(info["id"])
        data = stream.read()
        stream.close()
    except Exception:
        return None
    z = np.frombuffer(data, dtype="<f4").reshape(info["ny"], info["nx"])
    return Surface(info["x0"], info["y0"], info["cell"], z, info.get("source", ""))


def delete(db, info: dict | None) -> None:
    """Remove a stored surface (when the file is replaced)."""
    if info and info.get("id"):
        try:
            dblib.gridfs_bucket(db, BUCKET).delete(info["id"])
        except Exception:
            pass
