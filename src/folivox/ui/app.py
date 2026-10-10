"""Starlette app behind ``folivox ui``: a thin JSON/SSE layer over the same code the CLI uses."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import shutil
import uuid
from pathlib import Path

from platformdirs import user_data_dir
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from folivox import config
from folivox import voices as catalog
from folivox.pipeline import RenderOptions
from folivox.ui.jobs import JobManager, chapter_files

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 200 * 1024 * 1024
PREVIEW_CHARS = 600


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


class State:
    def __init__(self, data_dir: Path, render=None):
        self.data_dir = data_dir
        self.books: dict[str, dict] = {}
        self.manager = JobManager(render)
        self.gen_jobs: dict = {}

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


_PEAKS: dict[tuple[str, float], dict] = {}


def _wave(path: Path, bars: int = 64) -> dict:
    """Waveform thumbnail of a voice sample: ``{peaks: [0..100]*bars, seconds}`` (empty without soundfile)."""
    try:
        key = (str(path), path.stat().st_mtime)
        if key not in _PEAKS:
            import numpy as np
            import soundfile as sf

            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            mono = np.abs(data).max(axis=1)
            chunks = np.array_split(mono, bars)
            peaks = np.array([c.max() if c.size else 0.0 for c in chunks])
            peaks = peaks / (peaks.max() or 1.0)
            _PEAKS[key] = {"peaks": [int(round(100 * p)) for p in peaks], "seconds": round(len(mono) / sr, 1)}
        return _PEAKS[key]
    except Exception:  # noqa: BLE001 — a thumbnail is a nicety
        return {"peaks": [], "seconds": 0}


def _voice_json(v) -> dict:
    return {**_wave(v.path), "id": v.id, "name": v.name, "gender": v.gender, "lang": v.lang, "license": v.license,
            "bundled": v.bundled, "commercial": v.commercial, "default": v.id == catalog.DEFAULT_VOICE,
            "transcript": v.transcript}


def _registries():
    from folivox.llm import LLMS
    from folivox.qa.asr import ASR_PROVIDERS
    from folivox.tts import ENGINES
    from folivox.voicegen import GENERATORS

    return {r.kind: r for r in (ENGINES, ASR_PROVIDERS, GENERATORS, LLMS)}


def create_app(token: str | None = None, port: int | None = None, data_dir: Path | None = None,
               render=None, services: dict | None = None) -> Starlette:
    """``services`` (tests): ``generator(name)``, ``llm(name)`` and ``asr(lang)`` factories replacing the real ones."""
    state = State(data_dir or Path(user_data_dir("folivox", appauthor=False)) / "ui", render)
    services = services or {}
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

    def read_favorites() -> list[str]:
        try:
            ids = json.loads((state.data_dir / "favorites.json").read_text(encoding="utf-8"))
            return [i for i in ids if isinstance(i, str)]
        except (OSError, ValueError):
            return []

    async def put_favorites(request: Request):
        ids = (await request.json()).get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) and len(i) <= 64 for i in ids):
            raise ApiError("ids must be a list of voice ids")
        state.data_dir.mkdir(parents=True, exist_ok=True)
        (state.data_dir / "favorites.json").write_text(json.dumps(sorted(set(ids))), encoding="utf-8")
        return JSONResponse({"ok": True})

    async def list_voices(request: Request):
        lang = request.query_params.get("lang")
        voices = [v for v in catalog.all_voices() if not lang or v.lang == lang]
        auto = {code: catalog.default_for(code).id for code in sorted({v.lang for v in catalog.all_voices()})}
        return JSONResponse({"voices": [_voice_json(v) for v in voices], "auto": auto, "favorites": read_favorites(),
                             "user_dir": str(catalog.user_voices_dir())})

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

    async def denoise(request: Request):
        """WAV in → WAV out with steady background noise reduced (for the A/B check before adding a voice)."""
        import io

        import soundfile as sf

        from folivox.audio.denoise import reduce_noise

        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            raise ApiError("No audio file in the request")
        data, sr = sf.read(io.BytesIO(await f.read()), dtype="float32", always_2d=True)
        try:
            cleaned = await asyncio.to_thread(reduce_noise, data.mean(axis=1), sr)
        except RuntimeError as e:
            raise ApiError(str(e), 501) from None
        out = io.BytesIO()
        sf.write(out, cleaned, sr, format="WAV", subtype="PCM_16")
        return Response(out.getvalue(), media_type="audio/wav")

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
        if job.opts is None:
            return JSONResponse({**job.summary(), "takes": getattr(job, "takes", [])})
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

    async def job_reveal(request: Request):
        """Show the finished file in the system file manager (only the result of a job of this server)."""
        import subprocess
        import sys

        job = get_job(request)
        if job.state != "done" or not job.result or not Path(job.result).exists():
            raise ApiError("Nothing to show yet", 404)
        target = Path(job.result)
        if sys.platform == "darwin":
            cmd = ["open", "-R", str(target)]
        elif sys.platform == "win32":
            cmd = ["explorer", f"/select,{target}"]
        else:
            cmd = ["xdg-open", str(target if target.is_dir() else target.parent)]
        subprocess.Popen(cmd)  # noqa: S603 — fixed argv, path comes from our own job result
        return JSONResponse({"ok": True})

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

    def key_names() -> list[dict]:
        """Env var names the cloud providers read: the defaults plus any ``api_key_env`` in the config."""
        owners: dict[str, list[str]] = {}
        for kind, reg in _registries().items():
            for p in reg.providers():
                if not p.local and p.needs.isupper():
                    owners.setdefault(config.section(f"{kind}.{p.name}").get("api_key_env", p.needs), []).append(
                        f"{kind}/{p.name}")
        return [{"name": n, "used_by": u} for n, u in sorted(owners.items())]

    def mask(value: str) -> str:
        return "•" * 8 + value[-4:] if len(value) > 8 else "•" * 8

    async def get_keys(request: Request):
        out = []
        for k in key_names():
            stored = config.keychain_get(k["name"])
            out.append({**k, "env": bool(os.environ.get(k["name"])), "saved": bool(stored),
                        "masked": mask(stored) if stored else ""})
        return JSONResponse({"keys": out})  # the full value never leaves the server

    async def put_key(request: Request):
        name = request.path_params["name"]
        if name not in {k["name"] for k in key_names()}:
            raise ApiError("Unknown key name", 404)
        value = str((await request.json()).get("value", "")).strip()
        if not value:
            raise ApiError("Empty key")
        try:
            config.keychain_set(name, value)
        except Exception as e:  # noqa: BLE001
            raise ApiError(f"Cannot use the OS keychain: {type(e).__name__}") from None
        return await get_keys(request)

    async def delete_key(request: Request):
        name = request.path_params["name"]
        try:
            config.keychain_delete(name)
        except Exception as e:  # noqa: BLE001
            raise ApiError(f"Cannot use the OS keychain: {type(e).__name__}") from None
        return await get_keys(request)

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


    # ---- cloud voice generation -------------------------------------------------------------------
    GEN_TAKE = re.compile(r"^take_t\d+_\d+\.wav$")

    def gen_class(name: str):
        from folivox.voicegen.cloud import cloud_providers

        cls = cloud_providers().get(name)
        if cls is None:
            raise ApiError(f"Unknown cloud voice provider {name!r}", 404)
        return cls

    def key_state(cls) -> dict:
        env = config.section(f"voicegen.{cls.name}").get("api_key_env", cls.key_env)
        stored = config.keychain_get(env)
        return {"key_env": env, "key_in_env": bool(os.environ.get(env)), "key_saved": bool(stored),
                "key_masked": mask(stored) if stored else ""}

    def make_generator(name: str):
        from folivox.providers import ProviderError

        cls = gen_class(name)
        ks = key_state(cls)
        if not (ks["key_in_env"] or ks["key_saved"]):
            raise ApiError(f"No API key for {cls.label}: paste it below or set {ks['key_env']} in the environment",
                           412, missing_key=ks["key_env"], provider=name)
        try:
            return services["generator"](name) if "generator" in services else GENERATORS_create(name)
        except ProviderError as e:
            raise ApiError(str(e), 502) from None
        except ValueError as e:
            raise ApiError(str(e), 412, missing_key=ks["key_env"], provider=name) from None

    def GENERATORS_create(name: str):
        from folivox.voicegen import GENERATORS

        return GENERATORS.create(name)

    async def gen_call(fn, *args):
        """Run a blocking provider call; a provider failure becomes a clear API error (never the key)."""
        from folivox.providers import ProviderError

        try:
            return await asyncio.to_thread(fn, *args)
        except ProviderError as e:
            raise ApiError(str(e), 429 if getattr(e, "kind", "") == "rate_limit" else 502) from None

    def book_text(book, limit: int = 60000) -> str:
        parts, n = [], 0
        for ch in book.chapters():
            for b in ch.blocks:
                parts.append(b.text)
                n += len(b.text)
                if n > limit:
                    return "\n".join(parts)
        return "\n".join(parts)

    def make_llm(body: dict):
        from folivox.llm import LLMS
        from folivox.providers import ProviderError

        name = config.provider("llm", body.get("llm") or None) or LLMS.default
        try:
            if "llm" in services:
                return services["llm"](name)
            return LLMS.create(name, model=body.get("model") or None)
        except (ProviderError, ValueError) as e:
            raise ApiError(str(e), 412) from None

    async def gen_providers(request: Request):
        from folivox.voicegen.cloud import COMMERCIAL_NOTICE, cloud_providers

        out = [{**cls.capabilities(), **key_state(cls)} for cls in cloud_providers().values()]
        return JSONResponse({"providers": out, "notice": COMMERCIAL_NOTICE})

    async def gen_voices(request: Request):
        name = request.path_params["provider"]
        gen = make_generator(name)
        if "preset" not in gen.modes:
            return JSONResponse({"voices": []})
        speakers = await gen_call(gen.speakers, request.query_params.get("lang"))
        lang = request.query_params.get("lang")
        names = getattr(gen, "names", {})
        return JSONResponse({"voices": [{"id": k, "lang": v[0], "gender": v[1], "name": names.get(k, k)}
                                        for k, v in speakers.items() if not lang or v[0] in (lang, "")]})

    async def gen_suggest(request: Request):
        from folivox.voices.suggest import suggest_design_prompt

        body = await request.json()
        entry = state.book(body.get("book_id", ""))
        book = entry["book"]
        llm = make_llm(body)
        try:
            prompt = await asyncio.to_thread(suggest_design_prompt, book_text(book, 12000), book.lang, llm,
                                             title=book.title or "", author=book.author or "")
        except ValueError as e:
            raise ApiError(str(e), 502) from None
        except Exception as e:  # noqa: BLE001 — LLM server down, bad key…
            raise ApiError(f"The text LLM failed: {e}", 502) from None
        return JSONResponse({"prompt": prompt, "llm": getattr(llm, "name", "")})

    async def gen_texts(request: Request):
        from folivox import lang as languages
        from folivox.voices.design import pick_book_texts, safe_texts

        body = await request.json()
        try:
            code = languages.get(str(body.get("lang") or "en")).code
        except ValueError as e:
            raise ApiError(str(e)) from None
        if body.get("source") == "book":
            book = state.book(body.get("book_id", ""))["book"]
            llm = make_llm(body)
            try:
                found = await asyncio.to_thread(pick_book_texts, book_text(book), book.lang, llm, 3)
            except Exception as e:  # noqa: BLE001
                raise ApiError(f"The text LLM failed: {e}", 502) from None
            if not found:
                raise ApiError("No easy passage found in the book; use the built-in text or write your own", 404)
            return JSONResponse({"texts": found, "lang": book.lang})
        texts = safe_texts(code)
        if not texts:
            raise ApiError(f"No built-in text for {code!r}; write your own", 404)
        return JSONResponse({"texts": texts, "lang": code})

    def gen_params(body: dict) -> dict:
        from folivox import lang as languages

        cls = gen_class(str(body.get("provider", "")))
        mode = body.get("mode") or cls.modes[0]
        if mode not in cls.modes:
            raise ApiError(f"{cls.label} supports: {', '.join(cls.modes)}")
        try:
            lang = languages.get(str(body.get("lang") or "en")).code
        except ValueError as e:
            raise ApiError(str(e)) from None
        if lang not in cls.languages:
            raise ApiError(f"{cls.label} does not list {lang!r}; supported: {', '.join(cls.languages)}")
        texts = [" ".join(str(t).split()) for t in (body.get("texts") or [])]
        texts = [t for t in texts if t]
        if not 1 <= len(texts) <= 5:
            raise ApiError("Give one to five texts to be spoken")
        if any(len(t) > cls.max_chars for t in texts):
            raise ApiError(f"A text is longer than {cls.max_chars} characters")
        takes = int(body.get("takes", 3))
        if not 1 <= takes <= 6:
            raise ApiError("takes must be between 1 and 6")
        description = " ".join(str(body.get("description") or "").split())
        speaker = str(body.get("speaker") or "").strip()
        if mode == "design" and len(description) < 10:
            raise ApiError("Describe the voice (at least a few words), or press Suggest")
        if mode == "preset" and not speaker:
            raise ApiError("Pick one of the provider's voices")
        if len(description) > 1000:
            raise ApiError("The description is too long (1000 characters at most)")
        return {"cls": cls, "mode": mode, "lang": lang, "texts": texts, "takes": takes, "description": description,
                "speaker": speaker}

    async def gen_estimate(request: Request):
        from folivox.voicegen.cloud import COMMERCIAL_NOTICE

        prm = gen_params(await request.json())
        cls = prm["cls"]
        est = cls.estimate_for(sum(len(t) for t in prm["texts"]), prm["takes"], prm["mode"])
        return JSONResponse({**est, "notice": COMMERCIAL_NOTICE, "terms_url": cls.terms_url})

    async def gen_start(request: Request):
        from folivox.ui.gen import GenJob, run_generation

        body = await request.json()
        prm = gen_params(body)
        if body.get("acknowledged") is not True:
            raise ApiError("Confirm that the text is sent to the provider and billed to your account", 400)
        if state.manager.busy():
            raise ApiError("Another job is running; cancel it or wait", 409)
        name = prm["cls"].name
        gen = make_generator(name)
        gen.mode = prm["mode"]
        out_dir = state.data_dir / "gen" / uuid.uuid4().hex[:10]
        out_dir.mkdir(parents=True)
        job = GenJob(name, str(body.get("book_id") or ""), out_dir, {k: v for k, v in prm.items() if k != "cls"})
        texts = prm["texts"]

        def asr_factory(lang):
            if "asr" in services:
                return services["asr"](lang)
            from folivox.qa.asr import Transcriber

            return Transcriber(language=lang)

        try:
            state.manager.start_task(job, lambda j: run_generation(j, gen, texts, asr_factory=asr_factory, wave=_wave))
        except RuntimeError as e:
            raise ApiError(str(e), 409) from None
        state.gen_jobs[job.id] = job
        return JSONResponse(job.summary(), status_code=202)

    def get_gen_job(request: Request):
        job = state.gen_jobs.get(request.path_params["job_id"])
        if job is None:
            raise ApiError("Unknown generation job", 404)
        return job

    async def gen_take(request: Request):
        job = get_gen_job(request)
        name = request.path_params["name"]
        path = job.out_dir / name
        if not GEN_TAKE.match(name) or not path.is_file():
            raise ApiError("Unknown take", 404)
        return FileResponse(path, media_type="audio/wav")

    async def gen_add(request: Request):
        from folivox import lang as languages

        job = get_gen_job(request)
        body = await request.json()
        take = next((t for t in job.takes if t["name"] == body.get("take")), None)
        if take is None:
            raise ApiError("Pick one of the generated takes", 404)
        cls = gen_class(job.provider)
        try:
            code = languages.get(str(body.get("lang") or job.params["lang"])).code
            entry = await asyncio.to_thread(
                catalog.add, str(body.get("id", "")).strip(), job.out_dir / take["name"], take["text"],
                name=str(body.get("name") or ""), gender=str(body.get("gender") or ""), lang=code,
                source=f"{cls.label} (commercial API): {job.params['description'] or job.params['speaker']}",
                license=cls.license, url=cls.terms_url, commercial=True)
        except (ValueError, FileExistsError) as e:
            raise ApiError(str(e)) from None
        return JSONResponse(_voice_json(entry))

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
        return JSONResponse({"error": str(exc), **exc.extra}, status_code=exc.status)

    async def bad_request(request: Request, exc: Exception):
        return JSONResponse({"error": f"Bad request: {exc}"}, status_code=400)

    routes = [
        Route("/", index),
        Route("/api/books", upload_book, methods=["POST"]),
        Route("/api/books/{book_id}/chapters", book_chapters),
        Route("/api/session", get_session),
        Route("/api/session", put_session, methods=["PUT"]),
        Route("/api/favorites", put_favorites, methods=["PUT"]),
        Route("/api/voices", list_voices),
        Route("/api/voices", add_voice, methods=["POST"]),
        Route("/api/denoise", denoise, methods=["POST"]),
        Route("/api/voices/{voice_id}/sample", voice_sample),
        Route("/api/voices/{voice_id}", delete_voice, methods=["DELETE"]),
        Route("/api/jobs", start_job, methods=["POST"]),
        Route("/api/jobs/current", current_job),
        Route("/api/jobs/{job_id}", job_info),
        Route("/api/jobs/{job_id}/events", job_events),
        Route("/api/jobs/{job_id}/cancel", job_cancel, methods=["POST"]),
        Route("/api/jobs/{job_id}/reveal", job_reveal, methods=["POST"]),
        Route("/api/jobs/{job_id}/chapters/{n:int}", job_chapter),
        Route("/api/settings", get_settings),
        Route("/api/settings", put_settings, methods=["PUT"]),
        Route("/api/gen/providers", gen_providers),
        Route("/api/gen/suggest", gen_suggest, methods=["POST"]),
        Route("/api/gen/texts", gen_texts, methods=["POST"]),
        Route("/api/gen/estimate", gen_estimate, methods=["POST"]),
        Route("/api/gen/start", gen_start, methods=["POST"]),
        Route("/api/gen/voices/{provider}", gen_voices),
        Route("/api/gen/{job_id}/takes/{name}", gen_take),
        Route("/api/gen/{job_id}/add", gen_add, methods=["POST"]),
        Route("/api/keys", get_keys),
        Route("/api/keys/{name}", put_key, methods=["PUT"]),
        Route("/api/keys/{name}", delete_key, methods=["DELETE"]),
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
