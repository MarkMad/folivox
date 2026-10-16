"""Book markup: speakers and expression tags, kept apart from the book text; planning, cache keys and rendering."""

import json
import shutil
import sqlite3
import sys
import wave
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from folivox import markup as mk
from folivox.book import Block, BlockKind, Book, Chapter, Section
from folivox.journal import Journal, chunk_key
from folivox.text.chunk import ChunkOptions, MarkupContext, plan_chapter

TEXT = "— Ты куда? — спросила соседка. — Домой, — ответил он. Дверь закрылась."
CH = Chapter("Глава", [Block(BlockKind.PARAGRAPH, TEXT), Block(BlockKind.PARAGRAPH, "Второй абзац книги.")])


def marked() -> mk.Markup:
    m = mk.Markup()
    m.ensure_speaker(1, "Соседка")
    m.ensure_speaker(2, "Он")
    a = TEXT.index("Ты куда")
    b = TEXT.index("Домой")
    m.assign(0, 0, a, a + len("Ты куда?"), 1, ("whispering",))
    m.assign(0, 0, b, b + len("Домой,"), 2)
    m.add_mark(0, 0, TEXT.index("Дверь"), "sighs")
    mk.stamp(m, [CH])
    return m


def test_segments_cover_the_text_exactly_and_assign_speakers():
    m = marked()
    segs = m.segments(0, 0, TEXT)
    assert "".join(s.text for s in segs) == TEXT
    assert [s.speaker for s in segs if s.text.strip().startswith("Ты куда")] == [1]
    assert any(s.tags == ("whispering",) for s in segs) and any(s.tags == ("sighs",) for s in segs)
    assert m.segments(0, 1, "Второй абзац книги.") == [mk.Segment("Второй абзац книги.", 0)]
    assert m.segments(5, 0, "x") == [mk.Segment("x", 0)]


def test_assign_replaces_overlaps_and_clear_removes():
    m = mk.Markup()
    m.assign(0, 0, 0, 10, 1)
    m.assign(0, 0, 4, 6, 2)
    spans = [(s.start, s.end, s.speaker) for s in m.chapters[0].spans]
    assert spans == [(0, 4, 1), (4, 6, 2), (6, 10, 1)]
    m.clear(0, 0, 4, 6)
    assert [(s.start, s.end, s.speaker) for s in m.chapters[0].spans] == [(0, 4, 1), (6, 10, 1)]
    with pytest.raises(mk.MarkupError):
        m.ensure_speaker(16)


def test_json_round_trip(tmp_path):
    m = marked()
    f = tmp_path / "b.markup.json"
    m.save(f)
    again = mk.Markup.load(f)
    assert again.to_dict() == m.to_dict()
    f.write_text("{not json")
    with pytest.raises(mk.MarkupError):
        mk.Markup.load(f)
    with pytest.raises(mk.MarkupError, match="version"):
        mk.Markup.from_dict({"version": 99})


def test_text_form_round_trips_and_refuses_edited_book_text():
    m = marked()
    text = mk.export_text(m, [CH])
    assert "<|speaker:1|>" in text and "[whispering]" in text and "[sighs]" in text
    back = mk.import_text(text, [CH])
    assert back.to_dict()["chapters"] == m.to_dict()["chapters"]
    assert [s.name for s in back.speakers if s.id] == ["Соседка", "Он"]
    bad = text.replace("спросила", "спросил")
    with pytest.raises(mk.MarkupError, match=r"B1\.0: the text differs"):
        mk.import_text(bad, [CH])
    with pytest.raises(mk.MarkupError, match="no such block"):
        mk.import_text("B1.7  hello", [CH])


def test_text_form_keeps_literal_brackets_of_the_book():
    ch = Chapter("c", [Block(BlockKind.PARAGRAPH, "Он сказал [1] и ушёл.")])
    m = mk.Markup()
    m.ensure_speaker(1)
    m.assign(0, 0, 0, 6, 1)
    out = mk.export_text(m, [ch])
    back = mk.import_text(out, [ch])
    assert back.chapters[0].spans[0].end == 6 and not back.chapters[0].marks


def test_bind_drops_what_does_not_fit():
    m = marked()
    other = Chapter("Глава", [Block(BlockKind.PARAGRAPH, "Совсем другой текст.")])
    clean, problems = mk.bind(m, [other])
    assert not clean.chapters and "no longer matches" in problems[0]
    m2 = marked()
    m2.chapters[0].spans.append(mk.Span(0, 5, 9999, 1))  # past the end
    m2.chapters[0].spans.append(mk.Span(0, 0, 3, 7))  # unknown speaker
    clean, problems = mk.bind(m2, [CH])
    assert len(problems) == 2 and len(clean.chapters[0].spans) == 2


