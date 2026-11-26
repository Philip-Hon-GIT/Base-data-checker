"""Questions to uploaders.

Each file's evaluation lists the questions it needs (`needed`). Questions are then asked per register
entry (`sync_entry`): in a package, files with the same gap share one question, and the answer is
applied to all of them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from . import crs as crslib
from . import db as dblib
from .parsing import parse_crs_text, parse_date_text

_TEMPLATES = Path(__file__).resolve().parent / "prompts" / "questions_v1.yaml"
FIELD_ORDER = ["horizontal_epsg", "height_reference", "data_date", "source", "quality", "comments"]
RULE_FIELDS = {"R-CRS-01": "horizontal_epsg", "R-CRS-03": "horizontal_epsg", "R-EXT-01": "horizontal_epsg",
               "R-REF-01": "horizontal_epsg", "R-CRS-02": "height_reference", "R-DATE-01": "data_date",
               "R-SRC-01": "source", "R-QUA-01": "quality"}
FIELD_LABELS = {"horizontal_epsg": "Koordinatsystem", "height_reference": "Høydesystem", "data_date": "Dato",
                "source": "Kilde / leverandør", "quality": "Nøyaktighet / kvalitet", "comments": "Kommentarer",
                "data_type": "Datatype"}


class AnswerError(ValueError):
    """The answer could not be understood; the question stays open."""


@lru_cache(maxsize=1)
def templates() -> dict:
    """Question wording, from the editable YAML file."""
    return yaml.safe_load(_TEMPLATES.read_text(encoding="utf-8"))


def _display(field: str, value) -> str:
    return crslib.short_name(value) if field == "horizontal_epsg" else str(value)


def _choice(field: str, value, suffix: str = "") -> str:
    if field == "horizontal_epsg":
        return f"EPSG:{value} – {crslib.short_name(value)}{suffix}"
    return f"{_display(field, value)}{suffix}"


def needed(fdoc: dict, checks: list, eff: dict, plaus: dict, conflicts: list[str]) -> list[dict]:
    """The question specs one file needs right now (asked later, per register entry)."""
    t = templates()
    dk = t["dont_know"]
    specs: dict[str, dict] = {}
    for c in checks:
        field = RULE_FIELDS.get(c.rule_id)
        if not field or field in specs:
            continue
        cand = (c.data or {}).get("candidates") or plaus.get("candidates") or []
        if field == "horizontal_epsg" and c.rule_id == "R-CRS-03" and c.result == "deviation" and cand \
                and eff["horizontal_epsg"].get("from") == "file":
            tpl, declared = t["horizontal_epsg"], eff["horizontal_epsg"]["value"]
            best = cand[0]["epsg"]
            specs[field] = {"field": field, "kind": "contradiction", "variant": f"{declared}>{best}",
                            "declared": _display(field, declared),
                            "reason": tpl["reason_fits"].format(candidate=crslib.short_name(best)),
                            "choices": [_choice(field, best, tpl["fits_suffix"]), _choice(field, declared, tpl["file_suffix"]), dk],
                            "suggested": _choice(field, best, tpl["fits_suffix"])}
        elif c.result == "missing_info":
            tpl = t[field]
            choices: list[str] = []
            suggested = None
            if field == "horizontal_epsg":
                for cc in cand[:2]:
                    choices.append(_choice(field, cc["epsg"], tpl["fits_suffix"]))
                suggested = choices[0] if choices else None
                for ch in tpl["choices"]:
                    code = parse_crs_text(ch)
                    if not any(code and f"EPSG:{code} " in x for x in choices):
                        choices.append(ch)
            else:
                choices = list(tpl.get("choices", []))
            specs[field] = {"field": field, "kind": "ask", "variant": "", "choices": choices + [dk],
                            "suggested": suggested, "hint": tpl.get("hint", "")}

    for field in conflicts:
        if field in specs or "contradiction" not in t.get(field, {}):
            continue
        tpl = t[field]
        file_v, form_v = eff[field]["value"], eff[field]["conflict"]
        specs[field] = {"field": field, "kind": "contradiction", "variant": f"form:{file_v}>{form_v}",
                        "declared": _display(field, file_v), "candidate": _display(field, form_v),
                        "reason": t["horizontal_epsg"]["reason_form"].format(candidate=_display(field, form_v)),
                        "choices": [_choice(field, file_v, tpl.get("file_suffix", "")),
                                    _choice(field, form_v, tpl.get("form_suffix", "")), t["dont_know"]],
                        "suggested": None}
    return [specs[f] for f in FIELD_ORDER if f in specs]


def _wording(spec: dict, entry: dict, count: int, total: int) -> str:
    t = templates()[spec["field"]]
    package = entry.get("kind") == "package"
    key = spec["kind"] if spec["kind"] == "ask" else "contradiction"
    tpl = t.get(f"{key}_package") if package and t.get(f"{key}_package") else t[key]
    return tpl.format(file=entry["name"], count=count, total=total, declared=spec.get("declared", ""),
                      reason=spec.get("reason", ""), candidate=spec.get("candidate", ""))


def sync_entry(db, entry: dict, files: list[dict], now) -> tuple[list[dict], int]:
    """Create, update or withdraw an entry's questions. Returns (new questions, open count)."""
    coll = db[dblib.QUESTIONS]
    t = templates()
    existing = list(coll.find({"entry_id": entry["_id"]}))
    open_by_key = {q["key"]: q for q in existing if q["status"] == "open"}
    answered = {q["key"] for q in existing if q["status"] == "answered"}
    groups: dict[str, dict] = {}
    for f in files:
        given = set((f.get("uploader_values") or {}).keys())
        for spec in f.get("question_specs") or []:
            if spec["kind"] != "contradiction" and spec["field"] in given:
                continue
            key = f"{spec['field']}|{spec['kind']}|{spec.get('variant', '')}"
            if key in answered and spec["kind"] != "contradiction":
                continue
            g = groups.setdefault(key, {**spec, "key": key, "file_ids": [], "file_names": []})
            g["file_ids"].append(f["_id"])
            g["file_names"].append(f["file_name"])
    wanted = [groups[k] for k in sorted(groups, key=lambda k: FIELD_ORDER.index(groups[k]["field"]))]
    wanted = wanted[: int(t.get("max_per_entry", 5)) - 1]
    if wanted and not entry.get("uploader_comment") and "comments|ask|" not in answered:
        wanted.append({"field": "comments", "kind": "ask", "variant": "", "key": "comments|ask|", "choices": [],
                       "suggested": None, "hint": t["comments"]["hint"], "optional": True,
                       "file_ids": [f["_id"] for f in files], "file_names": [f["file_name"] for f in files]})
    total = len(files)
    created = []
    for g in wanted:
        question = (t["comments"]["ask"].format(file=entry["name"]) if g["field"] == "comments"
                    else _wording(g, entry, len(g["file_ids"]), total))
        fields = {"kind": g["kind"], "question": question, "choices": g["choices"], "suggested": g.get("suggested"),
                  "hint": g.get("hint", ""), "optional": bool(g.get("optional")), "file_ids": g["file_ids"],
                  "file_names": g["file_names"]}
        if g["key"] in open_by_key:
            coll.update_one({"_id": open_by_key[g["key"]]["_id"]}, {"$set": fields})
        else:
            q = {"_id": dblib.new_id("bdq"), "entry_id": entry["_id"], "project_id": entry["project_id"],
                 "entry_name": entry["name"], "entry_seq": entry.get("seq"), "key": g["key"], "field": g["field"],
                 "uploader_email": (entry.get("uploader") or {}).get("email", ""),
                 "uploader_name": (entry.get("uploader") or {}).get("name", ""), "status": "open", "answer": None,
                 "asked_at": now, "answered_at": None, "reminder_sent_at": None, **fields}
            coll.insert_one(q)
            created.append(q)
    keep = {g["key"] for g in wanted}
    for key, q in open_by_key.items():
        if key not in keep:
            coll.update_one({"_id": q["_id"]}, {"$set": {"status": "withdrawn", "withdrawn_at": now}})
    open_count = coll.count_documents({"entry_id": entry["_id"], "status": "open"})
    return created, open_count


