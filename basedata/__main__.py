"""Kommandolinje.

    python -m basedata start MAPPE     les grunnlagsdata i MAPPE og åpne appen på http://127.0.0.1:8000/basedata/
    python -m basedata run --folder MAPPE   les MAPPE én gang og oppdater registeret (uten nettleser)
    python -m basedata reminders --folder MAPPE   lag purringer på spørsmål som har stått åpne for lenge
    python -m basedata demo            demo med syntetiske data (ingenting lagres)
    python -m basedata build-demo UT   skriv den frittstående demosiden til UT
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="basedata", description="Base data checker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="start the web demo with synthetic data")
    d.add_argument("--port", type=int, default=8000)
    st = sub.add_parser("start", help="les en mappe med grunnlagsdata og åpne appen")
    st.add_argument("folder", type=Path, nargs="?", help="mappa med grunnlagsdata (lokal eller OneDrive)")
    st.add_argument("--store", type=Path, help="SQLite-fila med registeret (standard: MAPPE/_basedata/register.db)")
    st.add_argument("--port", type=int, default=8000)
    st.add_argument("--project", help="prosjekt-ID (standard: ut fra mappenavnet)")
    st.add_argument("--name", help="prosjektnavn første gang (standard: mappenavnet)")
    st.add_argument("--no-browser", action="store_true", help="ikke åpne nettleseren")
    r = sub.add_parser("run", help="les mappa én gang og oppdater registeret")
    r.add_argument("--folder", type=Path)
    r.add_argument("--store", type=Path)
    r.add_argument("--project")
    r.add_argument("--force", action="store_true", help="kontroller alle filer på nytt, også uendrede")
    rem = sub.add_parser("reminders", help="purr på spørsmål som har stått åpne for lenge")
    rem.add_argument("--folder", type=Path)
    rem.add_argument("--store", type=Path)
    b = sub.add_parser("build-demo", help="write the self-contained demo page")
    b.add_argument("out", type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "demo":
        import uvicorn
        from starlette.applications import Starlette
        from starlette.responses import RedirectResponse
        from starlette.routing import Mount, Route

        from basedata.selfcheck.demo import BANNER, USERS, build_demo
        from basedata.ui.web.app import create_app, demo_user_from_cookie

        ctx = build_demo()
        inner = create_app(lambda: ctx, demo_user_from_cookie(USERS), demo_users=USERS, banner=BANNER)
        app = Starlette(routes=[Route("/", lambda request: RedirectResponse("/basedata/")), Mount("/basedata", inner)])
        print(f"Base data checker demo: http://127.0.0.1:{args.port}/basedata/")
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        return 0

    if args.cmd == "build-demo":
        from basedata.selfcheck.demo.build_artifact import build

        build(args.out)
        print(f"Wrote {args.out}")
        return 0

    from basedata.core import db as dblib
    from basedata.ui.local import ensure_project, local_user, start_scanner
    from basedata.core.settings import Settings
    from basedata.harness.worker import make_context, run_once

    settings = Settings.from_env()
    if getattr(args, "folder", None):
        settings.source_folder = str(args.folder.expanduser().resolve())
    if getattr(args, "store", None):
        settings.store_path = str(args.store.expanduser().resolve())
    if not settings.source_folder and not settings.store_path:
        parser.error("oppgi mappa med grunnlagsdata, for eksempel: python -m basedata start \"C:\\Prosjekt\\Grunnlagsdata\"")
    if settings.source_folder and not Path(settings.source_folder).is_dir():
        parser.error(f"fant ikke mappa {settings.source_folder}")
    database = dblib.connect(settings)
    project = ensure_project(database, Path(settings.source_folder), getattr(args, "project", None),
                             getattr(args, "name", None)) if settings.source_folder else None
    ctx = make_context(database, settings)
    print(f"Registeret lagres i {settings.resolved_store_path()}")

    if args.cmd == "start":
        import uvicorn
        import webbrowser
        from starlette.applications import Starlette
        from starlette.responses import RedirectResponse
        from starlette.routing import Mount, Route

        from basedata.ui.web.app import create_app

        if project:
            print(f"Prosjekt «{project['name']}» ({project['_id']}): leser {project['source_folder']} …")
        first = run_once(ctx, trigger="start", project_id=getattr(args, "project", None))
        c = first.get("counts") or {}
        print(f"Ferdig: {c.get('new', 0)} nye filer, {c.get('new version', 0)} nye versjoner, "
              f"{c.get('skipped', 0)} uendret, {c.get('errors', 0)} feil.")
        for err in first.get("errors") or []:
            print(f"  Feil: {err['file']}: {err['error']}")
        start_scanner(ctx, settings.scan_minutes)
        user = local_user(settings)
        inner = create_app(lambda: ctx, lambda request: user)
        app = Starlette(routes=[Route("/", lambda request: RedirectResponse("/basedata/")), Mount("/basedata", inner)])
        url = f"http://127.0.0.1:{args.port}/basedata/"
        print(f"Åpne {url}  (stopp med Ctrl+C)")
        if not args.no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        return 0
    if args.cmd == "run":
        result = run_once(ctx, trigger="manual", project_id=args.project, force=args.force)
        print(json.dumps({k: result.get(k) for k in ("counts", "errors", "questions_created")}, default=str, indent=2))
        return 1 if result.get("counts", {}).get("errors") else 0
    if args.cmd == "reminders":
        from basedata.harness.notify import send_reminders

        n = send_reminders(database, settings, ctx.notifier, ctx.now())
        print(f"Laget purringer til {n} opplaster(e). De vises under Varsler i appen.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
