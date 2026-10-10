# Folivox

Turn an e-book into a chaptered audiobook — fully locally, with
[CosyVoice 3](https://github.com/FunAudioLLM/CosyVoice) zero-shot voice cloning.

```bash
folivox book.fb2 --voice me.wav -o book.m4b
```

- **Formats:** FB2 (also `.fb2.zip`), EPUB, DOCX, PDF (text layer, no OCR), TXT.
- **Output:** one `.m4b` with chapter markers, cover and metadata — or `--mp3` per chapter.
- **Languages:** Russian, English, German, French, Spanish, Italian, Chinese, Japanese, Korean
  (the CosyVoice 3 set). The book language comes from FB2/EPUB/DOCX metadata or is detected from
  the text; `--lang` overrides it.
- **Russian is the most polished:** numbers, dates, years, centuries, units and abbreviations are
  expanded with case/gender agreement; `ё` is restored with
  [ruaccent](https://github.com/Den4ikAI/ruaccent); dialogue dashes get natural pauses. Other
  languages start with basic normalisation (numbers via num2words, symbols, sentence splitting).
- **Pluggable:** TTS, speech recognition, reference-voice generation and the text LLM are
  providers behind small interfaces — swap them by name when better models appear.
- **Quality control:** every fragment is re-transcribed with Whisper (MLX on Apple Silicon,
  faster-whisper elsewhere); on mismatch it is re-synthesised and the best take is kept.
- **Resumable:** books take many hours. Every fragment is cached; interrupt at any time and run
  the same command again to continue. Editing the text re-synthesises only what changed.
- **Runs on** macOS (Apple Silicon: hybrid CPU + GPU), Windows and Linux (CUDA or CPU).

> Status: early development, private.

## Install

Requires Python 3.10–3.12 and [ffmpeg](https://ffmpeg.org/) (`brew install ffmpeg`,
`winget install ffmpeg`, `apt install ffmpeg`).

```bash
uv tool install "folivox[all]"   # or: pip install "folivox[all]"
```

On first run the CosyVoice 3 weights (~4.5 GB, plus ~2 GB for the default RL LLM) are downloaded
from Hugging Face into the user data directory. To use an existing copy set
`FOLIVOX_MODEL_DIR=/path/to/Fun-CosyVoice3-0.5B`.

For NVIDIA GPUs install a CUDA build of PyTorch 2.5 first
(<https://pytorch.org/get-started/locally/>).

## Usage

```bash
folivox inspect book.epub                     # chapter tree, size, estimated duration
folivox book.fb2 -v me.wav -o book.m4b        # render the whole book
folivox book.fb2 -v me.wav -c 1-2             # only chapters 1–2
folivox book.pdf -v me.wav --mp3 -o out/      # one mp3 per chapter
```

Run `folivox` with no arguments for a quick start, `folivox --help` / `folivox render --help` for
all options (grouped by purpose, with defaults and examples), and `folivox help <topic>` for
longer explanations (`voices`, `providers`, `config`, `languages`, `resuming`, `quality`).

`folivox render` options (the same groups as in `--help`):

| Group | Option | Default | |
|---|---|---|---|
| Input | `--lang` | from the book | `ru en de fr es it zh ja ko` |
| | `--chapters`, `-c` | all | `1-3,5` |
| | `--depth` | 2 | how deep to split the book into chapters |
| | `--preview N` | off | only the first N characters of each chapter (quick test) |
| Voice | `--voice`, `-v` | by book language | catalog id or a WAV/FLAC file |
| | `--voice-text` | `.txt` next to the sample, else Whisper | transcript of the voice sample |
| | `--speed` | 1.0 | speaking rate |
| Text | `--max-chars` | 400 | longest fragment sent to the model at once |
| | `--stress` | `yo` | `none`, `yo` (restore ё), `all` (acute stress marks, experimental) |
| Quality control | `--qa` / `--no-qa` | on | check each fragment with speech recognition (faster without) |
| | `--takes` | 3 | max takes per fragment when QA finds a mismatch |
| Providers | `--tts` | `cosyvoice3` | TTS provider (`folivox providers`) |
| | `--asr` | `auto` | speech recognition for QA: `mlx-whisper`, `faster-whisper`, `openai` |
| | `--llm` | `rl` | CosyVoice language-model weights: `rl` or `base` |
| | `--model-dir` | downloaded on first run | folder with CosyVoice 3 weights |
| Performance | `--device` | `auto` | `cpu`, `cuda`, `mps` |
| | `--threads` | PyTorch default | CPU threads |
| Output | `--output`, `-o` | `<book>.m4b` | output file (a folder with `--mp3`) |
| | `--mp3` | | one mp3 per chapter instead of an m4b |
| | `--bitrate` | `64k` | AAC/MP3 bitrate |
| | `--work-dir` | `<output>.folivox/` | cache and journal; delete it when done |
| | `--verbose` | | print every fragment |

### Web interface

```bash
uv tool install "folivox[all]"   # `all` includes the `ui` extra
folivox ui                       # http://127.0.0.1:8765, local only; the URL contains an access token
```

Pick a book, choose chapters and a voice (with audition), render a short preview, then the whole
book with live progress; stop and resume at any time. It uses the same pipeline, cache and config as
the CLI. See [docs/ui.md](docs/ui.md).

### Voices

```bash
folivox voices                                  # list voices (bundled + yours)
folivox book.fb2 --voice russlib                # pick a voice by id (default: russlib)
folivox voices add anna anna.wav --text anna.txt --gender f   # add your own (stays on this machine)
```

Without `--voice` Folivox picks a catalog voice in the book's language. Bundled voices are public
domain, CC0 or generated by an Apache-2.0 model; `folivox voices` shows each voice's source and
license.

#### Designing a voice

No good recording? Let a voice-design model read a few short, easy texts and use the best take
as the cloning prompt:

```bash
folivox voices design anna --lang ru --gender f \
  --describe "calm, warm female voice of a native Russian speaker, audiobook narrator, studio" \
  --keep takes/          # keep every take to listen to
folivox voices sample-text book.fb2    # passages from the book that are easy to read aloud (LLM)
```

Each take is checked with Whisper; the best one becomes a user voice. CosyVoice copies everything
about the prompt — accent and rhythm included — so listen to the *cloned* narration, not just the
take. Describe the speaker as a **native** speaker of the language: preset voices of multilingual
models carry their own accent into other languages.

### The voice sample

Use 6–15 seconds of **clean** speech (no music, no noise, no reverb), WAV or FLAC, with an exact
transcript. The model copies everything about the sample — timbre, pace, microphone, room — so a
calm, evenly read sentence works best.

Steady background noise (hiss, hum, a fan) can be reduced gently before the voice is added:
tick **Reduce background noise** in `folivox ui` (play the sample with and without it), or use
`folivox voices add … --denoise` (needs `pip install "folivox[denoise]"`; included in `folivox[all]`).
It is spectral gating with a noise profile from the quietest part of the recording, deliberately mild so the
voice does not get a metallic ring; it cannot fix a noisy room, re-record closer to the microphone for that.

**Clone only your own voice or a voice you have explicit permission to use.** Imitating real
people without consent can be illegal and is harmful. Folivox ships no celebrity or third-party
voices.

### Providers and configuration

```bash
folivox providers        # what is available and selected
```

| Kind | Local (default) | Optional |
|---|---|---|
| `tts` | `cosyvoice3` | — |
| `asr` | `auto` (mlx-whisper / faster-whisper) | `openai` (any OpenAI-compatible transcription API) |
| `voicegen` | `qwen3-voicedesign`, `qwen3-customvoice` | `openai` |
| `llm` | `ollama` | `openai` (OpenAI, OpenRouter, llama.cpp server… any OpenAI-compatible API) |

Choose with CLI options, `FOLIVOX_TTS` / `FOLIVOX_ASR` / `FOLIVOX_VOICEGEN` / `FOLIVOX_LLM`, or a
`config.toml` in the user config directory (`$FOLIVOX_CONFIG` overrides the path):

```toml
[providers]
llm = "ollama"

[llm.ollama]
model = "gemma4:31b-it-qat"

[voicegen.qwen3-voicedesign]
python = "~/qwen3tts/.venv/bin/python"   # a separate venv with `pip install qwen-tts`
model = "~/qwen3tts/models/VoiceDesign"   # Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign

[llm.openai]
base_url = "https://openrouter.ai/api/v1"
model = "some/model"
api_key_env = "OPENROUTER_API_KEY"
```

API keys are read from environment variables, or from your **OS keychain** when you save them in
the web interface (`folivox ui` → Providers → API keys). The config file refuses `api_key` fields, so
keys never end up in a file you might share. Cloud providers run at your own cost, and your text
or audio leaves your computer.

> **Commercial voice output.** Some providers' terms restrict using their outputs to build
> competing models or services (for example the Gemini API Additional Terms). Using such audio as a
> cloning prompt is a grey zone; that decision and its consequences are yours. Folivox never
> bundles audio produced by commercial APIs.

Third-party packages can register providers through the `folivox.providers` entry-point group
(see [CONTRIBUTING.md](CONTRIBUTING.md)).

### Interface language

The command line interface is in English only.

## How it works

1. **Read** — a reader per format produces a common `Book` model: metadata, cover, nested sections,
   typed blocks (paragraph, epigraph, poem, quote…). Footnotes are skipped; PDF headers, footers and
   page numbers are removed and hyphenation is undone.
2. **Normalise** — a language module turns numbers and abbreviations into words (and restores ё
   for Russian), splits sentences ([razdel](https://github.com/natasha/razdel) for Russian, a
   punctuation splitter elsewhere, including `。！？` for Chinese and Japanese) and packs them into
   fragments.
3. **Synthesise** — CosyVoice 3 clones the voice zero-shot. Each accepted take is stored in the
   work dir and recorded in an SQLite journal.
4. **Check** — Whisper transcribes the take; character error rate and speaking rate decide whether
   to retake.
5. **Assemble** — fragments are joined with structural pauses (sentence < paragraph < heading <
   chapter), loudness-normalised (EBU R128, −18 LUFS) and encoded to AAC in an `.m4b` with chapters.

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src tests
uv run python tests/fixtures/make_fixtures.py   # regenerate synthetic test books
```

Adding a language or a provider: see [CONTRIBUTING.md](CONTRIBUTING.md).

CI runs the unit tests (readers, text processing, journal, assembly) on macOS, Windows and Linux
without model inference.

## License

Apache-2.0. Folivox vendors a trimmed copy of the CosyVoice inference code (Apache-2.0) and parts of
Matcha-TTS and Whisper (MIT); see [`src/folivox/vendor/README.md`](src/folivox/vendor/README.md) and
[NOTICE](NOTICE). The CosyVoice 3 weights are Apache-2.0
([model card](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)) and are downloaded, not
redistributed.
