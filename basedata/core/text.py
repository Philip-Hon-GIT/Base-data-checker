"""Norwegian labels and number formatting shared by the checker, the web pages and the Excel export."""

from __future__ import annotations

RESULT_LABELS = {"ok": "OK", "warning": "Advarsel", "missing_info": "Mangler info", "needs_review": "Må vurderes",
                 "deviation": "Avvik", "pending": "Venter"}
QA_STATUS = {"ikke_begynt": "Ikke begynt", "pagar": "Pågår", "utfort": "Utført"}
READY = {"ja": "Ja", "med_forbehold": "Med forbehold", "nei": "Nei"}
LIFECYCLE = {"gjeldende": "Gjeldende", "utgatt": "Utgått"}
SOURCE_LABELS = {"file": "fra fila", "uploader": "oppgitt av opplaster", "ai_text": "lest fra tekst av AI",
                 "uploader_unknown": "opplaster vet ikke", "uploader_local": "opplaster: lokale koordinater"}


def nb(x: float, decimals: int = 2, signed: bool = False) -> str:
    """Norwegian number: decimal comma, narrow space between thousands, a real minus sign."""
    if round(x, decimals) == 0:
        x, signed = 0.0, False
    s = f"{x:+,.{decimals}f}" if signed else f"{x:,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",").replace("-", "−")


def metres(x: float, decimals: int = 2, signed: bool = False) -> str:
    """A length in metres, Norwegian style: '+0,32 m'."""
    return f"{nb(x, decimals, signed)} m"


def area(m2: float) -> str:
    """An area in m² or dekar (1 daa = 1000 m²)."""
    return f"{nb(m2 / 1000, 1)} daa" if m2 >= 1000 else f"{nb(m2, 0)} m²"


def pct(share: float, decimals: int = 0) -> str:
    """A share 0–1 as a Norwegian percentage."""
    return f"{nb(share * 100, decimals)} %"
