"""Give memory back to the system once a render stops (finished, paused or failed).

The TTS engine and the QA recogniser go out of scope with the render, but the big caches stay:
mlx-whisper keeps its model in a class attribute, the Russian stress model sits in an lru_cache,
and the torch (MPS/CUDA) and MLX allocators hold freed buffers for reuse. A paused studio would
keep ~20 GB that way; after :func:`release` it drops to the size of the web server.
"""

from __future__ import annotations

import ctypes
import gc
import sys


def release() -> None:
    mods = sys.modules
    holder = getattr(mods.get("mlx_whisper.transcribe"), "ModelHolder", None)
    if holder is not None:
        holder.model = holder.model_path = None
    stress = mods.get("folivox.text.stress")
    if stress is not None:
        stress._model.cache_clear()
    gc.collect()
    torch = mods.get("torch")
    if torch is not None:
        try:
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 — best effort
            pass
    mx = mods.get("mlx.core")
    if mx is not None:
        try:
            mx.clear_cache()
        except Exception:  # noqa: BLE001
            pass
    if sys.platform == "darwin":
        try:  # hand freed malloc pages back to the OS instead of keeping them for reuse
            ctypes.CDLL("/usr/lib/libSystem.B.dylib").malloc_zone_pressure_relief(None, 0)
        except Exception:  # noqa: BLE001
            pass
    elif sys.platform.startswith("linux"):
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:  # noqa: BLE001
            pass
