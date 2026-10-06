import numpy as np
import pytest
import soundfile as sf

from folivox import voices


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "user_voices_dir", lambda: tmp_path / "voices")
    return tmp_path


def test_bundled_catalog_is_complete():
    entries = voices.bundled()
    assert voices.DEFAULT_VOICE in {v.id for v in entries}
    for v in entries:
        assert v.path.exists(), v.id
        assert v.transcript and v.license and v.lang and v.gender in ("f", "m")
        info = sf.info(str(v.path))
        assert 6 <= info.frames / info.samplerate <= 15


def test_add_find_remove_user_voice(user_dir):
    src = user_dir / "in.wav"
    sr = 44100
    tone = 0.3 * np.sin(np.linspace(0, 2 * np.pi * 220 * 8, sr * 8)).astype(np.float32)
    sf.write(str(src), np.stack([tone, tone], axis=1), sr)  # stereo, 44.1 kHz
    e = voices.add("my-voice", src, "  Тестовая   фраза. ", gender="f")
    assert e.transcript == "Тестовая фраза."
    info = sf.info(str(e.path))
    assert info.samplerate == voices.TARGET_SR and info.channels == 1
    assert voices.find("my-voice").gender == "f"
    with pytest.raises(FileExistsError):
        voices.add("my-voice", src, "x")
    with pytest.raises(ValueError):
        voices.add("Bad Name", src, "x")
    voices.remove("my-voice")
    assert voices.find("my-voice") is None
