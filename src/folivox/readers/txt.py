"""Plain-text reader: encoding detection, paragraph reconstruction, chapter headings."""

from __future__ import annotations

import re
from pathlib import Path

from folivox.book import Book, one_line
from folivox.readers.headings import heading_level, split_by_headings


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        if enc == "utf-16" and data[:2] not in (b"\xff\xfe", b"\xfe\xff"):
            continue
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # cp1251 vs koi8-r: pick the one producing more common lowercase Cyrillic letters
    best, score = data.decode("cp1251", errors="replace"), -1
    for enc in ("cp1251", "koi8-r", "cp866"):
        text = data.decode(enc, errors="replace")
        sc = sum(text.count(ch) for ch in "оеаинт")
        if sc > score:
            best, score = text, sc
    return best


def paragraphs(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    lines = text.split("\n")
    nonempty = [ln for ln in lines if ln.strip()]
    if not nonempty:
        return []
    blank_separated = sum(1 for ln in lines if not ln.strip()) >= len(nonempty) * 0.3
    indented = sum(1 for ln in nonempty if re.match(r"^(\s{2,}|\t)", ln)) >= len(nonempty) * 0.3
    out: list[str] = []
    if blank_separated:
        buf: list[str] = []
        for ln in lines + [""]:
            if ln.strip():
                if buf and heading_level(ln):  # heading glued to text without a blank line
                    out.append(" ".join(buf))
                    buf = []
                buf.append(ln.strip())
                if heading_level(ln):
                    out.append(" ".join(buf))
                    buf = []
            elif buf:
                out.append(" ".join(buf))
                buf = []
    elif indented and len(nonempty) > 5:
        buf = []
        for ln in lines:
            if not ln.strip():
                continue
            if re.match(r"^(\s{2,}|\t)", ln) or heading_level(ln) or (buf and heading_level(buf[0])):
                if buf:
                    out.append(" ".join(buf))
                buf = [ln.strip()]
            else:
                buf.append(ln.strip())
        if buf:
            out.append(" ".join(buf))
    else:
        out = [ln.strip() for ln in nonempty]
    return [_dehyphen(one_line(p)) for p in out if one_line(p)]


def _dehyphen(s: str) -> str:
    # "сло- во" left over from hard-wrapped lines
    return re.sub(r"(\w)- (\w)", lambda m: m.group(1) + m.group(2) if m.group(2).islower() else m.group(0), s)


def _meta_from_name(path: Path) -> tuple[str, list[str]]:
    stem = path.name.rsplit(".", 1)[0]
    if " - " in stem:
        author, title = stem.split(" - ", 1)
        return title.strip(), [author.strip()]
    return stem, []


def read_txt(path: Path) -> Book:
    text = decode(path.read_bytes())
    book = Book()
    book.title, book.authors = _meta_from_name(path)
    book.sections = split_by_headings(paragraphs(text))
    return book
