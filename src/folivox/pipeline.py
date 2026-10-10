"""Book → audiobook pipeline. UI-agnostic: progress is reported through :class:`Events`."""

from __future__ import annotations

import hashlib
import re
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from folivox.audio import postprocess, save
from folivox.audio.assemble import BookMeta, ChapterAudio, build_chapter, write_m4b, write_mp3s
from folivox.book import Book
from folivox.journal import Journal, PlannedChunk, Take
from folivox.text.chunk import ChunkOptions, plan_chapter

# Bump when synthesis changes in a way that invalidates cached audio.
SYNTH_VERSION = "cv3-1"


@dataclass
class RenderOptions:
    output: Path
    voice_wav: Path
    voice_text: str | None = None
    work_dir: Path | None = None
    chapters: str | None = None  # "1-3,5" (1-based)
    preview: int | None = None  # only the first N characters of each selected chapter
    depth: int = 2
    max_chars: int = 400
    stress: str = "yo"
    lang: str | None = None  # book language (ISO 639-1); None → from the book metadata / detection
    speed: float = 1.0
    device: str = "auto"
    tts: str = "cosyvoice3"  # provider name in folivox.tts.ENGINES
    asr: str = "auto"  # provider name in folivox.qa.asr.ASR_PROVIDERS
    llm: str = "rl"  # CosyVoice LLM weights: "rl" (fewer content errors, per upstream eval) or "base"
    threads: int | None = None
    model_dir: str | None = None
    qa: bool = True
    max_takes: int = 3
    qa_threshold: float = 0.08
    mp3: bool = False
    bitrate: str = "64k"
    narrator: str = ""
    chunk: ChunkOptions = field(default_factory=ChunkOptions)

    def resolved_work_dir(self) -> Path:
        return self.work_dir or self.output.with_name(self.output.stem + ".folivox")


class Cancelled(Exception):
    """Raised by :func:`render` when ``Events.cancelled()`` returns True; progress is saved in the journal."""


class Events:
    """Override what you need. All methods are called from the rendering thread."""

    def cancelled(self) -> bool:
        """Polled between fragments; return True to stop cleanly (resume later by running again)."""
        return False

    def stage(self, name: str, detail: str = "") -> None: ...

    def warning(self, message: str) -> None: ...

    def plan(self, total_chars: int, done_chars: int, total_chunks: int, pending_chunks: int) -> None: ...

    def chunk_started(self, chunk: PlannedChunk) -> None: ...

    def chunk_done(self, chunk: PlannedChunk, take: Take, attempts: list[float | None]) -> None: ...

    def chapter_built(self, index: int, title: str, duration: float) -> None: ...


def parse_selection(spec: str | None, count: int) -> list[int]:
    """'1-3,5' → [0, 1, 2, 4] (0-based); None → all."""
    if not spec:
        return list(range(count))
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)?\s*-\s*(\d+)?|(\d+)", part)
        if not m:
            raise ValueError(f"Invalid chapter number: {part!r}")
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a, b = int(m.group(1) or 1), int(m.group(2) or count)
        out.update(i - 1 for i in range(a, b + 1) if 1 <= i <= count)
    if not out:
        raise ValueError(f"The book has no chapters {spec!r} (there are {count})")
    return sorted(out)


def plan(book: Book, opts: RenderOptions, journal: Journal, voice_id: str, events: Events) -> list[str]:
    chapters = book.chapters(opts.depth)
    selected = parse_selection(opts.chapters, len(chapters))
    events.stage("plan", f"Preparing text: {len(selected)} of {len(chapters)} chapters")
    copts = ChunkOptions(max_chars=opts.max_chars, min_chars=opts.chunk.min_chars, stress=opts.stress,
                         lang=opts.lang or book.lang or "ru", pauses=opts.chunk.pauses,
                         speak_headings=opts.chunk.speak_headings)
    planned = [(chapters[i].title, _limit(plan_chapter(chapters[i], copts), opts.preview, copts))
               for i in selected]
    settings = f"{SYNTH_VERSION}|llm={opts.llm}|speed={opts.speed}"
    if opts.tts != "cosyvoice3":  # keep cache keys of existing CosyVoice renders valid
        settings = f"{opts.tts}|speed={opts.speed}"
    journal.set_plan(planned, voice_id, settings)
    journal.set_meta(book_title=book.title, chapters_selected=[i + 1 for i in selected], settings=settings)
    return [t for t, _ in planned]


