import numpy as np
import pytest

pytest.importorskip("noisereduce")

from folivox.audio.denoise import quiet_profile, reduce_noise  # noqa: E402

SR = 16000


def _speechlike(seconds=6.0):
    t = np.arange(int(SR * seconds)) / SR
    env = (np.sin(2 * np.pi * 1.3 * t) > -0.2).astype(np.float32)  # voiced bursts with pauses
    carrier = sum(np.sin(2 * np.pi * f * t) / k for k, f in enumerate((140, 280, 420, 700, 1400), 1))
    return (0.3 * env * carrier).astype(np.float32)


def _snr(clean, x):
    n = x[: len(clean)] - clean
    return 10 * np.log10((clean @ clean) / (n @ n))


def test_reduces_hiss_and_keeps_length():
    clean = _speechlike()
    noisy = clean + 0.02 * np.random.default_rng(0).standard_normal(len(clean)).astype(np.float32)
    out = reduce_noise(noisy, SR)
    assert len(out) == len(noisy) and out.dtype == np.float32
    assert _snr(clean, out) > _snr(clean, noisy) + 1.0
    assert np.abs(out).max() <= 1.0


def test_silence_and_tiny_inputs_pass_through():
    assert np.array_equal(reduce_noise(np.zeros(SR, np.float32), SR), np.zeros(SR, np.float32))
    short = np.ones(100, np.float32) * 0.1
    assert np.array_equal(reduce_noise(short, SR), short)


def test_profile_is_the_quiet_part():
    x = _speechlike()
    prof = quiet_profile(x, SR)
    assert 0 < len(prof) < len(x) and np.abs(prof).mean() < np.abs(x).mean()


def test_denoise_endpoint(tmp_path, monkeypatch):
    sf = pytest.importorskip("soundfile")
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient

    from folivox.ui.app import create_app

    clean = _speechlike(3.0)
    noisy = clean + 0.02 * np.random.default_rng(1).standard_normal(len(clean)).astype(np.float32)
    path = tmp_path / "in.wav"
    sf.write(str(path), noisy, SR)
    client = TestClient(create_app(token="t", port=8765, data_dir=tmp_path / "ui"), base_url="http://127.0.0.1:8765",
                        headers={"X-Folivox-Token": "t"})
    r = client.post("/api/denoise", files={"file": ("in.wav", path.read_bytes(), "audio/wav")})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    out, sr = sf.read(__import__("io").BytesIO(r.content), dtype="float32")
    assert sr == SR and len(out) == len(noisy)
