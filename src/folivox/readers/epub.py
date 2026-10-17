"""EPUB 2/3 reader: spine order for content, TOC (NCX / nav) for chapter titles."""

from __future__ import annotations

import posixpath
import re
import warnings
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

from folivox.book import Block, BlockKind, Book, Section, one_line


def _soup(markup) -> BeautifulSoup:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        return BeautifulSoup(markup, "lxml")

BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li", "pre", "dd", "dt",
              "section", "article", "aside", "header", "footer", "figure", "figcaption", "table", "tr",
              "td", "th", "ul", "ol", "dl", "body", "center", "poem", "stanza"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
NOTE_TYPES = {"footnote", "footnotes", "endnote", "endnotes", "rearnote", "rearnotes", "note", "notes"}
SKIP_TYPES = NOTE_TYPES | {"toc", "landmarks", "page-list", "cover"}


def _epub_type(el: Tag) -> set[str]:
    v = el.get("epub:type") or el.get("type") or ""
    return set(str(v).lower().split()) | {str(r).lower().replace("doc-", "") for r in
                                          str(el.get("role") or "").split()}


def _strip_noise(soup: BeautifulSoup) -> None:
    for el in soup.find_all(["script", "style", "head", "img", "svg", "nav"]):
        el.decompose()
    for el in soup.find_all(True):
        if getattr(el, "decomposed", False):
            continue
        types = _epub_type(el)
        is_note = types & NOTE_TYPES and el.name != "a"
        is_ref = el.name == "a" and (types & {"noteref", "footnote-ref"} or _looks_like_noteref(el))
        if is_note or is_ref:
            el.decompose()
    for sup in soup.find_all("sup"):
        if sup.find("a") is not None or re.fullmatch(r"\s*[\d*†‡]+\s*", sup.get_text()):
            sup.decompose()


def _looks_like_noteref(a: Tag) -> bool:
    href = a.get("href") or ""
    text = a.get_text(strip=True)
    return "#" in href and bool(re.fullmatch(r"[\[(]?[\d*]{1,4}[\])]?", text))


def _is_leaf_block(el: Tag) -> bool:
    return not any(isinstance(d, Tag) and d.name in BLOCK_TAGS for d in el.descendants)


def _block_text(el: Tag) -> str:
    for br in el.find_all("br"):
        br.replace_with("\n")
    return el.get_text()


def html_blocks(root: Tag) -> list[tuple[Tag, int, str]]:
    """Leaf block elements in document order: (element, heading level or 0, text).

    Text sitting directly inside a non-leaf container (``<div>text<p>..</p></div>``) is emitted
    as its own block so that nothing is dropped.
    """
    out: list[tuple[Tag, int, str]] = []

    def rec(el: Tag):
        if el.name in HEADINGS or (el.name in BLOCK_TAGS and _is_leaf_block(el)) or el.name not in BLOCK_TAGS:
            if el.name not in BLOCK_TAGS:
                return
            raw = _block_text(el)
            text = "\n".join(one_line(x) for x in raw.split("\n")) if el.name in ("pre", "poem", "stanza") \
                else one_line(raw.replace("\n", " "))
            if text.strip():
                out.append((el, HEADINGS.get(el.name, 0), text.strip()))
            return
        loose: list[str] = []
        for c in el.children:
            if isinstance(c, NavigableString):
                if c.strip():
                    loose.append(str(c))
            elif isinstance(c, Tag):
                if c.name in BLOCK_TAGS:
                    if loose and one_line("".join(loose)):
                        out.append((el, 0, one_line("".join(loose))))
                    loose = []
                    rec(c)
                else:
                    loose.append(c.get_text())
        if loose and one_line("".join(loose)):
            out.append((el, 0, one_line("".join(loose))))

    rec(root)
    return out


def _block_kind(el: Tag, level: int) -> BlockKind:
    if level:
        return BlockKind.SUBTITLE
    classes = " ".join(el.get("class") or []).lower()
    parents = [p for p in el.parents if isinstance(p, Tag)]
    pclasses = " ".join(" ".join(p.get("class") or []) for p in parents).lower()
    if "epigraph" in classes or "epigraph" in pclasses or any("epigraph" in _epub_type(p) for p in parents):
        return BlockKind.EPIGRAPH
    if any(p.name == "blockquote" for p in parents) or el.name == "blockquote":
        return BlockKind.QUOTE
    if "poem" in pclasses or "stanza" in classes or "verse" in classes:
        return BlockKind.POEM
    return BlockKind.PARAGRAPH


def _toc_entries(book) -> list[tuple[int, str, str, str]]:
    """Flattened TOC: (depth, title, file href, fragment)."""
    out: list[tuple[int, str, str, str]] = []

    def rec(items, depth):
        for it in items:
            if isinstance(it, tuple):  # (Section, [children])
                sec, kids = it
                if getattr(sec, "href", None):
                    _add(depth, sec.title, sec.href)
                rec(kids, depth + 1)
            elif isinstance(it, list):
                rec(it, depth)
            else:
                _add(depth, it.title, it.href)

    def _add(depth, title, href):
        href = unquote(href or "")
        file, _, frag = href.partition("#")
        out.append((depth, one_line(title or ""), file, frag))

    rec(book.toc, 0)
    return out


