"""Interface of a speech synthesis engine (see :data:`folivox.tts.ENGINES`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from folivox.tts.voice import Voice


@dataclass
class Synthesis:
    audio: np.ndarray  # float32 mono
    sample_rate: int
    seconds: float  # wall time spent


class TTSEngine:
    """Zero-shot voice-cloning TTS.

    Synthesis is split into two stages so the pipeline can overlap them: :meth:`prepare` runs in a
    background thread for upcoming fragments (e.g. the autoregressive LLM), :meth:`finish` turns its
    result into audio. A single-stage engine may implement only :meth:`synthesize_audio`.
    """

    name = ""
    sample_rate: int = 24000
    device: str = "cpu"
    languages: tuple[str, ...] = ()  # ISO 639-1 codes the model can read
    local: bool = True  # False → a paid cloud API (the text leaves the computer)
    parallel: int = 1  # fragments prepared at the same time

    def prepare(self, text: str, voice: Voice, seed: int = 0) -> tuple[Any, float]:
        """Stage 1, thread-safe w.r.t. :meth:`finish`. Returns (intermediate, seconds)."""
        return (text, seed), 0.0

    def finish(self, prepared: Any, voice: Voice, speed: float = 1.0) -> tuple[np.ndarray, float]:
        """Stage 2: intermediate → float32 waveform. Returns (audio, seconds)."""
        text, seed = prepared
        return self.synthesize_audio(text, voice, seed, speed)

    def synthesize_audio(self, text: str, voice: Voice, seed: int, speed: float) -> tuple[np.ndarray, float]:
        raise NotImplementedError

    def synthesize(self, text: str, voice: Voice, seed: int = 0, speed: float = 1.0) -> Synthesis:
        prepared, t1 = self.prepare(text, voice, seed)
        audio, t2 = self.finish(prepared, voice, speed)
        return Synthesis(audio, self.sample_rate, t1 + t2)


class Prefetcher:
    """Runs stage 1 (:meth:`TTSEngine.prepare`) for upcoming fragments in a background thread.

    For CosyVoice on Apple Silicon the LLM runs on CPU and the flow on the GPU, so generating tokens
    for fragment *i+1* while fragment *i* goes through flow + vocoder hides most of the LLM time.
    """

    def __init__(self, engine: TTSEngine, voice: Voice):
        from concurrent.futures import ThreadPoolExecutor

        self.engine, self.voice = engine, voice
        self.pool = ThreadPoolExecutor(max_workers=max(1, engine.parallel), thread_name_prefix="folivox-llm")
        self.futures: dict[tuple[str, int], object] = {}

    def submit(self, key: str, text: str, seed: int):
        k = (key, seed)
        if k not in self.futures:
            self.futures[k] = self.pool.submit(self.engine.prepare, text, self.voice, seed)
        return self.futures[k]

    def synthesize(self, key: str, text: str, seed: int, speed: float = 1.0) -> Synthesis:
        tokens, t_llm = self.submit(key, text, seed).result()
        self.futures.pop((key, seed), None)
        audio, t_wav = self.engine.finish(tokens, self.voice, speed)
        return Synthesis(audio, self.engine.sample_rate, t_llm + t_wav)

    def close(self) -> None:
        for fut in self.futures.values():
            fut.cancel()
        self.pool.shutdown(wait=True)
