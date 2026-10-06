"""Whisper transcription backends: mlx-whisper on Apple Silicon, faster-whisper elsewhere."""

from __future__ import annotations

import platform
import sys

import numpy as np

MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
FW_MODEL = "large-v3-turbo"


class ASRUnavailable(RuntimeError):
    pass


def _resample_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == 16000:
        return audio.astype(np.float32)
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(sr, 16000)
    return resample_poly(audio, 16000 // g, sr // g).astype(np.float32)


class Transcriber:
    def __init__(self, backend: str = "auto", model: str | None = None, language: str = "ru"):
        self.language = language
        if backend == "auto":
            backend = "mlx" if sys.platform == "darwin" and platform.machine() == "arm64" else "faster-whisper"
        self.backend = backend
        if backend == "mlx":
            try:
                import mlx_whisper  # noqa: F401
            except ImportError as e:
                raise ASRUnavailable("mlx-whisper не установлен: pip install 'folivox[qa]'") from e
            self.model = model or MLX_MODEL
        elif backend == "faster-whisper":
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise ASRUnavailable("faster-whisper не установлен: pip install 'folivox[qa]'") from e
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model = model or FW_MODEL
            self._fw = WhisperModel(self.model, device=device, compute_type="float16" if device == "cuda" else "int8")
        else:
            raise ValueError(f"unknown ASR backend {backend!r}")

    def transcribe(self, audio: np.ndarray, sample_rate: int, prompt: str | None = None) -> str:
        x = _resample_16k(audio, sample_rate)
        if self.backend == "mlx":
            import mlx_whisper

            r = mlx_whisper.transcribe(x, path_or_hf_repo=self.model, language=self.language,
                                       condition_on_previous_text=False, initial_prompt=prompt, verbose=None)
            return r["text"].strip()
        segments, _ = self._fw.transcribe(x, language=self.language, beam_size=1, condition_on_previous_text=False,
                                          initial_prompt=prompt, vad_filter=False)
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe_file(self, path) -> str:
        import soundfile as sf

        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return self.transcribe(audio.mean(axis=1), sr)