def read_epub(path: Path) -> Book:
    import ebooklib
    from ebooklib import epub

    eb = _open_epub(path, epub)

    book = Book()
    titles = eb.get_metadata("DC", "title")
    # Empty elements (<dc:title/>) come back as None.
    book.title = one_line(titles[0][0] or "") if titles else ""
    book.authors = [one_line(a[0]) for a in eb.get_metadata("DC", "creator") if (a[0] or "").strip()]
    lang = eb.get_metadata("DC", "language")
    book.lang = (lang[0][0] or "") if lang else ""
    date = eb.get_metadata("DC", "date")
    book.year = ((date[0][0] if date else "") or "")[:4]
    desc = eb.get_metadata("DC", "description")
    if desc and desc[0][0]:
        book.annotation = one_line(_soup(desc[0][0]).get_text(" "))
    _read_cover(eb, book, ebooklib)

    toc = _toc_entries(eb)
    by_file: dict[str, list[tuple[int, str, str]]] = {}
    for depth, title, file, frag in toc:
        by_file.setdefault(posixpath.normpath(file), []).append((depth, title, frag))

    # Walk spine; open a new section at every TOC anchor (file start or fragment id).
    sections: list[tuple[int, Section]] = []  # (toc depth, section)
    current: Section | None = None
    for idref, _linear in eb.spine:
        item = eb.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        name = posixpath.normpath(item.get_name())
        soup = _soup(item.get_content())
        body = soup.body or soup
        if _epub_type(body) & SKIP_TYPES or any(_epub_type(s) & NOTE_TYPES for s in body.find_all(
                "section", recursive=False)) and len(body.find_all(recursive=False)) == 1:
            continue
        anchors = by_file.get(name) or by_file.get(_tail_match(name, by_file)) or []
        frag_map = {frag: (depth, title) for depth, title, frag in anchors if frag}
        file_anchor = next(((d, t) for d, t, f in anchors if not f), None)
        id_to_anchor = {}
        for el in body.find_all(id=True):
            if el["id"] in frag_map:
                id_to_anchor[id(el)] = frag_map[el["id"]]
        _strip_noise(soup)

        if file_anchor or (not anchors and current is None):
            depth, title = file_anchor or (0, None)
            current = Section(title=title or None)
            sections.append((depth, current))
        pending_title_check = current.title if current else None
        for el, level, text in html_blocks(body):
            anchor = None
            for node in [el, *el.parents]:
                if id(node) in id_to_anchor:
                    anchor = id_to_anchor.pop(id(node))
                    break
            if anchor is None:
                # anchor may sit on an empty element just before this block
                for prev in el.find_all_previous(id=True, limit=3):
                    if id(prev) in id_to_anchor:
                        anchor = id_to_anchor.pop(id(prev))
                        break
            if anchor is not None:
                current = Section(title=anchor[1] or None)
                sections.append((anchor[0], current))
                pending_title_check = current.title
            if current is None:
                current = Section()
                sections.append((0, current))
            if level and pending_title_check and _same(text, pending_title_check):
                pending_title_check = None
                continue  # heading duplicates the TOC title
            if level and current.title is None and not current.blocks:
                current.title = text
                pending_title_check = None
                continue
            pending_title_check = None
            current.blocks.append(Block(_block_kind(el, level), text))

    book.sections = _nest(sections)
    return book


def _open_epub(path: Path, epub):
    """ebooklib fails on a manifest entry whose file is missing from the archive; such files are
    replaced by empty placeholders (in memory) and the book is read again."""
    import io
    import zipfile

    src: str | io.BytesIO = str(path)
    added: set[str] = set()
    while True:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return epub.read_epub(src, options={"ignore_ncx": False})
        except KeyError as e:
            m = re.search(r"There is no item named '(.+)' in the archive", str(e))
            if not m or m.group(1) in added or len(added) >= 200:
                raise
            added.add(m.group(1))
            buf = io.BytesIO()
            with zipfile.ZipFile(path) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    zout.writestr(info, zin.read(info))
                for name in added:
                    zout.writestr(name, b"")
            buf.seek(0)
            src = buf


def _same(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"[\W_]+", "", s.lower())
    return norm(a) == norm(b) or (len(norm(b)) > 3 and norm(a).startswith(norm(b)))


def _tail_match(name: str, by_file: dict) -> str | None:
    base = posixpath.basename(name)
    return next((k for k in by_file if posixpath.basename(k) == base), None)


def _nest(flat: list[tuple[int, Section]]) -> list[Section]:
    roots: list[Section] = []
    stack: list[tuple[int, Section]] = []
    for depth, sec in flat:
        while stack and stack[-1][0] >= depth:
            stack.pop()
        (stack[-1][1].children if stack else roots).append(sec)
        stack.append((depth, sec))
    return roots


def _read_cover(eb, book: Book, ebooklib) -> None:
    item = None
    for meta in eb.get_metadata("OPF", "cover"):
        cid = (meta[1] or {}).get("content")
        if cid:
            item = eb.get_item_with_id(cid)
    if item is None:
        for it in eb.get_items():
            if it.get_type() == ebooklib.ITEM_COVER or (
                    it.get_type() == ebooklib.ITEM_IMAGE and "cover" in it.get_name().lower()):
                item = it
                break
    if item is not None and (getattr(item, "media_type", None) or "").startswith("image/"):
        book.cover = item.get_content()
        book.cover_mime = item.media_type
