"""Web UI endpoints of the cloud reading engines: estimate, consent gate, options reaching the pipeline."""
import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402
from test_ui import TOKEN, upload, wait_done  # noqa: E402

from folivox.ui.app import create_app  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-SECRET-1234")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr("folivox.config.keychain_get", lambda name: None)
    from folivox import config

    config.load.cache_clear()
    seen = {}

    def fake_render(book, opts, events):
        seen["opts"] = opts
        return opts.output

    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=fake_render)
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    yield c, seen
    config.load.cache_clear()


def test_engine_list_has_prices_limits_and_badges(env):
    c, _ = env
    data = c.get("/api/tts/engines").json()
    by = {e["name"]: e for e in data["engines"]}
    assert by["cosyvoice3"]["local"] and not by["openai"]["local"]
    assert set(by) >= {"elevenlabs", "openai", "gemini", "cartesia"}
    assert by["openai"]["per_hour"] > 0 and by["openai"]["max_chars"] == 4096 and by["openai"]["key_in_env"]
    assert "SECRET" not in c.get("/api/tts/engines").text
    assert by["gemini"]["voice_modes"] == ["preset", "design"] and by["elevenlabs"]["voice_modes"] == ["preset"]


def test_estimate_counts_the_book(env):
    c, _ = env
    b = upload(c)
    body = {"book_id": b["book_id"], "options": {"tts": "openai", "takes": 2}}
    e = c.post("/api/tts/estimate", json=body).json()
    assert e["chars"] > 500 and e["usd"] > 0 and e["usd_max"] >= e["usd"] and e["approximate"]
    prev = c.post("/api/tts/estimate", json={**body, "kind": "preview"}).json()
    assert prev["chars"] <= 600 and prev["usd"] < e["usd"]
    assert c.post("/api/tts/estimate", json={**body, "options": {"tts": "cosyvoice3"}}).status_code == 400


def test_cloud_job_needs_acknowledgement_and_key(env):
    c, seen = env
    b = upload(c)
    job = {"kind": "preview", "book_id": b["book_id"], "options": {"tts": "openai", "tts_voice": "coral"}}
    assert c.post("/api/jobs", json=job).status_code == 400  # no acknowledgement
    ack = {**job, "acknowledged": True, "options": {**job["options"], "tts": "elevenlabs", "tts_voice": "x"}}
    r = c.post("/api/jobs", json=ack)
    assert r.status_code == 412 and r.json().get("missing_key") == "ELEVENLABS_API_KEY"
    r = c.post("/api/jobs", json={**job, "acknowledged": True,
                                  "options": {**job["options"], "max_cost": "7.5", "tts_style": "calm"}})
    assert r.status_code == 202, r.text
    wait_done(c, r.json()["id"])
    o = seen["opts"]
    assert (o.tts, o.tts_voice, o.max_cost, o.tts_style, o.accept_cloud) == ("openai", "coral", 7.5, "calm", True)
    assert o.max_takes == 2  # cloud default: retakes are billed


def test_bad_cap_and_mode_are_rejected(env):
    c, _ = env
    b = upload(c)
    base = {"kind": "preview", "book_id": b["book_id"], "acknowledged": True}
    for extra in ({"max_cost": "abc"}, {"max_cost": 0}, {"tts_mode": "clone"}, {"tts_mode": "design"}):
        r = c.post("/api/jobs", json={**base, "options": {"tts": "openai", **extra}})
        assert r.status_code == 400, extra
