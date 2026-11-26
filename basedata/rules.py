"""Rule sets and the code-based rule checks.

Every check returns a result, the evidence it looked at, and who checked it. Results, from best to
worst: ok, warning, missing_info, needs_review, deviation. A file's result is its worst result.
Rules with check "auto" run built-in code (BUILTIN); rules with check "ai" are judged by the AI from
their text and guidance, so new requirements can be added in plain language.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import yaml

from . import crs as crslib
from .extract.common import year_of
from .text import RESULT_LABELS, SOURCE_LABELS, area, metres, nb, pct

RESULT_ORDER = {"ok": 0, "warning": 1, "missing_info": 2, "needs_review": 3, "deviation": 4}
CHECK_KINDS = {"auto": "Automatisk", "ai": "AI", "manual": "Manuell"}
DOCUMENT_FORMATS = {"PDF"}
_DEFAULT = Path(__file__).resolve().parent / "data" / "default_rules_v1.yaml"

BUILTIN = {
    "R-CRS-01": {"label": "Sammenligner koordinatsystemet med prosjektets", "params": {}},
    "R-CRS-02": {"label": "Sammenligner høydesystemet med prosjektets", "params": {}},
    "R-CRS-03": {"label": "Sjekker at koordinatene havner i prosjektområdet", "params": {}},
    "R-EXT-01": {"label": "Beregner hvor stor del av prosjektområdet som dekkes", "params": {"min_coverage_pct": 95}},
    "R-SRC-01": {"label": "Ser etter kilde i fila, leveransenotater og svar", "params": {}},
    "R-DATE-01": {"label": "Sjekker datoen mot prosjektets aldersgrense", "params": {}},
    "R-FMT-01": {"label": "Sjekker filformatet mot prosjektets liste", "params": {}},
    "R-REF-01": {"label": "Sammenligner høyder med godkjent terrengmodell eller punktsky",
                 "params": {"max_mean_offset_m": 0.10, "max_std_m": 0.15, "change_threshold_m": 0.5,
                            "max_changed_area_m2": 500}},
}
PARAM_LABELS = {"min_coverage_pct": "Minste dekning (%)", "max_mean_offset_m": "Største systematiske avvik (m)",
                "max_std_m": "Største spredning, std (m)", "change_threshold_m": "Endring regnes fra (m)",
                "max_changed_area_m2": "Største endrede areal (m²)"}

__all__ = ["RESULT_LABELS", "RESULT_ORDER", "BUILTIN", "Check", "EvalInput", "run_code_checks", "worst"]


@dataclass
class Check:
    """The outcome of one rule for one file."""

    rule_id: str
    rule_text: str
    result: str
    evidence: str
    checked_by: str = "code"
    confidence: float | None = None
    comment: str = ""
    flagged_for_review: bool = False
    model: str | None = None
    prompt_version: str | None = None
    depends_on: str | None = None     # the register field this check depends on, for questions
    data: dict = field(default_factory=dict)
    override: dict | None = None      # a person's correction of the result: {result, original, comment, by, at}

    def to_dict(self) -> dict:
        """Plain dict for MongoDB."""
        return asdict(self)


@dataclass
class EvalInput:
    """Everything the code checks need about one file."""

    data_type: str
    ext: str
    md: dict
    eff: dict           # field -> {"value", "from", "file_value", "evidence", ...}
    project: dict
    plaus: dict
    coverage: float | None
    today: date
    comparison: dict | None = None


def load_default_ruleset() -> dict:
    """The example rule set shipped with the module (data/default_rules_v1.yaml)."""
    return yaml.safe_load(_DEFAULT.read_text(encoding="utf-8"))


def applies(rule: dict, data_type: str) -> bool:
    """Is this rule active, and does it apply to this data type?"""
    if rule.get("active", True) is False:
        return False
    targets = rule.get("applies_to") or ["all"]
    return "all" in targets or data_type in targets


def params(rule: dict) -> dict:
    """The rule's parameters, with built-in defaults filled in."""
    return {**BUILTIN.get(rule["id"], {}).get("params", {}), **(rule.get("params") or {})}


