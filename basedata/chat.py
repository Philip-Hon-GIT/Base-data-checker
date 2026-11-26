"""AI chat over a project's base data: search, look up, relate and analyse registrations.

The model never sees the database directly. It gets a handful of read-only tools (search the
register, read one registration, follow relations, search the text inside documents, project
overview) and answers from what they return, citing registrations as #<nr>. With no AI provider
set up, a rule-based stand-in answers common questions with the same tools, clearly labelled.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from . import ai as ailib
from . import db as dblib
from .classify import DATA_TYPES
from .content import entry_profile
from .relations import for_entry
from .text import LIFECYCLE, QA_STATUS, READY, RESULT_LABELS, nb

OFFLINE_MODEL = "offline-demo (regelbasert erstatning, ikke en AI-modell)"
MAX_ROUNDS = 6

SYSTEM = """Du er en assistent for grunnlagsdata i et samferdselsprosjekt (veg, VA, konstruksjon). Brukeren
er prosjekterende eller KS-ansvarlig. Du svarer på norsk (bokmål), kort og konkret.

Grunnlagsdata kan være tegninger (PDF/DXF), dokumenter og rapporter, BIM-modeller (IFC), kartdata (SOSI,
GeoPackage), terrengmodeller, punktskyer og ortofoto. Hver registrering har et nummer (#1, #2 …) og kan
være en enkeltfil eller en pakke med mange filer.

Regler:
- Bruk verktøyene for å finne svaret. Ikke gjett på innhold du ikke har slått opp.
- Vis til registreringer som #nummer (for eksempel «#9 Terrengmodell_DTM2_2026.tif»), så blir de lenker.
- Si tydelig når noe mangler i dataene eller ikke er kontrollert.
- Ved analyse: forklar hva tallene betyr for prosjekteringen (nøyaktighet, alder, dekning, avvik).
- Utgåtte registreringer er erstattet av nyere versjoner; nevn det hvis de dukker opp.
- Skriv ren tekst: korte avsnitt og punktlister som starter med «- ». Ingen overskrifter, ingen tabeller."""

TOOLS = [
    {"name": "search_entries",
     "description": "Søk og filtrer i registeret. Returnerer registreringer med nummer, navn, type, innhold, mottatt, "
                    "resultat av automatisk kontroll, KS-status og om de er klare til bruk. Alle felt er valgfrie.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "Fritekst mot navn, innhold, nøkkelord og filnavn"},
         "data_type": {"type": "string", "enum": list(DATA_TYPES)},
         "check_result": {"type": "string", "enum": list(RESULT_LABELS)},
         "qa_status": {"type": "string", "enum": list(QA_STATUS)},
         "ready": {"type": "string", "enum": [*READY, "ikke_vurdert"]},
         "lifecycle": {"type": "string", "enum": list(LIFECYCLE)},
         "missing": {"type": "string", "enum": ["koordinatsystem", "høydesystem", "dato", "kilde", "kvalitet"]},
         "older_than_years": {"type": "number"},
         "discipline": {"type": "string"},
         "has_open_questions": {"type": "boolean"}}}},
    {"name": "get_entry",
     "description": "Alt om én registrering: innhold, metadata, kontroller som ikke er OK, åpne spørsmål, "
                    "sammenligning med referanse og KS.",
     "input_schema": {"type": "object", "properties": {"nr": {"type": "integer"}}, "required": ["nr"]}},
    {"name": "related",
     "description": "Hvordan en registrering henger sammen med andre: versjoner, referanse, omtaler i tekst, "
                    "samme leveranse og samme område.",
     "input_schema": {"type": "object", "properties": {"nr": {"type": "integer"}}, "required": ["nr"]}},
    {"name": "search_text",
     "description": "Søk i teksten inne i dokumenter, rapporter, tegningshoder og leveransenotater. "
                    "Returnerer utdrag med registreringsnummer.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "project_overview",
     "description": "Oversikt over prosjektet: antall per datatype, kontrollresultat, KS-status, utgåtte og åpne spørsmål.",
     "input_schema": {"type": "object", "properties": {}}},
]


# --- Data access ------------------------------------------------------------------------------------------

class Data:
    """A project's register as plain rows, loaded once per chat request."""

    def __init__(self, db, project_id: str, now: datetime):
        self.db, self.project_id, self.now = db, project_id, now
        self.project = db[dblib.PROJECTS].find_one({"_id": project_id}) or {}
        self.entries = sorted(db[dblib.ENTRIES].find({"project_id": project_id}), key=lambda e: e.get("seq", 0))
        self.files: dict[str, list[dict]] = {}
        for f in db[dblib.FILES].find({"project_id": project_id}):
            self.files.setdefault(f.get("entry_id"), []).append(f)
        self.by_seq = {e.get("seq"): e for e in self.entries}

    def eff(self, e: dict, field: str):
        vals = [((f.get("effective") or {}).get(field) or {}).get("value") for f in self.files.get(e["_id"], [])]
        vals = [v for v in vals if v not in (None, "")]
        return vals[0] if vals else None

    def row(self, e: dict) -> dict:
        prof = entry_profile(e, self.files.get(e["_id"], []))
        return {"nr": e.get("seq"), "navn": e["name"], "type": DATA_TYPES.get(e.get("data_type"), "Annet"),
                "pakke": e.get("kind") == "package", "filer": e.get("file_count"), "innhold": prof.get("summary"),
                "mottatt": str(e.get("received_at"))[:10], "fra": e.get("received_from_override") or (e.get("uploader") or {}).get("name"),
                "fag": e.get("discipline"), "automatisk_kontroll": RESULT_LABELS.get(e.get("check_result"), e.get("check_result")),
                "regler_med_merknad": e.get("deviations", []), "status_kontroll": QA_STATUS.get(e.get("qa_status")),
                "klar_til_bruk": READY.get(e.get("ready")) or "ikke vurdert", "gjeldende": LIFECYCLE.get(e.get("lifecycle", "gjeldende")),
                "åpne_spørsmål": e.get("open_questions", 0)}

    def text_of(self, e: dict) -> str:
        files = self.files.get(e["_id"], [])
        prof = entry_profile(e, files)
        parts = [e["name"], prof.get("summary") or "", " ".join(prof.get("keywords") or []), e.get("content_auto") or "",
                 " ".join(f["file_name"] for f in files), DATA_TYPES.get(e.get("data_type"), "")]
        return " ".join(parts).lower()


def _year(v) -> int | None:
    m = re.match(r"(\d{4})", str(v or ""))
    return int(m.group(1)) if m else None


def search_entries(data: Data, args: dict) -> dict:
    rows = []
    words = [w for w in re.findall(r"\w+", str(args.get("text") or "").lower()) if len(w) > 1]
    for e in data.entries:
        if args.get("data_type") and e.get("data_type") != args["data_type"]:
            continue
        if args.get("check_result") and e.get("check_result") != args["check_result"]:
            continue
        if args.get("qa_status") and e.get("qa_status") != args["qa_status"]:
            continue
        if args.get("ready"):
            if args["ready"] == "ikke_vurdert" and e.get("ready"):
                continue
            if args["ready"] != "ikke_vurdert" and e.get("ready") != args["ready"]:
                continue
        if args.get("lifecycle") and e.get("lifecycle", "gjeldende") != args["lifecycle"]:
            continue
        if args.get("discipline") and (e.get("discipline") or "").upper() != str(args["discipline"]).upper():
            continue
        if args.get("has_open_questions") is not None and bool(e.get("open_questions")) != bool(args["has_open_questions"]):
            continue
        miss = args.get("missing")
        if miss:
            field = {"koordinatsystem": "horizontal_epsg", "høydesystem": "height_reference", "dato": "data_date",
                     "kilde": "source", "kvalitet": "quality"}[miss]
            v = data.eff(e, field)
            if field == "horizontal_epsg" and isinstance(v, int):
                continue
            if field != "horizontal_epsg" and v:
                continue
            if miss in ("koordinatsystem", "høydesystem") and e.get("data_type") == "document":
                continue
        if args.get("older_than_years"):
            y = _year(data.eff(e, "data_date"))
            if y is None or data.now.year - y <= float(args["older_than_years"]):
                continue
        if words:
            t = data.text_of(e)
            if not all(w in t for w in words):
                continue
        rows.append(data.row(e))
    return {"antall": len(rows), "registreringer": rows[:30]}


def get_entry(data: Data, args: dict) -> dict:
    e = data.by_seq.get(int(args.get("nr") or 0))
    if not e:
        raise ValueError(f"Fant ikke registrering #{args.get('nr')}.")
    files = sorted(data.files.get(e["_id"], []), key=lambda f: f["file_name"])
    prof = entry_profile(e, files)
    out = {**data.row(e), "beskrivelse": prof.get("summary"), "fakta": dict(prof.get("facts") or []),
           "georeferanse": prof.get("georef"), "ks_merknad": e.get("qa_note") or None,
           "beslutning": (e.get("review") or {}).get("comment"),
           "verdier": {k: data.eff(e, k) for k in ("horizontal_epsg", "height_reference", "data_date", "source", "quality")}}
    issues = []
    for f in files:
        for c in data.db[dblib.CHECKS].find({"file_id": f["_id"], "run_id": f.get("last_run_id")}):
            if c["result"] != "ok":
                issues.append({"fil": f["file_name"], "regel": c["rule_id"], "krav": c["rule_text"],
                               "resultat": RESULT_LABELS.get(c["result"]), "belegg": str(c.get("evidence") or "")[:220]})
    out["merknader"] = issues[:20]
    comps = []
    for f in files:
        c = f.get("comparison") or {}
        if c.get("status") == "done":
            ref = c.get("reference") or {}
            comps.append({"fil": f["file_name"], "referanse": f"#{ref.get('entry_seq')} {ref.get('file_name')}",
                          "systematisk_avvik_m": c.get("mean_m"), "spredning_m": c.get("std_m"), "p95_m": c.get("p95_abs_m"),
                          "størst_avvik_m": c.get("max_m"), "endret_areal_over_0_5m_m2": (c.get("area_over_m2") or {}).get("0.5"),
                          "forskyvning": (c.get("shift") or {}).get("suspected") and (c.get("shift") or {})})
        elif c.get("status"):
            comps.append({"fil": f["file_name"], "status": c["status"]})
    if comps:
        out["sammenligning_med_referanse"] = comps
    qs = data.db[dblib.QUESTIONS].find({"entry_id": e["_id"], "status": "open"})
    out["åpne_spørsmål_tekst"] = [q["question"] for q in qs]
    if e.get("comments"):
        out["kommentarer"] = [f"{c.get('by_name') or c.get('by')}: {c['text']}" for c in e["comments"][-10:]]
    corr = [f"{k} korrigert manuelt" for k in e.get("corrected_fields") or []]
    corr += [f"{k} overstyrt til {RESULT_LABELS.get(o['result'])}: {o.get('comment')}" for k, o in (e.get("check_overrides") or {}).items()]
    if corr:
        out["manuelle_korreksjoner"] = corr
    if e.get("superseded_by"):
        out["erstattet_av"] = f"#{e['superseded_by'].get('seq')} {e['superseded_by'].get('name')}"
    return out


def related(data: Data, args: dict) -> dict:
    e = data.by_seq.get(int(args.get("nr") or 0))
    if not e:
        raise ValueError(f"Fant ikke registrering #{args.get('nr')}.")
    return {"nr": e.get("seq"), "navn": e["name"],
            "relasjoner": [{"type": g["label"], "registreringer": [f"#{x['seq']} {x['name']}" + (f" ({x['note']})" if x["note"] else "")
                                                                   + (" – utgått" if x["lifecycle"] == "utgatt" else "")
                                                                   for x in g["entries"]]} for g in for_entry(data.db, e)]}


def search_text(data: Data, args: dict) -> dict:
    q = str(args.get("query") or "").strip().lower()
    words = [w for w in re.findall(r"\w+", q) if len(w) > 2]
    if not words:
        raise ValueError("Skriv hva du leter etter.")
    hits = []
    for e in data.entries:
        for f in data.files.get(e["_id"], []):
            texts = [(f["file_name"], (f.get("metadata") or {}).get("text_excerpt") or "")]
            texts += [(t["name"], t.get("text") or "") for t in f.get("context_texts") or [] if t.get("name") != f["file_name"]]
            for name, text in texts:
                low = text.lower()
                pos = [low.find(w) for w in words if w in low]
                if not pos:
                    continue
                p = min(pos)
                snippet = re.sub(r"\s+", " ", text[max(0, p - 120): p + 200]).strip()
                hits.append({"nr": e.get("seq"), "registrering": e["name"], "kilde": name, "treff": len(pos), "utdrag": snippet})
    seen, out = set(), []
    for h in sorted(hits, key=lambda h: -h["treff"]):
        key = (h["nr"], h["kilde"])
        if key not in seen:
            seen.add(key)
            out.append(h)
    return {"antall": len(out), "treff": out[:12]}


def project_overview(data: Data, args: dict) -> dict:
    from collections import Counter
    es = data.entries
    return {"prosjekt": data.project.get("name"), "koordinatsystem": data.project.get("horizontal_crs"),
            "høydesystem": data.project.get("height_reference"), "registreringer": len(es),
            "filer": sum(e.get("file_count", 0) for e in es),
            "per_type": dict(Counter(DATA_TYPES.get(e.get("data_type"), "Annet") for e in es)),
            "automatisk_kontroll": dict(Counter(RESULT_LABELS.get(e.get("check_result"), "") for e in es)),
            "status_kontroll": dict(Counter(QA_STATUS.get(e.get("qa_status"), "") for e in es)),
            "klar_til_bruk": dict(Counter(READY.get(e.get("ready")) or "ikke vurdert" for e in es)),
            "utgått": [f"#{e.get('seq')} {e['name']}" for e in es if e.get("lifecycle") == "utgatt"],
            "åpne_spørsmål": sum(e.get("open_questions", 0) for e in es),
            "med_avvik": [f"#{e.get('seq')} {e['name']} ({', '.join(e.get('deviations', []))})" for e in es
                          if e.get("check_result") == "deviation"]}


FUNCS = {"search_entries": search_entries, "get_entry": get_entry, "related": related, "search_text": search_text,
         "project_overview": project_overview}


def run_tool(data: Data, name: str, args: dict) -> dict:
    try:
        return FUNCS[name](data, args or {})
    except (ValueError, KeyError) as exc:
        return {"feil": str(exc)}


# --- The conversation --------------------------------------------------------------------------------------

def _clean(messages: list[dict]) -> list[dict]:
    out = [{"role": m.get("role"), "content": str(m.get("content") or "")[:4000]} for m in messages or []
           if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()]
    out = out[-12:]
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise ValueError("Skriv et spørsmål.")
    return out


def chat(ctx, project_id: str, messages: list[dict], lang: str = "nb") -> dict:
    """Answer the last user message. Returns {answer, model, tools: [names used]}."""
    msgs = _clean(messages)
    data = Data(ctx.db, project_id, ctx.now())
    settings = ctx.settings
    system = SYSTEM + f"\n\nProsjekt: {data.project.get('name')} ({data.project.get('project_type')}, " \
                      f"{data.project.get('phase')}), {data.project.get('horizontal_crs')}, {data.project.get('height_reference')}. " \
                      f"I dag: {data.now.date().isoformat()}." + ("\n\nThe user has chosen English: answer in English (keep Norwegian "
                                                       "names of files, fields and rules as they are)." if lang == "en" else "")
    if settings.ai_provider == "anthropic":
        return _anthropic(settings, system, msgs, data)
    if settings.ai_provider == "azure_openai":
        return _azure(settings, system, msgs, data)
    if settings.ai_provider == "offline_demo":
        return offline_answer(data, msgs[-1]["content"])
    raise ValueError("AI er ikke satt opp (BASEDATA_AI_PROVIDER), så chatten er ikke tilgjengelig.")


def _anthropic(settings, system: str, msgs: list[dict], data: Data) -> dict:
    convo = [dict(m) for m in msgs]
    used = []
    headers = {"x-api-key": settings.ai_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    for _ in range(MAX_ROUNDS):
        body = {"model": settings.ai_model, "max_tokens": 2000, "system": system, "messages": convo, "tools": TOOLS}
        resp = ailib._post("https://api.anthropic.com/v1/messages", headers, body, settings.ai_timeout_s)
        blocks = resp.get("content", [])
        calls = [b for b in blocks if b.get("type") == "tool_use"]
        if not calls:
            return {"answer": "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip(),
                    "model": f"anthropic:{settings.ai_model}", "tools": used}
        convo.append({"role": "assistant", "content": blocks})
        results = []
        for c in calls:
            used.append(c["name"])
            results.append({"type": "tool_result", "tool_use_id": c["id"],
                            "content": json.dumps(run_tool(data, c["name"], c.get("input") or {}), ensure_ascii=False, default=str)[:30000]})
        convo.append({"role": "user", "content": results})
    return {"answer": "Fikk ikke et ferdig svar innen grensen for antall oppslag. Prøv et mer avgrenset spørsmål.",
            "model": f"anthropic:{settings.ai_model}", "tools": used}


def _azure(settings, system: str, msgs: list[dict], data: Data) -> dict:
    url = (f"{settings.azure_endpoint.rstrip('/')}/openai/deployments/{settings.ai_model}"
           f"/chat/completions?api-version={settings.azure_api_version}")
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                               "parameters": t["input_schema"]}} for t in TOOLS]
    convo = [{"role": "system", "content": system}, *msgs]
    used = []
    for _ in range(MAX_ROUNDS):
        resp = ailib._post(url, {"api-key": settings.ai_api_key, "content-type": "application/json"},
                           {"messages": convo, "tools": tools}, settings.ai_timeout_s)
        msg = resp["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"answer": (msg.get("content") or "").strip(), "model": f"azure_openai:{settings.ai_model}", "tools": used}
        convo.append(msg)
        for c in calls:
            name = c["function"]["name"]
            used.append(name)
            args = json.loads(c["function"].get("arguments") or "{}")
            convo.append({"role": "tool", "tool_call_id": c["id"],
                          "content": json.dumps(run_tool(data, name, args), ensure_ascii=False, default=str)[:30000]})
    return {"answer": "Fikk ikke et ferdig svar innen grensen for antall oppslag.", "model": f"azure_openai:{settings.ai_model}",
            "tools": used}


# --- Offline stand-in ------------------------------------------------------------------------------------------

_TYPE_WORDS = [("drawing", r"tegning"), ("point_cloud", r"punktsk|laser"), ("terrain", r"terreng|dtm"),
               ("orthophoto", r"ortofoto|flyfoto"), ("model", r"\bmodell|\bifc|\bbim\b"), ("utility", r"ledning"),
               ("ground_investigation", r"grunnunders|geotekn|boring"), ("fkb", r"\bfkb"), ("document", r"dokument|beskrivelse")]


def _list(rows: list[dict], extra=None) -> str:
    lines = []
    for r in rows[:15]:
        bit = f"- #{r['nr']} {r['navn']} – {(r['innhold'] or r['type']).rstrip('.')}"
        if extra:
            bit += f" ({extra(r)})"
        lines.append(bit)
    if len(rows) > 15:
        lines.append(f"- … og {len(rows) - 15} til")
    return "\n".join(lines)


def offline_answer(data: Data, question: str) -> dict:
    """Common questions answered with the same tools, without an AI model."""
    q = question.lower()
    used: list[str] = []

    def call(name, args=None):
        used.append(name)
        return run_tool(data, name, args or {})

    def done(text):
        return {"answer": text, "model": OFFLINE_MODEL, "tools": used}

    nr = re.search(r"#\s*(\d+)", q)
    if not nr:
        for e in data.entries:
            stem = e["name"].lower().rsplit(".", 1)[0]
            if stem in q or e["name"].lower() in q:
                nr = re.match(r"(\d+)", str(e.get("seq")))
                break
    if nr and re.search(r"relat|henger sammen|kobl|forbindelse|sammenheng", q):
        r = call("related", {"nr": int(nr.group(1))})
        if "feil" in r:
            return done(r["feil"])
        if not r["relasjoner"]:
            return done(f"Fant ingen relasjoner for #{r['nr']} {r['navn']}.")
        return done(f"#{r['nr']} {r['navn']} henger sammen med:\n" +
                    "\n".join(f"- {g['type']}: {', '.join(g['registreringer'])}" for g in r["relasjoner"]))
    if nr:
        e = call("get_entry", {"nr": int(nr.group(1))})
        if "feil" in e:
            return done(e["feil"])
        lines = [f"#{e['nr']} {e['navn']} ({e['type']}): {e['beskrivelse']}",
                 f"- Automatisk kontroll: {e['automatisk_kontroll']}; status kontroll: {e['status_kontroll']}; klar til bruk: {e['klar_til_bruk']}."]
        for m in e["merknader"][:5]:
            lines.append(f"- {m['regel']} {m['resultat']}: {m['belegg']}")
        comps = sorted((c for c in e.get("sammenligning_med_referanse", []) if "systematisk_avvik_m" in c),
                       key=lambda c: -abs(c["systematisk_avvik_m"] or 0))
        if comps:
            c = comps[0]
            lines.append(f"- Sammenlignet med {c['referanse']}" + (f" ({len(comps)} filer)" if len(comps) > 1 else "")
                         + f": største systematiske avvik {nb(c['systematisk_avvik_m'], 2, signed=True)} m i {c['fil']}, "
                         f"spredning {nb(c['spredning_m'], 2)} m.")
        if e["åpne_spørsmål_tekst"]:
            lines.append(f"- {len(e['åpne_spørsmål_tekst'])} åpne spørsmål til opplaster.")
        if e.get("erstattet_av"):
            lines.append(f"- Utgått, erstattet av {e['erstattet_av']}.")
        return done("\n".join(lines))

    args: dict = {}
    for key, pat in _TYPE_WORDS:
        if re.search(pat, q):
            args["data_type"] = key
            break
    if re.search(r"koordinatsystem|crs|epsg", q) and re.search(r"mangl|uten|ukjent|ikke", q):
        args["missing"] = "koordinatsystem"
    elif re.search(r"høydesystem", q) and re.search(r"mangl|uten|ukjent", q):
        args["missing"] = "høydesystem"
    elif re.search(r"kilde|leverandør", q) and re.search(r"mangl|uten|ukjent", q):
        args["missing"] = "kilde"
    elif re.search(r"dato", q) and re.search(r"mangl|uten|ukjent", q):
        args["missing"] = "dato"
    m = re.search(r"eldre enn (\d+)", q)
    if m:
        args["older_than_years"] = int(m.group(1))
    if "avvik" in q:
        args["check_result"] = "deviation"
    elif "mangler info" in q:
        args["check_result"] = "missing_info"
    if re.search(r"utgått|gamle versjon|erstattet", q):
        args["lifecycle"] = "utgatt"
    if re.search(r"åpne spørsmål|ubesvart", q):
        args["has_open_questions"] = True
    if re.search(r"klar til bruk|godkjent", q) and not re.search(r"ikke", q):
        args["ready"] = "ja"
    if re.search(r"ikke (begynt|kontrollert)", q):
        args["qa_status"] = "ikke_begynt"

    if not args and re.search(r"oppsummer|oversikt|status|hvordan står", q):
        o = call("project_overview")
        lines = [f"{o['prosjekt']}: {o['registreringer']} registreringer med {o['filer']} filer.",
                 "- Typer: " + ", ".join(f"{k} {v}" for k, v in o["per_type"].items()),
                 "- Automatisk kontroll: " + ", ".join(f"{k} {v}" for k, v in o["automatisk_kontroll"].items()),
                 "- Status kontroll: " + ", ".join(f"{k} {v}" for k, v in o["status_kontroll"].items()),
                 f"- {o['åpne_spørsmål']} åpne spørsmål til opplastere."]
        if o["med_avvik"]:
            lines.append("- Avvik: " + "; ".join(o["med_avvik"]))
        if o["utgått"]:
            lines.append("- Utgått: " + ", ".join(o["utgått"]))
        return done("\n".join(lines))

    if args:
        r = call("search_entries", args)
        rows = r["registreringer"]
        if not rows:
            return done("Fant ingen registreringer som passer.")
        extra = None
        if args.get("check_result") or args.get("has_open_questions"):
            extra = lambda x: ", ".join(x["regler_med_merknad"]) or f"{x['åpne_spørsmål']} spm."  # noqa: E731
        return done(f"Fant {r['antall']}:\n" + _list(rows, extra))

    words = re.sub(r"\b(finn|søk|vis|hvor|hva|står|det|om|etter|i|på|noe|alle|som|er|med|jeg|kan|hvilke)\b", " ", q)
    t = call("search_text", {"query": words})
    r = call("search_entries", {"text": " ".join(w for w in re.findall(r"\w+", words) if len(w) > 3)[:60]})
    if not t.get("treff") and not r.get("registreringer"):
        return done("Fant ikke noe som passer. Prøv å spørre om en datatype (tegninger, terrengmodeller, punktskyer), "
                    "et nummer (#9), avvik, åpne spørsmål eller noe som mangler koordinatsystem.")
    lines = []
    if r.get("registreringer"):
        lines.append("Registreringer:\n" + _list(r["registreringer"]))
    if t.get("treff"):
        lines.append("I teksten:\n" + "\n".join(f"- #{h['nr']} {h['kilde']}: «…{h['utdrag'][:160]}…»" for h in t["treff"][:6]))
    return done("\n\n".join(lines))