LOOKAHEAD = 2  # fragments whose LLM tokens are generated ahead of time


def _seed(key: str, attempt: int) -> int:
    return zlib.crc32(key.encode()) + attempt * 7919


def _limit(chunks, preview: int | None, copts: ChunkOptions):
    """Keep fragments until ``preview`` characters are covered; end with a chapter pause."""
    if not preview:
        return chunks
    out, n = [], 0
    for c in chunks:
        if n >= preview:
            break
        out.append(c)
        n += len(c.source)
    if out:
        out[-1].pause_after = copts.pauses.chapter_end
    return out


SPLIT_PAUSE = 0.25  # seconds between the halves of a fragment split after failed takes


def _best_take(prefetch, asr, opts: RenderOptions, key: str, text: str, source: str, depth: int = 0):
    """Synthesise ``text`` up to ``opts.max_takes`` times, keep the best take by QA score.

    If every take fails QA and the fragment has several sentences, split it in two at a
    sentence boundary and render the halves separately: CosyVoice tends to drop the last
    sentence of long, list-like paragraphs, and shorter inputs fix that reliably.
    Returns (score, audio, asr_text, per-attempt scores).
    """
    from folivox.qa import score, threshold_for
    from folivox.text.chunk import sentences
    from folivox.text.stress import strip_marks

    best = None
    attempts: list[float | None] = []
    lang = opts.lang or "ru"
    limit = threshold_for(source, opts.qa_threshold, lang)
    for attempt in range(max(1, opts.max_takes if asr else 1)):
        syn = prefetch.synthesize(key, text, _seed(key, attempt), speed=opts.speed)
        audio = postprocess(syn.audio, syn.sample_rate)
        dur = len(audio) / syn.sample_rate
        sc = hyp = None
        if asr is not None:
            hyp = asr.transcribe(audio, syn.sample_rate) if dur > 0.05 else ""
            sc = score(source, hyp, dur, lang)
        attempts.append(sc)
        if best is None or (sc is not None and sc < best[0]):
            best = (sc if sc is not None else 0.0, audio, hyp)
        if sc is None or sc <= limit:
            return best[0], best[1], best[2], attempts

    parts = sentences(text, lang)
    if len(parts) < 2 or depth >= 2:
        return best[0], best[1], best[2], attempts
    # split into two halves of similar length at a sentence boundary
    total, acc, cut = sum(len(x) for x in parts), 0, 1
    for i, part in enumerate(parts[:-1], 1):
        acc += len(part)
        if acc >= total / 2:
            cut = i
            break
    halves = [" ".join(parts[:cut]), " ".join(parts[cut:])]
    results = [_best_take(prefetch, asr, opts, f"{key}/{i}", h, strip_marks(h), depth + 1)
               for i, h in enumerate(halves)]
    sr = prefetch.engine.sample_rate
    audio = np.concatenate([results[0][1], np.zeros(int(sr * SPLIT_PAUSE), np.float32), results[1][1]])
    joined = f"{results[0][2] or ''} {results[1][2] or ''}".strip()
    split_score = score(source, joined, len(audio) / sr, lang) if asr is not None else 0.0
    attempts += results[0][3] + results[1][3]
    if split_score < best[0]:
        return split_score, audio, joined, attempts
    return best[0], best[1], best[2], attempts


