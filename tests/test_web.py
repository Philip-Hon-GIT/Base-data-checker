"""Smoke test of the HTTP layer: start the demo app with uvicorn and call the API."""

import json
import socket
import threading
import time
import urllib.request

import pytest

uvicorn = pytest.importorskip("uvicorn")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from basedata.demo import BANNER, USERS, build_demo
    from basedata.web.app import create_app, demo_user_from_cookie

    ctx = build_demo(tmp_path_factory.mktemp("web") / "samples", history=False)
    app = Starlette(routes=[Mount("/basedata", create_app(lambda: ctx, demo_user_from_cookie(USERS),
                                                          demo_users=USERS, banner=BANNER))])
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/basedata"
    srv.should_exit = True
    t.join(timeout=5)


def call(url, method="GET", body=None, cookie=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", **({"cookie": cookie} if cookie else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


REVIEWER = "bd_user=ingrid.berg@example.com"
KARI = "bd_user=kari.nordmann@example.com"
OLA = "bd_user=ola.hansen@example.com"
PID = "rv999-nordby"


def j(res):
    return json.loads(res[1])


def test_index_and_static(server):
    status, body, _ = call(server + "/")
    assert status == 200 and b"static/app.js" in body and b'lang="nb"' in body
    assert call(server + "/static/app.js")[0] == 200


def test_me_and_projects(server):
    me = j(call(server + "/api/me", cookie=KARI))
    assert me["user"]["name"] == "Kari Nordmann" and me["is_reviewer"] is False and len(me["demo_users"]) == 3
    projects = j(call(server + "/api/projects"))
    assert projects[0]["id"] == PID and projects[0]["entries"] == 13 and projects[0]["files"] == 18


def test_register_and_entry(server):
    rows = j(call(server + f"/api/projects/{PID}/entries"))
    assert [r["seq"] for r in rows] == list(range(1, 14)) and rows[6]["kind"] == "package"
    d = j(call(server + f"/api/entries/{rows[6]['id']}"))
    assert len(d["files"]) == 6 and d["permissions"]["can_review"] is True
    d = j(call(server + f"/api/entries/{rows[8]['id']}", cookie=OLA))
    assert d["permissions"] == {"can_review": False, "can_answer": True, "can_edit_info": True, "can_correct": True,
                                "can_override": False, "can_comment": True}
    assert any(q["field"] == "horizontal_epsg" for q in d["questions"])
    assert call(server + "/api/entries/finnes-ikke")[0] == 404


def test_answer_as_wrong_user_is_forbidden(server):
    rows = j(call(server + f"/api/projects/{PID}/entries"))
    q = next(q for q in j(call(server + f"/api/entries/{rows[4]['id']}"))["questions"] if q["field"] == "source")
    status, body, _ = call(server + f"/api/questions/{q['id']}/answer", "POST", {"answer": "Vet ikke"}, cookie=OLA)
    assert status == 403 and "Bare den som leverte" in json.loads(body)["error"]
    status, body, _ = call(server + f"/api/questions/{q['id']}/answer", "POST", {"answer": "Vet ikke"}, cookie=KARI)
    assert status == 200 and "kontrollert på nytt" in json.loads(body)["message"]


def test_ks_requires_reviewer(server):
    rows = j(call(server + f"/api/projects/{PID}/entries"))
    eid = rows[3]["id"]
    assert call(server + f"/api/entries/{eid}/decision", "POST", {"ready": "ja"}, cookie=KARI)[0] == 403
    status, body, _ = call(server + f"/api/entries/{eid}/decision", "POST", {"ready": "nei"}, cookie=REVIEWER)
    assert status == 400 and "Skriv hvorfor" in json.loads(body)["error"]
    status, body, _ = call(server + f"/api/entries/{eid}/qa", "POST", {"qa_status": "pagar", "qa_note": "Venter"}, cookie=REVIEWER)
    assert status == 200 and json.loads(body)["entry"]["qa_status"] == "pagar"


def test_settings_and_rules(server):
    s = j(call(server + f"/api/projects/{PID}/settings", cookie=KARI))
    assert s["horizontal_crs"] == "EPSG:25832" and s["can_edit"] is False and s["options"]["crs"]
    assert call(server + f"/api/projects/{PID}/settings", "POST", {"name": "x"}, cookie=KARI)[0] == 403
    rules = j(call(server + f"/api/projects/{PID}/rules"))
    assert rules["version"] == "v1.0" and "R-REF-01" in rules["builtin"]
    status, body, _ = call(server + f"/api/projects/{PID}/rules/draft", "POST",
                           {"text": "Ortofoto skal ha en oppløsning på 0,25 m eller bedre."}, cookie=REVIEWER)
    assert status == 200 and json.loads(body)["rules"][0]["applies_to"] == ["orthophoto"]


def test_export_download(server):
    status, body, headers = call(server + f"/api/projects/{PID}/export.xlsx")
    assert status == 200 and body[:2] == b"PK" and "attachment" in headers["content-disposition"]


def test_chat(server):
    status, body, _ = call(server + f"/api/projects/{PID}/chat", "POST",
                           {"messages": [{"role": "user", "content": "Hvilke data mangler koordinatsystem?"}]}, cookie=OLA)
    res = json.loads(body)
    assert status == 200 and "#8" in res["answer"] and "#9" in res["answer"] and "regelbasert" in res["model"]
    assert call(server + f"/api/projects/{PID}/chat", "POST", {"messages": []})[0] == 400


def test_correct_override_comment(server):
    rows = j(call(server + f"/api/projects/{PID}/entries"))
    eid = rows[9]["id"]  # #10 Ledninger_VA.gpkg, Ola's
    status, body, _ = call(server + f"/api/entries/{eid}/correct", "POST", {"field": "source", "value": "Nordby kommune"}, cookie=KARI)
    assert status == 403
    status, body, _ = call(server + f"/api/entries/{eid}/correct", "POST", {"field": "source", "value": "Nordby kommune", "comment": "VA-etaten"}, cookie=OLA)
    assert status == 200 and "Kilde korrigert" in json.loads(body)["message"]
    assert call(server + f"/api/entries/{eid}/override", "POST", {"rule_id": "R-QUA-01", "result": "ok", "comment": "ok"}, cookie=OLA)[0] == 403
    assert call(server + f"/api/entries/{eid}/comments", "POST", {"text": "Sjekk mot ledningskart"}, cookie=KARI)[0] == 200
    d = j(call(server + f"/api/entries/{eid}", cookie=KARI))
    assert d["entry"]["comment_list"][-1]["text"] == "Sjekk mot ledningskart" and d["permissions"]["can_correct"] is False


def test_map_and_area(server):
    m = j(call(server + f"/api/projects/{PID}/map", cookie=KARI))
    assert m["items"] and m["can_edit"] is False
    pts = [[10.80, 59.90], [10.86, 59.90], [10.86, 59.93], [10.80, 59.93]]
    assert call(server + f"/api/projects/{PID}/area", "POST", {"points": pts}, cookie=KARI)[0] == 403
    status, body, _ = call(server + f"/api/projects/{PID}/area", "POST", {"points": pts, "crs": "EPSG:4326"}, cookie=REVIEWER)
    assert status == 200 and len(json.loads(body)["area"]["coordinates"]) == 4
    status, body, _ = call(server + f"/api/projects/{PID}/chat", "POST", {"messages": [{"role": "user", "content": "Oppsummer status"}], "lang": "en"})
    assert status == 200


def test_open_source_file(server):
    status, body, _ = call(f"{server}/api/projects/{PID}/entries", cookie=REVIEWER)
    first = json.loads(body)[0]
    status, body, _ = call(f"{server}/api/entries/{first['id']}", cookie=REVIEWER)
    f = json.loads(body)["files"][0]
    assert f["source_path"].endswith(f["file_name"]) and f["link"].endswith("/download")
    status, data, headers = call(f"{server}/api/files/{f['id']}/download", cookie=REVIEWER)
    assert status == 200 and data.startswith(b".HODE")
    assert call(f"{server}/api/files/finnes-ikke/download", cookie=REVIEWER)[0] == 404
