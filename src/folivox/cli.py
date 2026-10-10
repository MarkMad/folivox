"""Command line interface.

``folivox BOOK [options]`` renders an audiobook (the ``render`` command is implied);
``folivox inspect BOOK`` shows the chapter tree and estimates; ``folivox voices`` manages voices;
``folivox providers`` lists the pluggable backends.
"""

from __future__ import annotations

import sys
import time
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from folivox import __version__
from folivox.book import Book, Section
from folivox.helptext import MAIN_EPILOG, QUICKSTART, RENDER_EPILOG, TOPICS

app = typer.Typer(add_completion=False, no_args_is_help=False, invoke_without_command=True,
                  rich_markup_mode="rich", epilog=MAIN_EPILOG, context_settings={"help_option_names": ["-h", "--help"]},
                  help="Turn e-books (FB2, EPUB, DOCX, PDF, TXT) into m4b audiobooks, locally.")
console = Console()
COMMANDS = {"render", "inspect", "voices", "providers", "help", "--help", "-h", "--version"}

# Option panels of `folivox render --help`
P_INPUT, P_VOICE, P_TEXT, P_QA = "Input", "Voice", "Text", "Quality control"
P_PROVIDERS, P_PERF, P_OUT = "Providers", "Performance", "Output"


class Stress(str, Enum):
    none = "none"
    yo = "yo"
    all = "all"


class LlmWeights(str, Enum):
    rl = "rl"
    base = "base"


class Device(str, Enum):
    auto = "auto"
    cpu = "cpu"
    cuda = "cuda"
    mps = "mps"


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min {s:02d} s"


def num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _load(path: Path, lang: str | None = None) -> Book:
    from folivox.readers import UnsupportedFormat, read_book

    if not path.exists():
        console.print(f"[red]File not found:[/] {path}")
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


@app.command(help="Show the book structure, chapters and estimated audio length.", rich_help_panel="Main commands",
             epilog="[bold]Example[/]\n\n  [cyan]folivox inspect book.epub --depth 1 --text[/]")
def inspect(
    book_path: Path = typer.Argument(..., help="Book file (FB2, EPUB, DOCX, PDF, TXT)."),
    depth: int = typer.Option(2, "--depth", help="How deep to split the book into chapters (1 = top level only)."),
    lang: str | None = typer.Option(None, "--lang", show_default="from book / detected",
                                    help="Book language: ru en de fr es it zh ja ko."),
    text: bool = typer.Option(False, "--text", help="Add a column with the beginning of every chapter."),
):
    """Show the book structure, chapters and estimated audio length."""
    book = _load(book_path, lang)
    meta = Table.grid(padding=(0, 2))
    meta.add_row("Title", book.title)
    meta.add_row("Author", book.author or "—")
    meta.add_row("Language", _lang_name(book.lang))
    meta.add_row("Format", book.source_format.upper())
    if book.year:
        meta.add_row("Year", book.year)
    meta.add_row("Cover", f"yes ({len(book.cover) // 1024} KB)" if book.cover else "no")
    words = sum(len(b.text.split()) for ch in book.chapters(depth) for b in ch.blocks)
    meta.add_row("Size", f"{num(book.chars)} characters, {num(words)} words")
    meta.add_row("Audio (estimate)", f"≈ {fmt_duration(book.estimated_seconds)}")
    console.print(meta)
    console.print()

    tree = Tree(f"[bold]{book.title}[/]")

    def add(node, sec: Section):
        label = sec.title or "[dim](untitled)[/]"
        n = node.add(f"{label} [dim]· {num(sec.chars)} chars[/]")
        for c in sec.children:
            add(n, c)

    for s in book.sections:
        add(tree, s)
    console.print(tree)
    console.print()

    chapters = book.chapters(depth)
    cps = book.chars / book.estimated_seconds if book.estimated_seconds else 14.0
    t = Table(title=f"Audiobook chapters ({len(chapters)})", show_lines=False)
    t.add_column("#", justify="right")
    t.add_column("Chapter")
    t.add_column("Characters", justify="right")
    t.add_column("≈ Time", justify="right")
    if text:
        t.add_column("Beginning")
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
                                 MofNCompleteColumn(), TextColumn("chars"), TimeElapsedColumn(), TextColumn("·"),
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
        console.log(f"Fragments: {num(total_chunks)}, left {num(pending_chunks)}; "
                    f"text {num(total_chars)} chars (done {num(done_chars)})")
        if pending_chunks:
            self.progress.start()
            self.task = self.progress.add_task("Rendering", total=total_chars, completed=done_chars, info="")

    def chunk_started(self, chunk):
        pass

    def chunk_done(self, chunk, take, attempts):
        self.audio += take.duration
        self.synth += take.synth_seconds
        if len(attempts) > 1:
            self.retakes += len(attempts) - 1
        rtf = self.synth / self.audio if self.audio else 0
        info = f"RTF {rtf:.2f} · audio {fmt_duration(self.audio)}"
        if self.retakes:
            info += f" · retakes {self.retakes}"
        if self.task is not None:
            self.progress.update(self.task, advance=len(chunk.source), info=info)
        if self.verbose or (take.score is not None and len(attempts) > 1):
            sc = ", ".join("—" if a is None else f"{a:.2f}" for a in attempts)
            self.progress.console.log(f"[dim]ch.{chunk.chapter + 1} #{chunk.idx}[/] [{sc}] {chunk.text[:70]}")

    def chapter_built(self, index, title, duration):
        if self.task is not None and self.progress.live.is_started:
            self.progress.stop()
        console.log(f"[green]✓[/] {title} — {fmt_duration(duration)}")

    def close(self):
        if self.progress.live.is_started:
            self.progress.stop()


