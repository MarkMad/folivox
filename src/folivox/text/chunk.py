"""Turn chapters into TTS chunks with pauses.

A chunk is what the model synthesizes in one call: one or a few sentences from a single
paragraph. Short sentences are packed together (CosyVoice is unstable on 1–3 word inputs),
long ones are split at clause boundaries. Pauses between chunks depend on structure:
sentence < paragraph < heading / scene break < chapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from razdel import sentenize

from folivox.book import Block, BlockKind, Chapter
from folivox.text import stress
from folivox.text.normalize import dialogue, has_speech, normalize


@dataclass
class Pauses:
    """Seconds of silence after a chunk."""

    sentence: float = 0.25  # between chunks of one paragraph
    paragraph: float = 0.65
    dialogue: float = 0.45  # between consecutive dialogue lines
    heading: float = 1.2
    scene: float = 1.8  # «* * *»
    chapter_end: float = 2.5


@dataclass
class ChunkOptions:
    max_chars: int = 220
    min_chars: int = 30
    stress: str = "yo"
    pauses: Pauses = field(default_factory=Pauses)
    speak_headings: bool = True


@dataclass
class Chunk:
    index: int  # within the chapter
    text: str  # model input (normalised, maybe with stress marks)
    source: str  # same text without stress marks, used for QA
    pause_after: float
    kind: str = "p"


_LOWER_START = re.compile(r"^[\s—–-]*[а-яё]")
_CLAUSE_SPLIT = re.compile(r"(?<=[,;:])\s+|\s+(?=—\s)")


def sentences(text: str) -> list[str]:
    """razdel sentences, re-joined where a dialogue attribution was split off.

    «Ты куда? — спросила соседка.» stays one sentence.
    """
    out: list[str] = []
    for s in (x.text.strip() for x in sentenize(text)):
        if not s:
            continue
        if out and (_LOWER_START.match(s) or not has_speech(s)):
            out[-1] = f"{out[-1]} {s}"
        else:
            out.append(s)
    return out


def split_long(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    parts = [p for p in _CLAUSE_SPLIT.split(sentence) if p]
    if len(parts) == 1:
        words = sentence.split()
        mid = len(words) // 2
        parts = [" ".join(words[:mid]), " ".join(words[mid:])]
        if len(words) < 2:
            return [sentence]
    # greedy re-pack of clauses up to max_chars
    out: list[str] = []
    for p in parts:
        if out and len(out[-1]) + 1 + len(p) <= max_chars:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    res: list[str] = []
    for p in out:
        res += split_long(p, max_chars) if len(p) > max_chars and p != sentence else [p]
    return res


def pack(sents: list[str], max_chars: int, min_chars: int) -> list[str]:
    pieces: list[str] = []
    for s in sents:
        pieces += split_long(s, max_chars)
    out: list[str] = []
    for p in pieces:
        if out and len(out[-1]) + 1 + len(p) <= max_chars:
            out[-1] = f"{out[-1]} {p}"
        else:
            out.append(p)
    return out


def _is_dialogue(block: Block) -> bool:
    return block.kind == BlockKind.PARAGRAPH and block.text.lstrip().startswith(("—", "–", "- "))


def _heading_text(h: str) -> str:
    h = h.strip()
    return h if re.search(r"[.!?…]$", h) else h + "."


def _poem_text(stanza: str) -> str:
    lines = [ln.strip() for ln in stanza.split("\n") if ln.strip()]
    return " ".join(ln if re.search(r"[,.;:!?…—-]$", ln) else ln + "," for ln in lines).rstrip(",") + (
        "" if re.search(r"[.!?…]$", lines[-1]) else ".") if lines else ""


def plan_chapter(chapter: Chapter, opts: ChunkOptions | None = None) -> list[Chunk]:
    opts = opts or ChunkOptions()
    p = opts.pauses
    raw: list[tuple[str, float, str]] = []  # (text, pause, kind)

    if opts.speak_headings:
        for h in chapter.headings:
            if has_speech(h):
                raw.append((normalize(_heading_text(h)), p.heading, "heading"))

    blocks = chapter.blocks
    for i, b in enumerate(blocks):
        if not has_speech(b.text):  # scene break «* * *»
            if raw:
                text, pause, kind = raw[-1]
                raw[-1] = (text, max(pause, p.scene), kind)
            continue
        if b.kind == BlockKind.SUBTITLE:
            raw.append((normalize(_heading_text(b.text)), p.heading, "heading"))
            continue
        text = dialogue(normalize(_poem_text(b.text) if b.kind == BlockKind.POEM else b.text))
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        end_pause = p.dialogue if (_is_dialogue(b) and nxt is not None and _is_dialogue(nxt)) else p.paragraph
        if b.kind in (BlockKind.EPIGRAPH, BlockKind.AUTHOR) and not (nxt and nxt.kind in (
                BlockKind.EPIGRAPH, BlockKind.AUTHOR)):
            end_pause = p.heading
        parts = pack(sentences(text), opts.max_chars, opts.min_chars)
        for j, part in enumerate(parts):
            raw.append((dialogue(part), end_pause if j == len(parts) - 1 else p.sentence, b.kind.value))

    chunks: list[Chunk] = []
    for text, pause, kind in raw:
        if not has_speech(text):
            continue
        tts = stress.apply(text, opts.stress)
        chunks.append(Chunk(len(chunks), tts, stress.strip_marks(tts), pause, kind))
    if chunks:
        chunks[-1].pause_after = p.chapter_end
    return chunks
