"""Cloud voice generation endpoints of the web UI, with fake provider, LLM and ASR."""
import json
import threading
import time

import numpy as np
import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

import soundfile as sf  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from folivox.ui.app import create_app  # noqa: E402
from folivox.voicegen.cloud import CloudError  # noqa: E402
from folivox.voicegen.cloud_apis import ElevenLabs, Gemini  # noqa: E402

TOKEN = "t0ken"
BOOK = ("Chapter 1\n\n" + "It was a quiet morning in the village. " * 12 + "\n").encode()
TEXT = "In the morning a light mist rose above the river. The old bridge slowly appeared out of the haze."


class FakeGen:
    """Stands in for a cloud generator: writes a 7 s tone per take."""

    def __init__(self, cls, gate=None, fail=None):
        self.name, self.label, self.mode, self.local = cls.name, cls.label, cls.modes[0], False
        self.modes, self.gate, self.fail, self.seen, self.model = cls.modes, gate, fail, [], cls.models[0]["id"]

    def generate(self, jobs, progress=None):
        for j in jobs:
            if self.gate:
                self.gate.wait(5)
            if self.fail:
                raise self.fail
            self.seen.append(j)
            sf.write(str(j.out), (0.2 * np.sin(np.arange(24000 * 7) / 15)).astype("float32"), 24000)
            if progress:
                progress(j, 0.1)
        return [j.out for j in jobs]


class FakeASR:
    def transcribe(self, audio, sr):
        return TEXT


class FakeLLM:
    name = "fake"

    def complete(self, prompt, system=None, temperature=0.3):
        if "EXACTLY" in prompt:
            return json.dumps([TEXT])
        return "A warm, unhurried middle-aged woman with a low timbre and a gentle pace, for a village tale."


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr("folivox.voices.user_voices_dir", lambda: tmp_path / "voices")
    monkeypatch.setattr("folivox.config.keychain_get", lambda n: None)
    for k in ("GEMINI_API_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from folivox import config

    config.load.cache_clear()
    holder = {"gen": None}

    def make(**services):
        app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui",
                         services={"generator": lambda n, model="": holder["gen"], "llm": lambda n: FakeLLM(),
                                   "asr": lambda lang: FakeASR(), **services})
        return TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})

    yield holder, make, tmp_path
    config.load.cache_clear()


def book(c):
    return c.post("/api/books", files={"file": ("tale.txt", BOOK, "text/plain")}).json()["book_id"]


def wait(c, job_id):
    for _ in range(200):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.03)
    raise AssertionError("job did not finish")


def events(c, job_id):
    out = []
    with c.stream("GET", f"/api/jobs/{job_id}/events") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def start_body(**kw):
    return {"provider": "gemini", "mode": "preset", "speaker": "Kore", "lang": "en", "texts": [TEXT], "takes": 3,
            "acknowledged": True, **kw}


def test_providers_list_shows_capabilities_and_masked_key_state(env, monkeypatch):
    holder, make, _ = env
    monkeypatch.setattr("folivox.config.keychain_get",
                        lambda n: "sk-abcdef123456" if n == "ELEVENLABS_API_KEY" else None)
    c = make()
    r = c.get("/api/gen/providers").json()
    by = {p["name"]: p for p in r["providers"]}
    assert [p["name"] for p in r["providers"]] == ["gemini", "cartesia", "elevenlabs", "openai"]
    assert by["gemini"]["tag"] == "cheap and best" and "non-English" in by["openai"]["tag"]
    assert set(by) == {"openai", "gemini", "elevenlabs", "cartesia"} and "billed" in r["notice"]
    assert by["elevenlabs"]["modes"] == ["preset", "design"] and by["gemini"]["key_env"] == "GEMINI_API_KEY"
    assert by["elevenlabs"]["key_saved"] and by["elevenlabs"]["key_masked"].endswith("3456")
    assert not by["gemini"]["key_saved"] and not by["gemini"]["key_in_env"]
    assert "sk-abcdef123456" not in json.dumps(r)  # the key never goes to the browser


def test_missing_key_is_a_clear_error(env):
    _, make, _ = env
    c = make()
    b = book(c)
    r = c.post("/api/gen/start", json=start_body(book_id=b))
    assert r.status_code == 412
    assert r.json()["missing_key"] == "GEMINI_API_KEY" and "No API key for Gemini API" in r.json()["error"]
    assert c.get("/api/gen/voices/gemini").status_code == 412


