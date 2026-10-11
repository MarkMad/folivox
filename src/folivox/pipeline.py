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
    voice_wav: Path | None = None  # reference recording (local engines)
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
    cover: Path | None = None  # an image to use instead of the book's own cover
    no_cover: bool = False  # write no cover at all
    meta: dict[str, str] = field(default_factory=dict)  # edited book details; an empty value keeps the book's own
    chunk: ChunkOptions = field(default_factory=ChunkOptions)
    # cloud engines (paid, the text leaves the computer)
    tts_model: str = "auto"
    tts_voice: str = ""  # provider voice id or name
    tts_style: str | None = None  # narration note; None → the engine's neutral default
    tts_mode: str = "preset"  # preset | design | localize | clone
    tts_description: str = ""  # voice description (design mode)
    voice_ref: Path | None = None  # your own recording to clone (clone mode)
    max_cost: float | None = None  # stop cleanly before spending more than this many USD
    accept_cloud: bool = False  # the caller showed the estimate and the user agreed
    keep_voice: bool = False  # keep a voice made in the provider account (and list it for other books)
    tts_voice_name: str = ""  # the name a kept voice is listed under

    def resolved_work_dir(self) -> Path:
        return self.work_dir or self.output.with_name(self.output.stem + ".folivox")


class Cancelled(Exception):
    """Raised by :func:`render` when ``Events.cancelled()`` returns True; progress is saved in the journal."""


class CostCapReached(Cancelled):
    """The spending cap was reached; progress is saved, raise the cap and run again to continue."""


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

    def layout(self, chapters: list[dict]) -> None:
        """Every fragment of every selected chapter: ``{index, title, fragments: [[chars, key]], done: "1010…"}``."""

    def step(self, step: str, attempt: int = 1, attempts: int = 1) -> None:
        """What happens to the current fragment: ``synth`` (take n of m), ``qa`` (recognising it), ``split``."""

    def download(self, name: str, done_bytes: int, total_bytes: int) -> None:
        """Model weights are being downloaded (``total_bytes`` is 0 when unknown)."""

    def spend(self, chars: int, usd: float | None, cap: float | None) -> None:
        """Cloud engines: characters sent so far in this run and the approximate spend."""


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


def plan(book: Book, opts: RenderOptions, journal: Journal, voice_id: str, events: Events, engine=None) -> list[str]:
    chapters = book.chapters(opts.depth)
    selected = parse_selection(opts.chapters, len(chapters))
    events.stage("plan", f"Preparing text: {len(selected)} of {len(chapters)} chapters")
    cloud = engine is not None and not engine.local
    stress = opts.stress
    if cloud and stress == "all":  # stress marks are CosyVoice markup; a cloud voice would read them aloud
        events.warning("Stress marks are not used with cloud engines; restoring ё only")
        stress = "yo"
    max_chars = min(opts.max_chars, engine.max_chars) if cloud else opts.max_chars  # the provider's request limit
    copts = ChunkOptions(max_chars=max_chars, min_chars=min(opts.chunk.min_chars, max_chars), stress=stress,
                         lang=opts.lang or book.lang or "ru", pauses=opts.chunk.pauses,
                         speak_headings=opts.chunk.speak_headings)
    planned = [(chapters[i].title, _limit(plan_chapter(chapters[i], copts), opts.preview, copts))
               for i in selected]
    settings = f"{SYNTH_VERSION}|llm={opts.llm}|speed={opts.speed}"
    if opts.tts != "cosyvoice3":  # keep cache keys of existing CosyVoice renders valid
        settings = f"{opts.tts}|speed={opts.speed}"
        if cloud:
            settings = f"{opts.tts}|{engine.model}"
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


