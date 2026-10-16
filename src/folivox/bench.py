"""Speed benchmark: the same fragment on each device, so different machines can be compared.

Every device runs in its own child process: a native crash (a broken cuDNN, for one) or an out-of-memory
error then ends only that line of the table, and the next device starts with an empty memory.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

from folivox.lang.bench_texts import TEXTS

MARK = "BENCH_RESULT "


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
    if device == "native":  # the audio.cpp runtime (`folivox runtime install`); PyTorch is not imported
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
    if device == "native":
        engine.close()
    if device.startswith("cuda"):
        import torch

        res["peak_vram_gb"] = torch.cuda.max_memory_allocated() / 1e9
    return res


def run_device(device: str, voice_wav: str, voice_text: str | None, text: str, timeout: float) -> dict:
    cmd = [sys.executable, "-m", "folivox.bench", device, voice_wav, voice_text or "", text]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
