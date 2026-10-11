"""Web studio: re-attach, restart, double start, cancel then resume, diagnostics."""
import time
import zipfile
from io import BytesIO

import pytest
from test_ui import TOKEN, client, fake_render, upload, wait_done  # noqa: F401

pytest.importorskip("starlette")

from folivox.pipeline import Cancelled  # noqa: E402
from folivox.ui.app import create_app  # noqa: E402


def body(b, tmp_path):
    return {"kind": "render", "book_id": b["book_id"], "chapters": [1],
            "options": {"output_dir": str(tmp_path / "out"), "qa": False}}


def slow(book, opts, events):
    while not events.cancelled():
        time.sleep(0.02)
    raise Cancelled


def test_reloaded_page_finds_the_running_job(client, tmp_path):  # noqa: F811
    client.app.state.ui.manager._render = slow
    job = client.post("/api/jobs", json=body(upload(client), tmp_path)).json()["id"]
    cur = client.get("/api/jobs/current").json()  # what a reloaded tab asks first
    assert cur["id"] == job and cur["state"] == "running"
    client.post(f"/api/jobs/{job}/cancel")
    wait_done(client, job)


def test_race_between_check_and_start_is_409_not_500(client, tmp_path, monkeypatch):  # noqa: F811
    b = upload(client)

    def lost_race(*a, **k):
        raise RuntimeError("Another job is running")

    monkeypatch.setattr(client.app.state.ui.manager, "start", lost_race)
    assert client.post("/api/jobs", json=body(b, tmp_path)).status_code == 409


def test_cancel_then_start_again(client, tmp_path):  # noqa: F811
    b = upload(client)
    client.app.state.ui.manager._render = slow
    first = client.post("/api/jobs", json=body(b, tmp_path)).json()["id"]
    client.post(f"/api/jobs/{first}/cancel")
    assert wait_done(client, first)["state"] == "cancelled"
    client.app.state.ui.manager._render = fake_render
    second = client.post("/api/jobs", json=body(b, tmp_path)).json()["id"]
    assert second != first and wait_done(client, second)["state"] == "done"


def test_server_restart_forgets_the_job_but_not_the_book(client, tmp_path):  # noqa: F811
    b = upload(client)
    client.app.state.ui.manager._render = slow
    client.post("/api/jobs", json=body(b, tmp_path))
    from starlette.testclient import TestClient

    app2 = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=fake_render)  # same data dir
    c2 = TestClient(app2, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    assert c2.get("/api/jobs/current").json() is None  # the page then says "press Render to resume"
    r = c2.post("/api/jobs", json=body(b, tmp_path))  # the book is re-read from disk
    assert r.status_code == 202 and wait_done(c2, r.json()["id"])["state"] == "done"
    client.post("/api/jobs/" + client.get("/api/jobs/current").json()["id"] + "/cancel")


def test_failed_job_reports_the_error_and_allows_a_new_one(client, tmp_path):  # noqa: F811
    def broken(book, opts, events):
        raise RuntimeError("Disk is full")

    client.app.state.ui.manager._render = broken
    b = upload(client)
    j = wait_done(client, client.post("/api/jobs", json=body(b, tmp_path)).json()["id"])
    assert j["state"] == "error" and "Disk is full" in j["error"]
    client.app.state.ui.manager._render = fake_render
    assert client.post("/api/jobs", json=body(b, tmp_path)).status_code == 202


def test_diagnostics_endpoints(client):  # noqa: F811
    d = client.get("/api/diagnostics").json()
    assert "ffmpeg" in d["text"] and d["report"]["platform"]["python"]
    r = client.get("/api/support-bundle")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "report.json" in zipfile.ZipFile(BytesIO(r.content)).namelist()
    assert client.get("/api/support-bundle", headers={"X-Folivox-Token": "bad"}).status_code == 401
