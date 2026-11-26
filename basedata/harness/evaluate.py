"""Evaluate one file: merge values, run the AI step, compare with approved references, run the rules."""

from __future__ import annotations

from datetime import datetime

from basedata import __version__
from basedata.harness import ai as ailib
from basedata.indata import crs as crslib
from basedata.core import db as dblib
from basedata.harness import questions as qlib
from basedata.indata import surface as surfacelib
from basedata.core.classify import SURFACE_TYPES
from basedata.indata.compare import compare
from basedata.harness.parsing import parse_crs_text, parse_date_text
from basedata.indata.content import file_profile
from basedata.harness.rules import Check, EvalInput, applies, load_default_ruleset, run_code_checks, worst
from basedata.core.text import nb

FIELDS = ["horizontal_epsg", "height_reference", "data_date", "source", "quality"]
_AI_KEY = {"horizontal_epsg": "horizontal_crs"}
READY_FOR_USE = ("ja", "med_forbehold")


def quality_summary(md: dict) -> str | None:
    """A short readable summary of what the file says about its quality."""
    q = md.get("quality") or {}
    parts = []
    if q.get("product_spec"):
        parts.append(str(q["product_spec"]))
    if isinstance(q.get("accuracy_cm"), dict):
        parts.append(f"nøyaktighet {nb(q['accuracy_cm']['median'], 0)} cm (median)")
    if q.get("pixel_size_m"):
        parts.append(f"{nb(q['pixel_size_m'], 2 if q['pixel_size_m'] < 1 else 0)} m piksler")
    if q.get("density_pts_per_m2"):
        parts.append(f"{nb(q['density_pts_per_m2'], 1)} punkter/m²")
    return ", ".join(parts) or None


def _file_values(md: dict) -> dict:
    return {"horizontal_epsg": md.get("horizontal_epsg"), "height_reference": md.get("height_reference"),
            "data_date": md.get("data_date"), "source": md.get("source"), "quality": quality_summary(md)}


def _weak(field: str, md: dict) -> bool:
    kind = (md.get("data_date_kind") or "").lower()
    return field == "data_date" and any(w in kind for w in ("prosesseringsdato", "datotagg", "opprettelsesdato"))


def _ai_value(field: str, raw: str):
    if field == "horizontal_epsg":
        return parse_crs_text(raw)
    if field == "height_reference":
        return crslib.normalize_height(raw)
    if field == "data_date":
        return parse_date_text(raw)
    return raw


def effective_values(md: dict, uploader: dict, ai_found: dict) -> tuple[dict, list[str]]:
    """Merge file, uploader and AI-from-text values. Returns (values by field, fields in conflict).

    The uploader wins where the file has nothing (or only a weak date) or where the uploader explicitly
    confirmed their value over the file's; otherwise the file wins and a conflict with the uploader's
    form value is reported. AI-from-text fills gaps only, with its evidence quote kept.
    """
    fv = _file_values(md)
    eff, conflicts = {}, []
    for f in FIELDS:
        file_v, up, weak = fv[f], uploader.get(f), _weak(f, md)
        ai = ai_found.get(_AI_KEY.get(f, f))
        e: dict = {"value": None, "from": None, "file_value": file_v}
        if up and up.get("via") == "korreksjon" and not up.get("unknown"):
            e.update({"value": up.get("value") if up.get("value") not in ("LOCAL",) else None,
                      "from": "manual" if up.get("value") != "LOCAL" else "uploader_local",
                      "corrected": {k: up.get(k) for k in ("by_name", "by", "at", "comment", "raw")},
                      "was": file_v if file_v is not None else (_ai_value(f, ai["value"]) if ai else None)})
        elif up:
            if up.get("unknown"):
                e["from"] = "uploader_unknown"
            elif up.get("value") == "LOCAL":
                e["from"] = "uploader_local"
            elif up.get("value") is None:
                e.update({"from": "uploader", "raw": up.get("raw")})
            elif file_v is None or weak or up.get("confirmed_over_file") or up["value"] == file_v:
                e.update({"value": up["value"], "from": "uploader"})
            else:
                e.update({"value": file_v, "from": "file", "conflict": up["value"]})
                conflicts.append(f)
        if e["from"] is None:
            if file_v is not None and not weak:
                e.update({"value": file_v, "from": "file"})
            elif ai:
                v = _ai_value(f, ai["value"])
                if v:
                    e.update({"value": v, "from": "ai_text", "evidence": ai["evidence"]})
            if e["from"] is None and file_v is not None:
                e.update({"value": file_v, "from": "file"})
        if f == "data_date" and e["from"] == "file":
            e["kind"] = md.get("data_date_kind")
        if f == "horizontal_epsg":
            e["name"] = crslib.crs_name(e["value"]) if isinstance(e["value"], int) else None
        eff[f] = e
    return eff, conflicts


