"""Automatic markup: character bible, annotation with verification, resuming and caching, all with a fake LLM."""

import json
import re

import pytest
from typer.testing import CliRunner

from folivox import markup as mk
from folivox import markup_llm as ml
from folivox.book import Block, BlockKind, Chapter
from folivox.llm import LLM, recommend_model

P1 = "Анна вошла в комнату."
P2 = "— Ты куда? — спросила Анна."
P3 = "— Домой, — ответил Борис и вздохнул."
P4 = "Дверь тихо закрылась."
P5 = "— Подожди, — сказала она."  # "she" = Anna, resolved from context
CH = [Chapter("Глава 1", [Block(BlockKind.PARAGRAPH, t) for t in (P1, P2, P3, P4)]),
      Chapter("Глава 2", [Block(BlockKind.PARAGRAPH, P5)])]
CAST = {"Анна": "f", "Борис": "m"}


class FakeLLM(LLM):
    """Plays a model that understands the cast above; modes make it misbehave."""

    name = "fake"

    def __init__(self, mode="good"):
        self.mode, self.calls = mode, []

    def complete(self, prompt, system=None, temperature=0.3):
        return self.complete_json(prompt, system, temperature)

    def complete_json(self, prompt, system=None, temperature=0.2):
        self.calls.append(system[:20])
        if self.mode == "down":
            raise OSError("connection refused")
        if self.mode == "garbage" or (self.mode == "flaky" and len(self.calls) % 2 == 1):
            return "I cannot do that, sorry"
        excerpt = prompt.split("Excerpt:\n")[-1] if "Excerpt:" in prompt else prompt.split("Paragraphs:\n")[-1]
        blocks = re.findall(r"\[B(\d+)\] (.*)", excerpt)
        if system.startswith("You are a careful"):
            chars = []
            for name, g in CAST.items():
                n = sum(1 for _, t in blocks if t.startswith("—") and name in t)
                if any(name in t for _, t in blocks):
                    chars.append({"name": name, "aliases": [], "gender": g, "role": "main", "lines": n,
                                  "traits": "calm"})
            return json.dumps({"narration_person": "third", "characters": chars}, ensure_ascii=False)
        speakers = json.loads(re.search(r"\n(\[\{.*\}\])\n", prompt).group(1))
        ids = {s["name"]: s["id"] for s in speakers}
        out = []
        for b, t in blocks:
            if not t.startswith("—"):
                continue
            who = next((n for n in CAST if n in t), "Анна" if "она" in t else None)
            if who is None or who not in ids:
                continue
            if self.mode == "rewrite" and "Домой" in t:
                text = t.replace("Домой", "Домой же")
            elif self.mode == "unknown_speaker":
                text = f"<|speaker:9|>{t}"
            elif self.mode == "tags":
                text = f"<|speaker:{ids[who]}|>[sighs] {t} [fakeeffect]"
            else:
                m = re.match(r"(— .*?[?!.,])( ?— .*)$", t)
                text = (f"<|speaker:{ids[who]}|>{m.group(1)} <|speaker:0|>{m.group(2).strip()}" if m
                        else f"<|speaker:{ids[who]}|>{t}")
            out.append({"b": int(b), "text": text})
        return json.dumps({"blocks": out, "new_characters": [], "updates": []}, ensure_ascii=False)


def run_analyse(llm=None, **kw):
    llm = llm or FakeLLM()
    runner = ml.Runner(llm, "fake-model", ml.Cache(None))
    return ml.analyse(CH, "ru", runner, **kw), runner, llm


def test_names_match_across_cases_and_aliases():
    assert ml.same_name("Анна", "Анны") and ml.same_name("Иван", "Ивана") and ml.same_name("Петр", "Петя")
    assert not ml.same_name("Ольга", "Олег") and not ml.same_name("Маша", "Миша")
    b = ml.Bible()
    anna = b.merge({"name": "Анна", "gender": "f", "lines": 2})
    again = b.merge({"name": "Анну", "aliases": ["Аня"], "lines": 3, "traits": "quiet"})
    assert again is anna and anna.lines == 5 and "Аня" in anna.aliases and "Анну" in anna.aliases
    assert b.merge({"name": "Аня"}) is anna  # found through the alias
    assert b.merge({"name": ""}) is None


