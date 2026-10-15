"""Automatic markup with a text LLM: a character bible (who is in the book) and per-paragraph speaker marking.

Two passes, both resumable and cached:

1. **Analyse** reads the whole book once, window by window, and builds the *character bible*: names with
   aliases, gender, role, age, speech traits, relations and how many lines each speaks. The bible tells how many
   distinct voices the book needs, before any voice is chosen.
2. **Annotate** walks the paragraphs that contain speech and asks the model to mark who speaks each part (and,
   if asked, where an expression tag belongs). The model sees the bible entries relevant to the window and a short
   context of the previous paragraphs, so "he said" and pronouns resolve across chapters; it may add or correct
   bible entries as it reads.

The model only *annotates*. It is asked to repeat each paragraph with ``<|speaker:N|>`` / ``[tag]`` inserted; the
reply is accepted only if removing the annotations gives exactly the book's paragraph
(:func:`folivox.markup.parse_block`). Anything else, an unknown speaker or tag, a failed call: the narrator reads
that paragraph and a warning is counted. Offsets are always computed here, never taken from the model.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from folivox import markup as mk
from folivox.lang import has_speech

PROMPT_VERSION = "1"
WINDOW_CHARS = 5000
MIN_LINES_FOR_A_VOICE = 3  # a character who speaks less than this is not counted as needing a voice of their own
MAX_RELEVANT = 25
SPEECH_MARKS = re.compile(r"[«»„“”\"‘’「」『』]|^\s*[—–―-]\s|\bthink|\bthought", re.I | re.M)

Progress = Callable[[str, int, int, str], None]  # stage, done, total, message


class LLMError(RuntimeError):
    pass


# -- character bible ------------------------------------------------------------------------------------------

def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.casefold().replace("\u0451", "\u0435"))  # yo -> ye
    return "".join(c for c in s if c.isalnum() or c == " ").strip()


def same_name(a: str, b: str) -> bool:
    """Equal names, or the same name in another case/declension (Anna/Anny/Annu, Ivan/Ivana)."""
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return False
    if a == b:
        return True
    lo = min(len(a), len(b))
    if lo < 3 or " " in a or " " in b or abs(len(a) - len(b)) > 3:
        return False
    common = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        common += 1
    return common >= max(3, lo - 1)


@dataclass
class Character:
    name: str
    aliases: list[str] = field(default_factory=list)
    gender: str = ""  # f | m | n (neutral/group) | "" unknown
    role: str = "minor"  # main | minor
    age: str = ""
    traits: str = ""  # how the character speaks
    relations: list[dict] = field(default_factory=list)  # [{"with": name, "kind": "mother"}]
    lines: int = 0  # lines of direct speech seen so far
    first: int = -1  # chapter where the character first appears
    unnamed: bool = False
    id: int = 0  # speaker id in the markup (0 = not assigned)
    voice_prompts: dict = field(default_factory=dict)  # voice-design descriptions: simple / standard / detailed

    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def matches(self, name: str) -> bool:
        return any(norm_name(n) == norm_name(name) for n in self.names())

    def matches_loosely(self, name: str, gender: str = "") -> bool:
        """Same name in another case form; never across two known, different genders (Mark / Mara)."""
        if self.gender and gender and self.gender != gender:
            return False
        return any(same_name(n, name) for n in self.names())


@dataclass
class Bible:
    lang: str = ""
    narration: str = ""  # first | third | mixed | ""
    characters: list[Character] = field(default_factory=list)
    model: str = ""
    done_windows: int = 0
    total_windows: int = 0

    def find(self, name: str, gender: str = "") -> Character | None:
        name = (name or "").strip()
        if not name:
            return None
        return (next((c for c in self.characters if c.matches(name)), None)
                or next((c for c in self.characters if c.matches_loosely(name, gender)), None))

    def merge(self, entry: dict, chapter: int = -1) -> Character | None:
        """Add what the model reported about one character; the same person under another name is recognised."""
        name = str(entry.get("name") or "").strip()
        if not name or len(name) > 60:
            return None
        aliases = [str(a).strip() for a in entry.get("aliases") or [] if str(a).strip() and len(str(a)) <= 60]
        gender = str(entry.get("gender") or "").strip().lower()[:1]
        gender = gender if gender in ("f", "m", "n") else ""
        c = self.find(name, gender) or next((x for x in (self.find(a, gender) for a in aliases) if x), None)
        if c is None:
            c = Character(name=name, first=chapter)
            self.characters.append(c)
        for a in [name, *aliases]:
            if not c.matches(a):
                c.aliases.append(a)
        if gender and not c.gender:
            c.gender = gender
        if str(entry.get("role") or "") == "main":
            c.role = "main"
        age = str(entry.get("age") or "").strip()[:30]
        if age and age != "?" and not c.age:
            c.age = age
        traits = str(entry.get("traits") or "").strip()[:200]
        if traits and traits.lower() not in c.traits.lower():
            c.traits = (c.traits + "; " + traits).strip("; ")[:300]
        for r in entry.get("relations") or []:
            if isinstance(r, dict) and r.get("with") and r not in c.relations and len(c.relations) < 12:
                c.relations.append({"with": str(r["with"])[:60], "kind": str(r.get("kind", ""))[:30]})
        try:
            c.lines += max(0, int(entry.get("lines") or 0))
        except (TypeError, ValueError):
            pass
        c.unnamed = c.unnamed or bool(entry.get("unnamed"))
        if c.first < 0:
            c.first = chapter
        return c

    def speakers(self) -> list[Character]:
        return sorted((c for c in self.characters if c.lines > 0), key=lambda c: -c.lines)

    def voices_needed(self, min_lines: int = MIN_LINES_FOR_A_VOICE) -> int:
        """Narrator plus every character who speaks at least ``min_lines`` lines."""
        return 1 + sum(1 for c in self.characters if c.lines >= min_lines)

    def assign_ids(self) -> None:
        """Stable speaker ids 1..15: keep existing ones, give the next free id to new speakers by lines spoken.
        With more than 15, the rarest share the ids 14 (men / unknown) and 15 (women)."""
        used = {c.id for c in self.characters if c.id}
        for c in sorted(self.characters, key=lambda c: -c.lines):
            if c.id or c.lines <= 0:
                continue
            free = next((i for i in range(1, mk.MAX_SPEAKERS) if i not in used), None)
            if free is None or (free >= 14 and sum(1 for x in self.characters if x.lines > 0) > 15):
                c.id = 15 if c.gender == "f" else 14
            else:
                c.id = free
                used.add(free)

    def to_dict(self) -> dict:
        return {"version": 1, "lang": self.lang, "narration": self.narration, "model": self.model,
                "done_windows": self.done_windows, "total_windows": self.total_windows,
                "voices_needed": self.voices_needed(), "characters": [c.__dict__ for c in self.characters]}

    @classmethod
    def from_dict(cls, d: dict) -> Bible:
        b = cls(str(d.get("lang", "")), str(d.get("narration", "")), model=str(d.get("model", "")),
                done_windows=int(d.get("done_windows", 0)), total_windows=int(d.get("total_windows", 0)))
        for c in d.get("characters", []):
            known = {k: c[k] for k in Character.__dataclass_fields__ if k in c}
            if known.get("name"):
                b.characters.append(Character(**known))
        return b

    def save(self, path: Path) -> None:
        tmp = Path(path).with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Bible:
        try:
            return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, AttributeError) as e:
            raise LLMError(f"Cannot read the character list {path}: {e}") from None


def bible_path(book_path: Path) -> Path:
    p = Path(book_path)
    return p.with_name(p.stem + ".characters.json")


def cache_path(book_path: Path) -> Path:
    p = Path(book_path)
    return p.with_name(p.stem + ".llm-cache.sqlite")


# -- cache and calls -------------------------------------------------------------------------------------------

class Cache:
    """Model replies by hash of (model, prompt version, prompts): an interrupted run continues where it stopped
    and an unchanged window is never asked twice."""

    def __init__(self, path: Path | None):
        self.db = sqlite3.connect(str(path) if path else ":memory:")
        self.db.execute("CREATE TABLE IF NOT EXISTS replies (key TEXT PRIMARY KEY, reply TEXT NOT NULL)")

    def get(self, key: str) -> str | None:
        row = self.db.execute("SELECT reply FROM replies WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, reply: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO replies VALUES (?, ?)", (key, reply))
        self.db.commit()

    def close(self) -> None:
        self.db.close()


def extract_json(text: str) -> dict:
    """The JSON object in a model reply (tolerates code fences, prose around it and trailing commas)."""
    text = re.sub(r"```(?:json)?", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON object in the reply")
    raw = text[a:b + 1]
    try:
        out = json.loads(raw)
    except ValueError:
        out = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
    if not isinstance(out, dict):
        raise ValueError("the reply is not a JSON object")
    return out


class Runner:
    """Calls the model with caching, JSON extraction and a few retries (a warmer second try)."""

    def __init__(self, llm, model: str, cache: Cache, tries: int = 2):
        self.llm, self.model, self.cache, self.tries = llm, model, cache, tries
        self.calls = self.cached = self.failures = 0

    def ask(self, system: str, prompt: str, validate: Callable[[dict], dict]) -> dict:
        """Reply parsed and checked by ``validate`` (which raises ValueError on a bad one)."""
        key = hashlib.sha1("\x1f".join((PROMPT_VERSION, self.model, system, prompt)).encode()).hexdigest()
        hit = self.cache.get(key)
        if hit is not None:
            try:
                out = validate(extract_json(hit))
                self.cached += 1
                return out
            except ValueError:
                pass
        last: Exception | None = None
        for attempt in range(self.tries):
            self.calls += 1
            extra = "" if attempt == 0 else "\n\nYour previous answer was not valid. Answer with the JSON object only."
            try:
                reply = self.llm.complete_json(prompt + extra, system=system, temperature=0.1 + 0.2 * attempt)
                out = validate(extract_json(reply))
            except (ValueError, KeyError, TypeError) as e:
                last = e
                continue
            except OSError as e:  # the model server is gone: not worth retrying every window
                raise LLMError(f"The language model did not answer: {e}") from None
            self.cache.put(key, reply)
            return out
        self.failures += 1
        raise ValueError(f"no usable answer after {self.tries} tries: {last}")


# -- windows --------------------------------------------------------------------------------------------------

@dataclass
class Window:
    chapter: int
    blocks: list[tuple[int, str]]  # (block index, text)

    @property
    def chars(self) -> int:
        return sum(len(t) for _, t in self.blocks)

    def text(self) -> str:
        return "\n".join(f"[B{b}] {t}" for b, t in self.blocks)


_LOOSE_SPEAKER = re.compile(r"<\|?\s*speaker\s*:\s*(\d{1,2})\s*\|?>")


def _fix_speaker_tags(line: str) -> str:
    """Small models often drop a bar (``<|speaker:1>``); read those as the tag they meant."""
    return _LOOSE_SPEAKER.sub(r"<|speaker:\1|>", line)


def windows(chapters: list, max_chars: int = WINDOW_CHARS, only_speech: bool = False) -> list[Window]:
    """Consecutive paragraphs of a chapter, up to ``max_chars`` (a paragraph is never cut)."""
    out: list[Window] = []
    for ci, ch in enumerate(chapters):
        cur: list[tuple[int, str]] = []
        size = 0
        for bi, b in enumerate(ch.blocks):
            t = b.text.strip()
            if not has_speech(t) or "\n" in t or (only_speech and not SPEECH_MARKS.search(t)):
                continue
            if cur and size + len(t) > max_chars:
                out.append(Window(ci, cur))
                cur, size = [], 0
            cur.append((bi, t))
            size += len(t)
        if cur:
            out.append(Window(ci, cur))
    return out


LANG_NAMES = {"ru": "Russian", "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
              "zh": "Chinese", "ja": "Japanese", "ko": "Korean"}

QUOTE_HINTS = ("Direct speech may be written with dialogue dashes (— …), guillemets («…»), curly or straight "
               "quotes (“…”, \"…\"), corner brackets (「…」『…』), or with no marks at all in some translations. "
               "Inner thoughts and letters read aloud also belong to a character, not to the narrator.")

# -- analyse ---------------------------------------------------------------------------------------------------

ANALYSE_SYSTEM = ("You are a careful literary analyst. You prepare books for multi-voice audiobooks. You answer "
                  "with one JSON object and nothing else. You never invent facts that are not in the text.")

ANALYSE_PROMPT = """Book language: {lang}.
{hints}

