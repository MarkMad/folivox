"""Local web interface (``folivox ui``). Needs the optional extra ``folivox[ui]``."""

from __future__ import annotations


def port_in_use(host: str, port: int) -> bool:
    """True if anything already answers on host:port, including a server bound to all interfaces: macOS lets a
    second server bind 127.0.0.1 next to it, and the browser would then talk to the wrong one."""
    import socket

    for target in (host, "localhost"):
        try:
            with socket.create_connection((target, port), timeout=0.5):
                return True
        except OSError:
            continue
    return False


MIN_TOKEN = 16


def is_loopback(host: str) -> bool:
    """True if ``host`` only accepts connections from this computer."""
    import ipaddress

    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False  # a name or an unspecified address (0.0.0.0, ::): reachable from the network


PRIVATE_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16",
                "::1/128", "fc00::/7", "fe80::/10")


def auth_off() -> bool:
    """``FOLIVOX_UI_AUTH=off``: the owner chose to run the network studio without a password. Anything else
    (or nothing) keeps the token required."""
    import os

    return os.environ.get("FOLIVOX_UI_AUTH", "").strip().lower() == "off"


def configured_nets() -> list | None:
    """``FOLIVOX_UI_ALLOWED_NETS`` (comma-separated CIDR or addresses): the client networks allowed without a
    password, replacing the private ranges. None if unset; a bad entry stops the start."""
    import ipaddress
    import os

    raw = [x.strip() for x in os.environ.get("FOLIVOX_UI_ALLOWED_NETS", "").split(",") if x.strip()]
    try:
        return [ipaddress.ip_network(x, strict=False) for x in raw] or None
    except ValueError as e:
        raise SystemExit(f"FOLIVOX_UI_ALLOWED_NETS: {e}. Use comma-separated CIDR, e.g. 192.168.1.0/24.") from None


def configured_token() -> str | None:
    """A token chosen by the owner: ``FOLIVOX_UI_TOKEN``, or the file named by ``FOLIVOX_UI_TOKEN_FILE`` (Docker and
    Kubernetes secrets). None if neither is set; a value that is too short stops the start."""
    import os
    from pathlib import Path

    value = os.environ.get("FOLIVOX_UI_TOKEN", "").strip()
    name = os.environ.get("FOLIVOX_UI_TOKEN_FILE", "").strip()
    if not value and name:
        try:
            value = Path(name).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise SystemExit(f"FOLIVOX_UI_TOKEN_FILE: cannot read {name} ({e.strerror or e}).") from None
    if value and len(value) < MIN_TOKEN:
        raise SystemExit(f"The studio token (FOLIVOX_UI_TOKEN) is too short: use at least {MIN_TOKEN} characters, "
                         "for example the output of: openssl rand -hex 24")
    return value or None


def ui_token() -> str:
    """The access token: the owner's (see :func:`configured_token`), else created once and kept in a private file
    in the user data dir so every run (and every bookmark or old tab) uses the same one."""
    chosen = configured_token()
    if chosen:
        return chosen
    import os
    import secrets
    from pathlib import Path

    from platformdirs import user_data_dir

    path = Path(user_data_dir("folivox", appauthor=False)) / "ui_token"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 16:
            return value
    except OSError:
        pass
    value = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)
    os.chmod(path, 0o600)
    return value


def read_token() -> str | None:
    """The access token, or None if the studio never ran (unlike :func:`ui_token`, creates nothing)."""
    from pathlib import Path

    try:
        chosen = configured_token()
    except SystemExit:
        chosen = None
    if chosen:
        return chosen

    from platformdirs import user_data_dir

    try:
        value = (Path(user_data_dir("folivox", appauthor=False)) / "ui_token").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if len(value) >= 16 else None


