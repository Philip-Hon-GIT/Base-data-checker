"""Operations behind the web pages. Framework-free: the Starlette app (or a Flask/Django view) calls these.

`user` is a dict {"name", "email", "roles": [...]} supplied by the host app's login. Roles used:
"reviewer" (QA fields, decisions, project settings, rule sets, running the worker) and "admin"
(everything). Every logged-in user can read the register; uploaders answer questions about their own
deliveries.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from basedata.indata.content import entry_profile
from basedata.harness.relations import for_entry as relations_for
from basedata.harness import ai as ailib
from basedata.indata import crs as crslib
from basedata.core import db as dblib
from basedata.harness import entries as entrylib
from basedata.harness import questions as qlib
from basedata.core.classify import DATA_TYPES, DEFAULT_DISCIPLINE_MAP, disciplines
from basedata.harness.evaluate import get_ruleset
from basedata.harness.rules import BUILTIN, CHECK_KINDS, PARAM_LABELS
from basedata.core.text import LIFECYCLE, QA_STATUS, READY, RESULT_LABELS
from basedata.harness.worker import Context, recheck_entry, recheck_project, run_once

PROJECT_TYPES = ["Veg", "VA", "Bru og konstruksjon", "Jernbane", "Bygg", "Landskap", "Annet"]
PHASES = ["Kommunedelplan", "Reguleringsplan", "Byggeplan", "Som bygget", "Drift og vedlikehold"]
CRS_OPTIONS = [25832, 25833, 25835] + list(range(5105, 5131))
HEIGHT_OPTIONS = ["NN2000", "NN1954"]
FORMAT_OPTIONS = ["sos", "gml", "gpkg", "geojson", "shp", "tif", "tiff", "jp2", "las", "laz", "dxf", "dwg", "ifc",
                  "xml", "pdf", "snd", "kof", "csv"]
FAILED_RESULTS = ["deviation", "warning", "missing_info", "needs_review"]


class Forbidden(PermissionError):
    """The user may not do this."""


class NotFound(KeyError):
    """No such record."""


def jsonable(obj):
    """Make MongoDB documents safe for JSON: dates to ISO text, ObjectIds to strings."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def is_reviewer(user: dict) -> bool:
    """Reviewers and admins handle QA, settings and rule sets."""
    return bool(set(user.get("roles") or []) & {"reviewer", "admin"})


def _require_reviewer(user: dict, what: str) -> None:
    if not is_reviewer(user):
        raise Forbidden(f"Bare KS-ansvarlige kan {what}.")


def options(project: dict) -> dict:
    """Value lists for the pages' dropdowns."""
    return {"data_types": DATA_TYPES, "disciplines": disciplines(project), "qa_status": QA_STATUS, "ready": READY,
            "results": RESULT_LABELS, "lifecycle": LIFECYCLE, "project_types": PROJECT_TYPES, "phases": PHASES,
            "crs": [{"value": f"EPSG:{c}", "label": f"{crslib.short_name(c)} (EPSG:{c})"} for c in CRS_OPTIONS],
            "heights": HEIGHT_OPTIONS, "formats": FORMAT_OPTIONS, "check_kinds": CHECK_KINDS}


# --- Register ----------------------------------------------------------------------------------------

def _replaces(e: dict, by_id: dict) -> dict | None:
    pid = entrylib.predecessor_id(e)
    if not pid:
        return None
    p = by_id.get(pid) or {}
    return {"id": pid, "seq": p.get("seq"), "name": p.get("name", ""), "mode": e.get("replaces_mode") or "auto"}


def _correction_count(e: dict) -> int:
    return len(e.get("corrected_fields") or []) + len(e.get("check_overrides") or {}) + len(e.get("text_overrides") or {})


def _row(e: dict, by_id: dict | None = None) -> dict:
    up = e.get("uploader") or {}
    return {
        "id": e["_id"], "seq": e.get("seq"), "name": e["name"], "kind": e.get("kind"), "file_count": e.get("file_count", 0),
        "content": e.get("content_override") or e.get("content_auto") or "", "file_types": e.get("file_types", ""),
        "received_at": e.get("received_at"), "received_from": e.get("received_from_override") or up.get("name") or "",
        "uploader": up, "link": f"#entry-{e['_id']}", "discipline": e.get("discipline"),
        "check_result": e.get("check_result", "pending"), "deviations": e.get("deviations", []),
        "open_questions": e.get("open_questions", 0), "flags": e.get("flags", 0),
        "comments": len(e.get("comments") or []), "corrections": _correction_count(e),
        "qa_status": e.get("qa_status", "ikke_begynt"), "qa_date": e.get("qa_date"), "ready": e.get("ready"),
        "lifecycle": e.get("lifecycle", "gjeldende"), "superseded_by": e.get("superseded_by"),
        "replaces": _replaces(e, by_id or {}), "data_type": e.get("data_type"),
        "data_type_label": DATA_TYPES.get(e.get("data_type"), "Annet"), "delivery_id": e.get("delivery_id"),
        "project_id": e["project_id"],
    }


def list_projects(ctx: Context, user: dict) -> list[dict]:
    """Projects with a summary of their register."""
    out = []
    for p in ctx.db[dblib.PROJECTS].find({}).sort("name"):
        es = list(ctx.db[dblib.ENTRIES].find({"project_id": p["_id"]}))
        out.append({"id": p["_id"], "name": p.get("name"), "project_type": p.get("project_type"), "phase": p.get("phase"),
                    "horizontal_crs": p.get("horizontal_crs"),
                    "crs_name": crslib.crs_name(crslib.parse_crs(p.get("horizontal_crs"))),
                    "height_reference": p.get("height_reference"), "active_ruleset": p.get("active_ruleset"),
                    "entries": len(es), "files": sum(e.get("file_count", 0) for e in es),
                    "open_questions": sum(e.get("open_questions", 0) for e in es),
                    "qa_status": {k: sum(1 for e in es if e.get("qa_status") == k) for k in QA_STATUS},
                    "superseded": sum(1 for e in es if e.get("lifecycle") == "utgatt")})
    return jsonable(out)


def list_entries(ctx: Context, user: dict, project_id: str) -> list[dict]:
    """The register for one project in the order received (the pages sort further)."""
    es = list(ctx.db[dblib.ENTRIES].find({"project_id": project_id}))
    by_id = {e["_id"]: e for e in es}
    es.sort(key=lambda e: (e.get("received_at") or e.get("created_at"), e.get("seq", 0)))
    return jsonable([_row(e, by_id) for e in es])