def test_tag_database():
    db = mk.tag_database()
    assert db["schema"] == 1 and {"sighs", "laughs"} <= mk.known_tags("drama3")
    assert "whisper" in mk.known_tags("s2") and all(t["sources"] and t["category"] in db["categories"]
                                                      for t in db["tags"])
    assert mk.unknown_tags(marked()) == set()
    m = marked()
    m.add_mark(0, 0, 3, "made up tag")
    assert mk.unknown_tags(m) == {"made up tag"}


def plan(ctx, **kw):
    return plan_chapter(CH, ChunkOptions(lang="ru", stress="none", max_chars=300, min_chars=5, **kw), ctx)


def test_planning_splits_by_speaker_and_writes_tags_only_when_allowed():
    m = marked()
    chunks = plan(MarkupContext(m, 0, True))
    assert [c.speaker for c in chunks] == [1, 0, 2, 0, 0][: len(chunks)] or {c.speaker for c in chunks} == {0, 1, 2}
    first = chunks[0]
    assert first.speaker == 1 and first.text.startswith("[whispering] ") and first.markup == "[whispering]"
    assert "[whispering]" not in first.source and first.source.startswith("Ты куда")
    assert any(c.text.startswith("[sighs] ") for c in chunks)
    assert "".join(c.source.replace(" ", "") for c in chunks if c.kind == "p")  # text is still there
    plain = plan(MarkupContext(m, 0, False))
    assert all("[" not in c.text for c in plain) and {c.speaker for c in plain} == {0, 1, 2}
    m.expression_tags = False
    assert all("[" not in c.text for c in plan(MarkupContext(m, 0, True)))
    # without markup nothing changes
    base = plan(None)
    assert all(c.speaker == 0 and not c.markup for c in base)


def test_read_text_is_unchanged_by_markup():
    m = marked()
    plain = " ".join(c.source for c in plan(None))
    marked_text = " ".join(c.source for c in plan(MarkupContext(m, 0, True)))
    squash = lambda s: "".join(s.replace("—", "").lower().split())  # noqa: E731  (no dash is read; a segment starts a sentence)
    assert squash(plain) == squash(marked_text)


def test_journal_keys_and_old_journals(tmp_path):
    assert chunk_key("t", "v", "s") != chunk_key("t", "v", "s", speaker="2")
    chunks = plan(MarkupContext(marked(), 0, True))
    j = Journal(tmp_path)
    j.set_plan([("c", chunks)], "main", "s", {1: "anna", 2: "ben"})
    rows = {c.speaker: c for c in j.chunks()}
    assert rows[1].voice == "anna" and rows[2].voice == "ben" and rows[0].voice == ""
    assert len({c.key for c in j.chunks()}) == len(chunks)
    other = Journal(tmp_path / "x")
    other.set_plan([("c", chunks)], "main", "s", {1: "other", 2: "ben"})
    assert {c.key for c in other.chunks() if c.speaker == 1}.isdisjoint({c.key for c in j.chunks() if c.speaker == 1})
    j.close()
    other.close()
    # a journal written before multi-voice gets the new columns
    old = tmp_path / "old"
    old.mkdir()
    db = sqlite3.connect(old / "journal.sqlite")
    db.executescript("CREATE TABLE chunks (chapter INTEGER NOT NULL, idx INTEGER NOT NULL, key TEXT NOT NULL, "
                     "text TEXT NOT NULL, source TEXT NOT NULL, pause REAL NOT NULL, kind TEXT NOT NULL, "
                     "PRIMARY KEY (chapter, idx)); INSERT INTO chunks VALUES (0, 0, 'k', 't', 's', 0.1, 'p');")
    db.commit()
    db.close()
    j = Journal(old)
    assert j.chunks()[0].speaker == 0 and j.chunks()[0].voice == ""
    j.close()


# -- a render with several voices and tags (fake worker, no model) --------------------------------------------

def write_wav(path: Path, freq: float):
    pcm = (3000 * np.sin(np.linspace(0, freq, 16000 * 8))).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is needed to build the audiobook")
