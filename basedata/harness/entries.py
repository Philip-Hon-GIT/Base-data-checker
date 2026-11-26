"""Register entries: one row in the register — a single file, or a package of files delivered together.

The row holds the documentation columns (sequence, name, content, file type, date received, received
from, link, responsible discipline, QA status, date checked, ready for use) and the automatic result,
which is the worst result of its files. When a new version of earlier data is put into use, the
earlier entry is marked as superseded (utgått).
"""

from __future__ import annotations

import os
import re
from collections import Counter

from basedata.core import db as dblib
from basedata.harness import questions as qlib
from basedata.core.classify import DATA_TYPES, SURFACE_TYPES, discipline_for
from basedata.harness.rules import worst
from basedata.core.text import area, nb

READY_FOR_USE = ("ja", "med_forbehold")
_VERSION_TOKENS = re.compile(r"(?<![a-z0-9])((19|20)\d{2}([-_.]?\d{2}){0,2}|\d{8}|v\d+|rev\d*|versjon\d*|ver\d+|"
                             r"kopi|copy|final|endelig|ny|new)(?![a-z0-9])")


def normalize_name(name: str) -> str:
    """Name without extension, dates and version words: 'FKB_Bygning_2026.sos' → 'fkb_bygning'."""
    stem = re.sub(r"\.[a-z0-9]{1,5}$", "", (name or "").lower())
    stem = _VERSION_TOKENS.sub(" ", stem)
    return re.sub(r"[\s_\-.]+", "_", stem).strip("_")


def package_name(folder: str, names: list[str], delivery_id: str) -> str:
    """A readable name for a package: its folder, or what its file names have in common."""
    if folder:
        return folder.split("/")[-1]
    prefix = os.path.commonprefix(names)
    prefix = re.sub(r"(blokk|tile|del|part|rute)?[\s_\-.]*\d*$", "", prefix, flags=re.I).rstrip(" _-.")
    return prefix if len(prefix) >= 4 else f"Pakke {delivery_id}"


def _next_seq(db, project_id: str) -> int:
    last = db[dblib.ENTRIES].find_one({"project_id": project_id}, sort=[("seq", -1)])
    return int((last or {}).get("seq") or 0) + 1


def _new_entry(ctx, project_id: str, key: str, kind: str, name: str, delivery_id: str, folder: str) -> dict:
    now = ctx.now()
    e = {"_id": dblib.new_id("bde"), "project_id": project_id, "group_key": key, "seq": _next_seq(ctx.db, project_id),
         "kind": kind, "name": name, "delivery_id": delivery_id, "folder": folder, "created_at": now,
         "discipline": None, "qa_status": "ikke_begynt", "qa_date": None, "qa_note": "", "ready": None, "review": None,
         "lifecycle": "gjeldende", "superseded_by": None, "superseded_at": None,
         "replaces_mode": "auto", "replaces": None, "replaces_candidate": None,
         "received_from_override": None, "content_override": None, "uploader_comment": None,
         "check_result": "pending", "open_questions": 0, "history": []}
    ctx.db[dblib.ENTRIES].insert_one(e)
    return e


def register_group(ctx, project_id: str, delivery_id: str, folder: str, file_ids: list[str],
                   as_package: bool) -> tuple[list[str], list[str]]:
    """Make sure the files belong to entries. Returns (entry ids, ids of entries created now)."""
    db = ctx.db
    files = [db[dblib.FILES].find_one({"_id": fid}) for fid in file_ids]
    files = [f for f in files if f]
    if not files:
        return [], []
    created: list[str] = []
    if as_package:
        key = f"{project_id}|pakke|{delivery_id}|{folder}"
        e = db[dblib.ENTRIES].find_one({"group_key": key})
        if e is None:
            e = _new_entry(ctx, project_id, key, "package",
                           package_name(folder, [f["file_name"] for f in files], delivery_id), delivery_id, folder)
            created.append(e["_id"])
        for f in files:
            if f.get("entry_id") != e["_id"]:
                db[dblib.FILES].update_one({"_id": f["_id"]}, {"$set": {"entry_id": e["_id"]}})
        return [e["_id"]], created
    ids = []
    for f in files:
        if f.get("entry_id"):
            ids.append(f["entry_id"])
            continue
        key = f"{project_id}|fil|{f['source_key']}"
        e = db[dblib.ENTRIES].find_one({"group_key": key})
        if e is None:
            e = _new_entry(ctx, project_id, key, "file", f["file_name"], delivery_id, folder)
            created.append(e["_id"])
        db[dblib.FILES].update_one({"_id": f["_id"]}, {"$set": {"entry_id": e["_id"]}})
        ids.append(e["_id"])
    return ids, created


