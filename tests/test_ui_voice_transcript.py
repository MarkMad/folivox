"""Studio endpoints for adding a voice: transcript check before saving."""

import io

import numpy as np
import pytest
import soundfile as sf

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from tests.test_ui import client  # noqa: E402, F401 — the studio fixture


def _wav(seconds=6.0):
    buf = io.BytesIO()
    t = np.arange(int(24000 * seconds)) / 24000
    sf.write(buf, (0.3 * np.sin(2 * np.pi * 180 * t)).astype("float32"), 24000, format="WAV")
    return buf.getvalue()


@pytest.fixture
def fake_asr(monkeypatch):
    import folivox.qa.asr as asr

    class Fake:
        def __init__(self, language="ru", **kw):
            self.language = language

        def transcribe_file(self, path):
            return "  Eto   primer rovnoy russkoy rechi  "

    monkeypatch.setattr(asr, "Transcriber", Fake)


def test_transcribe_endpoint_returns_text_and_warnings(client, fake_asr):  # noqa: F811
    r = client.post("/api/voices/transcribe", data={"lang": "ru"}, files={"file": ("v.wav", _wav(), "audio/wav")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == "Eto primer rovnoy russkoy rechi"
    assert any("sample language" in w for w in body["warnings"])


def test_transcribe_endpoint_needs_a_file(client):  # noqa: F811
    assert client.post("/api/voices/transcribe", data={"lang": "ru"}).status_code == 400


def test_add_voice_returns_transcript_warnings(client, tmp_path, monkeypatch):  # noqa: F811
    import folivox.voices as voices

    monkeypatch.setattr(voices, "user_voices_dir", lambda: tmp_path / "uv")
    r = client.post("/api/voices", data={"id": "mine", "lang": "ru", "transcript": "Привет"},
                    files={"file": ("v.wav", _wav(10.0), "audio/wav")})
    assert r.status_code == 200, r.text
    assert any("too short" in w for w in r.json()["warnings"])
