"""The background worker: find new or changed files in the source folder, read them, check them, register them, ask.

`python -m basedata start` runs it every few minutes while the app is open; or run it by hand:
    python -m basedata run --folder "C:\\...\\Grunnlagsdata"

Files are grouped by delivery and folder. A folder with at least `package_threshold` files (a project
setting) becomes one package row in the register, but every file in it is still read and checked.
"""

from __future__ import annotations

import hashlib
import tempfile
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from basedata.indata import footprint as footprintlib
from basedata import __version__
from basedata.core import db as dblib
from basedata.harness import entries as entrylib
from basedata.indata import surface as surfacelib
from basedata.core.classify import guess
from basedata.harness.evaluate import evaluate
from basedata.indata.extract import NOTE_EXTS, SIDECAR_EXTS, extract, stem_of, suffix_of
from basedata.indata.extract.documents import read_text_file
from basedata.indata.folder_source import FolderSource, SourceFile
from basedata.harness.notify import Notifier, StoreNotifier, questions_message
from basedata.core.settings import Settings

RUN_LOCK = threading.Lock()  # bare én gjennomgang av kildemappa om gangen (planlagt eller «Kjør nå»)


@dataclass
class Context:
    """What the worker and the web pages share: database, settings, the source folder and the notifier."""

    db: object
    settings: Settings
    source: FolderSource
    notifier: Notifier
    now: Callable[[], datetime] = field(default=dblib.now)


def make_context(db, settings: Settings, notifier: Notifier | None = None,
                 now: Callable[[], datetime] | None = None) -> Context:
    """Build a Context with the default store-only notifier."""
    return Context(db, settings, FolderSource(db, settings), notifier or StoreNotifier(db), now or dblib.now)


def _group(items: list[SourceFile]) -> dict[str, dict]:
    """Split each delivery into main files by folder, sidecars (by name stem) and delivery notes."""
    deliveries: dict[str, dict] = defaultdict(lambda: {"main": defaultdict(list), "sidecars": defaultdict(list),
                                                       "notes": [], "first": None})
    for it in items:
        d = deliveries[it.delivery_id]
        if it.uploaded_at and (d["first"] is None or it.uploaded_at < d["first"]):
            d["first"] = it.uploaded_at
        ext = suffix_of(it.filename)
        if ext in NOTE_EXTS:
            d["notes"].append(it)
        elif ext in SIDECAR_EXTS:
            d["sidecars"][stem_of(it.filename).lower()].append(it)
        else:
            d["main"][it.folder].append(it)
    return deliveries


def _texts(ctx: Context, notes: list[SourceFile], tmp: Path, cache: dict) -> list[dict]:
    out = []
    for n in notes:
        if n.key not in cache:
            p = tmp / f"note_{hashlib.sha1(n.key.encode('utf-8')).hexdigest()[:12]}{suffix_of(n.filename)}"
            ctx.source.download(n, p)
            cache[n.key] = read_text_file(p, ctx.settings.max_text_excerpt_chars)
        out.append({"name": n.filename, "kind": "leveransenotat", "text": cache[n.key]})
    return out


def notify_questions(ctx: Context, created: list[dict]) -> None:
    """One message per uploader listing their new questions."""
    by_person: dict[str, list[dict]] = defaultdict(list)
    for q in created:
        if q.get("uploader_email"):
            by_person[q["uploader_email"]].append(q)
    for email, qs in by_person.items():
        if not any(not q.get("optional") for q in qs):
            continue
        who = {"name": qs[0]["uploader_name"], "email": email}
        subject, body, link = questions_message(ctx.settings, who, qs)
        ctx.notifier.send(who, subject, body, link, "questions")