def get_ruleset(db, project: dict) -> dict:
    """The project's active rule set, or the built-in example."""
    pid, ver = project.get("_id"), project.get("active_ruleset")
    rs = db[dblib.RULESETS].find_one({"_id": f"{pid}:{ver}"}) if pid and ver else None
    return rs or load_default_ruleset()


def _overlap(a: dict | None, b: dict | None) -> float:
    if not a or not b:
        return 0.0
    w = min(a["maxx"], b["maxx"]) - max(a["minx"], b["minx"])
    h = min(a["maxy"], b["maxy"]) - max(a["miny"], b["miny"])
    return w * h if w > 0 and h > 0 else 0.0


def _ts(v) -> float:
    return v.timestamp() if isinstance(v, datetime) else 0.0


def compare_with_reference(ctx, fdoc: dict, data_type: str, epsg: int | None) -> dict | None:
    """Compare a terrain model or point cloud with the best approved, current reference that overlaps it."""
    if data_type not in SURFACE_TYPES:
        return None
    db = ctx.db
    if not fdoc.get("surface"):
        return {"status": "no_surface",
                "note": "Høydene i fila kunne ikke leses (LAZ krever laspy med lazrs), så den er ikke sammenlignet."}
    if epsg is None:
        return {"status": "crs_unknown"}
    candidates = []
    for e in db[dblib.ENTRIES].find({"project_id": fdoc["project_id"], "ready": {"$in": list(READY_FOR_USE)},
                                     "lifecycle": "gjeldende", "data_type": {"$in": sorted(SURFACE_TYPES)}}):
        if e["_id"] == fdoc.get("entry_id"):
            continue
        for rf in db[dblib.FILES].find({"entry_id": e["_id"]}):
            ref_epsg = ((rf.get("effective") or {}).get("horizontal_epsg") or {}).get("value")
            ov = _overlap(fdoc["metadata"].get("extent"), (rf.get("metadata") or {}).get("extent"))
            if rf.get("surface") and ref_epsg == epsg and ov > 0:
                candidates.append(((0 if e["data_type"] == "terrain" else 1, -ov, -_ts(e.get("received_at"))), rf, e))
    if not candidates:
        return {"status": "no_reference"}
    candidates.sort(key=lambda t: t[0])
    _, rf, e = candidates[0]
    key = f"{fdoc['surface']['id']}|{rf['surface']['id']}|{epsg}"
    prev = fdoc.get("comparison") or {}
    if prev.get("key") == key and prev.get("status") == "done":
        stats = {k: v for k, v in prev.items() if k != "reference"}
    else:
        new, ref = surfacelib.load(db, fdoc["surface"]), surfacelib.load(db, rf["surface"])
        if new is None or ref is None:
            return {"status": "no_surface", "note": "Lagrede høyder mangler; last opp fila på nytt."}
        stats = compare(new, ref)
        if stats["status"] != "done":
            return {"status": "no_overlap"}
    rev = e.get("review") or {}
    stats.update({"key": key, "reference": {
        "entry_id": e["_id"], "entry_seq": e.get("seq"), "entry_name": e["name"], "file_id": rf["_id"],
        "file_name": rf["file_name"], "data_type": e["data_type"], "ready": e.get("ready"), "approved_at": rev.get("at"),
        "approved_by": rev.get("by"), "cell_m": rf["surface"]["cell"], "source": rf["surface"].get("source"),
        "quality": quality_summary(rf.get("metadata") or {}),
        "data_date": ((rf.get("effective") or {}).get("data_date") or {}).get("value")}})
    stats["new_source"] = fdoc["surface"].get("source")
    return stats


