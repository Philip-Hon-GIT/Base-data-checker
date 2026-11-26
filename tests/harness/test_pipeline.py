"""Golden tests: the whole pipeline on the synthetic deliveries — register rows, packages, reference
comparisons, superseded versions, answers, KS decisions, project settings, rule sets and export."""

import io

import pytest
from openpyxl import load_workbook

from basedata.core import db as dblib
from basedata.ui import service
from basedata.selfcheck.demo import REVIEWER, USERS
from basedata.ui.export_excel import export_project
from basedata.harness.questions import AnswerError
from basedata.harness.worker import run_once

KARI, OLA = USERS[1], USERS[2]
PID = "rv999-nordby"

# seq: (name, kind, files, result, deviations, open questions, discipline)
EXPECTED = {
    1: ("FKB_Bygning_2025.sos", "file", 1, "ok", [], 0, "VEG"),
    2: ("Terrengmodell_DTM2_2021.tif", "file", 1, "ok", [], 0, "VEG"),
    3: ("FKB_Bygning_2026.sos", "file", 1, "ok", [], 0, "VEG"),
    4: ("FKB_Veg_2026.sos", "file", 1, "deviation", ["R-CRS-01"], 0, "VEG"),
    5: ("Ortofoto_2009.tif", "file", 1, "deviation", ["R-CRS-01", "R-CRS-03", "R-DATE-01", "R-QUA-01", "R-SRC-01"], 3, "VEG"),
    6: ("Ortofoto_2023_tile_0603.tif", "file", 1, "ok", [], 0, "VEG"),
    7: ("Laserdata_Nordby_2026", "package", 6, "ok", [], 0, "VEG"),
    8: ("Innmaaling_kummer.dxf", "file", 1, "missing_info",
        ["R-CRS-01", "R-CRS-02", "R-CRS-03", "R-DATE-01", "R-QUA-01", "R-SRC-01"], 5, "VA"),
    9: ("Terrengmodell_DTM2_2026.tif", "file", 1, "missing_info",
        ["R-CRS-01", "R-CRS-02", "R-CRS-03", "R-EXT-01", "R-REF-01", "R-SRC-01"], 4, "VEG"),
    10: ("Ledninger_VA.gpkg", "file", 1, "missing_info", ["R-DATE-01", "R-QUA-01", "R-SRC-01"], 4, "VA"),
    11: ("Grunnundersokelse_datarapport.pdf", "file", 1, "ok", [], 0, "GEO"),
    12: ("C101_Plan_og_profil.pdf", "file", 1, "ok", [], 0, "VEG"),
    13: ("VA_modell_Nordby.ifc", "file", 1, "ok", [], 0, "VA"),
}


def _entry(ctx, seq):
    return ctx.db[dblib.ENTRIES].find_one({"seq": seq})


def _file(ctx, name):
    return ctx.db[dblib.FILES].find_one({"file_name": name})


def _check(ctx, name, rule):
    f = _file(ctx, name)
    return ctx.db[dblib.CHECKS].find_one({"file_id": f["_id"], "run_id": f["last_run_id"], "rule_id": rule})


def _question(ctx, seq, field):
    return ctx.db[dblib.QUESTIONS].find_one({"entry_id": _entry(ctx, seq)["_id"], "field": field, "status": "open"})


def _laser(ctx):
    return sorted(ctx.db[dblib.FILES].find({"entry_id": _entry(ctx, 7)["_id"]}), key=lambda f: f["file_name"])


# --- Register --------------------------------------------------------------------------------------------

def test_golden_register(demo_ctx):
    got = {e["seq"]: (e["name"], e["kind"], e["file_count"], e["check_result"], e["deviations"], e["open_questions"],
                      e["discipline"]) for e in demo_ctx.db[dblib.ENTRIES].find({})}
    assert got == EXPECTED


def test_register_is_chronological(demo_ctx):
    rows = service.list_entries(demo_ctx, REVIEWER, PID)
    assert [r["seq"] for r in rows] == list(range(1, 14))
    assert rows == sorted(rows, key=lambda r: r["received_at"])
    assert rows[6]["content"].startswith("6 filer · Punktsky · 300\u202f000 punkter")
    assert rows[6]["file_types"] == "LAS 1.4 (6)" and rows[0]["link"] == f"#entry-{rows[0]['id']}"


