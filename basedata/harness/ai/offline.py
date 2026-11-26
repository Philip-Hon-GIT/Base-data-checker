"""A rule-based stand-in for the AI step, for demos and tests without an AI provider.

It is NOT an AI model. It follows the same output contract (found values with evidence quotes, rule
results with evidence and confidence, a short comment, drafted rules) using regular expressions and
fixed thresholds, so the rest of the pipeline and the web pages can be shown end to end. Everything
it produces is labelled "offline-demo" in the register.
"""

from __future__ import annotations

import re

from basedata.core.classify import DATA_TYPES
from basedata.harness.parsing import parse_date_text
from basedata.core.text import nb

_PATTERNS = {
    "source": r"(?:Levert av|Utført av|Leverandør|Produsent|Supplier|Delivered by)\s*:?\s*([^\n.;]+)",
    "data_date": r"(?:Skannet|Målt|Fotografert|Innmålt|Feltarbeid\w*(?: ble)? utført)\s*:?\s*(?:i\s+)?"
                 r"(\d{1,2}\.\d{1,2}\.\d{4}|[A-Za-zæøå]{3,9}\s+\d{4}|\d{4})",
    "horizontal_crs": r"((?:EUREF89|ETRS89)\s*(?:UTM|NTM)\s*(?:sone|zone)?\s*\d{1,2}|EPSG:\d{4,5})",
    "height_reference": r"(NN2000|NN1954|NN54)",
    "quality": r"((?:Nøyaktighet|nøyaktighet|Punkttetthet|Accuracy)[^\n]*)",
}


def _find(texts: list[dict]) -> dict:
    found: dict = {}
    for name, pattern in _PATTERNS.items():
        for t in texts:
            m = re.search(pattern, t.get("text", ""))
            if m:
                line = next((ln for ln in t["text"].splitlines() if m.group(0) in ln), m.group(0)).strip()
                found[name] = {"value": m.group(1).strip(), "evidence": line}
                break
    return found


def _quality(dtype: str, md: dict, found: dict, given: str | None = None) -> tuple[str, str, float, str]:
    q = md.get("quality") or {}
    text_q = found.get("quality", {}).get("evidence")
    if dtype == "orthophoto" and q.get("pixel_size_m"):
        px = q["pixel_size_m"]
        ev = f"pixel_size_m = {px}"
        if px <= 0.25:
            return "ok", ev, 0.9, f"{nb(px)} m piksler holder for reguleringsplan."
        if px <= 0.5:
            return "warning", ev, 0.85, f"{nb(px)} m piksler er grovere enn vanlige 0,25 m."
        return "deviation", ev, 0.85, f"{nb(px)} m piksler er for grovt for planlegging."
    if dtype == "terrain" and q.get("pixel_size_m"):
        px = q["pixel_size_m"]
        ev = f"pixel_size_m = {px}"
        if px <= 2:
            return "ok", ev, 0.85, f"{nb(px, 0)} m rutenett holder for reguleringsplan."
        if px <= 5:
            return "warning", ev, 0.8, f"{nb(px, 0)} m rutenett passer for oversikt, ikke detaljprosjektering."
        return "deviation", ev, 0.8, f"{nb(px, 0)} m rutenett er for grovt."
    if dtype == "point_cloud" and q.get("density_pts_per_m2"):
        d = q["density_pts_per_m2"]
        ev = f"density_pts_per_m2 = {d}" + (f"; tekst: «{text_q}»" if text_q else "")
        if d >= 5:
            return "ok", ev, 0.85, f"{nb(d, 1)} punkter/m² holder for planlegging."
        if d >= 2:
            return "warning", ev, 0.8, f"{nb(d, 1)} punkter/m² er lavt for detaljert terrengmodell."
        return "deviation", ev, 0.8, f"{nb(d, 1)} punkter/m² er for glissent."
    if dtype == "fkb" and isinstance(q.get("accuracy_cm"), dict):
        med = q["accuracy_cm"]["median"]
        ev = f"accuracy_cm median = {med}"
        if med <= 20:
            return "ok", ev, 0.85, f"Median nøyaktighet {nb(med, 0)} cm er i tråd med FKB-A/B."
        if med <= 50:
            return "warning", ev, 0.8, f"Median nøyaktighet {nb(med, 0)} cm er grovere enn FKB-B."
        return "deviation", ev, 0.8, f"Median nøyaktighet {nb(med, 0)} cm er for grov."
    d = md.get("details") or {}
    if dtype == "drawing" and d.get("scale"):
        ev = f"målestokk {d['scale']}" + (f", ark {d['paper']}" if d.get("paper") else "")
        return "ok", ev, 0.75, f"Tegning i målestokk {d['scale']} holder for reguleringsplan."
    if dtype == "model" and d.get("elements"):
        ev = "georeferert med " + d["georef_from"] if d.get("georef_from") else "ingen georeferanse"
        return ("ok" if d.get("georef_from") else "warning"), ev, 0.6, \
            "Modellen er georeferert; detaljeringsgraden må vurderes av fagansvarlig." if d.get("georef_from") \
            else "Modellen ligger i lokale koordinater og kan ikke kontrolleres mot kart."
    if given and given != "Vet ikke":
        return "ok", f"Opplaster: «{given}»", 0.6, "Nøyaktighet er bare oppgitt av opplaster; KS-ansvarlig bør vurdere om det holder."
    if text_q:
        return "ok", text_q, 0.6, "Nøyaktighet står bare i teksten; KS-ansvarlig bør vurdere om det holder."
    return "missing_info", "Ingen nøyaktighet, oppløsning eller kvalitetsklasse i metadata eller tekst.", 0.9, \
        "Be opplasteren om opplysninger om nøyaktighet."


