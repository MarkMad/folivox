"""Speed benchmark: the same fragment on each device, so different machines can be compared.

Every device runs in its own child process: a native crash (a broken cuDNN, for one) or an out-of-memory
error then ends only that line of the table, and the next device starts with an empty memory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from folivox.lang.bench_texts import TEXTS

MARK = "BENCH_RESULT "
ENGINE_ENV = "FOLIVOX_BENCH_ENGINE"  # {"tts", "build", "runtime"} for a Fish engine; unset = CosyVoice 3


def sample_text(lang: str) -> str:
    return TEXTS.get(lang, TEXTS["en"])


def available_devices() -> list[str]:
    out = ["cpu"]
    try:
        import torch

        if torch.cuda.is_available():
            out.append("cuda")
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            out.append("mps")
    except Exception:  # noqa: BLE001 — not installed, or a broken install (DLL load OSError)
        pass
    try:
        from folivox.tts import native_setup

        if native_setup.status().ready:
            out.append("native")
    except Exception:  # noqa: BLE001 — an unreadable native manifest must not stop the CPU/GPU lines
        pass
    return out


def nvidia_used_mb() -> int | None:
    """Memory in use on all NVIDIA cards together (MiB), or None without ``nvidia-smi``."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)  # noqa: S603, S607
        vals = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        return sum(vals) if r.returncode == 0 and vals else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class GpuWatch(threading.Thread):
    """Samples the used memory of the NVIDIA cards while a device runs; the peak is relative to the start.

    It sees the whole card, so the native engine (a separate process) and PyTorch are measured the same way.
    Other vendors give ``None``: there is no portable way to ask them.
    """

    def __init__(self, every: float = 0.5, read=nvidia_used_mb):
        super().__init__(daemon=True)
        self.read, self.every = read, every
        self.base = read()
        self.peak = self.base
        self._stop_evt = threading.Event()

    def run(self) -> None:
        while not self._stop_evt.wait(self.every):
            v = self.read()
            if v is not None and (self.peak is None or v > self.peak):
                self.peak = v

    def finish(self) -> float | None:
        self._stop_evt.set()
        v = self.read()
        if v is not None and (self.peak is None or v > self.peak):
            self.peak = v
        if self.base is None or self.peak is None:
            return None
        return max(0, self.peak - self.base) / 1024


def peak_ram_gb(pid: int | None = None) -> float | None:
    """Highest resident memory of a process (this one by default), in GB; None where it cannot be read."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
            k32.OpenProcess.restype = wintypes.HANDLE
            h = k32.GetCurrentProcess() if pid is None else k32.OpenProcess(0x0410, False, pid)
            if not h:
                return None
            c = Counters()
            c.cb = ctypes.sizeof(c)
            ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
            if pid is not None:
                k32.CloseHandle(h)
            return c.PeakWorkingSetSize / 1e9 if ok else None
        if pid is not None and Path(f"/proc/{pid}/status").exists():
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1e6  # kB
            return None
        if pid is None:
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return peak / 1e9 if sys.platform == "darwin" else peak / 1e6  # bytes on macOS, kB on Linux
    except Exception:  # noqa: BLE001 — a measurement must never fail a benchmark
        pass
    return None


def nvidia_cards() -> str | None:
    """'NVIDIA GeForce RTX 3050 Laptop GPU 4.3 GB, driver 561.09' from nvidia-smi (works without PyTorch)."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True,
                           timeout=10)  # noqa: S603, S607
        if r.returncode != 0:
            return None
        out = []
        for line in r.stdout.strip().splitlines():
            name, mem, drv = [x.strip() for x in line.split(",")]
            out.append(f"{name} {int(mem) / 1024:.1f} GB, driver {drv}")
        return "; ".join(out) or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def in_container() -> str | None:
    """'Docker container' when the benchmark runs inside one (the report must say so: GPUs differ there)."""
    try:
        if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
            return "container (Docker)"
    except OSError:
        pass
    return None


