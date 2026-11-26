"""Guess a file's data type and the responsible discipline. Both can be corrected in the app."""

from __future__ import annotations

import re

DATA_TYPES = {
    "fkb": "FKB",
    "terrain": "Terrengmodell",
    "point_cloud": "Punktsky",
    "orthophoto": "Ortofoto",
    "utility": "Ledningsdata",
    "ground_investigation": "Grunnundersøkelse",
    "model": "Eksisterende modell",
    "drawing": "Tegning / innmåling",
    "plan_data": "Plandata",
    "document": "Dokument / beskrivelse",
    "other": "Annet",
}
SURFACE_TYPES = {"terrain", "point_cloud"}  # compared against approved references

DEFAULT_DISCIPLINES = ["VEG", "VA", "KON", "GEO", "LARK", "ELE", "BIM"]
DEFAULT_DISCIPLINE_MAP = {"fkb": "VEG", "terrain": "VEG", "point_cloud": "VEG", "orthophoto": "VEG", "utility": "VA",
                          "ground_investigation": "GEO", "model": "KON", "drawing": "VEG", "plan_data": "VEG",
                          "document": "VEG", "other": "VEG"}

_UTILITY = r"ledning|(^|[_\- ])va([_\- ]|$)|vann|avl[øo]p|spillvann|overvann|(^|[_\- ])el([_\- ]|$)|tele|fiber|gass|fjernvarme"
_VA_WORDS = r"kum|ledning|(^|[_\- ])va([_\- ]|$)|vann|avl[øo]p|spillvann|overvann"
_SURVEY = r"innm[aå]+l|oppm[aå]+l|survey|kontrollm[aå]+l"
_GROUND = r"geotek|grunnunders|boring|sondering|cptu|geoteknisk"


def guess(filename: str, md: dict) -> tuple[str, str]:
    """Return (data type key, reason in Norwegian)."""
    name = filename.lower()
    fmt = (md.get("format") or "").upper()
    details = md.get("details") or {}
    ext = name.rsplit(".", 1)[-1] if "." in name else ""

    if ext in ("las", "laz"):
        return "point_cloud", "LAS/LAZ-punktsky"
    if ext == "snd" or re.search(_GROUND, name):
        return "ground_investigation", "filnavnet nevner grunnundersøkelse"
    if ext == "ifc":
        return "model", "IFC-modell"
    if fmt == "SOSI":
        spec = str(details.get("product_spec", ""))
        if "FKB" in spec.upper() or "fkb" in name:
            return "fkb", f"SOSI-produktspesifikasjon {spec or 'FKB'}"
        if "plan" in name or "PLAN" in spec.upper():
            return "plan_data", "SOSI-plandata"
    if fmt in ("GEOTIFF", "RASTER", "GTIFF"):
        kind = details.get("raster_kind")
        if kind == "elevation grid" or re.search(r"dtm|dem|dom|terreng|h[øo]yde", name):
            return "terrain", "énkanals høyderaster"
        if kind == "image (RGB)" or re.search(r"orto|ortho", name):
            return "orthophoto", "RGB-bilde"
    if re.search(_SURVEY, name):
        return "drawing", "filnavnet nevner innmåling"
    if re.search(_UTILITY, name):
        return "utility", "filnavnet nevner ledninger"
    if "fkb" in name:
        return "fkb", "filnavnet nevner FKB"
    if ext in ("dxf", "dwg"):
        return "drawing", "CAD-tegning"
    if ext == "pdf":
        if details.get("pdf_kind") == "drawing":
            return "drawing", f"PDF-tegning ({details.get('paper', 'tegningsark')}, tegningshode)"
        if re.search(_GROUND, (md.get("text_excerpt") or "")[:3000].lower()):
            return "ground_investigation", "teksten handler om grunnundersøkelser"
        return "document", "tekstdokument"
    return "other", "ingen regel passet"


def disciplines(project: dict) -> list[str]:
    """The project's disciplines (fag), or the defaults."""
    return list(project.get("disciplines") or DEFAULT_DISCIPLINES)


def discipline_for(project: dict, data_type: str, name: str, hint: str | None = None) -> str:
    """Default responsible discipline (Ansvarlig fag for KS) for a new registration. `hint` comes from
    the content (e.g. an IFC model full of pipes and chambers says VA)."""
    fag = disciplines(project)
    if hint in fag:
        return hint
    if re.search(_VA_WORDS, name.lower()) and "VA" in fag:
        return "VA"
    mapping = {**DEFAULT_DISCIPLINE_MAP, **(project.get("discipline_map") or {})}
    d = mapping.get(data_type)
    return d if d in fag else fag[0]
