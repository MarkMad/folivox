# Install and start

## Install (one command)

macOS and Linux, from a checkout of this repository:

```bash
./scripts/install.sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The script, step by step: installs `uv` (for your user, no administrator rights) if missing, checks ffmpeg (installs it
with Homebrew/winget when it can, otherwise tells you the exact command), looks at your hardware to pick the right
PyTorch build (NVIDIA GPU, Apple Silicon, or the smaller CPU build), installs Folivox, then runs `folivox setup`: it
shows your computer (cores, RAM, GPU) with advice, downloads the models once (about 6 GB for the voice and 1.6 GB for the
quality check) with a progress bar, speed and time left, and prints how to start. It is safe to run again; an interrupted
download continues where it stopped.

Options (environment variables): `FOLIVOX_SOURCE` (a folder, a git URL or a package name instead of this checkout),
`FOLIVOX_SKIP_MODELS=1` (download the models later, on first use).

Nothing is started in the background and nothing starts by itself at login.

## Start it when you need it

1. Open a terminal: Terminal (macOS), PowerShell (Windows), any terminal (Linux).
2. Type `folivox ui` and press Enter. The browser opens the studio; if it does not, open the address printed in the
   terminal.
3. Work in the studio. To stop, go back to the terminal and press `Ctrl+C`. Closing the terminal also stops it.

Without a browser: `folivox render book.fb2` (the audiobook appears next to the book). If it is interrupted by a
crash, a closed lid or a power cut, run the same command again: it continues from the first unfinished fragment.

## If the command is not found

Open a new terminal window. If it still says `folivox: command not found`, run `uv tool update-shell`, then open a new
terminal again.

## Check, update, remove

```bash
folivox doctor                  # ffmpeg, hardware, models, free disk
folivox setup                   # download what is missing; safe to repeat
uv tool upgrade folivox         # update
uv tool uninstall folivox       # remove (downloaded models stay in the data folder; see `folivox doctor`)
```

For problems, see [support.md](support.md) (`folivox doctor --bundle`).

## Not verified yet

The scripts were written to run on macOS, Linux and Windows, but only the shell syntax and `folivox setup` were run on
macOS. The CUDA/CPU PyTorch index choice and the Windows script have not been run on real Windows or NVIDIA machines.