def _call(host: str, port: int, path: str, body: dict | None = None, timeout: float = 2.0) -> dict | None:
    """One request to a studio on host:port with the saved token. The JSON answer (an error answer carries its
    ``status``), or None if nothing studio-like answered."""
    import json
    import urllib.error
    import urllib.request

    token = read_token()
    if token is None:
        return None
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=data, method="GET" if body is None else "POST",
                                 headers={"X-Folivox-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return {**json.loads(e.read()), "status": e.code}
        except ValueError:
            return None
    except (OSError, ValueError):
        return None


def studio_on(host: str, port: int) -> dict | None:
    """What /api/ping says if a Folivox studio (with our token) is on host:port, else None."""
    info = _call(host, port, "/api/ping")
    return info if info and info.get("app") == "folivox-studio" else None


def older_studio(host: str, port: int) -> str | None:
    """A studio that predates /api/ping (it cannot be asked to stop): a description with its pid if we can find
    it, else None. Recognised by answering our token on an old route."""
    if not isinstance(_call(host, port, "/api/settings"), dict):
        return None
    import shutil
    import subprocess

    pid = ""
    if shutil.which("lsof"):
        out = subprocess.run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True,
                             check=False).stdout.split()  # noqa: S603, S607 — fixed argv
        pid = out[0] if out else ""
    return (f"An older Folivox studio{f' (pid {pid})' if pid else ''} is running on port {port}; it cannot be "
            "stopped remotely. Stop it once with Ctrl+C in its terminal" + (f" or: kill {pid}" if pid else "")
            + ". Newer ones can be replaced with: folivox ui --restart")


def wait_free(host: str, port: int, seconds: float = 15.0) -> bool:
    import time

    end = time.time() + seconds
    while time.time() < end:
        if not port_in_use(host, port):
            return True
        time.sleep(0.2)
    return not port_in_use(host, port)


def stop_running(host: str, port: int, force: bool = False) -> dict:
    """Ask the studio on this port to exit and wait until the port is free. Exits with a message if there is no
    studio, if it is rendering (without ``force``) or if it does not stop."""
    info = studio_on(host, port)
    if info is None:
        if not port_in_use(host, port):
            raise SystemExit(f"No Folivox studio is running on port {port}.")
        raise SystemExit(older_studio(host, port) or f"Port {port} is used by another program, not by the studio.")
    answer = _call(host, port, "/api/shutdown", {"force": force}) or {}
    if answer.get("status") == 409:
        raise SystemExit(f"The studio on port {port} is rendering now. Wait for it to finish, or stop it anyway "
                         "(the work is saved and continues next time): folivox ui --restart --force")
    if not answer.get("stopping"):
        raise SystemExit(f"The studio on port {port} did not accept the stop request "
                         f"(version {info.get('version', '?')}, pid {info.get('pid', '?')}): stop it with Ctrl+C "
                         "in its terminal or kill that process.")
    if not wait_free(host, port):
        raise SystemExit(f"The studio on port {port} did not stop in time (pid {info.get('pid', '?')}).")
    return info


def access_needed_message(host: str) -> str:
    return (f"Listening on {host} makes the studio reachable from the network, which needs an access token "
            "(or an explicit choice to go without one). Set FOLIVOX_UI_TOKEN to a password of at least 16 "
            "characters (e.g. openssl rand -hex 24, or FOLIVOX_UI_TOKEN_FILE), or, on a home network where you "
            "trust every device, set FOLIVOX_UI_AUTH to off (see docs/docker.md, 'Without a password'). "
            "Then start again. Without either the studio stays on 127.0.0.1.")


