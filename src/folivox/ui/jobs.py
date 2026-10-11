"""One render job at a time, run in a worker thread; pipeline events are recorded for the browser."""

from __future__ import annotations

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
        self.job.emit("download", name=name, done=done_bytes, total=total_bytes)

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
    def __init__(self, render: Callable | None = None):
        self._render = render
        self.current: Job | None = None
        self.gen_current: Job | None = None  # a voice-generation job; never shown as the render job
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def busy(self) -> bool:
        return any(j is not None and j.state == "running" for j in (self.current, self.gen_current))

    def start(self, kind: str, book_id: str, book, opts: RenderOptions) -> Job:
        with self._lock:
            if self.busy():
                raise RuntimeError("Another job is running")
            job = Job(kind, book_id, opts)
            self.jobs[job.id] = job
            self.current = job
        threading.Thread(target=self._run, args=(job, book), daemon=True, name=f"folivox-job-{job.id}").start()
        return job

    def _run(self, job: Job, book) -> None:
        render = self._render
        if render is None:
            from folivox.pipeline import render
        try:
            result = render(book, job.opts, UIEvents(job))
            job.result = str(result)
            job.finish("done", "done", result=job.result)
        except CostCapReached as e:
            job.finish("cancelled", "cancelled", reason="cost_cap", message=str(e))
        except Cancelled:
            job.finish("cancelled", "cancelled")
        except Exception as e:  # noqa: BLE001 — report any failure to the browser
            job.error = str(e) or type(e).__name__
            job.finish("error", "error", message=job.error)

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


def chapter_files(work_dir: Path) -> dict[int, Path]:
    d = work_dir / "chapters"
    return {int(p.stem): p for p in sorted(d.glob("*.flac"))} if d.exists() else {}