def worst(results: list[str]) -> str:
    """The worst of several results; 'ok' when there are none."""
    ranked = [r for r in results if r in RESULT_ORDER]
    return max(ranked, key=RESULT_ORDER.get) if ranked else "ok"


def _src(e: dict) -> str:
    return SOURCE_LABELS.get(e.get("from") or "", "")


def _ev(e: dict, text: str) -> str:
    extra = f" Belegg: «{e['evidence']}»" if e.get("from") == "ai_text" and e.get("evidence") else ""
    return text + extra


# --- The checks -----------------------------------------------------------------------------------

def check_crs_matches(rule: dict, inp: EvalInput) -> Check:
    e = inp.eff["horizontal_epsg"]
    project_epsg = crslib.parse_crs(inp.project.get("horizontal_crs"))
    mk = lambda result, ev: Check(rule["id"], rule["text"], result, ev, depends_on="horizontal_epsg")  # noqa: E731
    if e.get("from") == "uploader_unknown":
        return mk("deviation", "Ukjent – bekreftet av opplaster. KS-ansvarlig avgjør om fila kan brukes.")
    if e.get("from") == "uploader_local":
        return mk("deviation", "Opplaster oppgir lokale koordinater; dataene må transformeres til prosjektets koordinatsystem.")
    if e.get("value") is None:
        hint = f" {inp.plaus['note']}" if inp.plaus.get("candidates") else ""
        return mk("missing_info", "Ingen koordinatsystem i fila eller tilhørende filer, og ikke oppgitt av opplaster." + hint)
    if project_epsg is None:
        return mk("needs_review", "Prosjektets koordinatsystem er ikke satt i prosjektinnstillingene.")
    value = e["value"]
    if value == project_epsg:
        if e.get("from") == "uploader" and e.get("file_value") not in (None, value):
            return mk("warning", f"Opplaster bekrefter {crslib.crs_name(value)}, men fila oppgir "
                                 f"{crslib.crs_name(e['file_value'])} – be leverandøren rette fila.")
        return mk("ok", _ev(e, f"{crslib.crs_name(value)}, {_src(e)}."))
    return mk("deviation", _ev(e, f"{crslib.crs_name(value)} ({_src(e)}); prosjektet bruker {crslib.crs_name(project_epsg)}. "
                                  "Transformer før bruk, eller avtal unntak."))


def check_height(rule: dict, inp: EvalInput) -> Check:
    e = inp.eff["height_reference"]
    want = crslib.normalize_height(inp.project.get("height_reference"))
    mk = lambda result, ev: Check(rule["id"], rule["text"], result, ev, depends_on="height_reference")  # noqa: E731
    if e.get("from") == "uploader_unknown":
        return mk("deviation", "Ukjent – bekreftet av opplaster.")
    value = e.get("value")
    if value is None:
        return mk("missing_info", "Ingen høydesystem i fila, og ikke oppgitt av opplaster.")
    if value == "NONE":
        return mk("ok", "Opplaster oppgir at fila ikke har høyder (2D-data).")
    if want and value != want:
        return mk("deviation", _ev(e, f"Høyder i {value} ({_src(e)}); prosjektet bruker {want}."))
    return mk("ok", _ev(e, f"{value}, {_src(e)}."))


def check_plausible(rule: dict, inp: EvalInput) -> Check | None:
    p = inp.plaus
    mk = lambda result, ev: Check(rule["id"], rule["text"], result, ev, depends_on="horizontal_epsg",  # noqa: E731
                                  data={"candidates": p.get("candidates", [])})
    if not p.get("checked"):
        if inp.md.get("format") in DOCUMENT_FORMATS:
            return None  # reports have no coordinates to check
        return mk("needs_review", p.get("note") or "Ingen koordinater kunne leses.")
    if p.get("looks_local"):
        return mk("deviation", p["note"])
    if inp.eff["horizontal_epsg"].get("value") is None:
        return mk("missing_info", p["note"])
    if p.get("declared_fits"):
        return mk("ok", p["note"])
    return mk("deviation", p["note"])