def _file_out(ctx: Context, f: dict, order: dict) -> dict:
    checks = list(ctx.db[dblib.CHECKS].find({"file_id": f["_id"], "run_id": f.get("last_run_id")}))
    checks.sort(key=lambda c: order.get(c["rule_id"], 99))
    md = {k: v for k, v in (f.get("metadata") or {}).items() if k != "text_excerpt"}
    comp = {k: v for k, v in (f.get("comparison") or {}).items() if k != "key"} or None
    eff = f.get("effective") or {}
    epsg = (eff.get("horizontal_epsg") or {}).get("value")
    return {
        "id": f["_id"], "file_name": f["file_name"], "version": f.get("version", 1), "format": md.get("format"),
        "format_version": md.get("format_version"), "data_type": f.get("data_type"),
        "data_type_label": DATA_TYPES.get(f.get("data_type"), "Annet"), "data_type_reason": f.get("data_type_reason"),
        "check_result": f.get("check_result", "pending"), "deviations": f.get("deviations", []),
        "crs": {"epsg": epsg if isinstance(epsg, int) else None,
                "name": crslib.short_name(epsg) if isinstance(epsg, int) else None, "from": (eff.get("horizontal_epsg") or {}).get("from")},
        "effective": eff, "conflicts": f.get("conflicts", []), "plausibility": f.get("plausibility"),
        "coverage": f.get("coverage"), "comparison": comp, "ai": f.get("ai"), "metadata": md,
        "checks": [{k: c.get(k) for k in ("rule_id", "rule_text", "result", "evidence", "checked_by", "confidence",
                                          "comment", "flagged_for_review", "model", "override")} for c in checks],
        "content": {k: v for k, v in (f.get("content") or {}).items() if k != "text_excerpt"} or None,
        "sidecars": f.get("sidecars", []), "delivery_notes": f.get("delivery_notes", []),
        "context_texts": [{"name": t["name"], "kind": t.get("kind"), "chars": len(t.get("text", ""))}
                          for t in f.get("context_texts", [])],
        "uploader_values": f.get("uploader_values", {}), "history": f.get("history", []),
        "uploaded_at": f.get("uploaded_at"), "last_checked_at": f.get("last_checked_at"),
        "ruleset_version": f.get("ruleset_version"),
        "surface": {k: (f.get("surface") or {}).get(k) for k in ("cell", "source", "valid_cells")} if f.get("surface") else None,
        "source_path": f.get("source_path"),
        "link": f"{ctx.settings.app_base_url.rstrip('/')}/api/files/{f['_id']}/download" if f.get("source_path") else None,
    }


def _sketch(files: list[dict], project: dict) -> dict | None:
    geo = crslib.project_geometry(project)
    if not geo:
        return None
    shapes = []
    for f in files:
        ext = (f.get("metadata") or {}).get("extent")
        epsg = ((f.get("effective") or {}).get("horizontal_epsg") or {}).get("value")
        plaus = f.get("plausibility") or {}
        use, mode = None, None
        if ext and isinstance(epsg, int) and plaus.get("declared_fits"):
            use, mode = epsg, "fits"
        elif ext and plaus.get("candidates"):
            use, mode = plaus["candidates"][0]["epsg"], "candidate"
        if not use:
            continue
        pts = [crslib.transform(x, y, use, geo["epsg"]) for x, y in crslib.bbox_corners(ext)]
        if all(pts):
            geom = _geom((f.get("metadata") or {}).get("footprint"), ext,
                         lambda x, y, u=use: crslib.transform(x, y, u, geo["epsg"]))
            shapes.append({"file_id": f["_id"], "name": f["file_name"], "pts": [list(p) for p in pts], "mode": mode,
                           "geom": geom, "result": f.get("check_result"), "crs_name": crslib.short_name(use)})
    return {"area": [list(p) for p in geo["points"]], "crs_name": crslib.short_name(geo["epsg"]), "shapes": shapes,
            "missing": len(files) - len(shapes)}


def entry_detail(ctx: Context, user: dict, entry_id: str) -> dict:
    """Everything the expanded register row shows."""
    db = ctx.db
    e = db[dblib.ENTRIES].find_one({"_id": entry_id})
    if not e:
        raise NotFound(entry_id)
    project = db[dblib.PROJECTS].find_one({"_id": e["project_id"]}) or {}
    ruleset = get_ruleset(db, project)
    order = {r["id"]: i for i, r in enumerate(ruleset.get("rules", []))}
    files = sorted(db[dblib.FILES].find({"entry_id": entry_id}), key=lambda f: f["file_name"].lower())
    all_entries = list(db[dblib.ENTRIES].find({"project_id": e["project_id"]}))
    by_id = {x["_id"]: x for x in all_entries}
    qs = list(db[dblib.QUESTIONS].find({"entry_id": entry_id, "status": {"$in": ["open", "answered"]}}))
    qs.sort(key=lambda q: (q["status"] != "open", qlib.FIELD_ORDER.index(q["field"]) if q["field"] in qlib.FIELD_ORDER else 9))
    own = (e.get("uploader") or {}).get("email", "").lower() == (user.get("email") or "").lower()
    earlier = sorted((x for x in all_entries if x["_id"] != entry_id and x.get("seq", 0) < e.get("seq", 0)),
                     key=lambda x: (x.get("data_type") != e.get("data_type"), -x.get("seq", 0)))
    entry = {**_row(e, by_id), "qa_note": e.get("qa_note", ""), "review": e.get("review"), "history": e.get("history", []),
             "uploader_comment": e.get("uploader_comment"), "replaces_mode": e.get("replaces_mode") or "auto",
             "replaces_candidate": e.get("replaces_candidate"), "content_auto": e.get("content_auto"),
             "content_override": e.get("content_override"), "received_from_override": e.get("received_from_override"),
             "folder": e.get("folder"), "superseded_at": e.get("superseded_at"),
             "comment_list": e.get("comments") or [], "check_overrides": e.get("check_overrides") or {},
             "text_overrides": e.get("text_overrides") or {}}
    return jsonable({
        "entry": entry,
        "files": [_file_out(ctx, f, order) for f in files],
        "questions": [{"id": q["_id"], **{k: q.get(k) for k in ("field", "kind", "question", "choices", "suggested", "hint",
                                                                 "optional", "status", "answer", "answered_at", "asked_at",
                                                                 "answered_by", "file_names")}} for q in qs],
        "profile": _profile(e, files),
        "relations": relations_for(db, e),
        "sketch": _sketch(files, project),
        "replace_choices": [{"id": x["_id"], "seq": x.get("seq"), "name": x["name"],
                             "data_type_label": DATA_TYPES.get(x.get("data_type"), "Annet"),
                             "lifecycle": x.get("lifecycle")} for x in earlier[:40]],
        "project": {"id": project.get("_id"), "name": project.get("name"), "horizontal_crs": project.get("horizontal_crs"),
                    "height_reference": project.get("height_reference")},
        "options": {"disciplines": disciplines(project), "qa_status": QA_STATUS, "ready": READY},
        "permissions": {"can_review": is_reviewer(user), "can_answer": own or is_reviewer(user),
                        "can_edit_info": own or is_reviewer(user), "can_correct": own or is_reviewer(user),
                        "can_override": is_reviewer(user), "can_comment": True},
    })


