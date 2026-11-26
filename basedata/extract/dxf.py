"""DXF drawings and survey files: header variables, layers, entity counts and extent.

ASCII DXF is plain text, so it is parsed directly. DWG must be converted to DXF first (for example
with the free ODA File Converter). DXF almost never carries a coordinate system, so expect a question
to the uploader.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from ..footprint import features
from .common import FileMetadata

_UNITS = {0: "uten enhet", 1: "tommer", 2: "fot", 4: "millimeter", 5: "centimeter", 6: "meter", 7: "kilometer"}
_VERSIONS = {"AC1009": "R12", "AC1015": "2000", "AC1018": "2004", "AC1021": "2007", "AC1024": "2010",
             "AC1027": "2013", "AC1032": "2018"}


def read(path: Path) -> FileMetadata:
    """Read a DXF's units, layers, entities and extent."""
    md = FileMetadata(format="DXF")
    raw = path.read_bytes()
    if raw.startswith(b"AutoCAD Binary DXF"):
        md.note("Binær DXF støttes ikke; lagre tegningen som ASCII-DXF.")
        return md
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    lines = [ln.strip() for ln in text.splitlines()]
    pairs = list(zip(lines[0::2], lines[1::2]))

    header: dict[str, dict[str, str]] = {}
    layers: list[str] = []
    entities: Counter[str] = Counter()
    xs: list[float] = []
    ys: list[float] = []
    geo = _Geometry()
    section = var = None
    expect_section_name = in_layer = False
    for code, value in pairs:
        if code == "0" and value == "SECTION":
            expect_section_name = True
            continue
        if expect_section_name and code == "2":
            section, expect_section_name = value, False
            continue
        if code == "0" and value == "ENDSEC":
            section = None
            continue
        if section == "HEADER":
            if code == "9":
                var = value
                header[var] = {}
            elif var:
                header[var][code] = value
        elif section == "TABLES":
            if code == "0":
                in_layer = value == "LAYER"
            elif in_layer and code == "2":
                layers.append(value)
                in_layer = False
        elif section == "ENTITIES":
            if code == "0":
                geo.end()
                if value not in ("EOF", "ENDSEC"):
                    geo.start(value)
                entities[value] += 1
            else:
                geo.code(code, value)
            if code in ("10", "11"):
                try:
                    xs.append(float(value))
                except ValueError:
                    pass
            elif code in ("20", "21"):
                try:
                    ys.append(float(value))
                except ValueError:
                    pass

    ver = header.get("$ACADVER", {}).get("1")
    md.format_version = _VERSIONS.get(ver, ver)
    units = header.get("$INSUNITS", {}).get("70")
    if units is not None and units.lstrip("-").isdigit():
        md.quality["units"] = _UNITS.get(int(units), f"kode {units}")
    else:
        md.note("Ingen tegningsenheter ($INSUNITS) i filhodet.")
    entities.pop("EOF", None)
    entities.pop("ENDSEC", None)
    md.count, md.count_label = sum(entities.values()), "entities"
    md.details["entities"] = dict(entities.most_common(10))
    md.details["layers"] = layers[:50]

    emin, emax = header.get("$EXTMIN", {}), header.get("$EXTMAX", {})
    try:
        ext = {"minx": float(emin["10"]), "miny": float(emin["20"]), "maxx": float(emax["10"]), "maxy": float(emax["20"])}
        if ext["minx"] < ext["maxx"] and abs(ext["minx"]) < 1e19:
            md.extent = ext
    except (KeyError, ValueError):
        pass
    if md.extent is None and xs and ys:
        md.extent = {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}
    geo.end()
    geo.start("SEQEND")
    md.footprint = features(geo.points, geo.lines, geo.polygons, "elementene i tegningen")

    m = re.search(r"EPSG\s*:?\s*(\d{4,5})", text) if "GEODATA" in text else None
    if m:
        md.horizontal_epsg = int(m.group(1))
        md.details["crs_from"] = "GEODATA object"
    else:
        md.note("DXF har ikke koordinatsystem – det er vanlig for DXF, så opplasteren blir spurt.")
    if md.extent and md.horizontal_epsg is None:
        md.details["extent_note"] = "utstrekning i tegningsenheter"
    return md


class _Geometry:
    """Collects each entity's real geometry: POINT/INSERT/CIRCLE/ARC as points, LINE as a two-point line,
    LWPOLYLINE and POLYLINE+VERTEX as lines, or polygons when flagged closed. Text and dimensions are skipped."""

    SKIP = {"TEXT", "MTEXT", "DIMENSION", "ATTRIB", "ATTDEF", "HATCH", "VIEWPORT", "LEADER", "MLEADER", "SEQEND"}

    def __init__(self) -> None:
        self.points: list[list[float]] = []
        self.lines: list[list[list[float]]] = []
        self.polygons: list[list[list[float]]] = []
        self.kind = ""
        self.vals: dict[str, float] = {}
        self.verts: list[list[float]] = []
        self.flags = 0
        self.poly: dict | None = None  # open old-style POLYLINE collecting VERTEX entities

    def start(self, kind: str) -> None:
        if kind == "VERTEX" and self.poly is not None:
            self.kind = "VERTEX"
        else:
            self._close_poly()
            self.kind = "" if kind in self.SKIP else kind
            if kind == "POLYLINE":
                self.poly = {"verts": [], "flags": 0}
        self.vals, self.verts, self.flags = {}, [], 0

    def code(self, code: str, value: str) -> None:
        if not self.kind:
            return
        if code == "70":
            try:
                self.flags = int(value)
            except ValueError:
                pass
            return
        if code not in ("10", "20", "11", "21"):
            return
        try:
            v = float(value)
        except ValueError:
            return
        if self.kind == "LWPOLYLINE":
            if code == "10":
                self.verts.append([v, float("nan")])
            elif code == "20" and self.verts:
                self.verts[-1][1] = v
        else:
            self.vals.setdefault(code, v)

    def end(self) -> None:
        k, v = self.kind, self.vals
        if not k:
            return
        if k == "LWPOLYLINE":
            self._add(self.verts, self.flags & 1)
        elif k == "POLYLINE" and self.poly is not None:
            self.poly["flags"] = self.flags
        elif k == "VERTEX" and self.poly is not None and "10" in v and "20" in v:
            self.poly["verts"].append([v["10"], v["20"]])
        elif k == "LINE" and all(c in v for c in ("10", "20", "11", "21")):
            self.lines.append([[v["10"], v["20"]], [v["11"], v["21"]]])
        elif "10" in v and "20" in v and k != "POLYLINE":
            self.points.append([v["10"], v["20"]])
        self.kind = ""

    def _close_poly(self) -> None:
        if self.poly is not None:
            self._add(self.poly["verts"], self.poly["flags"] & 1)
            self.poly = None

    def _add(self, verts: list, closed: int) -> None:
        if closed and len(verts) >= 3:
            self.polygons.append(verts)
        elif len(verts) >= 2:
            self.lines.append(verts)
        elif verts:
            self.points.append(verts[0])
