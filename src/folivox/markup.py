"""Book markup: who speaks each part of the text, and optional expression tags.

The markup is an *annotation layer*: it never contains or changes book text. It is anchored to the book by
(chapter index, block index, character offsets inside the block text) and carries a signature of each chapter's
text, so a markup made for another edition is detected and ignored (the narrator reads) instead of misapplied.

JSON (``BOOK.markup.json`` next to the book)::

    {"version": 1, "depth": 2, "expression_tags": true,
     "speakers": [{"id": 0, "name": "Narrator", "voice": ""}, {"id": 1, "name": "Anna", "voice": "my-voice"}],
     "chapters": {"0": {"title": "…", "sig": "…",
                        "spans": [{"b": 3, "s": 0, "e": 18, "sp": 1, "tags": ["whispering"]},
                                  {"b": 4, "s": 10, "e": 31, "sp": 0, "lang": "en"}],
                        "marks": [{"b": 3, "at": 40, "tag": "sighs"}]}}}

Speaker 0 is the narrator and reads everything not covered by a span. A span may carry delivery tags (put in
front of its text) and a language (ISO 639-1, only when it is not the book's language: ``"lang"`` is absent
otherwise, so files made before languages existed read the same); a mark is an inline tag at an offset.
Speaker ids are 0..15 (the range of Fish speaker tags).

Text form (for hand editing, ``folivox markup export --format text``): one line per block, the block text with
Fish-style ``<|speaker:N|>``, ``<|lang:xx|>`` (``<|lang:-|>`` goes back to the book's language) and ``[tag]``
inserted. Reading it back checks that removing the tags gives exactly
the book's text, so editing cannot alter the book.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

MAX_SPEAKERS = 16
VERSION = 1
SPEAKER_TAG = re.compile(r"<\|speaker:(\d{1,2})\|>")
LANG_TAG = re.compile(r"<\|lang:([A-Za-z]{2,3}|-)\|>")
TAG = re.compile(r"\[([^\[\]\n<>|]{1,40})\]")
TAGS_FILE = Path(__file__).with_name("tts") / "expression_tags.json"


class MarkupError(ValueError):
    pass


@dataclass
class Speaker:
    id: int
    name: str
    voice: str = ""  # voice id from the voice catalog or a path to a recording; "" = the book's main voice
    gender: str = ""
    aliases: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class Span:
    block: int
    start: int
    end: int
    speaker: int
    tags: tuple[str, ...] = ()
    lang: str = ""  # ISO 639-1; "" = the book's language


@dataclass(frozen=True)
class Mark:
    block: int
    at: int
    tag: str


@dataclass
class ChapterMarkup:
    title: str = ""
    sig: str = ""
    spans: list[Span] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    done: bool = False  # the automatic marking went through this chapter (even if it found no speech)
    review: list[dict] = field(default_factory=list)  # places to check: {"b": block, "code": why, ...details}


@dataclass(frozen=True)
class Segment:
    """A piece of one block read by one speaker; ``tags`` go in front of it."""
    text: str
    speaker: int
    tags: tuple[str, ...] = ()
    lang: str = ""  # "" = the book's language


def block_sig(texts: list[str]) -> str:
    h = hashlib.sha1()
    for t in texts:
        h.update(t.encode())
        h.update(b"\x00")
    return h.hexdigest()[:16]


def valid_lang(code: object) -> str:
    """A language code of a span: normalised, or ``""`` when it is not on the allow-list."""
    from folivox.lang.codes import valid

    return valid(code)


def norm_tag(tag: str) -> str:
    return " ".join(tag.strip().strip("[]").lower().split())


@lru_cache(maxsize=1)
def tag_database() -> dict:
    return json.loads(TAGS_FILE.read_text(encoding="utf-8"))


def known_tags(model: str | None = None) -> set[str]:
    return {t["tag"] for t in tag_database()["tags"] if model is None or model in t["models"]}


@dataclass
class Markup:
    speakers: list[Speaker] = field(default_factory=lambda: [Speaker(0, "Narrator")])
    chapters: dict[int, ChapterMarkup] = field(default_factory=dict)
    expression_tags: bool = True  # use tags at all (an engine without tag support strips them anyway)
    depth: int = 2

    # -- queries
    def speaker(self, sid: int) -> Speaker | None:
        return next((s for s in self.speakers if s.id == sid), None)

    def used_speakers(self) -> set[int]:
        return {0} | {sp.speaker for c in self.chapters.values() for sp in c.spans}

    def is_empty(self) -> bool:
        return not any(c.spans or c.marks or c.done for c in self.chapters.values())

    def segments(self, chapter: int, block: int, text: str, book_lang: str = "") -> list[Segment]:
        """The block split by speaker, language and inline tags. Concatenating the segment texts gives ``text``
        exactly. With ``book_lang``, stretches in another script (Latin words in Russian text, …) are found
        and get their language unless a span already names one."""
        cm = self.chapters.get(chapter)
        spans = sorted((s for s in cm.spans if s.block == block and 0 <= s.start < s.end <= len(text)),
                       key=lambda s: s.start) if cm else []
        marks = sorted((m for m in cm.marks if m.block == block and 0 < m.at < len(text)),
                       key=lambda m: m.at) if cm else []
        runs = []
        if book_lang:
            from folivox.lang.runs import script_runs

            runs = script_runs(text, book_lang)
        if not spans and not marks and not runs:
            return [Segment(text, 0)]
        cuts = sorted({0, len(text), *(s.start for s in spans), *(s.end for s in spans), *(m.at for m in marks),
                       *(r.start for r in runs), *(r.end for r in runs)})
        out: list[Segment] = []
        for a, b in zip(cuts, cuts[1:], strict=False):
            span = next((s for s in spans if s.start <= a and b <= s.end), None)
            tags: list[str] = []
            if span and span.start == a:
                tags += span.tags
            tags += [m.tag for m in marks if m.at == a]
            lang = span.lang if span and span.lang else next((r.lang for r in runs if r.start <= a and b <= r.end), "")
            out.append(Segment(text[a:b], span.speaker if span else 0, tuple(tags), lang))
        return out

    def languages_only(self) -> Markup:
        """A copy that keeps only the languages of the spans: one voice reads everything, but each fragment still
        gets its language (a book read by one voice has no use for the speakers, yet the English parts need
        to be read in English)."""
        out = Markup(expression_tags=False, depth=self.depth)
        for idx, c in self.chapters.items():
            spans = [Span(s.block, s.start, s.end, 0, (), s.lang) for s in c.spans if s.lang]
            if spans:
                out.chapters[idx] = ChapterMarkup(c.title, c.sig, spans)
        return out

    # -- editing helpers (used by the CLI, the LLM pass and the editor)
    def ensure_speaker(self, sid: int, name: str = "") -> Speaker:
        if not 0 <= sid < MAX_SPEAKERS:
            raise MarkupError(f"Speaker ids go from 0 to {MAX_SPEAKERS - 1}")
        sp = self.speaker(sid)
        if sp is None:
            sp = Speaker(sid, name or f"Speaker {sid}")
            self.speakers.append(sp)
            self.speakers.sort(key=lambda s: s.id)
        return sp

    def chapter(self, idx: int, title: str = "", sig: str = "") -> ChapterMarkup:
        cm = self.chapters.setdefault(idx, ChapterMarkup(title, sig))
        cm.title, cm.sig = title or cm.title, sig or cm.sig
        return cm

    def assign(self, chapter: int, block: int, start: int, end: int, speaker: int, tags: tuple[str, ...] = (),
               lang: str = "") -> None:
        """Give ``[start, end)`` of a block to a speaker (and a language other than the book's), replacing
        whatever overlapped it."""
        self.ensure_speaker(speaker)
        cm = self.chapter(chapter)
        kept: list[Span] = []
        for s in cm.spans:
            if s.block != block or s.end <= start or s.start >= end:
                kept.append(s)
                continue
            if s.start < start:
                kept.append(Span(block, s.start, start, s.speaker, s.tags, s.lang))
            if s.end > end:
                kept.append(Span(block, end, s.end, s.speaker, (), s.lang))
        lang = valid_lang(lang)
        if speaker != 0 or tags or lang:
            kept.append(Span(block, start, end, speaker, tags, lang))
        cm.spans = sorted(kept, key=lambda s: (s.block, s.start))

    def clear(self, chapter: int, block: int, start: int = 0, end: int = 1 << 30) -> None:
        cm = self.chapters.get(chapter)
        if cm is None:
            return
        cm.marks = [m for m in cm.marks if not (m.block == block and start <= m.at < end)]
        self.assign(chapter, block, start, end, 0)

    def add_mark(self, chapter: int, block: int, at: int, tag: str) -> None:
        cm = self.chapter(chapter)
        mark = Mark(block, at, norm_tag(tag))
        if mark not in cm.marks:
            cm.marks.append(mark)
            cm.marks.sort(key=lambda m: (m.block, m.at))

    # -- serialisation
    def to_dict(self) -> dict:
        return {"version": VERSION, "depth": self.depth, "expression_tags": self.expression_tags,
                "speakers": [{"id": s.id, "name": s.name, "voice": s.voice, "gender": s.gender,
                              "aliases": s.aliases, "notes": s.notes} for s in self.speakers],
                "chapters": {str(i): {"title": c.title, "sig": c.sig,
                                      "spans": [{"b": s.block, "s": s.start, "e": s.end, "sp": s.speaker,
                                                 "tags": list(s.tags), **({"lang": s.lang} if s.lang else {})}
                                                for s in c.spans],
                                      "marks": [{"b": m.block, "at": m.at, "tag": m.tag} for m in c.marks],
                                      "done": c.done, "review": c.review}
                             for i, c in sorted(self.chapters.items()) if c.spans or c.marks or c.done}}

    @classmethod
    def from_dict(cls, d: dict) -> Markup:
        try:
            if d.get("version") != VERSION:
                raise MarkupError(f"Unsupported markup version {d.get('version')!r}")
            m = cls(speakers=[Speaker(int(s["id"]), str(s.get("name", "")), str(s.get("voice", "")),
                                      str(s.get("gender", "")), list(s.get("aliases", [])), str(s.get("notes", "")))
                              for s in d.get("speakers", [])] or [Speaker(0, "Narrator")],
                    expression_tags=bool(d.get("expression_tags", True)), depth=int(d.get("depth", 2)))
            if m.speaker(0) is None:
                m.speakers.insert(0, Speaker(0, "Narrator"))
            for s in m.speakers:
                if not 0 <= s.id < MAX_SPEAKERS:
                    raise MarkupError(f"Speaker id {s.id} is outside 0..{MAX_SPEAKERS - 1}")
            for k, c in d.get("chapters", {}).items():
                m.chapters[int(k)] = ChapterMarkup(
                    str(c.get("title", "")), str(c.get("sig", "")),
                    [Span(int(s["b"]), int(s["s"]), int(s["e"]), int(s["sp"]),
                          tuple(norm_tag(t) for t in s.get("tags", [])), valid_lang(s.get("lang", "")))
                     for s in c.get("spans", [])],
                    [Mark(int(x["b"]), int(x["at"]), norm_tag(x["tag"])) for x in c.get("marks", [])],
                    bool(c.get("done", False)),
                    [{str(k): (int(v) if k == "b" else str(v)) for k, v in r.items()}
                     for r in c.get("review", []) if isinstance(r, dict) and "b" in r])
            return m
        except (KeyError, TypeError, ValueError) as e:
            if isinstance(e, MarkupError):
                raise
            raise MarkupError(f"Malformed markup: {e}") from None

    def save(self, path: Path) -> None:
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Markup:
        try:
            return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise MarkupError(f"{path}: not valid JSON ({e})") from None


def slice_markup(markup: Markup, chapter: int, first: int, last: int) -> Markup:
    """The markup of blocks ``first..last`` of a chapter as the markup of a one-chapter book of just those blocks
    (to listen to a passage with its speakers and tags)."""
    out = Markup(speakers=[Speaker(**s.__dict__) for s in markup.speakers], expression_tags=markup.expression_tags,
                 depth=markup.depth)
    cm = markup.chapters.get(chapter)
    if cm is None:
        return out
    new = out.chapter(0)
    new.spans = [Span(s.block - first, s.start, s.end, s.speaker, s.tags, s.lang) for s in cm.spans
                 if first <= s.block <= last]
    new.marks = [Mark(m.block - first, m.at, m.tag) for m in cm.marks if first <= m.block <= last]
    return out


def find(book_path: Path) -> Path | None:
    """``<book>.markup.json`` next to the book."""
    p = Path(book_path)
    p = p.with_name(p.stem + ".markup.json")
    return p if p.is_file() else None


def path_for(book_path: Path) -> Path:
    p = Path(book_path)
    return p.with_name(p.stem + ".markup.json")


# -- binding to a book ----------------------------------------------------------------------------------------

def chapter_sig(chapter) -> str:
    return block_sig([b.text for b in chapter.blocks])


def bind(markup: Markup, chapters: list) -> tuple[Markup, list[str]]:
    """Check the markup against the book's chapters (``book.chapters(depth)``): chapters whose text changed lose
    their markup (the narrator reads them); spans outside their block or overlapping are dropped. Returns a clean
    copy and the problems found, as readable messages."""
    problems: list[str] = []
    out = Markup(speakers=[Speaker(**s.__dict__) for s in markup.speakers], expression_tags=markup.expression_tags,
                 depth=markup.depth)
    for idx, cm in sorted(markup.chapters.items()):
        if idx >= len(chapters):
            problems.append(f"Markup for chapter {idx + 1} ignored: the book has {len(chapters)} chapters")
            continue
        ch = chapters[idx]
        if cm.sig and cm.sig != chapter_sig(ch):
            problems.append(f"Markup for chapter {idx + 1} ({ch.title}) ignored: the text no longer matches "
                            "the text it was made for")
            continue
        clean = ChapterMarkup(ch.title, chapter_sig(ch), done=cm.done)
        last_end: dict[int, int] = {}
        for s in sorted(cm.spans, key=lambda s: (s.block, s.start)):
            ok = 0 <= s.block < len(ch.blocks) and 0 <= s.start < s.end <= len(ch.blocks[s.block].text)
            if not ok or s.start < last_end.get(s.block, 0) or out.speaker(s.speaker) is None:
                problems.append(f"Chapter {idx + 1}, block {s.block}: a span was dropped (out of range, overlapping "
                                "or of an unknown speaker)")
                continue
            last_end[s.block] = s.end
            clean.spans.append(s)
        for m in cm.marks:
            if 0 <= m.block < len(ch.blocks) and 0 < m.at < len(ch.blocks[m.block].text) and m.tag:
                clean.marks.append(m)
            else:
                problems.append(f"Chapter {idx + 1}, block {m.block}: the tag [{m.tag}] was dropped (bad position)")
        clean.review = [r for r in cm.review if 0 <= r.get("b", -1) < len(ch.blocks)]
        out.chapters[idx] = clean
    return out, problems


def stamp(markup: Markup, chapters: list) -> None:
    """Record the text signature of every chapter that has markup (call before saving)."""
    for idx, cm in markup.chapters.items():
        if idx < len(chapters):
            cm.title, cm.sig = chapters[idx].title, chapter_sig(chapters[idx])


def unknown_tags(markup: Markup, model: str | None = None) -> set[str]:
    known = known_tags(model)
    used = {t for c in markup.chapters.values() for s in c.spans for t in s.tags}
    used |= {m.tag for c in markup.chapters.values() for m in c.marks}
    return used - known


# -- text form ------------------------------------------------------------------------------------------------

def block_to_text(markup: Markup, chapter: int, block: int, text: str) -> str:
    out: list[str] = []
    current = 0
    current_lang = ""
    pos = 0
    for seg in markup.segments(chapter, block, text):
        head = []
        ctrl = ""  # speaker and language switches are written together, with no space between them
        if seg.speaker != current:
            ctrl += f"<|speaker:{seg.speaker}|>"
            current = seg.speaker
        if seg.lang != current_lang:
            ctrl += f"<|lang:{seg.lang or '-'}|>"
            current_lang = seg.lang
        if ctrl:
            head.append(ctrl)
        head += [f"[{t}]" for t in seg.tags]
        if head:
            out.append(" ".join(head) + ("" if seg.text[:1] == " " else " "))
        out.append(seg.text)
        pos += len(seg.text)
    return "".join(out)


def export_text(markup: Markup, chapters: list) -> str:
    lines = ["# Folivox markup. Edit the speakers and tags; the book text itself must stay exactly as it is.",
             "# <|speaker:N|> switches the speaker (until the next tag, within a block); <|lang:xx|> the language",
             "# (<|lang:-|> = the book's); [tag] is an expression tag.",
             "# Lines: B<chapter>.<block>  text      Speakers: @speaker N | name | voice | gender"]
    for s in markup.speakers:
        lines.append(f"@speaker {s.id} | {s.name} | {s.voice} | {s.gender}")
    lines.append(f"@expression_tags {'on' if markup.expression_tags else 'off'}")
    for ci, ch in enumerate(chapters):
        lines.append("")
        lines.append(f"## chapter {ci + 1}: {ch.title}")
        for bi, b in enumerate(ch.blocks):
            if "\n" in b.text:
                continue  # poems keep their line breaks; annotate them in JSON
            lines.append(f"B{ci + 1}.{bi}  {block_to_text(markup, ci, bi, b.text)}")
    return "\n".join(lines) + "\n"


def _parse_block(line: str, original: str, loose: bool = False) -> tuple[list[Span], list[Mark]]:
    """Walk the edited line against the original text; tags are the only differences allowed. ``loose`` also
    tolerates differences in whitespace (a language model re-typing a paragraph); offsets stay in the original."""
    events: list[tuple[int, str, object]] = []
    i = p = 0

    def skip_space() -> int:  # the single space written after a tag
        return i + 1 if i < len(line) and line[i] == " " and (p >= len(original) or original[p] != " ") else i

    while i < len(line):
        m = SPEAKER_TAG.match(line, i)
        lg = LANG_TAG.match(line, i)
        t = TAG.match(line, i)
        if m:
            events.append((p, "sp", int(m.group(1))))
            i = m.end()
            i = skip_space()
        elif lg:
            code = "" if lg.group(1) == "-" else valid_lang(lg.group(1))
            if lg.group(1) != "-" and not code:
                raise MarkupError(f"unknown language {lg.group(1)!r}")
            events.append((p, "lang", code))
            i = lg.end()
            i = skip_space()
        elif t and not original.startswith(t.group(0), p):
            events.append((p, "tag", norm_tag(t.group(1))))
            i = t.end()
            i = skip_space()
        elif p < len(original) and line[i] == original[p]:
            i += 1
            p += 1
        elif loose and line[i].isspace():
            i += 1
        elif loose and p < len(original) and original[p].isspace():
            p += 1
        else:
            raise MarkupError("the text differs from the book")
    while loose and p < len(original) and original[p].isspace():
        p += 1
    if p != len(original):
        raise MarkupError("the text differs from the book")
    spans: list[Span] = []
    marks: list[Mark] = []
    speaker, start, tags, lang = 0, 0, [], ""
    for off, kind, value in events:
        if kind in ("sp", "lang"):
            if off > start and (speaker != 0 or tags or lang):
                spans.append(Span(-1, start, off, speaker, tuple(tags), lang))
            if kind == "sp":
                speaker = int(value)  # type: ignore[arg-type]
            else:
                lang = str(value)
            start, tags = off, []
        elif off == start:
            tags.append(str(value))
        else:
            marks.append(Mark(-1, off, str(value)))
    if len(original) > start and (speaker != 0 or tags or lang):
        spans.append(Span(-1, start, len(original), speaker, tuple(tags), lang))
    return spans, marks


def parse_block(line: str, original: str, loose: bool = False) -> tuple[list[Span], list[Mark]]:
    """Spans and marks (block index -1) of one annotated line; raises :class:`MarkupError` if its text is not the
    original text (so annotations can be taken from untrusted sources, such as a language model)."""
    return _parse_block(line, original, loose)


def import_text(text: str, chapters: list, base: Markup | None = None) -> Markup:
    """Read the text form back. Raises :class:`MarkupError` naming the first block whose text was changed."""
    mk = Markup(depth=base.depth if base else 2)
    mk.speakers = []
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line or line.startswith(("#", "//")):
            continue
        if line.startswith("@speaker"):
            parts = [x.strip() for x in line[len("@speaker"):].split("|")]
            head = parts[0].split()
            if not head or not head[0].isdigit():
                raise MarkupError(f"Bad speaker line: {line!r}")
            sp = mk.ensure_speaker(int(head[0]), parts[1] if len(parts) > 1 else "")
            sp.name = parts[1] if len(parts) > 1 and parts[1] else sp.name
            sp.voice = parts[2] if len(parts) > 2 else ""
            sp.gender = parts[3] if len(parts) > 3 else ""
            continue
        if line.startswith("@expression_tags"):
            mk.expression_tags = line.split()[-1].lower() != "off"
            continue
        m = re.match(r"B(\d+)\.(\d+)  (.*)$", line)
        if not m:
            raise MarkupError(f"Unrecognised line: {line[:60]!r}")
        ci, bi = int(m.group(1)) - 1, int(m.group(2))
        if not (0 <= ci < len(chapters) and 0 <= bi < len(chapters[ci].blocks)):
            raise MarkupError(f"B{ci + 1}.{bi}: no such block")
        original = chapters[ci].blocks[bi].text
        try:
            spans, marks = _parse_block(m.group(3), original)
        except MarkupError as e:
            raise MarkupError(f"B{ci + 1}.{bi}: {e}") from None
        for s in spans:
            if mk.speaker(s.speaker) is None:
                mk.ensure_speaker(s.speaker)
        if spans or marks:
            cm = mk.chapter(ci)
            cm.spans += [Span(bi, s.start, s.end, s.speaker, s.tags, s.lang) for s in spans]
            cm.marks += [Mark(bi, x.at, x.tag) for x in marks]
    if mk.speaker(0) is None:
        mk.speakers.insert(0, Speaker(0, "Narrator"))
    stamp(mk, chapters)
    return mk