# --- Uploader actions ----------------------------------------------------------------------------------

def _start_qa(ctx: Context, entry_id: str) -> None:
    ctx.db[dblib.ENTRIES].update_one({"_id": entry_id, "qa_status": "ikke_begynt"}, {"$set": {"qa_status": "pagar"}})


def _done(entry: dict, prefix: str = "") -> dict:
    msg = f"{prefix}#{entry.get('seq')} {entry['name']} kontrollert på nytt: {RESULT_LABELS.get(entry.get('check_result'), '')}."
    return jsonable({"entry": _row(entry), "message": msg})


def answer_question(ctx: Context, user: dict, question_id: str, answer: str) -> dict:
    """Store an answer on every file the question covers, then re-check the entry."""
    qc = ctx.db[dblib.QUESTIONS]
    q = qc.find_one({"_id": question_id})
    if not q:
        raise NotFound(question_id)
    if q["status"] != "open":
        raise ValueError("Spørsmålet er allerede besvart eller trukket tilbake.")
    if (q.get("uploader_email") or "") != (user.get("email") or "").lower() and not is_reviewer(user):
        raise Forbidden("Bare den som leverte dataene (eller en KS-ansvarlig) kan svare på dette spørsmålet.")
    value = qlib.parse_answer(q["field"], answer, q.get("kind", "ask"))  # raises AnswerError
    now = ctx.now()
    stamp = {"by": user.get("email"), "at": now, "via": "spørsmål", "question_id": question_id}
    if q["field"] == "comments":
        ctx.db[dblib.ENTRIES].update_one({"_id": q["entry_id"]}, {"$set": {"uploader_comment": answer.strip()}})
    else:
        for fid in q.get("file_ids") or []:
            ctx.db[dblib.FILES].update_one({"_id": fid}, {"$set": {f"uploader_values.{q['field']}": {**value, **stamp}}})
    qc.update_one({"_id": question_id}, {"$set": {"status": "answered", "answer": answer.strip(), "answered_at": now,
                                                  "answered_by": user.get("email")}})
    _start_qa(ctx, q["entry_id"])
    return _done(recheck_entry(ctx, q["entry_id"], trigger="svar"))


INFO_FIELDS = ["data_type", "horizontal_epsg", "height_reference", "data_date", "source", "quality", "comment"]


def save_data_info(ctx: Context, user: dict, entry_id: str, values: dict) -> dict:
    """The data-info form: what the uploader knows that the files do not say. Applies to every file in the entry."""
    e = ctx.db[dblib.ENTRIES].find_one({"_id": entry_id})
    if not e:
        raise NotFound(entry_id)
    own = (e.get("uploader") or {}).get("email", "") == (user.get("email") or "").lower()
    if not own and not is_reviewer(user):
        raise Forbidden("Bare den som leverte dataene (eller en KS-ansvarlig) kan endre opplysningene.")
    now = ctx.now()
    file_sets: dict = {}
    entry_sets: dict = {}
    for field in INFO_FIELDS:
        raw = str(values.get(field) or "").strip()
        if not raw:
            continue
        if field == "comment":
            entry_sets["uploader_comment"] = raw
            continue
        if field == "data_type" and raw not in DATA_TYPES:
            raise qlib.AnswerError(f"Ukjent datatype {raw!r}.")
        parsed = qlib.parse_answer(field, raw, "form")
        file_sets[f"uploader_values.{field}"] = {**parsed, "by": user.get("email"), "at": now, "via": "skjema"}
    if not file_sets and not entry_sets:
        raise qlib.AnswerError("Fyll ut minst ett felt.")
    if file_sets:
        ctx.db[dblib.FILES].update_many({"entry_id": entry_id}, {"$set": file_sets})
    if entry_sets:
        ctx.db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$set": entry_sets})
    _start_qa(ctx, entry_id)
    return _done(recheck_entry(ctx, entry_id, trigger="skjema"), "Lagret. ")


# --- QA actions ------------------------------------------------------------------------------------------

def update_qa(ctx: Context, user: dict, entry_id: str, values: dict) -> dict:
    """KS fields: responsible discipline, QA status, QA note, received from, content, which entry it replaces."""
    _require_reviewer(user, "endre KS-feltene")
    db = ctx.db
    e = db[dblib.ENTRIES].find_one({"_id": entry_id})
    if not e:
        raise NotFound(entry_id)
    project = db[dblib.PROJECTS].find_one({"_id": e["project_id"]}) or {}
    sets: dict = {}
    if "discipline" in values:
        if values["discipline"] not in disciplines(project):
            raise ValueError(f"Ukjent fag {values['discipline']!r}. Fag settes opp i prosjektinnstillingene.")
        sets["discipline"] = values["discipline"]
    if "qa_status" in values:
        if values["qa_status"] not in QA_STATUS:
            raise ValueError("Ugyldig status for kontroll.")
        sets["qa_status"] = values["qa_status"]
        if values["qa_status"] == "utfort" and not e.get("qa_date"):
            sets["qa_date"] = ctx.now()
        elif values["qa_status"] != "utfort" and not e.get("ready"):
            sets["qa_date"] = None
    if "qa_note" in values:
        sets["qa_note"] = str(values["qa_note"] or "").strip()[:2000]
    if "received_from" in values:
        sets["received_from_override"] = str(values["received_from"] or "").strip()[:200] or None
    if "content" in values:
        sets["content_override"] = str(values["content"] or "").strip()[:500] or None
    if "replaces" in values:
        r = values["replaces"] or "auto"
        if r in ("auto", "none"):
            sets.update({"replaces_mode": r, "replaces": None})
        else:
            target = db[dblib.ENTRIES].find_one({"_id": r, "project_id": e["project_id"]})
            if not target or target.get("seq", 0) >= e.get("seq", 0):
                raise ValueError("Velg en tidligere registrering i samme prosjekt.")
            sets.update({"replaces_mode": "manual", "replaces": r})
    if not sets:
        raise ValueError("Ingenting å lagre.")
    db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$set": sets})
    entry = db[dblib.ENTRIES].find_one({"_id": entry_id})
    if "replaces" in values:
        entry, _ = entrylib.refresh(ctx, entry_id)
    entrylib.apply_supersession(ctx, entry)
    return jsonable({"entry": _row(entry), "message": f"#{entry.get('seq')} {entry['name']}: KS-feltene er lagret."})


