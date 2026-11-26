"""The AI step: reads delivery text, judges the 'ai' rules, writes a comment, and drafts new rules.

Providers are called over plain HTTPS (no SDK needed):
- "anthropic":    Claude via the Messages API, forced tool use for structured output
- "azure_openai": an Azure OpenAI deployment, JSON mode
- "offline_demo": a rule-based stand-in for demos and tests — NOT an AI model, and labelled as such
Everything the AI returns is validated: values whose evidence is not found in the text are dropped,
results without evidence become needs_review, and low confidence flags the check for the reviewer.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..classify import DATA_TYPES
from ..settings import Settings

PROMPT_VERSION = "check_v1"
_PROMPTS = Path(__file__).resolve().parent / "prompts"
VALUE_FIELDS = ["source", "data_date", "horizontal_crs", "height_reference", "quality"]
RESULTS = ["ok", "warning", "missing_info", "needs_review", "deviation"]
OFFLINE_MODEL = "offline-demo (regelbasert erstatning, ikke en AI-modell)"

SCHEMA = {
    "type": "object",
    "properties": {
        "found_values": {
            "type": "object",
            "properties": {f: {"type": "object", "properties": {"value": {"type": ["string", "null"]},
                                                                "evidence": {"type": "string"}},
                               "required": ["value", "evidence"]} for f in VALUE_FIELDS},
        },
        "checks": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"rule_id": {"type": "string"}, "result": {"type": "string", "enum": RESULTS},
                                     "evidence": {"type": "string"}, "confidence": {"type": "number"},
                                     "comment": {"type": "string"}},
                      "required": ["rule_id", "result", "evidence", "confidence", "comment"]},
        },
        "file_comment": {"type": "string"},
        "suggested_data_type": {"type": "string", "enum": list(DATA_TYPES)},
    },
    "required": ["found_values", "checks", "file_comment", "suggested_data_type"],
}

RULES_SCHEMA = {
    "type": "object",
    "properties": {"rules": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "source": {"type": "string"},
                       "applies_to": {"type": "array", "items": {"type": "string", "enum": ["all", *DATA_TYPES]}},
                       "if_failed": {"type": "string", "enum": ["deviation", "warning", "missing_info"]},
                       "guidance": {"type": "string"}},
        "required": ["text", "source", "applies_to", "if_failed", "guidance"]}}},
    "required": ["rules"],
}


@dataclass
class AIReview:
    """The validated outcome of the AI step for one file."""

    status: str                      # done, skipped or error
    model: str = ""
    prompt_version: str = PROMPT_VERSION
    found_values: dict = field(default_factory=dict)   # field -> {"value", "evidence"}
    checks: list[dict] = field(default_factory=list)
    file_comment: str = ""
    suggested_data_type: str | None = None
    dropped: list[str] = field(default_factory=list)   # values rejected by validation
    error: str = ""


def system_prompt(name: str = PROMPT_VERSION) -> str:
    """A system prompt, kept in an editable Markdown file."""
    return (_PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def _post(url: str, headers: dict, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def ask_ai(settings: Settings, system: str, content: str, schema: dict, tool: str = "report_review") -> dict:
    """Send one request to the configured provider and return the JSON object it produced."""
    provider = settings.ai_provider
    if provider == "anthropic":
        body = {"model": settings.ai_model, "max_tokens": 4000, "system": system,
                "messages": [{"role": "user", "content": content}],
                "tools": [{"name": tool, "description": "Report the result in the required structure.",
                           "input_schema": schema}],
                "tool_choice": {"type": "tool", "name": tool}}
        headers = {"x-api-key": settings.ai_api_key, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        resp = _post("https://api.anthropic.com/v1/messages", headers, body, settings.ai_timeout_s)
        for block in resp.get("content", []):
            if block.get("type") == "tool_use":
                return block.get("input") or {}
        raise RuntimeError("Modellen returnerte ikke strukturert svar.")
    if provider == "azure_openai":
        url = (f"{settings.azure_endpoint.rstrip('/')}/openai/deployments/{settings.ai_model}"
               f"/chat/completions?api-version={settings.azure_api_version}")
        body = {"messages": [{"role": "system", "content": system + "\n\nReply with only a JSON object that "
                              "matches this JSON Schema:\n" + json.dumps(schema)},
                             {"role": "user", "content": content}],
                "response_format": {"type": "json_object"}}
        resp = _post(url, {"api-key": settings.ai_api_key, "content-type": "application/json"}, body,
                     settings.ai_timeout_s)
        return json.loads(resp["choices"][0]["message"]["content"])
    raise RuntimeError(f"Ukjent AI-leverandør {provider!r}.")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def validate(raw: dict, texts: list[dict], rule_ids: list[str], settings: Settings) -> AIReview:
    """Check the AI's answer against the input; drop anything not backed by evidence."""
    review = AIReview(status="done")
    corpus = _norm("\n".join(t.get("text", "") for t in texts))
    for name, item in (raw.get("found_values") or {}).items():
        if name not in VALUE_FIELDS or not isinstance(item, dict) or not item.get("value"):
            continue
        evidence = str(item.get("evidence") or "")
        if evidence and _norm(evidence) in corpus:
            review.found_values[name] = {"value": str(item["value"]), "evidence": evidence.strip()}
        else:
            review.dropped.append(f"{name}: «{item.get('value')}» (fant ikke belegg i teksten)")
    for c in raw.get("checks") or []:
        if c.get("rule_id") not in rule_ids:
            continue
        result = c.get("result") if c.get("result") in RESULTS else "needs_review"
        evidence = str(c.get("evidence") or "").strip()
        if not evidence:
            result = "needs_review"
        try:
            conf = max(0.0, min(1.0, float(c.get("confidence", 0))))
        except (TypeError, ValueError):
            conf = 0.0
        review.checks.append({"rule_id": c["rule_id"], "result": result, "evidence": evidence or "Ingen belegg oppgitt.",
                              "confidence": round(conf, 2), "comment": str(c.get("comment") or ""),
                              "flagged_for_review": conf < settings.review_below_confidence})
    review.file_comment = str(raw.get("file_comment") or "")[:600]
    sdt = raw.get("suggested_data_type")
    review.suggested_data_type = sdt if sdt in DATA_TYPES else None
    return review


