"""The recommended voice-sample length depends on the TTS engine; 30 s stays the hard maximum."""

from pathlib import Path

import pytest

from folivox.tts.voice import MAX_SECONDS, Voice, good_range


@pytest.mark.parametrize("engine,expected", [
    (None, (6.0, 15.0)), ("", (6.0, 15.0)), ("cosyvoice3", (6.0, 15.0)), ("elevenlabs", (6.0, 15.0)),
    ("fish", (10.0, 30.0)), ("fish-s2", (10.0, 30.0)), ("fish-drama3", (10.0, 30.0)),
])
def test_good_range_by_engine(engine, expected):
    assert good_range(engine) == expected


def _voice(sec):
    return Voice(Path("x.wav"), "text", sec)


def test_long_sample_is_fine_for_fish_but_not_for_cosyvoice():
    v = _voice(25.0)
    assert v.warnings_for("fish-s2") == []
    assert "6–15 s" in v.warnings_for("cosyvoice3")[0]
    assert v.warnings == v.warnings_for(None)


def test_short_sample_warns_for_fish_with_its_range():
    out = _voice(8.0).warnings_for("fish-drama3")
    assert len(out) == 1 and "10–30 s" in out[0]
    assert _voice(8.0).warnings_for("cosyvoice3") == []


def test_hard_maximum_unchanged():
    assert MAX_SECONDS == 30.0
    assert all(hi <= MAX_SECONDS for _, hi in (good_range(e) for e in ("fish", "cosyvoice3")))