def decide(ctx: Context, user: dict, entry_id: str, ready: str | None, comment: str = "") -> dict:
    """'Er dokument/fil klar til bruk?' — Ja, Med forbehold or Nei; empty reopens. Sets status and date checked."""
    _require_reviewer(user, "avgjøre om data er klare til bruk")
    db = ctx.db
    e = db[dblib.ENTRIES].find_one({"_id": entry_id})
    if not e:
        raise NotFound(entry_id)
    ready = ready or None
    if ready is not None and ready not in READY:
        raise ValueError("Svaret må være Ja, Med forbehold eller Nei.")
    comment = (comment or "").strip()
    if ready == "nei" and not comment:
        raise ValueError("Skriv hvorfor dataene ikke kan brukes, slik at opplasteren vet hva som må rettes.")
    if ready == "med_forbehold" and not comment:
        raise ValueError("Beskriv forbeholdet, slik at de som bruker dataene ser det.")
    now = ctx.now()
    was_in_use = e.get("ready") in entrylib.READY_FOR_USE
    if ready is None:
        sets = {"ready": None, "qa_status": "pagar", "qa_date": None, "review": None}
        hist = {"at": now, "event": "Gjenåpnet", "by": user.get("name"), "ready": e.get("ready"), "review": e.get("review")}
        db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$set": sets, "$push": {"history": hist}})
    else:
        review = {"by": user.get("name"), "email": user.get("email"), "at": now, "decision": ready, "comment": comment,
                  "check_result_at_review": e.get("check_result"), "open_questions_at_review": e.get("open_questions", 0)}
        db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$set": {"ready": ready, "qa_status": "utfort", "qa_date": now,
                                                                  "review": review}})
    entry = db[dblib.ENTRIES].find_one({"_id": entry_id})
    entrylib.apply_supersession(ctx, entry)
    if ready == "nei":
        ctx.notifier.send(e.get("uploader") or {}, f"#{e.get('seq')} {e['name']}: ikke klar til bruk",
                          f"{user.get('name')} har vurdert #{e.get('seq')} {e['name']} som ikke klar til bruk:\n\n{comment}\n\n"
                          "Legg en rettet versjon i kildemappa (samme navn erstatter den gamle); den kontrolleres og registreres på nytt.",
                          f"{ctx.settings.app_base_url}/#entry-{entry_id}", "review")
    rechecked = 0
    if entrylib.is_surface_entry(entry) and was_in_use != (ready in entrylib.READY_FOR_USE):
        rechecked = recheck_project(ctx, e["project_id"], trigger="ny referanse", only_surfaces_pending=True)
    label = READY.get(ready, "gjenåpnet") if ready else "gjenåpnet"
    msg = f"#{entry.get('seq')} {entry['name']}: {label.lower() if ready else label}."
    if rechecked:
        msg += f" {rechecked} registrering(er) med terrengdata er sammenlignet på nytt."
    return jsonable({"entry": _row(db[dblib.ENTRIES].find_one({"_id": entry_id})), "message": msg, "rechecked": rechecked})


def notifications(ctx: Context, user: dict) -> list[dict]:
    """Messages sent to this user (the Varsler page)."""
    items = ctx.db[dblib.NOTIFICATIONS].find({"to": (user.get("email") or "").lower()}).sort("created_at", -1).limit(50)
    return jsonable([{"id": n["_id"], **{k: n.get(k) for k in ("subject", "body", "link", "kind", "created_at")}} for n in items])


def _read_summary(run: dict) -> str:
    c = run.get("counts") or {}
    return (f"Kildemappa er lest: {c.get('new', 0)} nye filer, {c.get('new version', 0)} nye versjoner"
            + (f", {c['errors']} feil" if c.get("errors") else "") + ".")


def source_file(ctx: Context, user: dict, file_id: str) -> Path:
    """Stien til en registrert fil i kildemappa (for «Åpne fila»)."""
    f = ctx.db[dblib.FILES].find_one({"_id": file_id})
    if not f or not f.get("source_path"):
        raise NotFound(file_id)
    path = ctx.source.path_of(f["project_id"], f["source_path"])
    if path is None or not path.is_file():
        raise NotFound(f"{f['file_name']} i kildemappa (flyttet eller slettet?)")
    return path


def run_worker(ctx: Context, user: dict, force: bool = False) -> dict:
    """Run the worker now (reviewers and admins)."""
    _require_reviewer(user, "starte en kontroll")
    return jsonable(run_once(ctx, trigger="manual", force=force))


# --- Project settings ------------------------------------------------------------------------------------

SETTING_KEYS = ["name", "source_folder", "project_type", "phase", "horizontal_crs", "height_reference", "accepted_formats",
                "max_data_age_years", "question_reminder_days", "package_threshold", "disciplines", "discipline_map",
                "project_area"]
RECHECK_KEYS = {"horizontal_crs", "height_reference", "accepted_formats", "max_data_age_years", "project_area"}


def _int(values: dict, key: str, lo: int, hi: int, label: str) -> int:
    try:
        v = int(str(values.get(key, "")).strip())
    except ValueError as exc:
        raise ValueError(f"{label} må være et heltall.") from exc
    if not lo <= v <= hi:
        raise ValueError(f"{label} må være mellom {lo} og {hi}.")
    return v


def parse_area(value) -> list[list[float]]:
    """Project area from a list of points or text with one 'x y' pair per line."""
    if isinstance(value, list):
        pts = [[float(p[0]), float(p[1])] for p in value]
    else:
        pts = []
        for line in str(value or "").splitlines():
            nums = re.findall(r"-?\d+(?:[.,]\d+)?", line)
            if len(nums) >= 2:
                pts.append([float(nums[0].replace(",", ".")), float(nums[1].replace(",", "."))])
    if pts and len(pts) < 3:
        raise ValueError("Prosjektområdet trenger minst tre punkter, ett «øst nord»-par per linje.")
    return pts


