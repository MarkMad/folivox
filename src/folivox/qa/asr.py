"""Speech recognition backends for QA (see :data:`ASR`).

Local: mlx-whisper on Apple Silicon, faster-whisper elsewhere. Optional: any OpenAI-compatible
``/audio/transcriptions`` endpoint with the user's own key (audio leaves the machine).
"""

from __future__ import annotations

import io
import json
import os
import platform
import sys
import urllib.request
import uuid

import numpy as np

from folivox.providers import Registry

MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
FW_MODEL = "large-v3-turbo"


class ASRUnavailable(RuntimeError):
    pass


def _resample(audio: np.ndarray, sr: int, target: int = 16000) -> np.ndarray:
    if sr == target:
        return audio.astype(np.float32)
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(sr, target)
    return resample_poly(audio, target // g, sr // g).astype(np.float32)


_resample_16k = _resample


class ASR:
    """Transcribes float32 mono audio into text in ``language``."""

    name = ""

    def __init__(self, language: str = "ru"):
        self.language = language

    def transcribe(self, audio: np.ndarray, sample_rate: int, prompt: str | None = None) -> str:
        raise NotImplementedError

    def transcribe_file(self, path) -> str:
        import soundfile as sf

        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return self.transcribe(audio.mean(axis=1), sr)


class MLXWhisper(ASR):
    name = "mlx-whisper"

    def __init__(self, language: str = "ru", model: str | None = None):
        super().__init__(language)
        try:
            import mlx_whisper  # noqa: F401
        except ImportError as e:
            raise ASRUnavailable("mlx-whisper is not installed: pip install 'folivox[qa]'") from e
        self.model = model or MLX_MODEL
        from folivox.tts.weights import with_retries

        def fetch():
            from huggingface_hub import snapshot_download

            return snapshot_download(self.model)  # cached after the first time; later calls go offline-fast

        from folivox.tts.weights import watch_repo

        try:
            with watch_repo("Speech recognition model", self.model):
                self.model = with_retries(fetch, f"the speech-recognition model {self.model}")
        except ImportError:
            pass

    def transcribe(self, audio, sample_rate, prompt=None):
        import mlx_whisper

        r = mlx_whisper.transcribe(_resample(audio, sample_rate), path_or_hf_repo=self.model,
                                   language=self.language, condition_on_previous_text=False,
                                   initial_prompt=prompt, verbose=None)
        return r["text"].strip()


def _fw_repo(model: str) -> str | None:
    """The huggingface repo faster-whisper downloads for ``model`` (None for a local path or unknown name)."""
    if "/" in model:
        return None if os.path.isdir(model) else model
    try:
        from faster_whisper.utils import _MODELS

        return _MODELS.get(model)
    except ImportError:
        return None


class FasterWhisper(ASR):
    name = "faster-whisper"

    def __init__(self, language: str = "ru", model: str | None = None, device: str | None = None):
        super().__init__(language)
        from folivox import gpu

        # before ctranslate2 is imported, even for the CPU: on Windows it ships a bare cudnn64_9.dll of another
        # version, and once that is loaded torch's own cuDNN sub-libraries fail (cudnnGetLibConfig, error 127)
        gpu.pin_cudnn()
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise ASRUnavailable("faster-whisper is not installed: pip install 'folivox[qa]'") from e
        if device is None:
            try:
                from folivox import gpu

                device = gpu.whisper_device()
            except ImportError:
                device = "cpu"
        self.model = model or FW_MODEL
        # the first call downloads the model (~1.6 GB) from huggingface: retry network failures, resume parts
        from folivox.tts.weights import watch_repo, with_retries

        with watch_repo("Speech recognition model", _fw_repo(self.model)):
            self._fw = with_retries(lambda: WhisperModel(self.model, device=device,
                                                         compute_type="float16" if device == "cuda" else "int8"),
                                    f"the speech-recognition model {self.model}")

    def transcribe(self, audio, sample_rate, prompt=None):
        segments, _ = self._fw.transcribe(_resample(audio, sample_rate), language=self.language, beam_size=1,
                                          condition_on_previous_text=False, initial_prompt=prompt, vad_filter=False)
        return " ".join(s.text.strip() for s in segments).strip()


class OpenAIASR(ASR):
    """OpenAI-compatible transcription API. Costs money per minute; uses the user's own key."""

    name = "openai"

    def __init__(self, language: str = "ru", model: str = "gpt-4o-transcribe",
                 base_url: str = "https://api.openai.com/v1", api_key_env: str = "OPENAI_API_KEY"):
        from folivox.config import api_key

        super().__init__(language)
        self.model, self.base_url = model, base_url.rstrip("/")
        self.key = api_key(api_key_env, "openai ASR")

    def transcribe(self, audio, sample_rate, prompt=None):
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, _resample(audio, sample_rate), 16000, format="WAV", subtype="PCM_16")
        fields = {"model": self.model, "language": self.language, "response_format": "json"}
        if prompt:
            fields["prompt"] = prompt
        body, ctype = _multipart(fields, ("file", "audio.wav", buf.getvalue()))
        req = urllib.request.Request(f"{self.base_url}/audio/transcriptions", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["text"].strip()


def _multipart(fields: dict, file: tuple[str, str, bytes]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    name, filename, data = file
    out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
              f"Content-Type: application/octet-stream\r\n\r\n".encode())
    out.write(data + f"\r\n--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def auto(language: str = "ru", device: str | None = None, **kwargs) -> ASR:
    """mlx-whisper on Apple Silicon, faster-whisper elsewhere (``device="cpu"`` keeps it off the GPU)."""
    if sys.platform == "darwin" and platform.machine() == "arm64" and not os.environ.get("FOLIVOX_NO_MLX"):
        return MLXWhisper(language, **kwargs)
    return FasterWhisper(language, device=device, **kwargs)


def Transcriber(backend: str = "auto", model: str | None = None, language: str = "ru") -> ASR:  # noqa: N802
    """Backward-compatible constructor."""
    return ASR_PROVIDERS.create(backend, language=language, model=model)


ASR_PROVIDERS: Registry = Registry("asr", default="auto")
ASR_PROVIDERS.register("auto", auto, "mlx-whisper on Apple Silicon, faster-whisper elsewhere")
ASR_PROVIDERS.register("mlx-whisper", MLXWhisper, f"Whisper ({MLX_MODEL}) on Apple Silicon", needs="folivox[qa]")
ASR_PROVIDERS.register("faster-whisper", FasterWhisper, f"Whisper {FW_MODEL} via CTranslate2", needs="folivox[qa]")
ASR_PROVIDERS.register("openai", OpenAIASR, "OpenAI-compatible transcription API (your key, paid)", local=False,
                       needs="OPENAI_API_KEY")
