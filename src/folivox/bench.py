"""Speed benchmark: the same fragment on each device, so different machines can be compared.

Every device runs in its own child process: a native crash (a broken cuDNN, for one) or an out-of-memory
error then ends only that line of the table, and the next device starts with an empty memory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

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
    except ImportError:
        pass
    from folivox.tts import native_setup

    if native_setup.status().ready:
        out.append("native")
    return out


def worker(device: str, voice_wav: str, voice_text: str | None, text: str) -> dict:
    """Load the model, warm it up once, synthesise ``text`` and measure. Runs in the child process."""
    from folivox.tts import ENGINES
    from folivox.tts.voice import load_voice

    voice = load_voice(voice_wav, voice_text)
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
    if hasattr(engine, "close") and (device == "native" or spec.get("tts")):
        engine.close()
    if device.startswith("cuda"):
        import torch

        res["peak_vram_gb"] = torch.cuda.max_memory_allocated() / 1e9
    return res


def run_device(device: str, voice_wav: str, voice_text: str | None, text: str, timeout: float,
               engine: dict | None = None) -> dict:
    cmd = [sys.executable, "-m", "folivox.bench", device, voice_wav, voice_text or "", text]
    env = {**os.environ, ENGINE_ENV: json.dumps(engine)} if engine else None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"device": device, "error": f"no result within {timeout:.0f} s"}
    for line in reversed(r.stdout.splitlines()):
        if line.startswith(MARK):
            return json.loads(line[len(MARK):])
    tail = (r.stderr or r.stdout).strip().splitlines()
    return {"device": device, "error": f"crashed (exit {r.returncode})" + (f": {tail[-1][:200]}" if tail else "")}


if __name__ == "__main__":
    dev, wav, vtext, txt = sys.argv[1:5]
    try:
        out = worker(dev, wav, vtext or None, txt)
    except Exception as e:  # noqa: BLE001 — out of memory, no weights, …: report, do not traceback
        out = {"device": dev, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    print(MARK + json.dumps(out), flush=True)


def report_text(rows: list[dict], what: str, lang: str) -> str:
    """A block to paste into an issue: the computer, the runtime and the table, nothing private."""
    import platform

    from folivox import __version__, diag
    from folivox.tts import native_setup

    hw = diag.hardware()
    lines = ["Folivox speed report", f"folivox {__version__} · {platform.system()} {platform.release()} "
             f"({platform.machine()}) · Python {platform.python_version()}",
             f"{hw['cores']} cores, {hw['ram_gb']} GB RAM, GPU: {hw['gpu'] or 'none'}"
             f"{' ' + str(hw['vram_gb']) + ' GB' if hw['vram_gb'] else ''}",
             f"audio.cpp release {native_setup.load().release} · engine: {what} · test text language: {lang}", ""]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['device']}: FAILED {r['error']}")
        else:
            lines.append(f"{r['device']} ({r.get('actual', '')}): RTF {r['rtf']:.2f} · "
                         f"{r['chars_per_s']:.1f} chars/s · load {r['load_s']:.0f} s · warm-up {r['warmup_s']:.0f} s")
    lines.append("Quality was not checked by `folivox bench`: say what you heard, or run a preview with the quality "
                 "check on and add its score.")
    return "\n".join(lines)
