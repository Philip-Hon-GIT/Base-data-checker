"""Map overview and project area."""

import pytest

from basedata.indata import crs as crslib
from basedata.core import db as dblib
from basedata.ui import service
from basedata.selfcheck.demo import REVIEWER, USERS

PID = "rv999-nordby"
KARI = USERS[1]
AREA_LONLAT = [[10.80, 59.90], [10.86, 59.90], [10.86, 59.93], [10.80, 59.93]]


def test_map_data_places_every_registration(demo_ctx):
    m = service.map_data(demo_ctx, REVIEWER, PID)
    assert m["crs"] == "EPSG:25832" and len(m["area"]["lonlat"]) == 6 and not m["unplaced"]
    by_seq = {i["seq"]: i for i in m["items"]}
    assert len(by_seq[7]["footprints"]) == 6                      # one footprint per file in the package
    assert by_seq[5]["footprints"][0]["guess"] is True             # labelled UTM33, fits UTM32
    assert by_seq[9]["footprints"][0]["guess"] is True             # CRS unknown, placed where it fits
    assert by_seq[4]["footprints"][0]["crs_name"] == "EUREF89 UTM33"
    lon, lat = by_seq[12]["footprints"][0]["ring"][0]
    assert 10.7 < lon < 10.9 and 59.8 < lat < 60.0                # Oslo east, where the demo project lies
    assert by_seq[12]["summary"].startswith("Tegning C101")


def test_manual_crs_correction_is_not_a_guess(demo_ctx):
    eid = demo_ctx.db[dblib.ENTRIES].find_one({"seq": 9})["_id"]
    service.correct_value(demo_ctx, REVIEWER, eid, "horizontal_epsg", "EPSG:25832", "")
    m = service.map_data(demo_ctx, REVIEWER, PID)
    assert next(i for i in m["items"] if i["seq"] == 9)["footprints"][0]["guess"] is False


def test_save_area_from_lonlat_and_from_project_crs(demo_ctx):
    res = service.save_area(demo_ctx, REVIEWER, PID, AREA_LONLAT, "EPSG:4326", "rektangel tegnet i kartet")
    area = demo_ctx.db[dblib.PROJECTS].find_one({"_id": PID})["project_area"]
    assert area["crs"] == "EPSG:25832" and len(area["coordinates"]) == 4 and area["source"] == "rektangel tegnet i kartet"
    x, y = area["coordinates"][0]
    back = crslib.to_lonlat(25832, x, y)
    assert back[0] == pytest.approx(10.80, abs=1e-6) and back[1] == pytest.approx(59.90, abs=1e-6)
    assert "13 registreringer" in res["message"] and res["area"]["updated_by"] == REVIEWER["name"]
    utm = [[600300, 6640400], [601500, 6640150], [603900, 6642000], [603500, 6642800], [600300, 6640400]]
    service.save_area(demo_ctx, REVIEWER, PID, utm, "EPSG:25832", "fil: grense.xml")
    assert demo_ctx.db[dblib.PROJECTS].find_one({"_id": PID})["project_area"]["coordinates"][1] == [601500, 6640150]


def test_save_area_validation(demo_ctx):
    with pytest.raises(PermissionError):
        service.save_area(demo_ctx, KARI, PID, AREA_LONLAT)
    with pytest.raises(ValueError):
        service.save_area(demo_ctx, REVIEWER, PID, AREA_LONLAT[:2])
    with pytest.raises(ValueError):
        service.save_area(demo_ctx, REVIEWER, PID, [[-74.0, 40.7], [-73.9, 40.7], [-73.9, 40.8]])  # New York
    with pytest.raises(ValueError):
        service.save_area(demo_ctx, REVIEWER, PID, [[10.8, 59.9], [10.8000001, 59.9], [10.8, 59.9000001]])  # too small


def test_map_footprints_carry_real_geometry(demo_ctx):
    m = service.map_data(demo_ctx, REVIEWER, PID)
    by_file = {f["file"]: f["geom"] for i in m["items"] for f in i["footprints"]}
    assert len(by_file["Innmaaling_kummer.dxf"]["points"]) == 24 and len(by_file["Innmaaling_kummer.dxf"]["lines"]) == 10
    assert by_file["Ledninger_VA.gpkg"]["kind"] == "features" and len(by_file["Ledninger_VA.gpkg"]["lines"]) == 40
    assert by_file["FKB_Bygning_2026.sos"]["kind"] == "features" and len(by_file["FKB_Bygning_2026.sos"]["polygons"]) == 46
    assert by_file["Laserdata_Nordby_2026_blokk1.las"]["kind"] == "outline"
    assert by_file["Ortofoto_2009.tif"]["kind"] == "box"                 # a full raster: its extent is its footprint
    assert by_file["C101_Plan_og_profil.pdf"]["kind"] == "box"
    lon, lat = by_file["VA_modell_Nordby.ifc"]["points"][0]
    assert 10.7 < lon < 10.9 and 59.8 < lat < 60.0
