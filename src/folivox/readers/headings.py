"""Chapter heading detection for formats without structure (TXT, and DOCX/PDF fallbacks)."""

from __future__ import annotations

import re

from folivox.book import Block, BlockKind, Section

_ORDINALS = (
    "первая|вторая|третья|четв[её]ртая|пятая|шестая|седьмая|восьмая|девятая|десятая|одиннадцатая|"
    "двенадцатая|тринадцатая|четырнадцатая|пятнадцатая|шестнадцатая|семнадцатая|восемнадцатая|"
    "девятнадцатая|двадцатая|"
    "первый|второй|третий|четв[её]ртый|пятый|шестой|седьмой|восьмой|девятый|десятый|"
    "последняя|последний|заключительная"
)
_EN_NUMBERS = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
               "sixteen|seventeen|eighteen|nineteen|twenty")
_NUM = rf"(?:\d{{1,3}}|[IVXLCDM]{{1,7}}|{_ORDINALS}|{_EN_NUMBERS})"
_CJK_NUM = r"[0-9０-９一二三四五六七八九十百千零〇两]{1,6}"


def _words(attr: str) -> str:
    from folivox import lang

    words = {w for language in lang.available() for w in getattr(language, attr)}
    return "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))


# Level 1: parts / books. Level 2: chapters. Built from the words of every language module.
_PART = re.compile(rf"^(?:{_words('part_words')})\s+{_NUM}\b\.?|^第{_CJK_NUM}[部卷篇]|^제\s*\d+\s*부",
                   re.IGNORECASE)
_CHAPTER = re.compile(rf"^(?:{_words('chapter_words')})\s+{_NUM}\b\.?|^第{_CJK_NUM}[章回节話话]|^제\s*\d+\s*장",
                      re.IGNORECASE)
_STANDALONE = re.compile(rf"^(?:{_words('standalone_words')})\.?$", re.IGNORECASE)
_ORDINAL_CHAPTER = re.compile(rf"^(?:{_ORDINALS})\s+глава\.?$", re.IGNORECASE)

MAX_HEADING_LEN = 80


def heading_level(line: str) -> int:
    """1 for a part heading, 2 for a chapter heading, 0 for ordinary text."""
    s = line.strip()
    if not s or len(s) > MAX_HEADING_LEN:
        return 0
    if _PART.match(s):
        return 1
    if _CHAPTER.match(s) or _STANDALONE.match(s) or _ORDINAL_CHAPTER.match(s):
        return 2
    return 0


def split_by_headings(paragraphs: list[str], levels: list[int] | None = None,
                      merge_subtitles: bool = True) -> list[Section]:
    """Group paragraphs into sections using :func:`heading_level` (or given ``levels``).

    A heading line may be followed by a short subtitle line (``Глава 1`` / ``Встреча``); it is
    merged into the title when it is short and does not end like a sentence.
    """
    if levels is None:
        levels = [heading_level(p) for p in paragraphs]
    used = sorted({lv for lv in levels if lv})
    if not used:
        return [Section(blocks=[Block(BlockKind.PARAGRAPH, p) for p in paragraphs])] if paragraphs else []
    # normalise levels to 1..n
    rank = {lv: i + 1 for i, lv in enumerate(used)}
    roots: list[Section] = []
    stack: list[tuple[int, Section]] = []
    preface = Section()
    i = 0
    while i < len(paragraphs):
        p, lv = paragraphs[i], levels[i]
        if lv:
            depth = rank[lv]
            title = p.strip().rstrip(".")
            nxt = paragraphs[i + 1].strip() if i + 1 < len(paragraphs) else ""
            if merge_subtitles and nxt and not levels[i + 1] and _is_subtitle(nxt):
                title = f"{title}. {nxt.rstrip('.')}"
                i += 1
            sec = Section(title=title)
            while stack and stack[-1][0] >= depth:
                stack.pop()
            (stack[-1][1].children if stack else roots).append(sec)
            stack.append((depth, sec))
        else:
            target = stack[-1][1] if stack else preface
            target.blocks.append(Block(BlockKind.PARAGRAPH, p))
        i += 1
    return ([preface] if preface.blocks else []) + roots


def _is_subtitle(s: str) -> bool:
    return len(s) <= 60 and not re.search(r"[.!?…:;,]$", s) and len(s.split()) <= 8 and \
        not s.startswith(("—", "–", "-"))
