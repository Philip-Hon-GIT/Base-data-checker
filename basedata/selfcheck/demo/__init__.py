"""Demo: synthetic deliveries, an in-memory database, and a scripted QA history."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from basedata.core import db as dblib
from basedata.ui import service
from basedata.core.settings import Settings
from basedata.core.memory_mongo import MemoryDatabase
from basedata.harness.worker import Context, make_context, run_once
from basedata.selfcheck.demo.samples import KARI, OLA

REVIEWER = {"name": "Ingrid Berg", "email": "ingrid.berg@example.com", "roles": ["reviewer"], "role_label": "KS-ansvarlig VEG"}
USERS = [
    REVIEWER,
    {**KARI, "roles": [], "role_label": "opplaster"},
    {**OLA, "roles": [], "role_label": "opplaster"},
]
BANNER = ("Demo med syntetiske data for et oppdiktet prosjekt. AI-resultatene kommer fra en regelbasert erstatning, "
          "ikke en AI-modell. Ingenting du gjør her lagres.")


def build_demo(folder: Path | None = None, history: bool = True) -> Context:
    """The sample deliveries in a source folder, checked into an in-memory register, plus a realistic QA history."""
    from basedata.selfcheck.demo.seed import seed

    db = MemoryDatabase("demo")
    settings = Settings(ai_provider="offline_demo", app_base_url="")
    folder = folder or Path(tempfile.gettempdir()) / "basedata_demo_samples"
    seed(db, settings, folder)
    ctx = make_context(db, settings)
    run_once(ctx, trigger="schedule")
    if history:
        script_history(ctx)
    return ctx


def _entry(ctx: Context, name: str) -> dict:
    return ctx.db[dblib.ENTRIES].find_one({"name": name})


def _at(ctx: Context, when: datetime):
    real = ctx.now
    ctx.now = lambda: when
    return real


def script_history(ctx: Context) -> None:
    """September: the FKB and the 2021 terrain model are approved. November: the new FKB replaces the old one,
    and the FKB-Veg file in UTM33 is being followed up with the supplier."""
    real = ctx.now
    try:
        ctx.now = lambda: datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc)
        service.decide(ctx, REVIEWER, _entry(ctx, "FKB_Bygning_2025.sos")["_id"], "ja", "Kontrollert mot ortofoto. OK.")
        ctx.now = lambda: datetime(2026, 9, 10, 9, 30, tzinfo=timezone.utc)
        service.decide(ctx, REVIEWER, _entry(ctx, "Terrengmodell_DTM2_2021.tif")["_id"], "ja",
                       "Godkjent som referanse for terrengdata i prosjektet.")
        ctx.now = lambda: datetime(2026, 11, 2, 10, 15, tzinfo=timezone.utc)
        service.decide(ctx, REVIEWER, _entry(ctx, "FKB_Bygning_2026.sos")["_id"], "ja",
                       "Ny FKB-Bygning med 6 nye bygg. Erstatter #1.")
        ctx.now = lambda: datetime(2026, 11, 3, 8, 40, tzinfo=timezone.utc)
        service.update_qa(ctx, REVIEWER, _entry(ctx, "FKB_Veg_2026.sos")["_id"],
                          {"qa_status": "pagar", "qa_note": "Levert i UTM33. Har bedt Kartverket om ny leveranse i UTM32."})
    finally:
        ctx.now = real
