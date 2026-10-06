"""Command line interface.

``folivox BOOK [options]`` renders an audiobook (the ``render`` command is implied);
``folivox inspect BOOK`` shows the chapter tree and estimates; ``folivox voices`` manages voices;
``folivox providers`` lists the pluggable backends.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from folivox import __version__
from folivox.book import Book, Section
from folivox.i18n import _

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich",
                  help=_("Folivox — turn e-books (FB2, EPUB, DOCX, PDF, TXT) into m4b audiobooks, locally."))
console = Console()
COMMANDS = {"render", "inspect", "voices", "providers", "--help", "-h", "--version"}


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return _("{h} h {m:02d} min", h=h, m=m) if h else _("{m} min {s:02d} s", m=m, s=s)


def num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _load(path: Path, lang: str | None = None) -> Book:
    from folivox.readers import UnsupportedFormat, read_book

    if not path.exists():
        console.print(f"[red]{_('File not found:')}[/] {path}")
        raise typer.Exit(2)
    try:
        book = read_book(path)
    except UnsupportedFormat as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(2) from None
    if lang:
        book.lang = _check_lang(lang)
    return book


def _check_lang(code: str) -> str:
    from folivox import lang

    try:
        return lang.get(code).code
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(2) from None


def _lang_name(code: str) -> str:
    from folivox import lang

    try:
        language = lang.get(code)
        return f"{language.native} ({language.code})"
    except ValueError:
        return code or "—"


@app.command(help=_("Show the book structure, chapters and estimated audio length."))
def inspect(
    book_path: Path = typer.Argument(..., help=_("Book file"), show_default=False),
    depth: int = typer.Option(2, "--depth", help=_("Chapter split depth (1 — top level only)")),
    lang: str | None = typer.Option(None, "--lang", help=_("Book language (default: from metadata / detected)")),
    text: bool = typer.Option(False, "--text", help=_("Show the beginning of every chapter")),
):
    """Show the book structure, chapters and estimated audio length."""
    book = _load(book_path, lang)
    meta = Table.grid(padding=(0, 2))
    meta.add_row(_("Title"), book.title)
    meta.add_row(_("Author"), book.author or "—")
    meta.add_row(_("Language"), _lang_name(book.lang))
    meta.add_row(_("Format"), book.source_format.upper())
    if book.year:
        meta.add_row(_("Year"), book.year)
    meta.add_row(_("Cover"), _("yes ({kb} KB)", kb=len(book.cover) // 1024) if book.cover else _("no"))
    words = sum(len(b.text.split()) for ch in book.chapters(depth) for b in ch.blocks)
    meta.add_row(_("Size"), _("{chars} characters, {words} words", chars=num(book.chars), words=num(words)))
    meta.add_row(_("Audio (estimate)"), f"≈ {fmt_duration(book.estimated_seconds)}")
    console.print(meta)
    console.print()

    tree = Tree(f"[bold]{book.title}[/]")

    def add(node, sec: Section):
        label = sec.title or f"[dim]{_('(untitled)')}[/]"
        n = node.add(f"{label} [dim]· {num(sec.chars)} {_('chars')}[/]")
        for c in sec.children:
            add(n, c)

    for s in book.sections:
        add(tree, s)
    console.print(tree)
    console.print()

    chapters = book.chapters(depth)
    cps = book.chars / book.estimated_seconds if book.estimated_seconds else 14.0
    t = Table(title=_("Audiobook chapters ({n})", n=len(chapters)), show_lines=False)
    t.add_column("#", justify="right")
    t.add_column(_("Chapter"))
    t.add_column(_("Characters"), justify="right")
    t.add_column(_("≈ Time"), justify="right")
    if text:
        t.add_column(_("Beginning"))
    for i, ch in enumerate(chapters, 1):
        row = [str(i), ch.title, num(ch.chars), fmt_duration(ch.chars / cps)]
        if text:
            first = next((b.text for b in ch.blocks), "")
            row.append(first[:60] + ("…" if len(first) > 60 else ""))
        t.add_row(*row)
    console.print(t)


class RichEvents:
    """Console progress for :func:`folivox.pipeline.render`."""

    def __init__(self, verbose: bool = False):
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            TaskProgressColumn,
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )

        self.verbose = verbose
        self.progress = Progress(TextColumn("[bold]{task.description}"), BarColumn(), TaskProgressColumn(),
                                 MofNCompleteColumn(), TextColumn(_("chars")), TimeElapsedColumn(), TextColumn("·"),
                                 TimeRemainingColumn(), TextColumn("{task.fields[info]}"), console=console,
                                 transient=False)
        self.task = None
        self.audio = self.synth = 0.0
        self.retakes = self.flagged = 0

    def stage(self, name, detail=""):
        console.log(f"[cyan]{detail or name}[/]")

    def warning(self, message):
        console.log(f"[yellow]⚠ {message}[/]")

    def plan(self, total_chars, done_chars, total_chunks, pending_chunks):
        console.log(_("Fragments: {total}, left {pending}; text {chars} chars (done {done})",
                      total=num(total_chunks), pending=num(pending_chunks), chars=num(total_chars),
                      done=num(done_chars)))
        if pending_chunks:
            self.progress.start()
            self.task = self.progress.add_task(_("Rendering"), total=total_chars, completed=done_chars, info="")

    def chunk_started(self, chunk):
        pass

    def chunk_done(self, chunk, take, attempts):
        self.audio += take.duration
        self.synth += take.synth_seconds
        if len(attempts) > 1:
            self.retakes += len(attempts) - 1
        rtf = self.synth / self.audio if self.audio else 0
        info = _("RTF {rtf:.2f} · audio {audio}", rtf=rtf, audio=fmt_duration(self.audio))
        if self.retakes:
            info += _(" · retakes {n}", n=self.retakes)
        if self.task is not None:
            self.progress.update(self.task, advance=len(chunk.source), info=info)
        if self.verbose or (take.score is not None and len(attempts) > 1):
            sc = ", ".join("—" if a is None else f"{a:.2f}" for a in attempts)
            self.progress.console.log(f"[dim]{_('ch.')}{chunk.chapter + 1} #{chunk.idx}[/] [{sc}] {chunk.text[:70]}")

    def chapter_built(self, index, title, duration):
        if self.task is not None and self.progress.live.is_started:
            self.progress.stop()
        console.log(f"[green]✓[/] {title} — {fmt_duration(duration)}")

    def close(self):
        if self.progress.live.is_started:
            self.progress.stop()


@app.command(help=_("Render a book into an audiobook (m4b with chapters and cover)."))
def render(
    book_path: Path = typer.Argument(..., help=_("Book file (FB2, EPUB, DOCX, PDF, TXT)"), show_default=False),
    voice: str = typer.Option("", "--voice", "-v", envvar="FOLIVOX_VOICE",
                              help=_("Voice id from the catalog (folivox voices) or a WAV/FLAC file with 6–15 s "
                                     "of clean speech"), show_default=_("by book language")),
    voice_text: str | None = typer.Option(None, "--voice-text", envvar="FOLIVOX_VOICE_TEXT",
                                          help=_("Transcript of the sample (text or .txt). Default: .txt next to "
                                                 "the sample, else Whisper")),
    output: Path | None = typer.Option(None, "--output", "-o", help=_("Output .m4b (or a folder with --mp3)")),
    lang: str | None = typer.Option(None, "--lang", help=_("Book language: ru en de fr es it zh ja ko "
                                                             "(default: from metadata / detected)")),
    chapters: str | None = typer.Option(None, "--chapters", "-c", help=_("Which chapters: 1-3,5")),
    preview: int | None = typer.Option(None, "--preview", help=_("Only the first N characters of each chapter")),
    mp3: bool = typer.Option(False, "--mp3", help=_("MP3 per chapter instead of one m4b")),
    work_dir: Path | None = typer.Option(None, "--work-dir", help=_("Cache folder (default <output>.folivox)")),
    depth: int = typer.Option(2, "--depth", help=_("Chapter split depth")),
    max_chars: int = typer.Option(400, "--max-chars", help=_("Longest fragment sent to the model")),
    stress: str = typer.Option("yo", "--stress", help=_("Russian: none | yo (restore ё) | all (stress marks, "
                                                        "experimental)")),
    speed: float = typer.Option(1.0, "--speed", help=_("Speaking rate")),
    qa: bool = typer.Option(True, "--qa/--no-qa", help=_("Check every fragment with speech recognition")),
    takes: int = typer.Option(3, "--takes", help=_("Max takes per fragment when QA finds a mismatch")),
    tts: str | None = typer.Option(None, "--tts", help=_("TTS provider (folivox providers)"),
                                   show_default="cosyvoice3"),
    asr: str | None = typer.Option(None, "--asr", help=_("Speech recognition provider for QA"),
                                   show_default="auto"),
    llm: str = typer.Option("rl", "--llm", help=_("CosyVoice LLM weights: rl (fewer text errors) | base")),
    device: str = typer.Option("auto", "--device", help="auto | cpu | cuda | mps"),
    threads: int | None = typer.Option(None, "--threads", help=_("PyTorch CPU threads")),
    model_dir: Path | None = typer.Option(None, "--model-dir", envvar="FOLIVOX_MODEL_DIR",
                                          help=_("CosyVoice 3 weights folder (downloaded otherwise)")),
    bitrate: str = typer.Option("64k", "--bitrate", help=_("AAC bitrate")),
    verbose: bool = typer.Option(False, "--verbose", help=_("Print every fragment")),
):
    """Render a book into an audiobook (m4b with chapters and cover)."""
    from folivox import config
    from folivox.pipeline import RenderOptions
    from folivox.pipeline import render as run_render
    from folivox.providers import ProviderError
    from folivox.text.stress import MODES

    if stress not in MODES:
        console.print(f"[red]--stress: {', '.join(MODES)}[/]")
        raise typer.Exit(2)
    book = _load(book_path, lang)
    voice_path, voice_text, voice_lang = _resolve_voice(voice, voice_text, book.lang)
    if voice_lang and voice_lang != book.lang:
        console.print(f"[yellow]⚠ {_('The voice sample is in {v}, the book in {b}: the accent may carry over.', v=_lang_name(voice_lang), b=_lang_name(book.lang))}[/]")  # noqa: E501
    if output is None:
        output = book_path.with_suffix("" if mp3 else ".m4b")
    opts = RenderOptions(output=output, voice_wav=voice_path, voice_text=voice_text, work_dir=work_dir,
                         chapters=chapters, preview=preview, depth=depth, max_chars=max_chars, stress=stress,
                         lang=book.lang, speed=speed, device=device, threads=threads,
                         model_dir=str(model_dir) if model_dir else None, qa=qa, max_takes=takes, mp3=mp3,
                         bitrate=bitrate, llm=llm, tts=config.provider("tts", tts) or "cosyvoice3",
                         asr=config.provider("asr", asr) or "auto")
    console.print(f"[bold]{book.title}[/] — {book.author or _('unknown author')}; {_lang_name(book.lang)}; "
                  f"{_('estimated audio')} ≈ {fmt_duration(book.estimated_seconds)}")
    events = RichEvents(verbose)
    t0 = time.time()
    try:
        result = run_render(book, opts, events)
    except KeyboardInterrupt:
        events.close()
        console.print(f"\n[yellow]{_('Stopped. Progress is saved — run the same command again to continue.')}[/]")
        raise typer.Exit(130) from None
    except Exception as e:  # noqa: BLE001
        events.close()
        from folivox.tts.voice import VoiceError

        if isinstance(e, (VoiceError, ValueError, FileNotFoundError, RuntimeError, ProviderError)):
            console.print(f"[red]{_('Error:')}[/] {e}")
            raise typer.Exit(1) from None
        raise
    events.close()
    console.print(f"[bold green]{_('Done:')}[/] {result}  ({fmt_duration(time.time() - t0)})")
    if events.audio:
        console.print(_("Synthesis: {synth} for {audio} of audio, RTF {rtf:.2f}", synth=fmt_duration(events.synth),
                        audio=fmt_duration(events.audio), rtf=events.synth / events.audio))


def _version(value: bool):
    if value:
        console.print(f"folivox {__version__}")
        raise typer.Exit()


def _resolve_voice(voice: str, voice_text: str | None, book_lang: str = "ru") -> tuple[Path, str | None, str]:
    """Catalog id or path → (audio file, transcript, sample language or "")."""
    from folivox import voices as catalog

    entry = catalog.find(voice) if voice else catalog.default_for(book_lang)
    if entry is not None:
        return entry.path, voice_text or entry.transcript, entry.lang
    path = Path(voice).expanduser()
    if not path.exists():
        known = ", ".join(v.id for v in catalog.all_voices())
        console.print(f"[red]{_('Voice {v!r} not found.', v=voice)}[/] {_('Catalog: {ids}. Or give a WAV/FLAC path.', ids=known)}")  # noqa: E501
        raise typer.Exit(2)
    return path, voice_text, ""


voices_app = typer.Typer(help=_("Voice catalog"), no_args_is_help=False, invoke_without_command=True)
app.add_typer(voices_app, name="voices")


@voices_app.callback(help=_("List available voices."))
def voices_list(ctx: typer.Context,
                lang: str | None = typer.Option(None, "--lang", help=_("Only voices in this language"))):
    """List available voices."""
    if ctx.invoked_subcommand:
        return
    from folivox import voices as catalog

    t = Table(title=_("Voices"))
    for col in ("id", _("Name"), _("Sex"), _("Language"), _("Length"), _("License"), _("Where")):
        t.add_column(col)
    for v in catalog.all_voices():
        if lang and v.lang != lang:
            continue
        try:
            from folivox.tts.voice import audio_duration

            dur = _("{s:.1f} s", s=audio_duration(v.path))
        except Exception:  # noqa: BLE001
            dur = "?"
        star = " *" if v.id == catalog.DEFAULT_VOICE else ""
        t.add_row(v.id + star, v.name, {"f": _("f"), "m": _("m")}.get(v.gender, "—"), v.lang, dur, v.license or "—",
                  _("bundled") if v.bundled else _("mine"))
    console.print(t)
    console.print(f"[dim]{_('* default voice. Your voices: {path}', path=catalog.user_voices_dir())}[/]")


@voices_app.command("add", help=_("Add your own voice to the catalog (stays on this computer)."))
def voices_add(
    voice_id: str = typer.Argument(..., help=_("Id: latin letters, digits, - and _")),
    audio: Path = typer.Argument(..., help=_("WAV/FLAC/MP3 sample, 6–15 s")),
    text: str | None = typer.Option(None, "--text", help=_("Transcript (text or .txt); otherwise Whisper")),
    name: str = typer.Option("", "--name", help=_("Human-readable name")),
    gender: str = typer.Option("", "--gender", help="f | m"),
    lang: str = typer.Option("ru", "--lang", help=_("Language of the sample")),
    license: str = typer.Option("", "--license", help=_("License / origin of the sample")),
    force: bool = typer.Option(False, "--force", help=_("Overwrite an existing voice")),
):
    """Add your own voice to the catalog (stays on this computer)."""
    from folivox import voices as catalog
    from folivox.tts.voice import load_voice

    lang = _check_lang(lang)
    transcribe = None
    if not text and not audio.with_suffix(".txt").exists():
        from folivox.qa.asr import Transcriber

        transcribe = Transcriber(language=lang).transcribe_file
    v = load_voice(audio, text, transcribe=transcribe)
    for w in v.warnings:
        console.print(f"[yellow]⚠ {w}[/]")
    entry = catalog.add(voice_id, audio, v.transcript, name=name, gender=gender, lang=lang, license=license,
                        overwrite=force)
    console.print(f"[green]{_('Voice added:')}[/] {entry.id}: «{entry.transcript}»")


@voices_app.command("remove", help=_("Remove one of your voices from the catalog."))
def voices_remove(voice_id: str = typer.Argument(...)):
    """Remove one of your voices from the catalog."""
    from folivox import voices as catalog

    catalog.remove(voice_id)
    console.print(_("Removed {id}", id=voice_id))


@voices_app.command("design", help=_("Generate a reference voice with a voice generator, pick the best take "
                                     "by speech recognition."))
def voices_design(
    voice_id: str = typer.Argument(..., help=_("Id of the new voice")),
    describe: str = typer.Option("", "--describe", "-d", help=_("Voice description for a design generator, e.g. "
                                                                "\"calm native Russian female audiobook "
                                                                "narrator\"")),
    speaker: str = typer.Option("", "--speaker", help=_("Preset speaker for a preset generator")),
    lang: str = typer.Option("ru", "--lang", help=_("Language of the sample")),
    gender: str = typer.Option("", "--gender", help="f | m"),
    text: list[str] = typer.Option([], "--text", help=_("Text to read (repeatable); default: built-in safe texts")),
    takes: int = typer.Option(3, "--takes", help=_("Takes per text")),
    generator: str | None = typer.Option(None, "--generator", "-g", help=_("Voice generator provider"),
                                         show_default="qwen3-voicedesign"),
    keep: Path | None = typer.Option(None, "--keep", help=_("Folder to keep every take for listening")),
    add: bool = typer.Option(True, "--add/--no-add", help=_("Add the best take to the catalog")),
):
    """Generate a reference voice with a voice generator, pick the best take by speech recognition."""
    import tempfile

    from folivox import config
    from folivox import voices as catalog
    from folivox.qa.asr import Transcriber
    from folivox.voicegen import GENERATORS
    from folivox.voices.design import generate_takes, safe_texts, score_takes

    lang = _check_lang(lang)
    gen = GENERATORS.create(config.provider("voicegen", generator))
    if gen.mode == "design" and not describe:
        console.print(f"[red]{_('--describe is required for {g}', g=gen.name)}[/]")
        raise typer.Exit(2)
    if gen.mode == "preset" and not speaker:
        console.print(f"[red]{_('--speaker is required for {g}: {s}', g=gen.name, s=', '.join(gen.speakers()))}[/]")
        raise typer.Exit(2)
    texts = text or safe_texts(lang)
    if not texts:
        console.print(f"[red]{_('No built-in texts for {lang}; pass --text', lang=lang)}[/]")
        raise typer.Exit(2)
    out_dir = keep or Path(tempfile.mkdtemp(prefix="folivox-design-"))
    total = len(texts) * takes
    done = [0]

    def progress(job, seconds):
        done[0] += 1
        console.log(_("take {i}/{n} ({s:.0f} s)", i=done[0], n=total, s=seconds))

    console.log(_("Generating {n} takes with {g}…", n=total, g=gen.name))
    paths = generate_takes(gen, texts, lang, out_dir, description=describe, speaker=speaker, takes=takes,
                           prefix=voice_id, progress=progress)
    by_path = {p: texts[int(p.stem.split("_t")[-1].split("_")[0]) - 1] for p in paths}
    console.log(_("Checking takes with speech recognition…"))
    ranked = score_takes(paths, by_path, Transcriber(language=lang), lang)
    t = Table(title=voice_id)
    for col in ("#", _("File"), _("Length"), _("Score"), _("Recognised")):
        t.add_column(col)
    for i, c in enumerate(ranked, 1):
        t.add_row(str(i), c.path.name, _("{s:.1f} s", s=c.duration), "—" if c.score is None else f"{c.score:.3f}",
                  c.transcript[:60])
    console.print(t)
    best = ranked[0]
    if add:
        source = f"{gen.name}: {describe or speaker}"
        entry = catalog.add(voice_id, best.path, best.text, gender=gender, lang=lang, source=source,
                            license=gen.license, overwrite=True)
        console.print(f"[green]{_('Voice added:')}[/] {entry.id} ← {best.path.name}")
    if keep:
        console.print(_("All takes: {path}", path=out_dir))


@voices_app.command("sample-text", help=_("Pick passages from a book that are safe for a voice generator to "
                                          "read (by a text LLM)."))
def voices_sample_text(
    book_path: Path = typer.Argument(..., help=_("Book file")),
    n: int = typer.Option(3, "-n", help=_("How many passages")),
    lang: str | None = typer.Option(None, "--lang", help=_("Book language")),
    llm: str | None = typer.Option(None, "--llm", help=_("Text LLM provider"), show_default="ollama"),
    model: str | None = typer.Option(None, "--model", help=_("LLM model name")),
):
    """Pick passages from a book that are safe for a voice generator to read (by a text LLM)."""
    from folivox import config
    from folivox.llm import LLMS
    from folivox.voices.design import pick_book_texts

    book = _load(book_path, lang)
    text = "\n".join(b.text for ch in book.chapters() for b in ch.blocks)
    found = pick_book_texts(text, book.lang, LLMS.create(config.provider("llm", llm), model=model), n=n)
    for s in found:
        console.print(f"• {s}")
    if not found:
        console.print(f"[yellow]{_('Nothing suitable found.')}[/]")


@app.command(help=_("List pluggable backends: TTS, speech recognition, voice generators, text LLMs."))
def providers():
    """List pluggable backends: TTS, speech recognition, voice generators, text LLMs."""
    from folivox import config
    from folivox.llm import LLMS
    from folivox.qa.asr import ASR_PROVIDERS
    from folivox.tts import ENGINES
    from folivox.voicegen import GENERATORS

    t = Table(title=_("Providers"))
    for col in (_("Kind"), _("Name"), _("Description"), _("Runs"), _("Needs")):
        t.add_column(col)
    for reg in (ENGINES, ASR_PROVIDERS, GENERATORS, LLMS):
        current = config.provider(reg.kind) or reg.default
        for p in reg.providers():
            mark = " *" if p.name == current else ""
            t.add_row(reg.kind, p.name + mark, p.description, _("locally") if p.local else _("cloud API (your key)"),
                      p.needs)
    console.print(t)
    console.print(f"[dim]{_('* selected. Config: {path}', path=config.config_path())}[/]")


@app.callback()
def _root(version: bool | None = typer.Option(None, "--version", callback=_version, is_eager=True,
                                                 help=_("Show the version"))):
    pass


def main():
    # `folivox book.fb2 ...` is shorthand for `folivox render book.fb2 ...`
    args = sys.argv[1:]
    if args and args[0] not in COMMANDS and not args[0].startswith("-"):
        sys.argv.insert(1, "render")
    app()


if __name__ == "__main__":
    main()
