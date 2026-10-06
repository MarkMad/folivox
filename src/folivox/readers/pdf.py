"""PDF reader (text layer only, no OCR) built on PyMuPDF.

* running headers/footers and page numbers are removed: short lines in the top/bottom margin
  that repeat on many pages (digits ignored), or consist of a page number only;
* paragraphs are rebuilt from PyMuPDF blocks, merged across page breaks, hyphenation undone;
* chapters come from the outline (bookmarks); without one, from lines set noticeably larger
  than body text; as a last resort from «Глава N»-style lines.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from folivox.book import Block, BlockKind, Book, Section, one_line
from folivox.readers.headings import split_by_headings

MARGIN = 0.08  # share of page height treated as header / footer zone
_PAGE_NUM = re.compile(r"^[\s\-–—]*(?:стр\.?|page|с\.)?\s*\d{1,4}(?:\s*(?:/|из|of)\s*\d{1,4})?[\s\-–—]*$",
                       re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?…»\"”)\]:]$")


@dataclass
class _Para:
    page: int
    text: str
    size: float
    top: float  # y of the first line, for ordering against outline targets


def _norm_running(s: str) -> str:
    return re.sub(r"\d+", "#", s.strip().lower())


def _lines(page) -> list[tuple[float, float, float, str, int]]:
    """(y0, y1, font size, text, block number) for every text line."""
    out = []
    d = page.get_text("dict", flags=0)
    for bi, b in enumerate(d.get("blocks", [])):
        for ln in b.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in ln["spans"])
            size = max(s["size"] for s in spans)
            out.append((ln["bbox"][1], ln["bbox"][3], size, text, bi))
    return out


def _join_lines(lines: list[str]) -> str:
    text = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if text.endswith("-") and ln[:1].islower() and len(text) > 1 and text[-2].isalpha():
            text = text[:-1] + ln  # hyphenated word
        elif text:
            text += " " + ln
        else:
            text = ln
    return one_line(text)


def read_pdf(path: Path) -> Book:
    import pymupdf

    doc = pymupdf.open(str(path))
    book = Book()
    meta = doc.metadata or {}
    book.title = one_line(meta.get("title") or "")
    if meta.get("author"):
        book.authors = [a.strip() for a in re.split(r"[;,]", meta["author"]) if a.strip()]
    if (meta.get("creationDate") or "").startswith("D:"):
        book.year = meta["creationDate"][2:6]

    pages = [_lines(p) for p in doc]
    heights = [p.rect.height for p in doc]

    # running headers / footers
    counts: Counter[str] = Counter()
    for pi, lines in enumerate(pages):
        h = heights[pi]
        seen = {_norm_running(t) for y0, y1, _, t, _ in lines if y1 < h * MARGIN or y0 > h * (1 - MARGIN)}
        counts.update(seen)
    repeat_min = max(3, int(len(pages) * 0.3))
    running = {k for k, v in counts.items() if v >= repeat_min}

    paras: list[_Para] = []
    sizes: Counter[float] = Counter()
    for pi, lines in enumerate(pages):
        h = heights[pi]
        kept = []
        for y0, y1, size, text, bi in lines:
            in_margin = y1 < h * MARGIN or y0 > h * (1 - MARGIN)
            if in_margin and (_norm_running(text) in running or _PAGE_NUM.match(text)):
                continue
            if _PAGE_NUM.match(text) and len(text.strip()) <= 4:
                continue
            kept.append((y0, size, text, bi))
            sizes[round(size, 1)] += len(text)
        # group by PyMuPDF block, but also split a block at indented / large gaps is overkill;
        # blocks are a good paragraph approximation for book PDFs.
        groups: dict[int, list] = {}
        for item in kept:
            groups.setdefault(item[3], []).append(item)
        for bi in sorted(groups, key=lambda b: groups[b][0][0]):
            g = groups[bi]
            text = _join_lines([t for _, _, t, _ in g])
            if text:
                paras.append(_Para(pi, text, max(s for _, s, _, _ in g), g[0][0]))

    # merge paragraphs split by a page break
    merged: list[_Para] = []
    for p in paras:
        if merged and merged[-1].page == p.page - 1 and not _SENTENCE_END.search(merged[-1].text) \
                and p.text[:1].islower() and abs(merged[-1].size - p.size) < 0.6:
            prev = merged[-1]
            joiner = "" if prev.text.endswith("-") and prev.text[-2:-1].isalpha() else " "
            prev.text = (prev.text[:-1] if joiner == "" else prev.text) + joiner + p.text
        else:
            merged.append(p)

    body_size = sizes.most_common(1)[0][0] if sizes else 10.0
    toc = [(lvl, one_line(title), page - 1) for lvl, title, page, *_ in doc.get_toc(simple=True) if page >= 1]
    if toc:
        book.sections = _by_outline(merged, toc)
    else:
        levels = _levels_by_size(merged, body_size)
        if any(levels):
            book.sections = split_by_headings([p.text for p in merged], levels, merge_subtitles=False)
        else:
            book.sections = split_by_headings([p.text for p in merged])
    _cover(doc, book)
    return book


def _levels_by_size(paras: list[_Para], body: float) -> list[int]:
    big = sorted({round(p.size) for p in paras if p.size >= body * 1.25 and len(p.text) <= 100}, reverse=True)
    big = big[:3]
    out = []
    for p in paras:
        r = round(p.size)
        out.append(big.index(r) + 1 if r in big and len(p.text) <= 100 and p.size >= body * 1.25 else 0)
    # a single huge line on page 1 is usually the book title, not a chapter
    if out and out[0] and sum(1 for x in out if x == out[0]) == 1:
        out[0] = 0
    return out


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


def _by_outline(paras: list[_Para], toc: list[tuple[int, str, int]]) -> list[Section]:
    # Where does each outline entry start? First paragraph on its page whose text matches the
    # title, else the first paragraph on (or after) that page.
    starts: list[int] = []
    pos = 0
    for _, title, page in toc:
        idx = None
        for i in range(pos, len(paras)):
            if paras[i].page > page + 1:
                break
            if paras[i].page >= page and _norm(paras[i].text).startswith(_norm(title)[:40] or "\0"):
                idx = i
                break
        if idx is None:
            idx = next((i for i in range(pos, len(paras)) if paras[i].page >= page), len(paras))
        starts.append(idx)
        pos = idx

    roots: list[Section] = []
    stack: list[tuple[int, Section]] = []
    pre = paras[: starts[0]] if starts else paras
    if pre:
        roots.append(Section(blocks=[Block(BlockKind.PARAGRAPH, p.text) for p in pre]))
    for k, (lvl, title, _) in enumerate(toc):
        a = starts[k]
        b = starts[k + 1] if k + 1 < len(toc) else len(paras)
        chunk = [p.text for p in paras[a:b]]
        if chunk and _norm(chunk[0]) == _norm(title):
            chunk = chunk[1:]  # the heading line itself
        sec = Section(title=title, blocks=[Block(BlockKind.PARAGRAPH, t) for t in chunk])
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        (stack[-1][1].children if stack else roots).append(sec)
        stack.append((lvl, sec))
    return roots


def _cover(doc, book: Book) -> None:
    if not len(doc):
        return
    page = doc[0]
    text = page.get_text().strip()
    imgs = page.get_images(full=True)
    if imgs and len(text) < 200:
        try:
            pix = page.get_pixmap(dpi=110)
            book.cover = pix.tobytes("jpeg")
            book.cover_mime = "image/jpeg"
        except Exception:  # noqa: BLE001 - cover is optional
            pass

