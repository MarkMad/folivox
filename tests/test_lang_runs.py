"""Stretches of another language found by script, and language shares over a whole text."""

from folivox import markup as mk
from folivox.lang.detect import latin_lang, shares
from folivox.lang.runs import script_runs


def found(text: str, lang: str) -> list[tuple[str, str]]:
    return [(text[r.start:r.end], r.lang) for r in script_runs(text, lang)]


def test_english_phrases_and_words_in_russian_text():
    t = "Слово apple переводится как «яблоко». Фраза How are you? значит «как дела»."
    assert found(t, "ru") == [("apple", "en"), ("How are you?", "en")]


def test_a_phrase_keeps_the_numbers_and_light_punctuation_between_its_words():
    assert found("Нажмите Windows 10 Pro, потом Next.", "ru") == [("Windows 10 Pro,", "en"), ("Next.", "en")]


def test_abbreviations_roman_numerals_urls_and_short_words_are_left_alone():
    t = "Через USB в XIV веке по www.example.com или info@example.com, а ещё a и ok."
    assert found(t, "ru") == []


def test_french_words_are_told_from_english():
    assert found("Он сказал: Je ne sais pas, mon ami, и ушёл.", "ru") == [("Je ne sais pas, mon ami,", "fr")]


def test_cyrillic_and_cjk_inside_english():
    t = "The word 水 means water; ひらがな is kana; Привет, мир! is Russian."
    assert found(t, "en") == [("水", "zh"), ("ひらがな", "ja"), ("Привет, мир!", "ru")]


def test_a_text_in_one_script_has_no_runs():
    assert found("Это обычный русский текст без вставок.", "ru") == []
    assert found("An ordinary English text with 12 numbers and an e-mail a@b.co.", "en") == []
    assert found("日本語の文章です。", "ja") == []


def test_same_script_languages_are_not_guessed_here():
    assert found("Er sagte: « Je ne sais pas, mon ami. » und ging.", "de") == []


def test_segments_carry_the_language_of_the_runs_and_cover_the_text():
    t = "Он сказал: Good morning, everyone! И ушёл."
    m = mk.Markup()
    segs = m.segments(0, 0, t, "ru")
    assert "".join(s.text for s in segs) == t
    assert [(s.text, s.lang) for s in segs if s.lang] == [("Good morning, everyone!", "en")]
    assert m.segments(0, 0, t) == [mk.Segment(t, 0)]  # without the book language nothing is guessed
    assert m.segments(0, 0, "Только русский текст.", "ru") == [mk.Segment("Только русский текст.", 0)]


def test_an_explicit_language_wins_over_the_script_guess():
    t = "Он сказал: Good morning, everyone! И ушёл."
    m = mk.Markup()
    a = t.index("Good")
    m.assign(0, 0, a, a + 4, 0, lang="de")
    langs = {s.text: s.lang for s in m.segments(0, 0, t, "ru") if s.lang}
    assert langs["Good"] == "de"


def test_latin_language_guess():
    assert latin_lang("Das ist nicht gut") == "de"
    assert latin_lang("hello there") == "en"
    assert latin_lang("zzz qqq") == "en"
    assert latin_lang("zzz qqq", "") == ""


def test_shares_over_the_whole_book_not_only_its_start():
    ru = "Это русский текст про что-то важное и длинное. " * 100
    en = "This is the english part of the book and it is long. " * 20
    s = shares(ru * 5 + en * 5)
    assert list(s) == ["ru", "en"]
    assert abs(s["ru"] + s["en"] - 1) < 0.01
    assert 0.1 < s["en"] < 0.3  # the English comes after 20k+ characters of Russian
    assert shares(ru) == {"ru": 1.0}
    assert shares("1234 !!!") == {}


def test_shares_tell_latin_languages_apart():
    de = "Der Mann ist nicht da und die Frau ist es auch nicht. " * 40
    fr = "Il est dans la maison avec une amie qui ne se tait pas. " * 40
    s = shares(de + fr)
    assert set(s) == {"de", "fr"}
