from pathlib import Path

import pytest

from folivox.book import BlockKind, Book, Section, bare_number_title
from folivox.readers import UnsupportedFormat, detect_format, read_book
from folivox.readers.headings import heading_level, split_by_headings
from folivox.readers.txt import decode, paragraphs

FIX = Path(__file__).parent / "fixtures"
BOOKS = {
    "fb2": FIX / "book.fb2",
    "epub": FIX / "book.epub",
    "docx": FIX / "book.docx",
    "pdf": FIX / "book.pdf",
    "txt": FIX / "Иван Тестов - Тестовая книга.txt",
}


def all_text(book: Book) -> str:
    return "\n".join(b.text for ch in book.chapters() for b in ch.blocks)


@pytest.mark.parametrize("fmt", BOOKS)
def test_common_shape(fmt):
    book = read_book(BOOKS[fmt])
    assert book.source_format == fmt
    assert book.title == "Тестовая книга"
    assert book.authors == ["Иван Тестов"]
    text = all_text(book)
    assert "Утро выдалось холодным." in text
    assert "— Ты куда? — спросила соседка." in text
    assert "Он купил 3 кг яблок" in text
    assert "сноск" not in text.lower().replace("сноска здесь", "")  # note body skipped
    assert "[1]" not in text
    chapters = book.chapters()
    assert len(chapters) >= 2
    assert any("Утро" in c.title for c in chapters)
    assert book.chars > 200
    assert book.estimated_seconds > 10


@pytest.mark.parametrize("fmt", ["fb2", "epub"])
def test_cover(fmt):
    book = read_book(BOOKS[fmt])
    assert book.cover and book.cover[:2] == b"\xff\xd8"
    assert book.cover_mime == "image/jpeg"


def test_fb2_structure():
    book = read_book(BOOKS["fb2"])
    assert book.year == "2024"
    assert book.annotation == "Короткая аннотация."
    (part,) = book.sections
    assert part.title == "Часть первая"
    assert [b.kind for b in part.blocks] == [BlockKind.EPIGRAPH, BlockKind.AUTHOR]
    assert [c.title for c in part.children] == ["Глава 1. Утро", "2"]
    ch = book.chapters()
    assert ch[0].headings == ["Часть первая", "Глава 1. Утро"]
    assert ch[0].blocks[0].kind == BlockKind.EPIGRAPH  # part epigraph goes with first chapter
    assert ch[1].title == "Часть первая. Глава 2"
    poem = next(b for b in ch[0].blocks if b.kind == BlockKind.POEM)
    assert poem.text == "Мороз и солнце;\nдень чудесный!"
    assert any(b.kind == BlockKind.QUOTE for b in ch[1].blocks)
    assert "Сноска здесь не читается." in all_text(book)


def test_fb2_zip(tmp_path):
    import zipfile

    z = tmp_path / "book.fb2.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(BOOKS["fb2"], "book.fb2")
    assert detect_format(z) == "fb2"
    assert read_book(z).title == "Тестовая книга"


def test_epub_anchors_split_one_file():
    book = read_book(BOOKS["epub"])
    assert [s.title for s in book.sections] == ["Глава 1. Утро", "Глава 2", "Глава 3"]
    assert book.sections[2].blocks[0].text == "Короткая третья глава."
    assert book.sections[0].blocks[0].kind == BlockKind.EPIGRAPH
    assert "Текст сноски" not in all_text(book)


def test_docx_heading_levels():
    book = read_book(BOOKS["docx"])
    (part,) = book.sections
    assert part.title == "Часть первая"
    assert [c.title for c in part.children] == ["Глава 1. Утро", "Глава 2"]


def test_pdf_headers_footers_and_page_break():
    book = read_book(BOOKS["pdf"])
    assert [s.title for s in book.sections] == ["Глава 1. Утро", "Глава 2"]
    text = all_text(book)
    assert "Тестовая книга" not in text  # running header
    assert "\n1\n" not in f"\n{text}\n" and "\n2\n" not in f"\n{text}\n"  # page numbers
    assert "продолжается там, где его никто не ждёт." in text


def test_txt_cp1251_and_headings():
    book = read_book(BOOKS["txt"])
    (part,) = book.sections  # title-page line «Иван Тестов» dropped
    assert part.title == "ЧАСТЬ ПЕРВАЯ"
    assert [c.title for c in part.children] == ["ГЛАВА I. Утро", "Глава 2"]
    # hard-wrapped lines joined back into a paragraph
    assert part.children[1].blocks[0].text == "В 1999 году всё было иначе. Цены выросли на 15%, а зарплата — нет."


@pytest.mark.parametrize("line,level", [
    ("Глава 1", 2), ("ГЛАВА XII", 2), ("Глава первая", 2), ("Глава 3. Встреча", 2), ("Первая глава", 2),
    ("Часть вторая", 1), ("ЧАСТЬ 2", 1), ("Книга первая", 1), ("Пролог", 2), ("Эпилог.", 2),
    ("Глава из жизни моего отца, которая начинается с длинного предложения и никак не может закончиться", 0),
    ("Главное — не сдаваться.", 0), ("— Глава 1, — сказал он.", 0), ("Частью плана было уйти", 0),
])
def test_heading_level(line, level):
    assert heading_level(line) == level


def test_split_by_headings_preface():
    secs = split_by_headings(["Вступительный текст.", "Глава 1", "Текст."])
    assert secs[0].title is None and secs[0].blocks[0].text == "Вступительный текст."
    assert secs[1].title == "Глава 1"


def test_paragraphs_line_per_paragraph():
    assert paragraphs("Первая строка.\nВторая строка.\n") == ["Первая строка.", "Вторая строка."]


def test_paragraphs_dehyphenation():
    assert paragraphs("Это длин-\nное слово.\n\nДругой абзац.") == ["Это длинное слово.", "Другой абзац."]


def test_decode_variants():
    s = "Привет, мир! Это обычный русский текст."
    for enc in ("utf-8", "cp1251", "koi8-r"):
        assert decode(s.encode(enc)) == s
    assert decode(b"\xef\xbb\xbf" + s.encode()) == s


def test_unsupported(tmp_path):
    p = tmp_path / "x.mobi"
    p.write_bytes(b"x")
    with pytest.raises(UnsupportedFormat):
        detect_format(p)


def test_chapters_flatten_depth():
    from folivox.book import Block

    b = Book(sections=[Section("Часть 1", children=[Section("Глава 1", [Block(BlockKind.PARAGRAPH, "a")],
                                                             children=[Section("Сцена", [Block(BlockKind.PARAGRAPH, "b")])])])])
    ch = b.chapters(max_depth=2)
    assert len(ch) == 1
    assert [x.text for x in ch[0].blocks] == ["a", "Сцена", "b"]
    assert bare_number_title("12") == "Глава 12"
    assert bare_number_title("XIV.") == "Глава XIV"
    assert bare_number_title("Эпилог") == "Эпилог"
