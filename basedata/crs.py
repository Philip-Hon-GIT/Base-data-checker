"""Coordinate reference systems used in Norway: names, parsing, transformations and plausibility checks.

Uses pyproj when it is installed. Without it, a built-in Transverse Mercator implementation (Snyder's
formulas on GRS80) covers EUREF89/WGS84 UTM and NTM. That is accurate to well under a metre inside a
zone, which is plenty for plausibility and coverage checks; it is not meant for converting data.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

try:  # optional: exact transformations for every CRS when available
    import pyproj  # type: ignore
except ImportError:  # pragma: no cover - depends on the environment
    pyproj = None


@dataclass(frozen=True)
class CrsInfo:
    """One coordinate reference system the checker knows by name."""

    epsg: int
    name: str
    kind: str  # "projected" or "geographic"
    lon0: float | None = None
    k0: float = 0.9996
    false_easting: float = 500000.0
    false_northing: float = 0.0
    builtin_math: bool = True  # False when only pyproj can transform it
    lat0: float = 0.0


def _build_registry() -> dict[int, CrsInfo]:
    """All horizontal CRSs commonly met in Norwegian base data."""
    reg: dict[int, CrsInfo] = {}
    for zone in range(31, 37):
        lon0 = zone * 6 - 183
        reg[25800 + zone] = CrsInfo(25800 + zone, f"EUREF89 UTM{zone}", "projected", lon0)
        reg[32600 + zone] = CrsInfo(32600 + zone, f"WGS 84 UTM{zone}", "projected", lon0)
        reg[23000 + zone] = CrsInfo(23000 + zone, f"ED50 UTM{zone}", "projected", lon0, builtin_math=False)
    for zone in range(5, 31):
        reg[5100 + zone] = CrsInfo(5100 + zone, f"EUREF89 NTM{zone}", "projected", zone + 0.5, 1.0, 100000.0, 1000000.0,
                                   lat0=58.0)
    for axis, code in enumerate(range(27391, 27399), start=1):
        reg[code] = CrsInfo(code, f"NGO1948 akse {axis}", "projected", builtin_math=False)
    reg[4258] = CrsInfo(4258, "EUREF89 geografisk", "geographic")
    reg[4326] = CrsInfo(4326, "WGS 84 geografisk", "geographic")
    return reg


REGISTRY: dict[int, CrsInfo] = _build_registry()

# Vertical reference systems (height datums), by EPSG code of the vertical CRS.
VERTICAL = {5941: "NN2000", 5776: "NN1954"}

# CRSs tried when a file's coordinates do not fit its declared CRS.
CANDIDATES: list[int] = [25832, 25833, 25835] + list(range(5105, 5131))

NORWAY_BBOX = (4.0, 57.8, 31.5, 71.3)  # lon_min, lat_min, lon_max, lat_max (mainland and coast)

# GRS80 ellipsoid (ETRS89 / EUREF89); WGS 84 differs by far less than the accuracy needed here.
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)


def crs_name(epsg: int | None) -> str:
    """Readable name for an EPSG code, e.g. 'EUREF89 UTM32 (EPSG:25832)'."""
    if epsg is None:
        return "Ukjent"
    info = REGISTRY.get(epsg)
    return f"{info.name} (EPSG:{epsg})" if info else f"EPSG:{epsg}"


def short_name(epsg: int | None) -> str:
    """Name without the code, e.g. 'EUREF89 UTM32'."""
    if epsg is None:
        return "Ukjent"
    info = REGISTRY.get(epsg)
    return info.name if info else f"EPSG:{epsg}"


def crs_dict(epsg: int | None) -> dict | None:
    """The {epsg, name} pair stored in the register."""
    if epsg is None:
        return None
    return {"epsg": epsg, "name": crs_name(epsg)}


def normalize_height(text: str | None) -> str | None:
    """Turn the many spellings of a height datum into NN2000, NN1954, Ellipsoidisk or Lokal."""
    if not text:
        return None
    t = text.strip().upper().replace(" ", "")
    if "NN2000" in t or t == "5941":
        return "NN2000"
    if "NN1954" in t or "NN54" in t or t == "5776":
        return "NN1954"
    if "ELLIPS" in t or "EUREF89H" in t:
        return "Ellipsoidisk"
    if "LOKAL" in t or "LOCAL" in t:
        return "Lokal"
    return text.strip()


_EPSG_RE = re.compile(r"EPSG\s*(?::{1,2}|/0/|/)\s*(\d{4,5})", re.I)
_AUTH_RE = re.compile(r'(?:AUTHORITY|ID)\[\s*"EPSG"\s*,\s*"?(\d+)"?\s*\]', re.I)


def parse_crs(text: str | int | None) -> int | None:
    """Find the horizontal EPSG code in 'EPSG:25832', a URN, an OGC URL, a bare number or WKT."""
    if text is None:
        return None
    if isinstance(text, int):
        return text
    s = str(text).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if "[" in s:  # WKT
        return parse_wkt(s)[0]
    m = _EPSG_RE.search(s)
    return int(m.group(1)) if m else None


def parse_wkt(wkt: str) -> tuple[int | None, str | None]:
    """Return (horizontal EPSG, height reference) from WKT1/WKT2, including compound CRSs."""
    codes = [int(c) for c in _AUTH_RE.findall(wkt)]
    horizontal = [c for c in codes if c in REGISTRY]
    epsg = horizontal[-1] if horizontal else None
    if epsg is None:
        m = re.search(r"NTM[ _]zone[ _](\d{1,2})", wkt, re.I)
        if m:
            epsg = 5100 + int(m.group(1))
    if epsg is None:
        m = re.search(r"UTM[ _]zone[ _](\d{2})\s*N?", wkt, re.I)
        if m:
            zone = int(m.group(1))
            is_wgs = re.search(r"WGS[ _]?84\s*/\s*UTM", wkt, re.I) and not re.search(r"ETRS|EUREF", wkt, re.I)
            epsg = (32600 if is_wgs else 25800) + zone
    height = None
    if 5941 in codes or re.search(r"NN2000", wkt, re.I):
        height = "NN2000"
    elif 5776 in codes or re.search(r"NN54|NN1954", wkt, re.I):
        height = "NN1954"
    return epsg, height


# --- Transverse Mercator (Snyder, USGS Professional Paper 1395) ---------------------------------

def _meridian_arc(phi: float) -> float:
    e2, e4, e6 = _E2, _E2**2, _E2**3
    return _A * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )


def _tm_forward(lon: float, lat: float, info: CrsInfo) -> tuple[float, float]:
    phi, lam = math.radians(lat), math.radians(lon - info.lon0)
    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = _EP2 * math.cos(phi) ** 2
    a = math.cos(phi) * lam
    x = info.k0 * n * (a + (1 - t + c) * a**3 / 6 + (5 - 18 * t + t**2 + 72 * c - 58 * _EP2) * a**5 / 120)
    y = info.k0 * (
        _meridian_arc(phi) - _meridian_arc(math.radians(info.lat0))
        + n * math.tan(phi) * (a**2 / 2 + (5 - t + 9 * c + 4 * c**2) * a**4 / 24
                               + (61 - 58 * t + t**2 + 600 * c - 330 * _EP2) * a**6 / 720)
    )
    return x + info.false_easting, y + info.false_northing


def _tm_inverse(x: float, y: float, info: CrsInfo) -> tuple[float, float]:
    e2, e4, e6 = _E2, _E2**2, _E2**3
    m = _meridian_arc(math.radians(info.lat0)) + (y - info.false_northing) / info.k0
    mu = m / (_A * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
            + (151 * e1**3 / 96) * math.sin(6 * mu)
            + (1097 * e1**4 / 512) * math.sin(8 * mu))
    c1 = _EP2 * math.cos(phi1) ** 2
    t1 = math.tan(phi1) ** 2
    n1 = _A / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    r1 = _A * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = (x - info.false_easting) / (n1 * info.k0)
    phi = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * _EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * _EP2 - 3 * c1**2) * d**6 / 720
    )
    lam = (d - (1 + 2 * t1 + c1) * d**3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * _EP2 + 24 * t1**2) * d**5 / 120) / math.cos(phi1)
    return info.lon0 + math.degrees(lam), math.degrees(phi)


def to_lonlat(epsg: int, x: float, y: float) -> tuple[float, float] | None:
    """Convert a coordinate to longitude/latitude; None when it cannot be converted or is nonsense."""
    try:
        if pyproj is not None:
            tr = pyproj.Transformer.from_crs(epsg, 4326, always_xy=True)
            lon, lat = tr.transform(x, y)
        else:
            info = REGISTRY.get(epsg)
            if info is None or not info.builtin_math:
                return None
            if info.kind == "geographic":
                lon, lat = x, y
            else:
                lon, lat = _tm_inverse(x, y, info)
                if abs(lon - info.lon0) > 25:
                    return None
    except Exception:
        return None
    if not (math.isfinite(lon) and math.isfinite(lat)) or abs(lat) > 90 or abs(lon) > 180:
        return None
    return lon, lat


def from_lonlat(epsg: int, lon: float, lat: float) -> tuple[float, float] | None:
    """Convert longitude/latitude to the given CRS; None when it cannot be converted."""
    try:
        if pyproj is not None:
            tr = pyproj.Transformer.from_crs(4326, epsg, always_xy=True)
            return tr.transform(lon, lat)
        info = REGISTRY.get(epsg)
        if info is None or not info.builtin_math:
            return None
        if info.kind == "geographic":
            return lon, lat
        return _tm_forward(lon, lat, info)
    except Exception:
        return None


def transform(x: float, y: float, src: int, dst: int) -> tuple[float, float] | None:
    """Convert a coordinate between two CRSs via longitude/latitude."""
    if src == dst:
        return x, y
    ll = to_lonlat(src, x, y)
    return from_lonlat(dst, *ll) if ll else None


# --- Geometry helpers ------------------------------------------------------------------------------

def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def polygon_area(points: list[tuple[float, float]]) -> float:
    """Area of a simple polygon (shoelace formula)."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def _ensure_ccw(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    s = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))
    return points if s >= 0 else list(reversed(points))


