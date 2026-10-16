"""CosyVoice 3 synthesis engine (vendored inference code, zero-shot voice cloning)."""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path

import numpy as np

from folivox.tts.base import Prefetcher, Synthesis, TTSEngine  # noqa: F401 — re-exported
from folivox.tts.voice import Voice
from folivox.tts.weights import ensure_llm, resolve_model_dir

# CosyVoice 3 expects an instruction prefix in front of the prompt transcript.
SYSTEM_PROMPT = "You are a helpful assistant.<|endofprompt|>"
MODEL_ID = "Fun-CosyVoice3-0.5B-2512"


def pick_device(requested: str = "auto") -> str:
    from folivox import gpu

    gpu.pin_cudnn()
    import torch

    if requested != "auto":
        return requested
    if torch.cuda.is_available() and gpu.cuda_skip_reason() is None:
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"  # hybrid: LLM + vocoder on CPU, flow on the GPU (see _move)
    return "cpu"


class CosyVoiceEngine(TTSEngine):
    name = "cosyvoice3"
    languages = ("ru", "en", "zh", "ja", "ko", "de", "es", "fr", "it")

    def __init__(self, model_dir: str | None = None, device: str = "auto", threads: int | None = None,
                 fp16: bool = False, llm: str = "rl"):
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        import torch

        for name in ("folivox.vendor", "root"):
            logging.getLogger(name).setLevel(logging.WARNING)
        # Qwen2 config noise ("Sliding Window Attention is enabled but not implemented"): CosyVoice never uses it
        logging.getLogger("transformers").setLevel(logging.ERROR)
        if threads:
            torch.set_num_threads(threads)
        self.device = pick_device(device)
        self.model_dir = str(resolve_model_dir(model_dir))
        t0 = time.time()
        from folivox.vendor.cosyvoice.cli.cosyvoice import CosyVoice3

        self.llm = llm
        llm_file = ensure_llm(Path(self.model_dir), llm)
        self._cv = CosyVoice3(self.model_dir, fp16=fp16 and self.device == "cuda", llm_file=llm_file)
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

    def generate_tokens(self, text: str, voice: Voice, seed: int = 0, lang: str = "") -> tuple[list[int], float]:
        """Stage 1 (LLM): text → speech tokens. Thread-safe w.r.t. :meth:`tokens_to_audio`. The model has no
        language parameter and reads the language of the text, so ``lang`` changes nothing here."""
        import torch

        spk = self.prepare_voice(voice)
        m = self._cv.model
        tokens, _ = self._cv.frontend._extract_text_token(text)
        inp = self._speakers[spk]
        uid = str(uuid.uuid4())
        with m.lock:
            m.tts_speech_token_dict[uid], m.llm_end_dict[uid] = [], False
        torch.manual_seed(seed)
        t0 = time.time()
        try:
            with torch.inference_mode():
                m.llm_job(tokens, inp["prompt_text"], inp["llm_prompt_speech_token"], inp["llm_embedding"], uid)
            return list(m.tts_speech_token_dict[uid]), time.time() - t0
        finally:
            with m.lock:
                m.tts_speech_token_dict.pop(uid, None)
                m.llm_end_dict.pop(uid, None)

    def tokens_to_audio(self, speech_tokens: list[int], voice: Voice, speed: float = 1.0) -> tuple[np.ndarray, float]:
        """Stage 2 (flow + vocoder): speech tokens → waveform."""
        import torch

        spk = self.prepare_voice(voice)
        m = self._cv.model
        inp = self._speakers[spk]
        if not speech_tokens:
            return np.zeros(0, np.float32), 0.0
        uid = str(uuid.uuid4())
        with m.lock:
            m.hift_cache_dict[uid] = None
        t0 = time.time()
        try:
            with torch.inference_mode():
                wav = m.token2wav(token=torch.tensor(speech_tokens).unsqueeze(0),
                                  prompt_token=inp["flow_prompt_speech_token"], prompt_feat=inp["prompt_speech_feat"],
                                  embedding=inp["flow_embedding"], token_offset=0, uuid=uid, finalize=True, speed=speed)
            return wav.squeeze(0).float().cpu().numpy().astype(np.float32), time.time() - t0
        finally:
            with m.lock:
                m.hift_cache_dict.pop(uid, None)

    prepare = generate_tokens
    finish = tokens_to_audio
