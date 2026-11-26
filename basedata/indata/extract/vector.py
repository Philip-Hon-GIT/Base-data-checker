"""Vector data: GeoPackage, GeoJSON, Shapefile and GML — read without GDAL.

GeoPackage is SQLite, so its contents table already holds CRS, extent and a change date. Shapefile
headers hold the extent; the CRS comes from the .prj sidecar. GML is scanned for srsName and an
envelope. If pyogrio is installed it is used for any other vector format.
"""

from __future__ import annotations

import json
import re
import sqlite3
import struct
from datetime import date
from pathlib import Path

from basedata.indata import crs as crslib
from basedata.indata.footprint import features
from basedata.indata.extract.common import FileMetadata, iso_date, read_prj, sidecar

try:
    import pyogrio  # type: ignore
except ImportError:  # pragma: no cover
    pyogrio = None


def _union(a: dict | None, b: dict) -> dict:
    if a is None:
        return dict(b)
    return {"minx": min(a["minx"], b["minx"]), "miny": min(a["miny"], b["miny"]),
            "maxx": max(a["maxx"], b["maxx"]), "maxy": max(a["maxy"], b["maxy"])}


def _geoms() -> dict:
    return {"points": [], "lines": [], "polygons": []}


def _wkb_geoms(b: bytes, g: dict) -> None:
    """The points, lines and polygon rings of a WKB geometry (2D, Z, M, ZM; ISO and EWKB type codes)."""
    import struct

    def geom(o: int) -> int:
        bo = "<" if b[o] == 1 else ">"
        t = struct.unpack_from(bo + "I", b, o + 1)[0]
        o += 5
        ewkb_z, ewkb_m = bool(t & 0x80000000), bool(t & 0x40000000)
        if t & 0x20000000:
            o += 4
        t &= 0x0FFFFFFF
        base, dims = t % 1000, 2 + (t // 1000 in (1, 2)) + (t // 1000 == 3) * 2 + ewkb_z + ewkb_m
        fmt = bo + "d" * dims

        def pts(o, n):
            out = []
            for _ in range(n):
                v = struct.unpack_from(fmt, b, o)
                out.append([v[0], v[1]])
                o += 8 * dims
            return o, out

        if base == 1:
            o, out = pts(o, 1)
            g["points"] += out
            return o
        if base == 2:
            n = struct.unpack_from(bo + "I", b, o)[0]
            o, out = pts(o + 4, n)
            g["lines"].append(out)
            return o
        if base == 3:
            rings = struct.unpack_from(bo + "I", b, o)[0]
            o += 4
            for _ in range(rings):
                n = struct.unpack_from(bo + "I", b, o)[0]
                o, out = pts(o + 4, n)
                g["polygons"].append(out[:-1] if len(out) > 1 and out[0] == out[-1] else out)
            return o
        if base in (4, 5, 6, 7):
            n = struct.unpack_from(bo + "I", b, o)[0]
            o += 4
            for _ in range(n):
                o = geom(o)
            return o
        raise ValueError(f"WKB-type {t}")

    geom(0)


def _gpkg_geom(blob: bytes, g: dict) -> None:
    if not blob or blob[:2] != b"GP":
        return
    env = (blob[3] >> 1) & 0x07
    _wkb_geoms(blob[8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env, 0):], g)


def _footprint(g: dict) -> dict | None:
    return features(g["points"], g["lines"], g["polygons"], "geometriene i fila")