def synthesize_pending(journal: Journal, engine, voice, asr, opts: RenderOptions, events: Events) -> None:
    from folivox.tts.base import Prefetcher

    pending = journal.pending()
    st = journal.stats()
    events.plan(st["total_chars"], st["done_chars"], len(journal.chunks()), len(pending))
    todo: list[PlannedChunk] = []
    keys: set[str] = set()
    for c in pending:  # the same sentence may occur twice in a book
        if c.key not in keys:
            keys.add(c.key)
            todo.append(c)

    prefetch = Prefetcher(engine, voice)
    try:
        clock = time.time()
        for pos, chunk in enumerate(todo):
            if events.cancelled():
                raise Cancelled
            for nxt in todo[pos: pos + 1 + LOOKAHEAD]:
                prefetch.submit(nxt.key, nxt.text, _seed(nxt.key, 0))
            events.chunk_started(chunk)
            sc, audio, hyp, attempts = _best_take(prefetch, asr, opts, chunk.key, chunk.text, chunk.source)
            sr = engine.sample_rate
            dur = len(audio) / sr
            save(journal.audio_path(chunk.key), audio, sr)
            now = time.time()
            # wall time since the previous fragment: with prefetching, stage times overlap
            take = Take(chunk.key, dur, sc if asr is not None else None, hyp, len(attempts), now - clock)
            clock = now
            journal.record(take)
            events.chunk_done(chunk, take, attempts)
    finally:
        prefetch.close()


def assemble(journal: Journal, book: Book, opts: RenderOptions, sample_rate: int, events: Events) -> Path:
    work = journal.dir
    built: list[ChapterAudio] = []
    for ci, title in journal.chapters():
        chunks = journal.chunks(ci)
        if not chunks or not all(journal.is_done(c.key) for c in chunks):
            events.warning(f"Chapter “{title}” is not fully rendered — skipping")
            continue
        sig = hashlib.sha1("|".join(f"{c.key}:{c.pause}" for c in chunks).encode()).hexdigest()
        path = work / "chapters" / f"{ci + 1:03d}.flac"
        if journal.meta(f"chapter_sig_{ci}") == sig and path.exists():
            dur = journal.meta(f"chapter_dur_{ci}")
        else:
            events.stage("chapter", f"Building chapter {ci + 1}: {title}")
            dur = build_chapter([(journal.audio_path(c.key), c.pause) for c in chunks], path, sample_rate)
            journal.set_meta(**{f"chapter_sig_{ci}": sig, f"chapter_dur_{ci}": dur})
        built.append(ChapterAudio(title, path, dur))
        events.chapter_built(ci, title, dur)
    if not built:
        raise RuntimeError("Nothing to assemble: no chapter is fully rendered")
    meta = BookMeta(book.title, book.author, book.year, book.annotation, opts.narrator)
    events.stage("encode", "Encoding {fmt}".format(fmt="MP3" if opts.mp3 else "M4B"))
    if opts.mp3:
        out_dir = opts.output if opts.output.suffix == "" else opts.output.with_suffix("")
        write_mp3s(built, out_dir, meta, book.cover)
        return out_dir
    write_m4b(built, opts.output, meta, book.cover, opts.bitrate)
    return opts.output


def _engine_options(opts: RenderOptions) -> dict:
    if opts.tts == "cosyvoice3":
        return {"model_dir": opts.model_dir, "device": opts.device, "threads": opts.threads, "llm": opts.llm}
    return {"device": opts.device}


def render(book: Book, opts: RenderOptions, events: Events | None = None) -> Path:
    from folivox.qa.asr import ASR_PROVIDERS
    from folivox.tts import ENGINES
    from folivox.tts.voice import load_voice

    events = events or Events()
    from folivox import lang as languages

    opts.lang = languages.get(opts.lang or book.lang or "ru").code
    journal = Journal(opts.resolved_work_dir())
    try:
        asr = None
        if opts.qa:
            events.stage("asr", f"Loading speech recognition for QA ({opts.asr})")
            asr = ASR_PROVIDERS.create(opts.asr, language=opts.lang)
        voice = load_voice(opts.voice_wav, opts.voice_text,
                           transcribe=asr.transcribe_file if asr else None)
        for w in voice.warnings:
            events.warning(w)
        plan(book, opts, journal, voice.id, events)
        if journal.pending():
            events.stage("model", f"Loading TTS model ({opts.tts})")
            t0 = time.time()
            engine = ENGINES.create(opts.tts, **_engine_options(opts))
            events.stage("model", f"Model loaded in {time.time() - t0:.0f} s ({engine.device})")
            sample_rate = engine.sample_rate
            synthesize_pending(journal, engine, voice, asr, opts, events)
        else:
            sample_rate = journal.meta("sample_rate", 24000)
        journal.set_meta(sample_rate=sample_rate)
        return assemble(journal, book, opts, sample_rate, events)
    finally:
        journal.close()
