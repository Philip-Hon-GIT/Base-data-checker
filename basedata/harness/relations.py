"""How registrations relate: versions, reference comparisons, text that names other data, same
delivery, and overlapping areas. Worked out on demand from what is already stored."""

from __future__ import annotations

import re
from pathlib import Path

from basedata.core import db as dblib
from basedata.core.classify import DATA_TYPES
from basedata.harness.entries import READY_FOR_USE, predecessor_id

GROUPS = [
    ("erstatter", "Erstatter"), ("erstattet_av", "Erstattet av"), ("ny_versjon", "Mulig ny versjon"),
    ("sammenlignet_med", "Sammenlignet med"), ("referanse_for", "Referanse for"),
    ("omtaler", "Omtaler"), ("omtalt_i", "Omtalt i"),
    ("samme_leveranse", "Samme leveranse"), ("samme_omrade", "Samme område"),
]
LABELS = dict(GROUPS)


def _stems(entry: dict, files: list[dict]) -> set[str]:
    names = {Path(f["file_name"]).stem.lower() for f in files} | {Path(entry["name"]).stem.lower()}
    return {n for n in names if len(n) >= 6}


def _text(files: list[dict]) -> str:
    return "\n".join((f.get("metadata") or {}).get("text_excerpt") or "" for f in files).lower()


def _drawing_nos(files: list[dict]) -> set[str]:
    return {((f.get("content") or {}).get("drawing_no") or "").upper() for f in files} - {""}


def _overlap(a: dict | None, b: dict | None) -> float:
    if not a or not b:
        return 0.0
    w = min(a["maxx"], b["maxx"]) - max(a["minx"], b["minx"])
    h = min(a["maxy"], b["maxy"]) - max(a["miny"], b["miny"])
    return max(0.0, w) * max(0.0, h)


def _area(e: dict | None) -> float:
    return max(1.0, (e["maxx"] - e["minx"]) * (e["maxy"] - e["miny"])) if e else 0.0


def for_entry(db, entry: dict, max_area: int = 8) -> list[dict]:
    """Relations of one registration, grouped: [{type, label, entries: [{id, seq, name, type_label, lifecycle, note}]}]."""
    entries = {e["_id"]: e for e in db[dblib.ENTRIES].find({"project_id": entry["project_id"]})}
    files_by: dict[str, list[dict]] = {}
    for f in db[dblib.FILES].find({"project_id": entry["project_id"]}):
        files_by.setdefault(f.get("entry_id"), []).append(f)
    me, mine = entry["_id"], files_by.get(entry["_id"], [])
    found: dict[str, dict[str, str]] = {}

    def add(kind: str, other_id: str | None, note: str = "") -> None:
        if other_id and other_id != me and other_id in entries:
            found.setdefault(kind, {}).setdefault(other_id, note)

    pred = predecessor_id(entry)
    if pred:
        add("erstatter" if entry.get("ready") in READY_FOR_USE or entry.get("replaces_mode") == "manual" else "ny_versjon", pred)
    for x in entries.values():
        if predecessor_id(x) == me:
            add("erstattet_av" if x.get("ready") in READY_FOR_USE or x.get("replaces_mode") == "manual" else "ny_versjon", x["_id"])
    for f in mine:
        ref = (f.get("comparison") or {}).get("reference") or {}
        add("sammenlignet_med", ref.get("entry_id"))
    for eid, fs in files_by.items():
        if any(((f.get("comparison") or {}).get("reference") or {}).get("entry_id") == me for f in fs):
            add("referanse_for", eid)

    my_text, my_stems, my_nos = _text(mine), _stems(entry, mine), _drawing_nos(mine)
    for eid, x in entries.items():
        if eid == me:
            continue
        xf = files_by.get(eid, [])
        if any(s in my_text for s in _stems(x, xf)):
            add("omtaler", eid)
        else:
            no = next((n for n in _drawing_nos(xf) if re.search(rf"\b{re.escape(n.lower())}\b", my_text)), None)
            if no:
                add("omtaler", eid, f"tegning {no}")
        x_text = _text(xf)
        if x_text:
            if any(s in x_text for s in my_stems):
                add("omtalt_i", eid)
            else:
                no = next((n for n in my_nos if re.search(rf"\b{re.escape(n.lower())}\b", x_text)), None)
                if no:
                    add("omtalt_i", eid, f"som tegning {no}")
        if entry.get("delivery_id") and x.get("delivery_id") == entry.get("delivery_id"):
            add("samme_leveranse", eid)

    ext, epsg = entry.get("extent"), entry.get("extent_epsg")
    if ext and epsg:
        near = []
        for eid, x in entries.items():
            if eid == me or x.get("extent_epsg") != epsg or not x.get("extent"):
                continue
            ov = _overlap(ext, x["extent"])
            if ov / _area(ext) >= 0.01:
                near.append((ov / _area(ext), eid))
        for share, eid in sorted(near, reverse=True)[:max_area]:
            add("samme_omrade", eid, f"dekker {round(min(1.0, share) * 100)} % av denne")

    out = []
    for kind, label in GROUPS:
        items = found.get(kind)
        if not items:
            continue
        rows = []
        for eid, note in items.items():
            x = entries[eid]
            rows.append({"id": eid, "seq": x.get("seq"), "name": x["name"], "type_label": DATA_TYPES.get(x.get("data_type"), "Annet"),
                         "lifecycle": x.get("lifecycle", "gjeldende"), "note": note})
        rows.sort(key=lambda r: r["seq"] or 0)
        out.append({"type": kind, "label": label, "entries": rows})
    return out
