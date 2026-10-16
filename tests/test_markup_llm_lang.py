"""The markup model may name the language of a part; the answer is checked before it is kept."""

import json

from folivox import markup as mk
from folivox import markup_llm as ml
from folivox.book import Block, BlockKind, Chapter
from folivox.llm import LLM

DE = ("Der Mann ist nicht da und die Frau ist es auch nicht, sagte er mit einer leisen Stimme zu ihr. " * 6)
P1 = "„Je ne sais pas, mon ami“, sagte Anna und lachte."
P2 = "„Das ist nicht wahr“, sagte Anna."
CH = [Chapter("Kapitel", [Block(BlockKind.PARAGRAPH, t) for t in (DE, P1, P2)])]


class Scripted(LLM):
    name = "scripted"

    def __init__(self, lang_answer):
        self.prompts, self.lang_answer = [], lang_answer

    def complete(self, prompt, system=None, temperature=0.3):
        return self.complete_json(prompt, system, temperature)

    def complete_json(self, prompt, system=None, temperature=0.2):
        self.prompts.append(prompt)
        item1 = {"b": 1, "who": {"1": 1}, **({"lang": self.lang_answer} if self.lang_answer is not None else {})}
        return json.dumps({"blocks": [item1, {"b": 2, "who": {"1": 1}}], "new_characters": [], "updates": []})


def bible():
    b = ml.Bible()
    b.merge({"name": "Anna", "gender": "f", "lines": 5})
    b.assign_ids()
    return b


def run(llm, **kw):
    runner = ml.Runner(llm, "m", ml.Cache(None))
    return ml.annotate(CH, "de", bible(), runner, **kw)


def test_other_languages_of_a_book():
    fr = "Il est dans la maison avec une amie qui ne se tait pas. " * 12
    ch = [Chapter("x", [Block(BlockKind.PARAGRAPH, DE), Block(BlockKind.PARAGRAPH, fr)])]
    assert ml.other_languages(ch, "de") == ["fr"]
    assert ml.other_languages(CH, "de") == []


def test_the_prompt_is_unchanged_for_a_one_language_book_and_asks_about_languages_otherwise():
    plain = ml.parts_prompt("de", (), hints="H", person="third", speakers="[]", recent="", text="T")
    assert "ISO 639-1" not in plain and "lang_rule" not in plain
    assert plain == ml.PARTS_PROMPT.format(lang="German", lang_rule="", lang_json="", hints="H", person="third",
                                           speakers="[]", recent="", text="T")
    multi = ml.parts_prompt("de", ["fr"], hints="H", person="third", speakers="[]", recent="", text="T")
    assert "ISO 639-1" in multi and "French" in multi and '"lang"' in multi


def test_the_models_language_for_a_part_is_kept():
    llm = Scripted({"1": "fr"})
    markup, _ = run(llm, other_langs=["fr"])
    spans = [s for s in markup.chapters[0].spans if s.block == 1]
    assert spans and spans[0].lang == "fr" and spans[0].speaker == 1
    assert "ISO 639-1" in llm.prompts[0]


def test_unknown_or_implausible_languages_are_dropped():
    for bad in ({"1": "xx"}, {"1": "de"}, {"1": "ja"}, "fr", ["fr"], {"x": "fr"}):
        markup, _ = run(Scripted(bad), other_langs=["fr"])
        assert all(s.lang == "" for s in markup.chapters[0].spans), bad
    # a German part claimed to be French is refused by the function words
    markup, _ = run(Scripted({"1": "fr"}), other_langs=["fr"])
    b2 = [s for s in markup.chapters[0].spans if s.block == 2]
    assert all(s.lang == "" for s in b2)


def test_without_other_languages_the_answer_lang_is_ignored_and_the_prompt_is_old():
    llm = Scripted({"1": "fr"})
    markup, _ = run(llm, other_langs=[])
    assert all(s.lang == "" for s in markup.chapters[0].spans)
    assert "ISO 639-1" not in llm.prompts[0]


def test_spans_from_ids_merges_by_speaker_and_language():
    t = "ab cd ef"
    parts = [(0, 2), (3, 5), (6, 8)]
    spans = ml.spans_from_ids(0, t, parts, [0, 0, 1], ["en", "en", ""])
    assert [(s.start, s.end, s.speaker, s.lang) for s in spans] == [(0, 5, 0, "en"), (6, 8, 1, "")]
    assert ml.spans_from_ids(0, t, parts, [1, 0, 0]) == [mk.Span(0, 0, 2, 1)]
