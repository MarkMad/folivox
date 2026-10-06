"""Format-independent book model produced by every reader."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum

# Average Russian narration speed with pauses, characters (incl. spaces) per second.
# Measured on CosyVoice 3 zero-shot output; used only for estimates.
CHARS_PER_SECOND = 14.0


class BlockKind(str, Enum):
    PARAGRAPH = "p"
    SUBTITLE = "subtitle"  # heading inside a chapter that does not start a new one
    EPIGRAPH = "epigraph"
    POEM = "poem"  # one stanza; lines separated by "\n"
    QUOTE = "quote"
    AUTHOR = "author"  # attribution under an epigraph or quote


@dataclass
class Block:
    kind: BlockKind
    text: str


@dataclass
class Section:
    title: str | None = None
    blocks: list[Block] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)

    @property
    def chars(self) -> int:
        own = sum(len(b.text) for b in self.blocks) + len(self.title or "")
        return own + sum(c.chars for c in self.children)

    def is_empty(self) -> bool:
        return not self.blocks and all(c.is_empty() for c in self.children)

    def walk(self) -> Iterator[Section]:
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class Chapter:
    """A flat unit of audio output: one chapter marker in the m4b."""

    title: str
    blocks: list[Block]
    # Headings spoken at the start (e.g. ["Часть первая", "Глава 1"]).
    headings: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(b.text) for b in self.blocks) + sum(len(h) for h in self.headings)


@dataclass
class Book:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    lang: str = ""  # ISO 639-1; detected from the text when the file has no metadata
    annotation: str = ""
    year: str = ""
    cover: bytes | None = None
    cover_mime: str | None = None
    sections: list[Section] = field(default_factory=list)
    source_format: str = ""

    @property
    def author(self) -> str:
        return ", ".join(self.authors)

    @property
    def chars(self) -> int:
        return sum(s.chars for s in self.sections)

    @property
    def estimated_seconds(self) -> float:
        return self.chars / CHARS_PER_SECOND

    def chapters(self, max_depth: int = 2) -> list[Chapter]:
        """Flatten the section tree into audio chapters.

        A section becomes a chapter when it has no sub-sections or when ``max_depth`` is
        reached. A parent's title and own blocks (e.g. a part title with an epigraph) are
        prepended to its first child chapter so nothing is lost and nothing is duplicated.
        """
        out: list[Chapter] = []

        def visit(sec: Section, depth: int, pending_headings: list[str], pending_blocks: list[Block],
                  title_prefix: list[str]):
            heads = pending_headings + ([bare_number_title(sec.title)] if sec.title else [])
            if not sec.children or depth >= max_depth:
                blocks = pending_blocks + sec.blocks
                for c in sec.children:
                    blocks += _flatten_blocks(c)
                if not blocks and not heads:
                    return
                names = title_prefix + ([bare_number_title(sec.title)] if sec.title else [])
                title = ". ".join(names) if names else ("Вступление" if not out else f"Глава {len(out) + 1}")
                out.append(Chapter(title=title, blocks=blocks, headings=heads))
                return
            first = True
            kids = [c for c in sec.children if not c.is_empty()]
            if not kids:  # only a title + own blocks
                visit(Section(sec.title, sec.blocks), max_depth, pending_headings, pending_blocks, title_prefix)
                return
            for c in kids:
                prefix = title_prefix + ([sec.title] if sec.title else [])
                visit(c, depth + 1, heads if first else [], (pending_blocks + sec.blocks) if first else [],
                      prefix)
                first = False

        for s in self.sections:
            if not s.is_empty() or s.title:
                visit(s, 1, [], [], [])
        return out


_BARE_NUMBER = re.compile(r"^\s*(\d{1,3}|[IVXLCDM]{1,7})\s*\.?\s*$")


def bare_number_title(title: str) -> str:
    """"7" or "VII" → "Глава 7" / "Глава VII"; other titles unchanged."""
    return f"Глава {title.strip().rstrip('.')}" if _BARE_NUMBER.match(title) else title


def _flatten_blocks(sec: Section) -> list[Block]:
    blocks: list[Block] = []
    if sec.title:
        blocks.append(Block(BlockKind.SUBTITLE, sec.title))
    blocks += sec.blocks
    for c in sec.children:
        blocks += _flatten_blocks(c)
    return blocks


_WS = re.compile(r"[ \t\r\f\v\u00a0\u2000-\u200a\u202f\u205f\u3000]+")
_INVISIBLE = re.compile(r"[\u00ad\u200b-\u200d\u2060\ufeff]")


def clean_text(s: str) -> str:
    """Collapse whitespace, drop soft hyphens / zero-width chars. Keeps "\\n" (poem lines)."""
    s = _INVISIBLE.sub("", s)
    lines = [_WS.sub(" ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def one_line(s: str) -> str:
    return clean_text(s).replace("\n", " ")
