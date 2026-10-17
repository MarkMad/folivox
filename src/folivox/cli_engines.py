"""``folivox engines``: the optional Fish Audio engines (list, accept the licence, install, remove)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

engines_app = typer.Typer(help="Optional Fish Audio engines: list, accept the licence, install, remove.",
                          no_args_is_help=False, invoke_without_command=True, rich_markup_mode="rich",
                          context_settings={"help_option_names": ["-h", "--help"]})
console = Console()


def _build(build_id: str):
    from folivox.tts import builds

    try:
        return builds.load().build(build_id)
    except builds.CatalogError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(2) from None


@engines_app.callback(help="List the builds that can run on this computer, their licence and install state.")
def engines_list(ctx: typer.Context):
    """List catalog builds with fit, licence and install state."""
    if ctx.invoked_subcommand:
        return
    from folivox.tts import builds, licences

    hw = builds.detect_hardware()
    cat = builds.load()
    console.print(f"This computer: {hw.platform_tag}, {hw.total_gb:.0f} GB memory"
                  f"{f', {hw.available_gb:.0f} GB free now' if hw.available_gb is not None else ''}"
                  if hw.total_gb else f"This computer: {hw.platform_tag}")
    t = Table(title="Fish Audio builds (optional, downloaded from Hugging Face after you accept the licence)")
    for col in ("Id", "Size", "Peak memory", "Licence", "Tested", "Here", "State"):
        t.add_column(col, no_wrap=col in ("Id", "Size", "Peak memory", "Tested", "Here"))
    for b in sorted(cat.builds, key=lambda x: -x.rank):
        lic = cat.licences[b.licence]
        f = builds.fit(b, hw)
        here = {"ok": "[green]fits[/]", "tight": "[yellow]tight[/]", "no": "[red]no[/]"}[f.level]
        state = "[green]installed[/]" if builds.is_installed(b) else "not installed"
        if not licences.is_accepted(lic):
            state += ", licence not accepted"
        t.add_row(b.id, f"{b.size_gb:.1f} GB", f"{b.peak_gb:.0f} GB", lic.name,
                  ("yes" if b.status == "verified" else "[yellow]not yet[/]")
                  + (f", RTF {builds.measured_rtf(b):g}" if builds.measured_rtf(b) else ""), here, state)
    console.print(t)
    rec = builds.recommend(hw)
    console.print(f"Default engine now: [bold]{rec.engine if rec else 'cosyvoice3'}[/]"
                  + (f" ({rec.id})" if rec else " (no Fish build is installed with its licence accepted)"))
    console.print("Install: folivox engines install ID   ·   licence text: folivox engines licence ID   ·   "
                  "then:  folivox render BOOK --tts ENGINE --voice YOUR_VOICE.wav")


@engines_app.command("licence", help="Show the full licence text of a build (fetched from the official file).")
def engines_licence(build_id: str = typer.Argument(..., help="Build id from `folivox engines`.")):
    from folivox.tts import builds, licences

    lic = builds.load().licences[_build(build_id).licence]
    try:
        console.print(licences.fetch_text(lic), markup=False, highlight=False)
    except licences.LicenceError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1) from None


@engines_app.command("accept", help="Read and accept a licence (id: fish-research or fish-community).")
def engines_accept(licence_id: str = typer.Argument(...),
                   yes: bool = typer.Option(False, "--yes", help="Accept without the questions (you read it).")):
    from folivox.tts import builds, licences

    if licence_id not in builds.load().licences:
        console.print(f"[red]Unknown licence.[/] Known: {', '.join(builds.load().licences)}")
        raise typer.Exit(2)
    if not licences.prompt_accept(licence_id, assume_yes=yes, show=lambda m: console.print(m, markup=False)):
        console.print("Not accepted: the engine stays off.")
        raise typer.Exit(1)
    console.print("[green]Accepted and saved in config.toml.[/]")


@engines_app.command("revoke", help="Forget that you accepted a licence (the engine is off until you accept again).")
def engines_revoke(licence_id: str = typer.Argument(...)):
    from folivox.tts import licences

    licences.revoke(licence_id)
    console.print("Done.")


@engines_app.command("install", help="Download and verify a build (asks for the licence first).")
def engines_install(build_id: str = typer.Argument(..., help="Build id from `folivox engines`."),
                    accept_licence: bool = typer.Option(False, "--accept-licence",
                                                        help="Accept the licence of this build without the questions."),
                    yes: bool = typer.Option(False, "--yes", help="Do not ask for confirmation of the download.")):
    from folivox.tts import builds, fish_setup, licences, weights

    b = _build(build_id)
    cat = builds.load()
    hw = builds.detect_hardware()
    f = builds.fit(b, hw)
    if f.level == "no":
        console.print(f"[red]{f.message}[/]")
        raise typer.Exit(1)
    if f.level == "tight":
        console.print(f"[yellow]{f.message}[/]")
    if b.status != "verified":
        console.print(f"[yellow]{b.title} has not been run on the Folivox test fragment yet.[/]")
    if not licences.prompt_accept(b.licence, assume_yes=accept_licence, show=lambda m: console.print(m, markup=False)):
        console.print("Licence not accepted: nothing was downloaded.")
        raise typer.Exit(1)
    if not yes and not typer.confirm(f"Download {b.size_gb:.1f} GB from huggingface.co/{b.repo} "
                                     f"(revision {b.revision[:8]}) and install the engine environment?"):
        raise typer.Exit(1)

    def show(name: str, done: int, total: int) -> None:
        if total:
            console.print(f"\r  {name}: {done / 1e9:.1f} / {total / 1e9:.1f} GB", end="")

    try:
        with weights.reporting(show):
            fish_setup.install(b, show, log=lambda m: console.print(m, markup=False))
    except (fish_setup.InstallError, licences.LicenceError, RuntimeError, OSError) as e:  # network, disk
        console.print(f"\n[red]{e}[/]")
        raise typer.Exit(1) from None
    console.print(f"\n[green]Ready.[/] Use it:  folivox render BOOK --tts {b.engine} --tts-build {b.id} "
                  "--voice YOUR_VOICE.wav")
    console.print(f"Remember: {licences.ATTRIBUTION}. Licence: {cat.licences[b.licence].name}.")


@engines_app.command("remove", help="Delete the downloaded weights of a build.")
def engines_remove(build_id: str = typer.Argument(...)):
    from folivox.tts import fish_setup

    freed = fish_setup.remove(_build(build_id))
    console.print(f"Removed, {freed / 1e9:.1f} GB freed.")


@engines_app.command("best", help="Print the id of the best tested build that fits this computer (empty if none).")
def engines_best():
    from folivox.tts import builds

    best = builds.candidates()
    if best:
        print(best[0].id)
