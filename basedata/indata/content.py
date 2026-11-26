"""What a file contains, described the same way for every data type.

A content profile has a fixed shape so the pages can show every registration the same way:
    {kind, label, summary, facts: [[label, value], ...], keywords, mentions: {files, drawings},
     georef: how the location is known (or None), drawing_no}
Facts are type-specific (scale for a drawing, classes for a point cloud, element counts for a model),
but always a short list of label/value pairs. The summary is one sentence.
"""

from __future__ import annotations

from basedata.core.classify import DATA_TYPES
from basedata.indata.crs import short_name
from basedata.core.text import area, nb

ASPRS = {1: "uklassifisert", 2: "bakke", 3: "lav vegetasjon", 4: "middels vegetasjon", 5: "høy vegetasjon",
         6: "bygning", 7: "støy", 9: "vann", 17: "bru"}

KIND_LABELS = {
    "drawing_pdf": "Tegning (PDF)", "drawing_cad": "CAD-tegning", "report": "Rapport", "document": "Tekstdokument",
    "model": "BIM-modell", "terrain": "Terrengmodell", "point_cloud": "Punktsky", "orthophoto": "Ortofoto",
    "map": "Kartdata", "network": "Ledningsnett", "other": "Annet",
}


def _extent_area(md: dict) -> float | None:
    e = md.get("extent")
    if not e:
        return None
    return max(0.0, (e["maxx"] - e["minx"]) * (e["maxy"] - e["miny"]))


def _georef(md: dict, epsg: int | None) -> str | None:
    d = md.get("details") or {}
    if not md.get("extent"):
        return None
    how = d.get("georef_from") or {"GeoTIFF keys": "GeoTIFF-nøkler", "WKT-post": "LAS-header"}.get(d.get("crs_from"), "koordinater i fila")
    return f"{how}, {short_name(epsg)}" if epsg else f"{how} (koordinatsystem ukjent)"