def serve_access_needed(host: str, port: int, message: str) -> None:
    """Container started without a token or ``FOLIVOX_UI_AUTH=off``: serve only a page that says what to set (and fail
    the health check) rather than exit and restart in a loop. Nothing of the studio is served."""
    import html
    import http.server

    body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<title>Folivox</title><body style='font:16px system-ui,sans-serif;max-width:34rem;margin:12vh auto;"
            f"padding:0 1rem'><h1>Folivox needs one setting</h1><p>{html.escape(message)}</p>").encode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_HEAD = do_GET

        def log_message(self, *args):
            pass

    print(message, flush=True)
    print("The studio is not started. This container shows only this notice until the variable is set.", flush=True)
    http.server.ThreadingHTTPServer((host, port), Handler).serve_forever()


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, restart: bool = False,
        force: bool = False, allowed_hosts: set[str] | None = None) -> None:
    """``host`` beyond this computer (0.0.0.0, a LAN address) is the network mode: it needs an owner-chosen token
    (:func:`configured_token`), never prints it and never opens a browser."""
    import os
    import threading
    import webbrowser

    import uvicorn

    from folivox.ui.app import create_app

    network = not is_loopback(host)
    open_access = auth_off()
    nets = configured_nets() if open_access else None
    if open_access and configured_token() is not None:
        raise SystemExit("FOLIVOX_UI_AUTH=off and a token (FOLIVOX_UI_TOKEN / FOLIVOX_UI_TOKEN_FILE) are both set. "
                         "That would look protected and not be. Remove one of them.")
    if open_access and not network:
        open_access = False  # on this computer only there is nothing to open: the usual cookie link keeps working
        print("FOLIVOX_UI_AUTH=off only matters when listening beyond 127.0.0.1; ignored.", flush=True)
    if network:
        if open_access:
            pass
        elif configured_token() is None:
            need = access_needed_message(host)
            if os.environ.get("FOLIVOX_UI_HOST"):  # a container: stay up and say what to set instead of a restart loop
                serve_access_needed(host, port, need)
            raise SystemExit(need)
        open_browser = False
        probe = "127.0.0.1"  # the studio asks itself (is it running already, stop it) over the loopback
    else:
        probe = host
    if port_in_use(probe, port):
        info = studio_on(probe, port)
        if info is None:
            raise SystemExit(older_studio(probe, port) or f"Port {port} is used by another program. "
                             f"Choose another one: folivox ui --port {port + 1}")
        if not restart:
            state = ", rendering now" if info.get("busy") else ""
            raise SystemExit(f"The Folivox studio is already running at http://{host}:{port}/ "
                             f"(version {info.get('version', '?')}{state}). Open it, or replace it with this "
                             "version: folivox ui --restart")
        stop_running(probe, port, force)
        print(f"Stopped the previous studio (pid {info.get('pid', '?')}).", flush=True)

    token = None if open_access else ui_token()
    app = create_app(token=token, port=port, network=network, allowed_hosts=allowed_hosts,
                     open_access=open_access, allowed_nets=nets)
    class Server(uvicorn.Server):
        def handle_exit(self, sig, frame):  # Ctrl+C: stop the jobs first, or their open event streams hold the exit
            app.state.cancel_all()
            super().handle_exit(sig, frame)

    # open access judges clients by the TCP peer: X-Forwarded-For (uvicorn trusts it from 127.0.0.1) must not decide
    server = Server(uvicorn.Config(app, host=host, port=port, log_level="warning", proxy_headers=not open_access))

    def request_exit() -> None:
        app.state.cancel_all()
        server.should_exit = True

    app.state.request_exit = request_exit
    url = f"http://{host}:{port}/?token={token}"
    if open_access:
        where = ", ".join(str(n) for n in nets) if nets else "private and local networks"
        print("WARNING: Folivox studio runs WITHOUT A PASSWORD (FOLIVOX_UI_AUTH=off). Anyone who can reach "
              f"{host}:{port} from {where} can start renders, spend money on your cloud API keys and change folders. "
              "Use it only on a network you trust, and never publish the port to the internet.", flush=True)
    elif network:
        scope = f" (only for Host: {', '.join(sorted(allowed_hosts))})" if allowed_hosts else ""
        print(f"Folivox studio listens on {host}:{port}: anyone who can reach this port and knows the token can use it "
              f"and your API keys{scope}. The token is the one you set in FOLIVOX_UI_TOKEN; open the address of this "
              "machine and enter it. Traffic is not encrypted: do not expose the port to the internet, put an HTTPS "
              "reverse proxy in front of it.", flush=True)
    else:
        print(f"Folivox UI: {url}\nOpen this link once: the browser then keeps a cookie and you can use "
          f"http://{host}:{port}/ (bookmark it). Press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    app.state.watchdog.start()
    try:
        server.run()
    finally:
        app.state.shutdown()  # no render child, markup thread or loaded model outlives the studio
