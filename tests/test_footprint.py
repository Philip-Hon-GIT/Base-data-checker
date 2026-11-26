"""Footprints: real geometry for vector data (points stay points, lines stay lines), outlines for dense data."""

import json
import sqlite3
import struct

from basedata import footprint
from basedata.extract import extract


def test_sosi_surfaces_are_polygons(samples):
    fp = extract(samples / "FKB_Bygning_2025.sos").footprint
    assert fp["kind"] == "features" and len(fp["polygons"]) == 40 and not fp["lines"] and not fp["points"]
    assert all(len(r) == 4 for r in fp["polygons"])                 # closing vertex dropped


def test_sosi_points_and_curves(tmp_path):
    p = tmp_path / "punkt_og_linje.sos"
    p.write_text("\n".join([
        ".HODE", "..TEGNSETT UTF-8", "..TRANSPAR", "...KOORDSYS 22", "...ORIGO-NØ 0 0", "...ENHET 0.01",
        ".PUNKT 1:", "..OBJTYPE Kum", "..NØH", "664100000 60100000 10000",
        ".PUNKT 2:", "..OBJTYPE Kum", "..NØH", "664105000 60105000 10000",
        ".KURVE 3:", "..OBJTYPE Vannledning", "..NØ", "664100000 60100000", "664105000 60105000", "664110000 60103000",
        ".FLATE 4:", "..OBJTYPE Bygning", "..REF :3", "..NØ", "664102000 60102000",
        ".SLUTT"]) + "\n", encoding="utf-8")
    fp = extract(p).footprint
    assert fp["kind"] == "features"
    assert fp["points"] == [[601000.0, 6641000.0], [601050.0, 6641050.0]]
    assert fp["lines"] == [[[601000.0, 6641000.0], [601050.0, 6641050.0], [601030.0, 6641100.0]]]
    assert fp["polygons"] == []                                      # a surface made of curves: the curves draw it


def test_dxf_points_and_lines(samples):
    fp = extract(samples / "Innmaaling_kummer.dxf").footprint
    assert fp["kind"] == "features" and len(fp["points"]) == 24 and len(fp["lines"]) == 10 and not fp["polygons"]


def test_dxf_closed_polyline_is_polygon(tmp_path):
    p = tmp_path / "grense.dxf"
    ent = ["0", "LWPOLYLINE", "8", "0", "90", "4", "70", "1"]
    for x, y in ((0, 0), (100, 0), (100, 50), (0, 50)):
        ent += ["10", str(x), "20", str(y)]
    ent += ["0", "TEXT", "8", "0", "10", "500", "20", "500", "1", "tekst"]
    p.write_text("\n".join(["0", "SECTION", "2", "ENTITIES", *ent, "0", "ENDSEC", "0", "EOF"]) + "\n")
    fp = extract(p).footprint
    assert fp["polygons"] == [[[0.0, 0.0], [100.0, 0.0], [100.0, 50.0], [0.0, 50.0]]]
    assert not fp["points"]                                          # text is not data


def test_geopackage_lines(samples):
    fp = extract(samples / "Ledninger_VA.gpkg").footprint
    assert fp["kind"] == "features" and len(fp["lines"]) == 40 and not fp["points"]


def test_geojson_typed(tmp_path):
    p = tmp_path / "data.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [10.8, 59.9]}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[10.8, 59.9], [10.81, 59.91]]}},
        {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[[[10.8, 59.9], [10.82, 59.9], [10.82, 59.92], [10.8, 59.9]]]]}},
    ]}))
    fp = extract(p).footprint
    assert len(fp["points"]) == 1 and len(fp["lines"]) == 1 and len(fp["polygons"]) == 1


def test_shapefile_points(tmp_path):
    p = tmp_path / "kummer.shp"
    recs = b""
    for k, (x, y) in enumerate(((601000.0, 6641000.0), (601020.0, 6641010.0)), start=1):
        body = struct.pack("<i2d", 1, x, y)
        recs += struct.pack(">2i", k, len(body) // 2) + body
    head = struct.pack(">i", 9994) + b"\0" * 20 + struct.pack(">i", (100 + len(recs)) // 2) + struct.pack("<2i", 1000, 1)
    head += struct.pack("<4d", 601000, 6641000, 601020, 6641010) + b"\0" * 32
    p.write_bytes(head + recs)
    fp = extract(p).footprint
    assert fp["points"] == [[601000.0, 6641000.0], [601020.0, 6641010.0]]


def test_dense_data_becomes_outline(samples):
    fp = extract(samples / "Laserdata_Nordby_2026_blokk1.las").footprint
    assert fp["kind"] == "outline" and fp["rings"]


def test_feature_budget_simplifies_then_falls_back():
    import math
    wiggly = [[i, 10 * math.sin(i / 3)] for i in range(4000)]
    fp = footprint.features([], [wiggly, [[p[0], p[1] + 50] for p in wiggly]], [], "test")
    assert fp["kind"] == "features" and fp["simplified_m"] > 0
    assert sum(len(l) for l in fp["lines"]) <= footprint.FEATURE_BUDGET
    many = [[[i, 0], [i, 1], [i + 0.5, 2]] for i in range(0, 20000, 2)]   # 10 000 tiny triangles
    assert footprint.features([], [], many, "test")["kind"] == "outline"
