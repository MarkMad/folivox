import shutil
import subprocess
from pathlib import Path

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


def test_whisper_hallucinations_ignored():
    from folivox.qa import strip_hallucinations

    ref = "А уже понимание. Догадывалась Ульяна, каким будет ответ."
    hyp = "А уже понимание. Догадывалась Ульяна, каким будет ответ. Продолжение следует..."
    assert strip_hallucinations(hyp, ref) == "А уже понимание. Догадывалась Ульяна, каким будет ответ."
    assert score(ref, hyp, 4.0) == 0
    # kept when the book really says it
    assert strip_hallucinations("Продолжение следует.", "Продолжение следует.") == "Продолжение следует."
    assert strip_hallucinations("Текст. Субтитры сделал DimaTorzok", "Текст.") == "Текст."


def test_threshold_relaxed_for_short_lines():
    from folivox.qa import threshold_for

    assert threshold_for("Не-а.", 0.08) == 0.35
    assert threshold_for("Ладно. Зайди. Разуйся только.", 0.08) == 0.15
    assert threshold_for("Это обычное длинное предложение, в нём больше сорока букв точно.", 0.08) == 0.08


class _FakeSynth:
    def __init__(self, audio, sample_rate):
        self.audio, self.sample_rate, self.seconds = audio, sample_rate, 0.0


class _FakeEngine:
    sample_rate = 1000


class _DropsLastSentence:
    """Stub engine: «speaks» each char as 60 ms of tone; drops the last sentence of long inputs."""

    engine = _FakeEngine()

    def __init__(self):
        self.calls = []

    def synthesize(self, key, text, seed, speed=1.0):
        from folivox.text.chunk import sentences

        self.calls.append(text)
        spoken = text
        parts = sentences(text)
        if len(text) > 60 and len(parts) > 1:
            spoken = " ".join(parts[:-1])
        n = int(len(spoken) * 0.06 * 1000)
        audio = (0.5 * np.sin(np.arange(n) / 3)).astype(np.float32)
        audio = np.concatenate([audio, np.zeros(50, np.float32)])
        self.last = spoken
        return _FakeSynth(audio, 1000)


class _EchoASR:
    def __init__(self, synth):
        self.synth = synth

    def transcribe(self, audio, sr):
        return self.synth.last


def test_failed_fragment_is_split_at_sentence_boundary():
    from folivox.pipeline import RenderOptions, _best_take

    synth = _DropsLastSentence()
    opts = RenderOptions(output=Path("x.m4b"), voice_wav=Path("v.wav"), max_takes=2)
    text = "Первое предложение довольно длинное. Второе тоже не короткое. А третье потеряется."
    sc, audio, hyp, attempts = _best_take(synth, _EchoASR(synth), opts, "k", text, text)
    assert hyp.endswith("А третье потеряется.")
    assert sc <= 0.08
    assert len(attempts) > 2  # two failed full takes, then the halves
    assert any(len(c) < len(text) for c in synth.calls)


def test_any_image_becomes_a_small_jpeg_cover(tmp_path):
    """A user-supplied PNG is embedded as a JPEG attached picture, scaled down to at most 1600 px."""
    import json
    import subprocess

    import numpy as np
    import soundfile as sf

    from folivox.audio.assemble import BookMeta, ChapterAudio, ffmpeg, write_m4b

    png = tmp_path / "cover.png"
    sf_wav = tmp_path / "c.flac"
    sf.write(str(sf_wav), (0.1 * np.sin(np.arange(24000) / 20)).astype("float32"), 24000)
    # a 2400x1800 PNG made by ffmpeg itself (no imaging library needed)
    subprocess.run([ffmpeg(), "-y", "-f", "lavfi", "-i", "color=c=red:s=2400x1800", "-frames:v", "1", str(png)],
                   check=True, capture_output=True)
    out = tmp_path / "book.m4b"
    write_m4b([ChapterAudio("One", sf_wav, 1.0)], out, BookMeta("T", "A"), cover=png.read_bytes())
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json",
                            str(out)], capture_output=True, text=True, check=True)
    video = [s for s in json.loads(probe.stdout)["streams"] if s["codec_type"] == "video"]
    assert len(video) == 1 and video[0]["codec_name"] == "mjpeg" and video[0]["disposition"]["attached_pic"] == 1
    assert video[0]["width"] == 1600 and video[0]["height"] == 1600


def test_edited_details_become_tags(tmp_path):
    import json
    import subprocess

    import numpy as np
    import soundfile as sf

    from folivox.audio.assemble import BookMeta, ChapterAudio, write_m4b

    wav = tmp_path / "c.flac"
    sf.write(str(wav), (0.1 * np.sin(np.arange(24000) / 20)).astype("float32"), 24000)
    out = tmp_path / "b.m4b"
    meta = BookMeta("Title", "Author", "2024", "About it.", "Anna", series="Saga", series_part="2", genre="Fantasy")
    write_m4b([ChapterAudio("One", wav, 1.0)], out, meta)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-of", "json",
                            str(out)], capture_output=True, text=True, check=True)
    tags = {k.lower(): v for k, v in json.loads(probe.stdout)["format"]["tags"].items()}
    assert tags["title"] == "Title" and tags["artist"] == "Author" and tags["composer"] == "Anna"
    assert tags["genre"] == "Fantasy" and tags["comment"] == "About it." and tags["date"] == "2024"
    assert tags["grouping"] == "Saga #2"


def test_flagged_uses_recorded_qa_level_and_short_line_slack(tmp_path):
    long = "Это достаточно длинное предложение, чтобы порог был базовым для проверки."
    j = Journal(tmp_path)
    j.set_plan([("Глава 1", _chunks([long, "Не-а."]))], "voice", "s1")
    a, b = j.chunks()
    j.record(Take(a.key, 3.0, 0.2, "что-то другое", 3, 1.0))
    j.record(Take(b.key, 1.0, 0.2, "не", 3, 1.0))  # a short line gets 0.35 of slack: not flagged
    assert list(j.flagged()) == []  # no QA level recorded (render with --no-qa)
    j.set_meta(qa_threshold=0.10, lang="ru")
    assert [c.key for c, _ in j.flagged()] == [a.key]
    j.set_meta(qa_threshold=0.25)
    assert list(j.flagged()) == []