def test_package_checks_every_file(demo_ctx):
    files = _laser(demo_ctx)
    assert len(files) == 6 and {f["entry_id"] for f in files} == {_entry(demo_ctx, 7)["_id"]}
    for f in files:
        rules = {c["rule_id"] for c in demo_ctx.db[dblib.CHECKS].find({"file_id": f["_id"], "run_id": f["last_run_id"]})}
        assert {"R-CRS-01", "R-CRS-02", "R-CRS-03", "R-SRC-01", "R-DATE-01", "R-FMT-01", "R-QUA-01"} <= rules
        assert f["comparison"]["status"] == "no_reference" and "R-REF-01" not in rules  # nothing approved to compare with
    detail = service.entry_detail(demo_ctx, REVIEWER, _entry(demo_ctx, 7)["_id"])
    assert len(detail["files"]) == 6 and detail["sketch"]["missing"] == 0


def test_sidecars_and_notes_are_not_registered(demo_ctx):
    names = {f["file_name"] for f in demo_ctx.db[dblib.FILES].find({})}
    assert len(names) == 18
    assert "Ortofoto_2009.tfw" not in names and "Leveransenotat_laserdata.txt" not in names
    assert sorted(_file(demo_ctx, "Ortofoto_2009.tif")["sidecars"]) == ["Ortofoto_2009.prj", "Ortofoto_2009.tfw"]


def test_ai_values_come_with_evidence(demo_ctx):
    las = _file(demo_ctx, "Laserdata_Nordby_2026_blokk1.las")
    assert las["effective"]["source"]["value"] == "Demo Survey AS"
    assert las["effective"]["source"]["from"] == "ai_text" and las["effective"]["source"]["evidence"]


def test_second_run_skips_unchanged(demo_ctx):
    counts = run_once(demo_ctx)["counts"]
    assert counts["skipped"] == 18 and counts["entries_created"] == 0


def test_new_version_of_old_data_is_suggested(demo_ctx):
    assert _entry(demo_ctx, 3)["replaces_candidate"]["seq"] == 1
    assert _entry(demo_ctx, 9)["replaces_candidate"]["seq"] == 2
    assert _entry(demo_ctx, 4).get("replaces_candidate") is None  # FKB-Veg is not FKB-Bygning


# --- Versions and superseded entries ---------------------------------------------------------------------------

def test_approving_a_new_version_supersedes_the_old(demo_ctx):
    old, new = _entry(demo_ctx, 1), _entry(demo_ctx, 3)
    service.decide(demo_ctx, REVIEWER, old["_id"], "ja", "OK")
    service.decide(demo_ctx, REVIEWER, new["_id"], "ja", "Erstatter #1")
    old = _entry(demo_ctx, 1)
    assert old["lifecycle"] == "utgatt" and old["superseded_by"]["seq"] == 3
    new = _entry(demo_ctx, 3)
    assert new["qa_status"] == "utfort" and new["qa_date"] and new["review"]["by"] == REVIEWER["name"]
    service.decide(demo_ctx, REVIEWER, new["_id"], None)  # reopen
    assert _entry(demo_ctx, 1)["lifecycle"] == "gjeldende"
    assert _entry(demo_ctx, 3)["history"][-1]["event"] == "Gjenåpnet"


def test_manual_replacement_choice(demo_ctx):
    e = _entry(demo_ctx, 3)
    service.update_qa(demo_ctx, REVIEWER, e["_id"], {"replaces": "none"})
    service.decide(demo_ctx, REVIEWER, e["_id"], "ja", "")
    assert _entry(demo_ctx, 1)["lifecycle"] == "gjeldende"
    service.update_qa(demo_ctx, REVIEWER, e["_id"], {"replaces": _entry(demo_ctx, 1)["_id"]})
    assert _entry(demo_ctx, 1)["lifecycle"] == "utgatt"
    with pytest.raises(ValueError):
        service.update_qa(demo_ctx, REVIEWER, _entry(demo_ctx, 1)["_id"], {"replaces": e["_id"]})  # must be earlier


def test_new_file_version_sends_entry_back_to_qa(demo_ctx):
    service.decide(demo_ctx, REVIEWER, _entry(demo_ctx, 3)["_id"], "ja", "OK")
    assert _entry(demo_ctx, 1)["lifecycle"] == "utgatt"
    f = _file(demo_ctx, "FKB_Bygning_2026.sos")
    path = demo_ctx.source.path_of(PID, f["source_path"])
    path.unlink()  # the sample is hard-linked; replace it rather than writing through the link
    path.write_bytes(b".HODE\n..TEGNSETT UTF-8\n.SLUTT\n")
    assert run_once(demo_ctx)["counts"]["new version"] == 1
    e = _entry(demo_ctx, 3)
    assert e["ready"] is None and e["qa_status"] == "ikke_begynt" and e["history"][-1]["ready"] == "ja"
    assert _file(demo_ctx, "FKB_Bygning_2026.sos")["version"] == 2
    assert _entry(demo_ctx, 1)["lifecycle"] == "gjeldende"  # the old one is back in use until the new one is approved


