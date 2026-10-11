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


def ui_token() -> str:
    """The access token: created once, kept in a private file in the user data dir so every run (and every
    bookmark or old tab) uses the same one."""
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


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    from folivox.ui.app import create_app

    if port_in_use(host, port):
        raise SystemExit(f"Port {port} is already in use by another program. "
                         f"Choose another one: folivox ui --port {port + 1}")

    token = ui_token()
    app = create_app(token=token, port=port)
    url = f"http://{host}:{port}/?token={token}"
    print(f"Folivox UI: {url}\nOpen this link once: the browser then keeps a cookie and you can use "
          f"http://{host}:{port}/ (bookmark it). Press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