def _best_take(prefetch, asr, opts: RenderOptions, key: str, text: str, source: str, depth: int = 0,
               events: Events | None = None):
    """Synthesise ``text`` up to ``opts.max_takes`` times, keep the best take by QA score.

    If every take fails QA and the fragment has several sentences, split it in two at a
    sentence boundary and render the halves separately: CosyVoice tends to drop the last
    sentence of long, list-like paragraphs, and shorter inputs fix that reliably.
    Returns (score, audio, asr_text, per-attempt scores).
    """
    from folivox.qa import score, threshold_for
    from folivox.text.chunk import sentences
    from folivox.text.stress import strip_marks

    events = events or Events()
    best = None
    attempts: list[float | None] = []
    lang = opts.lang or "ru"
    limit = threshold_for(source, opts.qa_threshold, lang)
    takes = max(1, opts.max_takes if asr else 1)
    for attempt in range(takes):
        events.step("synth", attempt + 1, takes)
        if attempt:  # a retake of a cloud fragment is billed: stop cleanly instead of overspending
            _check_cap(prefetch.engine, len(text))
        syn = prefetch.synthesize(key, text, _seed(key, attempt), speed=opts.speed)
        audio = postprocess(syn.audio, syn.sample_rate)
        dur = len(audio) / syn.sample_rate
        sc = hyp = None
        if asr is not None:
            events.step("qa", attempt + 1, takes)
            hyp = asr.transcribe(audio, syn.sample_rate) if dur > 0.05 else ""
            sc = score(source, hyp, dur, lang)
        attempts.append(sc)
        if best is None or (sc is not None and sc < best[0]):
            best = (sc if sc is not None else 0.0, audio, hyp)
        if sc is None or sc <= limit:
            return best[0], best[1], best[2], attempts

    parts = sentences(text, lang)
    # a split re-renders the fragment: free locally, billed again with a cloud engine
    if len(parts) < 2 or depth >= (2 if getattr(prefetch.engine, "local", True) else 0):
        return best[0], best[1], best[2], attempts
    events.step("split")
    # split into two halves of similar length at a sentence boundary
    total, acc, cut = sum(len(x) for x in parts), 0, 1
    for i, part in enumerate(parts[:-1], 1):
        acc += len(part)
        if acc >= total / 2:
            cut = i
            break
    halves = [" ".join(parts[:cut]), " ".join(parts[cut:])]
    results = [_best_take(prefetch, asr, opts, f"{key}/{i}", h, strip_marks(h), depth + 1, events)
               for i, h in enumerate(halves)]
    sr = prefetch.engine.sample_rate
    audio = np.concatenate([results[0][1], np.zeros(int(sr * SPLIT_PAUSE), np.float32), results[1][1]])
    joined = f"{results[0][2] or ''} {results[1][2] or ''}".strip()
    split_score = score(source, joined, len(audio) / sr, lang) if asr is not None else 0.0
    attempts += results[0][3] + results[1][3]
    if split_score < best[0]:
        return split_score, audio, joined, attempts
    return best[0], best[1], best[2], attempts


def _check_cap(engine, next_chars: int) -> None:
    check = getattr(engine, "check_budget", None)
    if check is not None:
        check(next_chars)


def _report_spend(engine, events: Events, opts: RenderOptions) -> None:
    if not getattr(engine, "local", True):
        events.spend(engine.chars_sent, engine.spent_usd, opts.max_cost)