def test_render_uses_each_speakers_voice_and_tags(tmp_path, monkeypatch):
    from folivox import config
    from folivox.pipeline import Events, RenderOptions, render
    from folivox.tts import builds, fish, fish_setup, licences

    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    config.load.cache_clear()
    monkeypatch.setattr(builds, "engines_root", lambda: tmp_path / "engines")
    monkeypatch.setattr(builds, "detect_hardware", lambda: builds.Hardware("darwin", "arm64", 64.0, 50.0))
    worker = tmp_path / "w.py"
    worker.write_text(
        "import json, sys\nimport numpy as np\n"
        "for line in sys.stdin:\n    r = json.loads(line)\n"
        "    if r['cmd'] == 'quit': break\n"
        "    if r['cmd'] == 'load':\n"
        "        print(json.dumps({'ok': True, 'sample_rate': 16000, 'load_s': 0, 'warm_s': 0}), flush=True)\n"
        "    else:\n"
        "        np.save(r['out'], np.zeros(16000, np.float32) + 0.1)\n"
        "        print(json.dumps({'ok': True, 'id': r['id'], 'out': r['out'], 'audio_s': 1, 'seconds': 0,\n"
        "                          'peak_gb': 1}), flush=True)\n")
    log = tmp_path / "calls.jsonl"
    # the engine deletes its temp files: record the requests through a wrapper around _Worker.call
    real_call = fish._Worker.call

    def spy(self, req, timeout):
        if req["cmd"] == "synth":
            log.open("a").write(json.dumps({"text": req["text"], "wav": Path(req["refs"][0]["wav"]).name}) + "\n")
        return real_call(self, req, timeout)

    monkeypatch.setattr(fish._Worker, "call", spy)
    monkeypatch.setattr(fish, "WORKER", worker)
    monkeypatch.setattr(fish_setup, "venv_python", lambda rt: Path(sys.executable))
    monkeypatch.setattr(fish_setup, "is_ready", lambda b: True)
    monkeypatch.setattr(fish, "to_reference_wav", lambda src, dst: Path(src))
    licences.accept("fish-research")

    main, anna = tmp_path / "main.wav", tmp_path / "anna.wav"
    write_wav(main, 3000)
    write_wav(anna, 5000)
    anna.with_suffix(".txt").write_text("Голос Анны.", encoding="utf-8")
    book = Book(title="T", lang="ru", sections=[Section(title="Глава", blocks=list(CH.blocks))])
    m = marked()
    m.speaker(1).voice = str(anna)
    mk.stamp(m, book.chapters(2))
    mf = tmp_path / "b.markup.json"
    m.save(mf)

    class Rec(Events):
        warnings: list = []

        def warning(self, msg):
            self.warnings.append(msg)

    ev = Rec()
    ev.warnings = []
    out = render(book, RenderOptions(output=tmp_path / "b.m4b", tts="fish-s2", voice_wav=main,
                                     voice_text="Главный голос.", qa=False, stress="none", markup=mf,
                                     work_dir=tmp_path / "w"), ev)
    assert out.exists()
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    by_wav = {c["wav"] for c in calls}
    assert by_wav == {"main.wav", "anna.wav"}  # the narrator and the speaker with a voice of their own
    assert any(c["wav"] == "anna.wav" and c["text"].startswith("[whispering]") for c in calls)
    assert any(c["text"].startswith("[sighs]") for c in calls)
    j = Journal(tmp_path / "w")
    assert {c.speaker for c in j.chunks()} == {0, 1, 2}
    j.close()


def test_cli_export_import_check(tmp_path):
    from folivox.cli import app

    book = tmp_path / "book.txt"
    book.write_text("Глава 1\n\n" + TEXT + "\n\nВторой абзац книги.\n", encoding="utf-8")
    r = CliRunner()
    exported = tmp_path / "m.txt"
    res = r.invoke(app, ["markup", "export", str(book), "-o", str(exported)])
    assert res.exit_code == 0, res.output
    body = exported.read_text(encoding="utf-8")
    assert "@speaker 0 | Narrator" in body and "B1.0" in body
    edited = body.replace("@expression_tags", "@speaker 1 | Соседка |  | f\n@expression_tags")
    edited = edited.replace("B1.0  — Ты куда?", "B1.0  <|speaker:1|> [whispering] — Ты куда?")
    exported.write_text(edited, encoding="utf-8")
    res = r.invoke(app, ["markup", "import", str(book), str(exported)])
    assert res.exit_code == 0, res.output
    saved = json.loads((tmp_path / "book.markup.json").read_text(encoding="utf-8"))
    assert saved["speakers"][1]["name"] == "Соседка" and saved["chapters"]
    assert r.invoke(app, ["markup", "check", str(book)]).exit_code == 0
    exported.write_text(edited.replace("Второй абзац", "Третий абзац"), encoding="utf-8")
    res = r.invoke(app, ["markup", "import", str(book), str(exported)])
    assert res.exit_code == 1 and "text differs" in res.output
    assert r.invoke(app, ["markup", "tags", "--category", "emotion"]).exit_code == 0
    assert r.invoke(app, ["markup", "speakers", str(book)]).exit_code == 0
    assert r.invoke(app, ["markup", "speaker", str(book), "2", "--name", "Он", "--voice", "ru-helga35"]).exit_code == 0
    assert r.invoke(app, ["markup", "clear", str(book)]).exit_code == 0
    assert not (tmp_path / "book.markup.json").exists()
