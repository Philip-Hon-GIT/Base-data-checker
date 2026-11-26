"""PDF reports and plain-text delivery notes: text for the AI, plus document metadata."""

from __future__ import annotations

from pathlib import Path

from basedata.indata.extract.common import FileMetadata, iso_date
from basedata.indata.footprint import box
from basedata.indata.extract.textscan import scan

try:
    import pypdf  # type: ignore
except ImportError:  # pragma: no cover
    pypdf = None


def read_text_file(path: Path, limit: int = 6000) -> str:
    """Text of a delivery note or readme, decoded leniently."""
    raw = path.read_bytes()[: limit * 4]
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)[:limit]
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")[:limit]


PAPER = [("A4", 297), ("A3", 420), ("A2", 594), ("A1", 841), ("A0", 1189)]


def paper_size(w_pt: float, h_pt: float) -> tuple[str, bool]:
    """ISO paper name (nearest long side) and whether the page is landscape."""
    long_mm = max(w_pt, h_pt) * 25.4 / 72
    name = min(PAPER, key=lambda p: abs(p[1] - long_mm))[0]
    return name, w_pt > h_pt


def read_pdf(path: Path, limit: int = 8000) -> FileMetadata:
    """A PDF can be a drawing (title block, scale, grid coordinates) or a text document (report,
    description). Both are read for the same facts; which kind it is decides how it is checked."""
    md = FileMetadata(format="PDF")
    if pypdf is None:
        md.note("Lesing av PDF krever pypdf, som ikke er installert.")
        return md
    reader = pypdf.PdfReader(str(path))
    md.count, md.count_label = len(reader.pages), "pages"
    info = reader.metadata or {}
    md.format_version = reader.pdf_header.replace("%PDF-", "") if hasattr(reader, "pdf_header") else None
    title, author = info.get("/Title"), info.get("/Author")
    if title:
        md.details["title"] = str(title)
    if author:
        md.details["author"] = str(author)
    created = info.get("/CreationDate")
    if created:
        md.details["document_date"] = iso_date(str(created).replace("D:", "")[:8])
    parts, size = [], 0
    for page in reader.pages[:6]:
        t = (page.extract_text() or "").strip()
        parts.append(t)
        size += len(t)
        if size >= limit:
            break
    text = "\n\n".join(parts)
    md.text_excerpt = text[:limit] or None
    first = reader.pages[0].mediabox if reader.pages else None
    paper, landscape = paper_size(float(first.width), float(first.height)) if first is not None else ("A4", False)
    found = scan(text)
    words_per_page = found["words"] / max(1, min(len(reader.pages), 6))
    score = (2 if found["title_block_hits"] >= 2 else 0) + (paper != "A4") + landscape + (words_per_page < 250) \
        + bool(found["scale"])
    kind = "drawing" if score >= 3 else "text"
    md.details.update({"pdf_kind": kind, "paper": f"{paper} {'liggende' if landscape else 'stående'}",
                       "words": found["words"], "scan": {k: v for k, v in found.items() if k != "points"}})
    for key in (("drawing_no", "scale", "revision") if kind == "drawing" else ()):
        if found[key]:
            md.details[key] = found[key]
    if found["epsg"]:
        md.horizontal_epsg = found["epsg"]
        md.details["crs_from"] = "tekst i tegningen" if kind == "drawing" else "tekst i dokumentet"
    if found["height"]:
        md.height_reference = found["height"]
    if found["extent"] and found["epsg"]:
        md.extent = found["extent"]
        md.details["georef_from"] = "koordinater i tegningen" if kind == "drawing" else "koordinater i teksten"
        if kind == "drawing":
            md.footprint = box(found["extent"], "kartrammen i tegningen")
        elif found["points"]:
            md.footprint = {"kind": "points", "points": found["points"], "source": "koordinater i teksten"}
    if found["date"]:
        md.data_date = found["date"]
        md.data_date_kind = "dato i tegningshodet" if kind == "drawing" else "dato i dokumentet"
    if not text:
        md.note("Ingen tekst kunne hentes ut (PDF-en kan være skannede bilder).")
    elif kind == "drawing" and not md.extent:
        md.note("Tegningen har ingen lesbare koordinater; plassering må oppgis.")
    return md
