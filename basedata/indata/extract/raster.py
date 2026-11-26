"""Rasters: orthophotos and terrain grids (GeoTIFF, TIFF + world file, and others via rasterio).

GeoTIFF tags are read directly with tifffile, so no GDAL is needed for the common case. Other raster
formats (JPEG2000, ECW, ...) are read with rasterio when it is installed.
"""

from __future__ import annotations

import re
from pathlib import Path

from basedata.indata import crs as crslib
from basedata.indata.extract.common import FileMetadata, iso_date, read_prj, sidecar

try:
    import tifffile  # type: ignore
except ImportError:  # pragma: no cover
    tifffile = None
try:
    import rasterio  # type: ignore
except ImportError:  # pragma: no cover
    rasterio = None

_PROJECTED_CS = 3072
_GEOGRAPHIC_CS = 2048
_VERTICAL_CS = 4096
_CITATION = 1026


def _geokeys(tags) -> tuple[dict[int, object], str]:
    """Decode the GeoKeyDirectory into {key id: value}."""
    if 34735 not in tags:
        return {}, ""
    d = [int(v) for v in tags[34735].value]
    ascii_params = str(tags[34737].value) if 34737 in tags else ""
    doubles = list(tags[34736].value) if 34736 in tags else []
    keys: dict[int, object] = {}
    for n in range(d[3]):
        key, loc, count, value = d[4 + n * 4: 8 + n * 4]
        if loc == 0:
            keys[key] = value
        elif loc == 34737:
            keys[key] = ascii_params[value: value + count].rstrip("|")
        elif loc == 34736:
            keys[key] = doubles[value: value + count]
    return keys, ascii_params


def _read_tiff(path: Path, md: FileMetadata) -> None:
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        tags = page.tags
        width, height = page.imagewidth, page.imagelength
        md.format_version = "GeoTIFF" if 34735 in tags else "TIFF"
        md.quality.update({"bands": page.samplesperpixel, "bits": page.bitspersample,
                           "dtype": str(page.dtype), "width_px": width, "height_px": height})
        md.details["compression"] = str(getattr(page.compression, "name", page.compression))
        if 42113 in tags:
            md.quality["nodata"] = str(tags[42113].value).strip("\x00")

        keys, _ = _geokeys(tags)
        epsg = None
        for key in (_PROJECTED_CS, _GEOGRAPHIC_CS):
            v = keys.get(key)
            if isinstance(v, int) and v not in (0, 32767):
                epsg = v
                break
        if epsg is None and isinstance(keys.get(_CITATION), str):
            epsg = crslib.parse_wkt(keys[_CITATION])[0]
        if epsg:
            md.horizontal_epsg = epsg
            md.details["crs_from"] = "GeoTIFF keys"
        v = keys.get(_VERTICAL_CS)
        if isinstance(v, int) and v in crslib.VERTICAL:
            md.height_reference = crslib.VERTICAL[v]

        if 33550 in tags and 33922 in tags:
            sx, sy = tags[33550].value[:2]
            i, j, _, x, y, _ = tags[33922].value[:6]
            minx, maxy = x - i * sx, y + j * sy
            md.extent = {"minx": minx, "miny": maxy - height * sy, "maxx": minx + width * sx, "maxy": maxy}
            md.quality["pixel_size_m"] = round(float(sx), 4)
        elif 34264 in tags:
            m = tags[34264].value
            sx, sy, x, y = m[0], -m[5], m[3], m[7]
            md.extent = {"minx": x, "miny": y - height * sy, "maxx": x + width * sx, "maxy": y}
            md.quality["pixel_size_m"] = round(float(sx), 4)

        raw_date = tags[306].value if 306 in tags else None
        if 42112 in tags:
            gm = str(tags[42112].value)
            m = re.search(r'name="(?:TIFFTAG_DATETIME|ACQUISITIONDATE|DATE)"[^>]*>([^<]+)<', gm, re.I)
            if m:
                raw_date = m.group(1)
        if raw_date:
            md.data_date = iso_date(raw_date)
            md.data_date_kind = "datotagg i fila – ofte prosesseringsdato, ikke fotodato"
        if 270 in tags:
            md.details["description"] = str(tags[270].value)[:300]
        if 315 in tags:
            md.source = str(tags[315].value).strip()


def _read_world_file(path: Path, md: FileMetadata, width: int, height: int) -> None:
    wf = sidecar(path, ".tfw", ".tifw", ".wld", ".j2w", ".jgw")
    if not wf:
        return
    vals = [float(v) for v in wf.read_text().split()[:6]]
    a, _, _, e, c, f = vals
    minx, maxy = c - a / 2, f - e / 2
    md.extent = {"minx": minx, "miny": maxy + e * height, "maxx": minx + a * width, "maxy": maxy}
    md.quality["pixel_size_m"] = round(abs(a), 4)
    md.details["georef_from"] = wf.name


def _read_aux_xml(path: Path, md: FileMetadata) -> None:
    aux = sidecar(path, ".aux.xml")
    if not aux or md.horizontal_epsg:
        return
    m = re.search(r"<SRS[^>]*>(.*?)</SRS>", aux.read_text(errors="replace"), re.S)
    if m:
        epsg, height = crslib.parse_wkt(m.group(1).replace("&quot;", '"'))
        md.horizontal_epsg = md.horizontal_epsg or epsg
        md.height_reference = md.height_reference or height


def _read_rasterio(path: Path, md: FileMetadata) -> None:
    with rasterio.open(path) as ds:
        md.format_version = ds.driver
        if ds.crs:
            md.horizontal_epsg = ds.crs.to_epsg()
        b = ds.bounds
        md.extent = {"minx": b.left, "miny": b.bottom, "maxx": b.right, "maxy": b.top}
        md.quality.update({"pixel_size_m": round(abs(ds.res[0]), 4), "bands": ds.count,
                           "dtype": ds.dtypes[0], "nodata": ds.nodata, "width_px": ds.width, "height_px": ds.height})
        d = ds.tags().get("TIFFTAG_DATETIME")
        if d:
            md.data_date, md.data_date_kind = iso_date(d), "datotagg i fila"


def read(path: Path) -> FileMetadata:
    """Read raster metadata: CRS, extent, pixel size, bands, date."""
    md = FileMetadata(format="Raster")
    ext = path.suffix.lower()
    if ext in (".tif", ".tiff") and tifffile is not None:
        md.format = "GeoTIFF"
        _read_tiff(path, md)
        if md.extent is None:
            _read_world_file(path, md, md.quality.get("width_px", 0), md.quality.get("height_px", 0))
    elif rasterio is not None:
        _read_rasterio(path, md)
    else:
        md.note(f"Lesing av {ext}-raster krever rasterio, som ikke er installert.")
        return md
    if md.horizontal_epsg is None:
        read_prj(path, md)
        _read_aux_xml(path, md)
    if md.horizontal_epsg is None:
        md.note("Ingen koordinatsystem i fila eller tilhørende filer (.prj, .aux.xml).")
    if md.extent is None:
        md.note("Fant ingen georeferanse (verken GeoTIFF-nøkler eller world-fil).")
    bands, dtype = md.quality.get("bands"), md.quality.get("dtype", "")
    if bands == 1 and "float" in dtype:
        md.details["raster_kind"] = "elevation grid"
    elif bands in (3, 4) and dtype == "uint8":
        md.details["raster_kind"] = "image (RGB)"
    if md.extent:
        md.count = int(md.quality.get("width_px", 0)) * int(md.quality.get("height_px", 0)) or None
        md.count_label = "pixels"
    return md