@app.command(help="Render a book into an audiobook (m4b with chapters and cover).", epilog=RENDER_EPILOG,
             rich_help_panel="Main commands")
def render(
    book_path: Path = typer.Argument(..., help="Book file (FB2, EPUB, DOCX, PDF, TXT)."),
    lang: str | None = typer.Option(None, "--lang", rich_help_panel=P_INPUT, show_default="from book / detected",
                                    help="Book language: ru en de fr es it zh ja ko."),
    chapters: str | None = typer.Option(None, "--chapters", "-c", rich_help_panel=P_INPUT, show_default="all",
                                        help="Chapters to render, e.g. 1-3,5 (numbers from `folivox inspect`)."),
    depth: int = typer.Option(2, "--depth", rich_help_panel=P_INPUT,
                              help="How deep to split the book into chapters (1 = top level only)."),
    preview: int | None = typer.Option(None, "--preview", rich_help_panel=P_INPUT, show_default="off",
                                       help="Render only the first N characters of each chapter (quick test)."),
    voice: str = typer.Option("", "--voice", "-v", envvar="FOLIVOX_VOICE", rich_help_panel=P_VOICE,
                              show_default="by book language",
                              help="Catalog voice id (`folivox voices`) or a WAV/FLAC file of 6–15 s of clean speech."),
    voice_text: str | None = typer.Option(None, "--voice-text", envvar="FOLIVOX_VOICE_TEXT", rich_help_panel=P_VOICE,
                                          show_default=".txt next to sample, else Whisper",
                                          help="Transcript of the voice sample (text or a .txt file)."),
    speed: float = typer.Option(1.0, "--speed", rich_help_panel=P_VOICE, help="Speaking rate (0.9 = slower)."),
    max_chars: int = typer.Option(400, "--max-chars", rich_help_panel=P_TEXT,
                                  help="Longest fragment sent to the model at once."),
    stress: Stress = typer.Option(Stress.yo, "--stress", rich_help_panel=P_TEXT,
                                  help="Russian only: none | yo (restore ё) | all (stress marks, experimental)."),
    qa: bool = typer.Option(True, "--qa/--no-qa", rich_help_panel=P_QA, show_default=False,
                            help="Check every fragment with speech recognition and retake mismatches (on)."),
    takes: int = typer.Option(3, "--takes", rich_help_panel=P_QA,
                              help="Max takes per fragment when QA finds a mismatch."),
    tts: str | None = typer.Option(None, "--tts", rich_help_panel=P_PROVIDERS, show_default="cosyvoice3",
                                   help="Speech synthesis provider (`folivox providers`)."),
    asr: str | None = typer.Option(None, "--asr", rich_help_panel=P_PROVIDERS, show_default="auto",
                                   help="Speech recognition provider used by QA."),
    llm: LlmWeights = typer.Option(LlmWeights.rl, "--llm", rich_help_panel=P_PROVIDERS,
                                   help="CosyVoice language-model weights: rl (fewer text errors) or base."),
    model_dir: Path | None = typer.Option(None, "--model-dir", envvar="FOLIVOX_MODEL_DIR",
                                          rich_help_panel=P_PROVIDERS, show_default="downloaded on first run",
                                          help="Folder with CosyVoice 3 weights."),
    device: Device = typer.Option(Device.auto, "--device", rich_help_panel=P_PERF,
                                  help="Compute device for synthesis."),
    threads: int | None = typer.Option(None, "--threads", rich_help_panel=P_PERF, show_default="PyTorch default",
                                       help="CPU threads for PyTorch."),
    output: Path | None = typer.Option(None, "--output", "-o", rich_help_panel=P_OUT,
                                       show_default="<book>.m4b next to the book",
                                       help="Output .m4b file (a folder with --mp3)."),
    mp3: bool = typer.Option(False, "--mp3", rich_help_panel=P_OUT,
                             help="Write one MP3 per chapter instead of an m4b."),
    bitrate: str = typer.Option("64k", "--bitrate", rich_help_panel=P_OUT, help="AAC/MP3 bitrate."),
    work_dir: Path | None = typer.Option(None, "--work-dir", rich_help_panel=P_OUT, show_default="<output>.folivox",
                                         help="Cache and journal folder (makes runs resumable)."),
    verbose: bool = typer.Option(False, "--verbose", rich_help_panel=P_OUT, help="Print every fragment."),
):
    """Render a book into an audiobook (m4b with chapters and cover)."""
    from folivox import config
    from folivox.pipeline import RenderOptions
    from folivox.pipeline import render as run_render
    from folivox.providers import ProviderError
    book = _load(book_path, lang)
    voice_path, voice_text, voice_lang = _resolve_voice(voice, voice_text, book.lang)
    if voice_lang and voice_lang != book.lang:
        console.print(f"[yellow]⚠ The voice sample is in {_lang_name(voice_lang)}, the book in "
                      f"{_lang_name(book.lang)}: the accent may carry over.[/]")
    if output is None:
        output = book_path.with_suffix("" if mp3 else ".m4b")
    opts = RenderOptions(output=output, voice_wav=voice_path, voice_text=voice_text, work_dir=work_dir,
                         chapters=chapters, preview=preview, depth=depth, max_chars=max_chars, stress=stress.value,
                         lang=book.lang, speed=speed, device=device.value, threads=threads,
                         model_dir=str(model_dir) if model_dir else None, qa=qa, max_takes=takes, mp3=mp3,
                         bitrate=bitrate, llm=llm.value, tts=config.provider("tts", tts) or "cosyvoice3",
                         asr=config.provider("asr", asr) or "auto")
    console.print(f"[bold]{book.title}[/] — {book.author or 'unknown author'}; {_lang_name(book.lang)}; "
                  f"estimated audio ≈ {fmt_duration(book.estimated_seconds)}")
    events = RichEvents(verbose)
    t0 = time.time()
    try:
        result = run_render(book, opts, events)
    except KeyboardInterrupt:
        events.close()
        console.print("\n[yellow]Stopped. Progress is saved — run the same command again to continue.[/]")
        raise typer.Exit(130) from None
    except Exception as e:  # noqa: BLE001
        events.close()
        from folivox.tts.voice import VoiceError

        if isinstance(e, (VoiceError, ValueError, FileNotFoundError, RuntimeError, ProviderError)):
            console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1) from None
        raise
    events.close()
    console.print(f"[bold green]Done:[/] {result}  ({fmt_duration(time.time() - t0)})")
    if events.audio:
        console.print(f"Synthesis: {fmt_duration(events.synth)} for {fmt_duration(events.audio)} of audio, "
                      f"RTF {events.synth / events.audio:.2f}")


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
        console.print(f"[red]Voice {voice!r} not found.[/] Catalog: {known}. Or give a WAV/FLAC path.")
        raise typer.Exit(2)
    return path, voice_text, ""


