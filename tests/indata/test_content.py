"""Content profiles, relations between registrations, and the chat tools."""

import pytest

from basedata.harness import chat
from basedata.core import db as dblib
from basedata.ui import service
from basedata.indata.content import entry_profile
from basedata.selfcheck.demo import REVIEWER
from basedata.harness.relations import for_entry

PID = "rv999-nordby"


def _entry(ctx, seq):
    return ctx.db[dblib.ENTRIES].find_one({"seq": seq})


def _files(ctx, e):
    return list(ctx.db[dblib.FILES].find({"entry_id": e["_id"]}))


def test_every_type_gets_the_same_profile_shape(demo_ctx):
    kinds = {}
    for e in demo_ctx.db[dblib.ENTRIES].find({}):
        p = entry_profile(e, _files(demo_ctx, e))
        assert set(p) >= {"kind", "label", "summary", "facts", "keywords", "mentions", "georef"}
        assert p["summary"] and all(len(f) == 2 for f in p["facts"])
        kinds[e["seq"]] = p["kind"]
    assert kinds[8] == "drawing_cad" and kinds[11] == "report" and kinds[12] == "drawing_pdf" and kinds[13] == "model"
    assert kinds[7] == "point_cloud" and kinds[2] == "terrain" and kinds[10] == "network"


def test_pdf_drawing_and_report_are_told_apart(demo_ctx):
    drawing, report = _entry(demo_ctx, 12), _entry(demo_ctx, 11)
    assert drawing["data_type"] == "drawing" and report["data_type"] == "ground_investigation"
    assert drawing["content_auto"] == "Tegning C101 · Plan og profil · 1:1000 · rev. B"
    p = entry_profile(drawing, _files(demo_ctx, drawing))
    assert dict(p["facts"])["Målestokk"] == "1:1000" and "Georeferert" in p["summary"]


def test_relations(demo_ctx):
    groups = {g["type"]: [x["seq"] for x in g["entries"]] for g in for_entry(demo_ctx.db, _entry(demo_ctx, 12))}
    assert groups["omtaler"] == [2, 3, 7]          # named in the title block
    assert groups["omtalt_i"] == [11]              # the report refers to drawing C101
    assert groups["samme_leveranse"] == [13]
    assert 2 in groups["samme_omrade"] and 4 not in groups["samme_omrade"]  # #4 is in UTM33
    g9 = {g["type"]: [x["seq"] for x in g["entries"]] for g in for_entry(demo_ctx.db, _entry(demo_ctx, 9))}
    assert g9["ny_versjon"] == [2]
    service.decide(demo_ctx, REVIEWER, _entry(demo_ctx, 2)["_id"], "ja", "Referanse")
    g7 = {g["type"]: [x["seq"] for x in g["entries"]] for g in for_entry(demo_ctx.db, _entry(demo_ctx, 7))}
    assert g7["sammenlignet_med"] == [2]


def test_entry_detail_has_profile_and_relations(demo_ctx):
    d = service.entry_detail(demo_ctx, REVIEWER, _entry(demo_ctx, 13)["_id"])
    assert d["profile"]["kind"] == "model" and d["relations"]
    assert d["files"][0]["content"]["label"] == "BIM-modell"


def test_chat_tools(demo_ctx):
    data = chat.Data(demo_ctx.db, PID, demo_ctx.now())
    miss = chat.run_tool(data, "search_entries", {"missing": "koordinatsystem"})
    assert [r["nr"] for r in miss["registreringer"]] == [8, 9]
    old = chat.run_tool(data, "search_entries", {"older_than_years": 10})
    assert [r["nr"] for r in old["registreringer"]] == [5]
    hits = chat.run_tool(data, "search_text", {"query": "kvikkleire"})
    assert hits["treff"][0]["nr"] == 11
    e = chat.run_tool(data, "get_entry", {"nr": 5})
    assert e["automatisk_kontroll"] == "Avvik" and {m["regel"] for m in e["merknader"]} >= {"R-CRS-01", "R-DATE-01"}
    assert chat.run_tool(data, "get_entry", {"nr": 99}) == {"feil": "Fant ikke registrering #99."}
    assert chat.run_tool(data, "project_overview", {})["registreringer"] == 13


@pytest.mark.parametrize("question, expect", [
    ("Hva er relatert til #12?", ["Omtaler", "#2", "#11"]),
    ("Hvilke registreringer har avvik?", ["#4", "#5", "#7"]),
    ("Oppsummer status", ["13 registreringer"]),
    ("Hvor står det om kvikkleire?", ["#11"]),
    ("Fortell om #7", ["blokk5", "+0,32"]),
])
def test_offline_chat(demo_ctx, question, expect):
    from basedata.selfcheck.demo import script_history
    script_history(demo_ctx)
    res = service.ask(demo_ctx, REVIEWER, PID, [{"role": "user", "content": question}])
    assert all(x in res["answer"] for x in expect), res["answer"]
    assert res["model"] == chat.OFFLINE_MODEL


def test_anthropic_chat_loop(demo_ctx, monkeypatch):
    from basedata.harness import ai
    calls = []

    def fake_post(url, headers, body, timeout):
        calls.append(body)
        if len(calls) == 1:
            return {"content": [{"type": "tool_use", "id": "t1", "name": "search_entries", "input": {"data_type": "model"}}]}
        result = body["messages"][-1]["content"][0]
        assert result["type"] == "tool_result" and "VA_modell_Nordby.ifc" in result["content"]
        return {"content": [{"type": "text", "text": "Det finnes én modell: #13 VA_modell_Nordby.ifc."}]}

    monkeypatch.setattr(ai, "_post", fake_post)
    demo_ctx.settings.ai_provider, demo_ctx.settings.ai_model, demo_ctx.settings.ai_api_key = "anthropic", "claude-x", "k"
    res = service.ask(demo_ctx, REVIEWER, PID, [{"role": "user", "content": "Hvilke modeller finnes?"}])
    assert res["answer"].startswith("Det finnes én modell") and res["tools"] == ["search_entries"]
    assert calls[0]["tools"][0]["name"] == "search_entries" and "#nummer" in calls[0]["system"]


def test_chat_needs_ai_and_a_question(demo_ctx):
    with pytest.raises(ValueError):
        service.ask(demo_ctx, REVIEWER, PID, [])
    demo_ctx.settings.ai_provider = ""
    with pytest.raises(ValueError):
        service.ask(demo_ctx, REVIEWER, PID, [{"role": "user", "content": "Hei"}])
