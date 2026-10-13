import pytest

from folivox.book import Block, BlockKind, Chapter
from folivox.text.chunk import ChunkOptions, plan_chapter
from folivox.text.pronounce import ACUTE, Lexicon, PronounceError, find, normalize_stress, parse_phonemes


def lexicon(tmp_path, text, name="book.pronounce.txt"):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return Lexicon.load([f])


@pytest.mark.parametrize("typed", ["зам+ок", "замо'к", "замо’к", "замо´к", "замо" + ACUTE + "к", "замОк"])
def test_every_stress_notation_becomes_one_acute(typed):
    assert normalize_stress(typed) == "замо" + ACUTE + "к"


@pytest.mark.parametrize("typed", ["Mir+andel", "Mira'ndel", "Mira’ndel", "Mira´ndel", "Mira" + ACUTE + "ndel"])
def test_english_stress_notations_become_an_apostrophe_after_the_vowel(typed):
    assert normalize_stress(typed) == "Mira'ndel"


def test_stress_marks_leave_other_text_alone():
    assert normalize_stress("don't a+b Kvothe's") == "don't a+b Kvothe's"
    assert normalize_stress("всё") == "всё"
    assert normalize_stress("Москва") == "Москва"  # a capital at the start is not a stress mark


def test_phonemes():
    assert parse_phonemes("K W OW1 TH") == "[K][W][OW1][TH]"
    assert parse_phonemes("[k][w][ow1][th]") == "[K][W][OW1][TH]"
    for bad in ("Q OW1", "K1", "", "OW9"):
        with pytest.raises(PronounceError):
            parse_phonemes(bad)


def test_respelling_wildcard_and_case(tmp_path):
    lex = lexicon(tmp_path, "Kvothe = Quothe\nTolkien* = Tolkeen\n")
    assert lex.apply("Kvothe met KVOTHE and kvothe's friend.") == "Quothe met QUOTHE and Quothe's friend."
    assert lex.apply("Tolkien's and Tolkiens") == "Tolkeen's and Tolkeens"
    assert lex.apply("Kvothees") == "Kvothees"  # whole words only


def test_replacements_do_not_chain(tmp_path):
    lex = lexicon(tmp_path, "A = B\nB = C\n")
    assert lex.apply("A B") == "B C"


def test_multiword_and_longest_first(tmp_path):
    lex = lexicon(tmp_path, "Mount = Mownt\nMount Doom = Mownt Doom Doom\n")
    assert lex.apply("Mount Doom and Mount Etna") == "Mownt Doom Doom and Mownt Etna"


def test_phonemes_local_online_and_quality_control(tmp_path):
    lex = lexicon(tmp_path, "Kvothe = /K W OW1 TH/ | Quothe\nEbrokh = /EH B R AA1 K/\n")
    text = "Kvothe saw Ebrokh."
    assert lex.apply(text) == "[K][W][OW1][TH] saw [EH][B][R][AA1][K]."
    assert lex.apply(text, local=False) == "Quothe saw Ebrokh."  # no respelling given: left as written
    assert lex.apply(text, quality_control=True) == "Quothe saw Ebrokh."
    assert lex.unusable_here(local=False) == ["Ebrokh"]
    assert lex.unusable_here(local=True) == []


def test_russian_stress_local_and_online(tmp_path):
    lex = lexicon(tmp_path, "замок = зам+ок\n")
    assert lex.apply("Старый замок.") == "Старый замо" + ACUTE + "к."
    assert lex.apply("Старый замок.", local=False) == "Старый замок."
    assert lex.apply("Старый замо" + ACUTE + "к.") == "Старый замо" + ACUTE + "к."  # already marked by ruaccent


def test_comments_errors_and_override(tmp_path):
    series = tmp_path / "pronounce.txt"
    series.write_text("Alpha = one  # trailing comment\n# whole line\nbroken\nB = /Q/\n", encoding="utf-8")
    book = tmp_path / "x.pronounce.txt"
    book.write_text("Alpha = two\n", encoding="utf-8")
    lex = Lexicon.load([series, book])
    assert lex.apply("alpha") == "two"
    assert len(lex.warnings) == 2 and "pronounce.txt:3" in lex.warnings[0]


