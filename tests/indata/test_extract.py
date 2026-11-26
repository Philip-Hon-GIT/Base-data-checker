from basedata.indata.extract import extract


def test_sosi_header(samples):
    md = extract(samples / "FKB_Bygning_2025.sos")
    assert md.horizontal_epsg == 25832 and md.height_reference == "NN2000"
    assert md.source == "Kartverket" and md.data_date == "2024-06-12"
    assert md.quality["accuracy_cm"]["median"] == 15 and md.quality["product_spec"] == "FKB-Bygning 5.0"
    assert md.count == 40


def test_sosi_utm33(samples):
    assert extract(samples / "FKB_Veg_2026.sos").horizontal_epsg == 25833


def test_geotiff_keys(samples):
    md = extract(samples / "Ortofoto_2023_tile_0603.tif")
    assert md.horizontal_epsg == 25832 and md.quality["pixel_size_m"] == 0.25
    assert md.extent == {"minx": 601000, "miny": 6641550, "maxx": 601250, "maxy": 6641800}


def test_tiff_with_world_file_and_prj(samples):
    md = extract(samples / "Ortofoto_2009.tif")
    assert md.horizontal_epsg == 25833  # from the .prj sidecar
    assert md.details["georef_from"] == "Ortofoto_2009.tfw"
    assert md.extent["minx"] == 601500


def test_dtm_with_and_without_crs(samples):
    old = extract(samples / "Terrengmodell_DTM2_2021.tif")
    assert old.horizontal_epsg == 25832 and old.height_reference == "NN2000" and old.details["raster_kind"] == "elevation grid"
    new = extract(samples / "Terrengmodell_DTM2_2026.tif")
    assert new.horizontal_epsg is None and new.extent == old.extent
    assert any("Ingen koordinatsystem" in n for n in new.notes)


def test_las_header(samples):
    md = extract(samples / "Laserdata_Nordby_2026_blokk1.las")
    assert md.format_version == "1.4" and md.count == 50000
    assert md.horizontal_epsg == 25832 and md.height_reference == "NN2000"
    assert md.quality["density_pts_per_m2"] == 5.0
    assert set(md.quality["classes_sampled"]) == {1, 2, 3, 5, 6}


def test_dxf(samples):
    md = extract(samples / "Innmaaling_kummer.dxf")
    assert md.format_version == "R12" and md.quality["units"] == "meter"
    assert md.horizontal_epsg is None and md.count == 58
    assert "KUM_SPILLVANN" in md.details["layers"]


def test_geopackage(samples):
    md = extract(samples / "Ledninger_VA.gpkg")
    assert md.horizontal_epsg == 25832 and md.count == 40 and md.data_date is None


def test_pdf(samples):
    md = extract(samples / "Grunnundersokelse_datarapport.pdf")
    assert md.count == 2 and "Demo Geo AS" in md.text_excerpt


def test_broken_file_never_raises(tmp_path):
    p = tmp_path / "broken.tif"
    p.write_bytes(b"not a tiff")
    md = extract(p)
    assert md.notes and md.notes[0].startswith("Kunne ikke lese fila")


def test_pdf_drawing_is_recognised_and_placed(samples):
    md = extract(samples / "C101_Plan_og_profil.pdf")
    d = md.details
    assert d["pdf_kind"] == "drawing" and d["paper"] == "A1 liggende"
    assert d["drawing_no"] == "C101" and d["scale"] == "1:1000" and d["revision"] == "B"
    assert md.horizontal_epsg == 25832 and md.height_reference == "NN2000" and md.data_date == "2026-10-15"
    assert md.extent == {"minx": 601000.0, "miny": 6641000.0, "maxx": 603000.0, "maxy": 6642000.0}
    assert "FKB_Bygning_2026.sos" in d["scan"]["file_mentions"]


def test_pdf_report_is_text_with_coordinates(samples):
    md = extract(samples / "Grunnundersokelse_datarapport.pdf")
    assert md.details["pdf_kind"] == "text" and "drawing_no" not in md.details
    assert md.details["scan"]["drawing_mentions"] == ["C101"]
    assert md.extent == {"minx": 601640.0, "miny": 6641320.0, "maxx": 602250.0, "maxy": 6641610.0}


def test_ifc_model(samples):
    md = extract(samples / "VA_modell_Nordby.ifc")
    assert md.format_version == "IFC4" and md.horizontal_epsg == 25832 and md.height_reference == "NN2000"
    assert md.details["elements"] == {"rørsegmenter": 24, "rørdeler": 12, "kummer": 8}
    assert md.details["discipline_hint"] == "VA" and md.details["georef_from"] == "IfcMapConversion"
    assert md.extent == {"minx": 601500.0, "miny": 6641200.0, "maxx": 602600.0, "maxy": 6641900.0}
    assert md.source == "Demo VA AS" and md.data_date == "2026-10-28"