def synthesize_pending(journal: Journal, engine, voice, asr, opts: RenderOptions, events: Events) -> None:
    from folivox.tts.base import Prefetcher

    pending = journal.pending()
    st = journal.stats()
    events.plan(st["total_chars"], st["done_chars"], len(journal.chunks()), len(pending))
    pending_keys = {c.key for c in pending}
    layout = []
    for ci, title in journal.chapters():
        chunks = journal.chunks(ci)
        layout.append({"index": ci, "title": title, "fragments": [[len(c.source), c.key[:10]] for c in chunks],
                       "done": "".join("0" if c.key in pending_keys else "1" for c in chunks)})
    events.layout(layout)
    todo: list[PlannedChunk] = []
    keys: set[str] = set()
    for c in pending:  # the same sentence may occur twice in a book
        if c.key not in keys:
            keys.add(c.key)
            todo.append(c)

    from folivox.tts.cloud import CostCapReached as CapHit

    prefetch = Prefetcher(engine, voice)
    try:
        clock = time.time()
        for pos, chunk in enumerate(todo):
            if events.cancelled():
                raise Cancelled
            _check_cap(engine, len(chunk.text))
            for nxt in todo[pos: pos + 1 + max(LOOKAHEAD, engine.parallel)]:
                prefetch.submit(nxt.key, nxt.text, _seed(nxt.key, 0))
            events.chunk_started(chunk)
            sc, audio, hyp, attempts = _best_take(prefetch, asr, opts, chunk.key, chunk.text, chunk.source,
                                                  events=events)
            sr = engine.sample_rate
            dur = len(audio) / sr
            save(journal.audio_path(chunk.key), audio, sr)
            now = time.time()
            # wall time since the previous fragment: with prefetching, stage times overlap
            take = Take(chunk.key, dur, sc if asr is not None else None, hyp, len(attempts), now - clock)
            clock = now
            journal.record(take)
            events.chunk_done(chunk, take, attempts)
            _report_spend(engine, events, opts)
    except CapHit as e:
        raise CostCapReached(str(e)) from None
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
    m = opts.meta
    meta = BookMeta(m.get("title") or book.title, m.get("author") or book.author, m.get("year") or book.year,
                    m.get("description") or book.annotation, m.get("narrator") or opts.narrator,
                    m.get("series", ""), m.get("series_part", ""), m.get("genre", ""))
    cover = None if opts.no_cover else (opts.cover.read_bytes() if opts.cover else book.cover)
    events.stage("encode", "Encoding {fmt}".format(fmt="MP3" if opts.mp3 else "M4B"))
    if opts.mp3:
        out_dir = opts.output if opts.output.suffix == "" else opts.output.with_suffix("")
        write_mp3s(built, out_dir, meta, cover)
        return out_dir
    write_m4b(built, opts.output, meta, cover, opts.bitrate)
    return opts.output


def _engine_options(opts: RenderOptions) -> dict:
    if opts.tts == "cosyvoice3":
        return {"model_dir": opts.model_dir, "device": opts.device, "threads": opts.threads, "llm": opts.llm}
    return {"device": opts.device}


def is_cloud(name: str) -> bool:
    from folivox.tts import ENGINES

    return not ENGINES.get(name).local


def _default_voice_name(engine, opts: RenderOptions) -> str:
    """A readable name for a kept voice when the user gave none: never a bare provider id."""
    from folivox import lang as languages

    if opts.tts_mode == "design" and opts.tts_description:
        return opts.tts_description[:40].strip(" ,.")
    base = getattr(engine.gen, "names", {}).get(opts.tts_voice, "")
    language = languages.get(opts.lang).name
    if opts.tts_mode == "localize" and base:
        return f"{base} · {language}"
    if opts.tts_mode == "clone" and opts.voice_ref:
        return f"{Path(opts.voice_ref).parent.name or 'My voice'} (clone)"
    return f"My {language} voice"


