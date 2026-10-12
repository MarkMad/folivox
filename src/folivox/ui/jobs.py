"""One render job at a time; pipeline events are recorded for the browser.

A real render runs in a child process: a native crash there (CUDA/cuDNN, out of memory) kills only the child,
and the server reports it to the browser instead of dying with it. Its models are freed when it exits.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import queue
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from folivox.pipeline import Cancelled, CostCapReached, Events, RenderOptions


class UIEvents(Events):
    """Records every pipeline event as a JSON-able dict; consumers read ``events[n:]``."""

    def __init__(self, job: Job):
        self.job = job
        self.audio = self.synth = 0.0
        self.retakes = 0
        self.meters: dict = {}

    def cancelled(self) -> bool:
        return self.job.cancel_requested.is_set()

    def stage(self, name, detail=""):
        self.job.emit("stage", name=name, detail=detail or name)

    def warning(self, message):
        self.job.emit("warning", message=message)

    def plan(self, total_chars, done_chars, total_chunks, pending_chunks):
        self.job.total_chars, self.job.done_chars = total_chars, done_chars
        self.job.emit("plan", total_chars=total_chars, done_chars=done_chars, total_chunks=total_chunks,
                      pending_chunks=pending_chunks)

    def step(self, step, attempt=1, attempts=1):
        self.job.emit("step", step=step, attempt=attempt, attempts=attempts)

    def download(self, name, done_bytes, total_bytes):
        from folivox.tts.weights import DownloadMeter

        meter = self.meters.setdefault(name, DownloadMeter())
        speed, eta = meter.update(done_bytes, total_bytes, time.time())
        self.job.emit("download", name=name, done=done_bytes, total=total_bytes, speed=speed, eta=eta)

    def spend(self, chars, usd, cap):
        self.job.emit("spend", chars=chars, usd=usd, cap=cap)

    def layout(self, chapters):
        self.job.emit("layout", chapters=chapters)

    def chunk_started(self, chunk):
        self.job.emit("fragment", chapter=chunk.chapter + 1, idx=chunk.idx, key=chunk.key[:10], text=chunk.text[:90])

    def chunk_done(self, chunk, take, attempts):
        self.audio += take.duration
        self.synth += take.synth_seconds
        self.retakes += max(0, len(attempts) - 1)
        self.job.done_chars += len(chunk.source)
        self.job.emit("progress", done_chars=self.job.done_chars, total_chars=self.job.total_chars,
                      rtf=self.synth / self.audio if self.audio else 0, audio=self.audio, retakes=self.retakes,
                      chapter=chunk.chapter + 1, key=chunk.key[:10], text=chunk.text[:90], duration=take.duration,
                      score=take.score, attempts=len(attempts), chars=len(chunk.source))

    def chapter_built(self, index, title, duration):
        self.job.emit("chapter", index=index + 1, title=title, duration=duration)


class Job:
    def __init__(self, kind: str, book_id: str, opts: RenderOptions):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.book_id, self.opts = kind, book_id, opts
        self.state = "running"  # running | done | cancelled | error
        self.result: str | None = None
        self.error: str | None = None
        self.total_chars = self.done_chars = 0
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.cancel_requested = threading.Event()

    def emit(self, type_: str, **data) -> None:
        with self.cond:
            self.events.append({"type": type_, "t": time.time(), **data})
            self.cond.notify_all()

    def finish(self, state: str, type_: str, **data) -> None:
        """Set the final state and record the closing event atomically."""
        with self.cond:
            self.state = state
            self.events.append({"type": type_, "t": time.time(), **data})
            self.cond.notify_all()

    def wait_events(self, start: int, timeout: float = 15.0) -> tuple[list[dict], bool]:
        """Events from index ``start``; blocks up to ``timeout`` for new ones. Second item: no more will come."""
        with self.cond:
            if len(self.events) <= start and self.state == "running":
                self.cond.wait(timeout)
            new = self.events[start:]
            return new, self.state != "running" and start + len(new) >= len(self.events)

    def summary(self) -> dict:
        return {"id": self.id, "kind": self.kind, "book_id": self.book_id, "state": self.state,
                "result": self.result, "error": self.error, "done_chars": self.done_chars,
                "total_chars": self.total_chars}


class JobManager:
    def __init__(self, render: Callable | None = None, process_target: str = "folivox.pipeline:render"):
        self._render = render
        self._target = process_target  # "module:function" the render process runs (tests swap it)
        self.current: Job | None = None
        self.gen_current: Job | None = None  # a voice-generation job; never shown as the render job
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def busy(self) -> bool:
        return any(j is not None and j.state == "running" for j in (self.current, self.gen_current))

    def start(self, kind: str, book_id: str, book, opts: RenderOptions) -> Job:
        """Start a render; in a child process unless a test injected its own ``render``."""
        with self._lock:
            if self.busy():
                raise RuntimeError("Another job is running")
            job = Job(kind, book_id, opts)
            self.jobs[job.id] = job
            self.current = job
        target = self._run if self._render is not None else self._run_process
        threading.Thread(target=target, args=(job, book), daemon=True, name=f"folivox-job-{job.id}").start()
        return job

    def _run_process(self, job: Job, book) -> None:
        from folivox import diag

        ctx = mp.get_context("spawn")  # never fork a process that may hold CUDA or Metal state
        events, cancel = ctx.Queue(), ctx.Event()
        log = job.opts.resolved_work_dir() / "render-process.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = ctx.Process(target=_child, args=(self._target, book, job.opts, events, cancel, str(log)), daemon=True,
                           name=f"folivox-render-{job.id}")
        diag.event("job started", job=job.id, kind=job.kind, options=diag.options_summary(job.opts), process=True)
        t0 = time.time()
        proc.start()
        final = None
        while final is None:
            if job.cancel_requested.is_set():
                cancel.set()
            try:
                msg = events.get(timeout=0.5)
            except queue.Empty:
                if not proc.is_alive():
                    try:  # the last messages may still be in the pipe
                        msg = events.get(timeout=1)
                    except queue.Empty:
                        break
                else:
                    continue
            kind, type_, data = msg
            if kind == "event":
                if type_ == "plan":
                    job.total_chars, job.done_chars = data["total_chars"], data["done_chars"]
                elif type_ == "progress":
                    job.done_chars = data["done_chars"]
                job.emit(type_, **data)
            else:
                final = (type_, data)
        proc.join(timeout=30)
        secs = round(time.time() - t0, 1)
        if final is None:
            code = proc.exitcode
            tail = _tail(log)
            job.error = (f"The render process crashed (exit code {code}). Last output: {tail}" if tail else
                         f"The render process crashed (exit code {code}).")
            diag.event("job crashed", level=40, job=job.id, exitcode=code, tail=tail, seconds=secs)
            print(f"folivox: {job.error}", file=sys.stderr)
            job.finish("error", "error", message=job.error)
            return
        state, data = final
        if state == "done":
            job.result = data["result"]
            diag.event("job finished", job=job.id, seconds=secs)
            job.finish("done", "done", result=job.result)
        elif state == "cancelled":
            diag.event("job cancelled", job=job.id, seconds=secs)
            job.finish("cancelled", "cancelled", **data)
        else:
            job.error = data["message"]
            diag.event("job failed", level=40, job=job.id, error=job.error, traceback=data.get("traceback"))
            job.finish("error", "error", message=job.error)

    def _run(self, job: Job, book) -> None:
        render = self._render
        if render is None:
            from folivox.pipeline import render
        from folivox import diag

        t0 = time.time()
        diag.event("job started", job=job.id, kind=job.kind, options=diag.options_summary(job.opts))
        try:
            result = render(book, job.opts, UIEvents(job))
            job.result = str(result)
            diag.event("job finished", job=job.id, seconds=round(time.time() - t0, 1))
            job.finish("done", "done", result=job.result)
        except CostCapReached as e:
            diag.event("job stopped at the spending cap", job=job.id)
            job.finish("cancelled", "cancelled", reason="cost_cap", message=str(e))
        except Cancelled:
            diag.event("job cancelled", job=job.id, seconds=round(time.time() - t0, 1))
            job.finish("cancelled", "cancelled")
        except Exception as e:  # noqa: BLE001 — report any failure to the browser
            job.error = str(e) or type(e).__name__
            diag.event("job failed", level=40, exc_info=True, job=job.id, error=job.error)
            job.finish("error", "error", message=job.error)
        finally:
            from folivox import memory

            memory.release()  # a paused studio should not keep the models (~20 GB) in memory

    def start_task(self, job: Job, fn: Callable[[Job], str | None]) -> Job:
        """Run ``fn(job)`` in a worker thread as the current voice-generation job (events and cancel as a render)."""
        with self._lock:
            if self.busy():
                raise RuntimeError("Another job is running")
            self.jobs[job.id] = job
            self.gen_current = job

        def run():
            try:
                job.result = fn(job)
                job.finish("done", "done", result=job.result)
            except Cancelled:
                job.finish("cancelled", "cancelled")
            except Exception as e:  # noqa: BLE001 — report any failure to the browser
                job.error = str(e) or type(e).__name__
                job.finish("error", "error", message=job.error)

        threading.Thread(target=run, daemon=True, name=f"folivox-gen-{job.id}").start()
        return job


class _ChildJob:
    """What ``UIEvents`` needs from a job, inside the render process: events go to the parent's queue."""

    def __init__(self, events, cancel):
        self._events, self.cancel_requested = events, cancel
        self.total_chars = self.done_chars = 0

    def emit(self, type_: str, **data) -> None:
        self._events.put(("event", type_, data))