Characters already known (reuse the exact "name" when it is the same person, also under a nickname, a
patronymic, a title or another grammatical form; put new forms into "aliases"):
{known}

Read the excerpt (paragraphs are numbered [B..]). List every character who SPEAKS (direct speech), THINKS
(inner monologue) or is clearly important in it. Do not list places, objects, groups of people that never speak,
or the narrator. A speaker with no name gets a short descriptive name in the book's language ("old guard") and
"unnamed": true. Keep names exactly as spelled in the book (nominative case).

Reply with this JSON:
{{"narration_person": "first" | "third" | "mixed",
 "characters": [{{"name": str, "aliases": [str], "gender": "f" | "m" | "n" | "?", "role": "main" | "minor",
   "age": "child" | "young" | "adult" | "old" | "?", "traits": "how this character speaks, 6 words at most",
   "relations": [{{"with": str, "kind": str}}], "lines": <number of their direct-speech lines in this excerpt>,
   "unnamed": bool}}]}}

Excerpt:
{text}"""


def _known(bible: Bible, relevant: list[Character]) -> str:
    rows = [{"name": c.name, "aliases": c.aliases[:6], "gender": c.gender or "?", "role": c.role}
            for c in relevant]
    return json.dumps(rows, ensure_ascii=False) if rows else "(none yet)"


def relevant_for(bible: Bible, window_text: str, recent: list[str]) -> list[Character]:
    """Characters named in the window or active in the previous ones, plus the busiest, at most ``MAX_RELEVANT``."""
    low = norm_name(window_text)
    named = [c for c in bible.characters if any(norm_name(n) and norm_name(n)[: max(3, len(norm_name(n)) - 1)] in low
                                                for n in c.names())]
    active = [c for c in bible.characters if c.name in recent]
    busiest = sorted(bible.characters, key=lambda c: -c.lines)[:5]
    seen, out = set(), []
    for c in [*named, *active, *busiest]:
        if id(c) not in seen:
            seen.add(id(c))
            out.append(c)
    return out[:MAX_RELEVANT]


def analyse(chapters: list, lang: str, runner: Runner, bible: Bible | None = None, *, max_windows: int | None = None,
            save: Callable[[Bible], None] | None = None, progress: Progress | None = None,
            cancelled: Callable[[], bool] = lambda: False, window_chars: int = WINDOW_CHARS) -> Bible:
    """Read the book once and fill the character bible. Resumable: windows done before are skipped."""
    bible = bible or Bible()
    bible.lang, bible.model = lang, runner.model
    wins = windows(chapters, window_chars, only_speech=False)
    if max_windows and len(wins) > max_windows:  # spread a sample over the whole book
        step = len(wins) / max_windows
        wins = [wins[int(i * step)] for i in range(max_windows)]
    bible.total_windows = len(wins)
    recent: list[str] = []
    narr: dict[str, int] = {}
    for n, w in enumerate(wins):
        if cancelled():
            break
        if n < bible.done_windows:
            continue
        text = w.text()
        prompt = ANALYSE_PROMPT.format(lang=LANG_NAMES.get(lang, lang), hints=QUOTE_HINTS,
                                       known=_known(bible, relevant_for(bible, text, recent)), text=text)

        def check(d: dict) -> dict:
            if not isinstance(d.get("characters"), list):
                raise ValueError("no characters list")
            return d

        try:
            out = runner.ask(ANALYSE_SYSTEM, prompt, check)
        except ValueError as e:
            if progress:
                progress("analyse", n + 1, len(wins), f"window {n + 1} skipped: {e}")
            bible.done_windows = n + 1
            continue
        narr[str(out.get("narration_person", ""))] = narr.get(str(out.get("narration_person", "")), 0) + 1
        recent = []
        for e in out["characters"]:
            if isinstance(e, dict):
                c = bible.merge(e, w.chapter)
                if c:
                    recent.append(c.name)
        bible.done_windows = n + 1
        if narr:
            top = max(narr, key=narr.get)
            bible.narration = top if top in ("first", "third", "mixed") else bible.narration
        if save:
            save(bible)
        if progress:
            progress("analyse", n + 1, len(wins), f"{len(bible.characters)} characters")
    bible.assign_ids()
    if save:
        save(bible)
    return bible


# -- annotate --------------------------------------------------------------------------------------------------

ANNOTATE_SYSTEM = ("You mark up books for multi-voice audiobooks. You never change the text: you only insert "
                   "speaker markers. You answer with one JSON object and nothing else.")

ANNOTATE_PROMPT = """Book language: {lang}. {hints}
Narration is {person}-person.