def _fmt(md: dict) -> str:
    fmt = md.get("format") or "?"
    ver = md.get("format_version")
    return f"{fmt} {ver}" if ver and fmt in ("SOSI", "LAS", "LAZ", "DXF") else fmt


def content_text(entry: dict, files: list[dict], data_type: str) -> str:
    """The 'Innhold i fil/mappe' column, written from the metadata."""
    label = DATA_TYPES.get(data_type, "Annet")
    if entry.get("kind") == "package":
        parts = [f"{len(files)} filer", label]
        points = sum(f["metadata"].get("count") or 0 for f in files if f["metadata"].get("count_label") == "points")
        if points:
            parts.append(f"{nb(points, 0)} punkter")
        a = sum(((f["metadata"].get("extent") or {}).get("maxx", 0) - (f["metadata"].get("extent") or {}).get("minx", 0))
                * ((f["metadata"].get("extent") or {}).get("maxy", 0) - (f["metadata"].get("extent") or {}).get("miny", 0))
                for f in files)
        if a > 0:
            parts.append(f"ca. {area(a)}")
        if any(f.get("delivery_notes") for f in files):
            parts.append("med leveransenotat")
        return " · ".join(parts)
    md = files[0]["metadata"]
    q = md.get("quality") or {}
    d = md.get("details") or {}
    prof = files[0].get("content") or {}
    facts = dict(prof.get("facts") or [])
    if prof.get("kind") == "drawing_pdf":
        title = (d.get("title") or "").removeprefix(d.get("drawing_no") or "").strip(" -–:")
        bits = [f"Tegning {d['drawing_no']}" if d.get("drawing_no") else "Tegning (PDF)", title,
                facts.get("Målestokk"), f"rev. {d['revision']}" if d.get("revision") else None]
        return " · ".join(b for b in bits if b)
    if prof.get("kind") == "model":
        return " · ".join(b for b in (f"{md.get('format_version') or 'IFC'}-modell", facts.get("Objekter")) if b)
    if prof.get("kind") in ("report", "document"):
        return " · ".join(b for b in (prof.get("label"), d.get("title"), f"{md.get('count')} sider" if md.get("count") else None) if b)
    parts = [q.get("product_spec") or label]
    n, lbl = md.get("count"), md.get("count_label")
    if data_type == "orthophoto" and q.get("pixel_size_m"):
        parts.append(f"{nb(q['pixel_size_m'])} m piksler")
    elif data_type == "terrain" and q.get("pixel_size_m"):
        parts.append(f"{nb(q['pixel_size_m'], 0)} m rutenett")
    elif lbl == "points" and n:
        parts.append(f"{nb(n, 0)} punkter")
        if q.get("density_pts_per_m2"):
            parts.append(f"{nb(q['density_pts_per_m2'], 1)} pkt/m²")
    elif lbl == "pages" and n:
        if d.get("title"):
            parts.append(str(d["title"]))
        parts.append(f"{n} sider")
    elif lbl == "entities" and n:
        parts.append(f"{n} objekter i {len(d.get('layers') or [])} lag")
    elif lbl in ("objects", "features") and n:
        layers = d.get("layers")
        names = ", ".join(x["name"] for x in layers) if isinstance(layers, list) and layers and isinstance(layers[0], dict) else ""
        parts.append(f"{nb(n, 0)} objekter" + (f" ({names})" if names else ""))
    return " · ".join(dict.fromkeys(parts))


def _extent_and_epsg(files: list[dict]) -> tuple[dict | None, int | None]:
    epsgs = {((f.get("effective") or {}).get("horizontal_epsg") or {}).get("value") for f in files}
    exts = [f["metadata"].get("extent") for f in files if f["metadata"].get("extent")]
    if len(epsgs) != 1 or not exts:
        return None, None
    epsg = epsgs.pop()
    if not isinstance(epsg, int):
        return None, None
    return {"minx": min(e["minx"] for e in exts), "miny": min(e["miny"] for e in exts),
            "maxx": max(e["maxx"] for e in exts), "maxy": max(e["maxy"] for e in exts)}, epsg


def _overlaps(a: dict | None, b: dict | None) -> bool:
    return bool(a and b and min(a["maxx"], b["maxx"]) > max(a["minx"], b["minx"])
                and min(a["maxy"], b["maxy"]) > max(a["miny"], b["miny"]))


