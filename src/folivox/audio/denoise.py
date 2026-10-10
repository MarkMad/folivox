"""Gentle reduction of steady background noise (hiss, hum, fans) in a voice sample.

Spectral gating with a noise profile taken from the quietest part of the recording. Deliberately
conservative: no temporal/frequency smoothing of the mask (it smears speech and makes it dull) and a
partial reduction (``strength`` < 1) so the voice does not get the "metallic" ring of aggressive
denoisers. It cannot fix a noisy room; for that, record again closer to the microphone.
"""

from __future__ import annotations

import numpy as np


def quiet_profile(audio: np.ndarray, sr: int, fraction: float = 0.15, frame: float = 0.02) -> np.ndarray:
    """The quietest ``fraction`` of the frames, concatenated: an estimate of the background alone."""
    n = max(1, int(sr * frame))
    frames = audio[: len(audio) // n * n].reshape(-1, n)
    if len(frames) == 0:
        return audio[:0]
    energy = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    keep = np.sort(np.argsort(energy)[: max(5, int(fraction * len(energy)))])
    return np.concatenate([frames[i] for i in keep])


def reduce_noise(audio: np.ndarray, sr: int, strength: float = 0.7) -> np.ndarray:
    """Return ``audio`` with stationary background noise reduced by up to ``strength`` (0..1)."""
    try:
        import noisereduce
    except ImportError as e:
        raise RuntimeError('Noise reduction needs the "noisereduce" package: pip install "folivox[denoise]"') from e
    audio = np.asarray(audio, dtype=np.float32)
    profile = quiet_profile(audio, sr)
    if len(profile) < sr * 0.1 or float(np.abs(audio).max()) < 1e-4:
        return audio  # nothing to learn the noise from (or digital silence)
    out = noisereduce.reduce_noise(y=audio, sr=sr, y_noise=profile, stationary=True, prop_decrease=strength,
                                   n_std_thresh_stationary=1.5, freq_mask_smooth_hz=None, time_mask_smooth_ms=None)
    return np.clip(out, -1.0, 1.0).astype(np.float32)
