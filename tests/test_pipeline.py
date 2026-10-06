import shutil
import subprocess

import numpy as np
import pytest

from folivox.audio import fade, trim_silence
from folivox.journal import Journal, Take, chunk_key
from folivox.pipeline import parse_selection
from folivox.qa import canonical, cer, levenshtein, score
from folivox.text.chunk import Chunk


def test_parse_selection():
    assert parse_selection(None, 3) == [0, 1, 2]
    assert parse_selection("1-2,5", 6) == [0, 1, 4]
    assert parse_selection("3-", 4) == [2, 3]
    assert parse_selection("-2", 4) == [0, 1]
    with pytest.raises(ValueError):
        parse_selection("9", 3)
    with pytest.raises(ValueError):
        parse_selection("x", 3)


def test_qa_metrics():
    assert levenshtein("кот", "кит") == 1
    assert canonical("Ёлка, 7:30!") == "елка семь тридцать"
    assert cer("В семь тридцать он вышел.", "В 7.30 он вышел") == 0
    assert cer("Цены выросли на пятнадцать процентов", "Цены выросли на 15%") == 0
    assert cer("один два три", "один три") > 0.1
    text = "Это обычное предложение средней длины для проверки темпа."
    assert score(text, text, 4.0) == 0
    assert score(text, text, 30.0) > 0.5  # far too slow: babbling or silence
    assert score(text, text, 0.5) > 0.5  # far too fast: swallowed words


def _chunks(texts):
    return [Chunk(i, t, t, 0.3, "p") for i, t in enumerate(texts)]


def test_journal_resume_and_replan(tmp_path):
    j = Journal(tmp_path)
    j.set_plan([("Глава 1", _chunks(["а", "б"])), ("Глава 2", _chunks(["в"]))], "voice", "s1")
    assert [t for _, t in j.chapters()] == ["Глава 1", "Глава 2"]
    pending = j.pending()
    assert len(pending) == 3
    first = pending[0]
    j.audio_path(first.key).write_bytes(b"x")
    j.record(Take(first.key, 1.0, 0.0, "а", 1, 2.0))
    assert len(j.pending()) == 2
    assert j.stats()["done_chars"] == 1
    j.close()

    # reopen: progress survives; a changed plan keeps audio for unchanged text
    j = Journal(tmp_path)
    assert len(j.pending()) == 2
    j.set_plan([("Глава 1", _chunks(["а", "г"]))], "voice", "s1")
    assert [c.text for c in j.pending()] == ["г"]
    # other voice → everything pending again
    j.set_plan([("Глава 1", _chunks(["а"]))], "other", "s1")
    assert len(j.pending()) == 1
    j.close()


def test_chunk_key_depends_on_all_inputs():
    k = chunk_key("текст", "v", "s")
    assert k != chunk_key("текст.", "v", "s")
    assert k != chunk_key("текст", "w", "s")
    assert k != chunk_key("текст", "v", "t")


def test_trim_and_fade():
    sr = 24000
    tone = (0.5 * np.sin(np.linspace(0, 440 * 2 * np.pi, sr))).astype(np.float32)
    audio = np.concatenate([np.zeros(sr, np.float32), tone, np.zeros(sr, np.float32)])
    out = trim_silence(audio, sr)
    assert sr * 0.95 < len(out) < sr * 1.2
    f = fade(out, sr)
    assert abs(f[0]) < 1e-6 and abs(f[-1]) < 1e-6
    assert trim_silence(np.zeros(sr, np.float32), sr).size == 0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_assemble_m4b(tmp_path):
    import soundfile as sf

    from folivox.audio.assemble import BookMeta, ChapterAudio, build_chapter, write_m4b

    sr = 24000
    parts = []
    for i in range(2):
        p = tmp_path / f"c{i}.flac"
        sf.write(str(p), (0.3 * np.sin(np.linspace(0, 300 * 2 * np.pi, sr))).astype(np.float32), sr)
        parts.append((p, 0.5))
    chapters = []
    for i, title in enumerate(["Глава первая", "Глава вторая; «с кавычками»"]):
        out = tmp_path / f"ch{i}.flac"
        dur = build_chapter(parts, out, sr)
        assert 2.9 < dur < 3.5
        chapters.append(ChapterAudio(title, out, dur))
    book = tmp_path / "книга.m4b"
    write_m4b(chapters, book, BookMeta("Тестовая книга", "Иван Тестов", "2024"), cover=None)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_format", "-of", "json", str(book)],
                           capture_output=True, text=True, check=True).stdout
    import json

    info = json.loads(probe)
    assert [c["tags"]["title"] for c in info["chapters"]] == ["Глава первая", "Глава вторая; «с кавычками»"]
    assert info["format"]["tags"]["title"] == "Тестовая книга"
    assert 5.5 < float(info["format"]["duration"]) < 7.5
