"""The metadata record every extractor fills in, plus small shared helpers."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from .. import crs as crslib


@dataclass
class FileMetadata:
    """What a file says about itself. Unknown values stay None; notes explain why."""

    format: str
    format_version: str | None = None
    horizontal_epsg: int | None = None
    height_reference: str | None = None
    extent: dict | None = None          # {minx, miny, maxx, maxy} in the file's own CRS
    data_date: str | None = None        # ISO date (YYYY, YYYY-MM or YYYY-MM-DD)
    data_date_kind: str | None = None   # what the date means, e.g. "capture", "updated", "document"
    source: str | None = None
    quality: dict = field(default_factory=dict)
    count: int | None = None            # features, objects or points
    count_label: str | None = None      # "objects", "features", "points", "pages"
    details: dict = field(default_factory=dict)
    text_excerpt: str | None = None     # text for the AI (reports, notes)
    footprint: dict | None = None       # where the data really is (see basedata/footprint.py), file CRS
    notes: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        """Record something that could not be read, or is worth knowing."""
        if text not in self.notes:
            self.notes.append(text)

    def to_dict(self) -> dict:
        """Plain dict for MongoDB, with the CRS spelled out."""
        d = asdict(self)
        d["horizontal_crs"] = crslib.crs_dict(self.horizontal_epsg)
        return d


def sidecar(path: Path, *suffixes: str) -> Path | None:
    """Find a sidecar file next to `path` (e.g. .prj, .tfw), in any letter case."""
    for suffix in suffixes:
        for candidate in (path.with_suffix(suffix), path.with_suffix(suffix.upper()),
                          path.with_name(path.name + suffix)):
            if candidate.exists():
                return candidate
    return None


def read_prj(path: Path, md: FileMetadata) -> None:
    """Fill CRS and height reference from a .prj (WKT) sidecar, if there is one."""
    prj = sidecar(path, ".prj")
    if not prj:
        return
    wkt = prj.read_text(errors="replace")
    epsg, height = crslib.parse_wkt(wkt)
    if epsg:
        md.horizontal_epsg = epsg
        md.details["crs_from"] = prj.name
    else:
        md.note(f"{prj.name} finnes, men koordinatsystemet ble ikke gjenkjent.")
    if height and not md.height_reference:
        md.height_reference = height


def iso_date(value: str | date | datetime | None) -> str | None:
    """Normalise dates like 20240615, 2024:06:15 12:00:00, 15.06.2024 or 2024-06 to ISO text."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip().strip('"')
    m = re.match(r"^(\d{4})[-:/]?(\d{2})[-:/]?(\d{2})", s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    m = re.match(r"^(\d{4})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"^(\d{4})$", s)
    if m and 1900 < int(s) < 2100:
        return s
    return None


def year_of(iso: str | None) -> int | None:
    """The year of an ISO date string."""
    return int(iso[:4]) if iso and iso[:4].isdigit() else None
