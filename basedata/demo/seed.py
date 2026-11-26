"""Legg de syntetiske leveransene i en kildemappe slik en prosjektmappe på OneDrive ville sett ut."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .. import db as dblib
from ..folder_source import write_delivery_file
from ..rules import load_default_ruleset
from ..settings import Settings
from .samples import PROJECT, build_samples


def delivery_folder_name(item: dict) -> str:
    """Leveransemappa, for eksempel «2026-10-27 D-101»."""
    return f"{item['uploaded_at']:%Y-%m-%d} {item['delivery_id']}"


def _place(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.stat().st_size == src.stat().st_size and dest.stat().st_mtime_ns >= src.stat().st_mtime_ns:
            return
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def build_source_folder(samples: Path, source: Path) -> list[dict]:
    """Skriv eksempelfilene (én gang) og legg dem i leveransemapper med levering.yaml i `source`."""
    items = build_samples(samples)
    written = set()
    for item in items:
        delivery = source / delivery_folder_name(item)
        sub = delivery / item["folder"] if item.get("folder") else delivery
        _place(item["path"], sub / item["filename"])
        if delivery not in written:
            write_delivery_file(delivery, item["uploaded_by"], item["uploaded_at"])
            written.add(delivery)
    return items


def seed(db, settings: Settings, samples: Path, source: Path | None = None) -> list[dict]:
    """Bygg kildemappa, og legg prosjektet (med kildemappa) og regelsettet i databasen."""
    source = source or samples.with_name(samples.name + "_kildemappe")
    items = build_source_folder(samples, source)
    dblib.ensure_indexes(db)
    db[dblib.PROJECTS].replace_one({"_id": PROJECT["_id"]}, {**PROJECT, "source_folder": str(source)}, upsert=True)
    rs = load_default_ruleset()
    rs.update({"_id": f"{PROJECT['_id']}:{rs['version']}", "project_id": PROJECT["_id"],
               "approved_by": "Ingrid Berg", "approved_at": dblib.now(), "note": "Første versjon, fra standardregelsettet."})
    db[dblib.RULESETS].replace_one({"_id": rs["_id"]}, rs, upsert=True)
    return items
