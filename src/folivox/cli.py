"""Command line interface.

``folivox BOOK [options]`` renders an audiobook (the ``render`` command is implied);
``folivox inspect BOOK`` shows the chapter tree and estimates.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from folivox import __version__
from folivox.book import CHARS_PER_SECOND, Book, Section

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich",
                  help="Folivox — локальная озвучка книг (FB2, EPUB, DOCX, PDF, TXT) в аудиокнигу m4b.")
console = Console()
COMMANDS = {"render", "inspect", "voices", "--help", "-h", "--version"}


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


def _version(value: bool):
    if value:
        console.print(f"folivox {__version__}")
        raise typer.Exit()


@app.callback()
def _root(version: Optional[bool] = typer.Option(None, "--version", callback=_version, is_eager=True,
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
