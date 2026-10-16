"""Studio routes for the optional Fish Audio engines: state, licence, install."""

from __future__ import annotations

import threading

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from folivox.tts import builds, fish_check, fish_setup, licences


class Install:
    """One background download at a time; the page polls ``GET /api/engines/fish/install``."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state, self.build, self.name = "idle", "", ""
        self.done = self.total = 0
        self.message = ""
        self.phase, self.found = "", 0  # "found" | "downloading" | "verifying" | "" (environment still preparing)

    def snapshot(self) -> dict:
        return {"state": self.state, "build": self.build, "name": self.name, "done": self.done, "total": self.total,
                "message": self.message, "phase": self.phase, "found": self.found}


def build_info(b: builds.Build, hw: builds.Hardware, cat: builds.Catalog) -> dict:
    lic = cat.licences[b.licence]
    f = builds.fit(b, hw)
    return {"id": b.id, "engine": b.engine, "title": b.title, "quant": b.quant, "size_gb": round(b.size_gb, 1),
            "peak_gb": b.peak_gb, "weights_gb": b.weights_gb, "min_total_gb": b.min_total_gb,
            "licence": b.licence, "licence_name": lic.name, "licence_version": lic.version,
            "commercial": lic.commercial, "accepted": licences.is_accepted(lic),
            "installed": fish_setup.is_ready(b), "verified": b.status == "verified", "fit": f.level,
            "fit_message": f.message, "supported": hw.platform_tag in b.platforms, "repo": b.repo,
            "trusted_org": builds.is_trusted_org(b.repo, cat), "notes": b.notes,
            "tested_on": list(b.tested_on)}


def state_payload() -> dict:
    cat = builds.load()
    hw = builds.detect_hardware()
    infos = [build_info(b, hw, cat) for b in sorted(cat.builds, key=lambda x: -x.rank)]
    rec = builds.recommend(hw, cat=cat)
    return {"builds": infos, "recommended": rec.id if rec else None,
            "hardware": {"platform": hw.platform_tag, "total_gb": hw.total_gb, "available_gb": hw.available_gb},
            "licences": {k: licences.summary(k) for k in cat.licences},
            "bundled_voices_allowed": fish_check.bundled_voices_allowed(),
            "bundled_voices_note": fish_check.BUNDLED_VOICES_NOTE}


def routes(api_error, install: Install) -> list[Route]:
    def known_build(build_id: str) -> builds.Build:
        try:
            return builds.load().build(str(build_id))
        except builds.CatalogError as e:
            raise api_error(str(e), 404) from None

    async def get_state(request: Request):
        return JSONResponse(state_payload())

    async def get_licence(request: Request):
        lic = builds.load().licences.get(request.path_params["licence"])
        if lic is None:
            raise api_error("Unknown licence", 404)
        try:
            return JSONResponse({"id": lic.id, "text": licences.fetch_text(lic), "page": lic.page})
        except licences.LicenceError as e:  # offline or the vendor changed the text: send the reader to the page
            return JSONResponse({"id": lic.id, "text": "", "page": lic.page, "error": str(e)})

    async def accept(request: Request):
        body = await request.json()
        if body.get("confirm") is not True:
            raise api_error("The licence must be confirmed explicitly")
        lic = builds.load().licences.get(str(body.get("licence", "")))
        if lic is None:
            raise api_error("Unknown licence", 404)
        licences.accept(lic.id)
        return JSONResponse(state_payload())

    async def revoke(request: Request):
        licences.revoke(str((await request.json()).get("licence", "")))
        return JSONResponse(state_payload())

    async def install_status(request: Request):
        return JSONResponse(install.snapshot())

    async def install_start(request: Request):
        b = known_build((await request.json()).get("build", ""))
        hw = builds.detect_hardware()
        f = builds.fit(b, hw)
        if f.level == "no":
            raise api_error(f.message)
        if not licences.is_accepted(builds.load().licences[b.licence]):
            raise api_error("Accept the licence first", 403)
        with install.lock:
            if install.state == "running":
                raise api_error("An engine is already being installed", 409)
            install.state, install.build, install.name = "running", b.id, b.title
            install.done = install.total = 0
            install.message, install.phase, install.found = "", "", 0

        def progress(name: str, done: int, total: int) -> None:
            install.name, install.done, install.total = name, done, total

        def phase(name: str, size: int) -> None:
            install.phase, install.done, install.total = name, 0, 0
            if name == "found":
                install.found = size

        def work() -> None:
            try:
                fish_setup.install(b, progress, log=lambda m: setattr(install, "message", m), phase=phase)
                install.state, install.message = "done", ""
            except Exception as e:  # noqa: BLE001 — shown to the user
                install.state, install.message = "error", str(e)

        threading.Thread(target=work, daemon=True, name="folivox-fish-install").start()
        return JSONResponse(install.snapshot(), status_code=202)

    async def remove(request: Request):
        b = known_build((await request.json()).get("build", ""))
        if install.state == "running":
            raise api_error("An engine is being installed; wait for it", 409)
        fish_setup.remove(b)
        return JSONResponse(state_payload())

    return [Route("/api/engines/fish", get_state),
            Route("/api/engines/fish/licence/{licence}", get_licence),
            Route("/api/engines/fish/accept", accept, methods=["POST"]),
            Route("/api/engines/fish/revoke", revoke, methods=["POST"]),
            Route("/api/engines/fish/install", install_status),
            Route("/api/engines/fish/install", install_start, methods=["POST"]),
            Route("/api/engines/fish/remove", remove, methods=["POST"])]
