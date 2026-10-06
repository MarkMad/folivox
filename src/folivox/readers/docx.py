"""DOCX reader: chapters from heading styles (Heading N / Заголовок N / Title), regex fallback."""

from __future__ import annotations

import re
from pathlib import Path

from folivox.book import Book, one_line
from folivox.readers.headings import split_by_headings

_HEADING_STYLE = re.compile(r"^(?:heading|заголовок|überschrift|titre)\s*(\d)$", re.IGNORECASE)


def _style_level(paragraph) -> int:
    style = paragraph.style
    while style is not None:
        name = (style.name or "").strip()
        m = _HEADING_STYLE.match(name)
        if m:
            return int(m.group(1))
        if name.lower() in ("title", "название", "заголовок"):
            return 0  # document title, handled separately
        style = style.base_style
    # explicit outline level in paragraph properties
    ppr = paragraph._p.pPr
    if ppr is not None:
        lvl = ppr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}outlineLvl")
        if lvl is not None:
            val = lvl.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
            if val is not None and val.isdigit() and int(val) < 9:
                return int(val) + 1
    return 0


def _is_title_style(paragraph) -> bool:
    return (paragraph.style.name or "").strip().lower() in ("title", "название")


def read_docx(path: Path) -> Book:
    import docx

    doc = docx.Document(str(path))
    book = Book()
    cp = doc.core_properties
    book.title = one_line(cp.title or "")
    if cp.author:
        book.authors = [a.strip() for a in re.split(r"[;,]", cp.author) if a.strip()]
    if cp.language:
        book.lang = cp.language[:2].lower()

    texts: list[str] = []
    levels: list[int] = []
    for p in doc.paragraphs:
        text = one_line(p.text)
        if not text:
            continue
        if _is_title_style(p):
            if not book.title:
                book.title = text
            continue
        lv = _style_level(p)
        texts.append(text)
        levels.append(lv)

    if any(levels):
        book.sections = split_by_headings(texts, levels, merge_subtitles=False)
    else:
        book.sections = split_by_headings(texts)
    _read_cover(doc, book)
    return book


def _read_cover(doc, book: Book) -> None:
    """Use the first embedded image as the cover when it appears before any text."""
    body = doc.element.body
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    for p in list(body)[:3]:
        blip = next(iter(p.iter(ns)), None)
        if blip is not None:
            part = doc.part.related_parts.get(blip.get(rel_ns))
            if part is not None:
                book.cover = part.blob
                book.cover_mime = part.content_type
            return
