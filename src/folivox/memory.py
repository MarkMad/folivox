"""Give memory back to the system once a render stops (finished, paused or failed).

The TTS engine and the QA recogniser go out of scope with the render, but the big caches stay:
mlx-whisper keeps its model in a class attribute, the Russian stress model sits in an lru_cache,
and the torch (MPS/CUDA) and MLX allocators hold freed buffers for reuse. A paused studio would
keep ~20 GB that way; after :func:`release` it drops to the size of the web server.
"""

from __future__ import annotations

import ctypes
import gc
import os
import subprocess
import sys


def available_gb() -> float | None:
    """Memory that can be given to a program right now, in GB: free + reclaimable (file cache, purgeable pages).
    None when the system does not tell. Not psutil: macOS ``vm_stat``, Linux ``MemAvailable``, Windows API."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = 16384 if "page size of 16384" in out else 4096
            counts = {}
            for line in out.splitlines()[1:]:
                key, _, val = line.partition(":")
                digits = "".join(c for c in val if c.isdigit())
                if digits:
                    counts[key.strip()] = int(digits)
            pages = sum(counts.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative",
                                                   "Pages purgeable"))
            return pages * page / 1e9
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024 / 1e9
            return None
        if os.name == "nt":
            class Mem(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                            ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]

            m = Mem()
            m.length = ctypes.sizeof(Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
            return m.avail / 1e9
    except Exception:  # noqa: BLE001
        return None
    return None


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