def _over(answer: str, kind: str) -> bool:
    return kind == "contradiction" and "(som oppgitt i fila)" not in answer


def parse_answer(field: str, answer: str, kind: str = "ask") -> dict:
    """Turn an answer into an uploader value: {value, unknown, raw, confirmed_over_file}."""
    a = (answer or "").strip()
    if not a:
        raise AnswerError("Skriv et svar, eller velg «Vet ikke».")
    if a == templates()["dont_know"]:
        return {"value": None, "unknown": True, "raw": a}
    plain = a.split(" (")[0]
    if field == "horizontal_epsg":
        if a.lower().startswith("lokal"):
            return {"value": "LOCAL", "raw": a}
        epsg = parse_crs_text(a)
        if epsg is None:
            raise AnswerError("Fant ikke et koordinatsystem i svaret – prøv for eksempel «EPSG:25832».")
        return {"value": epsg, "raw": a, "confirmed_over_file": _over(a, kind)}
    if field == "height_reference":
        if a.lower().startswith("ingen høyder"):
            return {"value": "NONE", "raw": a}
        return {"value": crslib.normalize_height(plain), "raw": a, "confirmed_over_file": _over(a, kind)}
    if field == "data_date":
        return {"value": parse_date_text(plain), "raw": a, "confirmed_over_file": _over(a, kind)}
    if field in ("source", "quality", "comments"):
        return {"value": plain if kind == "contradiction" else a, "raw": a, "confirmed_over_file": _over(a, kind)}
    if field == "data_type":
        return {"value": a, "raw": a}
    raise AnswerError(f"Ukjent felt {field!r}.")