def _tail(path: Path, lines: int = 6, limit: int = 600) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    keep = [ln.strip() for ln in text.replace("\r", "\n").splitlines() if ln.strip()][-lines:]
    return " | ".join(keep)[-limit:]


def _child(target: str, book, opts: RenderOptions, events, cancel, log: str) -> None:
    """Render process entry point. Native libraries write straight to fds 1 and 2: keep them in a log the
    parent quotes if the process dies without a word."""
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    for std in (1, 2):
        os.dup2(fd, std)
    sys.stdout = open(1, "w", encoding="utf-8", errors="replace", buffering=1, closefd=False)  # noqa: SIM115
    sys.stderr = open(2, "w", encoding="utf-8", errors="replace", buffering=1, closefd=False)  # noqa: SIM115
    import importlib

    mod, _, fn = target.partition(":")
    try:
        render = getattr(importlib.import_module(mod), fn)
        result = render(book, opts, UIEvents(_ChildJob(events, cancel)))
        events.put(("final", "done", {"result": str(result)}))
    except CostCapReached as e:
        events.put(("final", "cancelled", {"reason": "cost_cap", "message": str(e)}))
    except Cancelled:
        events.put(("final", "cancelled", {}))
    except BaseException as e:  # noqa: BLE001 — report any failure to the parent
        import traceback

        traceback.print_exc()
        events.put(("final", "error", {"message": str(e) or type(e).__name__, "traceback": traceback.format_exc()}))
    finally:
        events.close()
        events.join_thread()


def chapter_files(work_dir: Path) -> dict[int, Path]:
    d = work_dir / "chapters"
    return {int(p.stem): p for p in sorted(d.glob("*.flac"))} if d.exists() else {}

