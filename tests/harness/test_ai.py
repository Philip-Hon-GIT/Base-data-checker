import json

from basedata.harness import ai
from basedata.core.settings import Settings

TEXTS = [{"name": "note.txt", "text": "Levert av: Demo Survey AS\nSkannet: 12.05.2024"}]
RULES = [{"id": "R-QUA-01", "text": "Accuracy adequate", "check": "ai"}]


def test_validate_drops_values_without_evidence():
    raw = {"found_values": {"source": {"value": "Demo Survey AS", "evidence": "Levert av: Demo Survey AS"},
                            "data_date": {"value": "2023-01-01", "evidence": "captured in 2023"}},
           "checks": [{"rule_id": "R-QUA-01", "result": "ok", "evidence": "", "confidence": 0.9, "comment": "x"}],
           "file_comment": "c", "suggested_data_type": "point_cloud"}
    r = ai.validate(raw, TEXTS, ["R-QUA-01"], Settings())
    assert set(r.found_values) == {"source"}
    assert r.dropped and "data_date" in r.dropped[0]
    assert r.checks[0]["result"] == "needs_review"  # no evidence


def test_low_confidence_is_flagged():
    raw = {"found_values": {}, "checks": [{"rule_id": "R-QUA-01", "result": "ok", "evidence": "pixel 0.25",
                                           "confidence": 0.4, "comment": ""}],
           "file_comment": "", "suggested_data_type": "orthophoto"}
    r = ai.validate(raw, [], ["R-QUA-01"], Settings())
    assert r.checks[0]["flagged_for_review"] is True


def test_not_configured_is_skipped():
    assert ai.review_file(Settings(), {}, [], RULES).status == "skipped"


def test_anthropic_request_shape(monkeypatch):
    seen = {}

    def fake_post(url, headers, body, timeout):
        seen.update(url=url, headers=headers, body=body)
        return {"content": [{"type": "tool_use", "name": "report_review",
                             "input": {"found_values": {}, "checks": [], "file_comment": "ok", "suggested_data_type": "other"}}]}

    monkeypatch.setattr(ai, "_post", fake_post)
    s = Settings(ai_provider="anthropic", ai_model="claude-sonnet-5-5", ai_api_key="k")
    r = ai.review_file(s, {"file": {"name": "a"}}, TEXTS, RULES)
    assert r.status == "done" and r.file_comment == "ok"
    assert seen["url"].endswith("/v1/messages") and seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "report_review"}
    sent = json.loads(seen["body"]["messages"][0]["content"])
    assert sent["texts"] == TEXTS and sent["rules_to_judge"][0]["id"] == "R-QUA-01"


def test_provider_errors_do_not_raise(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("HTTP 500: overloaded")

    monkeypatch.setattr(ai, "_post", boom)
    s = Settings(ai_provider="azure_openai", ai_model="gpt", ai_api_key="k", azure_endpoint="https://x")
    r = ai.review_file(s, {}, [], RULES)
    assert r.status == "error" and "overloaded" in r.error


def test_offline_rule_drafts():
    text = ("3.2 Terrengmodell\nTerrengmodell skal leveres som rutenett med maksimalt 1 m oppløsning. "
            "Punktskyer skal være klassifisert etter ASPRS-standard. Ortofoto bør ikke være eldre enn 3 år. "
            "IFC-modeller skal ha georeferanse. Kilde og leverandør er dokumentert.")
    existing = [{"id": "R-AI-01", "text": "Punktskyer skal være klassifisert etter ASPRS-standard"}]  # already a rule
    out = ai.draft_rules(Settings(ai_provider="offline_demo"), text, existing)
    assert [r["id"] for r in out["rules"]] == ["R-AI-02", "R-AI-03", "R-AI-04"]  # no «skal» in the last sentence
    dtm, orto, ifc = out["rules"]
    assert dtm["applies_to"] == ["terrain"] and dtm["source"] == "Innlimt tekst – 3.2 Terrengmodell"
    assert dtm["if_failed"] == "deviation" and ifc["applies_to"] == ["model"]
    assert orto["applies_to"] == ["orthophoto"] and orto["if_failed"] == "warning"  # «bør» is a soft requirement
    assert all(r["check"] == "ai" and r["guidance"] for r in out["rules"])


def test_rule_drafts_need_ai_and_text():
    import pytest

    with pytest.raises(ValueError):
        ai.draft_rules(Settings(), "Terrengmodell skal leveres som rutenett.", [])
    with pytest.raises(ValueError):
        ai.draft_rules(Settings(ai_provider="offline_demo"), "for kort", [])
