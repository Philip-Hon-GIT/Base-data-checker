"""Kilden for grunnlagsdata: en vanlig mappe på PC-en, gjerne en OneDrive- eller SharePoint-synkronisert mappe.

Dette er den eneste koden som vet hvordan filene ligger. Slik leses mappa:

    Grunnlagsdata/                       ← prosjektets kildemappe (Prosjektinnstillinger → Kildemappe)
      2026-10-27 Kartverket FKB/         ← én undermappe = én leveranse
        levering.yaml                    ← valgfri: hvem som leverte og når
        FKB_Bygning_2026.sos
        FKB_Veg_2026.sos
      2026-10-29 Laserdata/
        Laserdata_Nordby_2026/           ← mappe inne i leveransen; mange filer blir én pakke
          blokk1.las ...
      Notat.pdf                          ← filer rett i kildemappa: én leveranse per dag
      _basedata/                         ← registeret (SQLite); hoppes over

Mottatt dato: `mottatt` i levering.yaml, ellers datoen først i mappenavnet (ÅÅÅÅ-MM-DD), ellers
filens endringstid. Mottatt fra: `mottatt_fra` (og `epost`) i levering.yaml, ellers «Ukjent» – verdien
kan rettes i appen.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from basedata.core import db as dblib
from basedata.core.settings import STORE_DIR, Settings

CHUNK = 1024 * 1024
DELIVERY_FILE = "levering.yaml"
IGNORE_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", DELIVERY_FILE, "levering.yml"}
IGNORE_SUFFIXES = (".tmp", ".partial", ".crdownload", ".lock", ".bak")
DATE_PREFIX = re.compile(r"^(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})\b")
ROOT_DELIVERY = "(rett i kildemappa)"


@dataclass
class SourceFile:
    """Én fil i kildemappa, i samme form som resten av kontrollen forventer."""

    key: str             # "<prosjekt-id>:<relativ sti>", brukt overalt i kontrollen
    path: Path           # full sti på disken
    rel_path: str        # sti relativt til kildemappa, med /
    filename: str
    project_id: str | None
    uploaded_by: dict    # {"name", "email"}
    uploaded_at: datetime | None
    delivery_id: str     # navnet på leveransemappa
    folder: str          # undermappe inne i leveransen ("" når fila ligger rett i leveransen)
    length: int | None
    fingerprint: str     # endres når fila endres


def person(value, email: str = "") -> dict:
    """«Kari Nordmann <kari@firma.no>», en e-post eller et navn → {"name", "email"}."""
    if isinstance(value, dict):
        email = value.get("email") or value.get("epost") or email
        value = value.get("name") or value.get("navn") or ""
    text = str(value or "").strip()
    m = re.match(r"^(.*?)\s*<([^>]+@[^>]+)>$", text)
    if m:
        text, email = m.group(1).strip(), m.group(2)
    elif "@" in text and " " not in text:
        email, text = text, text.split("@")[0].replace(".", " ").title()
    email = str(email or "").strip().lower()
    return {"name": text or email or "Ukjent", "email": email}


def _as_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if hasattr(value, "year") and hasattr(value, "month"):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            return _as_datetime(datetime.fromisoformat(value.strip()))
        except ValueError:
            return None
    return None


def _date_from_name(name: str) -> datetime | None:
    m = DATE_PREFIX.match(name)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except ValueError:
        return None


def _skip(rel_parts: tuple[str, ...]) -> bool:
    for part in rel_parts[:-1]:
        if part.startswith((".", "~")) or part.lower() == STORE_DIR.lower():
            return True
    name = rel_parts[-1]
    low = name.lower()
    return name.startswith((".", "~$")) or low in IGNORE_NAMES or low.endswith(IGNORE_SUFFIXES)


def read_delivery_file(folder: Path) -> dict:
    """Innholdet i levering.yaml i en leveransemappe (tomt hvis fila mangler eller ikke kan leses)."""
    for name in (DELIVERY_FILE, "levering.yml"):
        p = folder / name
        if p.is_file():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
            except (OSError, yaml.YAMLError, UnicodeDecodeError):
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def write_delivery_file(folder: Path, sender: dict | None = None, received: datetime | None = None, note: str = "") -> Path:
    """Skriv en levering.yaml (brukes av demoen og testene)."""
    data: dict = {}
    if sender:
        data["mottatt_fra"] = sender.get("name", "")
        if sender.get("email"):
            data["epost"] = sender["email"]
    if received:
        data["mottatt"] = received.isoformat()
    if note:
        data["merknad"] = note
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / DELIVERY_FILE
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


class FolderSource:
    """Leser filene i kildemappa til hvert prosjekt (feltet `source_folder` i prosjektinnstillingene)."""

    def __init__(self, db, settings: Settings):
        self.db = db
        self.settings = settings

    def _roots(self, project_id: str | None = None) -> list[tuple[str, Path]]:
        flt = {"_id": project_id} if project_id else {}
        out = []
        for p in self.db[dblib.PROJECTS].find(flt):
            folder = str(p.get("source_folder") or "").strip()
            if folder:
                out.append((p["_id"], Path(folder).expanduser()))
        return out

    def root_of(self, project_id: str) -> Path | None:
        roots = self._roots(project_id)
        return roots[0][1] if roots else None

    def _scan(self, project_id: str, root: Path) -> list[SourceFile]:
        if not root.is_dir():
            return []
        out = []
        deliveries: dict[str, dict] = {}
        for path in sorted(root.rglob("*")):
            try:
                if not path.is_file():
                    continue
                rel = path.relative_to(root)
                if _skip(rel.parts):
                    continue
                st = path.stat()
            except OSError:  # fila forsvant eller er låst mens vi leste mappa
                continue
            mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            if len(rel.parts) == 1:
                delivery, folder, info, stamp = f"{ROOT_DELIVERY} {mtime.date().isoformat()}", "", {}, ""
                when = mtime
            else:
                delivery, folder = rel.parts[0], "/".join(rel.parts[1:-1])
                if delivery not in deliveries:
                    dfile = root / delivery / DELIVERY_FILE
                    deliveries[delivery] = {"info": read_delivery_file(root / delivery),
                                            "stamp": str(dfile.stat().st_mtime_ns) if dfile.is_file() else ""}
                info, stamp = deliveries[delivery]["info"], deliveries[delivery]["stamp"]
                when = _as_datetime(info.get("mottatt")) or _date_from_name(delivery) or mtime
            who = person(info.get("mottatt_fra"), info.get("epost") or "")
            rel_posix = rel.as_posix()
            out.append(SourceFile(key=f"{project_id}:{rel_posix}", path=path, rel_path=rel_posix, filename=path.name,
                                  project_id=project_id, uploaded_by=who, uploaded_at=when, delivery_id=delivery,
                                  folder=folder, length=st.st_size,
                                  fingerprint=f"{st.st_size}:{st.st_mtime_ns}:{stamp}"))
        return out

    def list_files(self, project_id: str | None = None) -> list[SourceFile]:
        """Alle filer i kildemappene, eventuelt for ett prosjekt."""
        out: list[SourceFile] = []
        for pid, root in self._roots(project_id):
            out += self._scan(pid, root)
        return out

    def get(self, key: str) -> SourceFile | None:
        """Én fil ut fra nøkkelen ("<prosjekt-id>:<relativ sti>")."""
        pid, _, rel = key.partition(":")
        root = self.root_of(pid)
        if root is None:
            return None
        return next((f for f in self._scan(pid, root) if f.rel_path == rel), None)

    def path_of(self, project_id: str, rel_path: str) -> Path | None:
        """Full sti til en fil i kildemappa – bare hvis den faktisk ligger inne i mappa."""
        root = self.root_of(project_id)
        if root is None or not rel_path:
            return None
        p = (root / rel_path).resolve()
        try:
            p.relative_to(root.resolve())
        except ValueError:
            return None
        return p if p.exists() else None

    def download(self, item: SourceFile, dest: Path) -> str:
        """Kopier fila til `dest` (en midlertidig mappe) og returner SHA-256. Originalen endres aldri."""
        h = hashlib.sha256()
        with item.path.open("rb") as src, dest.open("wb") as out:
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                out.write(chunk)
        try:
            shutil.copystat(item.path, dest)
        except OSError:
            pass
        return h.hexdigest()
