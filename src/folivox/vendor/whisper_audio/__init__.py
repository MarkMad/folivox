"""log-Mel spectrogram from openai/whisper (MIT, see LICENSE), trimmed by Folivox
so the vendored CosyVoice frontend does not depend on the openai-whisper package."""
import os
from functools import lru_cache

import numpy as np
import torch

N_FFT = 400
HOP_LENGTH = 160


@lru_cache(maxsize=None)
def mel_filters(device, n_mels: int) -> torch.Tensor:
    assert n_mels in {80, 128}, f"Unsupported n_mels: {n_mels}"
    path = os.path.join(os.path.dirname(__file__), "mel_filters.npz")
    with np.load(path, allow_pickle=False) as f:
        return torch.from_numpy(f[f"mel_{n_mels}"]).to(device)


def log_mel_spectrogram(audio: torch.Tensor, n_mels: int = 80, padding: int = 0) -> torch.Tensor:
    if not torch.is_tensor(audio):
        audio = torch.from_numpy(audio)
    if padding > 0:
        audio = torch.nn.functional.pad(audio, (0, padding))
    window = torch.hann_window(N_FFT).to(audio.device)
    stft = torch.stft(audio, N_FFT, HOP_LENGTH, window=window, return_complex=True)
    magnitudes = stft[..., :-1].abs() ** 2
    mel_spec = mel_filters(audio.device, n_mels) @ magnitudes
    log_spec = torch.clamp(mel_spec, min=1e-10).log10()
    log_spec = torch.maximum(log_spec, log_spec.max() - 8.0)
    return (log_spec + 4.0) / 4.0
