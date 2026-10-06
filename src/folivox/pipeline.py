"""Book → audiobook pipeline. UI-agnostic: progress is reported through :class:`Events`."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

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
    max_chars: int = 220
    stress: str = "yo"
    speed: float = 1.0
    device: str = "auto"
    llm: str = "rl"  # "rl" (fewer content errors, per upstream eval) or "base"
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


class Events:
    """Override what you need. All methods are called from the rendering thread."""

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
            raise ValueError(f"Неверный номер главы: {part!r}")
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a, b = int(m.group(1) or 1), int(m.group(2) or count)
        out.update(i - 1 for i in range(a, b + 1) if 1 <= i <= count)
    if not out:
        raise ValueError(f"В книге нет глав {spec!r} (всего {count})")
    return sorted(out)


def plan(book: Book, opts: RenderOptions, journal: Journal, voice_id: str, events: Events) -> list[str]:
    chapters = book.chapters(opts.depth)
    selected = parse_selection(opts.chapters, len(chapters))
    events.stage("plan", f"Разметка текста: {len(selected)} из {len(chapters)} глав")
    copts = ChunkOptions(max_chars=opts.max_chars, min_chars=opts.chunk.min_chars, stress=opts.stress,
                         pauses=opts.chunk.pauses, speak_headings=opts.chunk.speak_headings)
    planned = [(chapters[i].title, _limit(plan_chapter(chapters[i], copts), opts.preview, copts))
               for i in selected]
    settings = f"{SYNTH_VERSION}|llm={opts.llm}|speed={opts.speed}"
    journal.set_plan(planned, voice_id, settings)
    journal.set_meta(book_title=book.title, chapters_selected=[i + 1 for i in selected], settings=settings)
    return [t for t, _ in planned]


LOOKAHEAD = 2  # fragments whose LLM tokens are generated ahead of time


def _seed(key: str, attempt: int) -> int:
    return int(key[:8], 16) + attempt * 7919


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


def synthesize_pending(journal: Journal, engine, voice, asr, opts: RenderOptions, events: Events) -> None:
    from folivox.qa import score
    from folivox.tts.engine import Prefetcher

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
            for nxt in todo[pos: pos + 1 + LOOKAHEAD]:
                prefetch.submit(nxt.key, nxt.text, _seed(nxt.key, 0))
            events.chunk_started(chunk)
            best = None
            attempts: list[float | None] = []
            for attempt in range(max(1, opts.max_takes if asr else 1)):
                syn = prefetch.synthesize(chunk.key, chunk.text, _seed(chunk.key, attempt), speed=opts.speed)
                audio = postprocess(syn.audio, syn.sample_rate)
                dur = len(audio) / syn.sample_rate
                sc = hyp = None
                if asr is not None:
                    hyp = asr.transcribe(audio, syn.sample_rate) if dur > 0.05 else ""
                    sc = score(chunk.source, hyp, dur)
                attempts.append(sc)
                if best is None or (sc is not None and sc < best[0]):
                    best = (sc if sc is not None else 0.0, audio, hyp, dur, syn.sample_rate)
                if sc is None or sc <= opts.qa_threshold:
                    break
            sc, audio, hyp, dur, sr = best
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
            events.warning(f"Глава «{title}» озвучена не полностью — пропускаю")
            continue
        sig = hashlib.sha1("|".join(f"{c.key}:{c.pause}" for c in chunks).encode()).hexdigest()
        path = work / "chapters" / f"{ci + 1:03d}.flac"
        if journal.meta(f"chapter_sig_{ci}") == sig and path.exists():
            dur = journal.meta(f"chapter_dur_{ci}")
        else:
            events.stage("chapter", f"Сборка главы {ci + 1}: {title}")
            dur = build_chapter([(journal.audio_path(c.key), c.pause) for c in chunks], path, sample_rate)
            journal.set_meta(**{f"chapter_sig_{ci}": sig, f"chapter_dur_{ci}": dur})
        built.append(ChapterAudio(title, path, dur))
        events.chapter_built(ci, title, dur)
    if not built:
        raise RuntimeError("Нечего собирать: ни одна глава не озвучена полностью")
    meta = BookMeta(book.title, book.author, book.year, book.annotation, opts.narrator)
    events.stage("encode", f"Кодирование {'MP3' if opts.mp3 else 'M4B'}")
    if opts.mp3:
        out_dir = opts.output if opts.output.suffix == "" else opts.output.with_suffix("")
        write_mp3s(built, out_dir, meta, book.cover)
        return out_dir
    write_m4b(built, opts.output, meta, book.cover, opts.bitrate)
    return opts.output


def render(book: Book, opts: RenderOptions, events: Events | None = None) -> Path:
    from folivox.tts.engine import CosyVoiceEngine
    from folivox.tts.voice import load_voice

    events = events or Events()
    journal = Journal(opts.resolved_work_dir())
    try:
        asr = None
        if opts.qa:
            from folivox.qa.asr import Transcriber

            events.stage("asr", "Загрузка Whisper для проверки")
            asr = Transcriber()
        voice = load_voice(opts.voice_wav, opts.voice_text,
                           transcribe=asr.transcribe_file if asr else None)
        for w in voice.warnings:
            events.warning(w)
        plan(book, opts, journal, voice.id, events)
        if journal.pending():
            events.stage("model", "Загрузка CosyVoice 3")
            t0 = time.time()
            engine = CosyVoiceEngine(opts.model_dir, opts.device, opts.threads, llm=opts.llm)
            events.stage("model", f"Модель загружена за {time.time() - t0:.0f} с ({engine.device})")
            sample_rate = engine.sample_rate
            synthesize_pending(journal, engine, voice, asr, opts, events)
        else:
            sample_rate = journal.meta("sample_rate", 24000)
        journal.set_meta(sample_rate=sample_rate)
        return assemble(journal, book, opts, sample_rate, events)
    finally:
        journal.close()
