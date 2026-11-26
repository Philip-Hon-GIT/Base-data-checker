"""Build the self-contained demo page from real checker output.

Runs the checker on the synthetic deliveries, records every API answer the interface needs, and
pre-computes the re-check for each possible answer to each open question (free-text answers use a
placeholder that the page swaps for what the viewer types). The page then runs without a server.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .. import db as dblib
from .. import service
from ..questions import templates
from ..worker import make_context
from . import BANNER, REVIEWER, USERS, build_demo

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
TEXT_TOKEN = "DEMOTOKENANSWER"
DATE_TOKENS = ["2024-02", "2023-11", "2022-06"]
FONTS = ("https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600"
         "&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap")


DEMO_FOLDER = r"C:\Users\deg\OneDrive - Multiconsult\Rv 999 Nordby\Grunnlagsdata"


def _detail(ctx, entry_id: str) -> dict:
    d = service.entry_detail(ctx, REVIEWER, entry_id)
    d.pop("permissions", None)
    for f in d.get("files") or []:
        f["link"] = None  # the page has no server to open files from
    return d


def _preview(ctx, q: dict, answer: str) -> dict:
    db2 = copy.deepcopy(ctx.db)
    ctx2 = make_context(db2, ctx.settings, now=ctx.now)
    uploader = next((u for u in USERS if u["email"] == q.get("uploader_email")), REVIEWER)
    service.answer_question(ctx2, uploader, q["_id"], answer)
    return _detail(ctx2, q["entry_id"])


def _date_token(text: str) -> str:
    """A date that appears nowhere else in the data, so the page can swap it for the typed date."""
    for token in DATE_TOKENS:
        if token not in text:
            return token
    raise RuntimeError("No free date token for the demo previews.")


def demo_state() -> dict:
    """Everything the demo page needs, as plain JSON-ready data."""
    ctx = build_demo()
    dk = templates()["dont_know"]
    projects = service.list_projects(ctx, REVIEWER)
    details = {e["_id"]: _detail(ctx, e["_id"]) for e in ctx.db[dblib.ENTRIES].find({})}
    all_text = json.dumps(service.jsonable(details), ensure_ascii=False)
    previews = {}
    for q in ctx.db[dblib.QUESTIONS].find({"status": "open"}):
        item: dict = {"choices": {}, "text": None, "token": None}
        for choice in q.get("choices") or []:
            item["choices"][choice] = _preview(ctx, q, choice)
        if not [c for c in q.get("choices") or [] if c != dk]:
            token = _date_token(all_text) if q["field"] == "data_date" else TEXT_TOKEN
            item["text"], item["token"] = _preview(ctx, q, token), token
        previews[q["_id"]] = item
    settings = {}
    for p in projects:
        s = service.get_settings(ctx, REVIEWER, p["id"])
        s.pop("can_edit", None)
        s["source_folder"] = DEMO_FOLDER  # not the build machine's temporary folder
        settings[p["id"]] = s
    rules = {}
    for p in projects:
        r = service.get_rules(ctx, REVIEWER, p["id"])
        r.pop("can_edit", None)
        rules[p["id"]] = r
    texts = {}
    for f in ctx.db[dblib.FILES].find({}):
        items = texts.setdefault(f.get("entry_id"), [])
        if (f.get("metadata") or {}).get("text_excerpt"):
            items.append({"name": f["file_name"], "text": f["metadata"]["text_excerpt"][:5000]})
        for t in f.get("context_texts") or []:
            if t.get("name") != f["file_name"] and not any(x["name"] == t["name"] for x in items):
                items.append({"name": t["name"], "text": (t.get("text") or "")[:5000]})
    return service.jsonable({
        "texts": texts,
        "users": USERS, "banner": BANNER, "options": service.options({}), "projects": projects,
        "details": details, "settings": settings, "rules": rules,
        "notifications": [{"id": n["_id"], **{k: n.get(k) for k in ("to", "subject", "body", "link", "kind", "created_at")}}
                          for n in ctx.db[dblib.NOTIFICATIONS].find({})],
        "previews": previews,
    })


def build(out: Path) -> Path:
    """Write the demo page (an Artifact-ready HTML fragment with inlined CSS, JS and data)."""
    state = demo_state()
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    data = json.dumps(state, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = "\n".join([
        "<title>Base Data Checker</title>",
        '<meta name="claude:viewport-fit-sides" content="cover">',
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        f'<link rel="stylesheet" href="{FONTS}">',
        f"<style>\n{css}\n</style>",
        '<div id="app"><p style="padding:40px 16px">Laster grunnlagsdataregisteret…</p></div>',
        f"<script>window.BASEDATA_DEMO = {data};</script>",
        f"<script>\n{js}\n</script>",
    ])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