def process(ctx: Context, item: SourceFile, sidecars: list[SourceFile], notes: list[SourceFile],
            run_id: str, note_cache: dict, force: bool = False) -> tuple[str, str]:
    """Register or update one file and check it. Returns (what happened, file id)."""
    files = ctx.db[dblib.FILES]
    existing = files.find_one({"source_key": item.key})
    fingerprint = "|".join([item.fingerprint] + sorted(s.fingerprint for s in sidecars) + sorted(n.fingerprint for n in notes))
    if existing and existing.get("fingerprint") == fingerprint and not force:
        return "skipped", existing["_id"]
    now = ctx.now()
    with tempfile.TemporaryDirectory(prefix="basedata_") as tmpdir:
        tmp = Path(tmpdir)
        main_path = tmp / item.filename
        sha = ctx.source.download(item, main_path)
        stem = stem_of(item.filename)
        for s in sidecars:
            ctx.source.download(s, tmp / (stem + suffix_of(s.filename)))
        md = extract(main_path)
        mdd = md.to_dict()
        changed_content = existing is None or existing.get("hash") != sha
        surf = surfacelib.build(main_path, mdd) if changed_content else None
        texts = _texts(ctx, notes, tmp, note_cache)
    if md.text_excerpt:
        texts = [{"name": item.filename, "kind": "tekst i fila", "text": md.text_excerpt}] + texts
    dtype, reason = guess(item.filename, mdd)
    base = {"metadata": mdd, "data_type_guess": dtype, "data_type_reason": reason, "context_texts": texts,
            "sidecars": [s.filename for s in sidecars], "delivery_notes": [n.filename for n in notes],
            "fingerprint": fingerprint, "size": item.length, "uploaded_at": item.uploaded_at,
            "uploaded_by": item.uploaded_by, "delivery_id": item.delivery_id, "folder": item.folder, "source_path": item.rel_path, "updated_at": now}
    if changed_content:
        if existing:
            surfacelib.delete(ctx.db, existing.get("surface"))
        base["surface"] = surfacelib.save(ctx.db, surf, item.filename) if surf else None
        if surf is not None and mdd.get("data_type_hint") != "point_cloud" and suffix_of(item.filename) not in (".las", ".laz"):
            fp = footprintlib.from_mask(np.isfinite(surf.z), surf.x0, surf.y0, surf.cell, "høydeceller med data")
            if fp:
                mdd["footprint"] = fp
    elif existing and not mdd.get("footprint") and (existing.get("metadata") or {}).get("footprint"):
        mdd["footprint"] = existing["metadata"]["footprint"]
    if existing is None:
        doc = {"_id": dblib.new_id("bdf"), "source_key": item.key, "source_path": item.rel_path,
               "project_id": item.project_id, "file_name": item.filename, "ext": suffix_of(item.filename),
               "hash": sha, "version": 1, "uploader_values": {}, "entry_id": None, "history": [],
               "check_result": "pending", "created_at": now, **base}
        files.insert_one(doc)
        what = "new"
    elif changed_content:
        hist = {"version": existing.get("version", 1), "hash": existing.get("hash"), "uploaded_at": existing.get("uploaded_at"),
                "check_result": existing.get("check_result"), "uploader_values": existing.get("uploader_values"),
                "replaced_at": now}
        files.update_one({"_id": existing["_id"]}, {
            "$set": {**base, "hash": sha, "version": existing.get("version", 1) + 1, "uploader_values": {},
                     "file_name": item.filename, "comparison": None},
            "$push": {"history": hist}})
        doc = files.find_one({"_id": existing["_id"]})
        what = "new version"
        _reset_entry_review(ctx, doc, now)
    else:
        files.update_one({"_id": existing["_id"]}, {"$set": base})
        doc = files.find_one({"_id": existing["_id"]})
        what = "updated"
    evaluate(ctx, doc, run_id)
    return what, doc["_id"]


def _reset_entry_review(ctx: Context, fdoc: dict, now) -> None:
    """A replaced file sends its entry back to QA; the earlier decision is kept in the entry history."""
    eid = fdoc.get("entry_id")
    e = ctx.db[dblib.ENTRIES].find_one({"_id": eid}) if eid else None
    if not e:
        return
    hist = {"at": now, "event": f"Ny versjon av {fdoc['file_name']} mottatt", "ready": e.get("ready"),
            "qa_status": e.get("qa_status"), "review": e.get("review")}
    ctx.db[dblib.ENTRIES].update_one({"_id": eid}, {"$set": {"ready": None, "review": None, "qa_status": "ikke_begynt",
                                                             "qa_date": None}, "$push": {"history": hist}})
    ctx.db[dblib.QUESTIONS].update_many({"entry_id": eid, "status": "open"},
                                        {"$set": {"status": "withdrawn", "withdrawn_at": now}})
    entrylib.apply_supersession(ctx, ctx.db[dblib.ENTRIES].find_one({"_id": eid}))


