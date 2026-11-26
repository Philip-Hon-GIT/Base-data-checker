"""Read facts out of document text: coordinate system, height system, coordinates, dates, title-block
fields and references to other files or drawings. Used for PDFs (drawings and reports)."""

from __future__ import annotations

import re
from collections import Counter

from basedata.indata import crs as crslib
from basedata.indata.extract.common import iso_date

_UTM = re.compile(r"(?:EUREF\s*-?\s*89|ETRS\s*-?\s*89)?\s*UTM\s*(?:sone|zone)?\s*(3[1-6])\b", re.I)
_NTM = re.compile(r"NTM\s*(?:sone|zone)?\s*(\d{1,2})\b", re.I)
_NORTH = re.compile(r"(?<![\w.])(?:N|Nord|X)\s*[=:]?\s*(6\d{6}|7\d{6})(?:[.,]\d+)?(?!\d)")
_EAST = re.compile(r"(?<![\w.])(?:Ø|E|Øst|Y)\s*[=:]?\s*(\d{5,6})(?:[.,]\d+)?(?!\d)")
_FILE = re.compile(r"\b([\w\-æøåÆØÅ]+\.(?:sos|tif|tiff|las|laz|gpkg|dxf|dwg|ifc|pdf|gml|shp|xml|kof|snd))\b", re.I)
_DRAWING_NO = re.compile(r"\b(?:tegningsnr|tegningsnummer|tegning\s+nr|tegn\.?\s*nr)\.?\s*[:.]?\s*([A-Z]{1,3}[- ]?\d{2,4}[A-Z]?)\b", re.I)
_DRAWING_REF = re.compile(r"\b(?:tegning|tegningene?)\s+([A-Z]{1,3}\d{2,4}[A-Z]?)\b", re.I)
_SCALE = re.compile(r"(?:målestokk|målest\.?|m\.?\s*st\.?|scale)\s*[:.]?\s*1\s*:\s*(\d{2,6})", re.I)
_REV = re.compile(r"\brev(?:isjon)?\.?\s*[:.]?\s*([A-Z0-9]{1,3})\b", re.I)
_DATE = re.compile(r"\b(?:dato|date)\s*[:.]?\s*(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2})", re.I)
_TITLE_BLOCK = re.compile(r"tegningsnr|tegning nr|tegn\.? ?nr|målestokk|tegnet|kontrollert|godkjent|revisjon|\brev\.|"
                          r"oppdragsnr|fag:|tegningstype", re.I)
_STOP = set("""og i på av til for med som er det den de en et at ikke fra har ble blir kan skal vil være eller om
ved under over etter mellom også samt alle eller denne dette disse hvor når der her inn ut opp ned the and of
oppgitt utført ihht iht tegningsnr målestokk tegnet kontrollert godkjent revisjon oppdragsgiver
koordinatsystem""".split())


def scan(text: str) -> dict:
    """Everything the text says that the checker can use. Values are None when absent."""
    t = text or ""
    out: dict = {"epsg": None, "height": None, "points": [], "extent": None, "date": None, "drawing_no": None,
                 "scale": None, "revision": None, "title_block_hits": len(_TITLE_BLOCK.findall(t)),
                 "file_mentions": [], "drawing_mentions": [], "headings": [], "keywords": [], "words": 0}
    epsg = crslib.parse_crs(t) if re.search(r"EPSG", t, re.I) else None
    if not epsg:
        m = _UTM.search(t)
        if m and re.search(r"EUREF|ETRS", t, re.I):
            epsg = 25800 + int(m.group(1))
        m = _NTM.search(t)
        if not epsg and m:
            epsg = 5100 + int(m.group(1))
    out["epsg"] = epsg if epsg in crslib.REGISTRY else None
    if re.search(r"NN\s*2000", t):
        out["height"] = "NN2000"
    elif re.search(r"NN\s*1954", t):
        out["height"] = "NN1954"

    norths = [int(v) for v in _NORTH.findall(t)]
    easts = [int(v) for v in _EAST.findall(t) if 100000 <= int(v) <= 999999]
    for line in t.splitlines():
        n, e = _NORTH.search(line), _EAST.search(line)
        if n and e:
            out["points"].append([int(e.group(1)), int(n.group(1))])
    if norths and easts:
        minx, maxx, miny, maxy = min(easts), max(easts), min(norths), max(norths)
        if maxx - minx < 20:
            minx, maxx = minx - 25, maxx + 25
        if maxy - miny < 20:
            miny, maxy = miny - 25, maxy + 25
        out["extent"] = {"minx": float(minx), "miny": float(miny), "maxx": float(maxx), "maxy": float(maxy)}
        out["coordinate_count"] = len(norths) + len(easts)

    m = _DATE.search(t)
    if m:
        out["date"] = iso_date(m.group(1))
    m = _DRAWING_NO.search(t)
    if m:
        out["drawing_no"] = m.group(1).replace(" ", "").replace("-", "").upper()
    m = _SCALE.search(t)
    if m:
        out["scale"] = f"1:{int(m.group(1))}"
    m = _REV.search(t)
    if m and out["title_block_hits"]:
        out["revision"] = m.group(1).upper()
    out["file_mentions"] = list(dict.fromkeys(f for f in _FILE.findall(t)))
    refs = [r.upper() for r in _DRAWING_REF.findall(t)]
    out["drawing_mentions"] = [r for r in dict.fromkeys(refs) if r != out["drawing_no"]]
    for line in t.splitlines():
        s = line.strip()
        if 3 < len(s) < 70 and (re.match(r"^\d+(\.\d+)*\.?\s+[A-ZÆØÅ]", s) or (s.isupper() and len(s.split()) <= 6)):
            out["headings"].append(s)
    words = re.findall(r"[A-Za-zÆØÅæøå][a-zæøå\-]{5,}", t)
    out["words"] = len(re.findall(r"\w+", t))
    counts = Counter(w.lower() for w in words if w.lower() not in _STOP)
    out["keywords"] = [w for w, n in counts.most_common(8) if n >= 1][:8]
    return out
