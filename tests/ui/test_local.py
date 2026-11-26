"""Lokal drift: registeret i en SQLite-fil og grunnlagsdata fra en vanlig mappe (lokal eller OneDrive)."""

import io
import os
import shutil
from datetime import datetime, timezone

import pytest
from openpyxl import load_workbook

from basedata.core import db as dblib
from basedata.ui import service
from basedata.__main__ import main
from basedata.ui.export_excel import export_project
from basedata.indata.folder_source import FolderSource, person, write_delivery_file
from basedata.ui.local import ensure_project, local_user, project_id_for
from basedata.core.localstore import LocalDatabase, open_store
from basedata.core.settings import Settings
from basedata.harness.worker import make_context, run_once

WHEN = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)
KARI = {"name": "Kari Nordmann", "email": "kari.nordmann@example.com"}


# --- Lagring --------------------------------------------------------------------------------------------------------

def test_store_survives_restart(tmp_path):
    path = tmp_path / "register.db"
    db = LocalDatabase(path)
    db["c"].create_index("k", unique=True)
    db["c"].insert_one({"_id": "a", "k": 1, "at": WHEN, "raw": b"\x00\x01", "list": [1, {"x": 2}]})
    db["c"].insert_one({"_id": "b", "k": 2})
    db["c"].update_one({"_id": "a"}, {"$set": {"n": 5}, "$push": {"list": 3}})
    db["c"].update_many({}, {"$inc": {"count": 1}})
    db["c"].delete_one({"_id": "b"})
    db["c"].replace_one({"_id": "z"}, {"_id": "z", "k": 9}, upsert=True)
    db._blobs["blob1"] = b"heights"
    db.close()

    db2 = LocalDatabase(path)
    a = db2["c"].find_one({"_id": "a"})
    assert a["at"] == WHEN and a["raw"] == b"\x00\x01" and a["n"] == 5 and a["list"] == [1, {"x": 2}, 3] and a["count"] == 1
    assert db2["c"].find_one({"_id": "b"}) is None and db2["c"].find_one({"_id": "z"})["k"] == 9
    assert db2._blobs["blob1"] == b"heights"
    db2.close()


def test_store_keeps_unique_indexes(tmp_path):
    db = open_store(tmp_path / "r.db")
    db[dblib.FILES].insert_one({"_id": "f1", "source_key": "p:a.sos"})
    with pytest.raises(Exception):
        db[dblib.FILES].insert_one({"_id": "f2", "source_key": "p:a.sos"})
    db.close()
    db = open_store(tmp_path / "r.db")
    assert db[dblib.FILES].count_documents({}) == 1  # the refused insert was not written
    db.close()


# --- Kildemappa ---------------------------------------------------------------------------------------------------

def test_person_parsing():
    assert person("Kari Nordmann <Kari.Nordmann@example.com>") == KARI
    assert person("kari.nordmann@example.com") == KARI
    assert person("Kartverket") == {"name": "Kartverket", "email": ""}
    assert person(None) == {"name": "Ukjent", "email": ""}


def test_folder_layout(tmp_path):
    root = tmp_path / "Grunnlagsdata"
    (root / "2026-10-27 Kartverket" / "Ortofoto").mkdir(parents=True)
    (root / "2026-10-27 Kartverket" / "a.sos").write_text("x")
    (root / "2026-10-27 Kartverket" / "Ortofoto" / "b.tif").write_text("x")
    (root / "Leveranse uten dato").mkdir()
    (root / "Leveranse uten dato" / "c.dxf").write_text("x")
    write_delivery_file(root / "Leveranse uten dato", KARI, WHEN)
    (root / "notat.pdf").write_text("x")
    for junk in ("~$register.xlsx", "desktop.ini", ".hidden", "x.tmp"):
        (root / junk).write_text("x")
    (root / "_basedata").mkdir()
    (root / "_basedata" / "register.db").write_text("x")

    db = open_store(tmp_path / "r.db")
    db[dblib.PROJECTS].insert_one({"_id": "p", "source_folder": str(root)})
    files = {f.rel_path: f for f in FolderSource(db, Settings()).list_files()}
    assert set(files) == {"2026-10-27 Kartverket/a.sos", "2026-10-27 Kartverket/Ortofoto/b.tif",
                          "Leveranse uten dato/c.dxf", "notat.pdf"}
    a, b, c = files["2026-10-27 Kartverket/a.sos"], files["2026-10-27 Kartverket/Ortofoto/b.tif"], files["Leveranse uten dato/c.dxf"]
    assert a.delivery_id == "2026-10-27 Kartverket" and a.folder == "" and b.folder == "Ortofoto"
    assert a.uploaded_at == datetime(2026, 10, 27, tzinfo=timezone.utc) and a.uploaded_by["name"] == "Ukjent"
    assert c.uploaded_at == WHEN and c.uploaded_by == KARI and c.key == "p:Leveranse uten dato/c.dxf"
    assert files["notat.pdf"].delivery_id.startswith("(rett i kildemappa)")
    src = FolderSource(db, Settings())
    assert src.path_of("p", "../r.db") is None  # nothing outside the source folder can be opened
    assert src.path_of("p", "notat.pdf") == (root / "notat.pdf").resolve()
    db.close()