def clip_polygon(subject: list[tuple[float, float]], clip: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sutherland–Hodgman: the part of `subject` inside the convex polygon `clip`."""
    clip = _ensure_ccw(clip)
    output = list(subject)
    for a, b in zip(clip, clip[1:] + clip[:1]):
        if not output:
            break
        inp, output = output, []

        def inside(p: tuple[float, float]) -> bool:
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

        def cross_point(p: tuple[float, float], q: tuple[float, float]) -> tuple[float, float]:
            x1, y1, x2, y2 = a[0], a[1], b[0], b[1]
            x3, y3, x4, y4 = p[0], p[1], q[0], q[1]
            den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if den == 0:
                return q
            px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
            py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
            return px, py

        for p, q in zip(inp[-1:] + inp[:-1], inp):
            if inside(q):
                if not inside(p):
                    output.append(cross_point(p, q))
                output.append(q)
            elif inside(p):
                output.append(cross_point(p, q))
    return output


def bbox_corners(ext: dict) -> list[tuple[float, float]]:
    """The four corners of an extent dict {minx, miny, maxx, maxy}, counter-clockwise."""
    return [(ext["minx"], ext["miny"]), (ext["maxx"], ext["miny"]),
            (ext["maxx"], ext["maxy"]), (ext["minx"], ext["maxy"])]


def extent_to_wgs84(ext: dict, epsg: int) -> dict | None:
    """GeoJSON polygon of an extent in WGS 84, for maps and 2dsphere indexes."""
    ring = []
    for x, y in bbox_corners(ext):
        ll = to_lonlat(epsg, x, y)
        if ll is None:
            return None
        ring.append([round(ll[0], 7), round(ll[1], 7)])
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def _center(ext: dict) -> tuple[float, float]:
    return (ext["minx"] + ext["maxx"]) / 2, (ext["miny"] + ext["maxy"]) / 2


def project_geometry(project: dict) -> dict | None:
    """Centre (lon, lat) and radius in km of a project's area polygon."""
    area = (project or {}).get("project_area") or {}
    pts = area.get("coordinates")
    epsg = parse_crs(area.get("crs") or project.get("horizontal_crs"))
    if not pts or not epsg:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    ext = {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}
    c = to_lonlat(epsg, *_center(ext))
    corner = to_lonlat(epsg, ext["minx"], ext["miny"])
    if not c or not corner:
        return None
    return {"lon": c[0], "lat": c[1], "radius_km": haversine_km(c[0], c[1], corner[0], corner[1]),
            "epsg": epsg, "points": [tuple(p) for p in pts]}


def plausibility(ext: dict | None, epsg: int | None, project: dict | None) -> dict:
    """Do the coordinates make sense for the declared CRS, and near the project?

    Returns a dict with: checked, declared_fits, distance_km, looks_local, candidates (CRSs under which
    the coordinates would land near the project) and a plain-language note.
    """
    result: dict = {"checked": False, "declared_fits": None, "distance_km": None,
                    "looks_local": False, "candidates": [], "note": ""}
    if not ext:
        result["note"] = "Ingen koordinater kunne leses fra fila."
        return result
    cx, cy = _center(ext)
    result["checked"] = True
    if abs(cx) < 100000 and abs(cy) < 100000:
        result["looks_local"] = True
    geo = project_geometry(project) if project else None

    def near(code: int) -> float | None:
        ll = to_lonlat(code, cx, cy)
        if ll is None:
            return None
        if geo:
            dist = haversine_km(ll[0], ll[1], geo["lon"], geo["lat"])
            return dist if dist <= geo["radius_km"] + 5 else None
        lon_min, lat_min, lon_max, lat_max = NORWAY_BBOX
        return 0.0 if lon_min <= ll[0] <= lon_max and lat_min <= ll[1] <= lat_max else None

    if epsg is not None:
        ll = to_lonlat(epsg, cx, cy)
        if ll is not None and geo:
            result["distance_km"] = round(haversine_km(ll[0], ll[1], geo["lon"], geo["lat"]), 1)
        result["declared_fits"] = near(epsg) is not None
    if geo:
        for code in CANDIDATES:
            if code == epsg:
                continue
            dist = near(code)
            if dist is not None:
                result["candidates"].append({"epsg": code, "name": crs_name(code), "distance_km": round(dist, 1)})
        result["candidates"].sort(key=lambda c: c["distance_km"])

    if result["looks_local"]:
        result["note"] = "Koordinatene er små tall og ser ut som et lokalt koordinatsystem."
    elif epsg is None:
        result["note"] = ("Koordinatsystem ukjent; koordinatene passer med " + ", ".join(c["name"] for c in result["candidates"])
                          if result["candidates"] else "Koordinatsystem ukjent, og koordinatene passer ikke med vanlige norske koordinatsystemer nær prosjektet.")
    elif result["declared_fits"]:
        result["note"] = f"Koordinatene passer med {crs_name(epsg)}" + (" i prosjektområdet." if geo else " innenfor Norge.")
    elif result["candidates"]:
        result["note"] = (f"Koordinatene passer ikke med {crs_name(epsg)} i prosjektområdet, men med "
                          f"{result['candidates'][0]['name']} – oppgitt koordinatsystem kan være feil.")
    else:
        where = (f"{str(result['distance_km']).replace('.', ',')} km fra prosjektet" if result["distance_km"] is not None
                 else "utenfor Norge")
        result["note"] = f"Med {crs_name(epsg)} havner dataene {where}."
    return result


def coverage(ext: dict | None, epsg: int | None, project: dict | None) -> float | None:
    """Share (0–1) of the project area covered by the file's extent, or None when unknown."""
    geo = project_geometry(project) if project else None
    if not ext or epsg is None or not geo:
        return None
    corners = []
    for x, y in bbox_corners(ext):
        p = transform(x, y, epsg, geo["epsg"])
        if p is None:
            return None
        corners.append(p)
    area_pts = geo["points"]
    total = polygon_area(area_pts)
    if total == 0:
        return None
    inter = clip_polygon(area_pts, corners)
    return round(min(1.0, polygon_area(inter) / total), 3) if len(inter) >= 3 else 0.0
