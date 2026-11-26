"""Metadata extraction: one reader per format family, chosen by file extension."""

from __future__ import annotations

from pathlib import Path

from . import documents, dxf, ifc, pointcloud, raster, sosi, vector
from .common import FileMetadata

READERS = {
    ".sos": sosi.read,
    ".tif": raster.read, ".tiff": raster.read, ".jp2": raster.read, ".ecw": raster.read, ".img": raster.read,
    ".las": pointcloud.read, ".laz": pointcloud.read,
    ".dxf": dxf.read,
    ".gpkg": vector.read, ".geojson": vector.read, ".json": vector.read, ".shp": vector.read, ".gml": vector.read,
    ".pdf": documents.read_pdf,
    ".ifc": ifc.read,
}

# Files that belong to another file (same name, different extension) and travel with it.
SIDECAR_EXTS = {".prj", ".tfw", ".tifw", ".wld", ".j2w", ".jgw", ".aux.xml", ".xml.aux", ".shx", ".dbf",
                ".cpg", ".qix", ".sbn", ".sbx", ".ovr"}
# Delivery notes: not registered, but their text is given to the AI for every file in the delivery.
NOTE_EXTS = {".txt", ".md"}
# Formats the plan adds later; registered now, with a clear note.
LATER = {".xml": "LandXML", ".snd": "SND", ".dwg": "DWG", ".kof": "KOF", ".csv": "CSV", ".xyz": "XYZ"}


def suffix_of(name: str) -> str:
    """Extension in lower case, treating .aux.xml as one extension."""
    lower = name.lower()
    if lower.endswith(".aux.xml"):
        return ".aux.xml"
    return Path(lower).suffix


def stem_of(name: str) -> str:
    """File name without its extension (or .aux.xml)."""
    suf = suffix_of(name)
    return name[: -len(suf)] if suf else name


def extract(path: Path) -> FileMetadata:
    """Read a file's metadata. Never raises: problems end up in notes."""
    ext = suffix_of(path.name)
    reader = READERS.get(ext)
    if reader is None:
        md = FileMetadata(format=LATER.get(ext, ext.lstrip(".").upper() or "Unknown"))
        if ext == ".dwg":
            md.note("DWG må konverteres til DXF først (for eksempel med ODA File Converter).")
        elif ext in LATER:
            md.note(f"Lesing av {LATER[ext]} kommer i fase 4; fila registreres uten metadata.")
        else:
            md.note(f"Ingen leser for {ext or 'filer uten filtype'}.")
        return md
    try:
        return reader(path)
    except Exception as exc:  # a broken file must not stop the run
        md = FileMetadata(format=ext.lstrip(".").upper())
        md.note(f"Kunne ikke lese fila: {type(exc).__name__}: {exc}")
        return md


__all__ = ["FileMetadata", "extract", "suffix_of", "stem_of", "SIDECAR_EXTS", "NOTE_EXTS", "READERS"]
