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
    monkeypatch.setenv("FOLIVOX_UI_TOKEN", "abc")
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


def test_refusal_names_both_ways_out():
    msg = ui.access_needed_message("0.0.0.0")
    assert "FOLIVOX_UI_TOKEN" in msg and "FOLIVOX_UI_AUTH" in msg and "off" in msg


def test_container_without_access_choice_serves_only_a_notice(monkeypatch):
    import http.server
    import threading
    import urllib.error
    import urllib.request

    servers = []
    real = http.server.ThreadingHTTPServer

    class Probe(real):
        def serve_forever(self, *a, **k):
            servers.append(self)
            raise KeyboardInterrupt  # return control to the test instead of serving forever

    monkeypatch.setattr(http.server, "ThreadingHTTPServer", lambda addr, h: Probe(("127.0.0.1", 0), h))
    with pytest.raises(KeyboardInterrupt):
        ui.serve_access_needed("127.0.0.1", 0, ui.access_needed_message("127.0.0.1"))
    srv = servers[0]
    t = threading.Thread(target=lambda: real.serve_forever(srv), daemon=True)
    t.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/healthz", timeout=5)
        assert e.value.code == 503
        assert b"FOLIVOX_UI_AUTH" in e.value.read()
    finally:
        srv.shutdown()
        srv.server_close()


def test_run_in_a_container_without_access_choice_serves_the_notice(monkeypatch):
    for k in ("FOLIVOX_UI_TOKEN", "FOLIVOX_UI_TOKEN_FILE", "FOLIVOX_UI_AUTH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FOLIVOX_UI_HOST", "0.0.0.0")
    called = []
    monkeypatch.setattr(ui, "serve_access_needed", lambda host, port, msg: called.append((host, port, msg)))
    with pytest.raises(SystemExit):  # the stub returns, then the usual refusal follows (never reached for real)
        ui.run(host="0.0.0.0", port=8765, open_browser=False)
    assert called and called[0][0] == "0.0.0.0"


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


def test_non_ascii_token_is_a_401_not_a_crash(tmp_path):
    c = make(tmp_path)
    assert c.get("/api/voices", headers={"X-Folivox-Token": "тест".encode()}
                 ).status_code == 401
    assert c.get("/?token=%D1%82%D0%B5%D1%81%D1%82").status_code == 401
    assert c.post("/login", data={"token": "тест"}, headers={"Origin": "http://192.168.1.20:8765"}
                  ).status_code == 401


def test_guessing_locks_token_checks_but_not_the_cookie(tmp_path, monkeypatch):
    monkeypatch.setattr("asyncio.sleep", lambda s: _noop())
    c = make(tmp_path)
    origin = {"Origin": "http://192.168.1.20:8765"}
    ok = c.post("/login", data={"token": TOKEN}, headers=origin)
    assert ok.status_code == 303
    cookie = dict(c.cookies)
    c.cookies.clear()
    for _ in range(10):
        assert c.get("/api/voices", headers={"X-Folivox-Token": "wrong-" + "x" * 20}).status_code == 401
    # locked: even the right token is not looked at, over every door
    locked = c.get("/api/voices", headers={"X-Folivox-Token": TOKEN})
    assert locked.status_code == 429 and locked.headers["retry-after"]
    assert c.post("/login", data={"token": TOKEN}, headers=origin).status_code == 429
    assert c.get(f"/?token={TOKEN}").status_code == 429
    # the owner's session keeps working
    c.cookies.update(cookie)
    assert c.get("/api/voices").status_code == 200


def test_requests_without_credentials_do_not_count_as_guesses(tmp_path):
    c = make(tmp_path)
    for _ in range(30):
        assert c.get("/api/voices").status_code == 401
    assert c.get("/api/voices", headers={"X-Folivox-Token": TOKEN}).status_code == 200


def test_session_cookie_flags(tmp_path, monkeypatch):
    monkeypatch.setattr("asyncio.sleep", lambda s: _noop())
    c = make(tmp_path)
    origin = {"Origin": "http://192.168.1.20:8765"}
    plain = c.post("/login", data={"token": TOKEN}, headers=origin).headers["set-cookie"].lower()
    assert "httponly" in plain and "samesite=strict" in plain and "secure" not in plain
    proxied = c.post("/login", data={"token": TOKEN}, headers={**origin, "X-Forwarded-Proto": "https"})
    assert "secure" in proxied.headers["set-cookie"].lower()


