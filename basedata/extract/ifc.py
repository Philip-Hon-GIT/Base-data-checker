"""IFC models (STEP text): schema, project, georeferencing (IfcMapConversion / IfcProjectedCRS),
what the model contains, and where it lies."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from .. import crs as crslib
from ..footprint import from_xy
from .common import FileMetadata, iso_date

# Element classes worth naming, with Norwegian labels and the discipline they usually belong to.
ELEMENTS = {
    "IFCPIPESEGMENT": ("rørsegmenter", "VA"), "IFCPIPEFITTING": ("rørdeler", "VA"),
    "IFCDISTRIBUTIONCHAMBERELEMENT": ("kummer", "VA"), "IFCFLOWFITTING": ("rørdeler", "VA"),
    "IFCFLOWSEGMENT": ("rørsegmenter", "VA"), "IFCVALVE": ("ventiler", "VA"),
    "IFCWALL": ("vegger", "KON"), "IFCWALLSTANDARDCASE": ("vegger", "KON"), "IFCSLAB": ("dekker", "KON"),
    "IFCBEAM": ("bjelker", "KON"), "IFCCOLUMN": ("søyler", "KON"), "IFCFOOTING": ("fundamenter", "KON"),
    "IFCPILE": ("peler", "KON"), "IFCBRIDGE": ("bruer", "KON"), "IFCBRIDGEPART": ("brudeler", "KON"),
    "IFCALIGNMENT": ("linjer", "VEG"), "IFCROAD": ("veger", "VEG"), "IFCCOURSE": ("vegoverbygning", "VEG"),
    "IFCPAVEMENT": ("dekker (veg)", "VEG"), "IFCKERB": ("kantstein", "VEG"), "IFCEARTHWORKSFILL": ("fyllinger", "VEG"),
    "IFCEARTHWORKSCUT": ("skjæringer", "VEG"), "IFCGEOGRAPHICELEMENT": ("terrengobjekter", "LARK"),
    "IFCBUILDINGELEMENTPROXY": ("proxy-objekter", None), "IFCBUILDING": ("bygg", "ARK"),
    "IFCCABLESEGMENT": ("kabler", "ELE"), "IFCLIGHTFIXTURE": ("lysarmaturer", "ELE"),
}
_ENTITY = re.compile(r"#(\d+)\s*=\s*(IFC\w+)\s*\((.*)\)\s*;\s*$", re.S)


def _args(s: str) -> list[str]:
    """Split a STEP argument list at top-level commas."""
    out, depth, cur, quote = [], 0, [], False
    for ch in s:
        if ch == "'" :
            quote = not quote
        if not quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append("".join(cur).strip())
                cur = []
                continue
        cur.append(ch)
    out.append("".join(cur).strip())
    return out


def _str(v: str | None) -> str | None:
    if not v or v in ("$", "*"):
        return None
    v = v.strip()
    return v[1:-1] if v.startswith("'") and v.endswith("'") else v


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "$", "*") else None
    except ValueError:
        return None


def read(path: Path) -> FileMetadata:
    md = FileMetadata(format="IFC")
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    md.format_version = m.group(1) if m else None
    m = re.search(r"FILE_NAME\s*\((.*?)\);", text, re.S)
    if m:
        a = _args(m.group(1))
        if len(a) > 1 and _str(a[1]):
            md.data_date, md.data_date_kind = iso_date(_str(a[1])[:10]), "lagringsdato i IFC-fila"
        org = re.findall(r"'([^']+)'", a[3]) if len(a) > 3 else []
        if org:
            md.source = org[0]
        if len(a) > 5 and _str(a[5]):
            md.details["software"] = _str(a[5])
    data = text.split("DATA;", 1)[-1]
    counts: Counter = Counter()
    pts_x, pts_y = [], []
    conv, crs_args = None, None
    for raw in data.split(";\n"):
        mm = _ENTITY.match(raw.strip() + ";")
        if not mm:
            continue
        cls, body = mm.group(2).upper(), mm.group(3)
        counts[cls] += 1
        if cls == "IFCCARTESIANPOINT":
            nums = [_num(x) for x in re.findall(r"-?\d+(?:\.\d*)?(?:E[-+]?\d+)?", body, re.I)]
            if len(nums) >= 2 and None not in nums[:2]:
                pts_x.append(nums[0])
                pts_y.append(nums[1])
        elif cls == "IFCPROJECT":
            a = _args(body)
            if len(a) > 2 and _str(a[2]):
                md.details["ifc_project"] = _str(a[2])
        elif cls == "IFCMAPCONVERSION":
            conv = _args(body)
        elif cls == "IFCPROJECTEDCRS":
            crs_args = _args(body)
    if crs_args:
        epsg = crslib.parse_crs(_str(crs_args[0]) or "")
        md.horizontal_epsg = epsg if epsg in crslib.REGISTRY else None
        md.details["crs_name"] = _str(crs_args[0])
        vert = crslib.normalize_height(_str(crs_args[3]) if len(crs_args) > 3 else None)
        if vert:
            md.height_reference = vert
    elements = {k: v for k, v in counts.items() if k in ELEMENTS}
    md.count, md.count_label = sum(elements.values()), "objects"
    summary: Counter = Counter()
    fag: Counter = Counter()
    for k, n in elements.items():
        label, discipline = ELEMENTS[k]
        summary[label] += n
        if discipline:
            fag[discipline] += n
    md.details["elements"] = dict(summary.most_common())
    md.details["discipline_hint"] = fag.most_common(1)[0][0] if fag else None
    md.quality["schema"] = md.format_version
    if conv and pts_x:
        e0, n0 = _num(conv[2]) or 0.0, _num(conv[3]) or 0.0
        ax, ay = _num(conv[5]) if len(conv) > 5 else None, _num(conv[6]) if len(conv) > 6 else None
        scale = (_num(conv[7]) if len(conv) > 7 else None) or 1.0
        ang = math.atan2(ay, ax) if ax is not None and ay is not None else 0.0
        xs, ys = [], []
        for x, y in ((min(pts_x), min(pts_y)), (max(pts_x), min(pts_y)), (max(pts_x), max(pts_y)), (min(pts_x), max(pts_y))):
            xs.append(e0 + scale * (x * math.cos(ang) - y * math.sin(ang)))
            ys.append(n0 + scale * (x * math.sin(ang) + y * math.cos(ang)))
        md.extent = {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}
        md.details["georef_from"] = "IfcMapConversion"
        ca, sa = math.cos(ang), math.sin(ang)
        md.footprint = from_xy([e0 + scale * (x * ca - y * sa) for x, y in zip(pts_x, pts_y)],
                               [n0 + scale * (x * sa + y * ca) for x, y in zip(pts_x, pts_y)], "plasseringspunkter i modellen")
    elif pts_x and max(map(abs, pts_x + pts_y)) > 100000:
        md.extent = {"minx": min(pts_x), "miny": min(pts_y), "maxx": max(pts_x), "maxy": max(pts_y)}
        md.details["georef_from"] = "koordinater i modellen"
    else:
        md.note("Modellen har ikke IfcMapConversion; den ligger i lokale koordinater.")
    if not crs_args:
        md.note("Modellen oppgir ikke koordinatsystem (IfcProjectedCRS mangler).")
    return md