def test_analyse_builds_the_bible_and_counts_voices():
    bible, runner, _ = run_analyse()
    names = {c.name: c for c in bible.characters}
    assert set(names) == {"Анна", "Борис"} and names["Анна"].gender == "f" and names["Борис"].lines == 1
    assert names["Анна"].lines >= 1 and bible.narration == "third"
    assert {c.id for c in bible.characters} == {1, 2}
    assert bible.voices_needed(min_lines=1) == 3 and bible.voices_needed() == 1  # nobody reaches 3 lines here


def test_bible_round_trip(tmp_path):
    bible, _, _ = run_analyse()
    f = tmp_path / "b.characters.json"
    bible.save(f)
    again = ml.Bible.load(f)
    assert again.to_dict() == bible.to_dict()
    f.write_text("[1]")
    with pytest.raises(ml.LLMError):
        ml.Bible.load(f)


def test_analyse_is_resumable_and_cached():
    cache = ml.Cache(None)
    llm = FakeLLM()
    runner = ml.Runner(llm, "m", cache)
    bible = ml.analyse(CH, "ru", runner)
    calls = len(llm.calls)
    assert calls == 2  # one window per chapter
    # same book, same cache, fresh bible: nothing is asked again
    again = ml.analyse(CH, "ru", ml.Runner(llm, "m", cache))
    assert len(llm.calls) == calls and {c.name for c in again.characters} == {c.name for c in bible.characters}
    # a bible that already did the first window continues with the second
    part = ml.Bible()
    part.done_windows = 1
    llm2 = FakeLLM()
    ml.analyse(CH, "ru", ml.Runner(llm2, "m", ml.Cache(None)), part)
    assert len(llm2.calls) == 1


def test_analyse_survives_a_garbage_model_and_reports_a_dead_one():
    bible, runner, _ = run_analyse(FakeLLM("garbage"))
    assert bible.characters == [] and runner.failures == 2
    flaky, runner, _ = run_analyse(FakeLLM("flaky"))
    assert {c.name for c in flaky.characters} == {"Анна", "Борис"}  # the retry worked
    with pytest.raises(ml.LLMError, match="did not answer"):
        run_analyse(FakeLLM("down"))


def test_more_than_fifteen_speakers_share_the_last_ids():
    b = ml.Bible()
    names = "Альфа Бета Гамма Дельта Эпсилон Зита Тета Йота Каппа Лямбда Сигма Омега Ро Хи Пси Тау Фи Эта Мю Ню".split()
    for i, n in enumerate(names):
        b.merge({"name": n, "gender": "f" if i % 2 else "m", "lines": 40 - i})
    b.assign_ids()
    ids = [c.id for c in sorted(b.characters, key=lambda c: -c.lines)]
    assert ids[:13] == list(range(1, 14)) and set(ids[13:]) <= {14, 15} and max(ids) <= 15


def annotate(llm=None, bible=None, **kw):
    bible = bible or run_analyse()[0]
    llm = llm or FakeLLM()
    runner = ml.Runner(llm, "fake-model", ml.Cache(None))
    markup, stats = ml.annotate(CH, "ru", bible, runner, **kw)
    return markup, stats, bible


def test_annotate_marks_speech_and_leaves_the_text_alone():
    markup, stats, bible = annotate()
    ids = {c.name: c.id for c in bible.characters}
    spans = markup.chapters[0].spans
    q = [s for s in spans if s.block == 1]
    assert len(q) == 1 and q[0].speaker == ids["Анна"] and P2[q[0].start:q[0].end].startswith("— Ты куда?")
    assert [s.speaker for s in spans if s.block == 2] == [ids["Борис"]]
    assert stats.marked == 3 and stats.fell_back == 0
    assert markup.chapters[1].spans[0].speaker == ids["Анна"]  # "she" resolved by the model with the bible
    segs = markup.segments(0, 1, P2)
    assert "".join(s.text for s in segs) == P2
    assert {s.name for s in markup.speakers} >= {"Narrator", "Анна", "Борис"}
    # the result is valid for the book
    clean, problems = mk.bind(markup, CH)
    assert not problems and clean.chapters.keys() == markup.chapters.keys()


