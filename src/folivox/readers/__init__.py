"""Book readers. Each reader turns one file format into a :class:`folivox.book.Book`."""

from __future__ import annotations

import zipfile
from pathlib import Path

from folivox.book import Book

SUPPORTED = (".fb2", ".fb2.zip", ".epub", ".txt", ".docx", ".pdf")


class UnsupportedFormat(ValueError):
    pass


def detect_format(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".fb2.zip"):
        return "fb2"
    ext = path.suffix.lower().lstrip(".")
    if ext in {"fb2", "epub", "txt", "docx", "pdf"}:
        return ext
    if ext == "zip" and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            if any(n.lower().endswith(".fb2") for n in z.namelist()):
                return "fb2"
    raise UnsupportedFormat(f"Неподдерживаемый формат: {path.name} (поддерживаются {', '.join(SUPPORTED)})")


def read_book(path: str | Path) -> Book:
    path = Path(path)
    fmt = detect_format(path)
    if fmt == "fb2":
        from folivox.readers.fb2 import read_fb2 as reader
    elif fmt == "epub":
        from folivox.readers.epub import read_epub as reader
    elif fmt == "txt":
        from folivox.readers.txt import read_txt as reader
    elif fmt == "docx":
        from folivox.readers.docx import read_docx as reader
    else:
        from folivox.readers.pdf import read_pdf as reader
    book = reader(path)
    book.source_format = fmt
    if not book.title:
        book.title = path.name.split(".")[0]
    book.sections = [s for s in book.sections if not s.is_empty() or s.title]
    _drop_title_page(book)
    from folivox.lang import normalize_code

    book.lang = normalize_code(book.lang)
    if not book.lang:
        from folivox.lang.detect import detect

        book.lang = detect(" ".join(b.text for ch in book.chapters(1)[:5] for b in ch.blocks[:200]))
    return book


def _drop_title_page(book: Book) -> None:
    """Remove leading untitled paragraphs that only repeat the title / author."""
    if not book.sections or book.sections[0].title or book.sections[0].children:
        return
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    known = {norm(book.title), *(norm(a) for a in book.authors)}
    known.add(norm(book.author + book.title))
    first = book.sections[0]
    while first.blocks and norm(first.blocks[0].text) in known:
        first.blocks.pop(0)
    if not first.blocks:
        book.sections.pop(0)