voices_app = typer.Typer(help="Voice catalog: list, add, remove, design.", no_args_is_help=False,
                         invoke_without_command=True, rich_markup_mode="rich",
                         context_settings={"help_option_names": ["-h", "--help"]})
app.add_typer(voices_app, name="voices", rich_help_panel="Setup")


@voices_app.callback(help="List available voices.")
def voices_list(ctx: typer.Context,
                lang: str | None = typer.Option(None, "--lang", help="Only voices in this language (ru en de …).")):
    """List available voices."""
    if ctx.invoked_subcommand:
        return
    from folivox import voices as catalog

    t = Table(title="Voices")
    for col in ("id", "Name", "Sex", "Language", "Length", "License", "Where"):
        t.add_column(col)
    for v in catalog.all_voices():
        if lang and v.lang != lang:
            continue
        try:
            from folivox.tts.voice import audio_duration

            dur = f"{audio_duration(v.path):.1f} s"
        except Exception:  # noqa: BLE001
            dur = "?"
        star = " *" if v.id == catalog.DEFAULT_VOICE else ""
        t.add_row(v.id + star, v.name, {"f": "f", "m": "m"}.get(v.gender, "—"), v.lang, dur, v.license or "—",
                  "bundled" if v.bundled else "mine")
    console.print(t)
    console.print(f"[dim]* default voice. Your voices: {catalog.user_voices_dir()}[/]")