def _gpkg(path: Path, md: FileMetadata) -> None:
    md.format = "GeoPackage"
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT table_name, data_type, identifier, last_change, min_x, min_y, max_x, max_y, srs_id "
                           "FROM gpkg_contents").fetchall()
        srs = {r[0]: r[1:] for r in con.execute(
            "SELECT srs_id, organization, organization_coordsys_id, srs_name, definition FROM gpkg_spatial_ref_sys")}
        layers, epsgs, changes, total = [], set(), [], 0
        for table, kind, ident, last_change, x1, y1, x2, y2, srs_id in rows:
            n = None
            if kind == "features":
                try:
                    n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    total += n
                except sqlite3.Error:
                    pass
            layers.append({"name": table, "type": kind, "features": n, "srs_id": srs_id})
            org, code, _, definition = srs.get(srs_id, (None, None, None, None))
            epsg = int(code) if org and str(org).upper() == "EPSG" and code and int(code) > 0 else None
            if epsg is None and definition and definition != "undefined":
                epsg = crslib.parse_wkt(definition)[0]
            if epsg:
                epsgs.add(epsg)
            if None not in (x1, y1, x2, y2):
                md.extent = _union(md.extent, {"minx": x1, "miny": y1, "maxx": x2, "maxy": y2})
            if last_change:
                changes.append(iso_date(last_change))
        md.details["layers"] = layers
        md.count, md.count_label = total, "features"
        if len(epsgs) == 1:
            md.horizontal_epsg = epsgs.pop()
        elif len(epsgs) > 1:
            md.horizontal_epsg = sorted(epsgs)[0]
            md.note(f"Lagene bruker ulike koordinatsystemer: {', '.join(f'EPSG:{e}' for e in sorted(epsgs))}.")
        if changes:
            md.details["content_last_changed"] = max(c for c in changes if c)
            md.note("GeoPackage lagrer bare når innholdet sist ble endret, ikke når dataene ble samlet inn.")
        md.format_version = "GeoPackage 1.x"
        g = _geoms()
        try:
            for table, column in con.execute("SELECT table_name, column_name FROM gpkg_geometry_columns").fetchall():
                for (blob,) in con.execute(f'SELECT "{column}" FROM "{table}" LIMIT 20000'):
                    try:
                        _gpkg_geom(bytes(blob), g)
                    except Exception:  # one odd geometry must not stop the rest
                        continue
        except sqlite3.Error:
            pass
        md.footprint = _footprint(g)
    finally:
        con.close()


def _walk_coords(obj, xs: list[float], ys: list[float]) -> None:
    if isinstance(obj, (list, tuple)):
        if len(obj) >= 2 and all(isinstance(v, (int, float)) for v in obj[:2]):
            xs.append(float(obj[0]))
            ys.append(float(obj[1]))
        else:
            for item in obj:
                _walk_coords(item, xs, ys)


def _geojson_geom(geom: dict | None, g: dict) -> None:
    if not isinstance(geom, dict):
        return
    t, c = geom.get("type"), geom.get("coordinates")
    xy = lambda p: [float(p[0]), float(p[1])]  # noqa: E731
    try:
        if t == "Point":
            g["points"].append(xy(c))
        elif t == "MultiPoint":
            g["points"] += [xy(p) for p in c]
        elif t == "LineString":
            g["lines"].append([xy(p) for p in c])
        elif t == "MultiLineString":
            g["lines"] += [[xy(p) for p in l] for l in c]
        elif t == "Polygon":
            g["polygons"] += [[xy(p) for p in r] for r in c]
        elif t == "MultiPolygon":
            g["polygons"] += [[xy(p) for p in r] for poly in c for r in poly]
        elif t == "GeometryCollection":
            for sub in geom.get("geometries") or []:
                _geojson_geom(sub, g)
    except (TypeError, IndexError, ValueError):
        pass


def _geojson(path: Path, md: FileMetadata) -> None:
    md.format = "GeoJSON"
    data = json.loads(path.read_text(encoding="utf-8"))
    feats = data.get("features", []) if data.get("type") == "FeatureCollection" else [data]
    md.count, md.count_label = len(feats), "features"
    name = (data.get("crs") or {}).get("properties", {}).get("name")
    if name:
        md.horizontal_epsg = crslib.parse_crs(name)
    else:
        md.horizontal_epsg = 4326
        md.details["crs_from"] = "GeoJSON-standard (WGS 84, RFC 7946)"
    xs: list[float] = []
    ys: list[float] = []
    for feat in feats:
        _walk_coords((feat.get("geometry") or {}).get("coordinates"), xs, ys)
    if xs:
        md.extent = {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}
        g = _geoms()
        for feat in feats:
            _geojson_geom(feat.get("geometry"), g)
        md.footprint = _footprint(g)


