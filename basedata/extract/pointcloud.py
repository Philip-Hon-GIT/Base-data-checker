"""Point clouds (.las, .laz): header metadata, plus point access for height comparisons.

LAZ files keep an uncompressed header, so CRS, extent, counts and dates come out without any library.
Point coordinates are read directly from uncompressed LAS (memory-mapped); LAZ needs laspy with lazrs.
"""

from __future__ import annotations

import struct
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from .. import crs as crslib
from ..footprint import from_xy
from .common import FileMetadata

try:
    import laspy  # type: ignore
except ImportError:  # pragma: no cover
    laspy = None

_SAMPLE_POINTS = 50000


def _creation_date(year: int, doy: int) -> str | None:
    if not year or not doy or year < 1990:
        return None
    try:
        return (date(year, 1, 1) + timedelta(days=doy - 1)).isoformat()
    except ValueError:
        return None


def read_header(path: Path) -> dict | None:
    """The LAS public header and projection records, or None when the file is not LAS/LAZ."""
    with path.open("rb") as f:
        head = f.read(375)
        if head[:4] != b"LASF":
            return None
        h: dict = {}
        h["global_encoding"] = struct.unpack_from("<H", head, 6)[0]
        h["vmaj"], h["vmin"] = head[24], head[25]
        h["system_id"] = head[26:58].split(b"\x00")[0].decode("ascii", "replace").strip()
        h["software"] = head[58:90].split(b"\x00")[0].decode("ascii", "replace").strip()
        h["doy"], h["year"], h["header_size"] = struct.unpack_from("<HHH", head, 90)
        h["offset_points"], h["n_vlr"] = struct.unpack_from("<II", head, 96)
        fmt_raw, h["rec_len"], legacy = struct.unpack_from("<BHI", head, 104)
        h["fmt"] = fmt_raw & 0x3F
        h["compressed"] = bool(fmt_raw & 0x80) or path.suffix.lower() == ".laz"
        h["scale"] = struct.unpack_from("<3d", head, 131)
        h["offset"] = struct.unpack_from("<3d", head, 155)
        maxx, minx, maxy, miny, maxz, minz = struct.unpack_from("<6d", head, 179)
        h["bounds"] = (minx, miny, minz, maxx, maxy, maxz)
        count = legacy
        if (h["vmaj"], h["vmin"]) >= (1, 4) and len(head) >= 255:
            count = struct.unpack_from("<Q", head, 247)[0] or legacy
        h["count"] = int(count)
        f.seek(h["header_size"])
        h["wkt"], h["geokeys"] = None, []
        for _ in range(h["n_vlr"]):
            vh = f.read(54)
            if len(vh) < 54:
                break
            user = vh[2:18].split(b"\x00")[0].decode("ascii", "replace")
            rec_id, length = struct.unpack_from("<HH", vh, 18)
            payload = f.read(length)
            if user == "LASF_Projection" and rec_id == 2112:
                h["wkt"] = payload.split(b"\x00")[0].decode("utf-8", "replace")
            elif user == "LASF_Projection" and rec_id == 34735:
                h["geokeys"] = list(struct.unpack(f"<{length // 2}H", payload[: length // 2 * 2]))
            elif user == "laszip encoded":
                h["compressed"] = True
    return h


def points(path: Path, h: dict, max_points: int = 6_000_000):
    """(x, y, z, classification) as numpy arrays, thinned evenly to at most max_points; None if unreadable."""
    if h["compressed"]:
        if laspy is None:
            return None
        las = laspy.read(path)
        step = max(1, len(las.points) // max_points)
        return (np.asarray(las.x)[::step], np.asarray(las.y)[::step], np.asarray(las.z)[::step],
                np.asarray(las.classification)[::step])
    pos = 16 if h["fmt"] >= 6 else 15
    dt = np.dtype({"names": ["X", "Y", "Z", "c"], "formats": ["<i4", "<i4", "<i4", "u1"],
                   "offsets": [0, 4, 8, pos], "itemsize": h["rec_len"]})
    mm = np.memmap(path, dtype=dt, mode="r", offset=h["offset_points"], shape=(h["count"],))
    sub = mm[:: max(1, h["count"] // max_points)]
    (sx, sy, sz), (ox, oy, oz) = h["scale"], h["offset"]
    cls = np.asarray(sub["c"]) if h["fmt"] >= 6 else np.asarray(sub["c"]) & 0x1F
    return (sub["X"] * sx + ox, sub["Y"] * sy + oy, sub["Z"] * sz + oz, cls)


def read(path: Path) -> FileMetadata:
    """Read LAS/LAZ header metadata: version, points, extent, density, CRS, date, classes."""
    md = FileMetadata(format="LAZ" if path.suffix.lower() == ".laz" else "LAS")
    h = read_header(path)
    if h is None:
        md.note("Ikke en LAS/LAZ-fil (mangler LASF-signatur).")
        return md
    minx, miny, minz, maxx, maxy, maxz = h["bounds"]
    md.format_version = f"{h['vmaj']}.{h['vmin']}"
    md.count, md.count_label = h["count"], "points"
    md.extent = {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}
    md.details.update({"point_format": h["fmt"], "z_range": [round(minz, 2), round(maxz, 2)],
                       "system_identifier": h["system_id"], "generating_software": h["software"],
                       "compressed": h["compressed"], "wkt_flag": bool(h["global_encoding"] & 16)})
    area = (maxx - minx) * (maxy - miny)
    if area > 0:
        md.quality["density_pts_per_m2"] = round(h["count"] / area, 2)
        md.quality["note"] = "tetthet over omsluttende rektangel; reell dekning kan være mindre"
    md.quality["coordinate_resolution_m"] = round(h["scale"][0], 4)

    if h["wkt"]:
        md.horizontal_epsg, md.height_reference = crslib.parse_wkt(h["wkt"])
        md.details["crs_from"] = "WKT-post"
    elif h["geokeys"]:
        gk = h["geokeys"]
        for n in range(gk[3]):
            key, loc, _, value = gk[4 + n * 4: 8 + n * 4]
            if key == 3072 and loc == 0:
                md.horizontal_epsg = value
            if key == 4096 and loc == 0 and value in crslib.VERTICAL:
                md.height_reference = crslib.VERTICAL[value]
        md.details["crs_from"] = "GeoKeys-post"
    if md.horizontal_epsg is None:
        md.note("Ingen koordinatsystem i LAS-hodet (verken WKT eller GeoKeys).")
    if md.height_reference is None:
        md.note("Ingen høydesystem i LAS-hodet.")

    created = _creation_date(h["year"], h["doy"])
    if created:
        md.data_date, md.data_date_kind = created, "opprettelsesdato i fila – ofte prosesseringsdato"

    pts = None
    try:
        pts = points(path, h, max_points=_SAMPLE_POINTS)
        if pts is not None and len(pts[0]):
            md.footprint = from_xy(pts[0], pts[1], "punktene i fila", min_cell=0.5)
    except Exception as exc:  # pragma: no cover
        md.note(f"Kunne ikke lese punkter: {exc}")
    if pts is not None:
        md.quality["classes_sampled"] = dict(sorted(Counter(int(c) for c in pts[3]).items()))
    elif h["compressed"]:
        md.note("Klassekoder og høydesammenligning for LAZ krever laspy med lazrs.")
    return md
