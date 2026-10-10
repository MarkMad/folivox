"""Local web interface (``folivox ui``). Needs the optional extra ``folivox[ui]``."""

from __future__ import annotations


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import secrets
    import threading
    import webbrowser

    import uvicorn

    from folivox.ui.app import create_app

    token = secrets.token_urlsafe(16)
    app = create_app(token=token, port=port)
    url = f"http://{host}:{port}/?token={token}"
    print(f"Folivox UI: {url}\nPress Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