def validate_settings(values: dict) -> dict:
    """Check and normalise the settings form."""
    out: dict = {}
    name = str(values.get("name") or "").strip()
    if not name:
        raise ValueError("Prosjektet må ha et navn.")
    out["name"] = name[:120]
    folder = str(values.get("source_folder") or "").strip().strip('"')
    if folder and not Path(folder).expanduser().is_dir():
        raise ValueError(f"Fant ikke mappa «{folder}». Lim inn hele stien, for eksempel C:\\Users\\navn\\OneDrive - Multiconsult\\Prosjekt\\Grunnlagsdata.")
    out["source_folder"] = folder[:400]
    if values.get("project_type") not in PROJECT_TYPES:
        raise ValueError("Velg prosjekttype.")
    out["project_type"] = values["project_type"]
    if values.get("phase") not in PHASES:
        raise ValueError("Velg fase.")
    out["phase"] = values["phase"]
    epsg = crslib.parse_crs(values.get("horizontal_crs"))
    if epsg not in crslib.REGISTRY:
        raise ValueError("Velg et horisontalt koordinatsystem fra listen.")
    out["horizontal_crs"] = f"EPSG:{epsg}"
    if values.get("height_reference") not in HEIGHT_OPTIONS:
        raise ValueError("Velg høydesystem.")
    out["height_reference"] = values["height_reference"]
    fmts = [f.lower().lstrip(".") for f in values.get("accepted_formats") or []]
    if not fmts:
        raise ValueError("Velg minst ett godkjent filformat.")
    out["accepted_formats"] = [f for f in FORMAT_OPTIONS if f in fmts] + [f for f in fmts if f not in FORMAT_OPTIONS]
    out["max_data_age_years"] = _int(values, "max_data_age_years", 0, 100, "Maks alder på data")
    out["question_reminder_days"] = _int(values, "question_reminder_days", 0, 60, "Purring etter")
    out["package_threshold"] = _int(values, "package_threshold", 2, 10000, "Pakke fra antall filer")
    raw = values.get("disciplines") or []
    fag = [s.strip().upper() for s in (raw.split(",") if isinstance(raw, str) else raw) if s.strip()]
    fag = list(dict.fromkeys(fag))
    if not fag or len(fag) > 15 or any(len(f) > 12 for f in fag):
        raise ValueError("Skriv 1–15 fag, kommaseparert, for eksempel «VEG, VA, KON, GEO».")
    out["disciplines"] = fag
    dmap = values.get("discipline_map") or {}
    out["discipline_map"] = {dt: (dmap.get(dt) if dmap.get(dt) in fag else
                                  (DEFAULT_DISCIPLINE_MAP.get(dt) if DEFAULT_DISCIPLINE_MAP.get(dt) in fag else fag[0]))
                             for dt in DATA_TYPES}
    out["project_area"] = {"crs": out["horizontal_crs"], "coordinates": parse_area(values.get("project_area"))}
    return out


def get_settings(ctx: Context, user: dict, project_id: str) -> dict:
    """The project's settings, for the Prosjektinnstillinger page."""
    p = ctx.db[dblib.PROJECTS].find_one({"_id": project_id})
    if not p:
        raise NotFound(project_id)
    return jsonable({"id": p["_id"], **{k: p.get(k) for k in SETTING_KEYS}, "active_ruleset": p.get("active_ruleset"),
                     "options": options(p), "can_edit": is_reviewer(user)})


def save_settings(ctx: Context, user: dict, project_id: str | None, values: dict) -> dict:
    """Save (or create) a project's settings; re-check its files when anything they depend on changed."""
    _require_reviewer(user, "endre prosjektinnstillinger")
    clean = validate_settings(values)
    db = ctx.db
    if project_id is None:
        pid = re.sub(r"[^a-z0-9-]+", "-", str(values.get("id") or clean["name"]).lower()).strip("-")
        if not pid or db[dblib.PROJECTS].find_one({"_id": pid}):
            raise ValueError("Prosjekt-ID mangler eller finnes allerede. Velg en annen ID, for eksempel prosjektnummeret.")
        db[dblib.PROJECTS].insert_one({"_id": pid, **clean, "active_ruleset": None, "created_at": ctx.now()})
        msg = f"Prosjektet «{clean['name']}» er opprettet."
        if clean["source_folder"]:
            run = run_once(ctx, trigger="ny kildemappe", project_id=pid)
            msg += f" {_read_summary(run)}"
        return {**get_settings(ctx, user, pid), "message": msg, "rechecked": 0}
    old = db[dblib.PROJECTS].find_one({"_id": project_id})
    if not old:
        raise NotFound(project_id)
    db[dblib.PROJECTS].update_one({"_id": project_id}, {"$set": {**clean, "updated_at": ctx.now()}})
    changed = {k for k in RECHECK_KEYS if old.get(k) != clean.get(k)}
    n = recheck_project(ctx, project_id, trigger="innstillinger") if changed else 0
    msg = "Innstillingene er lagret." + (f" {n} registreringer er kontrollert på nytt." if n else "")
    if clean["source_folder"] and clean["source_folder"] != (old.get("source_folder") or ""):
        msg += " " + _read_summary(run_once(ctx, trigger="ny kildemappe", project_id=project_id))
    return {**get_settings(ctx, user, project_id), "message": msg, "rechecked": n}


# --- Rule sets ------------------------------------------------------------------------------------------------

def _versions(db, project_id: str) -> list[dict]:
    out = [{"version": r["version"], "approved_by": r.get("approved_by"), "approved_at": r.get("approved_at"),
            "note": r.get("note", ""), "rules": len(r.get("rules", []))}
           for r in db[dblib.RULESETS].find({"project_id": project_id})]
    return sorted(out, key=lambda v: [int(n) for n in re.findall(r"\d+", v["version"])], reverse=True)


