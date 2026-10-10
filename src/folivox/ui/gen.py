"""Voice generation with a cloud provider for the web UI: takes → speech-recognition ranking → pick one.

Runs as a job of :class:`folivox.ui.jobs.JobManager` so it streams the same kind of events as a render
(``stage``, ``take``, ``takes``, ``done`` / ``cancelled`` / ``error``) and is cancelled the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from folivox.pipeline import Cancelled
from folivox.ui.jobs import Job


class GenJob(Job):
    def __init__(self, provider: str, book_id: str, out_dir: Path, params: dict):
        super().__init__("voicegen", book_id, None)  # type: ignore[arg-type] — no RenderOptions
        self.provider, self.out_dir, self.params = provider, out_dir, params
        self.takes: list[dict] = []

    def summary(self) -> dict:
        return {**super().summary(), "provider": self.provider}


def run_generation(job: GenJob, gen, texts: list[str], *, asr_factory: Callable[[str], object],
                   wave: Callable[[Path], dict]) -> str:
    """Generate ``takes`` per text, rank them with ASR, publish the ranking as a ``takes`` event."""
    from folivox.voices.design import generate_takes, score_takes

    p = job.params
    n_takes, lang = p["takes"], p["lang"]
    total = len(texts) * n_takes
    done = [0]

    def progress(_job, seconds):
        done[0] += 1
        job.emit("take", n=done[0], total=total, seconds=round(seconds, 1))
        if job.cancel_requested.is_set():
            raise Cancelled

    job.emit("stage", name="generate", detail=f"Generating {total} takes with {gen.label or gen.name}")
    paths = generate_takes(gen, texts, lang, job.out_dir, description=p["description"], speaker=p["speaker"],
                           takes=n_takes, prefix="take", progress=progress)
    if job.cancel_requested.is_set():
        raise Cancelled
    by_path = {path: texts[i // n_takes] for i, path in enumerate(paths)}
    job.emit("stage", name="score", detail="Checking the takes with speech recognition")
    ranked = score_takes(paths, by_path, asr_factory(lang), lang)
    if job.cancel_requested.is_set():
        raise Cancelled
    job.takes = [{"name": c.path.name, "duration": round(c.duration, 1), "score": c.score, "text": c.text,
                  "heard": c.transcript, **wave(c.path)} for c in ranked]
    job.emit("takes", takes=job.takes)
    return str(job.out_dir)
