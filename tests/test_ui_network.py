"""Network mode of the studio (Docker, home servers): token required, login page, Host handling."""

from __future__ import annotations

import pytest

pytest.importorskip("starlette")
pytest.importorskip("multipart")
from starlette.testclient import TestClient  # noqa: E402

from folivox import ui  # noqa: E402
from folivox.ui.app import create_app  # noqa: E402

TOKEN = "network-token-0123456789"


def make(tmp_path, **kw):
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", network=True, **kw)
    return TestClient(app, base_url="http://192.168.1.20:8765", follow_redirects=False)


def test_network_mode_without_token_is_refused(tmp_path):
    with pytest.raises(ValueError):
        create_app(token=None, port=8765, data_dir=tmp_path / "ui", network=True)


def test_lan_host_works_only_with_the_token(tmp_path):
    c = make(tmp_path)
    assert c.get("/api/voices").status_code == 401
    assert c.get("/api/voices", headers={"X-Folivox-Token": TOKEN}).status_code == 200
    assert "Enter the access token" in c.get("/").text  # login page, not the studio
    assert c.get("/healthz").json() == {"ok": True}  # health check needs no token and tells nothing else


def test_login_sets_a_cookie_and_opens_the_studio(tmp_path, monkeypatch):
    monkeypatch.setattr("asyncio.sleep", lambda s: _noop())
    c = make(tmp_path)
    bad = c.post("/login", data={"token": "nope"}, headers={"Origin": "http://192.168.1.20:8765"})
    assert bad.status_code == 401 and "folivox_session_8765" not in bad.cookies
    ok = c.post("/login", data={"token": TOKEN}, headers={"Origin": "http://192.168.1.20:8765"})
    assert ok.status_code == 303 and "folivox_session_8765" in ok.cookies
    assert "Enter the access token" not in c.get("/").text
    assert c.get("/api/voices").status_code == 200  # the cookie alone is enough


async def _noop():
    return None


def test_other_site_cannot_post_or_rebind(tmp_path):
    c = make(tmp_path)
    cross = c.post("/login", data={"token": TOKEN}, headers={"Origin": "https://evil.example"})
    assert cross.status_code == 403
    assert c.get("/api/voices", headers={"X-Folivox-Token": TOKEN, "Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_allowed_hosts_limit_the_names(tmp_path):
    c = make(tmp_path, allowed_hosts={"studio.home", "192.168.1.20"})
    assert c.get("/api/voices", headers={"X-Folivox-Token": TOKEN}).status_code == 200
    assert c.get("/api/voices", headers={"X-Folivox-Token": TOKEN, "Host": "studio.home:9000"}).status_code == 200
    assert c.get("/api/voices", headers={"X-Folivox-Token": TOKEN, "Host": "evil.example"}).status_code == 403


def test_loopback_mode_keeps_the_strict_host_guard(tmp_path):
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui")
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    assert c.get("/api/voices", headers={"Host": "192.168.1.20:8765"}).status_code == 403
    assert "Enter the access token" not in c.get("/").text


@pytest.mark.parametrize("host,loop", [("127.0.0.1", True), ("localhost", True), ("::1", True), ("[::1]", True),
                                       ("0.0.0.0", False), ("::", False), ("192.168.1.5", False),
                                       ("studio.lan", False)])
def test_is_loopback(host, loop):
    assert ui.is_loopback(host) is loop


def test_configured_token(monkeypatch, tmp_path):
    for k in ("FOLIVOX_UI_TOKEN", "FOLIVOX_UI_TOKEN_FILE"):
        monkeypatch.delenv(k, raising=False)
    assert ui.configured_token() is None
    monkeypatch.setenv("FOLIVOX_UI_TOKEN", "short")
    with pytest.raises(SystemExit):
        ui.configured_token()
    monkeypatch.delenv("FOLIVOX_UI_TOKEN")
    f = tmp_path / "secret"
    f.write_text(TOKEN + "\n")
    monkeypatch.setenv("FOLIVOX_UI_TOKEN_FILE", str(f))
    assert ui.configured_token() == TOKEN == ui.read_token() == ui.ui_token()
    monkeypatch.setenv("FOLIVOX_UI_TOKEN_FILE", str(tmp_path / "missing"))
    with pytest.raises(SystemExit):
        ui.configured_token()


def test_run_refuses_the_network_without_a_token(monkeypatch):
    for k in ("FOLIVOX_UI_TOKEN", "FOLIVOX_UI_TOKEN_FILE"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit, match="access token"):
        ui.run(host="0.0.0.0", port=8765, open_browser=False)


def test_output_dir_env(monkeypatch, tmp_path):
    from folivox import config

    monkeypatch.setenv("FOLIVOX_OUTPUT_DIR", str(tmp_path / "out"))
    assert config.output_dir() == tmp_path / "out"


def test_work_dir_env(monkeypatch, tmp_path):
    from pathlib import Path

    from folivox.pipeline import RenderOptions

    opts = RenderOptions(output=tmp_path / "out" / "Book.m4b")
    assert opts.resolved_work_dir() == tmp_path / "out" / "Book.folivox"
    monkeypatch.setenv("FOLIVOX_WORK_DIR", str(tmp_path / "work"))
    assert opts.resolved_work_dir() == Path(tmp_path / "work" / "Book.folivox")