def file_profile(file_name: str, md: dict, data_type: str, epsg: int | None = None) -> dict:
    """The content profile for one file."""
    d = md.get("details") or {}
    q = md.get("quality") or {}
    sc = d.get("scan") or {}
    fmt = (md.get("format") or "").upper()
    epsg = epsg if epsg is not None else md.get("horizontal_epsg")
    facts: list[list[str]] = []
    kind, summary = "other", ""
    keywords = list(sc.get("keywords") or [])
    a = _extent_area(md)

    if fmt == "PDF" and d.get("pdf_kind") == "drawing":
        kind = "drawing_pdf"
        title = d.get("title") or (sc.get("headings") or [None])[0]
        if title and d.get("drawing_no") and title.upper().startswith(d["drawing_no"]):
            title = title[len(d["drawing_no"]):].strip(" -–:")
        for label, key in (("Tegningsnr.", "drawing_no"), ("Målestokk", "scale"), ("Ark", "paper"), ("Revisjon", "revision")):
            if d.get(key):
                facts.append([label, str(d[key])])
        bits = [f"Tegning {d['drawing_no']}" if d.get("drawing_no") else "Tegning"]
        if title:
            bits.append(f"«{title}»")
        if d.get("scale"):
            bits.append(f"i {d['scale']} på {str(d.get('paper', '')).split(' ')[0]}")
        summary = " ".join(bits) + "."
        if md.get("extent") and epsg:
            summary += f" Georeferert med koordinater i tegningen ({short_name(epsg)})."
        elif not md.get("extent"):
            summary += " Har ingen lesbare koordinater."
    elif fmt == "PDF":
        kind = "report" if data_type == "ground_investigation" or len(sc.get("headings") or []) >= 2 else "document"
        title = d.get("title") or (sc.get("headings") or [None])[0]
        facts.append(["Sider", nb(md.get("count") or 0, 0)])
        facts.append(["Ord", nb(d.get("words") or 0, 0)])
        if d.get("author"):
            facts.append(["Forfatter", d["author"]])
        if sc.get("headings"):
            facts.append(["Overskrifter", ", ".join(sc["headings"][:4])])
        n_coord = len(sc.get("points") or []) or (1 if md.get("extent") else 0)
        summary = f"{KIND_LABELS[kind]} på {nb(md.get('count') or 0, 0)} sider" + (f": «{title}»" if title else "") + "."
        if md.get("extent"):
            summary += " Inneholder koordinater som plasserer innholdet."
        elif n_coord == 0 and epsg:
            summary += f" Oppgir {short_name(epsg)}, men har ingen koordinater."
    elif fmt == "IFC":
        kind = "model"
        el = d.get("elements") or {}
        facts.append(["Skjema", md.get("format_version") or "ukjent"])
        if d.get("ifc_project"):
            facts.append(["Prosjekt i modellen", d["ifc_project"]])
        if d.get("software"):
            facts.append(["Programvare", d["software"]])
        facts.append(["Georeferanse", d.get("georef_from") or "mangler (lokale koordinater)"])
        if el:
            facts.append(["Objekter", ", ".join(f"{nb(n, 0)} {k}" for k, n in list(el.items())[:4])])
        summary = f"{md.get('format_version') or 'IFC'}-modell med {nb(md.get('count') or 0, 0)} objekter"
        summary += (f" ({', '.join(f'{nb(n, 0)} {k}' for k, n in list(el.items())[:3])})" if el else "") + ". "
        summary += (f"Georeferert med {d['georef_from']} til {short_name(epsg)}." if d.get("georef_from") and epsg
                    else "Ligger i lokale koordinater.")
        keywords = list(el.keys())[:6]
    elif fmt == "DXF":
        kind = "drawing_cad"
        layers = [x for x in (d.get("layers") or []) if x not in ("0", "Defpoints")]
        ents = d.get("entities") or {}
        facts.append(["Lag", f"{len(layers)}: {', '.join(layers[:5])}" if layers else "ingen"])
        facts.append(["Elementer", ", ".join(f"{nb(n, 0)} {k.lower()}" for k, n in list(ents.items())[:4]) or "–"])
        if q.get("units"):
            facts.append(["Enheter", q["units"]])
        summary = f"CAD-tegning med {nb(md.get('count') or 0, 0)} elementer i {len(layers)} lag"
        summary += (f" ({', '.join(layers[:3])})" if layers else "") + "."
        keywords = [x.lower() for x in layers[:6]]
    elif data_type == "terrain":
        kind = "terrain"
        if q.get("pixel_size_m"):
            facts.append(["Rutenett", f"{nb(q['pixel_size_m'], 0 if q['pixel_size_m'] >= 1 else 1)} m"])
        if q.get("width_px"):
            facts.append(["Størrelse", f"{nb(q['width_px'], 0)} × {nb(q['height_px'], 0)} celler"])
        if a:
            facts.append(["Areal", area(a)])
        summary = f"Terrengmodell som rutenett{(' på ' + nb(q['pixel_size_m'], 0) + ' m') if q.get('pixel_size_m') else ''}" \
                  + (f" over {area(a)}" if a else "") + "."
    elif data_type == "point_cloud":
        kind = "point_cloud"
        classes = q.get("classes_sampled") or {}
        names = [ASPRS.get(int(k), f"klasse {k}") for k in classes]
        facts.append(["Punkter", nb(md.get("count") or 0, 0)])
        if q.get("density_pts_per_m2"):
            facts.append(["Tetthet", f"{nb(q['density_pts_per_m2'], 1)} pkt/m²"])
        if names:
            facts.append(["Klasser", ", ".join(dict.fromkeys(names))])
        if d.get("z_range"):
            facts.append(["Høyder", f"{nb(d['z_range'][0], 1)}–{nb(d['z_range'][1], 1)} m"])
        summary = f"Punktsky med {nb(md.get('count') or 0, 0)} punkter" \
                  + (f", {nb(q['density_pts_per_m2'], 1)} pkt/m²" if q.get("density_pts_per_m2") else "") \
                  + (", klassifisert" if len(classes) > 1 else ", ikke klassifisert") + "."
        keywords = list(dict.fromkeys(names))
    elif data_type == "orthophoto":
        kind = "orthophoto"
        if q.get("pixel_size_m"):
            facts.append(["Piksel", f"{nb(q['pixel_size_m'])} m"])
        if q.get("bands"):
            facts.append(["Bånd", f"{q['bands']} ({q.get('dtype', '')})"])
        if a:
            facts.append(["Areal", area(a)])
        summary = f"Ortofoto med {nb(q.get('pixel_size_m') or 0)} m piksler" + (f" over {area(a)}" if a else "") + "."
    else:
        kind = "network" if data_type == "utility" else "map"
        objtypes = d.get("top_objtypes") or {}
        layers = d.get("layers") if isinstance(d.get("layers"), list) else []
        if q.get("product_spec"):
            facts.append(["Produkt", q["product_spec"]])
        if objtypes:
            facts.append(["Objekttyper", ", ".join(f"{k} ({nb(n, 0)})" for k, n in list(objtypes.items())[:4])])
        elif layers and isinstance(layers[0], dict):
            facts.append(["Lag", ", ".join(f"{x['name']} ({nb(x.get('features') or 0, 0)})" for x in layers[:4])])
        if q.get("accuracy_cm"):
            facts.append(["Nøyaktighet", f"median {nb(q['accuracy_cm']['median'], 0)} cm"])
        what = q.get("product_spec") or DATA_TYPES.get(data_type, "Kartdata")
        summary = f"{what} med {nb(md.get('count') or 0, 0)} objekter" \
                  + (f" ({', '.join(list(objtypes)[:3])})" if objtypes else
                     (f" ({', '.join(x['name'] for x in layers[:3])})" if layers and isinstance(layers[0], dict) else "")) + "."
        keywords = [k.lower() for k in list(objtypes)[:6]] or [x["name"] for x in layers[:6] if isinstance(x, dict)]

    return {"kind": kind, "label": KIND_LABELS[kind], "summary": summary, "facts": facts[:6],
            "keywords": keywords[:8], "drawing_no": d.get("drawing_no"),
            "mentions": {"files": list(sc.get("file_mentions") or []), "drawings": list(sc.get("drawing_mentions") or [])},
            "georef": _georef(md, epsg), "text_excerpt": (md.get("text_excerpt") or "")[:600] or None}