def test_project_from_folder(tmp_path):
    root = tmp_path / "Rv 999 Nordby" / "Grunnlagsdata"
    root.mkdir(parents=True)
    assert project_id_for(root) == "rv-999-nordby"
    db = open_store(tmp_path / "r.db")
    p = ensure_project(db, root)
    assert p["_id"] == "rv-999-nordby" and p["name"] == "Rv 999 Nordby" and p["source_folder"] == str(root.resolve())
    assert db[dblib.RULESETS].find_one({"project_id": p["_id"]})["version"] == p["active_ruleset"]
    assert ensure_project(db, root)["_id"] == p["_id"] and db[dblib.PROJECTS].count_documents({}) == 1
    db.close()


def test_local_user_is_reviewer():
    u = local_user(Settings(user_name="Philip Hon", user_email="P@X.NO"))
    assert u == {"name": "Philip Hon", "email": "p@x.no", "roles": ["reviewer"], "role_label": "KS-ansvarlig"}
    assert service.is_reviewer(local_user(Settings()))


def test_settings_check_the_folder(tmp_path):
    base = {"name": "X", "project_type": "Veg", "phase": "Reguleringsplan", "horizontal_crs": "EPSG:25832",
            "height_reference": "NN2000", "accepted_formats": ["sos"], "max_data_age_years": 10,
            "question_reminder_days": 5, "package_threshold": 5, "disciplines": "VEG"}
    assert service.validate_settings({**base, "source_folder": f'"{tmp_path}"'})["source_folder"] == str(tmp_path)
    with pytest.raises(ValueError, match="Fant ikke mappa"):
        service.validate_settings({**base, "source_folder": str(tmp_path / "finnes-ikke")})


# --- Hele løpet på en ekte mappe -------------------------------------------------------------------------------------

def _copy(samples, root, delivery, names, sender=KARI, when=WHEN):
    d = root / delivery
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        shutil.copy2(samples / n, d / n)
    write_delivery_file(d, sender, when)


def test_folder_to_register_and_back(samples, tmp_path):
    root = tmp_path / "Grunnlagsdata"
    _copy(samples, root, "2026-10-27 D-101", ["FKB_Bygning_2026.sos", "FKB_Veg_2026.sos"])
    settings = Settings(source_folder=str(root), ai_provider="offline_demo")
    db = dblib.connect(settings)
    assert settings.resolved_store_path() == root / "_basedata" / "register.db"
    project = ensure_project(db, root)
    ctx = make_context(db, settings)
    run = run_once(ctx)
    assert run["counts"]["new"] == 2 and not run["errors"]
    rows = service.list_entries(ctx, local_user(settings), project["_id"])
    assert [r["name"] for r in rows] == ["FKB_Bygning_2026.sos", "FKB_Veg_2026.sos"]
    veg = next(r for r in rows if r["name"] == "FKB_Veg_2026.sos")
    service.add_comment(ctx, local_user(settings), veg["id"], "Levert i UTM33, spør Kartverket.")
    db.close()

    # Restart: everything is still there, and unchanged files are not checked again.
    db = dblib.connect(settings)
    ctx = make_context(db, settings)
    assert run_once(ctx)["counts"]["skipped"] == 2
    e = db[dblib.ENTRIES].find_one({"name": "FKB_Veg_2026.sos"})
    assert e["comments"][-1]["text"].startswith("Levert i UTM33") and e["uploader"]["email"] == KARI["email"]

    # A new delivery folder and a changed file are picked up on the next pass.
    _copy(samples, root, "2026-10-30 D-104", ["Innmaaling_kummer.dxf"], sender={"name": "Ola Hansen", "email": ""})
    target = root / "2026-10-27 D-101" / "FKB_Bygning_2026.sos"
    shutil.copy2(samples / "FKB_Bygning_2025.sos", target)
    os.utime(target, None)
    counts = run_once(ctx)["counts"]
    assert counts["new"] == 1 and counts["new version"] == 1
    assert db[dblib.FILES].find_one({"file_name": "FKB_Bygning_2026.sos"})["version"] == 2

    # The Excel register links straight to the file in the source folder.
    wb = load_workbook(io.BytesIO(export_project(db, project["_id"], settings)))
    links = [c.hyperlink.target for c in wb["Register"]["G"][1:] if c.hyperlink]
    assert len(links) == 3 and all(link.startswith("file:") for link in links)
    assert any(link.endswith("FKB_Veg_2026.sos") for link in links)
    db.close()


def test_command_line_run(samples, tmp_path, capsys):
    root = tmp_path / "Prosjekt"
    _copy(samples, root, "2026-09-02 D-090", ["FKB_Bygning_2025.sos"])
    assert main(["run", "--folder", str(root)]) == 0
    out = capsys.readouterr().out
    assert '"new": 1' in out and str(root / "_basedata" / "register.db") in out
    assert main(["run", "--folder", str(root)]) == 0
    assert '"skipped": 1' in capsys.readouterr().out
