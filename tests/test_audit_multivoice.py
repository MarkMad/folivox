"""Audit regressions: markup parsing and binding, script runs, Russian speech-verb gender."""

from types import SimpleNamespace

import pytest

from folivox import markup as mk
from folivox.lang.attribution import RU_SAID
from folivox.lang.runs import script_runs


def _chapter(*texts):
    return SimpleNamespace(title="T", blocks=[SimpleNamespace(text=t) for t in texts])


@pytest.mark.parametrize("bad", [[], {"version": 1, "chapters": []}, {"version": 1, "chapters": {"0": []}}])
def test_malformed_markup_raises_markup_error(bad):
    with pytest.raises(mk.MarkupError):
        mk.Markup.from_dict(bad)


def test_bind_ignores_negative_chapter():
    m = mk.Markup()
    m.chapters[-1] = mk.ChapterMarkup(spans=[mk.Span(0, 0, 3, 0, (), "en")])
    out, problems = mk.bind(m, [_chapter("abc def"), _chapter("xyz")])
    assert not out.chapters and problems


def test_japanese_mixed_kanji_kana_found_in_russian():
    text = "Он сказал: 東京です и ушёл."
    runs = script_runs(text, "ru")
    assert [(text[r.start:r.end], r.lang) for r in runs] == [("東京です", "ja")]


def test_ru_said_proiznesla_is_feminine():
    assert RU_SAID.search("произнесла она").group(2) == "а"
    assert RU_SAID.search("произнёс он").group(2) is None
