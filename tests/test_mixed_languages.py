"""Books that mix languages: every fragment is planned, synthesised and checked in its own language."""

from pathlib import Path

import numpy as np

from folivox import markup as mk
from folivox.book import Block, BlockKind, Chapter
from folivox.journal import Journal, chunk_key
from folivox.text.chunk import ChunkOptions, MarkupContext, plan_chapter
from folivox.text.pronounce import Lexicon

RU = "Слово пишется так: Good morning, everyone! А потом читается медленно."
RU_PLAIN = "Это обычный русский абзац, в котором нет ни одного чужого слова. Он просто длинный."


def chapter(*texts: str) -> Chapter:
    return Chapter("Глава", [Block(BlockKind.PARAGRAPH, t) for t in texts])


def langs(chunks) -> list[tuple[str, str]]:
    return [(c.lang, c.source) for c in chunks]


def test_english_phrase_in_russian_text_is_its_own_fragment_with_its_language():
    chunks = plan_chapter(chapter(RU), ChunkOptions(lang="ru", stress="none"))
    assert [c.lang for c in chunks] == ["", "en", ""]
    assert chunks[1].source == "Good morning, everyone!"
    assert "".join(c.source.replace(" ", "") for c in chunks) == RU.replace(" ", "")


def test_numbers_in_an_english_fragment_are_spelled_in_english():
    chunks = plan_chapter(chapter("Скажите так: I have 5 apples today. Потом повторите."),
                          ChunkOptions(lang="ru", stress="none"))
    en = [c for c in chunks if c.lang == "en"]
    assert en and "five apples" in en[0].text


def test_german_book_with_a_french_line_marked_in_the_markup():
    t = "„Je ne sais pas, mon ami“, sagte Anna leise und ging hinaus."
    a = t.index("Je ne")
    m = mk.Markup()
    m.assign(0, 0, a, a + len("Je ne sais pas, mon ami"), 0, lang="fr")
    chunks = plan_chapter(chapter(t), ChunkOptions(lang="de"), MarkupContext(m, 0, False))
    assert [c.lang for c in chunks if "Je ne" in c.source] == ["fr"]
    assert all(c.lang == "" for c in chunks if "sagte" in c.source)


def test_cjk_inside_english():
    chunks = plan_chapter(chapter("The word 水 is read shui and 日本語 is Japanese, ひらがな too."),
                          ChunkOptions(lang="en"))
    assert [c.lang for c in chunks if c.lang] == ["zh", "zh", "ja"] or {c.lang for c in chunks} >= {"zh", "ja"}


def test_a_one_language_book_plans_exactly_as_before():
    ch = chapter(RU_PLAIN, "— Ты куда? — спросила соседка.", "Ещё один абзац без вставок, обычный и длинный.")
    new = plan_chapter(ch, ChunkOptions(lang="ru", stress="none"))
    old = plan_chapter(ch, ChunkOptions(lang="ru", stress="none", mixed=False))
    assert [(c.text, c.source, c.pause_after, c.kind, c.speaker, c.lang) for c in new] == \
           [(c.text, c.source, c.pause_after, c.kind, c.speaker, c.lang) for c in old]
    assert all(c.lang == "" for c in new)


def test_an_engine_that_cannot_read_the_language_leaves_it_to_the_book_language():
    opts = ChunkOptions(lang="ru", stress="none", speaks=frozenset({"ru", "de"}))
    chunks = plan_chapter(chapter(RU), opts)
    assert all(c.lang == "" for c in chunks)
    assert opts.fallbacks["en"] == 1


def test_a_language_without_text_rules_is_a_fallback_too():
    t = "Он сказал: Dzień dobry wszystkim, и ушёл."
    m = mk.Markup()
    a = t.index("Dzień")
    m.assign(0, 0, a, a + len("Dzień dobry wszystkim,"), 0, lang="pl")
    opts = ChunkOptions(lang="ru", stress="none")
    assert all(c.lang == "" for c in plan_chapter(chapter(t), opts, MarkupContext(m, 0, False)))
    assert opts.fallbacks["pl"] == 1


