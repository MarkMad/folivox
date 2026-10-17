# Fish Audio engines (optional)

Besides CosyVoice 3, Folivox can read with two optional local engines from [Fish Audio](https://fish.audio):

| Engine | Builds | What it is |
|---|---|---|
| `fish-drama3` | `drama3-mlx-4bit` (23.8 GB download, up to ~33 GB of memory), `drama3-mlx-3bit` (19.8 GB, RTF 1.08 on the test fragment, about the same as 4-bit) | Fish Audio Drama 3: the most capable local engine, built for several speakers in one scene |
| `fish-s2` | `s2pro-mlx-8bit` (6.7 GB download, up to ~18 GB of memory) | Fish Audio S2 Pro: natural single-voice reading |

They are **not part of Folivox and are never shipped with it**. You download them from Hugging Face
after accepting the vendor's licence, into a private folder (`<user data>/folivox/engines/`). Each
engine runs in its own worker process with its own Python environment, so a crash or an
out-of-memory kill takes down only the worker and the memory goes back to the system as soon as the
render stops. Folivox does not import or bundle any Fish code.

```bash
folivox engines                       # builds, size, memory, licence, fit for this computer, install state
folivox engines licence drama3-mlx-4bit   # the full licence text (fetched from the official file)
folivox engines install drama3-mlx-4bit   # asks for the licence, downloads, verifies sha256
folivox render book.epub --tts fish-drama3 --voice my-voice.wav
folivox engines remove drama3-mlx-4bit
```

In the studio: **3 · Reading engine** → pick the Fish engine → *Read and accept the licence…* →
*Download and install*.

## Native builds (audio.cpp, any platform, experimental)

The MLX builds above run on Apple Silicon only. S2 Pro also has **native GGUF builds** that run on the
[audio.cpp](native-runtime.md) engine (Metal, CUDA or Vulkan, so also Windows and Linux). They are never picked
automatically: choose them with the inference switch (`--runtime native`, or *Advanced settings → Inference runtime*)
or name the build.

| Build | Download | Notes |
|---|---|---|
| `s2pro-native-q8` | 6.3 GB | S2 Pro, Q8_0, official audio.cpp GGUF package |
| `s2pro-native-bf16` | 10.2 GB | S2 Pro, bf16: slower and larger, closest to the original |

```bash
folivox engines install s2pro-native-q8       # also downloads the audio.cpp engine (asks for the licence first)
folivox render book.epub --tts fish-s2 --runtime native --voice my-voice.wav
```

Same licences and notices as the MLX builds (S2 Pro: Research License, personal use only; Drama 3: Fish Community
License). The engine and the model run in a separate `audiocpp_server` process like the other native models.
**Drama 3 has no native build yet.** It is in the audio.cpp source (merged 2026-10-16) but not in a release, so Folivox
offers only its MLX builds until a release exists (`folivox runtime build-help` still lists how to compile it yourself).
Memory figures for native builds are estimates. The builds keep the status `untested` (the project's standard test
has not been run on them), but each was run once on the test fragment (M3 Pro 36 GB, Metal, voice `gemini-2`, 73 s of
audio, no retakes): `s2pro-native-q8` RTF 2.52 (MLX build: 2.3), mean Whisper QA score 0.004; `s2pro-native-bf16` RTF 4.03, score 0.002, peak 20.4 GB resident, model load 36 s (slower than Q8, no audible gain). So on Apple Silicon the native
builds are not faster than MLX; the reason to use them is a computer without MLX (Windows, Linux), which has not
been tested. See [Native runtime](native-runtime.md).

## Licences, and what they mean for your audiobooks

| Build | Licence | Selling the audiobooks |
|---|---|---|
| S2 Pro | Fish Audio Research License (2026-03-07) | **Not allowed.** Personal and research use only; commercial use needs a separate licence from Fish Audio |
| Drama 3 | Fish Audio Community License 1.0 (2026-10-13) | Allowed while your total yearly revenue (with affiliates) is under USD 500,000; above that, a licence from Fish Audio is needed |

Both licences also say: no offering the engine as a hosted service to others, no training other
speech models on the output, no imitating the voice of an identifiable person without their consent
(breaking this one ends your licence), and "Built with Fish Audio" wherever you show or distribute
the result. Folivox shows the points above in a dialog and the *full* text on request; this is a
summary, not legal advice.

The acceptance is stored in `config.toml`:

```toml
[consent.fish-community]
version = "1.0 (2026-10-13)"
sha256 = "…"             # of the licence text that was shown
accepted_at = "2026-10-15T09:00:00Z"
```

If the licence version or text changes (a new catalog), you are asked again. `folivox engines
revoke ID` forgets the acceptance. The question is also asked by `install.sh` / `install.ps1` (only
for a person at a terminal, only on a computer where a tested build fits) and by
`folivox engines install`. `--accept-licence` answers it for scripts: only use it after reading.

### Voices of real people

The recordings bundled with Folivox are real LibriVox readers. Their recordings are public domain,
but the Fish licences forbid generating speech that imitates an identifiable person without that
person's consent. So **Fish engines do not use the bundled voices**: use your own recording, a voice
you generated (`folivox voices design`), or a voice of someone who agreed. If you decide the
bundled voices are fine for your case, set (your responsibility):

```toml
[fish]
allow_bundled_voices = true
```

## Which build is used

`--tts-build auto` (default) takes the most capable tested build that has room to spare on this computer:
its memory peak is at most 75% of the *total* memory, i.e. what is left when the heavy applications are
closed (the memory that happens to be free right now plays no part). Installed builds are preferred; if none is
installed, the studio shows which build will be downloaded, for example *Automatic (Drama 3, MLX mixed 3-bit,
19.8 GB, will need downloading)*. On a 36 GB Mac that is the 3-bit Drama 3 (4-bit peaks at 92% of the memory); an
installed 4-bit build is kept, with the usual warning. With no `--tts` option, no `[providers] tts` and no `FOLIVOX_TTS`, Folivox picks the best
installed build **whose licence you accepted** (Drama 3 4-bit > Drama 3 3-bit > S2 Pro 8-bit), and
falls back to CosyVoice 3 otherwise, or when the chosen voice is a bundled one.

## Memory

These models are big. Before a render Folivox checks the memory:

- the computer has less total memory than the build needs → the build is shown as "no" and refused;
- the *weights* do not fit in the free memory → the render does not start (override:
  `FOLIVOX_IGNORE_MEMORY=1`);
- less free memory than the measured peak → a warning: **close your browser and other heavy
  applications**, otherwise the system swaps and the render crawls (Drama 3 4-bit swapped 17 GB and
  stalled when a browser and containers were open on a 36 GB Mac).

The first fragment is slower: the model warms up for 80–90 s (Drama 3), which Folivox does while
loading. Memory is returned when the render ends (the worker exits).

## The catalog

`src/folivox/tts/catalog.json` lists every build Folivox offers: Hugging Face repo, **pinned
revision**, size and **sha256** of the weight files, backend and platforms, runtime packages,
required memory (weights and measured peak), licence, languages and "tested on" notes. Only entries
in the catalog can be installed, only safetensors weights (never pickle) are accepted, and the
downloaded files are verified against the hashes. A build marked `untested` is hidden from the
automatic choice until it has been run.

Measured on a MacBook Pro M3 Pro, 36 GB, Russian, six fragments of the project's hard test passage
(speech-recognition CER with Whisper, `--qa` on):

| Build | Real-time factor | Peak memory | Russian CER |
|---|---|---|---|
| Drama 3 MLX 4-bit | ~1.0 (after the warm-up) | 28–33 GB | 0.000–0.134 (0.0–0.011 after the standard hallucination strip) |
| S2 Pro MLX 8-bit | ~2.3 | 17.7 GB | 0.000–0.007 |
| CosyVoice 3 (for comparison) | 1.65–2.9 | – | 0.000–0.013 |

How the voices *sound* (accents, timbre) is not measured by any of this; listen before a long book.

Windows and Linux: S2 Pro officially needs a 24 GB+ NVIDIA GPU (or a CPU), Drama 3 an NVIDIA GPU with
48 GB+ (FP8). The catalog schema (backend, platforms, runtime) allows such builds, but none is
listed because none has been tested; today the Fish engines are offered on Apple Silicon only.

### Keeping the catalog current

```bash
python tools/fish_catalog.py watch      # new quantisations of fishaudio/drama-3 and s2-pro, new Fish releases
python tools/fish_catalog.py pin REPO   # revision + file sizes/sha256 to paste into a catalog entry
```

Run `watch` now and then (monthly is enough). It never downloads weights and never edits the
catalog. A new build enters the catalog only after it was run on the standard test fragment
(real-time factor, peak memory, CER) and the numbers were written into its `tested_on`.

`drama3-mlx-4bit` needs a fork of mlx-audio pinned to a commit (`stickerdaniel/mlx-audio`, adds the
`fish_drama3` model); the pin is in the catalog's `runtimes`. It will switch to mainline mlx-audio
when [Blaizzy/mlx-audio#1018](https://github.com/Blaizzy/mlx-audio/pull/1018) is merged.
