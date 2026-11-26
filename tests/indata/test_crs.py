from basedata.indata import crs

PROJECT = {"horizontal_crs": "EPSG:25832",
           "project_area": {"crs": "EPSG:25832", "coordinates": [[600000, 6640000], [604000, 6640000],
                                                                [604000, 6643000], [600000, 6643000]]}}


def test_utm32_roundtrip_oslo():
    x, y = crs.from_lonlat(25832, 10.7334, 59.9119)
    assert abs(x - 596935) < 5 and abs(y - 6642869) < 5
    lon, lat = crs.to_lonlat(25832, x, y)
    assert abs(lon - 10.7334) < 1e-7 and abs(lat - 59.9119) < 1e-7


def test_ntm10_uses_latitude_of_origin_58():
    x, y = crs.from_lonlat(5110, 10.7334, 59.9119)
    assert 1_200_000 < y < 1_225_000
    lon, lat = crs.to_lonlat(5110, x, y)
    assert abs(lat - 59.9119) < 1e-7


def test_parse_crs_forms():
    assert crs.parse_crs("EPSG:25832") == 25832
    assert crs.parse_crs("urn:ogc:def:crs:EPSG::25833") == 25833
    assert crs.parse_crs("http://www.opengis.net/def/crs/EPSG/0/5110") == 5110
    assert crs.parse_wkt('PROJCS["ETRS89 / UTM zone 32N",AUTHORITY["EPSG","25832"]]') == (25832, None)


def test_mislabelled_crs_is_detected():
    ext = {"minx": 600500, "miny": 6640500, "maxx": 603500, "maxy": 6642500}
    ok = crs.plausibility(ext, 25832, PROJECT)
    bad = crs.plausibility(ext, 25833, PROJECT)
    assert ok["declared_fits"] is True
    assert bad["declared_fits"] is False and bad["candidates"][0]["epsg"] == 25832


def test_local_coordinates():
    assert crs.plausibility({"minx": 1000, "miny": 2000, "maxx": 1500, "maxy": 2600}, None, PROJECT)["looks_local"]


def test_coverage_half():
    assert crs.coverage({"minx": 600000, "miny": 6640000, "maxx": 602000, "maxy": 6643000}, 25832, PROJECT) == 0.5
    assert crs.coverage({"minx": 590000, "miny": 6630000, "maxx": 591000, "maxy": 6631000}, 25832, PROJECT) == 0.0