def get_rules(ctx: Context, user: dict, project_id: str, version: str | None = None) -> dict:
    """The project's active (or a chosen) rule set, its versions, and what the built-in checks do."""
    p = ctx.db[dblib.PROJECTS].find_one({"_id": project_id})
    if not p:
        raise NotFound(project_id)
    rs = ctx.db[dblib.RULESETS].find_one({"_id": f"{project_id}:{version}"}) if version else get_ruleset(ctx.db, p)
    rs = rs or get_ruleset(ctx.db, p)
    return jsonable({"version": rs.get("version"), "active": p.get("active_ruleset"), "title": rs.get("title"),
                     "approved_by": rs.get("approved_by"), "approved_at": rs.get("approved_at"), "note": rs.get("note", ""),
                     "rules": rs.get("rules", []), "versions": _versions(ctx.db, project_id),
                     "builtin": {k: {"label": v["label"], "params": v["params"]} for k, v in BUILTIN.items()},
                     "param_labels": PARAM_LABELS, "check_kinds": CHECK_KINDS, "data_types": DATA_TYPES,
                     "results": {k: RESULT_LABELS[k] for k in FAILED_RESULTS}, "can_edit": is_reviewer(user),
                     "ai_enabled": ctx.settings.ai_enabled})


def validate_rules(rules: list[dict]) -> list[dict]:
    """Check an edited rule list; returns the cleaned rules or raises ValueError in Norwegian."""
    out, seen = [], set()
    if not rules:
        raise ValueError("Regelsettet må ha minst én regel.")
    for i, r in enumerate(rules, start=1):
        rid = str(r.get("id") or "").strip().upper()
        if not re.fullmatch(r"R-[A-Z0-9][A-Z0-9-]{1,20}", rid):
            raise ValueError(f"Regel {i}: ID må se ut som «R-AI-01» (store bokstaver, tall og bindestrek).")
        if rid in seen:
            raise ValueError(f"Regel-ID {rid} er brukt to ganger.")
        seen.add(rid)
        text = str(r.get("text") or "").strip()
        if len(text) < 5:
            raise ValueError(f"{rid}: skriv kravet som en hel setning.")
        check = r.get("check") or "ai"
        if check not in CHECK_KINDS:
            raise ValueError(f"{rid}: ugyldig kontrolltype.")
        if check == "auto" and rid not in BUILTIN:
            raise ValueError(f"{rid}: bare innebygde regler kan kontrolleres automatisk. Velg AI eller manuell.")
        failed = r.get("if_failed") or "deviation"
        if failed not in FAILED_RESULTS:
            raise ValueError(f"{rid}: ugyldig resultat ved brudd.")
        applies = [a for a in (r.get("applies_to") or ["all"]) if a == "all" or a in DATA_TYPES] or ["all"]
        clean = {"id": rid, "text": text[:300], "source": str(r.get("source") or "").strip()[:200], "applies_to": applies,
                 "check": check, "if_failed": failed, "active": r.get("active", True) is not False}
        if r.get("guidance"):
            clean["guidance"] = str(r["guidance"]).strip()[:1500]
        if rid in BUILTIN and BUILTIN[rid]["params"]:
            params = {}
            for k, default in BUILTIN[rid]["params"].items():
                v = (r.get("params") or {}).get(k, default)
                try:
                    params[k] = float(str(v).replace(",", "."))
                except ValueError as exc:
                    raise ValueError(f"{rid}: {PARAM_LABELS.get(k, k)} må være et tall.") from exc
            clean["params"] = params
        out.append(clean)
    return out


def save_rules(ctx: Context, user: dict, project_id: str, rules: list[dict], note: str = "") -> dict:
    """Save the edited rules as a new version, make it active, and re-check the project."""
    _require_reviewer(user, "endre regelsettet")
    db = ctx.db
    p = db[dblib.PROJECTS].find_one({"_id": project_id})
    if not p:
        raise NotFound(project_id)
    clean = validate_rules(rules)
    current = get_ruleset(db, p)
    nums = [[int(n) for n in re.findall(r"\d+", v["version"])] or [1, 0] for v in _versions(db, project_id)] or [[1, 0]]
    major, minor = max(nums)[:2] if len(max(nums)) >= 2 else (max(nums)[0], 0)
    version = f"v{major}.{minor + 1}"
    db[dblib.RULESETS].insert_one({"_id": f"{project_id}:{version}", "project_id": project_id, "version": version,
                                   "title": current.get("title") or "Krav til grunnlagsdata", "rules": clean,
                                   "approved_by": user.get("name"), "approved_at": ctx.now(),
                                   "note": (note or "").strip()[:500], "based_on": current.get("version")})
    db[dblib.PROJECTS].update_one({"_id": project_id}, {"$set": {"active_ruleset": version}})
    n = recheck_project(ctx, project_id, trigger="regelsett")
    return {**get_rules(ctx, user, project_id), "message": f"Regelsett {version} er lagret og tatt i bruk. "
                                                           f"{n} registreringer er kontrollert på nytt."}


def draft_rules(ctx: Context, user: dict, project_id: str, text: str) -> dict:
    """AI-drafted rules from pasted requirement text, for the team to review before saving."""
    _require_reviewer(user, "foreslå regler")
    p = ctx.db[dblib.PROJECTS].find_one({"_id": project_id}) or {}
    existing = get_ruleset(ctx.db, p).get("rules", [])
    return jsonable(ailib.draft_rules(ctx.settings, text, existing))


# --- AI chat --------------------------------------------------------------------------------------------------

def ask(ctx: Context, user: dict, project_id: str, messages: list[dict], lang: str = "nb") -> dict:
    """The AI chat: answer the last question about the project's base data."""
    from basedata.harness import chat as chatlib

    if not ctx.db[dblib.PROJECTS].find_one({"_id": project_id}):
        raise NotFound(project_id)
    return jsonable(chatlib.chat(ctx, project_id, messages, lang))


# --- Corrections and comments -----------------------------------------------------------------------------------

CORRECTABLE = {"data_type": "Datatype", "horizontal_epsg": "Koordinatsystem", "height_reference": "Høydesystem",
               "data_date": "Dato", "source": "Kilde", "quality": "Kvalitet", "summary": "Beskrivelse av innholdet",
               "content": "Innhold i fil/mappe"}
TEXT_FIELDS = ("summary", "content")


def _profile(e: dict, files: list[dict]) -> dict:
    p = entry_profile(e, files)
    o = (e.get("text_overrides") or {}).get("summary")
    if o:
        p = {**p, "summary_original": p.get("summary"), "summary": o["value"], "summary_corrected": o}
    return p


def _can_edit(user: dict, e: dict) -> bool:
    return (e.get("uploader") or {}).get("email", "") == (user.get("email") or "").lower() or is_reviewer(user)


def _stamp(user: dict, now, comment: str) -> dict:
    return {"by": user.get("email"), "by_name": user.get("name"), "at": now, "comment": comment}