def offline_review(payload: dict, texts: list[dict], rules: list[dict]) -> dict:
    """Produce a review in the same shape the AI returns."""
    md = payload.get("metadata") or {}
    file = payload.get("file") or {}
    dtype = file.get("data_type") or "other"
    found = _find(texts)
    checks = []
    for rule in rules:
        if rule["id"] == "R-QUA-01":
            given = (payload.get("uploader_values") or {}).get("quality")
            result, evidence, conf, comment = _quality(dtype, md, found, given)
            checks.append({"rule_id": rule["id"], "result": result, "evidence": evidence,
                           "confidence": conf, "comment": comment})
        else:
            checks.append({"rule_id": rule["id"], "result": "needs_review", "evidence": "",
                           "confidence": 0.0, "comment": "Offline-erstatningen kan ikke vurdere egne regler – krever AI."})

    label = DATA_TYPES.get(dtype, "Data")
    source = md.get("source") or found.get("source", {}).get("value")
    date = found.get("data_date", {}).get("value") or md.get("data_date")
    date = parse_date_text(date) or date
    first = f"{label} fra {source or 'ukjent kilde'}" + (f", datert {date}" if date else "") + "."
    content = payload.get("content") or {}
    if content.get("summary"):
        first = content["summary"]
    q = next((c for c in checks if c["rule_id"] == "R-QUA-01"), None)
    second = q["comment"] if q else ""
    coord = payload.get("coordinate_check") or ""
    if "kan være feil" in coord or "lokalt" in coord:
        second = coord
    suggested = dtype
    if any(re.search(r"geotekn|grunnunders", t.get("text", ""), re.I) for t in texts):
        suggested = "ground_investigation"
    return {"found_values": found, "checks": checks, "file_comment": f"{first} {second}".strip(),
            "suggested_data_type": suggested}


_TYPE_WORDS = [
    ("point_cloud", r"punktsk|laser|lidar"), ("terrain", r"terreng|dtm|høydemodell|hoydemodell"),
    ("orthophoto", r"ortofoto|flyfoto"), ("fkb", r"\bfkb"), ("utility", r"ledning|va-|kabel"),
    ("ground_investigation", r"grunnunders|geotekn|boring"), ("model", r"\bifc\b|eksisterende modell|bim-modell|fagmodell"),
    ("drawing", r"tegning|innmål|dwg|dxf"),
]


def offline_draft_rules(text: str, existing: list[dict]) -> list[dict]:
    """Turn sentences with 'skal', 'må', 'bør', 'shall' or 'must' into draft rules."""
    known = {re.sub(r"\W+", " ", r["text"].lower()).strip() for r in existing}
    heading = ""
    out = []
    for raw in re.split(r"(?<=[.!?])\s+|\n+", text):
        s = raw.strip(" -•\t")
        if not s:
            continue
        if re.match(r"^(\d+(\.\d+)*|[A-ZÆØÅ][A-ZÆØÅ ]{3,})\s", s) and not re.search(r"\b(skal|må|bør|shall|must|should)\b", s, re.I):
            heading = s[:80]
            continue
        if not re.search(r"\b(skal|må|bør|shall|must|should)\b", s, re.I) or len(s) < 15:
            continue
        if re.sub(r"\W+", " ", s.lower()).strip() in known:
            continue
        applies = [t for t, pat in _TYPE_WORDS if re.search(pat, s, re.I)] or ["all"]
        soft = re.search(r"\b(bør|should)\b", s, re.I)
        text_out = s.rstrip(".")
        out.append({"text": text_out[:1].upper() + text_out[1:], "source": f"Innlimt tekst{' – ' + heading if heading else ''}",
                    "applies_to": applies, "if_failed": "warning" if soft else "deviation",
                    "guidance": "Vurder om metadata, leveransenotater eller svar fra opplaster viser at kravet er oppfylt. "
                                "Står det ingenting om det, er resultatet missing_info."})
    return out[:15]
