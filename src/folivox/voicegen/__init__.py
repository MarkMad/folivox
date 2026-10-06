"""Reference-voice generators (see :data:`GENERATORS`).

A generator reads a short text in a described ("design") or preset voice; the result becomes a
zero-shot prompt for the main TTS engine. Qwen3-TTS runs locally in its own Python environment;
commercial APIs are optional, use the user's own key, and their audio must never be bundled.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from folivox.providers import ProviderError, Registry

# Qwen3-TTS preset speakers and their native language (accent carries over into other languages).
QWEN_SPEAKERS = {
    "vivian": ("zh", "f"), "serena": ("zh", "f"), "uncle_fu": ("zh", "m"), "dylan": ("zh", "m"),
    "eric": ("zh", "m"), "ryan": ("en", "m"), "aiden": ("en", "m"), "ono_anna": ("ja", "f"), "sohee": ("ko", "f"),
}


@dataclass
class Job:
    text: str
    lang: str
    seed: int = 0
    description: str = ""  # natural-language voice description (design mode)
    speaker: str = ""  # preset speaker (preset mode)
    out: Path = field(default_factory=Path)


class VoiceGenerator:
    name = ""
    mode = "design"  # "design": described voice; "preset": named speakers
    license = ""  # license of the generated audio, recorded in the voice catalog
    local = True

    def generate(self, jobs: list[Job], progress=None) -> list[Path]:
        """Render every job to ``job.out`` (WAV). ``progress(job, seconds)`` after each one."""
        raise NotImplementedError

    def speakers(self) -> dict[str, tuple[str, str]]:
        return {}


class Qwen3TTS(VoiceGenerator):
    """Qwen3-TTS 12Hz 1.7B (Apache-2.0) run by ``qwen_worker.py`` in an external Python."""

    license = "Apache-2.0 (Qwen3-TTS model output)"

    def __init__(self, model: str, python: str | None = None, mode: str = "design"):
        self.mode = mode
        self.name = f"qwen3-{'voicedesign' if mode == 'design' else 'customvoice'}"
        self.model = str(Path(model).expanduser())
        self.python = str(Path(python or os.environ.get("FOLIVOX_QWEN_PYTHON", "python")).expanduser())
        if not Path(self.model).exists():
            raise ProviderError(f"{self.name}: model dir not found: {self.model}. Download "
                                f"Qwen/Qwen3-TTS-12Hz-1.7B-{'VoiceDesign' if mode == 'design' else 'CustomVoice'} "
                                f"and set [voicegen.{self.name}] model = \"…\" in the config")

    def speakers(self):
        return QWEN_SPEAKERS if self.mode == "preset" else {}

    def generate(self, jobs, progress=None):
        req = {"model": self.model, "mode": self.mode, "jobs": [
            {"text": j.text, "language": j.lang, "instruct": j.description, "speaker": j.speaker, "seed": j.seed,
             "out": str(j.out)} for j in jobs]}
        worker = Path(__file__).with_name("qwen_worker.py")
        env = {**os.environ, "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
        with tempfile.TemporaryFile("w+") as f:
            json.dump(req, f)
            f.seek(0)
            proc = subprocess.Popen([self.python, str(worker)], stdin=f, stdout=subprocess.PIPE, text=True, env=env)
            by_out = {str(j.out): j for j in jobs}
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if progress and msg.get("out") in by_out:
                    progress(by_out[msg["out"]], msg["seconds"])
            if proc.wait():
                raise ProviderError(f"{self.name}: worker failed (exit {proc.returncode}); is qwen-tts installed "
                                    f"for {self.python}?")
        return [j.out for j in jobs]


def qwen_design(model: str = "", python: str | None = None) -> Qwen3TTS:
    return Qwen3TTS(model or os.environ.get("FOLIVOX_QWEN_DESIGN_MODEL", ""), python, "design")


def qwen_custom(model: str = "", python: str | None = None) -> Qwen3TTS:
    return Qwen3TTS(model or os.environ.get("FOLIVOX_QWEN_CUSTOM_MODEL", ""), python, "preset")


class OpenAIVoice(VoiceGenerator):
    """OpenAI ``/audio/speech`` with style instructions. Paid, your key; the output is subject to the
    provider's terms — keep it local, never bundle or redistribute it."""

    name, mode, local = "openai", "preset", False
    license = "OpenAI API output — personal use, see provider terms"
    VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse")

    def __init__(self, model: str = "gpt-4o-mini-tts", base_url: str = "https://api.openai.com/v1",
                 api_key_env: str = "OPENAI_API_KEY"):
        from folivox.config import api_key

        self.model, self.base_url = model, base_url.rstrip("/")
        self.key = api_key(api_key_env, "openai voicegen")

    def speakers(self):
        return {v: ("en", "") for v in self.VOICES}

    def generate(self, jobs, progress=None):
        import time

        for j in jobs:
            t0 = time.time()
            payload = {"model": self.model, "input": j.text, "voice": j.speaker or "coral", "response_format": "wav"}
            if j.description:
                payload["instructions"] = j.description
            req = urllib.request.Request(f"{self.base_url}/audio/speech", data=json.dumps(payload).encode(),
                                         headers={"Authorization": f"Bearer {self.key}",
                                                  "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=300) as r:
                Path(j.out).write_bytes(r.read())
            if progress:
                progress(j, time.time() - t0)
        return [j.out for j in jobs]


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return audio.mean(axis=1), sr


GENERATORS: Registry = Registry("voicegen", default="qwen3-voicedesign")
GENERATORS.register("qwen3-voicedesign", qwen_design, "Qwen3-TTS 1.7B VoiceDesign: voice from a text description",
                    needs="qwen-tts in a separate venv")
GENERATORS.register("qwen3-customvoice", qwen_custom, "Qwen3-TTS 1.7B CustomVoice: 9 preset speakers (zh/en/ja/ko)",
                    needs="qwen-tts in a separate venv")
GENERATORS.register("openai", OpenAIVoice, "OpenAI TTS with style instructions (your key, paid; never bundle)",
                    local=False, needs="OPENAI_API_KEY")
