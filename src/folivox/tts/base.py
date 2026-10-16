"""Interface of a speech synthesis engine (see :data:`folivox.tts.ENGINES`)."""

from __future__ import annotations

import os
from concurrent.futures import TimeoutError as FutureTimeout
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

    def prepare(self, text: str, voice: Voice, seed: int = 0, lang: str = "") -> tuple[Any, float]:
        """Stage 1, thread-safe w.r.t. :meth:`finish`. Returns (intermediate, seconds). ``lang`` is the language of
        a fragment that is not in the book's language; an engine with no language parameter ignores it (it reads
        the language of the text)."""
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


class SynthTimeout(RuntimeError):
    """A local fragment did not finish in time (a hung or runaway generation)."""


def synth_timeout(chars: int) -> float:
    """Seconds a local fragment may take: generous for slow CPUs, but finite. FOLIVOX_SYNTH_TIMEOUT overrides
    (seconds per fragment; 0 turns the limit off)."""
    env = os.environ.get("FOLIVOX_SYNTH_TIMEOUT")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return 180.0 + 2.0 * chars


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
        self.hung = False

    def submit(self, key: str, text: str, seed: int, voice: Voice | None = None, lang: str = ""):
        k = (key, seed)
        if k not in self.futures:
            extra = {"lang": lang} if lang else {}  # only a fragment in another language than the book's
            self.futures[k] = self.pool.submit(self.engine.prepare, text, voice or self.voice, seed, **extra)
        return self.futures[k]

    def synthesize(self, key: str, text: str, seed: int, speed: float = 1.0, voice: Voice | None = None,
                   lang: str = "") -> Synthesis:
        limit = synth_timeout(len(text)) if getattr(self.engine, "local", True) else 0
        try:
            tokens, t_llm = self.submit(key, text, seed, voice, lang).result(timeout=limit or None)
        except FutureTimeout:
            self.hung = True
            raise SynthTimeout(f"Synthesis of one fragment ({len(text)} characters) did not finish in "
                               f"{limit:.0f} s and looks stuck. Progress is saved: run the same command again "
                               "to continue (set FOLIVOX_SYNTH_TIMEOUT=seconds to change the limit, 0 to turn it "
                               "off).") from None
        self.futures.pop((key, seed), None)
        audio, t_wav = self.engine.finish(tokens, voice or self.voice, speed)
        return Synthesis(audio, self.engine.sample_rate, t_llm + t_wav)

    def close(self) -> None:
        for fut in self.futures.values():
            fut.cancel()
        self.pool.shutdown(wait=not self.hung, cancel_futures=True)  # never wait for a stuck worker