Speakers (id = marker number; 0 is the narrator and needs no marker):
{speakers}
{recent}
For every numbered paragraph below that contains direct speech or a character's thoughts, repeat the paragraph
EXACTLY (same words, spaces and punctuation) inserting <|speaker:N|> in front of each part spoken by speaker N and
<|speaker:0|> where the narrator continues. Attribution such as "said Anna" is the narrator's. Do not mark
paragraphs that are pure narration. Resolve pronouns and "he said" from the context. If a speaker is not in the
list, leave that part to the narrator and add the speaker to "new_characters" (they get a marker for the next
paragraphs); if you learn something about a listed speaker (a new alias, the real gender) put it in
"updates".{expression}

Reply with this JSON:
{{"blocks": [{{"b": <paragraph number>, "text": "<the paragraph with markers>"}}],
 "new_characters": [{{"name": str, "aliases": [str], "gender": "f" | "m" | "n" | "?", "unnamed": bool}}],
 "updates": [{{"name": str, "aliases": [str], "gender": "f" | "m" | "n" | "?"}}]}}

Paragraphs:
{text}"""

EXPRESSION_RULES = """
Also put an expression tag in square brackets, for example [sighs] or [whispering], at the exact spot where the
text clearly asks for it (a sigh, a laugh, whispering, shouting, a long pause). Use only these tags:
{tags}
At most one tag per sentence, none when the text does not call for it; most paragraphs get none."""


@dataclass
class AnnotateStats:
    blocks: int = 0
    marked: int = 0
    fell_back: int = 0
    unknown_speakers: int = 0
    dropped_tags: int = 0
    failed_windows: int = 0
    new_characters: int = 0


def _speakers_json(bible: Bible, relevant: list[Character]) -> str:
    rows = []
    for c in relevant:
        if not c.id:
            continue
        rows.append({"id": c.id, "name": c.name, "aliases": c.aliases[:5], "gender": c.gender or "?",
                     "age": c.age, "traits": c.traits[:80]})
    return json.dumps(rows, ensure_ascii=False) if rows else "(no characters)"


def _tag_list() -> str:
    """The sound and tone tags offered to the model: short, common, documented for the Fish models."""
    names = sorted({t["tag"] for t in mk.tag_database()["tags"] if t["category"] in ("sound", "tone")})
    return ", ".join(f"[{t}]" for t in names[:30])


def annotate(chapters: list, lang: str, bible: Bible, runner: Runner, markup: mk.Markup | None = None, *,
             expression_tags: bool = False, chapter_filter: set[int] | None = None,
             save: Callable[[mk.Markup, Bible], None] | None = None, progress: Progress | None = None,
             cancelled: Callable[[], bool] = lambda: False, window_chars: int = WINDOW_CHARS,
             depth: int = 2) -> tuple[mk.Markup, AnnotateStats]:
    """Mark who speaks in every paragraph with speech. Existing spans in the paragraphs processed are replaced."""
    markup = markup or mk.Markup(depth=depth)
    markup.depth = depth
    bible.assign_ids()
    stats = AnnotateStats()
    wins = [w for w in windows(chapters, window_chars, only_speech=True)
            if chapter_filter is None or w.chapter in chapter_filter]
    tags_known = mk.known_tags() if expression_tags else set()
    tag_list = _tag_list() if expression_tags else ""
    recent_names: list[str] = []
    recent_ctx: list[str] = []

    def sync_speakers() -> None:
        for c in bible.characters:
            if c.id:
                sp = markup.ensure_speaker(c.id, c.name)
                if sp.name.startswith("Speaker ") or not sp.name:
                    sp.name = c.name
                sp.gender = sp.gender or c.gender
                sp.aliases = c.aliases[:8]
                sp.notes = sp.notes or c.traits

    for n, w in enumerate(wins):
        if cancelled():
            break
        text = w.text()
        relevant = relevant_for(bible, text, recent_names)
        recent = ""
        if recent_ctx:
            recent = "Context, the previous paragraphs and who spoke them:\n" + "\n".join(recent_ctx[-4:]) + "\n"
        prompt = ANNOTATE_PROMPT.format(
            lang=LANG_NAMES.get(lang, lang), hints=QUOTE_HINTS, person=bible.narration or "third",
            speakers=_speakers_json(bible, relevant), recent=recent, text=text,
            expression=EXPRESSION_RULES.format(tags=tag_list) if expression_tags else "")
        originals = dict(w.blocks)

        def check(d: dict) -> dict:
            if not isinstance(d.get("blocks"), list):
                raise ValueError("no blocks list")
            return d

        try:
            out = runner.ask(ANNOTATE_SYSTEM, prompt, check)
        except ValueError:
            stats.failed_windows += 1
            stats.blocks += len(w.blocks)
            stats.fell_back += len(w.blocks)
            if progress:
                progress("annotate", n + 1, len(wins), f"window {n + 1}: the narrator reads it")
            continue
        # characters the model met for the first time
        for e in list(out.get("new_characters") or []) + list(out.get("updates") or []):
            if isinstance(e, dict):
                before = len(bible.characters)
                bible.merge({**e, "lines": 0}, w.chapter)
                stats.new_characters += len(bible.characters) - before
        bible.assign_ids()
        for c in bible.characters:  # a new speaker needs an id and a line to get one
            if not c.id and c.lines <= 0:
                c.lines = 1
        bible.assign_ids()
        sync_speakers()
        ids = {c.id for c in bible.characters if c.id} | {0}
        by_name = {c.id: c.name for c in bible.characters if c.id}
        seen: set[int] = set()
        recent_names = []
        cm = markup.chapter(w.chapter, chapters[w.chapter].title, mk.chapter_sig(chapters[w.chapter]))
        for item in out["blocks"]:
            try:
                b = int(str(item["b"]).lstrip("B"))
                line = _fix_speaker_tags(str(item["text"]))
            except (KeyError, TypeError, ValueError):
                continue
            original = originals.get(b)
            if original is None or b in seen:
                continue
            seen.add(b)
            stats.blocks += 1
            try:
                spans, marks = mk.parse_block(line, original, loose=True)
            except mk.MarkupError:
                stats.fell_back += 1
                continue
            good_spans = []
            for s in spans:
                if s.speaker not in ids:
                    stats.unknown_speakers += 1
                    continue
                tags = tuple(t for t in s.tags if t in tags_known)
                stats.dropped_tags += len(s.tags) - len(tags)
                if s.speaker or tags:
                    good_spans.append(mk.Span(b, s.start, s.end, s.speaker, tags))
            good_marks = []
            for m in marks:
                if m.tag in tags_known:
                    good_marks.append(mk.Mark(b, m.at, m.tag))
                else:
                    stats.dropped_tags += 1
            cm.spans = [x for x in cm.spans if x.block != b] + good_spans
            cm.marks = [x for x in cm.marks if x.block != b] + good_marks
            if good_spans or good_marks:
                stats.marked += 1
                names = [by_name.get(s.speaker, "narrator") for s in good_spans if s.speaker] or ["narrator"]
                recent_names += [by_name[s.speaker] for s in good_spans if s.speaker in by_name]
                recent_ctx.append(f"{original[:140]} -> {', '.join(dict.fromkeys(names))}")
        missing = [b for b, _ in w.blocks if b not in seen]
        stats.blocks += len(missing)  # paragraphs the model skipped: the narrator reads them
        cm.spans.sort(key=lambda s: (s.block, s.start))
        cm.marks.sort(key=lambda m: (m.block, m.at))
        if save:
            save(markup, bible)
        if progress:
            progress("annotate", n + 1, len(wins), f"{stats.marked} paragraphs marked")
    return markup, stats


# -- choosing and reaching the model ------------------------------------------------------------------------------

def make_llm(provider: str | None = None, model: str | None = None):
    """(llm, model name) from the config and options. For Ollama the model defaults to the largest Gemma 4 that
    suits this computer, and a missing model or a stopped server is reported with the command that fixes it."""
    from folivox import config, diag
    from folivox.llm import LLMS, recommend_model

    name = config.provider("llm", provider) or LLMS.default
    cfg = config.section(f"llm.{name}")
    if name == "ollama":
        model = model or cfg.get("model") or recommend_model(diag.ram_gb())
        llm = LLMS.create(name, model=model)
        have = llm.installed()
        if not have:
            raise LLMError("Ollama is not running (start it, or install it from https://ollama.com), or has no "
                           f"models. Then:  ollama pull {model}")
        if not any(h == model or h.split(":")[0] == model for h in have):
            raise LLMError(f"The model {model} is not installed. Run:  ollama pull {model}   (installed: "
                           f"{', '.join(have)})")
        return llm, model
    llm = LLMS.create(name, **({"model": model} if model else {}))
    return llm, getattr(llm, "model", name)
