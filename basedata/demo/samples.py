"""Synthetic base data for tests and the demo — no real project data.

A fictional road project ("Rv 999 Nordby", EUREF89 UTM32 near Oslo) with deliveries spread over two
months: an approved terrain model and FKB from September, then October deliveries with typical
problems — a new FKB version, FKB in the wrong CRS, a mislabelled orthophoto, a laser package where one
block sits 0,32 m too high, a new terrain model without CRS that shows a new road cut, a DXF with
nothing but coordinates, a GeoPackage without dates, and a PDF report.
"""

from __future__ import annotations

import random
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import crs as crslib

SAMPLES_VERSION = "5-innhold"
PROJECT_ID = "rv999-nordby"
PROJECT_AREA = [[600000, 6640200], [601200, 6640000], [604000, 6642200],
                [603600, 6643000], [602400, 6642700], [600200, 6641000]]
BBOX = (599900, 6639900, 604100, 6643100)  # terrain models cover this rectangle

PROJECT = {
    "_id": PROJECT_ID,
    "name": "Rv 999 Nordby (demo)",
    "project_type": "Veg",
    "phase": "Reguleringsplan",
    "horizontal_crs": "EPSG:25832",
    "height_reference": "NN2000",
    "accepted_formats": ["sos", "gml", "gpkg", "tif", "tiff", "las", "laz", "dxf", "ifc", "xml", "pdf"],
    "max_data_age_years": 10,
    "question_reminder_days": 5,
    "package_threshold": 5,
    "disciplines": ["VEG", "VA", "KON", "GEO", "LARK", "ELE"],
    "discipline_map": {"fkb": "VEG", "terrain": "VEG", "point_cloud": "VEG", "orthophoto": "VEG", "utility": "VA",
                       "ground_investigation": "GEO", "model": "KON", "drawing": "VEG", "plan_data": "VEG",
                       "other": "VEG"},
    "project_area": {"crs": "EPSG:25832", "coordinates": PROJECT_AREA},
    "active_ruleset": "v1.0",
}

KARI = {"name": "Kari Nordmann", "email": "kari.nordmann@example.com"}
OLA = {"name": "Ola Hansen", "email": "ola.hansen@example.com"}

WKT_25832_NN2000 = (
    'COMPD_CS["ETRS89 / UTM zone 32N + NN2000 height",PROJCS["ETRS89 / UTM zone 32N",GEOGCS["ETRS89",'
    'DATUM["European_Terrestrial_Reference_System_1989",SPHEROID["GRS 1980",6378137,298.257222101,'
    'AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","6258"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4258"]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",9],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","25832"]],VERT_CS["NN2000 height",'
    'VERT_DATUM["Norwegian Normal Null 2000",2005,AUTHORITY["EPSG","1096"]],UNIT["metre",1,'
    'AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","5941"]]]'
)
PRJ_25833 = (
    'PROJCS["ETRS89 / UTM zone 33N",GEOGCS["ETRS89",DATUM["European_Terrestrial_Reference_System_1989",'
    'SPHEROID["GRS 1980",6378137,298.257222101]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",15],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],'
    'UNIT["metre",1],AUTHORITY["EPSG","25833"]]'
)


def terrain(x, y):
    """The 'true' ground height in NN2000 for the demo area (smooth hills, 100–150 m)."""
    dx, dy = x - 600000.0, y - 6640000.0
    return 120 + 0.004 * dx + 8 * np.sin(dx / 310) * np.cos(dy / 260) + 3 * np.sin(dy / 140)


def _centerline(t: float) -> tuple[float, float]:
    return 600600 + t * 2900, 6640550 + t * 1900


def road_cut(x, y):
    """Height change of the new road cut (2026): up to 3 m deep, 50 m wide, 250 m north of the laser blocks."""
    off = (y - 6640550) - (x - 600600) * 1900 / 2900 - 250
    d = np.abs(off) * 2900 / np.hypot(2900, 1900)
    inside = (d < 25) & (x > 601300) & (x < 602600)
    return np.where(inside, -3.0 * np.cos(np.minimum(d, 25) / 25 * np.pi / 2), 0.0)


