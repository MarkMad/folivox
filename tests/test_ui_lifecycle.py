"""What the studio does with long work when the browser goes away: it is server-owned, orphans are stopped."""

import threading
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402
from test_markup_llm import FakeLLM  # noqa: E402
from test_ui_markup_llm import BOOK, TOKEN, upload, wait  # noqa: E402, F401

from folivox import config  # noqa: E402
from folivox.pipeline import Cancelled  # noqa: E402
from folivox.ui import lifecycle  # noqa: E402
from folivox.ui.app import create_app  # noqa: E402


class SlowLLM(FakeLLM):
    """Answers like the fake model but takes its time, and notes when it was told to unload."""

    def __init__(self, delay=0.05):
        super().__init__()
        self.delay, self.unloaded = delay, threading.Event()

    def complete_json(self, prompt, system=None, temperature=0.2):
        time.sleep(self.delay)
        return super().complete_json(prompt, system, temperature)

    def unload(self):
        self.unloaded.set()


def slow_render(book, opts, events):
    while not events.cancelled():
        time.sleep(0.02)
    raise Cancelled


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    config.load.cache_clear()
    holder = {"llm": SlowLLM()}
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=slow_render,
                     services={"llm": lambda name: holder["llm"]})
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    c.holder, c.app_, c.data_dir = holder, app, tmp_path / "ui"
    yield c
    app.state.shutdown()
    config.load.cache_clear()


def test_markup_run_does_not_need_the_page(studio):
    """No status polling at all (a closed tab): the run still finishes and writes its files."""
    bid = upload(studio)
    assert studio.post(f"/api/books/{bid}/llm/start", json={"task": "auto"}).status_code == 202
    task = studio.app_.state.ui.markup_tasks[bid]
    deadline = time.time() + 20
    while task.state == "running" and time.time() < deadline:
        time.sleep(0.05)
    assert task.state == "done"
    assert (studio.data_dir / "markup" / f"{bid}.json").is_file()
    assert not studio.holder["llm"].unloaded.is_set()  # a finished run leaves the model to Ollama's keep-alive


def test_activity_lists_running_work_and_a_reopened_page_can_ask(studio):
    bid = upload(studio)
    studio.holder["llm"].delay = 0.3
    studio.post(f"/api/books/{bid}/llm/start", json={"task": "auto"})
    act = studio.get("/api/activity").json()
    assert act["markup"] == [{"book_id": bid, "task": "auto"}] and act["render"] is None
    assert studio.get("/api/ping").json()["busy"] is True
    studio.post(f"/api/books/{bid}/llm/cancel")
    wait(studio, bid)
    assert studio.get("/api/activity").json()["markup"] == []


def test_stopped_markup_unloads_the_model(studio):
    bid = upload(studio)
    studio.holder["llm"].delay = 0.2
    studio.post(f"/api/books/{bid}/llm/start", json={"task": "auto"})
    studio.post(f"/api/books/{bid}/llm/cancel")
    assert wait(studio, bid)["state"] == "cancelled"
    assert studio.holder["llm"].unloaded.wait(5)


def test_orphaned_markup_is_stopped_and_the_model_unloaded(studio):
    bid = upload(studio)
    studio.holder["llm"].delay = 0.2
    studio.post(f"/api/books/{bid}/llm/start", json={"task": "auto"})
    now = [1000.0]
    presence = lifecycle.Presence(lambda: now[0])
    said: list[str] = []
    dog = lifecycle.Watchdog(studio.app_.state.ui, presence, said.append)
    dog.tick()
    assert studio.get(f"/api/books/{bid}/llm/status").json()["state"] == "running"  # the browser was just here
    now[0] += lifecycle.ORPHAN_SECONDS + 1
    dog.tick()
    assert wait(studio, bid)["state"] == "cancelled"
    assert studio.holder["llm"].unloaded.wait(5)
    assert any("stopped automatic markup" in line for line in said)


def test_render_runs_on_without_a_browser_and_the_terminal_says_so(studio):
    from test_ui import upload as upload_book

    b = upload_book(studio)
    job = studio.post("/api/jobs", json={"kind": "render", "book_id": b["book_id"], "chapters": [1],
                                         "options": {"output_dir": str(studio.data_dir / "out"), "qa": False}}).json()
    now = [0.0]
    presence = lifecycle.Presence(lambda: now[0])
    said: list[str] = []
    dog = lifecycle.Watchdog(studio.app_.state.ui, presence, said.append)
    now[0] += lifecycle.ORPHAN_SECONDS * 2
    dog.tick()
    dog.tick()
    assert studio.get(f"/api/jobs/{job['id']}").json()["state"] == "running"  # a render is resumable: it goes on
    assert len([s for s in said if "without a browser" in s]) == 1  # said once, not every tick
    studio.post(f"/api/jobs/{job['id']}/cancel")


def test_requests_are_the_heartbeat(studio):
    presence_idle = []
    state = studio.app_.state
    state.watchdog.presence.last -= 500
    presence_idle.append(state.watchdog.presence.idle())
    studio.get("/api/activity")
    assert state.watchdog.presence.idle() < presence_idle[0] - 400
    state.watchdog.presence.last -= 500
    studio.get("/api/ping")  # `folivox ui` asking who is on the port is no browser
    assert state.watchdog.presence.idle() >= 500


def test_shutdown_cancels_render_and_markup(studio):
    bid = upload(studio)
    from test_ui import upload as upload_book

    b = upload_book(studio)
    studio.holder["llm"].delay = 0.2
    studio.post(f"/api/books/{bid}/llm/start", json={"task": "auto"})
    job = studio.post("/api/jobs", json={"kind": "render", "book_id": b["book_id"], "chapters": [1],
                                         "options": {"output_dir": str(studio.data_dir / "out"), "qa": False}}).json()
    studio.app_.state.shutdown()
    assert studio.get(f"/api/jobs/{job['id']}").json()["state"] == "cancelled"
    assert studio.get(f"/api/books/{bid}/llm/status").json()["state"] == "cancelled"
    assert studio.holder["llm"].unloaded.is_set()


def test_stop_all_kills_a_render_process_that_ignores_cancel(tmp_path):
    from folivox.book import Book
    from folivox.pipeline import RenderOptions
    from folivox.ui.jobs import JobManager

    m = JobManager(process_target="render_fakes:deaf")
    job = m.start("render", "b", Book(title="t"), RenderOptions(output=tmp_path / "x.m4b"))
    deadline = time.time() + 60
    while not job.events and time.time() < deadline:
        time.sleep(0.1)
    m.stop_all(wait=1)
    assert job.proc is not None and not job.proc.is_alive()
    deadline = time.time() + 10
    while job.state == "running" and time.time() < deadline:
        time.sleep(0.1)
    assert job.state == "error"  # the child was killed, so the parent reports a crash, not a hang
