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


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import secrets
    import threading
    import webbrowser

    import uvicorn

    from folivox.ui.app import create_app

    if port_in_use(host, port):
        raise SystemExit(f"Port {port} is already in use by another program. "
                         f"Choose another one: folivox ui --port {port + 1}")

    token = secrets.token_urlsafe(16)
    app = create_app(token=token, port=port)
    url = f"http://{host}:{port}/?token={token}"
    print(f"Folivox UI: {url}\nPress Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
