# Install and start

## Install (one command)

Without downloading anything first (the script fetches Folivox from GitHub, no git needed):

```bash
curl -fsSL https://raw.githubusercontent.com/vatavale/folivox/main/scripts/install.sh | bash
```

```powershell
irm https://raw.githubusercontent.com/vatavale/folivox/main/scripts/install.ps1 | iex
```

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

## Update

Run the same install command again (for example the `curl … | bash` or `irm … | iex` line, or
`bash scripts/install.sh` in an updated checkout). It always fetches the latest Folivox from GitHub and
reinstalls it; downloaded models, your voices, settings and unfinished renders are kept. Check the version with
`folivox --version`.

Options for the installer (environment variables, also for updates):

| Variable | Effect |
|---|---|
| `FOLIVOX_SOURCE` | Install from a folder, a git URL (`git+https://…@<tag or commit>`), an archive URL or a package name instead of the latest `main` |
| `FOLIVOX_NO_START=1` | Do not offer to start the studio at the end (it is offered only at an interactive terminal, never in CI or when input or output is redirected) |
| `FOLIVOX_SKIP_MODELS=1` | Do not download models now (they are downloaded on first use) |

For example, to install a specific commit or tag:

```bash
curl -fsSL https://raw.githubusercontent.com/vatavale/folivox/main/scripts/install.sh | FOLIVOX_SOURCE="git+https://github.com/vatavale/folivox@<tag>" bash
```

## Check and remove

```bash
folivox doctor                  # ffmpeg, hardware, models, free disk
folivox setup                   # download what is missing; safe to repeat
folivox uninstall               # step 1: delete the downloaded models (asks first; --dry-run only shows)
uv tool uninstall folivox       # step 2: remove the program itself
```

`folivox uninstall` removes only what Folivox created: the CosyVoice model and, if Folivox was the one that
downloaded it, the Whisper model (a Whisper model you already had for other programs stays). Your voices and settings
are kept unless you add `--everything`. It never touches your books, the `BOOK.folivox` work folders, finished
audiobooks, or a model folder you set yourself with `FOLIVOX_MODEL_DIR`.

The installer may also have installed `uv` and `ffmpeg`. Remove them only if you do not use them for anything else:
`uv self uninstall`; `winget uninstall Gyan.FFmpeg` (Windows) or `brew uninstall ffmpeg` (macOS).

For problems, see [support.md](support.md) (`folivox doctor --bundle`).

## Not verified yet

The scripts were written to run on macOS, Linux and Windows, but only the shell syntax and `folivox setup` were run on
macOS. The CUDA/CPU PyTorch index choice and the Windows script have not been run on real Windows or NVIDIA machines.
