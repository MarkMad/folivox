"""Qwen3-TTS worker, run with a Python that has ``qwen-tts`` installed (a separate venv: qwen-tts
needs a newer ``transformers`` than CosyVoice). Standalone: must not import folivox.

stdin: {"model": dir, "mode": "design"|"preset", "jobs": [{"text", "language", "instruct", "speaker",
        "seed", "out"}]}; writes one WAV per job and prints a JSON line per finished job.
"""

import json
import sys
import time

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

LANGS = {"ru": "Russian", "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German",
         "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese"}


def main():
    req = json.load(sys.stdin)
    if torch.cuda.is_available():
        dev, dtype = "cuda", torch.bfloat16
    elif torch.backends.mps.is_available():
        dev, dtype = "mps", torch.float32  # bf16 hits an MPSGraph assertion on Apple Silicon
    else:
        dev, dtype = "cpu", torch.float32
    model = Qwen3TTSModel.from_pretrained(req["model"], device_map=dev, dtype=dtype)
    for job in req["jobs"]:
        torch.manual_seed(job.get("seed", 0))
        lang = LANGS.get(job["language"], job["language"])
        t0 = time.time()
        if req["mode"] == "design":
            wavs, sr = model.generate_voice_design(text=job["text"], instruct=job["instruct"], language=lang)
        else:
            wavs, sr = model.generate_custom_voice(text=job["text"], speaker=job["speaker"], language=lang,
                                                   instruct=job.get("instruct") or None)
        sf.write(job["out"], wavs[0], sr)
        print(json.dumps({"out": job["out"], "seconds": time.time() - t0}), flush=True)


if __name__ == "__main__":
    main()
