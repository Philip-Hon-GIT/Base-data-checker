"""Turn free text (uploader answers, delivery notes, AI output) into register values."""

from __future__ import annotations

import re

from . import crs as crslib
from .extract.common import iso_date

_MONTHS = {
    "jan": 1, "januar": 1, "january": 1, "feb": 2, "februar": 2, "february": 2, "mar": 3, "mars": 3, "march": 3,
    "apr": 4, "april": 4, "mai": 5, "may": 5, "jun": 6, "juni": 6, "june": 6, "jul": 7, "juli": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "okt": 10, "oktober": 10, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "des": 12, "desember": 12, "dec": 12, "december": 12,
}


def parse_crs_text(text: str | None) -> int | None:
    """EPSG code from 'EPSG:25832', 'EUREF89 UTM sone 32', 'NTM zone 10', WKT, or similar."""
    if not text:
        return None
    epsg = crslib.parse_crs(text)
    if epsg:
        return epsg
    m = re.search(r"NTM\s*(?:sone|zone)?\s*(\d{1,2})", text, re.I)
    if m and 5 <= int(m.group(1)) <= 30:
        return 5100 + int(m.group(1))
    m = re.search(r"UTM\s*(?:sone|zone)?\s*(3[1-6])", text, re.I)
    if m:
        zone = int(m.group(1))
        return (32600 if re.search(r"WGS", text, re.I) and not re.search(r"EUREF|ETRS", text, re.I) else 25800) + zone
    return None


def parse_date_text(text: str | None) -> str | None:
    """ISO date from '12.05.2024', '2024-05', 'mars 2024', 'May 2024' or '2024'."""
    if not text:
        return None
    s = str(text).strip()
    direct = iso_date(s)
    if direct:
        return direct
    m = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", s)
    if m:
        return iso_date(m.group(1))
    m = re.search(r"(\d{4}-\d{2}(?:-\d{2})?)", s)
    if m:
        return iso_date(m.group(1)) or m.group(1)
    m = re.search(r"([A-Za-zæøåÆØÅ]{3,9})\.?\s+(\d{4})", s)
    if m and m.group(1).lower() in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}"
    m = re.search(r"\b(19\d{2}|20\d{2})\b", s)
    return m.group(1) if m else None