def test_loopback_cookie_is_unchanged(tmp_path):
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui")
    c = TestClient(app, base_url="http://127.0.0.1:8765", follow_redirects=False)
    cookie = c.get(f"/?token={TOKEN}").headers["set-cookie"].lower()
    assert "max-age=7776000" in cookie and "secure" not in cookie
    c.cookies.clear()
    for _ in range(15):  # no lock-out on the loopback
        assert c.get("/api/voices", headers={"X-Folivox-Token": "x" * 20}).status_code == 401
    assert c.get("/api/voices", headers={"X-Folivox-Token": TOKEN}).status_code == 200


def test_healthz_ignores_allowed_hosts(tmp_path):
    c = make(tmp_path, allowed_hosts={"studio.home"})
    assert c.get("/healthz", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    assert c.get("/api/voices", headers={"X-Folivox-Token": TOKEN, "Host": "127.0.0.1:8765"}).status_code == 403


def test_every_route_but_the_login_ones_needs_the_token(tmp_path):
    """No page, download or stream is reachable without credentials (only /, /login, /healthz, /i18n)."""
    c = make(tmp_path)
    app_routes = c.app.routes
    open_paths = {"/", "/healthz", "/login"}
    for r in app_routes:
        path = getattr(r, "path", "")
        if path in open_paths or path.startswith("/i18n/"):
            continue
        assert path.startswith("/api/"), path
        probe = path.split("{")[0] if "{" in path else path
        for method in ("GET", "POST", "DELETE"):
            if method in (getattr(r, "methods", None) or {"GET", "POST", "DELETE"}):
                assert c.request(method, probe).status_code == 401, (method, path)


def test_redact_removes_the_studio_token_read_from_a_file(monkeypatch, tmp_path):
    from folivox import diag

    f = tmp_path / "token"
    f.write_text(TOKEN)
    monkeypatch.delenv("FOLIVOX_UI_TOKEN", raising=False)
    monkeypatch.setenv("FOLIVOX_UI_TOKEN_FILE", str(f))
    assert TOKEN not in diag.redact(f"login with {TOKEN} ok")


# ---- FOLIVOX_UI_AUTH=off: no password, private clients only ------------------------------------------------

def open_client(tmp_path, peer="192.168.1.50", base="http://192.168.1.20:8765", **kw):
    app = create_app(port=8765, data_dir=tmp_path / "ui", network=True, open_access=True, **kw)
    return TestClient(app, base_url=base, client=(peer, 50000), follow_redirects=False)


def test_open_access_needs_network_and_no_token(tmp_path):
    with pytest.raises(ValueError):
        create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", network=True, open_access=True)
    with pytest.raises(ValueError):
        create_app(port=8765, data_dir=tmp_path / "ui", open_access=True)


@pytest.mark.parametrize("peer", ["10.1.2.3", "172.17.0.1", "192.168.1.50", "127.0.0.1", "169.254.1.1", "::1",
                                  "fd12:3456::1", "fe80::1", "::ffff:192.168.1.5"])
def test_open_access_takes_private_clients_without_login(tmp_path, peer):
    c = open_client(tmp_path, peer)
    assert c.get("/api/voices").status_code == 200
    page = c.get("/")
    assert page.status_code == 200 and "Enter the access token" not in page.text
    assert "set-cookie" not in page.headers
    assert c.get("/healthz").json() == {"ok": True}


@pytest.mark.parametrize("peer", ["8.8.8.8", "100.64.0.1", "172.32.0.1", "2001:4860::1", "testclient", "",
                                  "::ffff:8.8.8.8"])
def test_open_access_refuses_public_and_unparsable_clients(tmp_path, peer):
    c = open_client(tmp_path, peer)
    for path in ("/", "/api/voices"):
        r = c.get(path)
        assert r.status_code == 403 and "FOLIVOX_UI_ALLOWED_NETS" in r.text
    assert c.get("/healthz").status_code == 200  # the container health check is not a client


def test_open_access_respects_allowed_nets(tmp_path):
    import ipaddress

    nets = [ipaddress.ip_network("100.64.0.0/10")]
    assert open_client(tmp_path, "100.100.1.1", allowed_nets=nets).get("/api/voices").status_code == 200
    assert open_client(tmp_path, "192.168.1.50", allowed_nets=nets).get("/api/voices").status_code == 403


def test_open_access_ignores_x_forwarded_for(tmp_path):
    c = open_client(tmp_path, "8.8.8.8")
    assert c.get("/api/voices", headers={"X-Forwarded-For": "192.168.1.5"}).status_code == 403


@pytest.mark.parametrize("host,code", [("192.168.1.20:8765", 200), ("[fd00::5]:8765", 200), ("nas:8765", 200),
                                       ("studio.local:8765", 200), ("folivox.home.arpa", 200),
                                       ("evil.example", 403), ("evil.example:8765", 403), ("a.b.c.com", 403)])
def test_open_access_host_guard(tmp_path, host, code):
    assert open_client(tmp_path).get("/api/voices", headers={"Host": host}).status_code == code


def test_open_access_allowed_hosts_replace_the_defaults(tmp_path):
    c = open_client(tmp_path, allowed_hosts={"studio.example.org"})
    assert c.get("/api/voices", headers={"Host": "studio.example.org"}).status_code == 200
    assert c.get("/api/voices", headers={"Host": "nas"}).status_code == 403


def test_open_access_still_blocks_other_sites(tmp_path):
    c = open_client(tmp_path)
    assert c.post("/api/shutdown", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/voices", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_open_access_keys_never_show_values(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value-123456")
    body = open_client(tmp_path).get("/api/keys").text
    assert "sk-secret-value-123456" not in body


def test_default_network_mode_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("FOLIVOX_UI_AUTH", raising=False)
    assert ui.auth_off() is False
    c = make(tmp_path)  # a public peer is not filtered when a token is the protection
    assert c.get("/api/voices").status_code == 401


def test_auth_env(monkeypatch):
    for v, expected in (("off", True), ("OFF", True), (" off ", True), ("on", False), ("", False), ("0", False)):
        monkeypatch.setenv("FOLIVOX_UI_AUTH", v)
        assert ui.auth_off() is expected


def test_allowed_nets_env(monkeypatch):
    monkeypatch.delenv("FOLIVOX_UI_ALLOWED_NETS", raising=False)
    assert ui.configured_nets() is None
    monkeypatch.setenv("FOLIVOX_UI_ALLOWED_NETS", "192.168.1.0/24, 10.0.0.7")
    assert [str(n) for n in ui.configured_nets()] == ["192.168.1.0/24", "10.0.0.7/32"]
    monkeypatch.setenv("FOLIVOX_UI_ALLOWED_NETS", "nonsense")
    with pytest.raises(SystemExit, match="ALLOWED_NETS"):
        ui.configured_nets()


def test_run_refuses_token_together_with_auth_off(monkeypatch):
    monkeypatch.setenv("FOLIVOX_UI_AUTH", "off")
    monkeypatch.setenv("FOLIVOX_UI_TOKEN", TOKEN)
    with pytest.raises(SystemExit, match="both set"):
        ui.run(host="0.0.0.0", port=8765, open_browser=False)


def test_run_warns_loudly_and_starts_without_a_token(monkeypatch, capsys):
    import uvicorn

    for k in ("FOLIVOX_UI_TOKEN", "FOLIVOX_UI_TOKEN_FILE", "FOLIVOX_UI_ALLOWED_NETS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FOLIVOX_UI_AUTH", "off")
    seen = {}
    monkeypatch.setattr(ui, "port_in_use", lambda h, p: False)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self: None)
    from types import SimpleNamespace as NS

    fake = NS(state=NS(watchdog=NS(start=lambda: None), shutdown=lambda: None, cancel_all=lambda: None))
    monkeypatch.setattr("folivox.ui.app.create_app", lambda **kw: seen.update(kw=kw) or fake)
    monkeypatch.setattr(uvicorn, "Config", lambda *a, **k: seen.update(config_kw=k) or object())
    monkeypatch.setattr(uvicorn.Server, "__init__", lambda self, cfg: None)
    ui.run(host="0.0.0.0", port=8765, open_browser=False)
    out = capsys.readouterr().out
    assert out.count("WITHOUT A PASSWORD") == 1 and "cloud API keys" in out
    assert seen["kw"]["token"] is None and seen["kw"]["open_access"] is True
    assert seen["config_kw"]["proxy_headers"] is False


def test_open_access_on_loopback_is_ignored(monkeypatch, capsys):
    monkeypatch.setenv("FOLIVOX_UI_AUTH", "off")
    monkeypatch.delenv("FOLIVOX_UI_TOKEN", raising=False)
    monkeypatch.delenv("FOLIVOX_UI_TOKEN_FILE", raising=False)
    monkeypatch.setattr(ui, "port_in_use", lambda h, p: True)
    monkeypatch.setattr(ui, "studio_on", lambda h, p: {"version": "x"})
    with pytest.raises(SystemExit, match="already running"):
        ui.run(host="127.0.0.1", port=8765, open_browser=False)
    assert "ignored" in capsys.readouterr().out
