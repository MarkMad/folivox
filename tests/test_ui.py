import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402

from folivox.pipeline import Cancelled  # noqa: E402
from folivox.ui.app import create_app  # noqa: E402

TOKEN = "t0ken"
BOOK = ("Chapter 1\n\n" + "It was a quiet morning in the village. " * 12 + "\n\nChapter 2\n\n"
        + "The river was cold and bright. " * 12 + "\n").encode()


def fake_render(book, opts, events):
    """Stands in for pipeline.render: emits the same events without any model."""
    events.stage("plan", "Preparing text")
    events.plan(100, 0, 2, 2)
    for i in range(2):
        if events.cancelled():
            raise Cancelled
        chunk = SimpleNamespace(source="x" * 50, chapter=0, idx=i, key=f"key{i}", text="x")
        events.chunk_done(chunk, SimpleNamespace(duration=2.0, synth_seconds=1.0, score=0.0), [0.0])
        time.sleep(0.05)
    work = opts.resolved_work_dir() / "chapters"
    work.mkdir(parents=True, exist_ok=True)
    (work / "001.flac").write_bytes(b"fLaC")
    events.chapter_built(0, "Chapter 1", 2.0)
    return opts.output


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    from folivox import config

    config.load.cache_clear()
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=fake_render)
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    yield c
    config.load.cache_clear()


def upload(client):
    r = client.post("/api/books", files={"file": ("tale.txt", BOOK, "text/plain")})
    assert r.status_code == 200, r.text
    return r.json()


def wait_done(client, job_id):
    for _ in range(100):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_auth_and_host_guard(client):
    assert client.get("/").status_code == 200  # the page itself needs no token
    assert client.get("/api/voices", headers={"X-Folivox-Token": "wrong"}).status_code == 401
    assert client.get("/api/voices", headers={"Host": "evil.example"}).status_code == 403


def test_book_upload_and_chapters(client):
    b = upload(client)
    assert b["title"] and b["chapters"] and b["chapters"][0]["n"] == 1
    r = client.get(f"/api/books/{b['book_id']}/chapters?depth=1&lang=de")
    assert r.json()["lang"] == "de"
    assert client.post("/api/books", files={"file": ("x.xyz", b"?", "text/plain")}).status_code == 415


def test_voices_listing_and_sample(client):
    voices = client.get("/api/voices").json()["voices"]
    assert voices
    r = client.get(f"/api/voices/{voices[0]['id']}/sample")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/flac"
    bundled = next(v for v in voices if v["bundled"])
    assert client.delete(f"/api/voices/{bundled['id']}").status_code == 404  # bundled voices cannot be removed


def test_render_job_events_and_chapter_audio(client, tmp_path):
    b = upload(client)
    body = {"kind": "render", "book_id": b["book_id"], "chapters": [1],
            "options": {"output_dir": str(tmp_path / "out"), "qa": False}}
    r = client.post("/api/jobs", json=body)
    assert r.status_code == 202, r.text
    job = r.json()["id"]
    assert wait_done(client, job)["state"] == "done"
    types = [line for line in client.get(f"/api/jobs/{job}/events").text.splitlines() if line.startswith("data:")]
    joined = "\n".join(types)
    for t in ("stage", "plan", "progress", "chapter", "done"):
        assert f'"type": "{t}"' in joined
    assert client.get(f"/api/jobs/{job}/chapters/1").content == b"fLaC"
    assert client.get(f"/api/jobs/{job}/chapters/9").status_code == 404


def test_busy_and_cancel(client, tmp_path, monkeypatch):
    def slow(book, opts, events):
        while not events.cancelled():
            time.sleep(0.02)
        raise Cancelled

    client.app.state.ui.manager._render = slow
    b = upload(client)
    body = {"kind": "preview", "book_id": b["book_id"], "chapters": [1], "options": {"qa": False}}
    job = client.post("/api/jobs", json=body).json()["id"]
    assert client.post("/api/jobs", json=body).status_code == 409
    client.post(f"/api/jobs/{job}/cancel")
    assert wait_done(client, job)["state"] == "cancelled"


def test_bad_options_are_rejected(client):
    b = upload(client)
    r = client.post("/api/jobs", json={"book_id": b["book_id"], "chapters": [1], "options": {"stress": "loud"}})
    assert r.status_code == 400
    r = client.post("/api/jobs", json={"book_id": b["book_id"], "voice": "nobody", "chapters": [1]})
    assert r.status_code == 400