# --- Comparison with approved reference data ------------------------------------------------------------------------

def test_approved_terrain_model_becomes_reference(demo_ctx):
    service.decide(demo_ctx, REVIEWER, _entry(demo_ctx, 2)["_id"], "ja", "Referanse")
    laser = _laser(demo_ctx)
    assert all(f["comparison"]["status"] == "done" and f["comparison"]["reference"]["entry_seq"] == 2 for f in laser)
    blokk5 = next(f for f in laser if "blokk5" in f["file_name"])
    assert blokk5["comparison"]["mean_m"] == pytest.approx(0.32, abs=0.03)
    assert blokk5["check_result"] == "deviation" and blokk5["deviations"] == ["R-REF-01"]
    assert "Systematisk høydeavvik +0,32 m" in _check(demo_ctx, blokk5["file_name"], "R-REF-01")["evidence"]
    others = [f for f in laser if f is not blokk5]
    assert all(abs(f["comparison"]["mean_m"]) < 0.05 and f["check_result"] == "ok" for f in others)
    e7 = _entry(demo_ctx, 7)
    assert e7["check_result"] == "deviation" and e7["deviations"] == ["R-REF-01"]


def test_new_terrain_model_compared_and_put_into_use(demo_ctx):
    service.decide(demo_ctx, REVIEWER, _entry(demo_ctx, 2)["_id"], "ja", "Referanse")
    q = _question(demo_ctx, 9, "horizontal_epsg")
    service.answer_question(demo_ctx, OLA, q["_id"], q["choices"][0])
    f = _file(demo_ctx, "Terrengmodell_DTM2_2026.tif")
    c = f["comparison"]
    assert c["status"] == "done" and abs(c["mean_m"]) < 0.05 and not c["shift"]["suspected"]
    assert c["area_over_m2"]["0.5"] == pytest.approx(69_400, rel=0.02)
    ref = _check(demo_ctx, f["file_name"], "R-REF-01")
    assert ref["result"] == "warning" and "69,4 daa" in ref["evidence"]
    assert _entry(demo_ctx, 9)["qa_status"] == "pagar"  # an answer starts the QA

    with pytest.raises(ValueError):
        service.decide(demo_ctx, REVIEWER, _entry(demo_ctx, 9)["_id"], "med_forbehold", "")  # needs the reservation
    res = service.decide(demo_ctx, REVIEWER, _entry(demo_ctx, 9)["_id"], "med_forbehold", "Lokale endringer ved ny veg.")
    assert res["rechecked"] >= 1
    old = _entry(demo_ctx, 2)
    assert old["lifecycle"] == "utgatt" and old["superseded_by"]["seq"] == 9
    assert all(x["comparison"]["reference"]["entry_seq"] == 9 for x in _laser(demo_ctx))


# --- Questions and answers ----------------------------------------------------------------------------------------------

def test_mislabelled_crs_question_and_answer(demo_ctx):
    q = _question(demo_ctx, 5, "horizontal_epsg")
    assert q["kind"] == "contradiction" and q["suggested"].startswith("EPSG:25832")
    with pytest.raises(PermissionError):
        service.answer_question(demo_ctx, OLA, q["_id"], q["suggested"])  # not Ola's delivery
    service.answer_question(demo_ctx, KARI, q["_id"], q["suggested"])
    crs = _check(demo_ctx, "Ortofoto_2009.tif", "R-CRS-01")
    assert crs["result"] == "warning" and "be leverandøren rette fila" in crs["evidence"]
    assert "R-CRS-03" not in _file(demo_ctx, "Ortofoto_2009.tif")["deviations"]


def test_answers_fill_in_and_recheck(demo_ctx):
    for field, answer in (("horizontal_epsg", "EPSG:25832 – EUREF89 UTM32 (koordinatene passer)"),
                          ("height_reference", "NN2000"), ("data_date", "mai 2024"), ("source", "Byggherren, innmålt av Demo Survey AS")):
        service.answer_question(demo_ctx, OLA, _question(demo_ctx, 8, field)["_id"], answer)
    f = _file(demo_ctx, "Innmaaling_kummer.dxf")
    assert f["effective"]["data_date"] == {**f["effective"]["data_date"], "value": "2024-05", "from": "uploader"}
    assert f["deviations"] == ["R-QUA-01"]
    left = {q["field"] for q in demo_ctx.db[dblib.QUESTIONS].find({"entry_id": f["entry_id"], "status": "open"})}
    assert left == {"quality", "comments"} and _entry(demo_ctx, 8)["open_questions"] == 2


