"""SOSI (.sos) — the Norwegian exchange format for FKB and other map data.

Reads the header as text (no SOSI driver needed) and scans the objects for dates, quality and counts.
The KOORDSYS → EPSG table lives in basedata/data/sosi_koordsys.yaml so it can be checked and edited.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from functools import lru_cache
from pathlib import Path

import yaml

from ..footprint import features
from .common import FileMetadata, iso_date

_DATA = Path(__file__).resolve().parent.parent / "data" / "sosi_koordsys.yaml"

# ND7 is the old 7-bit Norwegian character set: [ \ ] { | } stand for Æ Ø Å æ ø å.
_ND7 = str.maketrans({"[": "Æ", "\\": "Ø", "]": "Å", "{": "æ", "|": "ø", "}": "å"})
_ENCODINGS = {"UTF-8": "utf-8", "UTF8": "utf-8", "ISO8859-1": "latin-1", "ISO8859-10": "iso8859_10",
              "ANSI": "cp1252", "DOSN8": "cp865", "ND7": "ascii"}


@lru_cache(maxsize=1)
def koordsys_table() -> dict[int, int]:
    """SOSI KOORDSYS code → EPSG code, from the editable data file."""
    rows = yaml.safe_load(_DATA.read_text(encoding="utf-8"))
    return {int(k): int(v["epsg"]) for k, v in rows["koordsys"].items()}


def _decode(raw: bytes) -> tuple[str, str]:
    head = raw[:65536].decode("latin-1")
    m = re.search(r"\.\.TEGNSETT\s+(\S+)", head)
    charset = m.group(1).upper() if m else "UTF-8"
    encoding = _ENCODINGS.get(charset, "utf-8")
    try:
        text = raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        text = raw.decode("latin-1")
        charset += " (fallback latin-1)"
    if charset == "ND7":
        text = text.translate(_ND7)
    return text, charset


def _value(line: str) -> str:
    parts = line.split(None, 1)
    return parts[1].strip().strip('"') if len(parts) > 1 else ""


def read(path: Path) -> FileMetadata:
    """Read a SOSI file's header and object statistics."""
    md = FileMetadata(format="SOSI")
    text, charset = _decode(path.read_bytes())
    md.details["charset"] = charset
    lines = text.splitlines()

    header: dict[str, str] = {}
    i = 0
    if lines and lines[0].strip().upper().startswith(".HODE"):
        i = 1
        while i < len(lines) and not re.match(r"^\.[A-ZÆØÅ]", lines[i]):
            line = lines[i].strip()
            if line.startswith(".."):
                key = line.split(None, 1)[0].lstrip(".").upper()
                header.setdefault(key, _value(line))
            i += 1
    else:
        md.note("Fant ikke .HODE – dette er kanskje ikke en SOSI-fil.")

    md.format_version = header.get("SOSI-VERSJON") or None
    md.details["sosi_level"] = header.get("SOSI-NIVÅ") or None
    if header.get("PRODUKTSPEK"):
        md.details["product_spec"] = header["PRODUKTSPEK"]

    ks = header.get("KOORDSYS")
    if ks and ks.split()[0].isdigit():
        code = int(ks.split()[0])
        md.details["koordsys"] = code
        md.horizontal_epsg = koordsys_table().get(code)
        if md.horizontal_epsg is None:
            md.note(f"KOORDSYS {code} finnes ikke i oppslagstabellen (data/sosi_koordsys.yaml).")
    else:
        md.note("Ingen KOORDSYS i SOSI-hodet.")

    vd = header.get("VERT-DATUM")
    if vd:
        from ..crs import normalize_height
        md.height_reference = normalize_height(vd)
    owner, producer = header.get("EIER"), header.get("PRODUSENT")
    if owner or producer:
        md.source = " / ".join(dict.fromkeys(v for v in (producer, owner) if v))

    unit = float(header.get("ENHET", "1").replace(",", ".") or 1)
    origo = [float(v) for v in header.get("ORIGO-NØ", "0 0").split()[:2]] if header.get("ORIGO-NØ") else [0.0, 0.0]
    mn, mx = header.get("MIN-NØ"), header.get("MAX-NØ")
    if mn and mx:
        n1, e1 = (float(v) for v in mn.split()[:2])
        n2, e2 = (float(v) for v in mx.split()[:2])
        md.extent = {"minx": e1, "miny": n1, "maxx": e2, "maxy": n2}

    # Object statistics: types, dates, quality, and the real coordinate extent.
    kinds: Counter[str] = Counter()
    objtypes: Counter[str] = Counter()
    dates: list[str] = []
    accuracies: list[float] = []
    methods: Counter[str] = Counter()
    min_e = min_n = float("inf")
    max_e = max_n = float("-inf")
    geo_pts: list[list[float]] = []
    geo_lines: list[list[list[float]]] = []
    geo_polys: list[list[list[float]]] = []
    cur_kind, cur = "", []

    def flush() -> None:
        # Points stay points, curves stay lines and surfaces with their own boundary become polygons.
        # A surface that only references curves (..REF) has one representation point; the curves draw it.
        if not cur:
            return
        if cur_kind in ("KURVE", "LINJE", "BUEP", "BUE", "KLOTOIDE", "SIRKELP", "SIRKEL") and len(cur) >= 2:
            geo_lines.append(list(cur))
        elif cur_kind == "FLATE" and len(cur) >= 3:
            geo_polys.append(cur[:-1] if cur[0] == cur[-1] else list(cur))
        elif cur_kind != "FLATE" or not geo_lines:
            geo_pts.extend(cur)

    in_coords = False
    for line in lines[i:]:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^\.[A-ZÆØÅ]", s):
            flush()
            kind = s.split()[0][1:].upper()
            if kind != "SLUTT":
                kinds[kind] += 1
            cur_kind, cur = kind, []
            in_coords = False
            continue
        if s.startswith(".."):
            key = s.split(None, 1)[0].lstrip(".").upper()
            in_coords = key in ("NØ", "NØH")
            val = _value(s)
            if key == "OBJTYPE":
                objtypes[val] += 1
            elif key in ("DATAFANGSTDATO", "OPPDATERINGSDATO", "VERIFISERINGSDATO"):
                d = iso_date(val)
                if d:
                    dates.append(d)
            elif key == "KVALITET" and val:
                parts = val.split()
                if parts:
                    methods[parts[0]] += 1
                if len(parts) > 1 and re.match(r"^\d+(\.\d+)?$", parts[1]):
                    accuracies.append(float(parts[1]))
            elif key in ("DATAFANGSTMETODE",):
                methods[val] += 1
            elif key in ("NØYAKTIGHET",) and re.match(r"^\d+(\.\d+)?$", val):
                accuracies.append(float(val))
            continue
        if in_coords:
            nums = s.split()
            if len(nums) >= 2 and re.match(r"^-?\d+$", nums[0]) and re.match(r"^-?\d+$", nums[1]):
                n = int(nums[0]) * unit + origo[0]
                e = int(nums[1]) * unit + origo[1]
                min_n, max_n = min(min_n, n), max(max_n, n)
                min_e, max_e = min(min_e, e), max(max_e, e)
                cur.append([e, n])
    flush()

    md.count = sum(kinds.values())
    md.count_label = "objects"
    md.details["object_kinds"] = dict(kinds)
    md.details["top_objtypes"] = dict(objtypes.most_common(8))
    if min_e != float("inf"):
        data_extent = {"minx": min_e, "miny": min_n, "maxx": max_e, "maxy": max_n}
        if md.extent is None:
            md.extent = data_extent
        md.details["data_extent"] = data_extent
        md.footprint = features(geo_pts, geo_lines, geo_polys, "geometrien til objektene i fila")
    if dates:
        md.data_date = max(dates)
        md.data_date_kind = "seneste datafangst- eller oppdateringsdato i objektene"
        md.details["date_range"] = [min(dates), max(dates)]
    elif header.get("DATO"):
        md.data_date = iso_date(header["DATO"])
        md.data_date_kind = "dato i filhodet"
    if accuracies:
        md.quality["accuracy_cm"] = {"min": min(accuracies), "median": statistics.median(accuracies),
                                     "max": max(accuracies), "objects_with_value": len(accuracies)}
    if methods:
        md.quality["capture_methods"] = dict(methods.most_common(5))
    if md.details.get("product_spec"):
        md.quality["product_spec"] = md.details["product_spec"]
    if not accuracies and not methods:
        md.note("Ingen KVALITET (nøyaktighet) i objektene.")
    return md
