# Folivox

Turn an e-book into a chaptered audiobook — fully locally, with
[CosyVoice 3](https://github.com/FunAudioLLM/CosyVoice) zero-shot voice cloning.

```bash
folivox book.fb2 --voice me.wav -o book.m4b
```

- **Formats:** FB2 (also `.fb2.zip`), EPUB, DOCX, PDF (text layer, no OCR), TXT.
- **Output:** one `.m4b` with chapter markers, cover and metadata — or `--mp3` per chapter.
- **Russian first:** numbers, dates, years, centuries, units and abbreviations are expanded with
  case/gender agreement; `ё` is restored with [ruaccent](https://github.com/Den4ikAI/ruaccent);
  dialogue dashes are handled so replies and attributions get natural pauses.
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

Useful options (`folivox render --help` for all):

| Option | Default | |
|---|---|---|
| `--voice-text` | `.txt` next to the sample, else Whisper | transcript of the voice sample |
| `--chapters` | all | `1-3,5` |
| `--max-chars` | 400 | longest fragment sent to the model at once |
| `--stress` | `yo` | `none`, `yo` (restore ё), `all` (acute stress marks, experimental) |
| `--llm` | `rl` | `rl` or `base` CosyVoice 3 LLM weights |
| `--takes` | 3 | max takes per fragment when Whisper finds a mismatch |
| `--no-qa` | | skip the Whisper check (faster, no retakes) |
| `--device` | `auto` | `cuda`, `mps`, `cpu` |
| `--work-dir` | `<output>.folivox/` | cache and journal; delete it when done |

### Voices

```bash
folivox voices                                  # list voices (bundled + yours)
folivox book.fb2 --voice russlib                # pick a voice by id (default: russlib)
folivox voices add anna anna.wav --text anna.txt --gender f   # add your own (stays on this machine)
```

Bundled voices are public domain / CC0 only; `folivox voices` shows each voice's source and license.

### The voice sample

Use 6–15 seconds of **clean** speech (no music, no noise, no reverb), WAV or FLAC, with an exact
transcript. The model copies everything about the sample — timbre, pace, microphone, room — so a
calm, evenly read sentence works best.

**Clone only your own voice or a voice you have explicit permission to use.** Imitating real
people without consent can be illegal and is harmful. Folivox ships no celebrity or third-party
voices.

<!-- TODO: bundle a CC0 default voice (e.g. from Mozilla Common Voice) so it works out of the box. -->

## How it works

1. **Read** — a reader per format produces a common `Book` model: metadata, cover, nested sections,
   typed blocks (paragraph, epigraph, poem, quote…). Footnotes are skipped; PDF headers, footers and
   page numbers are removed and hyphenation is undone.
2. **Normalise** — numbers and abbreviations become words, ё is restored, text is split into
   sentences ([razdel](https://github.com/natasha/razdel)) and packed into fragments.
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

CI runs the unit tests (readers, text processing, journal, assembly) on macOS, Windows and Linux
without model inference.

## License

Apache-2.0. Folivox vendors a trimmed copy of the CosyVoice inference code (Apache-2.0) and parts of
Matcha-TTS and Whisper (MIT); see [`src/folivox/vendor/README.md`](src/folivox/vendor/README.md) and
[NOTICE](NOTICE). The CosyVoice 3 weights are Apache-2.0
([model card](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)) and are downloaded, not
redistributed.
