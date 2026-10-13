"""Is the CUDA GPU worth using? One answer for the TTS engine, the recogniser and ``folivox doctor``.

``torch.cuda.is_available()`` only says a driver is present. A broken cuDNN (another version earlier on PATH)
kills the whole process with a native error that Python cannot catch, and a small card runs out of memory with
the TTS model and Whisper side by side. So "auto" uses CUDA only after a probe in a child process and a memory check.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from functools import lru_cache

MIN_TTS_VRAM_GB = 4.0  # the TTS model alone (Whisper stays on the CPU below 8 GB); `folivox bench` measures it
MIN_WHISPER_VRAM_GB = 8.0  # the speech-recognition model also lives on the GPU next to the TTS model

_PROBE = ("from folivox.gpu import pin_cudnn;pin_cudnn();"
          "import torch;x=torch.randn(1,3,16,16,device='cuda');c=torch.nn.Conv2d(3,4,3).cuda();"
          "c(x).sum().item();torch.cuda.synchronize()")


@lru_cache(maxsize=1)
def pin_cudnn() -> None:
    """Windows: load every cuDNN DLL shipped with torch up front.

    cuDNN 9 loads its sub-libraries lazily, on the first op that needs them. If another cuDNN 9 build is on
    PATH (a CUDA toolkit, another app) or already loaded (ctranslate2 ships a bare cudnn64_9.dll), a late load
    picks that copy and the process dies with
    "Could not load symbol cudnnGetLibConfig. Error code 127". Windows reuses an already loaded DLL of the
    same name, so loading torch's whole set first keeps torch and faster-whisper (ctranslate2) on one build.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        import torch

        lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        dlls = sorted(glob.glob(os.path.join(lib, "cudnn*.dll")), key=lambda p: "_" in os.path.basename(p))
        if not dlls:
            return
        os.add_dll_directory(lib)
        os.environ["PATH"] = lib + os.pathsep + os.environ.get("PATH", "")
        for dll in dlls:  # cudnn64_9.dll first, then the sub-libraries
            try:
                ctypes.WinDLL(dll)
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


@lru_cache(maxsize=1)
def vram_gb() -> float | None:
    try:
        pin_cudnn()
        import torch

        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / 1e9
    except Exception:  # noqa: BLE001
        pass
    return None


def missing_arch() -> str | None:
    """The GPU architecture (e.g. "sm_120") when this PyTorch build has no kernels for it, else None.

    An RTX 50 card with a pre-2.7 build fails every op with "no kernel image is available for execution on
    the device"; the installer picks the right build, so the fix is to run it again (``folivox update``).
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        major, minor = torch.cuda.get_device_capability(0)
        archs = torch.cuda.get_arch_list()
    except Exception:  # noqa: BLE001
        return None
    if not archs:
        return None
    sm = f"sm_{major}{minor}"
    # same-major binaries run on a newer minor (sm_86 kernels on sm_89); PTX ("compute_XY") is JIT-compiled forward
    have = [a.split("_")[-1] for a in archs]
    ok = any(len(h) >= 2 and h[:-1] == str(major) and int(h[-1]) <= minor for h in have if h.isdigit())
    ptx = any(a.startswith("compute_") and a[8:].isdigit() and int(a[8:]) <= major * 10 + minor for a in archs)
    return None if ok or ptx else sm


@lru_cache(maxsize=1)
def cuda_skip_reason() -> str | None:
    """None when CUDA is absent or fine to use; otherwise why "auto" should stay on the CPU."""
    mem = vram_gb()
    if mem is None:
        return None
    sm = missing_arch()
    if sm:
        return (f"this PyTorch build has no code for your GPU ({sm}); run 'folivox update' "
                "to install the build that supports it")
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
