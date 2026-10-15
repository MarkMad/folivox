"""``folivox markup``: speakers and expression tags for a book (export, import, check, assign voices)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

markup_app = typer.Typer(help="Speakers and expression tags: export, import, check, assign voices.",
                         no_args_is_help=True, rich_markup_mode="rich",
                         context_settings={"help_option_names": ["-h", "--help"]})
console = Console()


def _book_and_markup(book_path: Path, depth: int, file: Path | None, must_exist: bool = False):
    from folivox import cli
    from folivox import markup as mk

    book = cli._load(book_path)
    path = file or mk.path_for(book_path)
    if path.is_file():
        try:
            m = mk.Markup.load(path)
        except mk.MarkupError as e:
            console.print(f"[red]{e}[/]")
            raise typer.Exit(2) from None
    elif must_exist:
        console.print(f"[red]No markup yet:[/] {path}. Create one with `folivox markup import` (or in the studio).")
        raise typer.Exit(2)
    else:
        m = mk.Markup(depth=depth)
    return book, m, path


@markup_app.command("export", help="Write the markup (or an empty template) as text or JSON for editing.")
def markup_export(book_path: Path = typer.Argument(..., help="The book file."),
                  output: Path = typer.Option(None, "-o", "--output", help="Default: print to the screen."),
                  fmt: str = typer.Option("text", "--format", help="text | json"),
                  depth: int = typer.Option(2, "--depth", help="Chapter depth (as in render)."),
                  file: Path = typer.Option(None, "--markup", help="Markup file (default: <book>.markup.json).")):
    from folivox import markup as mk

    book, m, _ = _book_and_markup(book_path, depth, file)
    chapters = book.chapters(m.depth if m.chapters else depth)
    if fmt == "json":
        mk.stamp(m, chapters)
        body = json.dumps(m.to_dict(), ensure_ascii=False, indent=1) + "\n"
    elif fmt == "text":
        body = mk.export_text(m, chapters)
    else:
        console.print("[red]--format is text or json[/]")
        raise typer.Exit(2)
    if output:
        output.write_text(body, encoding="utf-8")
        console.print(f"Wrote {output}")
    else:
        print(body, end="")


@markup_app.command("import", help="Read an edited text or JSON file, check it against the book and save it.")
def markup_import(book_path: Path = typer.Argument(...), source: Path = typer.Argument(..., help="Text or JSON file."),
                  depth: int = typer.Option(2, "--depth"),
                  file: Path = typer.Option(None, "--markup", help="Where to save (default: <book>.markup.json).")):
    from folivox import markup as mk

    book = _book_and_markup(book_path, depth, file)[0]
    path = file or mk.path_for(book_path)
    raw = source.read_text(encoding="utf-8")
    try:
        if source.suffix.lower() == ".json" or raw.lstrip().startswith("{"):
            m = mk.Markup.from_dict(json.loads(raw))
            chapters = book.chapters(m.depth)
            m, problems = mk.bind(m, chapters)
            mk.stamp(m, chapters)
            for w in problems:
                console.print(f"[yellow]{w}[/]")
        else:
            m = mk.import_text(raw, book.chapters(depth), mk.Markup(depth=depth))
            m.depth = depth
    except (mk.MarkupError, json.JSONDecodeError) as e:
        console.print(f"[red]Not imported: {e}[/]")
        raise typer.Exit(1) from None
    m.save(path)
    spans = sum(len(c.spans) for c in m.chapters.values())
    marks = sum(len(c.marks) for c in m.chapters.values())
    console.print(f"Saved {path}: {len(m.speakers)} speakers, {spans} spans, {marks} inline tags.")
    odd = mk.unknown_tags(m)
    if odd:
        console.print(f"[yellow]Tags not in the tag list (kept; the models accept free-form tags):[/] "
                      f"{', '.join(sorted(odd))}")


@markup_app.command("speakers", help="List the speakers, their voices and how much each reads.")
def markup_speakers(book_path: Path = typer.Argument(...), depth: int = typer.Option(2, "--depth"),
                    file: Path = typer.Option(None, "--markup")):
    book, m, path = _book_and_markup(book_path, depth, file, must_exist=True)
    from folivox import voices as catalog

    chapters = book.chapters(m.depth)
    chars: dict[int, int] = {s.id: 0 for s in m.speakers}
    for c in m.chapters.values():
        for s in c.spans:
            chars[s.speaker] = chars.get(s.speaker, 0) + s.end - s.start
    t = Table(title=str(path))
    for col in ("Id", "Name", "Voice", "Characters", "Notes"):
        t.add_column(col)
    for s in m.speakers:
        voice = s.voice or "(main voice)"
        if s.voice and catalog.find(s.voice) is None and not Path(s.voice).expanduser().is_file():
            voice += " [red]not found[/]"
        n = chars.get(s.id, 0) if s.id else sum(len(b.text) for ch in chapters for b in ch.blocks) - sum(
            v for k, v in chars.items() if k)
        t.add_row(str(s.id), s.name, voice, str(max(n, 0)), s.notes)
    console.print(t)


@markup_app.command("speaker", help="Add or change a speaker: name, voice (catalog id or file), gender.")
def markup_speaker(book_path: Path = typer.Argument(...),
                   speaker_id: int = typer.Argument(..., help="0 = narrator, 1..15"),
                   name: str = typer.Option(None, "--name"),
                   voice: str = typer.Option(None, "--voice", help="Voice id or file; '' = the main voice"),
                   gender: str = typer.Option(None, "--gender", help="f | m"),
                   depth: int = typer.Option(2, "--depth"), file: Path = typer.Option(None, "--markup")):
    from folivox import markup as mk

    _book, m, path = _book_and_markup(book_path, depth, file)
    try:
        sp = m.ensure_speaker(speaker_id)
    except mk.MarkupError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(2) from None
    if name is not None:
        sp.name = name
    if voice is not None:
        sp.voice = voice
    if gender is not None:
        sp.gender = gender
    m.save(path)
    console.print(f"Saved {path}")


@markup_app.command("check", help="Check the markup against the book: stale chapters, bad spans, tags, voices.")
def markup_check(book_path: Path = typer.Argument(...), depth: int = typer.Option(2, "--depth"),
                 file: Path = typer.Option(None, "--markup")):
    from folivox import markup as mk
    from folivox import voices as catalog

    book, m, path = _book_and_markup(book_path, depth, file, must_exist=True)
    clean, problems = mk.bind(m, book.chapters(m.depth))
    bad = 0
    for w in problems:
        console.print(f"[yellow]{w}[/]")
        bad += 1
    for s in m.speakers:
        if s.voice and catalog.find(s.voice) is None and not Path(s.voice).expanduser().is_file():
            console.print(f"[red]Speaker {s.id} ({s.name}): voice {s.voice!r} not found[/]")
            bad += 1
    for sid in sorted(m.used_speakers() - {s.id for s in m.speakers}):
        console.print(f"[red]Speaker {sid} reads something but is not defined[/]")
        bad += 1
    odd = mk.unknown_tags(clean)
    if odd:
        console.print(f"[yellow]Tags not in the tag list:[/] {', '.join(sorted(odd))}")
    console.print(f"{path}: {len(clean.used_speakers())} speakers read; "
                  f"{'no problems' if not bad else f'{bad} problem(s)'}")
    if bad:
        raise typer.Exit(1)


@markup_app.command("tags", help="List the known expression tags (Fish Audio engines), by category.")
def markup_tags(category: str = typer.Option(None, "--category", help="emotion | tone | sound | effect | pause"),
                model: str = typer.Option(None, "--model", help="s2 | drama3")):
    from folivox import markup as mk

    db = mk.tag_database()
    t = Table(title="Expression tags: write them as [tag] where the effect should happen")
    for col in ("Tag", "Category", "Models"):
        t.add_column(col)
    for x in db["tags"]:
        if (category and x["category"] != category) or (model and model not in x["models"]):
            continue
        t.add_row(f"[{x['tag']}]".replace("[", "\\["), x["category"], ", ".join(x["models"]))
    console.print(t)
    console.print(db["syntax"]["placement"])


@markup_app.command("clear", help="Delete the markup file of the book.")
def markup_clear(book_path: Path = typer.Argument(...), file: Path = typer.Option(None, "--markup")):
    from folivox import markup as mk

    path = file or mk.path_for(book_path)
    if path.is_file():
        path.unlink()
        console.print(f"Deleted {path}")