def review_file(settings: Settings, payload: dict, texts: list[dict], rules: list[dict]) -> AIReview:
    """Run the AI step for one file. Never raises: errors come back as status 'error'."""
    rule_ids = [r["id"] for r in rules]
    if not settings.ai_enabled:
        return AIReview(status="skipped", error="AI er ikke satt opp (BASEDATA_AI_PROVIDER, _MODEL, _API_KEY).")
    try:
        if settings.ai_provider == "offline_demo":
            from .offline import offline_review

            raw = offline_review(payload, texts, rules)
            model = OFFLINE_MODEL
        else:
            content = json.dumps({**payload, "texts": texts,
                                  "rules_to_judge": [{"id": r["id"], "text": r["text"], "guidance": r.get("guidance", "")}
                                                     for r in rules]}, ensure_ascii=False, default=str)
            raw = ask_ai(settings, system_prompt(), content, SCHEMA)
            model = f"{settings.ai_provider}:{settings.ai_model}"
        review = validate(raw, texts, rule_ids, settings)
        review.model = model
        return review
    except Exception as exc:  # network, provider or parsing problems must not stop the run
        return AIReview(status="error", error=f"{type(exc).__name__}: {exc}"[:400])


def draft_rules(settings: Settings, text: str, existing: list[dict]) -> dict:
    """Draft new rules from pasted requirement text. Returns {rules: [...], model, note}."""
    text = (text or "").strip()
    if len(text) < 20:
        raise ValueError("Lim inn litt mer tekst – minst én hel setning med et krav.")
    if not settings.ai_enabled:
        raise ValueError("AI er ikke satt opp, så regler kan ikke foreslås automatisk. Skriv regelen selv.")
    if settings.ai_provider == "offline_demo":
        from .offline import offline_draft_rules

        drafts, model = offline_draft_rules(text, existing), OFFLINE_MODEL
    else:
        content = json.dumps({"requirement_text": text[:20000],
                              "existing_rules": [{"id": r["id"], "text": r["text"]} for r in existing],
                              "data_types": DATA_TYPES}, ensure_ascii=False)
        drafts = ask_ai(settings, system_prompt("rules_v1"), content, RULES_SCHEMA, tool="report_rules").get("rules", [])
        model = f"{settings.ai_provider}:{settings.ai_model}"
    taken = {r["id"] for r in existing}
    out, n = [], 1
    for d in drafts:
        if not d.get("text"):
            continue
        while f"R-AI-{n:02d}" in taken:
            n += 1
        rid = f"R-AI-{n:02d}"
        taken.add(rid)
        applies = [a for a in d.get("applies_to") or ["all"] if a == "all" or a in DATA_TYPES] or ["all"]
        out.append({"id": rid, "text": str(d["text"])[:300], "source": str(d.get("source") or "Innlimt tekst")[:200],
                    "applies_to": applies, "check": "ai",
                    "if_failed": d.get("if_failed") if d.get("if_failed") in ("deviation", "warning", "missing_info") else "deviation",
                    "guidance": str(d.get("guidance") or "")[:800], "active": True})
    return {"rules": out, "model": model}
