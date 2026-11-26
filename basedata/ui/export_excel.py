"""Export a project's register to Excel, with the same columns as the register page.

Sheets: Register (one row per entry), Filer (every file, including those inside packages), Kontroller,
Spørsmål and Regelsett.
"""

from __future__ import annotations

import io
from pathlib import Path
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from basedata.indata import crs as crslib
from basedata.core import db as dblib
from basedata.harness import entries as entrylib
from basedata.core.classify import DATA_TYPES, disciplines
from basedata.harness.evaluate import get_ruleset
from basedata.harness.questions import FIELD_LABELS
from basedata.harness.rules import CHECK_KINDS
from basedata.core.settings import Settings
from basedata.core.text import LIFECYCLE, QA_STATUS, READY, RESULT_LABELS

RESULT_FILL = {"ok": "E2EFDA", "warning": "FFF2CC", "missing_info": "DDEBF7", "needs_review": "EDEDED", "deviation": "F8CBAD"}
QA_FILL = {"ikke_begynt": "BDD7EE", "pagar": "FFF59D", "utfort": "A9D08E"}
READY_FILL = {"ja": "A9D08E", "med_forbehold": "FFE699", "nei": "F4B183"}
HEADER_FILL = PatternFill("solid", fgColor="1F3A44")
HEADER_FONT = Font(bold=True, color="FFFFFF")
DATE_FMT = "dd.mm.yyyy"

REGISTER_COLUMNS = [
    ("Rekkefølge", 10), ("Dokumentnavn/Pakke", 34), ("Innhold i fil/folder", 44), ("Filtype", 14), ("Dato mottatt", 12),
    ("Mottatt fra", 18), ("Lenke", 30), ("Ansvarlig fag for KS", 12), ("Status kontroll", 13), ("Dato kontrollert", 12),
    ("Er dokument/fil klar til bruk?", 16), ("Automatisk kontroll", 14), ("Regler med merknad", 30), ("Åpne spørsmål", 9),
    ("Gjeldende/utgått", 11), ("Erstatter", 26), ("Erstattet av", 26), ("KS-merknad", 40), ("Kommentar til beslutning", 40),
    ("Antall filer", 8), ("Leveranse", 10), ("Manuelle korreksjoner", 44), ("Kommentarer", 60),
]


