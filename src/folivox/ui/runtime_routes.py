"""Studio endpoints for the inference runtime switch and the optional native runtime (audio.cpp)."""

from __future__ import annotations

import threading

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from folivox import config
from folivox.tts import native_setup as ns
from folivox.ui.fish_routes import Install


def state_payload(install: Install) -> dict:
    opts = config.native_options()
    st = ns.status(opts["weights"])
    try:
        plan = ns.plan(opts["weights"], opts["backend"])
        todo = {"lines": plan.lines, "bytes": plan.todo_bytes}
    except ns.NativeError:
        todo = {"lines": [], "bytes": 0}
    b = st.binary
    return {"selected": config.runtime(), "platform": st.platform,
            "build": {"id": b.id, "backend": b.backend, "verified": b.status == "verified", "note": b.note,
                      "mb": round(b.size / 1e6)} if b else None,
            "installed": st.server is not None and st.problem == "", "server": st.server is not None,
            "problem": st.problem, "auto": st.auto, "todo": todo, "release": ns.load().release,
            "install": install.snapshot()}


def routes(api_error, install: Install) -> list[Route]:
    async def get_state(request: Request):
        return JSONResponse(state_payload(install))

    async def put_state(request: Request):
        value = str((await request.json()).get("inference", ""))
        try:
            config.save_runtime(value)
        except ValueError as e:
            raise api_error(str(e)) from None
        return JSONResponse(state_payload(install))

    async def install_status(request: Request):
        return JSONResponse(install.snapshot())

    async def install_start(request: Request):
        opts = config.native_options()
        try:
            plan = ns.plan(opts["weights"], opts["backend"])
        except ns.NativeError as e:
            raise api_error(str(e)) from None
        if not plan.lines:
            return JSONResponse(state_payload(install))
        problem = ns.disk_problem(plan.todo_bytes)
        if problem:
            raise api_error(problem)
        with install.lock:
            if install.state == "running":
                raise api_error("The native runtime is already being installed", 409)
            install.state, install.build, install.name = "running", "native", "audio.cpp"
            install.done = install.total = 0
            install.message = ""

        def progress(name: str, done: int, total: int) -> None:
            install.name, install.done, install.total = name, done, total

        def work() -> None:
            try:
                ns.install(plan, progress, log=lambda m: setattr(install, "message", m))
                install.state, install.message = "done", ""
            except Exception as e:  # noqa: BLE001 — shown to the user
                install.state, install.message = "error", str(e)

        threading.Thread(target=work, daemon=True, name="folivox-native-install").start()
        return JSONResponse(install.snapshot(), status_code=202)

    async def remove(request: Request):
        if install.state == "running":
            raise api_error("The native runtime is being installed; wait for it", 409)
        from folivox.tts import native

        native.shutdown_all()
        ns.remove()
        return JSONResponse(state_payload(install))

    return [Route("/api/runtime", get_state),
            Route("/api/runtime", put_state, methods=["PUT"]),
            Route("/api/runtime/install", install_status),
            Route("/api/runtime/install", install_start, methods=["POST"]),
            Route("/api/runtime/remove", remove, methods=["POST"])]
