# Contributing

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src tests
```

Unit tests must not need PyTorch or model weights: CI runs them on macOS, Windows and Linux
without the `tts` extra.

## CLI messages and help

The command line is English only: write plain English strings (f-strings) in `cli.py` and the
modules it calls. There is no message catalog and no locale detection. (`folivox.i18n._` is a
pass-through kept only until `folivox/voices` stops importing it; do not use it in new code.)

A new `folivox render` option needs a one-line `help=`, a `rich_help_panel=` (Input / Voice / Text /
Quality control / Providers / Performance / Output) and, when the default is not obvious,
`show_default="…"`; `tests/test_cli_help.py` checks this. Longer explanations live in
`src/folivox/helptext.py` (`folivox help <topic>`). Update the options table in the README.

## Adding or improving a language

Everything language-specific lives in one module, `src/folivox/lang/<code>.py` (ISO 639-1 code).
Copy the closest existing module (`en.py` for languages with spaces, `zh.py` / `ja.py` for
CJK) and adjust:

```python
from folivox.lang import LatinLanguage, register


class Portuguese(LatinLanguage):
    code, name, native = "pt", "Portuguese", "Português"
    chapter_label, intro_label = "Capítulo {n}", "Introdução"   # titles for untitled chapters
    part_words = ("parte", "livro")          # "Parte 2" in plain-text books → part heading
    chapter_words = ("capítulo",)            # "Capítulo 3" → chapter heading
    standalone_words = ("prólogo", "epílogo")
    abbreviations = ("sr", "sra", "dr")      # "Sr." does not end a sentence
    hallucinations = (r"legendas pela comunidade[^.!?]*[.!?]?",)  # Whisper junk at the end of audio

    def numbers(self, text):                 # optional: units, currencies, thousands separators…
        return super().numbers(text)


register(Portuguese())
```

What you can override (see `src/folivox/lang/base.py`):

| Method / attribute | Used for |
|---|---|
| `normalize(text)` | text sent to the TTS model: numbers, symbols, punctuation |
| `sentences(text)` | sentence splitting before fragments are packed |
| `dialogue(text)` | removing dialogue dashes the narrator does not read |
| `stress(text, mode)` | pronunciation hints (Russian ё / stress marks) |
| `canonical(text)` | comparison form for Whisper QA (character error rate) |
| `cps` | plausible narration speed, canonical characters per second |
| `chars_per_second` | duration estimate in `folivox inspect` |

Then:

1. add the code to `SUPPORTED` in `src/folivox/lang/__init__.py` (only languages the TTS model
   can speak) and stop-words to `src/folivox/lang/detect.py` if it uses the Latin script;
2. add a case to `CASES` in `tests/test_lang.py` (normalised sentences, a chapter heading);
3. add two or three calm "safe" texts to `src/folivox/voices/safe_texts.json` (frequent words,
   no names, numbers or dialogue) for `folivox voices design`;
4. ideally contribute a bundled voice in that language (see below).

## Adding a provider

Providers are registered in a `Registry` by name with a factory (`"module:attr"`, imported
lazily, so optional dependencies are only needed when the provider is used):

| Kind | Registry | Interface |
|---|---|---|
| TTS | `folivox.tts.ENGINES` | `folivox.tts.base.TTSEngine` (`prepare` / `finish` or `synthesize_audio`) |
| ASR | `folivox.qa.asr.ASR_PROVIDERS` | `folivox.qa.asr.ASR.transcribe(audio, sr)` |
| Voice generator | `folivox.voicegen.GENERATORS` | `folivox.voicegen.VoiceGenerator.generate(jobs)` |
| Text LLM | `folivox.llm.LLMS` | `folivox.llm.LLM.complete(prompt)` |

Factory keyword arguments come from the `[<kind>.<name>]` table of the user's `config.toml`. API
keys come from environment variables or the OS keychain (`folivox.config.api_key`), never from the config file. A separate package can
register providers through an entry point:

```toml
[project.entry-points."folivox.providers"]
my-tts = "my_package.folivox_plugin:register"
```

## Bundled voices

Only audio that may be redistributed: public domain, CC0, or output of an openly licensed model
(e.g. Qwen3-TTS, Apache-2.0). Never audio from commercial APIs, never a real person's voice
without their explicit consent. Add `<id>.flac` (mono, 24 kHz, 6–15 s, trimmed) and an entry with
`source`, `license` and `url` to `src/folivox/voices/catalog.json`.
