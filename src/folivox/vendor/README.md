# Vendored third-party code

| Directory | Upstream | License | Commit |
|---|---|---|---|
| `cosyvoice/` | https://github.com/FunAudioLLM/CosyVoice | Apache-2.0 (`cosyvoice/LICENSE`) | `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc` |
| `matcha/` | https://github.com/shivammehta25/Matcha-TTS (as shipped in CosyVoice `third_party/`) | MIT (`matcha/LICENSE`) | same |
| `whisper_audio/` | https://github.com/openai/whisper (`whisper/audio.py`, `assets/mel_filters.npz`) | MIT (`whisper_audio/LICENSE`) | v20231117 |

Only the inference path is kept. Modifications by Folivox:

- imports rewritten from `cosyvoice.*` / `matcha.*` to `folivox.vendor.*`;
- training code removed (dataset, bin, executors, GAN discriminators, schedulers, losses);
- `modelscope`, TensorRT, vLLM and DeepSpeed paths removed (stubs raise `NotImplementedError`);
- `openai-whisper` replaced by a 30-line `whisper_audio.log_mel_spectrogram`;
- `matcha.utils.pylogger` no longer depends on `lightning`;
- `CosyVoice3.__init__` loads only the inference part of the model yaml.

Model weights are **not** vendored; they are downloaded on first run.
- `utils/file_utils.py` no longer calls `logging.basicConfig(level=DEBUG)` at import;
- `hifigan/` vocoder input is moved to the vocoder's device and the LLM may run on its own device
  (`model.llm_device`), enabling the MPS hybrid mode (LLM + vocoder on CPU, flow on GPU);
- `CosyVoice3(..., llm_file=...)` selects base (`llm.pt`) or RL (`llm.rl.pt`) weights.