def test_dont_know_is_recorded(demo_ctx):
    service.answer_question(demo_ctx, OLA, _question(demo_ctx, 10, "source")["_id"], "Vet ikke")
    src = _check(demo_ctx, "Ledninger_VA.gpkg", "R-SRC-01")
    assert src["result"] == "deviation" and "bekreftet av opplaster" in src["evidence"]


def test_bad_answer_keeps_question_open(demo_ctx):
    q = _question(demo_ctx, 8, "horizontal_epsg")
    with pytest.raises(AnswerError):
        service.answer_question(demo_ctx, OLA, q["_id"], "den vanlige")
    assert demo_ctx.db[dblib.QUESTIONS].find_one({"_id": q["_id"]})["status"] == "open"


def test_notifications_group_questions_per_uploader(demo_ctx):
    mails = list(demo_ctx.db[dblib.NOTIFICATIONS].find({"kind": "questions"}))
    assert {m["to"] for m in mails} == {OLA["email"], KARI["email"]}
    ola = next(m for m in mails if m["to"] == OLA["email"])
    assert "3 registreringer" in ola["body"] and ola["link"].endswith("#register")
    kari = next(m for m in mails if m["to"] == KARI["email"])
    assert kari["link"].endswith(f"#entry-{_entry(demo_ctx, 5)['_id']}")


# --- KS ------------------------------------------------------------------------------------------------------------------

def test_only_reviewers_do_ks(demo_ctx):
    e = _entry(demo_ctx, 4)
    with pytest.raises(PermissionError):
        service.decide(demo_ctx, KARI, e["_id"], "ja")
    with pytest.raises(PermissionError):
        service.update_qa(demo_ctx, KARI, e["_id"], {"qa_status": "pagar"})
    with pytest.raises(ValueError):
        service.decide(demo_ctx, REVIEWER, e["_id"], "nei")  # needs a comment
    service.decide(demo_ctx, REVIEWER, e["_id"], "nei", "Lever på nytt i UTM32.")
    assert _entry(demo_ctx, 4)["ready"] == "nei"
    assert demo_ctx.db[dblib.NOTIFICATIONS].find_one({"to": KARI["email"], "kind": "review"})


def test_ks_fields(demo_ctx):
    e = _entry(demo_ctx, 10)
    service.update_qa(demo_ctx, REVIEWER, e["_id"], {"discipline": "VA", "qa_status": "utfort", "qa_note": "Sjekket mot kart",
                                                    "received_from": "Kommunen v/ Ola Hansen"})
    row = service.list_entries(demo_ctx, REVIEWER, PID)[9]
    assert row["qa_status"] == "utfort" and row["qa_date"] and row["received_from"] == "Kommunen v/ Ola Hansen"
    with pytest.raises(ValueError):
        service.update_qa(demo_ctx, REVIEWER, e["_id"], {"discipline": "XYZ"})


def test_worker_never_touches_ks_fields(demo_ctx):
    e = _entry(demo_ctx, 6)
    service.decide(demo_ctx, REVIEWER, e["_id"], "ja", "fint")
    run_once(demo_ctx, force=True)
    e = _entry(demo_ctx, 6)
    assert e["ready"] == "ja" and e["review"]["comment"] == "fint" and e["qa_status"] == "utfort"


# --- Project settings and rule sets -----------------------------------------------------------------------------------------

def _settings(ctx):
    s = service.get_settings(ctx, REVIEWER, PID)
    s["project_area"] = "\n".join(f"{x} {y}" for x, y in s["project_area"]["coordinates"])
    s["disciplines"] = ", ".join(s["disciplines"])
    return s


def test_settings_change_rechecks(demo_ctx):
    s = _settings(demo_ctx)
    assert "R-DATE-01" in _file(demo_ctx, "Ortofoto_2009.tif")["deviations"]
    res = service.save_settings(demo_ctx, REVIEWER, PID, {**s, "max_data_age_years": 20})
    assert res["rechecked"] == 13 and res["max_data_age_years"] == 20
    assert "R-DATE-01" not in _file(demo_ctx, "Ortofoto_2009.tif")["deviations"]
    res = service.save_settings(demo_ctx, REVIEWER, PID, {**_settings(demo_ctx), "question_reminder_days": 3})
    assert res["rechecked"] == 0  # nothing the checks depend on


