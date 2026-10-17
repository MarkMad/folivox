"""What the studio does with long work when nobody is looking at it.

Everything long is owned by the server, not by the page: a render runs in a child process, automatic markup,
voice generation and downloads run in server threads, and the page only polls them. Closing a tab therefore
does not stop anything. This module decides what happens next:

* a render may run to the end without a browser (its journal makes it resumable anyway), but the terminal says so;
* work that holds a model in memory and is not resumable (markup by a language model, voice generation, a
  preview render) is stopped, and its model unloaded, once no browser has talked to the server for
  :data:`ORPHAN_SECONDS`;
* downloads and installs use no GPU or RAM and resume by themselves, so they continue.

The page counts as present while it polls (it asks ``/api/jobs/current`` every few seconds), so any request
to the server is the heartbeat.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

ORPHAN_SECONDS = 600.0  # no browser for this long: stop the work that holds a model
NOTICE_SECONDS = 60.0  # no browser for this long: tell the terminal that a render runs on its own


class Presence:
    """When a browser last talked to the server."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.last = clock()

    def touch(self) -> None:
        self.last = self.clock()

    def idle(self) -> float:
        return self.clock() - self.last


def activity(state) -> dict:
    """The running long work, for the page (to warn before it closes) and for the watchdog."""
    m = state.manager
    out: dict = {"render": None, "voicegen": None, "markup": [], "download": None, "install": []}
    cur, gen = m.current, m.gen_current
    if cur is not None and cur.state == "running":
        out["render"] = cur.summary()
    if gen is not None and gen.state == "running":
        out["voicegen"] = gen.summary()
    for bid, t in getattr(state, "markup_tasks", {}).items():
        if t.state == "running":
            out["markup"].append({"book_id": bid, "task": t.task})
    pull = getattr(state, "pull", None)
    if pull is not None and pull.state == "running":
        out["download"] = {"model": pull.model}
    out["install"] = [i.snapshot()["name"] or i.build for i in getattr(state, "installs", ()) if i.state == "running"]
    return out


def stop_orphans(state, say: Callable[[str], None] = print) -> list[str]:
    """Stop the non-resumable work that holds a model; returns what was stopped."""
    stopped: list[str] = []
    for t in getattr(state, "markup_tasks", {}).values():
        if t.state == "running":
            t.release = True
            t.cancel.set()
            stopped.append("automatic markup")
    m = state.manager
    for job in m.running_jobs():
        if job.kind in ("voicegen", "preview"):
            job.cancel_requested.set()
            stopped.append("voice generation" if job.kind == "voicegen" else "preview")
    if stopped:
        say(f"folivox: no browser for {int(ORPHAN_SECONDS // 60)} minutes; stopped {', '.join(stopped)} "
            "to free the model (the saved progress is kept).")
    return stopped


class Watchdog:
    """Looks at :class:`Presence` and the running work; :meth:`tick` is called every few seconds."""

    def __init__(self, state, presence: Presence, say: Callable[[str], None] = print,
                 orphan_after: float = ORPHAN_SECONDS, notice_after: float = NOTICE_SECONDS):
        self.state, self.presence, self.say = state, presence, say
        self.orphan_after, self.notice_after = orphan_after, notice_after
        self.noticed: str | None = None  # the render already announced in the terminal
        self._stop = threading.Event()

    def tick(self) -> None:
        idle = self.presence.idle()
        render = self.state.manager.current
        running = render is not None and render.state == "running"
        if not running:
            self.noticed = None
        elif idle >= self.notice_after and self.noticed != render.id:
            self.noticed = render.id
            self.say("folivox: a render is running without a browser; it continues to the end. "
                     "Ctrl+C stops it (the work is saved and can be resumed).")
        if idle >= self.orphan_after:
            stop_orphans(self.state, self.say)

    def start(self, interval: float = 5.0) -> None:
        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 — a watchdog must never die of one bad tick
                    pass

        threading.Thread(target=loop, daemon=True, name="folivox-watchdog").start()

    def stop(self) -> None:
        self._stop.set()