def run_once(ctx: Context, trigger: str = "schedule", project_id: str | None = None, force: bool = False) -> dict:
    """One pass over the source folders. Safe to run as often as you like."""
    if not ctx.settings.enabled:
        return {"skipped": "BASEDATA_ENABLED er av"}
    if not RUN_LOCK.acquire(blocking=False):
        return {"skipped": "busy", "counts": {}, "message": "En kontroll av kildemappa kjører allerede. Prøv igjen om litt."}
    try:
        return _run_once(ctx, trigger, project_id, force)
    finally:
        RUN_LOCK.release()


def _run_once(ctx: Context, trigger: str, project_id: str | None, force: bool) -> dict:
    runs = ctx.db[dblib.RUNS]
    run = {"_id": dblib.new_id("bdr"), "trigger": trigger, "started_at": ctx.now(), "finished_at": None,
           "counts": {"new": 0, "new version": 0, "updated": 0, "skipped": 0, "errors": 0, "entries_created": 0},
           "errors": [], "questions_created": 0, "app_version": __version__}
    runs.insert_one(run)
    projects = {p["_id"]: p for p in ctx.db[dblib.PROJECTS].find({})}
    created_q: list[dict] = []
    note_cache: dict = {}
    deliveries = _group(ctx.source.list_files(project_id))
    for delivery, parts in sorted(deliveries.items(), key=lambda kv: (kv[1]["first"] is None, kv[1]["first"] or 0, kv[0])):
        for folder, mains in sorted(parts["main"].items()):
            mains = sorted(mains, key=lambda it: it.filename.lower())
            pid = mains[0].project_id
            threshold = int((projects.get(pid) or {}).get("package_threshold") or 5)
            file_ids, changed = [], False
            for item in mains:
                sidecars = parts["sidecars"].get(stem_of(item.filename).lower(), [])
                try:
                    what, fid = process(ctx, item, sidecars, parts["notes"], run["_id"], note_cache, force)
                    run["counts"][what] += 1
                    file_ids.append(fid)
                    changed |= what != "skipped"
                except Exception as exc:  # one broken file must not stop the others
                    run["counts"]["errors"] += 1
                    run["errors"].append({"file": item.filename, "error": f"{type(exc).__name__}: {exc}"})
            eids, new_eids = entrylib.register_group(ctx, pid, delivery, folder, file_ids, len(mains) >= threshold)
            run["counts"]["entries_created"] += len(new_eids)
            for eid in dict.fromkeys(eids):
                if changed or eid in new_eids:
                    created_q += entrylib.refresh(ctx, eid)[1]
    notify_questions(ctx, created_q)
    run.update({"finished_at": ctx.now(), "questions_created": len(created_q)})
    runs.replace_one({"_id": run["_id"]}, run)
    return run


def recheck_entry(ctx: Context, entry_id: str, trigger: str = "recheck", notify: bool = True) -> dict:
    """Re-run the checks on every file in an entry with stored metadata (after an answer or a change)."""
    db = ctx.db
    entry = db[dblib.ENTRIES].find_one({"_id": entry_id})
    if entry is None:
        raise KeyError(entry_id)
    run = {"_id": dblib.new_id("bdr"), "trigger": trigger, "entry_id": entry_id, "started_at": ctx.now(),
           "counts": {"rechecked": 0}, "errors": [], "app_version": __version__}
    db[dblib.RUNS].insert_one(run)
    for f in db[dblib.FILES].find({"entry_id": entry_id}):
        evaluate(ctx, f, run["_id"])
        run["counts"]["rechecked"] += 1
    entry, created = entrylib.refresh(ctx, entry_id)
    if notify:
        notify_questions(ctx, created)
    db[dblib.RUNS].update_one({"_id": run["_id"]}, {"$set": {"finished_at": ctx.now(), "counts": run["counts"],
                                                             "questions_created": len(created)}})
    return entry


def recheck_project(ctx: Context, project_id: str, trigger: str = "settings", only_surfaces_pending: bool = False) -> int:
    """Re-check every entry in a project, oldest first (after a settings or rule-set change)."""
    n = 0
    for e in ctx.db[dblib.ENTRIES].find({"project_id": project_id}).sort("seq"):
        if only_surfaces_pending and (not entrylib.is_surface_entry(e) or e.get("ready") in entrylib.READY_FOR_USE):
            continue
        recheck_entry(ctx, e["_id"], trigger)
        n += 1
    return n