# --- SOSI ---------------------------------------------------------------------------------------

def _sosi(path: Path, koordsys: int, to_crs: int, spec: str, objtype: str, capture: str, n: int, seed: int) -> None:
    rnd = random.Random(seed)
    pts32 = [(rnd.uniform(600300, 603700), rnd.uniform(6640300, 6642700)) for _ in range(n)]
    pts = [crslib.transform(x, y, 25832, to_crs) for x, y in pts32] if to_crs != 25832 else pts32
    corners = [crslib.transform(x, y, 25832, to_crs) if to_crs != 25832 else (x, y)
               for x, y in ((BBOX[0], BBOX[1]), (BBOX[2], BBOX[1]), (BBOX[2], BBOX[3]), (BBOX[0], BBOX[3]))]
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    lines = [".HODE", "..TEGNSETT UTF-8", "..TRANSPAR", f"...KOORDSYS {koordsys}", "...ORIGO-NØ 0 0",
             "...ENHET 0.01", "...VERT-DATUM NN2000", "..OMRÅDE",
             f"...MIN-NØ {int(min(ys)) - 100} {int(min(xs)) - 100}", f"...MAX-NØ {int(max(ys)) + 100} {int(max(xs)) + 100}",
             "..SOSI-VERSJON 4.5", "..SOSI-NIVÅ 4", "..INNHOLD", f'...PRODUKTSPEK "{spec}"',
             '..EIER "Kartverket"', '..PRODUSENT "Kartverket"']
    for k, (x, y) in enumerate(pts, start=1):
        w = rnd.uniform(8, 25)
        lines += [f".FLATE {k}:", f"..OBJTYPE {objtype}", f"..DATAFANGSTDATO {capture}",
                  f"..KVALITET 22 {rnd.choice([10, 15, 15, 20])}", "..NØH"]
        for dx, dy in ((0, 0), (w, 0), (w, w), (0, w), (0, 0)):
            lines.append(f"{round((y + dy) * 100)} {round((x + dx) * 100)} {rnd.randint(9000, 14000)}")
    lines.append(".SLUTT")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- GeoTIFF ------------------------------------------------------------------------------------

