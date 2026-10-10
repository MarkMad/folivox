"""Starlette app behind ``folivox ui``: a thin JSON/SSE layer over the same code the CLI uses."""

from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import uuid
from pathlib import Path

from platformdirs import user_data_dir
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from folivox import config
from folivox import voices as catalog
from folivox.pipeline import RenderOptions
from folivox.ui.jobs import JobManager, chapter_files

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 200 * 1024 * 1024
PREVIEW_CHARS = 600


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class State:
    def __init__(self, data_dir: Path, render=None):
        self.data_dir = data_dir
        self.books: dict[str, dict] = {}
        self.manager = JobManager(render)

    def book(self, book_id: str) -> dict:
        """The uploaded book; re-read from disk after a server restart."""
        if book_id not in self.books:
            from folivox.readers import read_book

            folder = self.data_dir / "uploads" / Path(book_id).name
            files = [p for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []
            if not files:
                raise ApiError("Unknown book; upload it again", 404)
            self.books[book_id] = {"book": read_book(files[0]), "path": files[0]}
        return self.books[book_id]

    @property
    def session_file(self) -> Path:
        return self.data_dir / "session.json"


def _chapters(book, depth: int) -> list[dict]:
    cps = book.chars / book.estimated_seconds if book.estimated_seconds else 14.0
    return [{"n": i, "title": ch.title, "chars": ch.chars, "seconds": ch.chars / cps}
            for i, ch in enumerate(book.chapters(depth), 1)]


def _book_summary(book_id: str, book, depth: int = 2) -> dict:
    from folivox import lang as languages

    try:
        lang_name = languages.get(book.lang).native
    except ValueError:
        lang_name = book.lang
    return {"book_id": book_id, "title": book.title, "author": book.author, "lang": book.lang,
            "lang_name": lang_name, "format": book.source_format, "year": book.year, "has_cover": bool(book.cover),
            "chars": book.chars, "estimated_seconds": book.estimated_seconds, "chapters": _chapters(book, depth)}


def _voice_json(v) -> dict:
    return {"id": v.id, "name": v.name, "gender": v.gender, "lang": v.lang, "license": v.license,
            "bundled": v.bundled, "default": v.id == catalog.DEFAULT_VOICE, "transcript": v.transcript}


def _registries():
    from folivox.llm import LLMS
    from folivox.qa.asr import ASR_PROVIDERS
    from folivox.tts import ENGINES
    from folivox.voicegen import GENERATORS

    return {r.kind: r for r in (ENGINES, ASR_PROVIDERS, GENERATORS, LLMS)}


def create_app(token: str | None = None, port: int | None = None, data_dir: Path | None = None,
               render=None) -> Starlette:
    state = State(data_dir or Path(user_data_dir("folivox", appauthor=False)) / "ui", render)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"} if port else None

    # ---- handlers -------------------------------------------------------------------------------
    async def index(request: Request):
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    async def upload_book(request: Request):
        from folivox.readers import UnsupportedFormat, read_book

        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            raise ApiError("No file in the request")
        data = await f.read()
        if len(data) > MAX_UPLOAD:
            raise ApiError("File is too large", 413)
        book_id = uuid.uuid4().hex[:12]
        folder = state.data_dir / "uploads" / book_id
        folder.mkdir(parents=True)
        path = folder / (Path(f.filename or "book").name or "book")
        path.write_bytes(data)
        try:
            book = await asyncio.to_thread(read_book, path)
        except UnsupportedFormat as e:
            shutil.rmtree(folder, ignore_errors=True)
            raise ApiError(str(e), 415) from None
        except Exception as e:  # noqa: BLE001 — a broken book must not kill the server
            shutil.rmtree(folder, ignore_errors=True)
            raise ApiError(f"Cannot read the book: {e}") from None
        state.books[book_id] = {"book": book, "path": path}
        return JSONResponse(_book_summary(book_id, book))

    async def book_chapters(request: Request):
        entry = state.book(request.path_params["book_id"])
        book = entry["book"]
        if lang := request.query_params.get("lang"):
            from folivox import lang as languages

            try:
                book.lang = languages.get(lang).code
            except ValueError as e:
                raise ApiError(str(e)) from None
        depth = int(request.query_params.get("depth", 2))
        return JSONResponse(_book_summary(request.path_params["book_id"], book, depth))

    async def get_session(request: Request):
        """What the page had selected, so a reload (or a restart) shows the same screen."""
        try:
            data = json.loads(state.session_file.read_text(encoding="utf-8"))
            state.book(data.get("book_id", ""))  # drop a session whose book is gone
        except (OSError, ValueError, ApiError):
            data = None
        return JSONResponse(data)

    async def put_session(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ApiError("Session must be an object")
        state.data_dir.mkdir(parents=True, exist_ok=True)
        state.session_file.write_text(json.dumps(body), encoding="utf-8")
        return JSONResponse({"ok": True})

    async def list_voices(request: Request):
        lang = request.query_params.get("lang")
        out = [_voice_json(v) for v in catalog.all_voices() if not lang or v.lang == lang]
        return JSONResponse({"voices": out, "user_dir": str(catalog.user_voices_dir())})

    async def voice_sample(request: Request):
        v = catalog.find(request.path_params["voice_id"])
        if v is None or not v.path.exists():
            raise ApiError("Unknown voice", 404)
        return FileResponse(v.path, media_type="audio/flac")

    async def add_voice(request: Request):
        from folivox import lang as languages
        from folivox.tts.voice import VoiceError, load_voice

        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            raise ApiError("No audio file in the request")
        voice_id = str(form.get("id", "")).strip()
        try:
            code = languages.get(str(form.get("lang") or "en")).code
        except ValueError as e:
            raise ApiError(str(e)) from None
        tmp = state.data_dir / "tmp" / uuid.uuid4().hex
        tmp.mkdir(parents=True)
        try:
            audio = tmp / (Path(f.filename or "voice.wav").name or "voice.wav")
            audio.write_bytes(await f.read())
            transcribe = None
            text = str(form.get("transcript") or "").strip()
            if not text:
                from folivox.qa.asr import Transcriber

                transcribe = Transcriber(language=code).transcribe_file
            try:
                v = await asyncio.to_thread(load_voice, audio, text or None, transcribe)
                entry = await asyncio.to_thread(
                    catalog.add, voice_id, audio, v.transcript, name=str(form.get("name") or ""),
                    gender=str(form.get("gender") or ""), lang=code, overwrite=False)
            except (VoiceError, ValueError, FileExistsError) as e:
                raise ApiError(str(e)) from None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return JSONResponse({**_voice_json(entry), "warnings": v.warnings})

    async def delete_voice(request: Request):
        voice_id = request.path_params["voice_id"]
        v = next((x for x in catalog.user() if x.id == voice_id), None)
        if v is None:
            raise ApiError("Only your own voices can be removed", 404)
        catalog.remove(voice_id)
        return JSONResponse({"ok": True})

    def build_options(body: dict, book_entry: dict, kind: str) -> RenderOptions:
        from folivox.text.stress import MODES

        o = body.get("options") or {}
        book = book_entry["book"]
        voice_id = body.get("voice") or ""
        v = catalog.find(voice_id) if voice_id else catalog.default_for(book.lang)
        if v is None:
            raise ApiError(f"Unknown voice {voice_id!r}")
        stress = o.get("stress", "yo")
        if stress not in MODES:
            raise ApiError(f"stress must be one of {', '.join(MODES)}")
        regs = _registries()
        tts = config.provider("tts", o.get("tts") or None) or "cosyvoice3"
        asr = config.provider("asr", o.get("asr") or None) or "auto"
        for kind_name, name in (("tts", tts), ("asr", asr)):
            if name not in regs[kind_name].names():
                raise ApiError(f"Unknown {kind_name} provider {name!r}")
        chapters = body.get("chapters") or []
        spec = ",".join(str(int(n)) for n in chapters) or None
        common = dict(voice_wav=v.path, voice_text=body.get("voice_text") or v.transcript, lang=book.lang,
                      depth=int(o.get("depth", 2)), max_chars=int(o.get("max_chars", 400)), stress=stress,
                      speed=float(o.get("speed", 1.0)), qa=bool(o.get("qa", True)), max_takes=int(o.get("takes", 3)),
                      tts=tts, asr=asr, device=str(o.get("device", "auto")))
        if kind == "preview":
            first = [int(chapters[0])] if chapters else [1]
            work = state.data_dir / "previews" / uuid.uuid4().hex[:8]
            return RenderOptions(output=work / "preview.m4b", work_dir=work / "work", chapters=str(first[0]),
                                 preview=int(o.get("preview_chars", PREVIEW_CHARS)), **common)
        out_dir = Path(str(o.get("output_dir") or Path.home() / "Audiobooks")).expanduser()
        mp3 = bool(o.get("mp3", False))
        stem = Path(book_entry["path"]).stem
        return RenderOptions(output=out_dir / stem if mp3 else out_dir / f"{stem}.m4b", chapters=spec, mp3=mp3,
                             bitrate=str(o.get("bitrate", "64k")), **common)

    async def start_job(request: Request):
        body = await request.json()
        kind = body.get("kind", "render")
        if kind not in ("render", "preview"):
            raise ApiError("kind must be render or preview")
        entry = state.book(body.get("book_id", ""))
        if state.manager.busy():
            raise ApiError("Another job is running; cancel it or wait", 409)
        opts = build_options(body, entry, kind)
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        job = state.manager.start(kind, body["book_id"], entry["book"], opts)
        return JSONResponse(job.summary(), status_code=202)

    def get_job(request: Request):
        job = state.manager.jobs.get(request.path_params["job_id"])
        if job is None:
            raise ApiError("Unknown job", 404)
        return job

    async def job_info(request: Request):
        job = get_job(request)
        chapters = sorted(chapter_files(job.opts.resolved_work_dir()))
        return JSONResponse({**job.summary(), "chapters_built": chapters})

    async def current_job(request: Request):
        job = state.manager.current
        return JSONResponse(job.summary() if job else None)

    async def job_events(request: Request):
        job = get_job(request)

        async def stream():
            idx = int(request.headers.get("last-event-id", -1)) + 1
            while True:
                new, finished = await asyncio.to_thread(job.wait_events, idx)
                for ev in new:
                    yield f"id: {idx}\ndata: {json.dumps(ev)}\n\n"
                    idx += 1
                if finished:
                    return
                if not new:
                    yield ": keep-alive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def job_cancel(request: Request):
        job = get_job(request)
        job.cancel_requested.set()
        return JSONResponse(job.summary())

    async def job_chapter(request: Request):
        job = get_job(request)
        path = chapter_files(job.opts.resolved_work_dir()).get(int(request.path_params["n"]))
        if path is None:
            raise ApiError("Chapter is not built yet", 404)
        return FileResponse(path, media_type="audio/flac")

    async def get_settings(request: Request):
        kinds = {}
        for kind, reg in _registries().items():
            kinds[kind] = {"default": reg.default, "selected": config.provider(kind) or reg.default,
                           "providers": [{"name": p.name, "description": p.description, "local": p.local,
                                          "needs": p.needs} for p in reg.providers()]}
        return JSONResponse({"kinds": kinds, "config_path": str(config.config_path()),
                             "output_dir": str(Path.home() / "Audiobooks")})

    async def put_settings(request: Request):
        import tomli_w

        body = await request.json()
        chosen = body.get("providers") or {}
        regs = _registries()
        for kind, name in chosen.items():
            if kind not in regs or name not in regs[kind].names():
                raise ApiError(f"Unknown {kind} provider {name!r}")
        path = config.config_path()
        data = dict(config.load())
        data["providers"] = {**data.get("providers", {}), **chosen}
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))  # comments are lost on rewrite
        path.write_text(tomli_w.dumps(data), encoding="utf-8")
        config.load.cache_clear()
        return await get_settings(request)

    # ---- plumbing -------------------------------------------------------------------------------
    def check(request: Request) -> JSONResponse | None:
        if allowed_hosts is not None and request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"error": "Bad Host header"}, status_code=403)  # DNS-rebinding guard
        if token and request.url.path.startswith("/api/"):
            given = request.headers.get("x-folivox-token") or request.query_params.get("token") or ""
            if not secrets.compare_digest(given, token):
                return JSONResponse({"error": "Missing or wrong token"}, status_code=401)
        return None

    async def api_error(request: Request, exc: ApiError):
        return JSONResponse({"error": str(exc)}, status_code=exc.status)

    async def bad_request(request: Request, exc: Exception):
        return JSONResponse({"error": f"Bad request: {exc}"}, status_code=400)

    routes = [
        Route("/", index),
        Route("/api/books", upload_book, methods=["POST"]),
        Route("/api/books/{book_id}/chapters", book_chapters),
        Route("/api/session", get_session),
        Route("/api/session", put_session, methods=["PUT"]),
        Route("/api/voices", list_voices),
        Route("/api/voices", add_voice, methods=["POST"]),
        Route("/api/voices/{voice_id}/sample", voice_sample),
        Route("/api/voices/{voice_id}", delete_voice, methods=["DELETE"]),
        Route("/api/jobs", start_job, methods=["POST"]),
        Route("/api/jobs/current", current_job),
        Route("/api/jobs/{job_id}", job_info),
        Route("/api/jobs/{job_id}/events", job_events),
        Route("/api/jobs/{job_id}/cancel", job_cancel, methods=["POST"]),
        Route("/api/jobs/{job_id}/chapters/{n:int}", job_chapter),
        Route("/api/settings", get_settings),
        Route("/api/settings", put_settings, methods=["PUT"]),
    ]
    app = Starlette(routes=routes, exception_handlers={ApiError: api_error, ValueError: bad_request,
                                                      TypeError: bad_request, KeyError: bad_request})
    app.add_middleware(_Guard, check=check)
    app.state.ui = state
    return app


class _Guard:
    """Pure-ASGI middleware (keeps SSE streaming intact): Host and token checks before routing."""

    def __init__(self, app, check):
        self.app, self.check = app, check

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            denied = self.check(Request(scope, receive))
            if denied is not None:
                return await denied(scope, receive, send)
        await self.app(scope, receive, send)