def find_predecessor(db, entry: dict) -> dict | None:
    """An earlier, current entry this one looks like a new version of: same data type, same name once
    dates and version words are removed, and overlapping extent when both extents are known."""
    norm = normalize_name(entry["name"])
    if not norm:
        return None
    best = None
    for c in db[dblib.ENTRIES].find({"project_id": entry["project_id"], "lifecycle": "gjeldende",
                                     "data_type": entry.get("data_type")}):
        if c["_id"] == entry["_id"] or normalize_name(c["name"]) != norm:
            continue
        if not c.get("received_at") or not entry.get("received_at") or c["received_at"] > entry["received_at"]:
            continue
        if c.get("seq", 0) >= entry.get("seq", 0):
            continue
        if c.get("extent_epsg") and c.get("extent_epsg") == entry.get("extent_epsg") \
                and not _overlaps(c.get("extent"), entry.get("extent")):
            continue
        if best is None or c["received_at"] > best["received_at"]:
            best = c
    return {"id": best["_id"], "seq": best.get("seq"), "name": best["name"]} if best else None


def predecessor_id(entry: dict) -> str | None:
    """The entry this one replaces: chosen by hand, suggested automatically, or none."""
    mode = entry.get("replaces_mode") or "auto"
    if mode == "manual":
        return entry.get("replaces")
    if mode == "auto":
        return (entry.get("replaces_candidate") or {}).get("id")
    return None


def apply_supersession(ctx, entry: dict) -> None:
    """When an entry is put into use, the entry it replaces becomes superseded (utgått); undo otherwise."""
    db = ctx.db
    target = predecessor_id(entry) if entry.get("ready") in READY_FOR_USE and entry.get("lifecycle") == "gjeldende" else None
    for x in db[dblib.ENTRIES].find({"superseded_by.id": entry["_id"]}):
        if x["_id"] != target:
            db[dblib.ENTRIES].update_one({"_id": x["_id"]}, {"$set": {"lifecycle": "gjeldende", "superseded_by": None,
                                                                      "superseded_at": None}})
    if target:
        t = db[dblib.ENTRIES].find_one({"_id": target})
        if t and t.get("lifecycle") == "gjeldende":
            db[dblib.ENTRIES].update_one({"_id": target}, {"$set": {
                "lifecycle": "utgatt", "superseded_at": ctx.now(),
                "superseded_by": {"id": entry["_id"], "seq": entry.get("seq"), "name": entry["name"]}}})


def refresh(ctx, entry_id: str) -> tuple[dict, list[dict]]:
    """Recompute an entry from its files and sync its questions. Returns (entry, new questions)."""
    db = ctx.db
    e = db[dblib.ENTRIES].find_one({"_id": entry_id})
    files = sorted(db[dblib.FILES].find({"entry_id": entry_id}), key=lambda f: f["file_name"].lower())
    if not files:
        return e, []
    project = db[dblib.PROJECTS].find_one({"_id": e["project_id"]}) or {}
    data_type = Counter(f.get("data_type") or f.get("data_type_guess") for f in files).most_common(1)[0][0]
    formats = Counter(_fmt(f["metadata"]) for f in files)
    ext, epsg = _extent_and_epsg(files)
    updates = {
        "file_ids": [f["_id"] for f in files],
        "file_count": len(files),
        "data_type": data_type,
        "file_types": ", ".join(f"{k} ({n})" if n > 1 else k for k, n in formats.most_common()),
        "received_at": min((f.get("uploaded_at") for f in files if f.get("uploaded_at")), default=e.get("created_at")),
        "uploader": files[0].get("uploaded_by") or {},
        "content_auto": content_text(e, files, data_type),
        "check_result": worst([f.get("check_result", "ok") for f in files]),
        "deviations": sorted({r for f in files for r in f.get("deviations", [])}),
        "flags": sum(f.get("flags", 0) for f in files),
        "extent": ext, "extent_epsg": epsg,
        "updated_at": ctx.now(),
    }
    if not e.get("discipline"):
        hint = next(((f.get("metadata") or {}).get("details", {}).get("discipline_hint") for f in files
                     if (f.get("metadata") or {}).get("details", {}).get("discipline_hint")), None)
        updates["discipline"] = discipline_for(project, data_type, e["name"], hint)
    merged = {**e, **updates}
    if (e.get("replaces_mode") or "auto") == "auto":
        updates["replaces_candidate"] = find_predecessor(db, merged)
        merged["replaces_candidate"] = updates["replaces_candidate"]
    created, open_count = qlib.sync_entry(db, merged, files, ctx.now())
    updates["open_questions"] = open_count
    db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$set": updates})
    entry = db[dblib.ENTRIES].find_one({"_id": entry_id})
    if entry.get("ready") in READY_FOR_USE:
        apply_supersession(ctx, entry)
    return entry, created


def is_surface_entry(entry: dict) -> bool:
    """Terrain models and point clouds take part in reference comparisons."""
    return entry.get("data_type") in SURFACE_TYPES
