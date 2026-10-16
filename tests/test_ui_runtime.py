"""Studio routes of the inference runtime switch: state, saving the choice, install progress, remove."""

import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402

from folivox import config  # noqa: E402
from folivox.tts import native_setup as ns  # noqa: E402
from folivox.ui.app import create_app  # noqa: E402

TOKEN = "t0ken"


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k in ("FOLIVOX_RUNTIME", ns.SERVER_ENV, ns.MODEL_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv(ns.DIR_ENV, str(tmp_path / "native"))
    monkeypatch.setattr(ns, "platform_tag", lambda: "darwin-arm64")
    config.load.cache_clear()
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=lambda b, o, e: o.output)
    yield TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    config.load.cache_clear()


def test_state_before_install(client):
    s = client.get("/api/runtime").json()
    assert s["selected"] == "auto" and s["installed"] is False and s["auto"] is False
    assert s["build"]["backend"] == "metal" and s["todo"]["bytes"] > 2_000_000_000 and len(s["todo"]["lines"]) == 2
    assert s["install"]["state"] == "idle"


def test_choice_is_saved_and_validated(client, tmp_path):
    assert client.put("/api/runtime", json={"inference": "native"}).json()["selected"] == "native"
    assert 'inference = "native"' in (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert client.put("/api/runtime", json={"inference": "turbo"}).status_code == 400
    assert client.get("/api/runtime").json()["selected"] == "native"


def test_install_runs_in_background_and_reports_errors(client, monkeypatch):
    def boom(plan, progress, log):
        progress("audio.cpp", 5, 10)
        raise ns.NativeError("no network")

    monkeypatch.setattr(ns, "install", boom)
    monkeypatch.setattr(ns, "disk_problem", lambda need: None)
    assert client.post("/api/runtime/install").status_code == 202
    for _ in range(50):
        i = client.get("/api/runtime/install").json()
        if i["state"] != "running":
            break
        time.sleep(0.05)
    assert i["state"] == "error" and "no network" in i["message"]


def test_install_refuses_without_disk_space(client, monkeypatch):
    monkeypatch.setattr(ns, "disk_problem", lambda need: "Not enough disk space")
    r = client.post("/api/runtime/install")
    assert r.status_code == 400 and "disk" in r.json()["error"].lower()


def test_remove_returns_the_new_state(client):
    assert client.post("/api/runtime/remove").json()["installed"] is False