def test_annotate_never_accepts_changed_text_or_unknown_speakers():
    markup, stats, _ = annotate(FakeLLM("rewrite"))
    assert not [s for s in markup.chapters[0].spans if s.block == 2]  # the rewritten paragraph stays narrator
    assert stats.fell_back == 1 and stats.marked == 2
    markup, stats, _ = annotate(FakeLLM("unknown_speaker"))
    assert stats.unknown_speakers >= 1 and not any(s.speaker == 9 for c in markup.chapters.values() for s in c.spans)
    markup, stats, _ = annotate(FakeLLM("garbage"))
    assert stats.failed_windows == 2 and markup.is_empty()


def test_expression_tags_are_validated_against_the_database():
    markup, stats, _ = annotate(FakeLLM("tags"), expression_tags=True)
    used = {t for c in markup.chapters.values() for s in c.spans for t in s.tags}
    used |= {m.tag for c in markup.chapters.values() for m in c.marks}
    assert used == {"sighs"} and stats.dropped_tags >= 1
    off, stats2, _ = annotate(FakeLLM("tags"), expression_tags=False)
    assert not any(s.tags for c in off.chapters.values() for s in c.spans) and not any(
        c.marks for c in off.chapters.values())


def test_annotation_is_cached_and_chapters_can_be_filtered():
    cache = ml.Cache(None)
    bible = run_analyse()[0]
    llm = FakeLLM()
    ml.annotate(CH, "ru", bible, ml.Runner(llm, "m", cache))
    n = len(llm.calls)
    ml.annotate(CH, "ru", bible, ml.Runner(llm, "m", cache))
    assert len(llm.calls) == n
    markup, _ = ml.annotate(CH, "ru", bible, ml.Runner(FakeLLM(), "m", ml.Cache(None)), chapter_filter={1})
    assert set(markup.chapters) == {1}


def test_model_recommendation_follows_memory():
    assert recommend_model(64) == "gemma4:31b-it-qat" and recommend_model(36) == "gemma4:26b-a4b-it-qat"
    assert recommend_model(16) == "gemma4:12b-it-qat" and recommend_model(8) == "gemma4:e2b-it-qat"
    assert recommend_model(None) == "gemma4:12b-it-qat"