def entry_profile(entry: dict, files: list[dict]) -> dict:
    """One profile for a registration: the file's own, or a summary across a package."""
    profiles = [f.get("content") or file_profile(f["file_name"], f.get("metadata") or {}, f.get("data_type") or "other")
                for f in files]
    if not profiles:
        return {"kind": "other", "label": "Annet", "summary": "", "facts": [], "keywords": [], "mentions": {}}
    if entry.get("kind") != "package" or len(profiles) == 1:
        return profiles[0]
    first = profiles[0]
    pts = sum((f.get("metadata") or {}).get("count") or 0 for f in files
              if (f.get("metadata") or {}).get("count_label") == "points")
    a = sum(_extent_area(f.get("metadata") or {}) or 0 for f in files)
    facts = [["Filer", nb(len(files), 0)]]
    if pts:
        facts.append(["Punkter", nb(pts, 0)])
    if a:
        facts.append(["Areal", f"ca. {area(a)}"])
    facts += [f for f in first["facts"] if f[0] not in ("Punkter", "Areal", "Høyder")][:3]
    notes = sorted({n for f in files for n in f.get("delivery_notes") or []})
    if notes:
        facts.append(["Leveransenotat", ", ".join(notes)])
    summary = f"Pakke med {len(files)} filer: {first['label'].lower()}" + (f", til sammen {nb(pts, 0)} punkter" if pts else "") \
              + (f" over ca. {area(a)}" if a else "") + "."
    mentions = {"files": sorted({m for p in profiles for m in p["mentions"].get("files", [])}),
                "drawings": sorted({m for p in profiles for m in p["mentions"].get("drawings", [])})}
    return {**first, "summary": summary, "facts": facts[:6], "mentions": mentions}