def _cloud_voice(engine, opts: RenderOptions, journal: Journal, events: Events):
    """The provider voice for the whole run → ``(voice, owned)``.

    A voice kept from an earlier book (``tts_voice`` = its id or name) is reused as it is and never deleted here.
    A voice made for this book (design / localize / clone) is remembered in the journal so an interrupted run
    continues with the same voice; it is deleted after a finished run unless ``keep_voice`` lists it for later."""
    from folivox.tts import saved

    mine = saved.find(opts.tts, opts.tts_voice)
    if mine is not None:
        voice = engine.make_voice("", opts.tts_style, opts.lang, mine["mode"], mine.get("description", ""), None,
                                  mine["id"])
        events.stage("voice", f"Using your saved voice “{mine['name']}”")
        return voice, False
    kind = f"{opts.tts}|{opts.tts_mode}|{opts.tts_voice}|{opts.tts_description}|{opts.voice_ref}"
    remembered = journal.meta("cloud_voice") if journal.meta("cloud_voice_for") == kind else ""
    voice = engine.make_voice(opts.tts_voice, opts.tts_style, opts.lang, opts.tts_mode, opts.tts_description,
                              opts.voice_ref, remembered or "")
    if opts.tts_mode == "preset":
        if not voice.speaker and opts.tts in ("elevenlabs", "cartesia"):
            raise RuntimeError(f"Pick a voice for {opts.tts} (--tts-voice NAME or id; `folivox tts-voices {opts.tts}`)")
        return voice, False
    journal.set_meta(cloud_voice=voice.speaker, cloud_voice_for=kind)
    if not remembered:
        events.stage("voice", f"Created a voice in your {type(engine.gen).label} account for this book")
    if opts.keep_voice:
        name = opts.tts_voice_name or _default_voice_name(engine, opts)
        saved.add(opts.tts, voice.speaker, name, opts.tts_mode, opts.tts_description, opts.lang)
        events.stage("voice", f"Voice “{name}” is kept in your account and listed for other books")
    return voice, True


def render(book: Book, opts: RenderOptions, events: Events | None = None) -> Path:
    from folivox.qa.asr import ASR_PROVIDERS
    from folivox.tts import ENGINES
    from folivox.tts.voice import load_voice

    events = events or Events()
    from folivox import lang as languages

    opts.lang = languages.get(opts.lang or book.lang or "ru").code
    journal = Journal(opts.resolved_work_dir())
    voice, owned = None, False
    try:
        cloud = is_cloud(opts.tts)
        if cloud and not opts.accept_cloud:
            from folivox.providers import ProviderError

            raise ProviderError(f"{opts.tts} is a paid cloud engine: the book text is sent to the provider and billed "
                                "to your account. Confirm the cost estimate first (--yes in the CLI, the checkbox in "
                                "the studio)")
        asr = None
        if opts.qa:
            events.stage("asr", f"Loading speech recognition for QA ({opts.asr})")
            asr = ASR_PROVIDERS.create(opts.asr, language=opts.lang)
        engine = None
        if cloud:
            if opts.speed != 1.0:
                events.warning("Reading speed is not applied by cloud engines; the provider's own pace is used")
            engine = ENGINES.create(opts.tts, model=opts.tts_model, max_cost=opts.max_cost)
            voice, owned = _cloud_voice(engine, opts, journal, events)
            for w in voice.warnings:
                events.warning(w)
            events.stage("model", f"{type(engine.gen).label}, model {engine.model}")
        else:
            voice = load_voice(opts.voice_wav, opts.voice_text,
                               transcribe=asr.transcribe_file if asr else None)
            for w in voice.warnings:
                events.warning(w)
        plan(book, opts, journal, voice.id, events, engine)
        if journal.pending():
            from folivox.tts import weights

            if engine is not None:
                sample_rate = engine.sample_rate
            else:
                if opts.tts == "cosyvoice3" and weights.needs_download(opts.model_dir, opts.llm):
                    events.stage("download", "Preparing the model download (first run)")
                else:
                    events.stage("model", f"Loading TTS model into memory ({opts.tts})")
                t0 = time.time()

                with weights.reporting(events.download):
                    engine = ENGINES.create(opts.tts, **_engine_options(opts))
                events.stage("model", f"Model loaded in {time.time() - t0:.0f} s ({engine.device})")
                sample_rate = engine.sample_rate
            synthesize_pending(journal, engine, voice, asr, opts, events)
        else:
            sample_rate = journal.meta("sample_rate", 24000)
        journal.set_meta(sample_rate=sample_rate)
        result = assemble(journal, book, opts, sample_rate, events)
        if cloud and owned and not opts.keep_voice:
            engine.release(voice)  # only after a finished run: an interrupted one resumes with the same voice
            journal.set_meta(cloud_voice="", cloud_voice_for="")
        return result
    finally:
        journal.close()
