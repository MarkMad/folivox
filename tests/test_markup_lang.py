"""Language of a fragment in the markup data: storage, old files, text form."""

import json

import pytest

from folivox import markup as mk
from folivox.book import Block, BlockKind, Chapter

TEXT = "Он сказал: Good morning, everyone! И ушёл."
CH = Chapter("Глава", [Block(BlockKind.PARAGRAPH, TEXT)])
A = TEXT.index("Good")
B = TEXT.index(" И ушёл")


def test_a_span_with_a_language_round_trips_through_json():
    m = mk.Markup()
    m.assign(0, 0, A, B, 0, lang="en")
    mk.stamp(m, [CH])
    d = m.to_dict()
    assert d["chapters"]["0"]["spans"] == [{"b": 0, "s": A, "e": B, "sp": 0, "tags": [], "lang": "en"}]
    back = mk.Markup.from_dict(json.loads(json.dumps(d)))
    assert back.chapters[0].spans == m.chapters[0].spans
    segs = back.segments(0, 0, TEXT)
    assert "".join(s.text for s in segs) == TEXT
    assert [(s.text, s.lang) for s in segs if s.lang] == [("Good morning, everyone!", "en")]


def test_old_files_without_a_language_store_and_read_the_same():
    m = mk.Markup()
    m.ensure_speaker(1, "A")
    m.assign(0, 0, 0, 7, 1)
    assert "lang" not in json.dumps(m.to_dict())
    old = m.to_dict()
    assert mk.Markup.from_dict(old).chapters[0].spans[0].lang == ""


def test_unknown_codes_are_dropped_and_names_normalised():
    d = {"version": 1, "chapters": {"0": {"spans": [{"b": 0, "s": 0, "e": 3, "sp": 0, "lang": "xx"},
                                                    {"b": 0, "s": 4, "e": 7, "sp": 0, "lang": "EN-us"}]}}}
    spans = mk.Markup.from_dict(d).chapters[0].spans
    assert [s.lang for s in spans] == ["", "en"]


def test_assign_keeps_the_language_of_the_parts_it_cuts():
    m = mk.Markup()
    m.assign(0, 0, 10, 30, 0, lang="en")
    m.assign(0, 0, 15, 20, 0, ("whispering",))
    assert [(s.start, s.end, s.lang) for s in m.chapters[0].spans] == [(10, 15, "en"), (15, 20, ""), (20, 30, "en")]


def test_text_form_round_trips_the_language():
    m = mk.Markup()
    m.ensure_speaker(1, "A")
    m.assign(0, 0, A, B, 1, lang="en")
    mk.stamp(m, [CH])
    text = mk.export_text(m, [CH])
    assert "<|lang:en|>" in text and "<|lang:-|>" in text
    back = mk.import_text(text, [CH])
    assert back.chapters[0].spans == m.chapters[0].spans


def test_text_form_rejects_an_unknown_language():
    text = "@speaker 0 | Narrator | |\nB1.0  <|lang:xx|> " + TEXT + "\n"
    with pytest.raises(mk.MarkupError):
        mk.import_text(text, [CH])


def test_languages_only_drops_speakers_and_tags_but_keeps_the_languages():
    m = mk.Markup()
    m.ensure_speaker(1, "A")
    m.assign(0, 0, 0, 5, 1, ("whispering",))
    m.assign(0, 0, A, B, 1, lang="en")
    m.add_mark(0, 0, 3, "sighs")
    mk.stamp(m, [CH])
    only = m.languages_only()
    assert [(s.start, s.end, s.speaker, s.tags, s.lang) for s in only.chapters[0].spans] == [(A, B, 0, (), "en")]
    assert not only.chapters[0].marks and only.used_speakers() == {0}
    plain = mk.Markup()
    plain.assign(0, 0, 0, 5, 0, ("whispering",))
    assert plain.languages_only().is_empty()