def _shapefile(path: Path, md: FileMetadata) -> None:
    md.format = "Shapefile"
    with path.open("rb") as f:
        head = f.read(100)
    if struct.unpack(">i", head[:4])[0] != 9994:
        md.note("Ugyldig .shp-filhode.")
        return
    shape_type = struct.unpack("<i", head[32:36])[0]
    x1, y1, x2, y2 = struct.unpack("<4d", head[36:68])
    md.extent = {"minx": x1, "miny": y1, "maxx": x2, "maxy": y2}
    md.details["shape_type"] = shape_type
    read_prj(path, md)
    if md.horizontal_epsg is None:
        md.note("Ingen .prj-fil, så koordinatsystemet er ukjent.")
    dbf = sidecar(path, ".dbf")
    if dbf:
        with dbf.open("rb") as f:
            d = f.read(8)
        md.count, md.count_label = struct.unpack("<I", d[4:8])[0], "features"
        try:
            md.details["content_last_changed"] = date(1900 + d[1], d[2], d[3]).isoformat()
        except ValueError:
            pass
    try:
        md.footprint = _footprint(_shp_geoms(path))
    except (struct.error, OSError, ValueError):
        md.note("Klarte ikke å lese geometrien i shapefila.")
    for needed in (".shx", ".dbf"):
        if not sidecar(path, needed):
            md.note(f"Shapefila mangler {needed}-delen.")


def _shp_geoms(path: Path, limit: int = 20000) -> dict:
    """Points, lines and polygon rings from the .shp records (Z and M variants included)."""
    g = _geoms()
    data = path.read_bytes()
    o = 100
    for _ in range(limit):
        if o + 12 > len(data):
            break
        length = struct.unpack_from(">i", data, o + 4)[0] * 2
        rec, o = data[o + 8: o + 8 + length], o + 8 + length
        t = struct.unpack_from("<i", rec, 0)[0] if len(rec) >= 4 else 0
        if t in (1, 11, 21):
            g["points"].append(list(struct.unpack_from("<2d", rec, 4)))
        elif t in (8, 18, 28):
            n = struct.unpack_from("<i", rec, 36)[0]
            g["points"] += [list(struct.unpack_from("<2d", rec, 40 + 16 * k)) for k in range(n)]
        elif t in (3, 13, 23, 5, 15, 25):
            nparts, npts = struct.unpack_from("<2i", rec, 36)
            parts = list(struct.unpack_from(f"<{nparts}i", rec, 44)) + [npts]
            p0 = 44 + 4 * nparts
            for a, b in zip(parts[:-1], parts[1:]):
                ring = [list(struct.unpack_from("<2d", rec, p0 + 16 * k)) for k in range(a, b)]
                if t % 10 == 5:
                    g["polygons"].append(ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring)
                else:
                    g["lines"].append(ring)
    return g


def _gml(path: Path, md: FileMetadata) -> None:
    md.format = "GML"
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'srsName="([^"]+)"', text)
    if m:
        md.horizontal_epsg = crslib.parse_crs(m.group(1))
    lo = re.search(r"<gml:lowerCorner>([^<]+)</gml:lowerCorner>", text)
    up = re.search(r"<gml:upperCorner>([^<]+)</gml:upperCorner>", text)
    if lo and up:
        a, b = [float(v) for v in lo.group(1).split()[:2]], [float(v) for v in up.group(1).split()[:2]]
        md.extent = {"minx": a[0], "miny": a[1], "maxx": b[0], "maxy": b[1]}
    md.count = len(re.findall(r"<(?:gml:featureMember|wfs:member|gml:featureMembers)\b", text))
    md.count_label = "features"
    if md.horizontal_epsg is None:
        md.note("Fant ikke srsName i GML-fila.")


def read(path: Path) -> FileMetadata:
    """Read vector metadata for the supported formats."""
    md = FileMetadata(format="Vector")
    ext = path.suffix.lower()
    if ext == ".gpkg":
        _gpkg(path, md)
    elif ext in (".geojson", ".json"):
        _geojson(path, md)
    elif ext == ".shp":
        _shapefile(path, md)
    elif ext == ".gml":
        _gml(path, md)
    elif pyogrio is not None:
        info = pyogrio.read_info(path)
        md.format = info.get("driver") or "Vector"
        md.horizontal_epsg = crslib.parse_crs(info.get("crs"))
        b = info.get("total_bounds")
        if b is not None:
            md.extent = {"minx": b[0], "miny": b[1], "maxx": b[2], "maxy": b[3]}
        md.count, md.count_label = info.get("features"), "features"
    else:
        md.note(f"Lesing av {ext} krever pyogrio, som ikke er installert.")
    return md
