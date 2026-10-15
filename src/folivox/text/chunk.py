"""Turn chapters into TTS chunks with pauses.

A chunk is what the model synthesizes in one call: one or a few sentences from a single
paragraph. Short sentences are packed together (CosyVoice is unstable on 1–3 word inputs),
long ones are split at clause boundaries. Pauses between chunks depend on structure:
sentence < paragraph < heading / scene break < chapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from folivox import lang as languages
from folivox.book import Block, BlockKind, Chapter
from folivox.lang import has_speech
from folivox.text.pronounce import Lexicon
from folivox.text.stress import strip_marks


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
    max_chars: int = 300
    min_chars: int = 30
    stress: str = "yo"
    lang: str = "ru"
    pauses: Pauses = field(default_factory=Pauses)
    speak_headings: bool = True
    lexicon: Lexicon | None = None  # the book's custom pronunciations
    local_engine: bool = True  # False: an online engine, which cannot take stress marks or phonemes


@dataclass
class Chunk:
    index: int  # within the chapter
    text: str  # model input (normalised, maybe with stress marks)
    source: str  # same text without stress marks, used for QA
    pause_after: float
    kind: str = "p"
    speaker: int = 0  # who reads it (0 = narrator); see folivox.markup
    markup: str = ""  # expression tags written in front of the text, e.g. "[sighs]" (part of the cache key)


@dataclass
class MarkupContext:
    """What ``plan_chapter`` needs to apply a book's markup to one chapter."""
    markup: object  # folivox.markup.Markup
    chapter: int
    tags: bool  # the engine understands expression tags; otherwise they are dropped


_CLAUSE_SPLIT = re.compile(r"(?<=[,;:])\s+|\s+(?=—\s)|(?<=[，；：、])")


def sentences(text: str, lang: str = "ru") -> list[str]:
    """Sentences of the language module, re-joined where a dialogue attribution was split off.

    «Ты куда? — спросила соседка.» stays one sentence.
    """
    language = languages.get(lang)
    out: list[str] = []
    for s in language.sentences(text):
        if not s:
            continue
        if out and (language.is_continuation(s) or not has_speech(s)):
            out[-1] = f"{out[-1]}{_sep(out[-1])}{s}"
        else:
            out.append(s)
    return out


def _sep(prev: str) -> str:
    """No space after CJK full-width punctuation."""
    return "" if prev and prev[-1] in "。！？，；：、」』）" else " "


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


def finalize(text: str, opts: ChunkOptions) -> tuple[str, str]:
    """Model input (stress marks, custom pronunciations) and the plain text that quality control compares with."""
    tts = languages.get(opts.lang).stress(text, opts.stress)
    source = strip_marks(tts)
    if opts.lexicon:
        tts = opts.lexicon.apply(tts, local=opts.local_engine)
        source = opts.lexicon.apply(source, quality_control=True)
    return tts, source


def _plan_segments(raw, segs, ctx, end_pause, opts, normalize, dialogue, p) -> None:
    """One block read by several speakers (or with tags): every segment is packed on its own, so a fragment
    never mixes two voices. Tags go in front of the first fragment of their segment."""
    from folivox.markup import norm_tag

    def tag_text(seg) -> str:
        return "".join(f"[{norm_tag(t)}]" for t in seg.tags) if ctx.tags and ctx.markup.expression_tags else ""

    pieces, carry = [], ""
    for seg in segs:
        if has_speech(seg.text):
            pieces.append((seg, seg.text.strip().strip("—–―").strip(), carry + tag_text(seg)))  # dialogue dashes at the edges
            carry = ""
        else:  # a segment without speech (a stray space): its tags go to the next one
            carry += tag_text(seg)
    for k, (seg, text, tags) in enumerate(pieces):
        parts = pack(sentences(dialogue(normalize(text)), opts.lang), opts.max_chars, opts.min_chars)
        nxt_speaker = pieces[k + 1][0].speaker if k + 1 < len(pieces) else None
        last_pause = end_pause if nxt_speaker is None else (p.dialogue if nxt_speaker != seg.speaker else p.sentence)
        for j, part in enumerate(parts):
            raw.append((dialogue(part), last_pause if j == len(parts) - 1 else p.sentence, "p", seg.speaker,
                        tags if j == 0 else ""))


def plan_chapter(chapter: Chapter, opts: ChunkOptions | None = None, ctx: MarkupContext | None = None) -> list[Chunk]:
    opts = opts or ChunkOptions()
    p = opts.pauses
    language = languages.get(opts.lang)
    normalize, dialogue = language.normalize, language.dialogue
    raw: list[tuple[str, float, str, int, str]] = []  # (text, pause, kind, speaker, tags)

    if opts.speak_headings:
        for h in chapter.headings:
            if has_speech(h):
                raw.append((normalize(_heading_text(h)), p.heading, "heading", 0, ""))

    blocks = chapter.blocks
    for i, b in enumerate(blocks):
        if not has_speech(b.text):  # scene break «* * *»
            if raw:
                text, pause, kind, spk, tg = raw[-1]
                raw[-1] = (text, max(pause, p.scene), kind, spk, tg)
            continue
        if b.kind == BlockKind.SUBTITLE:
            raw.append((normalize(_heading_text(b.text)), p.heading, "heading", 0, ""))
            continue
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        end_pause = p.dialogue if (_is_dialogue(b) and nxt is not None and _is_dialogue(nxt)) else p.paragraph
        if b.kind in (BlockKind.EPIGRAPH, BlockKind.AUTHOR) and not (nxt and nxt.kind in (
                BlockKind.EPIGRAPH, BlockKind.AUTHOR)):
            end_pause = p.heading
        segs = ctx.markup.segments(ctx.chapter, i, b.text) if ctx and b.kind != BlockKind.POEM else None
        if segs and (len(segs) > 1 or segs[0].speaker or segs[0].tags):
            _plan_segments(raw, segs, ctx, end_pause, opts, normalize, dialogue, p)
            continue
        text = dialogue(normalize(_poem_text(b.text) if b.kind == BlockKind.POEM else b.text))
        parts = pack(sentences(text, opts.lang), opts.max_chars, opts.min_chars)
        for j, part in enumerate(parts):
            raw.append((dialogue(part), end_pause if j == len(parts) - 1 else p.sentence, b.kind.value, 0, ""))

    chunks: list[Chunk] = []
    for text, pause, kind, speaker, tags in raw:
        if not has_speech(text):
            continue
        tts, source = finalize(text, opts)
        if tags:
            tts = f"{tags} {tts}"
        chunks.append(Chunk(len(chunks), tts, source, pause, kind, speaker, tags))
    if chunks:
        chunks[-1].pause_after = p.chapter_end
    return chunks
