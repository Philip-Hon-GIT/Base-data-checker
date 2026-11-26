"""Kjør kontrollen lokalt på én mappe: `python -m basedata start "C:\\...\\Grunnlagsdata"`.

- Registeret lagres i `_basedata/register.db` i mappa (eller der `--store` peker).
- Første gang opprettes et prosjekt for mappa med standardinnstillinger og standardregelsettet.
  Innstillingene (koordinatsystem, prosjektområde, formater …) endres i appen.
- Mappa leses med en gang, og deretter hvert `scan_minutes` minutt mens appen er åpen.
- Du er innlogget som deg selv (Windows-brukernavnet) med rollen KS-ansvarlig.
"""

from __future__ import annotations

import getpass
import re
import threading
from pathlib import Path

from basedata.core import db as dblib
from basedata.harness.rules import load_default_ruleset
from basedata.core.settings import Settings
from basedata.harness.worker import Context, run_once

DEFAULT_PROJECT = {
    "project_type": "Veg",
    "phase": "Reguleringsplan",
    "horizontal_crs": "EPSG:25832",
    "height_reference": "NN2000",
    "accepted_formats": ["sos", "gml", "gpkg", "geojson", "shp", "tif", "tiff", "las", "laz", "dxf", "ifc", "xml", "pdf"],
    "max_data_age_years": 10,
    "question_reminder_days": 5,
    "package_threshold": 5,
    "disciplines": ["VEG", "VA", "KON", "GEO", "LARK", "ELE"],
    "project_area": [],
}


def local_user(settings: Settings) -> dict:
    """Den som kjører appen: navn fra innstillingene eller Windows-brukernavnet, med rollen KS-ansvarlig."""
    name = settings.user_name
    if not name:
        try:
            login = getpass.getuser()
        except Exception:  # noqa: BLE001 – brukernavnet er bare pynt
            login = "lokal bruker"
        name = login.replace(".", " ").replace("_", " ").title()
    return {"name": name, "email": (settings.user_email or "").lower(), "roles": ["reviewer"], "role_label": "KS-ansvarlig"}


def project_id_for(folder: Path) -> str:
    """En prosjekt-ID ut fra mappenavnet (eller mappa over hvis den heter «Grunnlagsdata»)."""
    name = folder.name
    if name.lower() in ("grunnlagsdata", "basedata", "base data") and folder.parent.name:
        name = folder.parent.name
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "prosjekt"


def ensure_project(db, folder: Path, project_id: str | None = None, name: str | None = None) -> dict:
    """Prosjektet som bruker `folder` som kildemappe; opprettes med standardverdier første gang."""
    from basedata.ui.service import validate_settings

    folder = folder.expanduser().resolve()
    projects = db[dblib.PROJECTS]
    for p in projects.find({}):
        if p.get("source_folder") and Path(p["source_folder"]).expanduser().resolve() == folder:
            return p
    pid = project_id or project_id_for(folder)
    if projects.find_one({"_id": pid}):
        projects.update_one({"_id": pid}, {"$set": {"source_folder": str(folder)}})
        return projects.find_one({"_id": pid})
    values = {**DEFAULT_PROJECT, "name": name or (folder.parent.name if folder.name.lower() == "grunnlagsdata" else folder.name),
              "source_folder": str(folder)}
    clean = validate_settings(values)
    rs = load_default_ruleset()
    doc = {"_id": pid, **clean, "active_ruleset": rs["version"], "created_at": dblib.now()}
    projects.insert_one(doc)
    rs.update({"_id": f"{pid}:{rs['version']}", "project_id": pid, "approved_by": "standard", "approved_at": dblib.now(),
               "note": "Første versjon, fra standardregelsettet."})
    db[dblib.RULESETS].replace_one({"_id": rs["_id"]}, rs, upsert=True)
    return projects.find_one({"_id": pid})


def start_scanner(ctx: Context, minutes: int) -> threading.Event | None:
    """Les kildemappene på nytt hvert `minutes` minutt i bakgrunnen. Returnerer et Event som stopper det."""
    if minutes <= 0:
        return None
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(minutes * 60):
            try:
                run = run_once(ctx, trigger="schedule")
                c = run.get("counts") or {}
                if c.get("new") or c.get("new version") or c.get("errors"):
                    print(f"Kildemappa lest: {c.get('new', 0)} nye, {c.get('new version', 0)} nye versjoner, "
                          f"{c.get('errors', 0)} feil.")
            except Exception as exc:  # noqa: BLE001 – en feil skal ikke stoppe neste gjennomgang
                print(f"Feil under lesing av kildemappa: {type(exc).__name__}: {exc}")

    threading.Thread(target=loop, name="basedata-scanner", daemon=True).start()
    return stop
