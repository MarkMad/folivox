"""CosyVoice 3 synthesis engine (vendored inference code, zero-shot voice cloning)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import numpy as np

from folivox.tts.voice import Voice
from folivox.tts.weights import resolve_model_dir

# CosyVoice 3 expects an instruction prefix in front of the prompt transcript.
SYSTEM_PROMPT = "You are a helpful assistant.<|endofprompt|>"
MODEL_ID = "Fun-CosyVoice3-0.5B-2512"


@dataclass
class Synthesis:
    audio: np.ndarray  # float32 mono
    sample_rate: int
    seconds: float  # wall time spent


def pick_device(requested: str = "auto") -> str:
    import torch

    if requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"  # hybrid: LLM + vocoder on CPU, flow on the GPU (see _move)
    return "cpu"


class CosyVoiceEngine:
    def __init__(self, model_dir: str | None = None, device: str = "auto", threads: int | None = None,
                 fp16: bool = False):
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        import torch

        for name in ("folivox.vendor", "root"):
            logging.getLogger(name).setLevel(logging.WARNING)
        if threads:
            torch.set_num_threads(threads)
        self.device = pick_device(device)
        self.model_dir = str(resolve_model_dir(model_dir))
        t0 = time.time()
        from folivox.vendor.cosyvoice.cli.cosyvoice import CosyVoice3

        self._cv = CosyVoice3(self.model_dir, fp16=fp16 and self.device == "cuda")
        if self.device not in ("cpu", "cuda"):
            self._move(self.device)
        self.sample_rate: int = self._cv.sample_rate
        self.load_seconds = time.time() - t0
        self._speakers: dict[str, dict] = {}

    def _move(self, device: str) -> None:
        import torch

        dev = torch.device(device)
        m = self._cv.model
        if dev.type == "mps":
            # Measured on M3 Pro: the flow-matching DiT is ~2.5x faster on MPS, while the
            # token-by-token LLM is ~3x slower there. The HiFT vocoder needs float64 and complex
            # iSTFT, which MPS lacks. So only the flow goes to the GPU.
            m.llm_device = torch.device("cpu")
            m.device = dev
            m.flow.to(dev)
        else:
            m.device = dev
            for part in (m.llm, m.flow, m.hift):
                part.to(dev)

    def prepare_voice(self, voice: Voice) -> str:
        """Extract prompt features once per voice; returns the speaker id."""
        if voice.id in self._speakers:
            return voice.id
        fe = self._cv.frontend
        inp = fe.frontend_zero_shot("", SYSTEM_PROMPT + voice.transcript, str(voice.wav), self.sample_rate, "")
        del inp["text"], inp["text_len"]
        self._speakers[voice.id] = inp
        return voice.id

    def synthesize(self, text: str, voice: Voice, seed: int = 0, speed: float = 1.0) -> Synthesis:
        import torch

        spk = self.prepare_voice(voice)
        fe = self._cv.frontend
        tokens, tokens_len = fe._extract_text_token(text)
        model_input = {**self._speakers[spk], "text": tokens, "text_len": tokens_len}
        torch.manual_seed(seed)
        np.random.seed(seed % (2**32))
        t0 = time.time()
        with torch.inference_mode():
            parts = [out["tts_speech"] for out in self._cv.model.tts(**model_input, stream=False, speed=speed)]
        audio = torch.cat(parts, dim=1).squeeze(0).float().cpu().numpy() if parts else np.zeros(0, np.float32)
        return Synthesis(audio.astype(np.float32), self.sample_rate, time.time() - t0)