def test_save_key_then_generate_and_add(env, monkeypatch):
    holder, make, tmp = env
    store = {}
    monkeypatch.setattr("folivox.config.keychain_get", lambda n: store.get(n))
    monkeypatch.setattr("folivox.config.keychain_set", lambda n, v: store.__setitem__(n, v))
    c = make()
    b = book(c)
    assert c.post("/api/gen/start", json=start_body(book_id=b)).status_code == 412
    keys = c.put("/api/keys/GEMINI_API_KEY", json={"value": "AIza-secret-9999"}).json()["keys"]
    assert "AIza-secret-9999" not in json.dumps(keys)
    holder["gen"] = FakeGen(Gemini)
    est = c.post("/api/gen/estimate", json=start_body()).json()
    assert est["chars"] == len(TEXT) * 3 and est["usd"] is not None and "billed" in est["notice"]
    r = c.post("/api/gen/start", json=start_body(book_id=b))
    assert r.status_code == 202
    job = r.json()["id"]
    assert wait(c, job)["state"] == "done"
    evs = events(c, job)
    kinds = [e["type"] for e in evs]
    assert kinds.count("take") == 3 and "takes" in kinds and kinds[-1] == "done"
    assert [e["name"] for e in evs if e["type"] == "stage"] == ["generate", "score"]
    takes = next(e for e in evs if e["type"] == "takes")["takes"]
    assert len(takes) == 3 and takes[0]["score"] == 0.0 and takes[0]["peaks"] and takes[0]["text"] == TEXT
    wav = c.get(f"/api/gen/{job}/takes/{takes[0]['name']}")
    assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
    assert c.get(f"/api/gen/{job}/takes/..%2Fx.wav").status_code == 404
    assert c.get(f"/api/gen/{job}/takes/passwd").status_code == 404
    added = c.post(f"/api/gen/{job}/add", json={"take": takes[0]["name"], "id": "mist", "name": "Mist",
                                                 "gender": "f"})
    assert added.status_code == 200, added.text
    meta = json.loads((tmp / "voices" / "mist" / "meta.json").read_text())
    assert meta["commercial"] is True and "Gemini API gemini-3.8-flash-tts (commercial API): Kore" == meta["source"]
    assert meta["transcript"] == TEXT and "terms" in meta["license"].lower()
    assert c.post(f"/api/gen/{job}/add", json={"take": "take_t9_9.wav", "id": "x"}).status_code == 404