def test_json_extraction_is_forgiving():
    assert ml.extract_json('Sure!\n```json\n{"a": 1,}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        ml.extract_json("no json")


def test_cli_analyse_and_auto(tmp_path, monkeypatch):
    from folivox import cli_markup
    from folivox.cli import app

    book = tmp_path / "b.txt"
    book.write_text("Глава 1\n\n" + "\n\n".join((P1, P2, P3, P4)) + "\n\nГлава 2\n\n" + P5 + "\n", encoding="utf-8")
    monkeypatch.setattr(cli_markup, "_llm", lambda provider, model: (FakeLLM(), "fake-model"))
    r = CliRunner()
    res = r.invoke(app, ["markup", "analyse", str(book)])
    assert res.exit_code == 0, res.output
    assert "Voices needed" in res.output and (tmp_path / "b.characters.json").is_file()
    assert r.invoke(app, ["markup", "characters", str(book)]).exit_code == 0
    res = r.invoke(app, ["markup", "auto", str(book)])
    assert res.exit_code == 0, res.output
    saved = json.loads((tmp_path / "b.markup.json").read_text(encoding="utf-8"))
    assert saved["chapters"] and any(s["name"] == "Анна" for s in saved["speakers"])
    assert r.invoke(app, ["markup", "check", str(book)]).exit_code == 0
    assert r.invoke(app, ["markup", "models"]).exit_code == 0


# -- voice-design prompts for the characters -----------------------------------------------------------------

class VoiceLLM(FakeLLM):
    def __init__(self, reply=None):
        super().__init__()
        self.reply, self.prompts = reply, []

    def complete_json(self, prompt, system=None, temperature=0.2):
        self.prompts.append(prompt)
        if self.reply == "down":
            raise OSError("no server")
        return self.reply if self.reply is not None else json.dumps({
            "simple": "A woman in her thirties, calm and warm, speaking slowly.",
            "standard": "A woman in her thirties with a soft, warm mid-range voice, a native Russian speaker, "
                        "unhurried and gentle.",
            "detailed": "A woman in her thirties with a soft, warm mid-range voice, a native Russian speaker, "
                        "unhurried, with small pauses and a trace of tiredness that lifts when she is amused."})


def test_voice_ideas_are_english_tiered_and_never_use_the_name():
    from folivox.voices import character_voice as cv

    anna = ml.Character("Анна", gender="f", age="adult", traits="quiet", id=1, lines=5)
    ideas = cv.ideas_for(anna, "ru", VoiceLLM(), others=["A gruff old man"], lines=["— Ты куда?"])
    assert ideas.from_llm and set(ideas.prompts) == set(cv.TIERS)
    assert len(ideas.prompts["simple"]) <= cv.LIMITS["simple"] < len(ideas.prompts["detailed"]) <= cv.LIMITS["detailed"]
    # a tier that names the character or imitates a person is replaced by the plain fallback
    bad = json.dumps({"simple": "Анна, a woman with a warm voice", "standard": "She sounds like a famous actress today",
                      "detailed": "A calm adult woman, native Russian speaker, even pace, soft low timbre."})
    ideas = cv.ideas_for(anna, "ru", VoiceLLM(bad))
    base = cv.fallback_prompts(anna, "Russian")
    assert ideas.prompts["simple"] == base["simple"] and ideas.prompts["standard"] == base["standard"]
    assert ideas.prompts["detailed"].startswith("A calm adult woman")
    assert all(ord(ch) < 128 for p in base.values() for ch in p)  # plain English even for a Russian book


def test_voice_ideas_without_a_usable_model_fall_back_to_plain_text():
    from folivox.voices import character_voice as cv

    boris = ml.Character("Борис", gender="m", age="old", traits="ворчливый")
    for llm in (None, VoiceLLM("garbage"), VoiceLLM("down")):
        ideas = cv.ideas_for(boris, "ru", llm)
        assert not ideas.from_llm and "elderly man" in ideas.prompts["simple"]
        assert "ворчливый" not in ideas.prompts["standard"]  # a non-English trait is not pasted into the prompt


def test_design_all_tells_later_characters_how_to_differ_and_can_regenerate():
    from folivox.voices import character_voice as cv

    bible, _, _ = run_analyse()
    llm = VoiceLLM()
    assert cv.design_all(bible, "ru", llm) == 2
    assert all(c.voice_prompts for c in bible.characters)
    assert "none" in llm.prompts[0].split("already described")[1][:120] and "A woman in her thirties" in llm.prompts[1]
    assert cv.design_all(bible, "ru", llm) == 0  # nothing new: no calls
    assert len(llm.prompts) == 2
    first = bible.characters[0].id
    assert cv.design_all(bible, "ru", llm, speakers={first}) == 1  # one speaker again
    assert cv.design_all(bible, "ru", llm, regenerate=True) == 2


def test_sample_texts_are_the_characters_own_lines():
    from folivox.voices import character_voice as cv

    markup, _, bible = annotate()
    anna = next(c.id for c in bible.characters if c.name == "Анна")
    lines = cv.speaker_lines(markup, CH, anna, max_chars=300)
    assert lines and all(len(x) >= 25 for x in lines) or lines == []
    assert cv.sample_texts(markup, CH, anna, "ru")
    assert cv.sample_texts(None, None, 3, "ru") == cv.sample_texts(None, None, 4, "ru")  # the built-in sample


def test_loose_speaker_tags_are_read_as_the_tag_they_mean():
    from folivox.markup_llm import _fix_speaker_tags

    assert _fix_speaker_tags('<|speaker:1>"Hi" <|speaker:0|>said <speaker:2|>x <|speaker: 3 >y') == \
        '<|speaker:1|>"Hi" <|speaker:0|>said <|speaker:2|>x <|speaker:3|>y'


def test_spanish_dialogue_dash_without_space_counts_as_speech():
    from folivox.markup_llm import SPEECH_MARKS

    assert SPEECH_MARKS.search("—¿Vas a alguna parte? —preguntó Daniel.")
    assert SPEECH_MARKS.search("— Ты куда? — спросил он.")
    assert not SPEECH_MARKS.search("Plain narration without any speech.")
