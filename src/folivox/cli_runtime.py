"""``folivox runtime``: the optional native C++ runtime (audio.cpp): status, install, remove."""

from __future__ import annotations

import os

import typer
from rich.console import Console

runtime_app = typer.Typer(help="Optional native C++ runtime (audio.cpp): status, install, remove.",
                          no_args_is_help=False, invoke_without_command=True, rich_markup_mode="rich",
                          context_settings={"help_option_names": ["-h", "--help"]})
console = Console()


def describe() -> list[str]:
    """Plain lines about the native runtime on this computer (used by `runtime`, `setup` and `doctor`)."""
    from folivox import config
    from folivox.tts import native_setup as ns

    st = ns.status(config.native_options()["weights"])
    cat = ns.load()
    out = [f"audio.cpp {cat.release} · this computer: {st.platform}"]
    if st.binary:
        out.append(f"engine for this computer: {st.binary.id} ({st.binary.backend}, {st.binary.size / 1e6:.0f} MB, "
                   f"{'checked' if st.binary.status == 'verified' else 'not yet checked on this platform'})")
        if st.binary.note:
            out.append(f"needs: {st.binary.note}")
    else:
        out.append("no prebuilt engine for this computer (own build: set FOLIVOX_NATIVE_SERVER and "
                   "FOLIVOX_NATIVE_MODEL)")
    out.append(f"engine installed: {st.server if st.server else 'no'}")
    if os.environ.get(ns.MODEL_ENV):
        out.append(f"model file: {os.environ[ns.MODEL_ENV]} (from {ns.MODEL_ENV})")
    else:
        out.append("model files: " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in st.weights.items()))
    out.append(f"`--runtime auto` uses it: {'yes' if st.auto else 'no (PyTorch)'}")
    return out


@runtime_app.callback(help="Show whether the native runtime is installed and what `--runtime auto` does here.")
def runtime_status(ctx: typer.Context):
    if ctx.invoked_subcommand:
        return
    from folivox import config

    console.print(f"Inference runtime now: [bold]{config.runtime()}[/] (set with --runtime, FOLIVOX_RUNTIME or "
                  "`\\[runtime] inference` in config.toml)", highlight=False)
    for line in describe():
        console.print(line, markup=False, highlight=False)
    console.print("Install: folivox runtime install   ·   use: folivox render BOOK --runtime native")


@runtime_app.command("install", help="Download the native engine and the CosyVoice 3 model (asks first).")
def runtime_install(
        weights: str = typer.Option("q8_0", "--weights", help="Model file: q8_0 (2.3 GB, converted to fp16 on "
                                    "load) or f32 (7 GB, the cleanest source for fp16)."),
        backend: str = typer.Option("auto", "--backend", help="auto, metal, cuda or vulkan."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    from folivox.cli import RichEvents
    from folivox.tts import native_setup as ns

    try:
        p = ns.plan(weights, backend)
    except ns.NativeError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1) from None
    if not p.lines:
        console.print("[green]✓[/] Already installed. See `folivox runtime`.")
        return
    console.print("This will download:")
    for line in p.lines:
        console.print(f"  • {line}", highlight=False)
    if p.binary and p.binary.status != "verified":
        console.print(f"[yellow]This build was not yet checked by the Folivox team on {ns.platform_tag()}.[/] "
                      "PyTorch stays the default; use `--runtime native` to try it and report how it went.")
    problem = ns.disk_problem(p.todo_bytes)
    if problem:
        console.print(f"[red]{problem}[/]")
        raise typer.Exit(1)
    if not yes and not typer.confirm(f"Download {p.todo_bytes / 1e9:.1f} GB now?", default=False):
        console.print("Cancelled, nothing was downloaded.")
        raise typer.Exit(1)
    events = RichEvents()
    try:
        ns.install(p, events.download, lambda m: console.print(m, markup=False, highlight=False))
    except (ns.NativeError, RuntimeError, OSError) as e:
        events.close()
        console.print(f"[red]Install stopped:[/] {e}\nRun the same command again to continue.")
        raise typer.Exit(1) from None
    events.close()
    console.print("[green]✓[/] Native runtime installed. Try it: folivox render BOOK --runtime native --preview 400")


@runtime_app.command("remove", help="Delete the downloaded native engine and model (PyTorch files are not touched).")
def runtime_remove(yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation.")):
    from folivox.tts import native_setup as ns

    if not yes and not typer.confirm("Delete the native engine and model files?", default=False):
        raise typer.Exit(1)
    from folivox.tts import native

    native.shutdown_all()
    console.print(f"Freed {ns.remove() / 1e9:.1f} GB.")
