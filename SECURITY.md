# Security and privacy

This page is written for anyone who wants to know, before installing, what Folivox does on their computer: you, your
IT department, or an assistant you asked to review the code. Every claim below can be checked in the source; file
names are given for that.

## In short

- Folivox runs on your computer. Your books are read, voiced and assembled locally.
- There is **no telemetry, no analytics, no account, no update check, no background service**. Nothing runs when you
  are not using it.
- It never asks for administrator rights.
- The only time text leaves the computer is when **you** choose a cloud voice engine and give it **your own** API key.
  The studio asks you to tick a box before such a render.

## What it connects to

| When | Where | What for |
|---|---|---|
| Install | `astral.sh` (the `uv` installer), `github.com` / `raw.githubusercontent.com` (Folivox itself), `pypi.org` and `files.pythonhosted.org` (Python packages), `download.pytorch.org` (PyTorch builds) | Installing the program |
| First run of the local voice | `huggingface.co`, repository `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` (`src/folivox/tts/weights.py`) | Voice model weights, about 4.5 GB |
| First use of the quality check | `huggingface.co`, Whisper `large-v3-turbo` (`src/folivox/qa/asr.py`) | Speech recognition model that checks each take |
| Only if you pick a cloud engine and set a key | OpenAI, Google Gemini, ElevenLabs, Cartesia (`src/folivox/voicegen/cloud_apis.py`, `src/folivox/tts/cloud.py`) | Speech synthesis; the text of the book goes to that provider |
| Only if you pick a cloud text helper | OpenRouter / OpenAI, or a local Ollama on `localhost:11434` (`src/folivox/llm.py`) | Writing voice descriptions; short snippets only |

There is no other network code. You can check: `grep -rnE "urlopen|huggingface_hub|requests|socket" src` (the
`vendor/` folder is third-party model code and makes no network calls of its own).

## What the web studio exposes

`folivox ui` is a local web page. It listens on `127.0.0.1` only (there is no option to listen on other
interfaces) and protects itself against other pages in your browser:

- an access token stored in a file readable only by you (`ui_token` in the data folder), traded for a
  `HttpOnly`, `SameSite=Strict` cookie;
- the `Host` header is checked, which stops DNS-rebinding attacks;
- uploaded file names are reduced to a bare name, so an upload cannot write outside its folder;
- the UI makes no requests to other sites and loads no external scripts, fonts or images.

## Your API keys

Keys typed into the studio are saved in the **operating system keychain** (macOS Keychain, Windows Credential Locker,
Secret Service on Linux), never in a file. The config file refuses keys: it only holds the *name* of an environment
variable. The studio shows a key only as a mask. Keys are removed from the log and from the support bundle.

## What it writes to disk

Only in your user folders (names from `platformdirs`):

- the data folder (`folivox`): downloaded voice model (unless you point `FOLIVOX_MODEL_DIR` at your own), the voice
  catalog, studio state, the access token;
- the config folder: `config.toml`, with provider choices only;
- the log folder: a rotating log, with keys and your home path removed;
- the Hugging Face cache (`~/.cache/huggingface`): Whisper;
- the audiobook goes where you tell it (default `~/Audiobooks`); a work folder with the journal of each render sits
  next to it.

`folivox uninstall` removes what Folivox itself created and nothing else (the Whisper model only if Folivox downloaded
it). It is described in [docs/install.md](docs/install.md).

## What it runs

- `ffmpeg` to build the audiobook.
- The file manager (`open -R`, `explorer`, `xdg-open`) for the "show in folder" button, with a fixed command line.
- Only if you configure Qwen3-TTS: the Python interpreter named in `FOLIVOX_QWEN_PYTHON`, running
  `src/folivox/voicegen/qwen_worker.py`. This is off by default.

The code uses no `eval`, `exec`, `pickle`, `shell=True` or `os.system`. Model weights are read with
`torch.load(weights_only=True)`.

## Things worth knowing

- **Model files are trusted input.** The voice model comes with a small YAML file that `hyperpyyaml` reads, and
  that format can construct Python objects. The weights are downloaded from the model authors' repository on
  Hugging Face, so you trust that repository the same way you trust the model itself.
- **Books are untrusted input.** FB2 is parsed with entities and network access switched off. EPUB, DOCX and PDF
  are read by `ebooklib`, `python-docx` and `PyMuPDF`; keep those up to date, as with any program that opens
  documents from the internet. Folivox does not limit the unpacked size of an archive, so a deliberately crafted
  book can use a lot of memory.
- **The installer is a script you pipe into a shell.** That is convenient and is the same trust decision as for
  `uv` and most developer tools. If you prefer, read `scripts/install.sh` / `scripts/install.ps1` first (under 100
  lines each), or install from a checkout.
- **Python packages are resolved at install time** within the version ranges in `pyproject.toml`. The `uv.lock` file in
  the repository records tested versions, but `uv tool install` does not use it.
- **Third-party code** lives in `src/folivox/vendor/` (CosyVoice, Matcha-TTS, a part of OpenAI Whisper), with the
  upstream commit and every change we made listed in `src/folivox/vendor/README.md`.
- **Voice samples** in the bundled catalog are public-domain LibriVox recordings; their sources are in
  `src/folivox/voices/catalog.json`.

## Reporting a problem

Open an issue on GitHub, or for something sensitive write to the address in the repository owner's profile.
Please include the version (`folivox --version`) and, if it helps, the output of `folivox doctor`, which is
redacted by design.
