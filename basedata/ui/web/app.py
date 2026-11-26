"""The web layer: a Starlette app with a JSON API and the single-page interface.

Mount it in the host app, for example in FastAPI:

    from basedata.ui.web.app import create_app
    app.mount("/basedata", create_app(get_context, get_user))

`get_context()` returns a basedata.harness.worker.Context; `get_user(request)` returns the logged-in user as
{"name", "email", "roles"} (or None), using the host app's own login.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from basedata.ui import service
from basedata.ui.export_excel import export_project
from basedata.harness.questions import AnswerError

STATIC = Path(__file__).resolve().parent / "static"


def create_app(get_context: Callable[[], object], get_user: Callable[[Request], dict | None],
               demo_users: list[dict] | None = None, banner: str = "") -> Starlette:
    """Build the module's ASGI app. `demo_users` enables the user switcher (demo only)."""

    def user_or_401(request: Request) -> dict:
        user = get_user(request)
        if not user:
            raise PermissionError("Du er ikke logget inn.")
        return user

    def api(fn):
        """Wrap a blocking handler: log-in check, JSON body, errors as JSON, run in a worker thread."""
        async def endpoint(request: Request):
            try:
                user = user_or_401(request)
                body = await request.json() if request.method == "POST" and await request.body() else {}
                return JSONResponse(await run_in_threadpool(fn, request, user, body))
            except PermissionError as exc:
                return JSONResponse({"error": str(exc)}, status_code=403 if get_user(request) else 401)
            except service.NotFound as exc:
                return JSONResponse({"error": f"Fant ikke {exc}"}, status_code=404)
            except (AnswerError, ValueError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        return endpoint

    def ctx():
        return get_context()

    async def index(request: Request):
        if not request.url.path.endswith("/"):
            return RedirectResponse(request.url.path + "/")
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @api
    def me(request, user, body):
        return {"user": user, "is_reviewer": service.is_reviewer(user), "demo_users": demo_users or [], "banner": banner,
                "options": service.options({})}

    @api
    def projects(request, user, body):
        return service.list_projects(ctx(), user)

    @api
    def create_project(request, user, body):
        return service.save_settings(ctx(), user, None, body)

    @api
    def entries(request, user, body):
        return service.list_entries(ctx(), user, request.path_params["pid"])

    @api
    def settings_get(request, user, body):
        return service.get_settings(ctx(), user, request.path_params["pid"])

    @api
    def settings_save(request, user, body):
        return service.save_settings(ctx(), user, request.path_params["pid"], body)

    @api
    def rules_get(request, user, body):
        return service.get_rules(ctx(), user, request.path_params["pid"], request.query_params.get("version"))

    @api
    def rules_save(request, user, body):
        return service.save_rules(ctx(), user, request.path_params["pid"], body.get("rules") or [], body.get("note", ""))

    @api
    def rules_draft(request, user, body):
        return service.draft_rules(ctx(), user, request.path_params["pid"], body.get("text", ""))

    @api
    def map_view(request, user, body):
        return service.map_data(ctx(), user, request.path_params["pid"])

    @api
    def area(request, user, body):
        return service.save_area(ctx(), user, request.path_params["pid"], body.get("points") or [], body.get("crs"),
                                 body.get("source", ""))

    @api
    def chat(request, user, body):
        return service.ask(ctx(), user, request.path_params["pid"], body.get("messages") or [], body.get("lang") or "nb")

    @api
    def correct(request, user, body):
        return service.correct_value(ctx(), user, request.path_params["eid"], body.get("field", ""), body.get("value", ""),
                                     body.get("comment", ""))

    @api
    def override(request, user, body):
        return service.override_check(ctx(), user, request.path_params["eid"], body.get("rule_id", ""),
                                      body.get("result") or None, body.get("comment", ""))

    @api
    def comment(request, user, body):
        return service.add_comment(ctx(), user, request.path_params["eid"], body.get("text", ""))

    @api
    def entry(request, user, body):
        return service.entry_detail(ctx(), user, request.path_params["eid"])

    @api
    def info(request, user, body):
        return service.save_data_info(ctx(), user, request.path_params["eid"], body)

    @api
    def qa(request, user, body):
        return service.update_qa(ctx(), user, request.path_params["eid"], body)

    @api
    def decision(request, user, body):
        return service.decide(ctx(), user, request.path_params["eid"], body.get("ready") or None, body.get("comment", ""))

    @api
    def answer(request, user, body):
        return service.answer_question(ctx(), user, request.path_params["qid"], body.get("answer", ""))

    @api
    def inbox(request, user, body):
        return service.notifications(ctx(), user)

    @api
    def run(request, user, body):
        return service.run_worker(ctx(), user, bool(body.get("force")))

    async def export(request: Request):
        try:
            user_or_401(request)
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        pid = request.path_params["pid"]
        c = get_context()
        data = await run_in_threadpool(export_project, c.db, pid, c.settings)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="Grunnlagsdata_register_{pid}.xlsx"'})

    async def download(request: Request):
        try:
            user = user_or_401(request)
            path = await run_in_threadpool(service.source_file, get_context(), user, request.path_params["fid"])
        except PermissionError as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        except service.NotFound as exc:
            return JSONResponse({"error": f"Fant ikke {exc}"}, status_code=404)
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    async def demo_login(request: Request):
        if not demo_users:
            return JSONResponse({"error": "Demo-innlogging er av."}, status_code=404)
        email = (await request.json()).get("email", "")
        resp = JSONResponse({"ok": True})
        resp.set_cookie("bd_user", email, httponly=True, samesite="lax")
        return resp

    routes = [
        Route("/", index),
        Route("/api/me", me),
        Route("/api/projects", projects),
        Route("/api/projects", create_project, methods=["POST"]),
        Route("/api/projects/{pid}/entries", entries),
        Route("/api/projects/{pid}/settings", settings_get),
        Route("/api/projects/{pid}/settings", settings_save, methods=["POST"]),
        Route("/api/projects/{pid}/rules", rules_get),
        Route("/api/projects/{pid}/rules", rules_save, methods=["POST"]),
        Route("/api/projects/{pid}/rules/draft", rules_draft, methods=["POST"]),
        Route("/api/projects/{pid}/export.xlsx", export),
        Route("/api/projects/{pid}/chat", chat, methods=["POST"]),
        Route("/api/projects/{pid}/map", map_view),
        Route("/api/projects/{pid}/area", area, methods=["POST"]),
        Route("/api/entries/{eid}", entry),
        Route("/api/entries/{eid}/info", info, methods=["POST"]),
        Route("/api/entries/{eid}/qa", qa, methods=["POST"]),
        Route("/api/entries/{eid}/decision", decision, methods=["POST"]),
        Route("/api/entries/{eid}/correct", correct, methods=["POST"]),
        Route("/api/entries/{eid}/override", override, methods=["POST"]),
        Route("/api/entries/{eid}/comments", comment, methods=["POST"]),
        Route("/api/questions/{qid}/answer", answer, methods=["POST"]),
        Route("/api/files/{fid}/download", download),
        Route("/api/notifications", inbox),
        Route("/api/worker/run", run, methods=["POST"]),
        Route("/api/demo/login", demo_login, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    return Starlette(routes=routes)


def demo_user_from_cookie(users: list[dict]) -> Callable[[Request], dict | None]:
    """For the demo: the user picked in the switcher (cookie), defaulting to the first."""
    by_email = {u["email"]: u for u in users}

    def get_user(request: Request) -> dict | None:
        return by_email.get(request.cookies.get("bd_user", ""), users[0])

    return get_user
