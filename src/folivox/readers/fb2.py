"""FictionBook 2 reader (lxml, namespace-agnostic)."""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

from lxml import etree

from folivox.book import Block, BlockKind, Book, Section, clean_text, one_line
from folivox.i18n import _

XLINK = "{http://www.w3.org/1999/xlink}href"
NOTE_BODIES = {"notes", "comments", "footnotes"}


def _local(el) -> str:
    tag = el.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _kids(el, name: str | None = None):
    return [c for c in el if isinstance(c.tag, str) and (name is None or _local(c) == name)]


def _text(el) -> str:
    """Inline text of an element, without footnote references."""
    parts: list[str] = []

    def rec(e):
        if e.text:
            parts.append(e.text)
        for c in e:
            if not isinstance(c.tag, str):  # comment / PI
                pass
            elif _local(c) == "a" and (c.get("type") == "note" or (c.get(XLINK) or "").startswith("#n")):
                pass  # footnote reference like [1]
            else:
                rec(c)
            if c.tail:
                parts.append(c.tail)

    rec(el)
    return "".join(parts)


def _title(el) -> str | None:
    t = _kids(el, "title")
    if not t:
        return None
    lines = [one_line(_text(p)) for p in _kids(t[0]) if _local(p) == "p"]
    lines = [ln for ln in lines if ln]
    return ". ".join(ln.rstrip(".") for ln in lines) or None


def _poem(el) -> list[Block]:
    out: list[Block] = []
    t = _title(el)
    if t:
        out.append(Block(BlockKind.SUBTITLE, t))
    for c in _kids(el):
        name = _local(c)
        if name == "stanza":
            lines = [one_line(_text(v)) for v in _kids(c, "v")]
            text = "\n".join(ln for ln in lines if ln)
            if text:
                out.append(Block(BlockKind.POEM, text))
        elif name == "text-author":
            out.append(Block(BlockKind.AUTHOR, one_line(_text(c))))
    return out


def _blocks(elements, default: BlockKind = BlockKind.PARAGRAPH) -> list[Block]:
    """Block-level elements of a section / cite / epigraph."""
    out: list[Block] = []
    for c in elements:
        name = _local(c)
        if name in ("p", "subtitle", "text-author", "v"):
            text = one_line(_text(c))
            if not text:
                continue
            kind = {"subtitle": BlockKind.SUBTITLE, "text-author": BlockKind.AUTHOR}.get(name, default)
            out.append(Block(kind, text))
        elif name == "poem":
            out += _poem(c)
        elif name == "cite":
            out += _blocks(_kids(c), BlockKind.QUOTE)
        elif name == "epigraph":
            out += _blocks(_kids(c), BlockKind.EPIGRAPH)
        elif name == "table":
            for tr in _kids(c, "tr"):
                cells = [one_line(_text(td)) for td in _kids(tr)]
                row = ", ".join(x for x in cells if x)
                if row:
                    out.append(Block(default, row))
    return out


def _section(el) -> Section:
    sec = Section(title=_title(el))
    for c in _kids(el):
        name = _local(c)
        if name == "section":
            sec.children.append(_section(c))
        elif name in ("title", "image", "annotation", "empty-line"):
            continue
        elif sec.children:
            # Content after nested sections: attach to a trailing anonymous section.
            if sec.children[-1].title is not None or sec.children[-1].children:
                sec.children.append(Section())
            sec.children[-1].blocks += _blocks([c])
        else:
            sec.blocks += _blocks([c])
    return sec


def _parse(path: Path):
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".fb2"))
            data = z.read(name)
    else:
        data = path.read_bytes()
    root = etree.fromstring(data, parser)
    if root is None:
        raise ValueError(_("Cannot parse FB2: {path}", path=path))
    return root


def read_fb2(path: Path) -> Book:
    root = _parse(path)
    book = Book()
    desc = next(iter(_kids(root, "description")), None)
    ti = next(iter(_kids(desc, "title-info")), None) if desc is not None else None
    cover_id = None
    if ti is not None:
        for c in _kids(ti):
            name = _local(c)
            if name == "book-title":
                book.title = one_line(_text(c))
            elif name == "author":
                parts = [one_line(_text(x)) for x in _kids(c) if _local(x) in ("first-name", "middle-name",
                                                                                  "last-name")]
                nick = [one_line(_text(x)) for x in _kids(c, "nickname")]
                name_ = " ".join(p for p in parts if p) or (nick[0] if nick else "")
                if name_:
                    book.authors.append(name_)
            elif name == "lang":
                book.lang = one_line(_text(c)) or book.lang
            elif name == "annotation":
                book.annotation = clean_text("\n".join(one_line(_text(p)) for p in _kids(c)))
            elif name == "date":
                book.year = (c.get("value") or one_line(_text(c)))[:4]
            elif name == "coverpage":
                img = next(iter(_kids(c, "image")), None)
                if img is not None:
                    href = img.get(XLINK) or img.get("href") or ""
                    cover_id = href.lstrip("#")
    if not book.year and desc is not None:
        for pi in _kids(desc, "publish-info"):
            for y in _kids(pi, "year"):
                book.year = one_line(_text(y))[:4]

    for body in _kids(root, "body"):
        if (body.get("name") or "").lower() in NOTE_BODIES:
            continue
        top = _section(body)
        # The body title is the book title; leading body-level blocks become a preface.
        if top.blocks:
            book.sections.append(Section(title=None, blocks=top.blocks))
        book.sections += top.children
        break  # only the main body; extra bodies are notes in practice

    if cover_id:
        for b in _kids(root, "binary"):
            if b.get("id") == cover_id and b.text:
                try:
                    book.cover = base64.b64decode(b.text)
                    book.cover_mime = b.get("content-type") or "image/jpeg"
                except ValueError:
                    pass
                break
    return book