def test_settings_roundtrip(client, tmp_path):
    s = client.get("/api/settings").json()
    assert set(s["kinds"]) == {"tts", "asr", "voicegen", "llm"}
    llm_names = [p["name"] for p in s["kinds"]["llm"]["providers"]]
    r = client.put("/api/settings", json={"providers": {"llm": llm_names[-1]}})
    assert r.status_code == 200 and r.json()["kinds"]["llm"]["selected"] == llm_names[-1]
    assert client.put("/api/settings", json={"providers": {"llm": "nope"}}).status_code == 400


def test_session_survives_reload_and_restart(client, tmp_path):
    assert client.get("/api/session").json() is None
    b = upload(client)
    saved = {"book_id": b["book_id"], "chapters": [2], "voice": "", "lang": "en", "depth": 2,
             "options": {"o-speed": "0.9"}}
    assert client.put("/api/session", json=saved).status_code == 200
    assert client.get("/api/session").json() == saved
    # a brand new server on the same data dir (a restart) re-reads the book from disk
    app2 = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=fake_render)
    c2 = TestClient(app2, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    assert c2.get("/api/session").json() == saved
    assert c2.get(f"/api/books/{b['book_id']}/chapters").json()["chapters"]


def test_session_with_vanished_book_is_dropped(client):
    client.put("/api/session", json={"book_id": "gone"})
    assert client.get("/api/session").json() is None


@pytest.fixture
def keychain(monkeypatch):
    keyring = pytest.importorskip("keyring")
    from keyring.backend import KeyringBackend

    class Memory(KeyringBackend):
        priority = 1

        def __init__(self):
            self.data = {}

        def get_password(self, service, username):
            return self.data.get((service, username))

        def set_password(self, service, username, password):
            self.data[(service, username)] = password

        def delete_password(self, service, username):
            if (service, username) not in self.data:
                raise keyring.errors.PasswordDeleteError("missing")
            del self.data[(service, username)]

    previous = keyring.get_keyring()
    keyring.set_keyring(Memory())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield
    keyring.set_keyring(previous)


def test_api_keys_in_keychain_are_masked_and_used(client, keychain, monkeypatch):
    from folivox import config

    keys = client.get("/api/keys").json()["keys"]
    openai = next(k for k in keys if k["name"] == "OPENAI_API_KEY")
    assert not openai["saved"] and openai["used_by"]
    secret = "sk-test-1234567890abcd"
    r = client.put("/api/keys/OPENAI_API_KEY", json={"value": secret})
    assert r.status_code == 200
    assert secret not in r.text and "abcd" in r.text  # only the last 4 characters come back
    assert secret not in client.get("/api/keys").text
    assert config.api_key("OPENAI_API_KEY", "x") == secret  # providers find it without an env var
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert config.api_key("OPENAI_API_KEY", "x") == "from-env"  # the environment wins
    assert client.delete("/api/keys/OPENAI_API_KEY").status_code == 200
    assert not next(k for k in client.get("/api/keys").json()["keys"] if k["name"] == "OPENAI_API_KEY")["saved"]


def test_api_key_rejects_unknown_names_and_empty_values(client, keychain):
    assert client.put("/api/keys/HOME", json={"value": "x"}).status_code == 404
    assert client.put("/api/keys/OPENAI_API_KEY", json={"value": "  "}).status_code == 400


def test_ui_events_carry_what_the_studio_view_needs():
    from folivox.pipeline import RenderOptions
    from folivox.ui.jobs import Job, UIEvents

    job = Job("render", "b", RenderOptions(output=Path("x.m4b"), voice_wav=Path("v.wav")))
    ev = UIEvents(job)
    ev.layout([{"index": 0, "title": "One", "fragments": [[10, "abc"], [20, "def"]], "done": "10"}])
    chunk = SimpleNamespace(chapter=0, idx=1, key="def" * 5, text="hello", source="x" * 20)
    ev.chunk_started(chunk)
    ev.step("qa", 1, 3)
    ev.chunk_done(chunk, SimpleNamespace(duration=2.0, synth_seconds=3.0, score=0.05), [0.5, 0.05])
    by_type = {e["type"]: e for e in job.events}
    assert by_type["layout"]["chapters"][0]["done"] == "10"
    assert by_type["fragment"]["key"] == "defdefdefd" and by_type["fragment"]["idx"] == 1
    assert (by_type["step"]["step"], by_type["step"]["attempts"]) == ("qa", 3)
    p = by_type["progress"]
    assert p["attempts"] == 2 and p["chars"] == 20 and p["retakes"] == 1 and p["key"] == "defdefdefd"
