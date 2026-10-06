"""Command line interface.

``folivox BOOK [options]`` renders an audiobook (the ``render`` command is implied);
``folivox inspect BOOK`` shows the chapter tree and estimates.
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
from folivox.book import CHARS_PER_SECOND, Book, Section

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich",
                  help="Folivox — локальная озвучка книг (FB2, EPUB, DOCX, PDF, TXT) в аудиокнигу m4b.")
console = Console()
COMMANDS = {"render", "inspect", "--help", "-h", "--version"}


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h} ч {m:02d} мин" if h else f"{m} мин {s:02d} с"


def num(n: int) -> str:
    return f"{n:,}".replace(",", "\u202f")


def _load(path: Path) -> Book:
    from folivox.readers import UnsupportedFormat, read_book

    if not path.exists():
        console.print(f"[red]Файл не найден:[/] {path}")
        raise typer.Exit(2)
    try:
        return read_book(path)
    except UnsupportedFormat as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(2) from None


@app.command()
def inspect(
    book_path: Path = typer.Argument(..., help="Файл книги", show_default=False),
    depth: int = typer.Option(2, "--depth", help="Глубина разбиения на главы (1 — только верхний уровень)"),
    text: bool = typer.Option(False, "--text", help="Показать начало текста каждой главы"),
):
    """Показать структуру книги, главы и оценку длительности аудио."""
    book = _load(book_path)
    meta = Table.grid(padding=(0, 2))
    meta.add_row("Название", book.title)
    meta.add_row("Автор", book.author or "—")
    meta.add_row("Формат", book.source_format.upper())
    if book.year:
        meta.add_row("Год", book.year)
    meta.add_row("Обложка", f"есть ({len(book.cover) // 1024} КБ)" if book.cover else "нет")
    words = sum(len(b.text.split()) for ch in book.chapters(depth) for b in ch.blocks)
    meta.add_row("Объём", f"{num(book.chars)} символов, {num(words)} слов")
    meta.add_row("Аудио (оценка)", f"≈ {fmt_duration(book.estimated_seconds)}")
    console.print(meta)
    console.print()

    tree = Tree(f"[bold]{book.title}[/]")

    def add(node, sec: Section):
        label = sec.title or "[dim](без названия)[/]"
        n = node.add(f"{label} [dim]· {num(sec.chars)} симв.[/]")
        for c in sec.children:
            add(n, c)

    for s in book.sections:
        add(tree, s)
    console.print(tree)
    console.print()

    chapters = book.chapters(depth)
    t = Table(title=f"Главы аудиокниги ({len(chapters)})", show_lines=False)
    t.add_column("#", justify="right")
    t.add_column("Глава")
    t.add_column("Символов", justify="right")
    t.add_column("≈ Время", justify="right")
    if text:
        t.add_column("Начало")
    for i, ch in enumerate(chapters, 1):
        row = [str(i), ch.title, num(ch.chars), fmt_duration(ch.chars / CHARS_PER_SECOND)]
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
                                 MofNCompleteColumn(), TextColumn("симв."), TimeElapsedColumn(), TextColumn("·"),
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
        console.log(f"Фрагментов: {num(total_chunks)}, осталось {num(pending_chunks)}; "
                    f"текст {num(total_chars)} симв. (готово {num(done_chars)})")
        if pending_chunks:
            self.progress.start()
            self.task = self.progress.add_task("Озвучка", total=total_chars, completed=done_chars, info="")

    def chunk_started(self, chunk):
        pass

    def chunk_done(self, chunk, take, attempts):
        self.audio += take.duration
        self.synth += take.synth_seconds
        if len(attempts) > 1:
            self.retakes += len(attempts) - 1
        rtf = self.synth / self.audio if self.audio else 0
        info = f"RTF {rtf:.2f} · аудио {fmt_duration(self.audio)}"
        if self.retakes:
            info += f" · перезаписей {self.retakes}"
        if self.task is not None:
            self.progress.update(self.task, advance=len(chunk.source), info=info)
        if self.verbose or (take.score is not None and len(attempts) > 1):
            sc = ", ".join("—" if a is None else f"{a:.2f}" for a in attempts)
            self.progress.console.log(f"[dim]гл.{chunk.chapter + 1} #{chunk.idx}[/] [{sc}] {chunk.text[:70]}")

    def chapter_built(self, index, title, duration):
        if self.task is not None and self.progress.live.is_started:
            self.progress.stop()
        console.log(f"[green]✓[/] {title} — {fmt_duration(duration)}")

    def close(self):
        if self.progress.live.is_started:
            self.progress.stop()


@app.command()
def render(
    book_path: Path = typer.Argument(..., help="Файл книги (FB2, EPUB, DOCX, PDF, TXT)", show_default=False),
    voice: Path = typer.Option(..., "--voice", "-v", envvar="FOLIVOX_VOICE",
                               help="Образец голоса: WAV/FLAC 6–15 с чистой речи"),
    voice_text: str | None = typer.Option(None, "--voice-text", envvar="FOLIVOX_VOICE_TEXT",
                                             help="Расшифровка образца (текст или .txt). "
                                                  "По умолчанию — .txt рядом с образцом или Whisper"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Итоговый .m4b (или папка для --mp3)"),
    chapters: str | None = typer.Option(None, "--chapters", "-c", help="Какие главы: 1-3,5"),
    preview: int | None = typer.Option(None, "--preview", help="Только первые N символов каждой главы (проба)"),
    mp3: bool = typer.Option(False, "--mp3", help="MP3 по главам вместо одного m4b"),
    work_dir: Path | None = typer.Option(None, "--work-dir", help="Папка кэша (по умолчанию <output>.folivox)"),
    depth: int = typer.Option(2, "--depth", help="Глубина разбиения на главы"),
    max_chars: int = typer.Option(220, "--max-chars", help="Максимальная длина фрагмента для модели"),
    stress: str = typer.Option("yo", "--stress", help="none | yo (только ё) | all (ударения, эксперимент)"),
    speed: float = typer.Option(1.0, "--speed", help="Темп речи"),
    qa: bool = typer.Option(True, "--qa/--no-qa", help="Проверять каждый фрагмент через Whisper"),
    takes: int = typer.Option(3, "--takes", help="Максимум дублей на фрагмент при ошибке распознавания"),
    llm: str = typer.Option("rl", "--llm", help="Веса LLM: rl (меньше ошибок в тексте) | base"),
    device: str = typer.Option("auto", "--device", help="auto | cpu | cuda | mps"),
    threads: int | None = typer.Option(None, "--threads", help="Потоков CPU для PyTorch"),
    model_dir: Path | None = typer.Option(None, "--model-dir", envvar="FOLIVOX_MODEL_DIR",
                                             help="Папка с весами CosyVoice 3 (иначе скачаются)"),
    bitrate: str = typer.Option("64k", "--bitrate", help="Битрейт AAC"),
    verbose: bool = typer.Option(False, "--verbose", help="Печатать каждый фрагмент"),
):
    """Озвучить книгу в аудиокнигу (m4b с главами и обложкой)."""
    from folivox.pipeline import RenderOptions
    from folivox.pipeline import render as run_render
    from folivox.text.stress import MODES

    if stress not in MODES:
        console.print(f"[red]--stress: одно из {', '.join(MODES)}[/]")
        raise typer.Exit(2)
    book = _load(book_path)
    if output is None:
        output = book_path.with_suffix("" if mp3 else ".m4b")
    opts = RenderOptions(output=output, voice_wav=voice, voice_text=voice_text, work_dir=work_dir,
                         chapters=chapters, preview=preview, depth=depth, max_chars=max_chars, stress=stress,
                         speed=speed,
                         device=device, threads=threads, model_dir=str(model_dir) if model_dir else None, qa=qa,
                         max_takes=takes, mp3=mp3, bitrate=bitrate, llm=llm)
    console.print(f"[bold]{book.title}[/] — {book.author or 'автор неизвестен'}; "
                  f"оценка аудио ≈ {fmt_duration(book.estimated_seconds)}")
    events = RichEvents(verbose)
    t0 = time.time()
    try:
        result = run_render(book, opts, events)
    except KeyboardInterrupt:
        events.close()
        console.print("\n[yellow]Остановлено. Прогресс сохранён — запустите ту же команду, чтобы продолжить.[/]")
        raise typer.Exit(130) from None
    except Exception as e:  # noqa: BLE001
        events.close()
        from folivox.tts.voice import VoiceError

        if isinstance(e, (VoiceError, ValueError, FileNotFoundError, RuntimeError)):
            console.print(f"[red]Ошибка:[/] {e}")
            raise typer.Exit(1) from None
        raise
    events.close()
    console.print(f"[bold green]Готово:[/] {result}  (за {fmt_duration(time.time() - t0)})")
    if events.audio:
        console.print(f"Синтез: {fmt_duration(events.synth)} на {fmt_duration(events.audio)} аудио, "
                      f"RTF {events.synth / events.audio:.2f}")


def _version(value: bool):
    if value:
        console.print(f"folivox {__version__}")
        raise typer.Exit()


@app.callback()
def _root(version: bool | None = typer.Option(None, "--version", callback=_version, is_eager=True,
                                                 help="Показать версию")):
    pass


def main():
    # `folivox book.fb2 ...` is shorthand for `folivox render book.fb2 ...`
    args = sys.argv[1:]
    if args and args[0] not in COMMANDS and not args[0].startswith("-"):
        sys.argv.insert(1, "render")
    app()


if __name__ == "__main__":
    main()