def _sheet(wb: Workbook, title: str, columns: list[tuple[str, int]], first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append([c for c, _ in columns])
    for i, (_, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
        cell = ws.cell(row=1, column=i)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "C2" if first else "A2"
    return ws


def _d(v):
    """A date for Excel (no time zone), or None."""
    return v.replace(tzinfo=None) if isinstance(v, datetime) else v


def _fill(cell, colour: str | None) -> None:
    if colour:
        cell.fill = PatternFill("solid", fgColor=colour)


def _link(settings: Settings, entry_id: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}/#entry-{entry_id}"


def source_location(db, project: dict, e: dict) -> Path | None:
    """Hvor registreringen ligger i kildemappa: fila, eller mappa for en pakke."""
    root = str(project.get("source_folder") or "").strip()
    if not root:
        return None
    if e.get("kind") == "package":
        parts = [p for p in (e.get("delivery_id"), e.get("folder")) if p and not str(p).startswith("(")]
        return Path(root, *parts) if parts else Path(root)
    f = db[dblib.FILES].find_one({"entry_id": e["_id"]}) or {}
    return Path(root, f["source_path"]) if f.get("source_path") else None


def _file_link(db, project: dict, e: dict) -> str:
    loc = source_location(db, project, e)
    if loc is None:
        return ""
    try:
        return loc.resolve().as_uri()
    except ValueError:
        return ""


def _corrections(db, e: dict) -> str:
    """Manual corrections of values, texts and rule results, one per line."""
    lines = []
    f = db[dblib.FILES].find_one({"entry_id": e["_id"]}) or {}
    for field in e.get("corrected_fields") or []:
        u = (f.get("uploader_values") or {}).get(field) or {}
        lines.append(f"{FIELD_LABELS.get(field, field)}: {u.get('raw')} ({u.get('by_name') or u.get('by')}"
                     + (f": {u['comment']}" if u.get("comment") else "") + ")")
    for field, o in (e.get("text_overrides") or {}).items():
        lines.append(f"{'Beskrivelse' if field == 'summary' else 'Innhold'}: {o['value']} ({o.get('by_name')})")
    for rule, o in (e.get("check_overrides") or {}).items():
        lines.append(f"{rule} → {RESULT_LABELS.get(o['result'], o['result'])} ({o.get('by_name')}: {o.get('comment')})")
    return "\n".join(lines)


def export_project(db, project_id: str, settings: Settings | None = None) -> bytes:
    """Build the workbook for one project and return its bytes."""
    settings = settings or Settings()
    project = db[dblib.PROJECTS].find_one({"_id": project_id}) or {"_id": project_id}
    es = sorted(db[dblib.ENTRIES].find({"project_id": project_id}),
                key=lambda e: (e.get("received_at") or e.get("created_at"), e.get("seq", 0)))
    by_id = {e["_id"]: e for e in es}
    wb = Workbook()

    reg = _sheet(wb, "Register", REGISTER_COLUMNS, first=True)
    for e in es:
        rev = e.get("review") or {}
        pid = entrylib.predecessor_id(e)
        prev = by_id.get(pid) if pid else None
        sup = e.get("superseded_by") or {}
        link = _file_link(db, project, e) or _link(settings, e["_id"])
        reg.append([
            e.get("seq"), e["name"], e.get("content_override") or e.get("content_auto"), e.get("file_types"),
            _d(e.get("received_at")), e.get("received_from_override") or (e.get("uploader") or {}).get("name"), link,
            e.get("discipline"), QA_STATUS.get(e.get("qa_status"), ""), _d(e.get("qa_date")),
            READY.get(e.get("ready"), ""), RESULT_LABELS.get(e.get("check_result"), ""), ", ".join(e.get("deviations", [])),
            e.get("open_questions", 0), LIFECYCLE.get(e.get("lifecycle"), ""),
            f"#{prev.get('seq')} {prev['name']}" if prev else "", f"#{sup.get('seq')} {sup.get('name')}" if sup else "",
            e.get("qa_note") or "", rev.get("comment") or "", e.get("file_count", 0), e.get("delivery_id"),
            _corrections(db, e), "\n".join(f"{_d(c.get('at')):%d.%m.%Y} {c.get('by_name') or c.get('by')}: {c['text']}"
                                             if isinstance(_d(c.get("at")), datetime) else f"{c.get('by_name')}: {c['text']}"
                                             for c in e.get("comments") or []),
        ])
        r = reg.max_row
        for col in (5, 10):
            reg.cell(row=r, column=col).number_format = DATE_FMT
        if link.startswith(("http", "file:")):
            reg.cell(row=r, column=7).hyperlink = link
        _fill(reg.cell(row=r, column=9), QA_FILL.get(e.get("qa_status")))
        _fill(reg.cell(row=r, column=11), READY_FILL.get(e.get("ready")))
        _fill(reg.cell(row=r, column=12), RESULT_FILL.get(e.get("check_result")))
        if e.get("lifecycle") == "utgatt":
            for col in range(1, len(REGISTER_COLUMNS) + 1):
                reg.cell(row=r, column=col).font = Font(color="808080", strike=col == 2)
    for row in reg.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    if es:
        last = len(es) + 1
        for formula, col in ((f'"{",".join(disciplines(project))}"', "H"), (f'"{",".join(QA_STATUS.values())}"', "I"),
                             (f'"{",".join(READY.values())}"', "K")):
            dv = DataValidation(type="list", formula1=formula, allow_blank=True)
            reg.add_data_validation(dv)
            dv.add(f"{col}2:{col}{last}")
        reg.auto_filter.ref = f"A1:{get_column_letter(len(REGISTER_COLUMNS))}{last}"

    files = list(db[dblib.FILES].find({"project_id": project_id}))
    files.sort(key=lambda f: ((by_id.get(f.get("entry_id")) or {}).get("seq", 0), f["file_name"].lower()))
    fs = _sheet(wb, "Filer", [("Rekkefølge", 10), ("Registrering", 30), ("Fil", 36), ("Versjon", 8), ("Format", 12),
                              ("Datatype", 18), ("Koordinatsystem", 26), ("Høydesystem", 12), ("Dato", 11), ("Kilde", 26),
                              ("Kvalitet", 30), ("Automatisk kontroll", 14), ("Regler med merknad", 26),
                              ("Middelavvik mot referanse (m)", 14), ("Std (m)", 9), ("Referanse", 32)])
    for f in files:
        e = by_id.get(f.get("entry_id")) or {}
        eff = f.get("effective") or {}
        epsg = (eff.get("horizontal_epsg") or {}).get("value")
        comp = f.get("comparison") or {}
        ref = comp.get("reference") or {}
        md = f.get("metadata") or {}
        fs.append([e.get("seq"), e.get("name"), f["file_name"], f.get("version", 1), md.get("format"),
                   DATA_TYPES.get(f.get("data_type"), ""), crslib.crs_name(epsg) if isinstance(epsg, int) else "Ukjent",
                   (eff.get("height_reference") or {}).get("value"), (eff.get("data_date") or {}).get("value"),
                   (eff.get("source") or {}).get("value"), (eff.get("quality") or {}).get("value"),
                   RESULT_LABELS.get(f.get("check_result"), ""), ", ".join(f.get("deviations", [])),
                   comp.get("mean_m") if comp.get("status") == "done" else None,
                   comp.get("std_m") if comp.get("status") == "done" else None,
                   f"#{ref.get('entry_seq')} {ref.get('file_name')}" if ref else ""])
        _fill(fs.cell(row=fs.max_row, column=12), RESULT_FILL.get(f.get("check_result")))

    chk = _sheet(wb, "Kontroller", [("Rekkefølge", 10), ("Fil", 36), ("Regel", 10), ("Krav", 44), ("Resultat", 13),
                                    ("Belegg", 80), ("Kontrollert av", 12), ("Sikkerhet", 10), ("Til vurdering", 10),
                                    ("Overstyrt", 50)])
    for f in files:
        e = by_id.get(f.get("entry_id")) or {}
        for c in db[dblib.CHECKS].find({"file_id": f["_id"], "run_id": f.get("last_run_id")}):
            chk.append([e.get("seq"), f["file_name"], c["rule_id"], c["rule_text"], RESULT_LABELS.get(c["result"], c["result"]),
                        c["evidence"], {"code": "kode"}.get(c["checked_by"], c["checked_by"]), c.get("confidence"),
                        "ja" if c.get("flagged_for_review") else "",
                        (f"fra {RESULT_LABELS.get(c['override']['original'])} av {c['override'].get('by')}: {c['override'].get('comment')}"
                         if c.get("override") else "")])
            _fill(chk.cell(row=chk.max_row, column=5), RESULT_FILL.get(c["result"]))

    qs = _sheet(wb, "Spørsmål", [("Rekkefølge", 10), ("Registrering", 30), ("Felt", 18), ("Spørsmål", 60), ("Status", 10),
                                 ("Svar", 34), ("Spurt", 11), ("Besvart", 11), ("Opplaster", 26)])
    for q in db[dblib.QUESTIONS].find({"project_id": project_id, "status": {"$in": ["open", "answered"]}}).sort("asked_at"):
        qs.append([q.get("entry_seq"), q.get("entry_name"), FIELD_LABELS.get(q["field"], q["field"]), q["question"],
                   {"open": "åpent", "answered": "besvart"}.get(q["status"]), q.get("answer") or "",
                   _d(q.get("asked_at")), _d(q.get("answered_at")), q.get("uploader_email")])
        for col in (7, 8):
            qs.cell(row=qs.max_row, column=col).number_format = DATE_FMT

    rs = get_ruleset(db, project)
    rules = _sheet(wb, "Regelsett", [("Regel", 11), ("Krav", 50), ("Kilde", 34), ("Gjelder for", 40), ("Kontrolleres av", 13),
                                     ("Ved brudd", 13), ("Aktiv", 7)])
    for r in rs.get("rules", []):
        rules.append([r["id"], r["text"], r.get("source", ""),
                      ", ".join("alle" if a == "all" else DATA_TYPES.get(a, a) for a in r.get("applies_to", [])),
                      CHECK_KINDS.get(r.get("check"), r.get("check")), RESULT_LABELS.get(r.get("if_failed"), ""),
                      "ja" if r.get("active", True) else "nei"])
    rules.append([])
    rules.append([f"Regelsett {rs.get('version')}", rs.get("title", ""), f"Prosjekt: {project.get('name', project_id)}"])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