def check_coverage(rule: dict, inp: EvalInput) -> Check:
    cov = inp.coverage
    need = float(params(rule).get("min_coverage_pct", 95)) / 100
    mk = lambda result, ev: Check(rule["id"], rule["text"], result, ev, depends_on="horizontal_epsg")  # noqa: E731
    if cov is None:
        if inp.eff["horizontal_epsg"].get("value") is None:
            return mk("missing_info", "Dekning er ukjent til koordinatsystemet er kjent.")
        if not (inp.project.get("project_area") or {}).get("coordinates"):
            return mk("needs_review", "Prosjektområdet er ikke satt i prosjektinnstillingene.")
        return mk("needs_review", "Dekning kunne ikke beregnes for dette koordinatsystemet.")
    if cov >= need:
        return mk("ok", f"Dekker {pct(cov)} av prosjektområdet.")
    if cov > 0:
        return mk(rule.get("if_failed", "warning"), f"Dekker bare {pct(cov)} av prosjektområdet (krav {pct(need)}).")
    return mk(rule.get("if_failed", "warning"), "Overlapper ikke prosjektområdet.")


def check_source(rule: dict, inp: EvalInput) -> Check:
    e = inp.eff["source"]
    mk = lambda result, ev: Check(rule["id"], rule["text"], result, ev, depends_on="source")  # noqa: E731
    if e.get("from") == "uploader_unknown":
        return mk("deviation", "Ukjent – bekreftet av opplaster.")
    if e.get("value"):
        return mk("ok", _ev(e, f"{e['value']} ({_src(e)})."))
    return mk("missing_info", "Ingen kilde eller leverandør i fila, i leveransenotater eller fra opplaster.")


def check_date(rule: dict, inp: EvalInput) -> Check:
    e = inp.eff["data_date"]
    limit = int(inp.project.get("max_data_age_years") or 0)
    mk = lambda result, ev: Check(rule["id"], rule["text"], result, ev, depends_on="data_date")  # noqa: E731
    if e.get("from") == "uploader_unknown":
        return mk("deviation", "Ukjent – bekreftet av opplaster.")
    value = e.get("value")
    if not value:
        raw = e.get("raw")
        if raw:
            return mk("needs_review", f"Opplaster skrev «{raw}», som ikke kunne leses som dato.")
        return mk("missing_info", "Ingen innsamlings- eller oppdateringsdato i fila, i leveransenotater eller fra opplaster.")
    kind = f"; {e['kind']}" if e.get("kind") and e.get("from") == "file" else ""
    year = year_of(value)
    if limit and year and inp.today.year - year > limit:
        return mk(rule.get("if_failed", "warning"),
                  _ev(e, f"Data fra {value} – eldre enn prosjektets grense på {limit} år ({_src(e)}{kind})."))
    return mk("ok", _ev(e, f"{value} ({_src(e)}{kind})."))


def check_format(rule: dict, inp: EvalInput) -> Check:
    accepted = [a.lower().lstrip(".") for a in inp.project.get("accepted_formats") or []]
    ext = inp.ext.lstrip(".")
    fmt = inp.md.get("format") or ext.upper()
    if not accepted:
        return Check(rule["id"], rule["text"], "needs_review", "Prosjektets godkjente filformater er ikke satt.")
    if ext in accepted:
        return Check(rule["id"], rule["text"], "ok", f"{fmt} (.{ext}) er på listen over godkjente formater.")
    return Check(rule["id"], rule["text"], "deviation", f".{ext} er ikke på prosjektets liste ({', '.join(accepted)}).")