def correct_value(ctx: Context, user: dict, entry_id: str, field: str, value: str, comment: str = "") -> dict:
    """A person corrects a value the file, the AI or the checker got wrong. Empty value removes the correction.
    The correction wins over the file and the AI, is shown as «korrigert», and the entry is re-checked."""
    db = ctx.db
    e = db[dblib.ENTRIES].find_one({"_id": entry_id})
    if not e:
        raise NotFound(entry_id)
    if not _can_edit(user, e):
        raise Forbidden("Bare den som leverte dataene (eller en KS-ansvarlig) kan korrigere verdiene.")
    if field not in CORRECTABLE:
        raise ValueError("Dette feltet kan ikke korrigeres.")
    value, comment, now = str(value or "").strip(), str(comment or "").strip()[:1000], ctx.now()
    label = CORRECTABLE[field]
    corrected = set(e.get("corrected_fields") or [])
    if field in TEXT_FIELDS:
        key = f"text_overrides.{field}"
        if value:
            db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$set": {key: {"value": value[:1000], **_stamp(user, now, comment)},
                                                                      **({"content_override": value[:500]} if field == "content" else {})}})
        else:
            db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$unset": {key: "", **({"content_override": ""} if field == "content" else {})}})
        _log(ctx, entry_id, user, f"{label} {'korrigert' if value else 'tilbakestilt'}", comment)
        return jsonable({"entry": _row(db[dblib.ENTRIES].find_one({"_id": entry_id})),
                         "message": f"{label} er {'korrigert' if value else 'tilbakestilt'}."})
    if value:
        if field == "data_type" and value not in DATA_TYPES:
            value = next((k for k, v in DATA_TYPES.items() if v.lower() == value.lower()), value)
            if value not in DATA_TYPES:
                raise ValueError("Velg en datatype fra listen.")
        parsed = qlib.parse_answer(field, value, "form")
        if field == "data_date" and not parsed.get("value"):
            raise qlib.AnswerError("Fant ikke en dato – skriv for eksempel «2024-05» eller «12.05.2024».")
        doc = {**parsed, "confirmed_over_file": True, "via": "korreksjon", **_stamp(user, now, comment)}
        db[dblib.FILES].update_many({"entry_id": entry_id}, {"$set": {f"uploader_values.{field}": doc}})
        corrected.add(field)
        for q in db[dblib.QUESTIONS].find({"entry_id": entry_id, "field": field, "status": "open"}):
            db[dblib.QUESTIONS].update_one({"_id": q["_id"]}, {"$set": {"status": "answered", "answer": f"{value} (korrigert)",
                                                                       "answered_at": now, "answered_by": user.get("email")}})
    else:
        db[dblib.FILES].update_many({"entry_id": entry_id, f"uploader_values.{field}.via": "korreksjon"},
                                    {"$unset": {f"uploader_values.{field}": ""}})
        corrected.discard(field)
    db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$set": {"corrected_fields": sorted(corrected)}})
    _log(ctx, entry_id, user, f"{label} {'korrigert til «' + value + '»' if value else 'tilbakestilt'}", comment)
    _start_qa(ctx, entry_id)
    return _done(recheck_entry(ctx, entry_id, trigger="korreksjon"), f"{label} {'korrigert' if value else 'tilbakestilt'}. ")


def override_check(ctx: Context, user: dict, entry_id: str, rule_id: str, result: str | None, comment: str = "") -> dict:
    """KS sets the result of one rule by hand (for every file in the entry) when the AI or a check is wrong."""
    _require_reviewer(user, "overstyre kontrollresultater")
    db = ctx.db
    e = db[dblib.ENTRIES].find_one({"_id": entry_id})
    if not e:
        raise NotFound(entry_id)
    comment = str(comment or "").strip()[:1000]
    key = f"check_overrides.{rule_id}"
    if result:
        if result not in RESULT_LABELS or result == "pending":
            raise ValueError("Ugyldig resultat.")
        if not comment:
            raise ValueError("Skriv hvorfor resultatet overstyres, slik at det er dokumentert.")
        db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$set": {key: {"result": result, **_stamp(user, ctx.now(), comment)}}})
        _log(ctx, entry_id, user, f"{rule_id} overstyrt til «{RESULT_LABELS[result]}»", comment)
    else:
        db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$unset": {key: ""}})
        _log(ctx, entry_id, user, f"Overstyring av {rule_id} fjernet", comment)
    return _done(recheck_entry(ctx, entry_id, trigger="overstyring"), f"{rule_id} {'overstyrt' if result else 'tilbakestilt'}. ")


def add_comment(ctx: Context, user: dict, entry_id: str, text: str) -> dict:
    """Any logged-in user can comment on a registration; comments are kept as documentation."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("Skriv en kommentar.")
    e = ctx.db[dblib.ENTRIES].find_one({"_id": entry_id})
    if not e:
        raise NotFound(entry_id)
    c = {"id": dblib.new_id("bdk"), "text": text[:3000], **_stamp(user, ctx.now(), "")}
    c.pop("comment")
    ctx.db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$push": {"comments": c}})
    up = (e.get("uploader") or {})
    if up.get("email") and up["email"] != (user.get("email") or "").lower():
        ctx.notifier.send(up, f"Ny kommentar på #{e.get('seq')} {e['name']}",
                          f"{user.get('name')} skrev:\n\n{text}", f"{ctx.settings.app_base_url}/#entry-{entry_id}", "comment")
    return jsonable({"comment": c, "message": "Kommentaren er lagret."})


def _log(ctx: Context, entry_id: str, user: dict, event: str, comment: str) -> None:
    ctx.db[dblib.ENTRIES].update_one({"_id": entry_id}, {"$push": {"history": {
        "at": ctx.now(), "event": event + (f" – «{comment}»" if comment else ""), "by": user.get("name")}}})


# --- Map overview and project area --------------------------------------------------------------------------

def _ring(ext: dict, epsg: int, steps: int = 4) -> list[list[float]] | None:
    """A file's extent as a lon/lat ring (edges densified so a UTM rectangle bends correctly)."""
    pts = []
    corners = [(ext["minx"], ext["miny"]), (ext["maxx"], ext["miny"]), (ext["maxx"], ext["maxy"]), (ext["minx"], ext["maxy"])]
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        for k in range(steps):
            ll = crslib.to_lonlat(epsg, x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps)
            if not ll:
                return None
            pts.append([round(ll[0], 7), round(ll[1], 7)])
    return pts