@voices_app.command("add", help="Add your own voice to the catalog (stays on this computer).")
def voices_add(
    voice_id: str = typer.Argument(..., help="Id: lowercase latin letters, digits, - and _."),
    audio: Path = typer.Argument(..., help="WAV/FLAC/MP3 sample, 6–15 s of clean speech."),
    text: str | None = typer.Option(None, "--text", help="Transcript of the sample (text or a .txt file).",
                                  show_default=".txt next to sample, else Whisper"),
    name: str = typer.Option("", "--name", help="Human-readable name."),
    gender: str = typer.Option("", "--gender", help="Speaker sex: f or m (informational)."),
    lang: str = typer.Option("ru", "--lang", help="Language of the sample (ru en de …)."),
    license: str = typer.Option("", "--license", help="License / origin of the sample."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing voice with the same id."),
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
    console.print(f"[green]Voice added:[/] {entry.id}: «{entry.transcript}»")


@voices_app.command("remove", help="Remove one of your voices from the catalog.")
def voices_remove(voice_id: str = typer.Argument(..., help="Id of one of your voices.")):
    """Remove one of your voices from the catalog."""
    from folivox import voices as catalog

    catalog.remove(voice_id)
    console.print(f"Removed {voice_id}")


@voices_app.command("design", help=("Generate a reference voice with a voice generator, pick the best take "
                                     "by speech recognition."))
def voices_design(
    voice_id: str = typer.Argument(..., help="Id of the new voice."),
    describe: str = typer.Option("", "--describe", "-d", help=("Voice description for a design generator, e.g. "
                                                                "\"calm native Russian female audiobook "
                                                                "narrator\"")),
    speaker: str = typer.Option("", "--speaker", help="Preset speaker name (for preset generators)."),
    lang: str = typer.Option("ru", "--lang", help="Language of the sample (ru en de …)."),
    gender: str = typer.Option("", "--gender", help="Speaker sex: f or m (informational)."),
    text: list[str] = typer.Option([], "--text", help="Text to read (repeatable).",
                                  show_default="built-in easy texts"),
    takes: int = typer.Option(3, "--takes", help="Takes generated per text; the best one is kept."),
    generator: str | None = typer.Option(None, "--generator", "-g",
                                         help="Voice generator provider (`folivox providers`).",
                                         show_default="qwen3-voicedesign"),
    keep: Path | None = typer.Option(None, "--keep", show_default="temporary",
                                 help="Folder to keep every take for listening."),
    add: bool = typer.Option(True, "--add/--no-add", help="Add the best take to the catalog."),
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
        console.print(f"[red]--describe is required for {gen.name}[/]")
        raise typer.Exit(2)
    if gen.mode == "preset" and not speaker:
        console.print(f"[red]--speaker is required for {gen.name}: {', '.join(gen.speakers())}[/]")
        raise typer.Exit(2)
    texts = text or safe_texts(lang)
    if not texts:
        console.print(f"[red]No built-in texts for {lang}; pass --text[/]")
        raise typer.Exit(2)
    out_dir = keep or Path(tempfile.mkdtemp(prefix="folivox-design-"))
    total = len(texts) * takes
    done = [0]

    def progress(job, seconds):
        done[0] += 1
        console.log(f"take {done[0]}/{total} ({seconds:.0f} s)")

    console.log(f"Generating {total} takes with {gen.name}…")
    paths = generate_takes(gen, texts, lang, out_dir, description=describe, speaker=speaker, takes=takes,
                           prefix=voice_id, progress=progress)
    by_path = {p: texts[int(p.stem.split("_t")[-1].split("_")[0]) - 1] for p in paths}
    console.log("Checking takes with speech recognition…")
    ranked = score_takes(paths, by_path, Transcriber(language=lang), lang)
    t = Table(title=voice_id)
    for col in ("#", "File", "Length", "Score", "Recognised"):
        t.add_column(col)
    for i, c in enumerate(ranked, 1):
        t.add_row(str(i), c.path.name, f"{c.duration:.1f} s", "—" if c.score is None else f"{c.score:.3f}",
                  c.transcript[:60])
    console.print(t)
    best = ranked[0]
    if add:
        source = f"{gen.name}: {describe or speaker}"
        entry = catalog.add(voice_id, best.path, best.text, gender=gender, lang=lang, source=source,
                            license=gen.license, overwrite=True)
        console.print(f"[green]Voice added:[/] {entry.id} ← {best.path.name}")
    if keep:
        console.print(f"All takes: {out_dir}")


@voices_app.command("sample-text", help=("Pick passages from a book that are safe for a voice generator to "
                                          "read (by a text LLM)."))
def voices_sample_text(
    book_path: Path = typer.Argument(..., help="Book file."),
    n: int = typer.Option(3, "-n", help="How many passages to pick."),
    lang: str | None = typer.Option(None, "--lang", help="Book language.", show_default="from book / detected"),
    llm: str | None = typer.Option(None, "--llm", show_default="ollama",
                                 help="Text LLM provider (`folivox providers`)."),
    model: str | None = typer.Option(None, "--model", show_default="from config",
                                   help="Model name for the LLM provider."),
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
        console.print("[yellow]Nothing suitable found.[/]")


@app.command(help="List pluggable backends: TTS, speech recognition, voice generators, text LLMs.",
             rich_help_panel="Setup")
def providers():
    """List pluggable backends: TTS, speech recognition, voice generators, text LLMs."""
    from folivox import config
    from folivox.llm import LLMS
    from folivox.qa.asr import ASR_PROVIDERS
    from folivox.tts import ENGINES
    from folivox.voicegen import GENERATORS

    t = Table(title="Providers")
    for col in ("Kind", "Name", "Description", "Runs", "Needs"):
        t.add_column(col)
    for reg in (ENGINES, ASR_PROVIDERS, GENERATORS, LLMS):
        current = config.provider(reg.kind) or reg.default
        for p in reg.providers():
            mark = " *" if p.name == current else ""
            t.add_row(reg.kind, p.name + mark, p.description, "locally" if p.local else "cloud API (your key)",
                      p.needs)
    console.print(t)
    console.print(f"[dim]* selected. Config: {config.config_path()}[/]")


@app.command("help", help="Explain a topic: voices, providers, config, languages, resuming, quality.",
             rich_help_panel="Help")
def help_topic(topic: str | None = typer.Argument(None, help="Topic name; omit to list topics.", show_default=False)):
    """Explain a topic in more detail than --help can."""
    from rich.panel import Panel

    if topic is None or topic not in TOPICS:
        if topic:
            console.print(f"[red]Unknown topic {topic!r}.[/]")
        t = Table(box=None, show_header=False, padding=(0, 2))
        for name, (title, _body) in TOPICS.items():
            t.add_row(f"[cyan]folivox help {name}[/]", title)
        console.print(t)
        raise typer.Exit(2 if topic else 0)
    title, body = TOPICS[topic]
    console.print(Panel(body, title=f"[bold]{title}[/]", title_align="left", padding=(1, 2)))


@app.callback()
def _root(ctx: typer.Context,
          version: bool | None = typer.Option(None, "--version", callback=_version, is_eager=True,
                                              help="Show the version and exit.")):
    if ctx.invoked_subcommand is not None:
        return
    from rich.panel import Panel

    console.print(f"[bold]Folivox[/] {__version__} — local audiobooks from e-books\n")
    console.print(Panel(QUICKSTART, title="Quick start", title_align="left", padding=(1, 2)))
    t = Table(box=None, show_header=False, padding=(0, 2), title="Commands", title_justify="left")
    rows = [("folivox BOOK [options]", "render a book (short for `render`)"),
            ("folivox inspect BOOK", "chapters, size, estimated duration"),
            ("folivox voices", "list, add, design voices"),
            ("folivox providers", "TTS / ASR / LLM backends and config"),
            ("folivox help [topic]", "voices · providers · config · languages · resuming · quality")]
    for cmd, desc in rows:
        t.add_row(f"[cyan]{cmd}[/]", desc)
    console.print(t)
    console.print("\n[dim]All options: `folivox render --help`[/]")


def main():
    # `folivox book.fb2 ...` is shorthand for `folivox render book.fb2 ...`
    args = sys.argv[1:]
    if args and args[0] not in COMMANDS and not args[0].startswith("-"):
        sys.argv.insert(1, "render")
    app()


if __name__ == "__main__":
    main()