def engine_info(engine, device: str) -> dict:
    """Which runtime and which physical device actually did the work (best effort, never raises)."""
    info: dict = {"runtime": "PyTorch", "detail": ""}
    try:
        spec = getattr(engine, "spec", None)
        if spec is not None and hasattr(spec, "server"):  # the native audio.cpp engine
            from folivox.tts import native_setup

            build = Path(spec.server).parent.name
            name = ""
            devs = native_setup.list_devices(spec.server, spec.backend) or []
            pick = next((d for d in devs if d.index == spec.device), None) if spec.device is not None else None
            if pick is None and len(devs) == 1:
                pick = devs[0]
            if pick:
                name = f" · {pick.name} ({'integrated' if pick.kind == 'IGPU' else pick.kind.lower()})"
            info = {"runtime": "audio.cpp (native)", "detail": f"{build}, backend {spec.backend}"
                    + (f", device {spec.device}" if spec.device is not None else "") + name}
        elif device.startswith("cuda"):
            import torch

            info["detail"] = (f"torch {torch.__version__}, CUDA {torch.version.cuda}, "
                              f"{torch.cuda.get_device_name(0)}")
        elif device == "mps":
            import torch

            info["detail"] = f"torch {torch.__version__}, Apple GPU (MPS)"
        else:
            import torch

            info["detail"] = f"torch {torch.__version__}, CPU"
    except Exception:  # noqa: BLE001
        pass
    return info


def worker(device: str, voice_wav: str, voice_text: str | None, text: str) -> dict:
    """Load the model, warm it up once, synthesise ``text`` and measure. Runs in the child process."""
    from folivox.tts import ENGINES
    from folivox.tts.voice import load_voice

    voice = load_voice(voice_wav, voice_text)
    watch = GpuWatch()
    watch.start()
    t0 = time.time()
    spec = json.loads(os.environ.get(ENGINE_ENV) or "{}")
    if spec.get("tts") and spec["tts"] != "cosyvoice3":  # a Fish engine: its own build, native or MLX
        engine = ENGINES.create(spec["tts"], build=spec.get("build") or "auto", runtime=spec.get("runtime") or None)
        engine.start(voice)  # loads the model and warms it up with the voice, as a render does
    elif device == "native":  # the audio.cpp runtime (`folivox runtime install`); PyTorch is not imported
        from folivox import config
        from folivox.tts.native import NativeCosyVoiceEngine

        engine = NativeCosyVoiceEngine(**config.native_options())
    else:
        engine = ENGINES.create("cosyvoice3", device=device)
    load_s = time.time() - t0
    t0 = time.time()
    engine.synthesize(text.split(".")[0] + ".", voice)  # the first call pays for kernel compilation and caches
    warm_s = time.time() - t0
    r = engine.synthesize(text, voice)
    audio_s = len(r.audio) / r.sample_rate
    res = {"device": device, "actual": engine.device, "load_s": load_s, "warmup_s": warm_s, "synth_s": r.seconds,
           "audio_s": audio_s, "chars": len(text), "chars_per_s": len(text) / r.seconds if r.seconds else 0,
           "rtf": r.seconds / audio_s if audio_s else 0, "peak_vram_gb": None}
    res["actual"] = engine.device
    res.update(engine_info(engine, device))
    # peak RAM of the process that holds the model; the native engine keeps it in a separate server process
    server = getattr(engine, "_server", None)
    server_pid = getattr(getattr(server, "proc", None), "pid", None)
    res["ram_peak_gb"] = peak_ram_gb(server_pid) if server_pid else peak_ram_gb()
    res["ram_where"] = "engine process" if server_pid else "Folivox process"
    res["gpu_card_peak_gb"] = watch.finish()  # whole NVIDIA card, relative to before the model was loaded
    if hasattr(engine, "close") and (device == "native" or spec.get("tts")):
        engine.close()
    if device.startswith("cuda"):
        import torch

        res["peak_vram_gb"] = torch.cuda.max_memory_allocated() / 1e9
        res["torch_reserved_gb"] = torch.cuda.max_memory_reserved() / 1e9
        res["card_total_gb"] = torch.cuda.get_device_properties(0).total_memory / 1e9
    return res


def run_device(device: str, voice_wav: str, voice_text: str | None, text: str, timeout: float,
               engine: dict | None = None) -> dict:
    cmd = [sys.executable, "-m", "folivox.bench", device, voice_wav, voice_text or "", text]
    env = {**os.environ, ENGINE_ENV: json.dumps(engine)} if engine else None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"device": device, "error": f"no result within {timeout:.0f} s"}
    except OSError as e:
        return {"device": device, "error": f"could not start: {e}"}
    for line in reversed(r.stdout.splitlines()):
        if line.startswith(MARK):
            try:
                return json.loads(line[len(MARK):])
            except ValueError:
                break
    tail = (r.stderr or r.stdout).strip().splitlines()
    return {"device": device, "error": f"crashed (exit {r.returncode})" + (f": {tail[-1][:200]}" if tail else "")}