def evaluate(ctx, fdoc: dict, run_id: str) -> None:
    """Check one file and save the results on the file document (questions are asked per entry)."""
    db, settings, now = ctx.db, ctx.settings, ctx.now()
    project = db[dblib.PROJECTS].find_one({"_id": fdoc["project_id"]}) or {}
    ruleset = get_ruleset(db, project)
    md = fdoc["metadata"]
    uploader = fdoc.get("uploader_values") or {}
    data_type = (uploader.get("data_type") or {}).get("value") or fdoc["data_type_guess"]
    rules = [r for r in ruleset["rules"] if applies(r, data_type)]
    ai_rules = [r for r in rules if r.get("check") == "ai"]
    texts = fdoc.get("context_texts") or []

    pre = crslib.plausibility(md.get("extent"), md.get("horizontal_epsg"), project)
    payload = {"file": {"name": fdoc["file_name"], "format": md.get("format"), "data_type": data_type},
               "metadata": {k: v for k, v in md.items() if k != "text_excerpt"},
               "project": {k: project.get(k) for k in ("name", "project_type", "phase", "horizontal_crs",
                                                       "height_reference", "accepted_formats", "max_data_age_years")},
               "coordinate_check": pre.get("note"),
               "uploader_values": {k: v.get("raw") for k, v in uploader.items() if v.get("raw")},
               "content": {k: v for k, v in file_profile(fdoc["file_name"], md, data_type).items() if k != "text_excerpt"}}
    review = ailib.review_file(settings, payload, texts, ai_rules) if (ai_rules or texts) \
        else ailib.AIReview(status="skipped")

    eff, conflicts = effective_values(md, uploader, review.found_values)
    epsg = eff["horizontal_epsg"]["value"] if isinstance(eff["horizontal_epsg"]["value"], int) else None
    plaus = crslib.plausibility(md.get("extent"), epsg, project)
    content = file_profile(fdoc["file_name"], md, data_type, epsg)
    cov = crslib.coverage(md.get("extent"), epsg, project)
    comparison = compare_with_reference(ctx, fdoc, data_type, epsg) \
        if any(r["id"] == "R-REF-01" for r in rules) else None
    inp = EvalInput(data_type, fdoc["ext"], md, eff, project, plaus, cov, now.date(), comparison)
    checks = run_code_checks(rules, inp)

    for r in ai_rules:
        c = next((x for x in review.checks if x["rule_id"] == r["id"]), None)
        if c:
            checks.append(Check(r["id"], r["text"], c["result"], c["evidence"], "ai", c["confidence"], c["comment"],
                                c["flagged_for_review"], review.model, review.prompt_version, depends_on="quality"))
        else:
            reason = {"skipped": "AI er ikke satt opp – KS-ansvarlig vurderer denne regelen.",
                      "error": f"AI-kallet feilet ({review.error}) – KS-ansvarlig vurderer denne regelen."}
            checks.append(Check(r["id"], r["text"], "needs_review",
                                reason.get(review.status, "AI ga ikke resultat for denne regelen."), "ai",
                                depends_on="quality"))

    entry = db[dblib.ENTRIES].find_one({"_id": fdoc.get("entry_id")}) if fdoc.get("entry_id") else None
    for c in checks:
        o = ((entry or {}).get("check_overrides") or {}).get(c.rule_id)
        if o and o.get("result"):
            c.override = {"result": o["result"], "original": c.result, "comment": o.get("comment", ""),
                          "by": o.get("by_name") or o.get("by"), "at": o.get("at")}
            c.result = o["result"]
            c.flagged_for_review = False
    for c in checks:
        db[dblib.CHECKS].insert_one({"_id": dblib.new_id("bdc"), "file_id": fdoc["_id"], "run_id": run_id,
                                     "version": fdoc.get("version", 1), "ruleset_version": ruleset.get("version"),
                                     "created_at": now, **c.to_dict()})
    updates = {
        "data_type": data_type,
        "effective": eff,
        "conflicts": conflicts,
        "plausibility": plaus,
        "content": content,
        "coverage": cov,
        "comparison": comparison,
        "check_result": worst([c.result for c in checks]),
        "deviations": [c.rule_id for c in checks if c.result != "ok"],
        "flags": sum(1 for c in checks if c.flagged_for_review),
        "question_specs": qlib.needed(fdoc, checks, eff, plaus, conflicts),
        "ai": {"status": review.status, "model": review.model, "prompt_version": review.prompt_version,
               "comment": review.file_comment, "suggested_data_type": review.suggested_data_type,
               "found_values": review.found_values, "dropped": review.dropped, "error": review.error},
        "last_checked_at": now,
        "last_run_id": run_id,
        "ruleset_version": ruleset.get("version"),
        "app_version": __version__,
        "updated_at": now,
    }
    wgs = crslib.extent_to_wgs84(md["extent"], epsg) if md.get("extent") and epsg and plaus.get("declared_fits") else None
    change: dict = {"$set": updates}
    if wgs:
        updates["extent_wgs84"] = wgs
    else:
        change["$unset"] = {"extent_wgs84": ""}
    db[dblib.FILES].update_one({"_id": fdoc["_id"]}, change)
