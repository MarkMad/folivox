"""Transcript checks when a voice is added: hints for a text that does not belong to the recording."""

from folivox.tts.voice import transcript_warnings


def test_matching_transcript_has_no_warnings():
    assert transcript_warnings("Это пример ровной русской речи, записанной в тишине.", 4.5, "ru") == []
    assert transcript_warnings("This is an even sample of speech recorded in a quiet room.", 4.5, "en") == []
    assert transcript_warnings("今日はいい天気ですね、散歩に行きましょう。", 5.0, "ja") == []


def test_transcript_of_a_longer_original_is_flagged():
    text = "слово " * 120  # ~600 letters for a 10 s clip
    out = transcript_warnings(text, 10.0, "ru")
    assert len(out) == 1 and "too long" in out[0]


def test_cut_off_transcript_is_flagged():
    out = transcript_warnings("Привет", 12.0, "ru")
    assert len(out) == 1 and "too short" in out[0]


def test_wrong_language_transcript_is_flagged():
    # a Russian recording run through Whisper as English comes back in Latin letters
    out = transcript_warnings("Eto primer rovnoy russkoy rechi zapisannoy v tishine", 4.0, "ru")
    assert any("sample language" in w for w in out)
    out = transcript_warnings("Это пример ровной русской речи записанной в тишине", 4.0, "en")
    assert any("sample language" in w for w in out)


def test_empty_text_or_duration_is_ignored():
    assert transcript_warnings("", 5.0, "ru") == []
    assert transcript_warnings("слово", 0.0, "ru") == []