def test_settings_validation_and_permissions(demo_ctx):
    s = _settings(demo_ctx)
    with pytest.raises(PermissionError):
        service.save_settings(demo_ctx, KARI, PID, s)
    with pytest.raises(ValueError):
        service.save_settings(demo_ctx, REVIEWER, PID, {**s, "accepted_formats": []})
    with pytest.raises(ValueError):
        service.save_settings(demo_ctx, REVIEWER, PID, {**s, "project_area": "600000 6640000\n601000 6640000"})


def test_create_project(demo_ctx):
    s = _settings(demo_ctx)
    res = service.save_settings(demo_ctx, REVIEWER, None, {**s, "id": "E18 Test", "name": "E18 Test",
                                                          "horizontal_crs": "EPSG:5110"})
    assert res["id"] == "e18-test" and res["horizontal_crs"] == "EPSG:5110"
    assert [p["id"] for p in service.list_projects(demo_ctx, REVIEWER)] == ["e18-test", PID]
    with pytest.raises(ValueError):
        service.save_settings(demo_ctx, REVIEWER, None, {**s, "id": PID})  # taken


def test_rules_edit_new_version_and_recheck(demo_ctx):
    rs = service.get_rules(demo_ctx, REVIEWER, PID)
    assert rs["version"] == "v1.0" and rs["can_edit"]
    rules = [{**r, "active": r["id"] != "R-DATE-01"} for r in rs["rules"]]
    rules.append({"id": "R-AI-01", "text": "Ortofoto skal ha dokumentert flyhøyde", "applies_to": ["orthophoto"],
                  "check": "ai", "if_failed": "warning", "guidance": "Se etter flyhøyde i metadata."})
    res = service.save_rules(demo_ctx, REVIEWER, PID, rules, "Test")
    assert res["version"] == "v1.1" and res["active"] == "v1.1" and [v["version"] for v in res["versions"]] == ["v1.1", "v1.0"]
    assert "13 registreringer" in res["message"]
    assert _check(demo_ctx, "Ortofoto_2009.tif", "R-DATE-01") is None
    assert _check(demo_ctx, "Ortofoto_2009.tif", "R-AI-01")["checked_by"] == "ai"
    assert _check(demo_ctx, "FKB_Veg_2026.sos", "R-AI-01") is None  # applies to orthophotos only
    assert _file(demo_ctx, "Ortofoto_2009.tif")["ruleset_version"] == "v1.1"


def test_rules_validation(demo_ctx):
    rules = service.get_rules(demo_ctx, REVIEWER, PID)["rules"]
    with pytest.raises(ValueError):
        service.validate_rules(rules + [{"id": "R-NY-01", "text": "Noe som skal sjekkes", "check": "auto"}])
    with pytest.raises(ValueError):
        service.validate_rules(rules + [dict(rules[0])])  # duplicate id
    with pytest.raises(ValueError):
        service.validate_rules([{**rules[-1], "params": {}}] + [{"id": "feil", "text": "Kort nok krav"}])
    with pytest.raises(PermissionError):
        service.save_rules(demo_ctx, OLA, PID, rules)


def test_draft_rules_for_reviewers(demo_ctx):
    out = service.draft_rules(demo_ctx, REVIEWER, PID, "Punktskyer skal ha minst 5 punkter per m².")
    assert out["rules"][0]["applies_to"] == ["point_cloud"] and "regelbasert" in out["model"]


# --- Export -----------------------------------------------------------------------------------------------------------------

def test_excel_export(demo_ctx):
    service.decide(demo_ctx, REVIEWER, _entry(demo_ctx, 1)["_id"], "ja", "OK")
    service.decide(demo_ctx, REVIEWER, _entry(demo_ctx, 3)["_id"], "ja", "OK")
    wb = load_workbook(io.BytesIO(export_project(demo_ctx.db, PID)))
    assert wb.sheetnames == ["Register", "Filer", "Kontroller", "Spørsmål", "Regelsett"]
    reg = wb["Register"]
    assert [c.value for c in reg[1]][:11] == [
        "Rekkefølge", "Dokumentnavn/Pakke", "Innhold i fil/folder", "Filtype", "Dato mottatt", "Mottatt fra", "Lenke",
        "Ansvarlig fag for KS", "Status kontroll", "Dato kontrollert", "Er dokument/fil klar til bruk?"]
    assert reg.max_row == 14 and [reg.cell(row=r, column=1).value for r in range(2, 15)] == list(range(1, 14))
    assert reg["I2"].value == "Utført" and reg["K2"].value == "Ja" and reg["O2"].value == "Utgått"
    assert reg["H9"].value == "VA" and reg["B8"].value == "Laserdata_Nordby_2026" and reg["T8"].value == 6
    assert wb["Filer"].max_row == 19
