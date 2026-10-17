"""Decided fixes: missing character voices, normalised cost estimate, measured chapter lengths, saved voices."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np

from folivox import pipeline
from folivox.book import Block, BlockKind, Book, Section
from folivox.tts import cost, saved


class _Ev(pipeline.Events):
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


class _Markup:
    def used_speakers(self):
        return {0, 1}

    def speaker(self, sid):
        return SimpleNamespace(name="Анна", voice="/nonexistent/voice.wav")


def test_missing_character_voice_falls_back_to_narrator():
    ev = _Ev()
    out = pipeline.speaker_voices(_Markup(), None, None, None, ev)
    assert out == {}
    assert any("Анна" in w for w in ev.warnings)


def _book(text):
    return Book(title="t", lang="ru", sections=[Section("Глава", [Block(BlockKind.PARAGRAPH, text)])])


def test_cost_counts_normalised_numbers():
    text = "В 1987 году было 25 000 человек, 15.03.2021 — 342 рубля. " * 20
    chars = cost.book_chars(_book(text), 1)
    assert chars > len(text) * 1.3


def test_cost_plain_text_unchanged():
    text = "Просто текст без чисел. " * 20
    assert cost.book_chars(_book(text), 1) == len(text)


def test_build_chapter_returns_file_length(tmp_path):
    from folivox.audio import audio_seconds, save
    from folivox.audio.assemble import build_chapter

    src = tmp_path / "a.wav"
    save(src, (np.sin(np.arange(24000) / 10) * 0.3).astype(np.float32), 24000)
    out = tmp_path / "c.flac"
    dur = build_chapter([(src, 0.5)], out, 24000)
    assert abs(dur - audio_seconds(out)) < 1e-6


def test_saved_write_leaves_no_temp(tmp_path, monkeypatch):
    p = tmp_path / "cloud_voices.json"
    monkeypatch.setattr(saved, "_path", lambda: p)
    saved.add("elevenlabs", "v1", "Анна", "design")
    saved.add("elevenlabs", "v2", "Борис", "design")
    assert len(json.loads(p.read_text(encoding="utf-8"))) == 2
    assert [x.name for x in tmp_path.iterdir()] == ["cloud_voices.json"]
