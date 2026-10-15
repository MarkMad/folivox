"""Studio routes for the automatic markup: model choice, character list, background analysis and marking."""

from __future__ import annotations

import threading
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from folivox import markup as mk
from folivox import markup_llm as ml


class Task:
    """One background analysis/marking per book; the page polls ``GET /api/books/{id}/llm/status``."""

    def __init__(self):
        self.state = "idle"  # idle | running | done | error | cancelled
        self.task = ""
        self.stage, self.done, self.total, self.message = "", 0, 0, ""
        self.stats: dict = {}
        self.cancel = threading.Event()

    def snapshot(self) -> dict:
        return {"state": self.state, "task": self.task, "stage": self.stage, "done": self.done, "total": self.total,
                "message": self.message, "stats": self.stats}


def routes(api_error, state, services: dict) -> list[Route]:
    tasks: dict[str, Task] = {}

    def files(bid: str) -> tuple[Path, Path, Path]:
        name = Path(bid).name
        d = state.data_dir
        return d / "characters" / f"{name}.json", d / "markup" / f"{name}.json", d / "llm-cache" / f"{name}.sqlite"

    def task_of(bid: str) -> Task:
        return tasks.setdefault(bid, Task())

    async def models(request: Request):
        from folivox import config, diag
        from folivox.llm import GEMMA_TIERS, Ollama, recommend_model

        ram = diag.ram_gb()
        return JSONResponse({"ram_gb": ram, "recommended": recommend_model(ram),
                             "configured": config.section("llm.ollama").get("model", ""),
                             "installed": Ollama().installed(),
                             "tiers": [{"min_ram_gb": n, "model": t, "download_gb": g, "note": note}
                                       for n, t, g, note in GEMMA_TIERS]})

    async def get_characters(request: Request):
        bid = request.path_params["book_id"]
        state.book(bid)
        f = files(bid)[0]
        try:
            bible = ml.Bible.load(f) if f.is_file() else ml.Bible()
        except ml.LLMError as e:
            raise api_error(str(e)) from None
        return JSONResponse(bible.to_dict())

    async def put_characters(request: Request):
        bid = request.path_params["book_id"]
        state.book(bid)
        try:
            bible = ml.Bible.from_dict(await request.json())
        except (TypeError, ValueError, AttributeError) as e:
            raise api_error(f"Malformed character list: {e}") from None
        for c in bible.characters:
            if not 0 <= c.id < mk.MAX_SPEAKERS:
                raise api_error(f"{c.name}: the speaker id must be 0..{mk.MAX_SPEAKERS - 1}")
        f = files(bid)[0]
        f.parent.mkdir(parents=True, exist_ok=True)
        bible.save(f)
        return JSONResponse(bible.to_dict())

    async def status(request: Request):
        return JSONResponse(task_of(request.path_params["book_id"]).snapshot())

    async def cancel(request: Request):
        t = task_of(request.path_params["book_id"])
        t.cancel.set()
        return JSONResponse(t.snapshot())

    async def start(request: Request):
        bid = request.path_params["book_id"]
        entry = state.book(bid)
        body = await request.json()
        what = body.get("task")
        if what not in ("analyse", "auto"):
            raise api_error("task must be analyse or auto")
        t = task_of(bid)
        if t.state == "running":
            raise api_error("The language model is already working on this book", 409)
        try:
            if "llm" in services:
                llm, model = services["llm"](body.get("llm") or None), str(body.get("model") or "fake")
            else:
                llm, model = ml.make_llm(body.get("llm") or None, body.get("model") or None)
        except ml.LLMError as e:
            raise api_error(str(e), 409) from None
        except Exception as e:  # noqa: BLE001 — a missing key, an unknown provider
            raise api_error(str(e)) from None
        book = entry["book"]
        depth = int(body.get("depth", 2))
        chapters = book.chapters(depth)
        expression = bool(body.get("expression_tags", False))
        sample = int(body["sample"]) if body.get("sample") else None
        only = body.get("chapters")
        chapter_filter = {int(n) - 1 for n in only} if only else None
        bp, mp, cp = files(bid)
        for f in (bp, mp, cp):
            f.parent.mkdir(parents=True, exist_ok=True)
        t.state, t.task, t.message, t.stats = "running", what, "", {}
        t.done = t.total = 0
        t.cancel.clear()

        def progress(stage: str, done: int, total: int, message: str) -> None:
            t.stage, t.done, t.total, t.message = stage, done, total, message

        def work() -> None:
            cache = ml.Cache(cp)
            runner = ml.Runner(llm, model, cache)
            try:
                bible = ml.Bible.load(bp) if bp.is_file() and body.get("resume", True) else ml.Bible()
                if what == "analyse" or bible.done_windows < max(bible.total_windows, 1):
                    bible = ml.analyse(chapters, book.lang, runner, bible, save=lambda b: b.save(bp),
                                       max_windows=sample if what == "analyse" else None, progress=progress,
                                       cancelled=t.cancel.is_set)
                if what == "auto" and not t.cancel.is_set():
                    markup = mk.Markup.load(mp) if mp.is_file() else mk.Markup(depth=depth)

                    def save(m, b):
                        mk.stamp(m, chapters)
                        m.save(mp)
                        b.save(bp)

                    markup, stats = ml.annotate(chapters, book.lang, bible, runner, markup,
                                                expression_tags=expression, chapter_filter=chapter_filter, save=save,
                                                progress=progress, cancelled=t.cancel.is_set, depth=depth)
                    mk.stamp(markup, chapters)
                    markup.save(mp)
                    bible.save(bp)
                    t.stats = stats.__dict__
                t.state = "cancelled" if t.cancel.is_set() else "done"
                t.message = f"{bible.voices_needed()} voices needed" if what == "analyse" else t.message
            except Exception as e:  # noqa: BLE001 — shown to the user; progress is saved
                t.state, t.message = "error", str(e)
            finally:
                cache.close()

        threading.Thread(target=work, daemon=True, name="folivox-llm-markup").start()
        return JSONResponse(t.snapshot(), status_code=202)

    return [Route("/api/llm/models", models),
            Route("/api/books/{book_id}/characters", get_characters),
            Route("/api/books/{book_id}/characters", put_characters, methods=["PUT"]),
            Route("/api/books/{book_id}/llm/start", start, methods=["POST"]),
            Route("/api/books/{book_id}/llm/status", status),
            Route("/api/books/{book_id}/llm/cancel", cancel, methods=["POST"])]
