# Command line reference


```bash
folivox inspect book.epub                     # chapter tree, size, estimated duration
folivox book.fb2 -v me.wav -o book.m4b        # render the whole book
folivox book.fb2 -v me.wav -c 1-2             # only chapters 1–2
folivox book.pdf -v me.wav --mp3 -o out/      # one mp3 per chapter
```

Run `folivox` with no arguments for a quick start, `folivox --help` / `folivox render --help` for
all options (grouped by purpose, with defaults and examples), and `folivox help <topic>` for
longer explanations (`voices`, `providers`, `config`, `languages`, `resuming`, `quality`, `speed`).

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
| Text | `--max-chars` | 300 | longest fragment sent to the model at once |
| | `--stress` | `yo` | `none`, `yo` (restore ё), `all` (acute stress marks, experimental) |
| Quality control | `--qa` / `--no-qa` | on | check each fragment with speech recognition (faster without) |
| | `--takes` | 3 | max takes per fragment when QA finds a mismatch |
| Providers | `--tts` | best installed Fish engine you accepted, else `cosyvoice3` | TTS provider (`folivox providers`, `folivox engines`) |
| | `--tts-build` | `auto` | Fish engines: build id from `folivox engines` |
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

## Fish Audio engines

```bash
folivox engines                         # builds, size, memory, licence, fit here, install state
folivox engines licence BUILD           # the full licence text
folivox engines accept fish-community   # read and accept a licence (also asked by `install`)
folivox engines install BUILD           # download + verify (asks for the licence first)
folivox engines remove BUILD            # delete the downloaded weights
folivox engines best                    # id of the best tested build that fits this computer
folivox render book.epub --tts fish-drama3 --tts-build drama3-mlx-4bit --voice my-voice.wav
```

`--tts-build auto` (default) uses the best installed build that fits. Details, licences and memory:
[Fish Audio engines](fish-engines.md).

## Speed test

```bash
folivox bench                         # every device found: cpu, cuda, mps
folivox bench --devices cpu,cuda      # only these (cuda is tried even if `auto` would skip a small GPU)
folivox bench --lang en --voice me.wav --timeout 600
```

Synthesises one short fragment per device, each in its own process (a crash or an out-of-memory error ends only
that line) and prints characters per second, RTF (synthesis time / audio length; below 1 is faster than real
time), model load and warm-up time, and the peak GPU memory. Run it with the same voice and language on
different machines to compare them. Speech recognition (the QA step) is not measured. The studio and the
console also show the device and the current `chars/s` during a render.

## Interface language

The command line interface is in English only.
