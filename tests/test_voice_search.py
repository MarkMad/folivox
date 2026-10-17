"""Finding a voice sample in a long recording: speech is told from music, noise and silence."""

import shutil
import subprocess

import numpy as np
import pytest

from folivox.voices import search

SR = search.ANALYSIS_SR
rng = np.random.default_rng(7)


def speech(seconds: float, f0: float = 120.0) -> np.ndarray:
    """A voiced buzz with a syllable rhythm (about 4 Hz) and a pause every few syllables."""
    t = np.arange(int(seconds * SR)) / SR
    # harmonics up to 3 kHz, the strongest in the formant region like in a real voice
    buzz = sum((1.0 if 300 <= f0 * k <= 3000 else 0.2) * np.sin(2 * np.pi * f0 * k * t)
               for k in range(1, int(3000 / f0)))
    syll = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)
    gate = ((t % 3.0) < 2.6).astype(float)  # 0.4 s pause every 3 s
    return (0.015 * buzz * syll**2 * gate).astype(np.float32)


def music(seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (0.1 * sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330))).astype(np.float32)


def noise(seconds: float, level: float = 0.05) -> np.ndarray:
    return (level * rng.standard_normal(int(seconds * SR))).astype(np.float32)


def quiet(seconds: float) -> np.ndarray:
    return noise(seconds, 0.001)


def windows(x: np.ndarray):
    return search.find_windows(search.frame_features(x))


def test_speech_between_music_and_noise_is_found():
    x = np.concatenate([music(20), noise(15), quiet(10), speech(12), quiet(10), music(20)])
    found = search.pick_distinct(windows(x), 3)
    assert found
    best = found[0]
    assert 6 <= best.duration <= 15
    assert best.start >= 43 and best.end <= 58  # inside the 45–57 s speech


def test_no_speech_means_no_windows():
    x = np.concatenate([music(30), noise(30), quiet(30)])
    assert windows(x) == []


def test_two_pitches_in_one_window_rank_lower():
    one = np.concatenate([quiet(2), speech(12), quiet(2)])
    two = np.concatenate([quiet(2), speech(6, 110), quiet(0.5), speech(6, 220), quiet(2)])
    assert windows(one)[0].score > windows(two)[0].score


def test_clipping_lowers_the_score():
    ok = np.concatenate([quiet(2), speech(12), quiet(2)])
    clipped = ok.copy()
    clipped[SR * 2:SR * 14] = np.clip(clipped[SR * 2:SR * 14] * 40, -1, 1)
    assert windows(clipped)[0].score < windows(ok)[0].score


def test_distinct_windows_do_not_overlap():
    x = np.concatenate([quiet(2), speech(14), quiet(30), speech(14), quiet(2)])
    picked = search.pick_distinct(windows(x), 5)
    for a, b in zip(picked, picked[1:], strict=False):
        assert a.end <= b.start or b.end <= a.start


def test_parse_time():
    assert search.parse_time("90") == 90
    assert search.parse_time("1:30") == 90
    assert search.parse_time("1:02:03") == 3723
    with pytest.raises(ValueError):
        search.parse_time("a:b")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_find_in_a_video_file(tmp_path):
    import soundfile as sf

    wav = tmp_path / "a.wav"
    sf.write(str(wav), np.concatenate([music(15), quiet(5), speech(12), quiet(5)]), SR)
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=32x32:d=40", "-i", str(wav),
                    "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(video)], check=True)
    assert search.needs_search(video)
    got = search.find_samples(video, "en", None, count=2)
    assert got and 19 <= got[0].start and got[0].end <= 38
    clip = search.cut(video, got[0], tmp_path / "clip.wav")
    info = sf.info(str(clip))
    assert info.samplerate == search.VOICE_SR and 6 <= info.duration <= 16


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_video_without_sound_is_reported(tmp_path):
    video = tmp_path / "mute.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=32x32:d=3", "-c:v", "mpeg4",
                    str(video)], check=True)
    with pytest.raises(search.NothingFound, match="no audio"):
        search.find_samples(video, "en", None)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_studio_finds_samples_in_an_uploaded_video(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    pytest.importorskip("multipart")
    import soundfile as sf
    from starlette.testclient import TestClient

    from folivox.qa import asr
    from folivox.ui.app import create_app

    class FakeASR:
        def __init__(self, language="en"):
            pass

        def transcribe(self, audio, sr, **kw):
            return "hello there this is a short test of the voice finder"

    monkeypatch.setattr(asr, "Transcriber", FakeASR)
    wav = tmp_path / "a.wav"
    sf.write(str(wav), np.concatenate([music(10), quiet(3), speech(12), quiet(3)]), SR)
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=32x32:d=30", "-i", str(wav),
                    "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(video)], check=True)
    c = TestClient(create_app(data_dir=tmp_path / "ui"))
    r = c.post("/api/voices/find", data={"lang": "en"}, files={"file": ("v.mp4", video.read_bytes())})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] and body["found"][0]["text"].startswith("hello")
    clip = c.get(f"/api/voices/found/{body['token']}/0")
    assert clip.status_code == 200 and clip.content[:4] == b"RIFF"
    assert c.get(f"/api/voices/found/{body['token']}/7").status_code == 404
    assert c.get("/api/voices/found/..%2F..%2Fx/0").status_code == 404