def test_a_pronunciation_entry_keeps_its_word_in_the_book_language(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("iPhone = айфон\n", encoding="utf-8")
    t = "Купил новый iPhone вчера."
    chunks = plan_chapter(chapter(t), ChunkOptions(lang="ru", stress="none", lexicon=Lexicon.load([f])))
    assert all(c.lang == "" for c in chunks) and any("айфон" in c.text for c in chunks)
    assert any(c.lang == "en" for c in plan_chapter(chapter(t), ChunkOptions(lang="ru", stress="none")))


def test_stress_marks_are_only_for_russian_fragments(monkeypatch):
    from folivox.text import stress

    monkeypatch.setattr(stress, "apply", lambda text, mode: text.replace("о", "о\u0301"))
    chunks = plan_chapter(chapter("Хорошая погода сегодня. Скажите: Good morning, my friend! Спасибо большое."),
                          ChunkOptions(lang="ru", stress="all"))
    en = [c for c in chunks if c.lang == "en"]
    assert en and en[0].text == "Good morning, my friend!"
    assert any("\u0301" in c.text for c in chunks if not c.lang)


def test_the_journal_keeps_the_language_and_old_keys_stay_valid(tmp_path):
    base = chunk_key("t", "v", "s")
    assert chunk_key("t", "v", "s", lang="") == base
    assert chunk_key("t", "v", "s", lang="en") != base
    chunks = plan_chapter(chapter(RU), ChunkOptions(lang="ru", stress="none"))
    j = Journal(tmp_path)
    j.set_plan([("Глава", chunks)], "v", "s")
    got = j.chunks()
    assert [c.lang for c in got] == ["", "en", ""]
    assert len({c.key for c in got}) == 3
    j.close()


class _Engine:
    sample_rate = 1000
    local = True
    parallel = 1

    def __init__(self):
        self.langs = []

    def prepare(self, text, voice, seed=0, lang=""):
        self.langs.append(lang)
        return (text, seed), 0.0

    def finish(self, prepared, voice, speed=1.0):
        return (0.5 * np.sin(np.arange(int(len(prepared[0]) * 60)) / 3)).astype(np.float32), 0.0


class _ASR:
    def __init__(self):
        self.languages = []

    def transcribe(self, audio, sr, prompt=None, language=None):
        self.languages.append(language)
        return self.text


def _take(text, fragment_lang=""):
    from folivox.pipeline import RenderOptions, _best_take
    from folivox.tts.base import Prefetcher

    eng, asr = _Engine(), _ASR()
    asr.text = text
    opts = RenderOptions(output=Path("x.m4b"), voice_wav=Path("v.wav"), lang="ru", max_takes=1)
    out = _best_take(Prefetcher(eng, object()), asr, opts, "k", text, text, fragment_lang=fragment_lang)
    return out, eng, asr


def test_the_engine_and_the_recogniser_get_the_fragment_language():
    _, eng, asr = _take("Good morning, everyone!", "en")
    assert eng.langs == ["en"] and asr.languages == ["en"]


def test_a_book_language_fragment_is_called_exactly_as_before():
    _, eng, asr = _take("Доброе утро, друзья мои!")
    assert eng.langs == [""] and asr.languages == [None]


def test_qa_of_an_english_fragment_in_a_russian_book_is_not_skipped():
    # the share of Latin letters would exempt it from the check in a Russian fragment
    (sc, *_), _, asr = _take("Good morning, everyone!", "en")
    assert asr.languages == ["en"]
    (sc, *_), _, asr2 = _take("Good morning, everyone!")
    assert asr2.languages == []  # book language: the old rule skips the check (mostly Latin letters)


def test_cloud_notes_name_the_fragment_language():
    from test_cloud import Fake, make, ok, wav_bytes

    from folivox.tts.cloud import CloudTTS
    from folivox.voicegen.cloud_apis import OpenAIVoice

    eng = CloudTTS("openai", generator=make(OpenAIVoice, Fake(ok(wav_bytes()))))
    voice = eng.make_voice("coral", None, "ru")
    assert "Russian" in voice.style
    en = eng.note_for(voice, "en")
    assert "Russian" not in en and "native speaker" not in en
    de = eng.note_for(voice, "de")
    assert "German" in de and "Russian" not in de
    assert eng.note_for(voice, "") == voice.style


def test_plan_reads_the_engines_languages_and_warns_about_the_fallback(tmp_path, monkeypatch):
    from folivox import pipeline
    from folivox.book import Book, Section
    from folivox.pipeline import Events, RenderOptions, plan

    assert pipeline.engine_languages("cosyvoice3") >= {"ru", "en", "de"}
    assert pipeline.engine_languages("elevenlabs") is None or "en" in pipeline.engine_languages("elevenlabs")
    book = Book(title="T", lang="ru", sections=[Section(title="Глава", blocks=[Block(BlockKind.PARAGRAPH, RU)])])

    class Rec(Events):
        def __init__(self):
            self.warnings = []

        def warning(self, message):
            self.warnings.append(message)

    def run(speaks):
        monkeypatch.setattr(pipeline, "engine_languages", lambda name, engine=None: speaks)
        ev, j = Rec(), Journal(tmp_path / str(len(speaks)))
        plan(book, RenderOptions(output=tmp_path / "o.m4b", stress="none"), j, "v", ev)
        out = [c.lang for c in j.chunks()]
        j.close()
        return out, ev.warnings

    assert run(frozenset({"ru", "en"})) == (["", "", "en", ""], [])  # the chapter title comes first
    langs_, warnings = run(frozenset({"ru"}))
    assert langs_ == ["", "", "", ""] and len(warnings) == 1 and "English" in warnings[0] and "Russian" in warnings[0]


def test_voice_accent_notes_name_the_voice_and_the_language(tmp_path):
    from folivox import voices as catalog
    from folivox.pipeline import RenderOptions, voice_accent_notes

    ru_voice = catalog.find("russlib")
    opts = RenderOptions(output=tmp_path / "o.m4b", voice_wav=ru_voice.path)
    chunks = plan_chapter(chapter(RU), ChunkOptions(lang="ru", stress="none"))
    j = Journal(tmp_path)
    j.set_plan([("Глава", chunks)], "v", "s")
    notes = voice_accent_notes(j, None, opts)
    assert len(notes) == 1 and "English" in notes[0] and "Russian" in notes[0]
    en_opts = RenderOptions(output=tmp_path / "o.m4b", voice_wav=catalog.find("en-ben-tucker").path)
    assert voice_accent_notes(j, None, en_opts) == []  # an English voice reads the English fragments natively
    j.close()
    j2 = Journal(tmp_path / "plain")
    j2.set_plan([("Глава", plan_chapter(chapter(RU_PLAIN), ChunkOptions(lang="ru", stress="none")))], "v", "s")
    assert voice_accent_notes(j2, None, opts) == []
    j2.close()
