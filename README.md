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
| Book details | `--title` `--author` `--narrator` `--series` `--series-number` `--year` `--description` | from the book | what the player shows; the series is written as the Grouping tag |
| | `--cover` | the book's own | an image (JPEG, PNG, WebP) to embed instead, or `none`; shrunk to 1600 px |
| | `--work-dir` | `<output>.folivox/` | cache and journal; delete it when done |
| | `--verbose` | | print every fragment |

### Web interface

```bash
uv tool install "folivox[all]"   # `all` includes the `ui` extra
folivox ui                       # http://127.0.0.1:8765, local only; open the printed link once (access token → cookie), then bookmark http://127.0.0.1:8765/
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

#### Cloud voice generation

A third source of voices, besides uploaded and recorded samples: let a cloud TTS provider read a
short text, listen to the takes (ranked by Whisper), keep the best one as your cloning prompt.

| Provider (`-g`) | Modes (`--mode`) | Models (`--model`, default `auto` = newest the provider lists) | API key variable |
|---|---|---|---|
| `gemini` | `preset` (30 voices + narration style), `design` (voice from a description; made for the run, then deleted) | `gemini-3.8-flash-tts`, `-flash-lite-tts`, 3.1 preview, 2.5 | `GEMINI_API_KEY` |
| `openai` | `preset` (13 voices + style instructions on `gpt-*-tts`) | `gpt-4o-mini-tts`, `tts-1-hd`, `tts-1` | `OPENAI_API_KEY` |
| `elevenlabs` | `preset` (premade voices; `[style]` audio tags on v3/v4), `design` (3 previews per request, billed once) | `eleven_v4`, `eleven_v3`, `eleven_multilingual_v2`, `eleven_flash_v2_5` (design: `eleven_ttv_v3`) | `ELEVENLABS_API_KEY` |
| `cartesia` | `preset`, `localize` (same voice with the native accent of the language), `clone` (one of your own voices) | `sonic-3.6`, `sonic-3.5`, `sonic-3`, `sonic-latest` | `CARTESIA_API_KEY` |

Texts here are a few hundred characters, so use the best model: with `auto` Folivox asks the provider
which models your key can use and takes the newest one (new releases are picked up without a Folivox
update); pin a model with `--model`, in the UI model list, or `[voicegen.gemini] model = "…"` in
`config.toml`. Temporary voices (Gemini design, Cartesia localize/clone) are deleted from your account
when the takes are made. Free-plan accounts may lack some of this (ElevenLabs library voices, Cartesia cloning).

```bash
export GEMINI_API_KEY=…                                    # or save it in `folivox ui`
folivox voices speakers -g gemini                          # preset voices
folivox voices design narrator -g gemini --speaker Kore --lang en --describe "calm audiobook narrator" --keep takes/
folivox voices design narrator -g gemini --mode design --lang ru --describe "calm woman in her forties, warm low voice"
folivox voices design narrator -g cartesia --mode localize --speaker <voice-id> --lang ru   # `voices speakers -g cartesia`
folivox voices suggest-prompt book.fb2 -g elevenlabs       # a design prompt from the book (text LLM)
folivox voices design narrator -g elevenlabs --lang en \
  --describe "calm, warm woman in her forties, low timbre, unhurried pace" --yes