def test_find_next_to_the_book(tmp_path):
    book = tmp_path / "saga.epub"
    assert find(book) == []
    (tmp_path / "saga.pronounce.txt").write_text("a = b", encoding="utf-8")
    (tmp_path / "pronounce.txt").write_text("a = c", encoding="utf-8")
    assert [p.name for p in find(book)] == ["pronounce.txt", "saga.pronounce.txt"]


def test_plan_chapter_uses_the_lexicon_for_the_model_and_qc(tmp_path):
    lex = lexicon(tmp_path, "Kvothe = /K W OW1 TH/ | Quothe\n")
    chapter = Chapter("c", [Block(BlockKind.PARAGRAPH, "Kvothe walked on.")])
    (chunk,) = plan_chapter(chapter, ChunkOptions(lang="en", lexicon=lex))
    assert chunk.text == "[K][W][OW1][TH] walked on."
    assert chunk.source == "Quothe walked on."
    (online,) = plan_chapter(chapter, ChunkOptions(lang="en", lexicon=lex, local_engine=False))
    assert online.text == "Quothe walked on."


NAMES_BOOK = ("Chapter 1\n\nThe old road ran north, and Kvothe followed it alone. Kvothe did not look back. "
              "At dusk he reached Ebrokh, where Kvothe's friend Denna waited. Denna smiled at him. "
              "He saw Ebrokh again, "
              "and then Denna left. The road was long, and the road waited; Monday came and Monday went. "
              "He met Denna in Ebrokh and the road went on.\n")


def test_names_found_in_a_book(tmp_path):
    from folivox.readers import read_book
    from folivox.text.names import candidates

    f = tmp_path / "saga.txt"
    f.write_text(NAMES_BOOK, encoding="utf-8")
    found = {c.word: c.count for c in candidates(read_book(f), min_count=2)}
    assert found == {"Denna": 3, "Ebrokh": 3, "Kvothe": 2}  # not «The», «Monday», «He» or lower-case words
    assert "Kvothe" not in {c.word for c in candidates(read_book(f), min_count=3)}


def test_names_command_prints_and_writes_without_duplicates(tmp_path):
    from typer.testing import CliRunner

    from folivox.cli import app

    f = tmp_path / "saga.txt"
    f.write_text(NAMES_BOOK, encoding="utf-8")
    runner = CliRunner()
    out = runner.invoke(app, ["names", str(f), "--min", "2"])
    assert out.exit_code == 0 and "Denna = Denna" in out.output and "Kvothe = Kvothe" in out.output
    (tmp_path / "saga.pronounce.txt").write_text("Denna = Dena\n", encoding="utf-8")
    assert runner.invoke(app, ["names", str(f), "--min", "2", "--write"]).exit_code == 0
    text = (tmp_path / "saga.pronounce.txt").read_text(encoding="utf-8")
    assert text.count("Denna") == 1 and "Ebrokh = Ebrokh" in text and "Kvothe = Kvothe" in text
    again = runner.invoke(app, ["names", str(f), "--min", "2", "--write"])
    assert "No new names" in again.output
    lex = Lexicon.load([tmp_path / "saga.pronounce.txt"])  # what it wrote is a valid dictionary
    assert not lex.warnings and len(lex.entries) == 3


def test_sample_follows_the_order_of_the_file_and_names_the_missing_words(tmp_path):
    lex = lexicon(tmp_path, "Kvothe = Quothe\nAbsent* = Abs\nDenna = Dena\nMount Doom = Mownt Doom\n")
    paragraphs = ["Denna smiled. Denna left.", "It rained. Kvothe walked on, and the road was long.", "Nothing here."]
    split = lambda text: [s.strip() + "." for s in text.split(".") if s.strip()]  # noqa: E731
    text, missing = lex.sample(paragraphs, split)
    assert text == "Kvothe walked on, and the road was long. Absent. Denna smiled. Mount Doom."
    assert missing == ["Absent", "Mount Doom"]
    assert lex.sample(paragraphs, split, most=1) == ("Kvothe walked on, and the road was long.", [])


def test_english_stress_in_the_dictionary(tmp_path):
    lex = lexicon(tmp_path, "Mirandel = Mir+andel\nThalassar = Thala'ssar\n")
    text = "She called Mirandel and Thalassar."
    assert lex.apply(text) == "She called Mira'ndel and Thala'ssar."
    assert lex.apply(text, local=False) == "She called Mirandel and Thalassar."  # online engines read marks aloud
    assert lex.apply(text, quality_control=True) == "She called Mirandel and Thalassar."