def _geom(fp: dict | None, ext: dict | None, fn) -> dict | None:
    """A stored footprint (in the file's CRS) converted with `fn(x, y) -> (x', y') | None`, as
    {"kind", "polygons", "lines", "points", "source"}. Falls back to the extent rectangle."""
    if not fp and ext:
        from basedata.indata.footprint import box
        fp = box(ext, "utstrekningen i fila")
    if not fp:
        return None

    def conv(arr):
        out = []
        for x, y in ((p[0], p[1]) for p in arr):
            q = fn(x, y)
            if q:
                out.append([round(q[0], 7), round(q[1], 7)])
        return out

    kind = fp.get("kind")
    g = {"kind": kind, "source": fp.get("source"), "polygons": [], "lines": [], "points": []}
    if kind in ("outline", "box"):
        g["polygons"] = [r for r in (conv(r) for r in fp.get("rings") or []) if len(r) >= 3]
    elif kind == "points":
        g["points"] = conv(fp.get("points") or [])
    elif kind == "features":
        g["polygons"] = [r for r in (conv(r) for r in fp.get("polygons") or []) if len(r) >= 3]
        g["lines"] = [l for l in (conv(l) for l in fp.get("lines") or []) if len(l) >= 2]
        g["points"] = conv(fp.get("points") or [])
    if not (g["polygons"] or g["lines"] or g["points"]):
        return None
    return g


def map_data(ctx: Context, user: dict, project_id: str) -> dict:
    """The map overview: project boundary and every registration's footprint in lon/lat."""
    db = ctx.db
    p = db[dblib.PROJECTS].find_one({"_id": project_id})
    if not p:
        raise NotFound(project_id)
    area = p.get("project_area") or {}
    epsg = crslib.parse_crs(area.get("crs") or p.get("horizontal_crs"))
    lonlat = [list(crslib.to_lonlat(epsg, x, y) or (None, None)) for x, y in area.get("coordinates") or []] if epsg else []
    lonlat = [[round(a, 7), round(b, 7)] for a, b in lonlat if a is not None]
    items, unplaced = [], []
    es = sorted(db[dblib.ENTRIES].find({"project_id": project_id}), key=lambda e: e.get("seq", 0))
    by_id = {e["_id"]: e for e in es}
    for e in es:
        files = sorted(db[dblib.FILES].find({"entry_id": e["_id"]}), key=lambda f: f["file_name"])
        fps, why = [], None
        for f in files:
            ext = (f.get("metadata") or {}).get("extent")
            fe = ((f.get("effective") or {}).get("horizontal_epsg") or {}).get("value")
            if not ext:
                why = why or "ingen koordinater i fila"
                continue
            plaus = f.get("plausibility") or {}
            cands = [c["epsg"] for c in plaus.get("candidates") or [] if c.get("epsg")]
            use, guess = (fe, False) if isinstance(fe, int) else (None, False)
            manual = ((f.get("effective") or {}).get("horizontal_epsg") or {}).get("from") == "manual"
            if (use is None or (plaus.get("declared_fits") is False and not manual)) and cands:
                use, guess = cands[0], True
            if use is None:
                why = why or "koordinatsystem ukjent"
                continue
            ring = _ring(ext, use)
            if ring:
                geom = _geom((f.get("metadata") or {}).get("footprint"), ext, lambda x, y, u=use: crslib.to_lonlat(u, x, y))
                fps.append({"file": f["file_name"], "ring": ring, "geom": geom, "result": f.get("check_result"),
                            "guess": guess, "crs_name": crslib.short_name(use)})
        row = {**_row(e, by_id), "summary": _profile(e, files).get("summary")}
        if fps:
            items.append({**row, "footprints": fps})
        else:
            unplaced.append({**row, "reason": why or "ingen koordinater"})
    return jsonable({"crs": f"EPSG:{epsg}" if epsg else None, "crs_name": crslib.short_name(epsg) if epsg else None,
                     "area": {"coordinates": area.get("coordinates") or [], "lonlat": lonlat, "source": area.get("source"),
                              "updated_by": area.get("updated_by"), "updated_at": area.get("updated_at")},
                     "items": items, "unplaced": unplaced, "can_edit": is_reviewer(user)})


def save_area(ctx: Context, user: dict, project_id: str, points: list, crs: str | None = None, source: str = "") -> dict:
    """Set the project boundary from a drawn rectangle/polygon or an imported file. `points` are [x, y] in `crs`
    (default lon/lat, EPSG:4326); they are stored in the project's own coordinate system."""
    _require_reviewer(user, "endre prosjektområdet")
    db = ctx.db
    p = db[dblib.PROJECTS].find_one({"_id": project_id})
    if not p:
        raise NotFound(project_id)
    target = crslib.parse_crs(p.get("horizontal_crs"))
    src = crslib.parse_crs(crs or "EPSG:4326")
    try:
        pts = [[float(a), float(b)] for a, b in points or []]
    except (TypeError, ValueError) as exc:
        raise ValueError("Ugyldige koordinater for prosjektområdet.") from exc
    if len(pts) > 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError("Prosjektområdet trenger minst tre punkter.")
    out = []
    for x, y in pts:
        t = crslib.transform(x, y, src, target) if src != target else (x, y)
        if not t:
            raise ValueError("Koordinatene kunne ikke regnes om til prosjektets koordinatsystem.")
        out.append([round(t[0], 2), round(t[1], 2)])
    if crslib.polygon_area([tuple(q) for q in out]) < 100:
        raise ValueError("Området er for lite – sjekk at koordinatene er i riktig koordinatsystem.")
    ll = crslib.to_lonlat(target, *out[0])
    b = crslib.NORWAY_BBOX
    if not ll or not (b[0] - 2 <= ll[0] <= b[2] + 2 and b[1] - 2 <= ll[1] <= b[3] + 2):
        raise ValueError("Området havner utenfor Norge – sjekk koordinatsystemet.")
    db[dblib.PROJECTS].update_one({"_id": project_id}, {"$set": {"project_area": {
        "crs": f"EPSG:{target}", "coordinates": out, "source": (source or "tegnet i kartet")[:200],
        "updated_by": user.get("name"), "updated_at": ctx.now()}}})
    n = recheck_project(ctx, project_id, trigger="prosjektområde")
    return {**map_data(ctx, user, project_id),
            "message": f"Prosjektområdet er lagret ({len(out)} punkter). {n} registreringer er kontrollert på nytt."}