```

In `folivox ui`: voice gallery → **Generate a voice sample**. Pick a provider (the key is requested
there if missing and stored in the OS keychain, never sent back to the browser), describe a voice
(**Suggest** asks your text LLM to write the prompt from the book) or pick a preset voice (with an optional narration style), choose the model, choose
the text (a built-in calm English sample, passages from the book, or your own), see the number of
characters and an approximate price, generate 3 takes, audition, name and add. Generation can be
stopped at any time.

The default text is a short English sample; for another language pick the language and a text in
it. Preset voices of multilingual providers carry their accent into other languages.

The estimates are approximate and based on public price lists seen in October 2026; check your
provider's dashboard. **Your text is sent to the provider and billed to your account.** Generated
voices are stored with the provider in `source`, the license note and a `commercial: true` flag
(shown as *commercial API* in the gallery); keep them for personal use. Providers' terms differ
(for example Gemini's and Cartesia's forbid using output to develop competing models, ElevenLabs'
free plan is non-commercial); read them before you publish audiobooks. They are never added to
the bundled catalog, and Folivox has no feature for imitating real people.

### Cloud reading engines

Besides the local CosyVoice 3 model, the whole book can be read by a paid online service. **The book
text is sent to the provider and billed to your account** — a full audiobook (≈ 10 h, 500,000 characters)
costs roughly $8–40 depending on the provider. Folivox therefore shows an estimate first and asks you to
confirm (checkbox in the studio, a question or `--yes` in the CLI), and `--max-cost` stops a run cleanly
at a spending cap (progress is saved; raise the cap and run the same command to continue — fragments already
rendered are never paid for twice).

| Engine (`--tts`) | Voice quality / languages | ≈ price per hour of audio¹ | Request limit | Notes and terms |
|---|---|---|---|---|
| `elevenlabs` | most natural; 90+ languages (v4), 29 (multilingual v2) | $4.0 (v4, v3, multilingual v2), $2.0 (flash) | 10,000 chars (v3: 5,000) | Free plan: personal, non-commercial only; selling audiobooks needs a paid plan. Audio tags (`[calm]`) on v3/v4. |
| `cartesia` | clean, fast; 40+ languages | $2.5 (Pro plan credits) | 5,000 chars | Commercial use needs a paid plan; output must not train competing models. Voice cloning from your own recording. |
| `openai` | good, simple; 13 voices, style note on `gpt-4o-mini-tts` | $0.9 (`gpt-4o-mini-tts`), $0.8 (`tts-1`), $1.5 (`tts-1-hd`) | 4,096 chars | Cheapest. Disclose that the voice is AI-generated (OpenAI usage policy). |
| `gemini` | natural; 30 voices, style note, voice from a description | $0.8 (`gemini-3.8-flash-tts`) | 4,000 chars | Free tier exists, but Google may then use your text; paid tier does not. Output must not train competing models. |

¹ List prices seen in October 2026 at 14 characters per second of speech; approximate, check your dashboard.
The cloud voices are not clones of a reference recording: pick one of the provider's voices (with sex and
traits, as in the voice gallery), or have a voice made for the book: Gemini and ElevenLabs *design* (from a description) and
Cartesia *localize* (take any voice, e.g. an English one, and adapt it to the book's language with a native accent — the default for non-English books) / *clone* (your own voice only, with a confirmation). Such a voice lives in your account
for the whole run, so every fragment sounds the same. Tick *Keep this voice* in the studio (CLI: `--keep-voice
--tts-voice-name "Calm narrator"`) and it stays in your account and is listed under *My created voices* for
every later book (`--tts-voice "Calm narrator"`, `folivox tts-voices gemini`, delete with `--delete`); otherwise it
is deleted when the book is finished. A kept voice uses a slot of your provider plan.

```bash
export OPENAI_API_KEY=…                       # or save the key in `folivox ui`; keys: GEMINI/OPENAI/ELEVENLABS/CARTESIA_API_KEY
folivox tts-voices openai                     # voices with sex and traits (Cartesia/ElevenLabs: ids and names)
folivox render book.epub --tts openai --tts-voice coral --preview 600            # first step: ~1 minute for a few cents
folivox render book.epub --tts elevenlabs --tts-voice Rachel --tts-model auto --max-cost 10 --yes
folivox render book.epub --tts gemini --tts-mode design --tts-describe "calm warm woman, unhurried" --tts-style "audiobook narration"
folivox render book.epub --tts cartesia --tts-mode clone --voice my-voice --own-voice   # my-voice = your own catalog voice
```

Quality control still works (Whisper QA with retakes), but every retake is billed, so cloud runs default to
2 takes (`--takes`) and never re-split a failed fragment; the estimate includes a retake allowance. Fragments
are limited to the provider's request size and sent in a few parallel requests (Retry-After is honoured).
Reading speed (`--speed`) and Russian stress marks (`--stress all`) do not apply; the narration style is
`--tts-style` (OpenAI and Gemini get a neutral audiobook note by default). Audio from commercial APIs is
yours to keep under the provider's terms and is never bundled with Folivox.

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
| `voicegen` | `qwen3-voicedesign`, `qwen3-customvoice` | `gemini`, `openai`, `elevenlabs`, `cartesia` |
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