def test_requires_acknowledgement_and_validates(env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    holder, make, _ = env
    holder["gen"] = FakeGen(Gemini)
    c = make()
    b = book(c)
    for bad, code in (({"acknowledged": False}, 400), ({"mode": "design"}, 400), ({"texts": []}, 400),
                      ({"takes": 50}, 400), ({"speaker": ""}, 400), ({"provider": "nope"}, 404)):
        assert c.post("/api/gen/start", json=start_body(book_id=b, **bad)).status_code == code, bad


def test_design_mode_needs_a_description(env, monkeypatch):
    holder, make, _ = env
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    holder["gen"] = FakeGen(ElevenLabs)
    c = make()
    body = {"provider": "elevenlabs", "mode": "design", "lang": "en", "texts": [TEXT * 2], "takes": 3,
            "acknowledged": True, "description": "short"}
    assert c.post("/api/gen/start", json=body).status_code == 400
    body["description"] = "A warm, unhurried middle-aged woman with a low timbre"
    r = c.post("/api/gen/start", json=body)
    assert r.status_code == 202
    wait(c, r.json()["id"])
    assert holder["gen"].mode == "design" and holder["gen"].seen[0].description.startswith("A warm")


def test_cancel(env, monkeypatch):
    holder, make, _ = env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    gate = threading.Event()
    holder["gen"] = FakeGen(Gemini, gate=gate)
    c = make()
    job = c.post("/api/gen/start", json=start_body(book_id=book(c))).json()["id"]
    assert c.post("/api/gen/start", json=start_body()).status_code == 409  # one job at a time
    assert c.post(f"/api/jobs/{job}/cancel").status_code == 200
    gate.set()
    assert wait(c, job)["state"] == "cancelled"
    assert [e["type"] for e in events(c, job)][-1] == "cancelled"
    assert c.get("/api/jobs/current").json() is None  # a generation never looks like a render


def test_provider_failure_is_reported_in_the_job(env, monkeypatch):
    holder, make, _ = env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    holder["gen"] = FakeGen(Gemini, fail=CloudError("Gemini API: rate limit reached. Retry in about 30 s.",
                                                    "rate_limit"))
    c = make()
    job = c.post("/api/gen/start", json=start_body(book_id=book(c))).json()["id"]
    j = wait(c, job)
    assert j["state"] == "error" and "rate limit" in j["error"]


def test_suggest_and_texts(env):
    _, make, _ = env
    c = make()
    b = book(c)
    r = c.post("/api/gen/suggest", json={"book_id": b})
    assert r.status_code == 200 and r.json()["prompt"].startswith("A warm")
    assert c.post("/api/gen/suggest", json={"book_id": "missing"}).status_code == 404
    built = c.post("/api/gen/texts", json={"lang": "en"}).json()
    assert built["lang"] == "en" and len(built["texts"]) >= 3 and all(len(t) < 300 for t in built["texts"])
    # the fake LLM returns TEXT, which is not in this book → nothing usable
    assert c.post("/api/gen/texts", json={"source": "book", "book_id": b, "lang": "en"}).status_code == 404


def test_llm_failure_is_a_clear_error(env):
    _, make, _ = env

    class Down:
        def complete(self, *a, **k):
            raise ConnectionRefusedError("connection refused")

    c = make(llm=lambda n: Down())
    r = c.post("/api/gen/suggest", json={"book_id": book(c)})
    assert r.status_code == 502 and "text LLM failed" in r.json()["error"]


def test_generated_voices_are_never_bundled(env):
    from folivox import voices

    assert not any(v.commercial for v in voices.bundled())
    assert not any("commercial" in v.source.lower() for v in voices.bundled())


def test_models_are_listed_and_a_model_can_be_chosen(env, monkeypatch):
    holder, make, _ = env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    holder["gen"] = FakeGen(Gemini)
    c = make()
    by = {p["name"]: p for p in c.get("/api/gen/providers").json()["providers"]}
    assert [m["id"] for m in by["gemini"]["models"]][0] == "gemini-3.8-flash-tts" and by["gemini"]["style"]
    assert by["cartesia"]["modes"] == ["preset", "localize", "clone"]
    assert "native accent" in by["cartesia"]["mode_labels"]["localize"]
    assert c.post("/api/gen/estimate", json=start_body(model="gemini-3.8-flash-lite-tts")).status_code == 200
    assert c.post("/api/gen/start", json=start_body(book_id=book(c), model="bad model!")).status_code == 400


def test_clone_and_localize_rules(env, monkeypatch):
    from folivox import voices
    from folivox.voicegen.cloud_apis import Cartesia

    holder, make, tmp = env
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    holder["gen"] = FakeGen(Cartesia)
    sf.write(str(tmp / "me.wav"), (0.2 * np.sin(np.arange(24000 * 7) / 15)).astype("float32"), 24000)
    voices.add("me", tmp / "me.wav", "My own voice.", name="Me", lang="en")
    c = make()
    b = book(c)
    base = {"provider": "cartesia", "lang": "ru", "texts": [TEXT], "takes": 1, "acknowledged": True, "book_id": b}
    assert c.post("/api/gen/start", json={**base, "mode": "localize"}).status_code == 400  # needs a base voice
    assert c.post("/api/gen/start", json={**base, "mode": "clone", "reference": "me"}).status_code == 400  # no consent
    assert c.post("/api/gen/start", json={**base, "mode": "clone", "reference": "russlib",
                                          "own_voice": True}).status_code == 400  # bundled voices are not yours
    r = c.post("/api/gen/start", json={**base, "mode": "clone", "reference": "me", "own_voice": True})
    assert r.status_code == 202
    wait(c, r.json()["id"])
    assert holder["gen"].seen[0].reference.name == "voice.flac" and holder["gen"].mode == "clone"


def test_voice_list_carries_sex_traits_and_preview(env, monkeypatch):
    holder, make, _ = env
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")

    class Rich(FakeGen):
        names = {"v1": "Sarah"}
        details = {"v1": {"traits": "american", "description": "Warm.", "preview_url": "https://cdn.example/s.mp3"}}
        voices_note = "note"

        def speakers(self, lang=None):
            return {"v1": ("", "f")}

    holder["gen"] = Rich(ElevenLabs)
    r = make().get("/api/gen/voices/elevenlabs?lang=ru").json()
    assert r["voices"] == [{"id": "v1", "lang": "", "gender": "f", "name": "Sarah", "traits": "american",
                            "description": "Warm.", "preview_url": "https://cdn.example/s.mp3"}] and r["note"] == "note"
