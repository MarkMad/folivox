"""Audio helpers: silence trimming, fades, chunk I/O."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def trim_silence(audio: np.ndarray, sr: int, threshold_db: float = -45.0, margin: float = 0.04,
                 frame: float = 0.01) -> np.ndarray:
    """Cut leading/trailing silence (pauses are inserted explicitly during assembly)."""
    if audio.size == 0:
        return audio
    n = max(1, int(sr * frame))
    frames = audio[: len(audio) // n * n].reshape(-1, n)
    if frames.size == 0:
        return audio
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1) + 1e-12)
    peak = rms.max()
    if peak < 1e-4:  # digital silence (−80 dBFS)
        return audio[:0]
    loud = np.nonzero(20 * np.log10(rms / peak + 1e-12) > threshold_db)[0]
    if loud.size == 0:
        return audio[:0]
    m = int(sr * margin)
    start = max(0, loud[0] * n - m)
    end = min(len(audio), (loud[-1] + 1) * n + m)
    return audio[start:end]


def fade(audio: np.ndarray, sr: int, seconds: float = 0.008) -> np.ndarray:
    n = min(int(sr * seconds), len(audio) // 2)
    if n <= 0:
        return audio
    audio = audio.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    audio[:n] *= ramp
    audio[-n:] *= ramp[::-1]
    return audio


def postprocess(audio: np.ndarray, sr: int) -> np.ndarray:
    audio = trim_silence(audio.astype(np.float32), sr)
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    return fade(audio, sr)


def save(path: Path, audio: np.ndarray, sr: int) -> None:
    import soundfile as sf

    tmp = path.with_suffix(".tmp.flac")
    sf.write(str(tmp), audio, sr, subtype="PCM_16", format="FLAC")
    tmp.replace(path)  # atomic: an interrupted write never leaves a half file


def load(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    audio, sr = sf.read(str(path), dtype="float32")
    return audio, sr