def check_reference(rule: dict, inp: EvalInput) -> Check | None:
    c = inp.comparison
    if not c or c.get("status") in ("no_reference", "no_overlap", None):
        return None  # nothing approved to compare with yet; shown on the page instead
    p = params(rule)
    mk = lambda result, ev, dep=None: Check(rule["id"], rule["text"], result, ev, depends_on=dep)  # noqa: E731
    if c["status"] == "crs_unknown":
        return mk("missing_info", "Sammenligning med godkjent referanse venter på koordinatsystem.", "horizontal_epsg")
    if c["status"] != "done":
        return mk("needs_review", c.get("note") or "Høydene i fila kunne ikke leses, så den er ikke sammenlignet.")
    ref = c["reference"]
    label = f"#{ref['entry_seq']} {ref['file_name']}"
    mean, std, sh = c["mean_m"], c["std_m"], c["shift"]
    thr = float(p["change_threshold_m"])
    keys = sorted((float(k) for k in c["area_over_m2"]), key=lambda k: abs(k - thr))
    changed = c["area_over_m2"][str(keys[0])] if keys else 0.0
    if sh.get("suspected"):
        return mk("deviation", f"Mulig horisontal forskyvning på ca. {metres(sh['distance_m'], 1)} mot {sh['direction']} "
                               f"sammenlignet med {label}: spredningen faller fra {metres(sh['std_before_m'])} til "
                               f"{metres(sh['std_after_m'])} når dataene flyttes.")
    if abs(mean) > float(p["max_mean_offset_m"]):
        return mk("deviation", f"Systematisk høydeavvik {metres(mean, signed=True)} mot {label} "
                               f"(std {metres(std)}, grense ±{metres(float(p['max_mean_offset_m']))}).")
    if changed > float(p["max_changed_area_m2"]):
        return mk("warning", f"Lokale endringer mot {label}: ca. {area(changed)} avviker mer enn {metres(keys[0], 2)} "
                             f"(størst {metres(c['max_m'], signed=True)}). Kontroller om endringene er reelle, for eksempel nytt anlegg.")
    if std > float(p["max_std_m"]):
        return mk("warning", f"Stor spredning mot {label}: std {metres(std)} (grense {metres(float(p['max_std_m']))}).")
    return mk("ok", f"Stemmer med {label}: middelavvik {metres(mean, signed=True)}, std {metres(std)}, "
                    f"95 % innenfor ±{metres(c['p95_abs_m'])} ({nb(c['cells'], 0)} celler à {nb(c['cell_m'], 1)} m).")


CODE_CHECKS: dict[str, Callable[[dict, EvalInput], Check | None]] = {
    "R-CRS-01": check_crs_matches,
    "R-CRS-02": check_height,
    "R-CRS-03": check_plausible,
    "R-EXT-01": check_coverage,
    "R-SRC-01": check_source,
    "R-DATE-01": check_date,
    "R-FMT-01": check_format,
    "R-REF-01": check_reference,
}


def run_code_checks(rules: list[dict], inp: EvalInput) -> list[Check]:
    """Run every applicable 'auto' and 'manual' rule. AI rules are handled by the AI step."""
    out: list[Check] = []
    for rule in rules:
        kind = rule.get("check", "auto")
        if kind == "manual":
            out.append(Check(rule["id"], rule["text"], "needs_review", "Kontrolleres av KS-ansvarlig.", checked_by="manuell"))
            continue
        if kind != "auto":
            continue
        fn = CODE_CHECKS.get(rule["id"])
        if fn is None:
            out.append(Check(rule["id"], rule["text"], "needs_review",
                             "Ingen innebygd sjekk finnes for denne regelen – velg AI eller manuell kontroll i regelsettet."))
            continue
        result = fn(rule, inp)
        if result is not None:
            out.append(result)
    return out