if __name__ == "__main__":
    dev, wav, vtext, txt = sys.argv[1:5]
    try:
        out = worker(dev, wav, vtext or None, txt)
    except Exception as e:  # noqa: BLE001 — out of memory, no weights, …: report, do not traceback
        out = {"device": dev, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    print(MARK + json.dumps(out), flush=True)


def _verdict(rtf: float) -> str:
    if rtf <= 0:
        return ""
    if rtf < 1:
        return f"{1 / rtf:.1f}x faster than real time"
    return f"{rtf:.1f}x SLOWER than real time (a minute of audio takes {rtf:.1f} min)"


def report_text(rows: list[dict], what: str, lang: str) -> str:
    """A block to paste into an issue: the computer, the engine and device of every line, nothing private."""
    import platform

    from folivox import __version__, config, diag
    from folivox.tts import native_setup

    hw = diag.hardware()
    where = in_container()
    try:
        setting = config.runtime()
    except ValueError:
        setting = "?"
    lines = ["Folivox speed report", f"folivox {__version__} · {platform.system()} {platform.release()} "
             f"({platform.machine()}) · Python {platform.python_version()}",
             f"{hw['cores']} cores, {hw['ram_gb']} GB RAM, GPU: "
             + (f"{hw['gpu']}{' ' + str(hw['vram_gb']) + ' GB' if hw['vram_gb'] else ''}" if hw["gpu"]
                else (nvidia_cards() or "none found")),
             f"running in: {where or 'directly on the host'} · inference runtime setting: {setting}",
             f"engine: {what} · test text language: {lang} · audio.cpp release {_native_release(native_setup)} "
             "(used only by the lines marked audio.cpp)", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['device']} — FAILED {diag.redact(str(r['error']))}")
            continue
        runtime = r.get("runtime") or ("audio.cpp (native)" if str(r.get("actual", "")).startswith("native") else "")
        lines.append(f"{r['device']} — OK, {runtime or r.get('actual', '')}".rstrip(", "))
        if r.get("detail"):
            lines.append(f"  engine: {diag.redact(str(r['detail']))}")
        lines.append(f"  speed: RTF {r['rtf']:.2f} ({_verdict(r['rtf'])}) · {r['chars_per_s']:.1f} chars/s")
        if r.get("audio_s"):
            lines.append(f"  test: {r.get('chars', '?')} characters -> {r['audio_s']:.1f} s of audio, "
                         f"synthesis took {r.get('synth_s', 0):.1f} s")
        lines.append(f"  time before the first result: model load {r['load_s']:.0f} s, warm-up {r['warmup_s']:.0f} s "
                     "(neither is in the speed)")
        mem = []
        if r.get("gpu_card_peak_gb") is not None:
            mem.append(f"NVIDIA card +{r['gpu_card_peak_gb']:.1f} GB at peak (whole card, from nvidia-smi)")
        if r.get("peak_vram_gb") is not None:
            res = f", reserved {r['torch_reserved_gb']:.1f}" if r.get("torch_reserved_gb") is not None else ""
            tot = f" of {r['card_total_gb']:.1f} GB" if r.get("card_total_gb") else ""
            mem.append(f"PyTorch tensors {r['peak_vram_gb']:.1f} GB{res}{tot}")
        if r.get("ram_peak_gb") is not None:
            mem.append(f"RAM peak {r['ram_peak_gb']:.1f} GB ({r.get('ram_where', 'process')})")
        lines.append("  memory: " + ("; ".join(mem) if mem else "not measured for this device (GPU memory is only "
                                      "read for NVIDIA cards)"))
    lines.append("Quality was not checked by `folivox bench`: say what you heard, or run a preview with the quality "
                 "check on and add its score.")
    return "\n".join(lines)


def _native_release(native_setup) -> str:
    try:
        return str(native_setup.load().release)
    except Exception:  # noqa: BLE001 — the report must print even with a broken native manifest
        return "unknown"
