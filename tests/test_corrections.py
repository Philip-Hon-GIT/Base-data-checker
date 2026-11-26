"""People can correct values the file or the AI got wrong, override rule results, and comment."""

import io

import pytest
from openpyxl import load_workbook

from basedata import db as dblib
from basedata import service
from basedata.demo import REVIEWER, USERS
from basedata.export_excel import export_project
from basedata.worker import run_once

KARI, OLA = USERS[1], USERS[2]


def _entry(ctx, seq):
    return ctx.db[dblib.ENTRIES].find_one({"seq": seq})


def _files(ctx, seq):
    return list(ctx.db[dblib.FILES].find({"entry_id": _entry(ctx, seq)["_id"]}))


def _check(ctx, seq, rule):
    f = _files(ctx, seq)[0]
    return ctx.db[dblib.CHECKS].find_one({"file_id": f["_id"], "run_id": f["last_run_id"], "rule_id": rule})


def test_correct_ai_value_and_reset(demo_ctx):
    eid = _entry(demo_ctx, 7)["_id"]
    assert all(f["effective"]["source"]["from"] == "ai_text" for f in _files(demo_ctx, 7))
    service.correct_value(demo_ctx, REVIEWER, eid, "source", "Nordby Oppmåling AS", "Notatet er feil")
    for f in _files(demo_ctx, 7):  # every file in the package
        s = f["effective"]["source"]
        assert s["value"] == "Nordby Oppmåling AS" and s["from"] == "manual" and s["was"] == "Demo Survey AS"
        assert s["corrected"]["comment"] == "Notatet er feil" and s["corrected"]["by_name"] == REVIEWER["name"]
    assert _entry(demo_ctx, 7)["corrected_fields"] == ["source"]
    assert "Kilde korrigert" in _entry(demo_ctx, 7)["history"][-1]["event"]
    run_once(demo_ctx, force=True)  # a re-run keeps the correction
    assert _files(demo_ctx, 7)[0]["effective"]["source"]["value"] == "Nordby Oppmåling AS"
    service.correct_value(demo_ctx, REVIEWER, eid, "source", "", "")
    assert _files(demo_ctx, 7)[0]["effective"]["source"]["from"] == "ai_text" and _entry(demo_ctx, 7)["corrected_fields"] == []


def test_correction_wins_over_the_file_and_closes_the_question(demo_ctx):
    eid = _entry(demo_ctx, 5)["_id"]
    service.correct_value(demo_ctx, KARI, eid, "horizontal_epsg", "EPSG:25832", "Feil .prj fra leverandør")
    e = _files(demo_ctx, 5)[0]["effective"]["horizontal_epsg"]
    assert e["value"] == 25832 and e["from"] == "manual" and e["was"] == 25833
    assert _check(demo_ctx, 5, "R-CRS-01")["result"] == "ok"
    assert not demo_ctx.db[dblib.QUESTIONS].find_one({"entry_id": eid, "field": "horizontal_epsg", "status": "open"})


def test_correct_permissions_and_validation(demo_ctx):
    eid = _entry(demo_ctx, 9)["_id"]  # Ola's delivery
    with pytest.raises(PermissionError):
        service.correct_value(demo_ctx, KARI, eid, "source", "x")
    with pytest.raises(ValueError):
        service.correct_value(demo_ctx, OLA, eid, "data_date", "en gang i fjor")
    with pytest.raises(ValueError):
        service.correct_value(demo_ctx, OLA, eid, "file_name", "x")
    service.correct_value(demo_ctx, OLA, eid, "data_type", "Punktsky")
    assert _entry(demo_ctx, 9)["data_type"] == "point_cloud"


def test_text_corrections(demo_ctx):
    eid = _entry(demo_ctx, 12)["_id"]
    service.correct_value(demo_ctx, OLA, eid, "summary", "Plan- og profiltegning for hele strekningen.", "Mer presist")
    service.correct_value(demo_ctx, OLA, eid, "content", "Tegning C101 rev. B")
    d = service.entry_detail(demo_ctx, REVIEWER, eid)
    assert d["profile"]["summary"] == "Plan- og profiltegning for hele strekningen."
    assert d["profile"]["summary_original"].startswith("Tegning C101") and d["entry"]["content"] == "Tegning C101 rev. B"
    assert d["entry"]["corrections"] == 2


def test_override_rule_result(demo_ctx):
    eid = _entry(demo_ctx, 5)["_id"]
    with pytest.raises(PermissionError):
        service.override_check(demo_ctx, KARI, eid, "R-QUA-01", "ok", "fint")
    with pytest.raises(ValueError):
        service.override_check(demo_ctx, REVIEWER, eid, "R-QUA-01", "ok", "")  # needs a reason
    service.override_check(demo_ctx, REVIEWER, eid, "R-QUA-01", "ok", "0,5 m holder i denne fasen")
    c = _check(demo_ctx, 5, "R-QUA-01")
    assert c["result"] == "ok" and c["override"]["original"] == "warning" and c["override"]["by"] == REVIEWER["name"]
    assert "R-QUA-01" not in _entry(demo_ctx, 5)["deviations"]
    run_once(demo_ctx, force=True)
    assert _check(demo_ctx, 5, "R-QUA-01")["result"] == "ok"
    service.override_check(demo_ctx, REVIEWER, eid, "R-QUA-01", None)
    assert _check(demo_ctx, 5, "R-QUA-01")["result"] == "warning"


def test_comments_and_export(demo_ctx):
    eid = _entry(demo_ctx, 12)["_id"]
    with pytest.raises(ValueError):
        service.add_comment(demo_ctx, KARI, eid, "  ")
    service.add_comment(demo_ctx, KARI, eid, "Er dette siste revisjon?")
    assert [c["text"] for c in _entry(demo_ctx, 12)["comments"]] == ["Er dette siste revisjon?"]
    assert demo_ctx.db[dblib.NOTIFICATIONS].find_one({"to": OLA["email"], "kind": "comment"})
    assert service.list_entries(demo_ctx, REVIEWER, "rv999-nordby")[11]["comments"] == 1
    service.override_check(demo_ctx, REVIEWER, _entry(demo_ctx, 5)["_id"], "R-QUA-01", "ok", "holder")
    wb = load_workbook(io.BytesIO(export_project(demo_ctx.db, "rv999-nordby")))
    reg = wb["Register"]
    head = [c.value for c in reg[1]]
    assert head[-2:] == ["Manuelle korreksjoner", "Kommentarer"]
    assert "Kari Nordmann: Er dette siste revisjon?" in reg.cell(row=13, column=len(head)).value
    assert "R-QUA-01 → OK" in reg.cell(row=6, column=len(head) - 1).value