def _geotiff(path: Path, data: np.ndarray, x0: float, y0: float, px: float, epsg: int | None, when: str,
             artist: str | None = None, world_file: bool = False, vertical: int | None = None) -> None:
    import tifffile
    extratags = []
    if not world_file:
        extratags += [(33550, "d", 3, (px, px, 0.0), True), (33922, "d", 6, (0.0, 0.0, 0.0, x0, y0, 0.0), True)]
    if epsg and not world_file:
        keys = [1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, epsg] + ([4096, 0, 1, vertical] if vertical else [])
        keys = [1, 1, 0, len(keys) // 4] + keys
        extratags.append((34735, "H", len(keys), keys, True))
    if artist:
        extratags.append((315, "s", 0, artist, True))
    photometric = "rgb" if data.ndim == 3 else "minisblack"
    tifffile.imwrite(path, data, photometric=photometric, compression="zlib", datetime=when,
                     software="basedata demo", extratags=extratags)
    if world_file:
        path.with_suffix(".tfw").write_text(f"{px}\n0.0\n0.0\n{-px}\n{x0 + px / 2}\n{y0 - px / 2}\n")


def _ortho(h: int, w: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    base = (np.sin(xx / 37.0) + np.cos(yy / 23.0)) * 40 + 120
    img = np.stack([base, base * 0.9 + 15, base * 0.7 + 10], axis=-1) + rng.normal(0, 3, (h, w, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def _dtm(cell: float, with_cut: bool, noise: float, seed: int) -> np.ndarray:
    x0, y0, x1, y1 = BBOX
    nx, ny = int((x1 - x0) / cell), int((y1 - y0) / cell)
    xs = x0 + (np.arange(nx) + 0.5) * cell
    ys = y1 - (np.arange(ny) + 0.5) * cell
    X, Y = np.meshgrid(xs, ys)
    z = terrain(X, Y)
    if with_cut:
        z = z + road_cut(X, Y)
    if noise:
        z = z + np.random.default_rng(seed).normal(0, noise, z.shape)
    return z.astype(np.float32)


# --- LAS ----------------------------------------------------------------------------------------

def _las(path: Path, x0: float, y0: float, size: float, density: float, wkt: str, year: int, doy: int,
         seed: int, dz: float = 0.0) -> None:
    rng = np.random.default_rng(seed)
    n = int(size * size * density)
    xs = rng.uniform(x0, x0 + size, n)
    ys = rng.uniform(y0, y0 + size, n)
    classes = rng.choice([1, 2, 3, 5, 6], n, p=[0.05, 0.55, 0.15, 0.15, 0.10])
    ground = terrain(xs, ys) + road_cut(xs, ys)
    zs = np.where(classes == 2, ground + rng.normal(0, 0.05, n), ground + rng.uniform(0.3, 15, n)) + dz
    scale = 0.01
    rec = np.zeros(n, dtype=[("X", "<i4"), ("Y", "<i4"), ("Z", "<i4"), ("i", "<u2"), ("r", "u1"), ("f", "u1"),
                             ("c", "u1"), ("u", "u1"), ("a", "<i2"), ("s", "<u2"), ("t", "<f8")])
    rec["X"] = np.round((xs - x0) / scale)
    rec["Y"] = np.round((ys - y0) / scale)
    rec["Z"] = np.round(zs / scale)
    rec["r"] = 0x11
    rec["c"] = classes
    payload = wkt.encode() + b"\x00"
    vlr = struct.pack("<H16sHH32s", 0, b"LASF_Projection", 2112, len(payload), b"OGC WKT") + payload
    header = struct.pack(
        "<4sHH16sBB32s32sHHHIIBHI5I3d3d6dQQIQ15Q",
        b"LASF", 0, 16, b"\x00" * 16, 1, 4, b"Demo drone scanner", b"basedata demo", doy, year, 375,
        375 + len(vlr), 1, 6, 30, 0, 0, 0, 0, 0, 0,
        scale, scale, scale, x0, y0, 0.0,
        float(xs.max()), float(xs.min()), float(ys.max()), float(ys.min()), float(zs.max()), float(zs.min()),
        0, 0, 0, n, *([n] + [0] * 14),
    )
    path.write_bytes(header + vlr + rec.tobytes())


LASER_BLOCKS = [round(t, 2) for t in (0.12, 0.27, 0.42, 0.57, 0.72, 0.87)]
LASER_OFFSET_BLOCK = 5  # this block is 0,32 m too high
LASER_OFFSET = 0.32


def laser_block_origin(k: int) -> tuple[int, int]:
    """Lower-left corner of laser block k (1-based), on the road centre line."""
    x, y = _centerline(LASER_BLOCKS[k - 1])
    return int(x // 10 * 10 - 50), int(y // 10 * 10 - 50)


# --- DXF ----------------------------------------------------------------------------------------

def _dxf(path: Path) -> None:
    rnd = random.Random(3)
    ents = []
    for k in range(24):
        x, y = rnd.uniform(601500, 602600), rnd.uniform(6641200, 6641900)
        layer = rnd.choice(["KUM_SPILLVANN", "KUM_OVERVANN"])
        ents += ["0", "POINT", "8", layer, "10", f"{x:.3f}", "20", f"{y:.3f}", "30", f"{rnd.uniform(108, 114):.3f}",
                 "0", "TEXT", "8", "TEKST", "10", f"{x + 0.5:.3f}", "20", f"{y + 0.5:.3f}", "30", "0.0",
                 "40", "0.5", "1", f"K{k + 1:03d}"]
    for k in range(10):
        x, y = rnd.uniform(601500, 602600), rnd.uniform(6641200, 6641900)
        ents += ["0", "LINE", "8", "SPILLVANN", "10", f"{x:.3f}", "20", f"{y:.3f}", "30", "0.0",
                 "11", f"{x + 40:.3f}", "21", f"{y + 15:.3f}", "31", "0.0"]
    header = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "6",
              "9", "$EXTMIN", "10", "601480.0", "20", "6641180.0", "30", "0.0",
              "9", "$EXTMAX", "10", "602660.0", "20", "6641920.0", "30", "0.0", "0", "ENDSEC"]
    layers = ["0", "SECTION", "2", "TABLES", "0", "TABLE", "2", "LAYER", "70", "5"]
    for name in ("0", "KUM_SPILLVANN", "KUM_OVERVANN", "SPILLVANN", "TEKST"):
        layers += ["0", "LAYER", "2", name, "70", "0", "62", "7", "6", "CONTINUOUS"]
    layers += ["0", "ENDTAB", "0", "ENDSEC"]
    body = header + layers + ["0", "SECTION", "2", "ENTITIES"] + ents + ["0", "ENDSEC", "0", "EOF"]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


# --- GeoPackage ---------------------------------------------------------------------------------

def _gpkg(path: Path) -> None:
    rnd = random.Random(5)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute("PRAGMA application_id = 1196444487")
    con.execute("PRAGMA user_version = 10300")
    con.executescript("""
    CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
      organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
    CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
      description TEXT DEFAULT '', last_change DATETIME NOT NULL, min_x DOUBLE, min_y DOUBLE, max_x DOUBLE,
      max_y DOUBLE, srs_id INTEGER);
    CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL,
      geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL);
    CREATE TABLE vannledning (fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB, dimensjon INTEGER,
      materiale TEXT, anleggsaar INTEGER);
    """)
    con.execute("INSERT INTO gpkg_spatial_ref_sys VALUES ('ETRS89 / UTM zone 32N', 25832, 'EPSG', 25832, 'undefined', NULL)")
    xs, ys = [], []
    for _ in range(40):
        x, y = rnd.uniform(600800, 603400), rnd.uniform(6640600, 6642600)
        pts = [(x, y), (x + rnd.uniform(20, 120), y + rnd.uniform(-60, 60))]
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
        wkb = struct.pack("<BII", 1, 2, len(pts)) + b"".join(struct.pack("<dd", *p) for p in pts)
        blob = b"GP" + bytes([0, 1]) + struct.pack("<i", 25832) + wkb
        con.execute("INSERT INTO vannledning (geom, dimensjon, materiale, anleggsaar) VALUES (?,?,?,?)",
                    (blob, rnd.choice([110, 160, 200, 250]), rnd.choice(["PE", "PVC", "Støpejern"]), rnd.randint(1965, 2020)))
    con.execute("INSERT INTO gpkg_geometry_columns VALUES ('vannledning','geom','LINESTRING',25832,0,0)")
    con.execute("INSERT INTO gpkg_contents VALUES ('vannledning','features','vannledning','VA-ledninger, uttak fra kommunens ledningskart',"
                "'2025-02-10T08:15:00Z',?,?,?,?,25832)", (min(xs), min(ys), max(xs), max(ys)))
    con.commit()
    con.close()


# --- PDF and delivery notes -----------------------------------------------------------------------

REPORT_TEXT = [
    "Geoteknisk datarapport - Rv 999 Nordby",
    "Oppdragsgiver: Demo Vegeier. Utført av: Demo Geo AS.",
    "Feltarbeidet ble utført i mars 2024 med borerigg Geotech 605.",
    "Koordinatsystem: EUREF89 UTM sone 32. Høyder er oppgitt i NN2000.",
    "Det er utført 14 totalsonderinger, 6 CPTU og 3 prøveserier med 54 mm stempelprøvetaker.",
    "Borpunktene er målt inn med RTK-GNSS, nøyaktighet ca. 5 cm i grunnriss og høyde.",
    "Borpunktene er vist på tegning C101. Terrengmodell_DTM2_2021.tif er brukt som terrenggrunnlag.",
    "Borpunkt BP1: N 6641320  Ø 601640  (kote 112,4)",
    "Borpunkt BP2: N 6641480  Ø 601910  (kote 114,0)",
    "Borpunkt BP3: N 6641610  Ø 602250  (kote 117,8)",
    "Løsmassene består av leire over berg. Kvikkleire er ikke påvist.",
]

DRAWING_LINES = [
    "Rv 999 Nordby - reguleringsplan",
    "Plan og profil, profil 0 - 1200",
    "Tegningsnr.: C101",
    "Målestokk 1:1000 (A1)",
    "Rev. B",
    "Dato: 15.10.2026",
    "Tegnet: KN   Kontrollert: IB   Godkjent: IB",
    "Koordinatsystem: EUREF89 UTM32 / NN2000",
    "Grunnlag: FKB_Bygning_2026.sos, Terrengmodell_DTM2_2021.tif, Laserdata_Nordby_2026",
    "Oppdragsgiver: Demo Vegeier   Utført av: Demo Rådgiver AS",
]


def _drawing_pdf(path: Path) -> None:
    """An A1 drawing: grid with coordinates, a road line and a title block."""
    from reportlab.lib.pagesizes import A1, landscape
    from reportlab.pdfgen import canvas
    w, h = landscape(A1)
    c = canvas.Canvas(str(path), pagesize=(w, h))
    c.setTitle("C101 Plan og profil")
    c.rect(40, 40, w - 80, h - 80)
    x0, y0, sx, sy = 120, 260, (w - 520) / 2000, (h - 420) / 1000  # 601000..603000, 6641000..6642000
    c.setFont("Helvetica", 14)
    for k, e in enumerate((601000, 602000, 603000)):
        x = x0 + (e - 601000) * sx
        c.line(x, y0 - 10, x, y0 + 1000 * sy)
        c.drawString(x + 4, y0 - 26, f"Ø {e}")
    for n in (6641000, 6642000):
        y = y0 + (n - 6641000) * sy
        c.line(x0 - 10, y, x0 + 2000 * sx, y)
        c.drawString(x0 + 6, y + 6, f"N {n}")
    c.setLineWidth(4)
    pts = [(601050, 6641100), (601600, 6641350), (602200, 6641600), (602900, 6641900)]
    for (a, b), (cc, d) in zip(pts, pts[1:]):
        c.line(x0 + (a - 601000) * sx, y0 + (b - 6641000) * sy, x0 + (cc - 601000) * sx, y0 + (d - 6641000) * sy)
    c.setLineWidth(1)
    bx, by = w - 760, 60
    c.rect(bx, by, 700, 300)
    c.setFont("Helvetica", 16)
    for i, line in enumerate(DRAWING_LINES):
        c.drawString(bx + 14, by + 276 - i * 27, line)
    c.save()


IFC_TEMPLATE = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');
FILE_NAME('VA_modell_Nordby.ifc','2026-10-28T14:20:00',('Ola Hansen'),('Demo VA AS'),'IFC4 export','Demo BIM 2026','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0aB1',$,'Rv 999 Nordby VA',$,$,$,$,(#10),#5);
#5=IFCUNITASSIGNMENT((#6));
#6=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#11,$);
#11=IFCAXIS2PLACEMENT3D(#12,$,$);
#12=IFCCARTESIANPOINT((0.,0.,0.));
#20=IFCPROJECTEDCRS('EPSG:25832','EUREF89 UTM32',$,'NN2000',$,$,$);
#21=IFCMAPCONVERSION(#10,#20,601500.,6641200.,0.,1.,0.,1.);
#30=IFCSITE('0aB2',$,'Nordby',$,$,$,$,$,.ELEMENT.,$,$,$,$,$);
{body}
ENDSEC;
END-ISO-10303-21;
"""


def _ifc(path: Path) -> None:
    rnd = random.Random(11)
    lines, n = [], 100
    def point(x, y, z):
        nonlocal n
        n += 1
        lines.append(f"#{n}=IFCCARTESIANPOINT(({x:.3f},{y:.3f},{z:.3f}));")
        return n
    for k in range(24):
        x, y = rnd.uniform(0, 1100), rnd.uniform(0, 700)
        point(x, y, 108.0)
        n += 1
        lines.append(f"#{n}=IFCPIPESEGMENT('p{k:03d}',$,'Spillvann {k + 1}',$,$,$,$,$,.RIGIDSEGMENT.);")
    for k in range(8):
        x, y = rnd.uniform(0, 1100), rnd.uniform(0, 700)
        point(x, y, 110.0)
        n += 1
        lines.append(f"#{n}=IFCDISTRIBUTIONCHAMBERELEMENT('k{k:03d}',$,'Kum K{k + 1:03d}',$,$,$,$,$,.MANHOLE.);")
    for k in range(12):
        n += 1
        lines.append(f"#{n}=IFCPIPEFITTING('f{k:03d}',$,'Bend {k + 1}',$,$,$,$,$,.BEND.);")
    point(0, 0, 100.0)
    point(1100, 700, 120.0)
    path.write_text(IFC_TEMPLATE.replace("{body}", "\n".join(lines)), encoding="utf-8")

LASER_NOTE = """Leveransenotat - laserdata Rv 999 Nordby
Levert av: Demo Survey AS
Skannet: 14.09.2026 (droneskanning)
Punkttetthet: ca. 5 pkt/m2
Nøyaktighet: +/- 5 cm i høyde, kontrollert mot 12 kontrollpunkter
Koordinatsystem: EUREF89 UTM32, høyder NN2000
Leveransen består av 6 blokker à 100 x 100 m langs planlagt veglinje.
"""


def _pdf(path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Geoteknisk datarapport Rv 999 Nordby")
    c.setAuthor("Demo Geo AS")
    y = 800
    for line in REPORT_TEXT:
        c.drawString(60, y, line)
        y -= 22
    c.showPage()
    c.drawString(60, 800, "Vedlegg: borplan og borprofiler (ikke vist i demo).")
    c.save()


# --- The deliveries ------------------------------------------------------------------------------

LASER_FOLDER = "Laserdata_Nordby_2026"


def _write_all(folder: Path) -> None:
    _sosi(folder / "FKB_Bygning_2025.sos", 22, 25832, "FKB-Bygning 5.0", "Bygning", "20240612", 40, 1)
    _geotiff(folder / "Terrengmodell_DTM2_2021.tif", _dtm(2.0, False, 0.0, 0), BBOX[0], BBOX[3], 2.0, 25832,
             "2021:06:20 00:00:00", artist="Kartverket", vertical=5941)
    _sosi(folder / "FKB_Bygning_2026.sos", 22, 25832, "FKB-Bygning 5.0", "Bygning", "20260320", 46, 11)
    _sosi(folder / "FKB_Veg_2026.sos", 23, 25833, "FKB-Veg 4.6", "Vegkant", "20250905", 30, 2)
    _geotiff(folder / "Ortofoto_2023_tile_0603.tif", _ortho(1000, 1000, 1), 601000, 6641800, 0.25, 25832,
             "2023:07:02 11:30:00", artist="Demo Flyfoto AS")
    _geotiff(folder / "Ortofoto_2009.tif", _ortho(600, 600, 2), 601500, 6641500, 0.5, None,
             "2009:08:14 09:00:00", world_file=True)
    (folder / "Ortofoto_2009.prj").write_text(PRJ_25833)
    for k in range(1, len(LASER_BLOCKS) + 1):
        x0, y0 = laser_block_origin(k)
        _las(folder / f"{LASER_FOLDER}_blokk{k}.las", x0, y0, 100, 5, WKT_25832_NN2000, 2026, 260, seed=20 + k,
             dz=LASER_OFFSET if k == LASER_OFFSET_BLOCK else 0.0)
    (folder / "Leveransenotat_laserdata.txt").write_text(LASER_NOTE, encoding="utf-8")
    _geotiff(folder / "Terrengmodell_DTM2_2026.tif", _dtm(2.0, True, 0.02, 7), BBOX[0], BBOX[3], 2.0, None,
             "2026:10:20 00:00:00")
    _dxf(folder / "Innmaaling_kummer.dxf")
    _gpkg(folder / "Ledninger_VA.gpkg")
    _pdf(folder / "Grunnundersokelse_datarapport.pdf")
    _drawing_pdf(folder / "C101_Plan_og_profil.pdf")
    _ifc(folder / "VA_modell_Nordby.ifc")


def _ts(month: int, day: int, hour: int) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


def deliveries(folder: Path) -> list[dict]:
    """How the sample files were delivered: who, when, which delivery and folder."""
    def item(name: str, who: dict, delivery: str, when: datetime, sub: str = "") -> dict:
        return {"filename": name, "path": folder / name, "project_id": PROJECT_ID, "uploaded_by": who,
                "uploaded_at": when, "delivery_id": delivery, "folder": sub}

    laser_when = _ts(10, 29, 14)
    out = [
        item("FKB_Bygning_2025.sos", KARI, "D-090", _ts(9, 2, 8)),
        item("Terrengmodell_DTM2_2021.tif", KARI, "D-091", _ts(9, 8, 10)),
        item("FKB_Bygning_2026.sos", KARI, "D-101", _ts(10, 27, 8)),
        item("FKB_Veg_2026.sos", KARI, "D-101", _ts(10, 27, 8)),
        item("Ortofoto_2023_tile_0603.tif", KARI, "D-102", _ts(10, 28, 10)),
        item("Ortofoto_2009.tif", KARI, "D-102", _ts(10, 28, 10)),
        item("Ortofoto_2009.tfw", KARI, "D-102", _ts(10, 28, 10)),
        item("Ortofoto_2009.prj", KARI, "D-102", _ts(10, 28, 10)),
    ]
    out += [item(f"{LASER_FOLDER}_blokk{k}.las", KARI, "D-103", laser_when, LASER_FOLDER)
            for k in range(1, len(LASER_BLOCKS) + 1)]
    out += [
        item("Leveransenotat_laserdata.txt", KARI, "D-103", laser_when, LASER_FOLDER),
        item("Terrengmodell_DTM2_2026.tif", OLA, "D-104", _ts(10, 30, 9)),
        item("Innmaaling_kummer.dxf", OLA, "D-104", _ts(10, 30, 9)),
        item("Ledninger_VA.gpkg", OLA, "D-105", _ts(10, 31, 13)),
        item("Grunnundersokelse_datarapport.pdf", OLA, "D-106", _ts(10, 31, 15)),
        item("C101_Plan_og_profil.pdf", OLA, "D-107", _ts(11, 2, 9)),
        item("VA_modell_Nordby.ifc", OLA, "D-107", _ts(11, 2, 9)),
    ]
    return out


def build_samples(folder: Path) -> list[dict]:
    """Write the sample files into `folder` (once) and describe how they were delivered."""
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / ".samples_version"
    if not marker.exists() or marker.read_text() != SAMPLES_VERSION:
        _write_all(folder)
        marker.write_text(SAMPLES_VERSION)
    return deliveries(folder)
