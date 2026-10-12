"""Is the CUDA GPU worth using? One answer for the TTS engine, the recogniser and ``folivox doctor``.

``torch.cuda.is_available()`` only says a driver is present. A broken cuDNN (another version earlier on PATH)
kills the whole process with a native error that Python cannot catch, and a small card runs out of memory with
the TTS model and Whisper side by side. So "auto" uses CUDA only after a probe in a child process and a memory check.
"""

from __future__ import annotations

import subprocess
import sys
from functools import lru_cache

MIN_TTS_VRAM_GB = 4.0  # the TTS model alone (Whisper stays on the CPU below 8 GB); `folivox bench` measures it
MIN_WHISPER_VRAM_GB = 8.0  # the speech-recognition model also lives on the GPU next to the TTS model

_PROBE = ("import torch;x=torch.randn(1,3,16,16,device='cuda');c=torch.nn.Conv2d(3,4,3).cuda();"
          "c(x).sum().item();torch.cuda.synchronize()")


@lru_cache(maxsize=1)
def vram_gb() -> float | None:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / 1e9
    except Exception:  # noqa: BLE001
        pass
    return None


@lru_cache(maxsize=1)
def cuda_skip_reason() -> str | None:
    """None when CUDA is absent or fine to use; otherwise why "auto" should stay on the CPU."""
    mem = vram_gb()
    if mem is None:
        return None
    if mem < MIN_TTS_VRAM_GB:
        return f"the GPU has only {mem:.1f} GB of memory (at least {MIN_TTS_VRAM_GB:.0f} GB needed)"
    try:
        r = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True, timeout=180)
    except Exception as e:  # noqa: BLE001
        return f"the CUDA self-test could not run ({e})"
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()
        return f"the CUDA self-test failed (exit {r.returncode}{': ' + tail[-1][:160] if tail else ''})"
    return None


def whisper_device() -> str:
    """Device for the speech-recognition QA: the GPU only when it is healthy and has room for both models."""
    mem = vram_gb()
    return "cuda" if mem is not None and mem >= MIN_WHISPER_VRAM_GB and cuda_skip_reason() is None else "cpu"
