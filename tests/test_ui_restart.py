"""`folivox ui --restart/--stop`: the studio answers who it is, can be asked to exit, and the port is reused."""

import socket
import threading
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
uvicorn = pytest.importorskip("uvicorn")

from starlette.testclient import TestClient  # noqa: E402

from folivox import ui  # noqa: E402
from folivox.ui.app import API_LEVEL, create_app  # noqa: E402

TOKEN = "t0ken-t0ken-t0ken-t0ken"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def saved_token(monkeypatch):
    monkeypatch.setattr(ui, "read_token", lambda: TOKEN)


def start_studio(tmp_path, port):
    app = create_app(token=TOKEN, port=port, data_dir=tmp_path / "ui")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    app.state.request_exit = lambda: setattr(server, "should_exit", True)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if ui.port_in_use("127.0.0.1", port):
            return app, server, thread
        time.sleep(0.05)
    raise AssertionError("the studio did not start")


def test_ping_says_what_is_on_the_port_and_whether_it_is_busy(tmp_path):
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui")
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    info = c.get("/api/ping").json()
    assert info["app"] == "folivox-studio" and info["api"] == API_LEVEL and info["busy"] is False and info["pid"]
    assert TestClient(app, base_url="http://127.0.0.1:8765").get("/api/ping").status_code == 401  # needs the token


def test_shutdown_refuses_while_rendering_unless_forced(tmp_path):
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui")
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    assert c.post("/api/shutdown").status_code == 501  # nobody can stop it from outside (not started by the CLI)
    stopped = []
    app.state.request_exit = lambda: stopped.append(1)
    app.state.ui.manager.busy = lambda: True
    refused = c.post("/api/shutdown", json={})
    assert refused.status_code == 409 and refused.json()["busy"] is True and not stopped
    assert c.post("/api/shutdown", json={"force": True}).json() == {"stopping": True} and stopped == [1]


def test_stop_and_restart_reuse_the_same_port(tmp_path):
    port = free_port()
    _, _, thread = start_studio(tmp_path, port)
    assert ui.studio_on("127.0.0.1", port)["app"] == "folivox-studio"
    info = ui.stop_running("127.0.0.1", port)
    assert info["pid"] and not ui.port_in_use("127.0.0.1", port)
    thread.join(timeout=5)
    _, server, thread = start_studio(tmp_path, port)  # the same port is free to use again
    assert ui.studio_on("127.0.0.1", port) is not None
    server.should_exit = True
    thread.join(timeout=5)


def test_stop_says_why_it_cannot(tmp_path):
    port = free_port()
    with pytest.raises(SystemExit, match="No Folivox studio is running"):
        ui.stop_running("127.0.0.1", port)
    with socket.socket() as other:  # another program on the port
        other.bind(("127.0.0.1", port))
        other.listen()
        with pytest.raises(SystemExit, match="another program"):
            ui.stop_running("127.0.0.1", port)
        with pytest.raises(SystemExit, match="another program"):
            ui.run(port=port, open_browser=False)


def test_run_on_a_port_with_our_studio_points_to_restart(tmp_path):
    port = free_port()
    _, server, thread = start_studio(tmp_path, port)
    with pytest.raises(SystemExit, match=r"already running.*--restart"):
        ui.run(port=port, open_browser=False)
    server.should_exit = True
    thread.join(timeout=5)
