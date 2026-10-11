"""Commercial cloud TTS engines: ElevenLabs, OpenAI, Gemini API, Cartesia.

A thin adapter over the cloud *voice generators* in :mod:`folivox.voicegen.cloud_apis`, so the HTTP plumbing
(retries with ``Retry-After``, error mapping, ``model=auto``, key lookup) is shared. Differences from the local
engine: the voice is a provider voice id (:class:`CloudVoice`) instead of a reference recording, requests run
in a few parallel threads, and every request is billed, so the engine counts characters sent.

Everything sent here leaves the computer and is billed to the user's account. The audio is kept on this
computer and must never be bundled with Folivox. Add an engine by writing a ``CloudGenerator`` and calling
:func:`register_cloud_engine` (see CONTRIBUTING).
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass

import numpy as np

from folivox.providers import ProviderError
from folivox.tts.base import TTSEngine
from folivox.voicegen import Job

NEUTRAL_STYLE = "Neutral, steady audiobook narration. Read the text exactly as written."
# provider → default narration note (ElevenLabs reads bracketed tags as direction, so none by default)
DEFAULT_STYLE = {"openai": NEUTRAL_STYLE, "gemini": NEUTRAL_STYLE}
# Neither OpenAI nor Gemini has a language parameter: the language comes from the text, and their voices
# are English-native, so a non-English book gets an English accent unless the note asks for a native one.
ACCENT_NOTE = ("Speak {language} like a native speaker, with natural {language} pronunciation and intonation, "
               "never an English accent.")
NO_INSTRUCTIONS = ("tts-1", "tts-1-hd")  # OpenAI models that ignore the note
PARALLEL = {"elevenlabs": 3, "openai": 3, "gemini": 2, "cartesia": 3}  # simultaneous requests per provider
CHARS_PER_SECOND = 14  # narration pace used for audio-duration estimates
SPEED_NOTE = "Reading speed is not applied by cloud engines; the provider's own pace is used."


class CostCapReached(ProviderError):
    """The per-run spending cap would be exceeded; progress is saved and the run can be resumed."""


@dataclass(frozen=True)
class CloudVoice:
    """What the pipeline passes instead of a reference recording."""

    provider: str
    model: str
    speaker: str = ""  # provider voice id (preset) or the id of a voice made for this book
    style: str = ""
    mode: str = "preset"  # preset | design | localize | clone
    description: str = ""
    wav = None
    transcript = ""
    duration = 0.0
    warnings: tuple = ()

    @property
    def id(self) -> str:
        # cache key part: anything that changes how the text sounds must be here (never the temporary voice id)
        import hashlib

        h = hashlib.sha1(f"{self.mode}|{self.speaker}|{self.style}|{self.description}".encode()).hexdigest()[:12]
        return f"{self.provider}:{self.model}:{h}"


class CloudTTS(TTSEngine):
    local = False

    def __init__(self, provider: str, model: str = "auto", generator=None, parallel: int | None = None,
                 max_cost: float | None = None, **options):
        self.name = provider
        if generator is None:
            generator = generator_class(provider)(model=model or "auto", **{
                k: v for k, v in options.items() if k in ("transport", "sleep", "api_key", "api_key_env")})
        self.gen = generator
        self.parallel = parallel or PARALLEL.get(provider, 2)
        self.max_cost = max_cost
        self.languages = tuple(type(generator).languages)
        self.sample_rate = 24000
        self.device = "cloud"
        self._lock = threading.Lock()
        self.chars_sent = 0
        self.requests = 0

    # ---- facts the pipeline and UI need -----------------------------------------------------------
    @property
    def model(self) -> str:
        return self.gen.model

    @property
    def max_chars(self) -> int:
        limits = getattr(type(self.gen), "LIMITS", None)
        return (limits or {}).get(self.model, self.gen.max_chars)

    def estimate_usd(self, chars: int, mode: str = "preset") -> float | None:
        return type(self.gen).estimate_for(chars, 1, mode, self.model).get("usd")

    @property
    def spent_usd(self) -> float:
        return self.estimate_usd(self.chars_sent) or 0.0

    def check_budget(self, next_chars: int = 0) -> None:
        """Raise :class:`CostCapReached` when sending ``next_chars`` more would pass the cap."""
        if self.max_cost is None:
            return
        after = self.estimate_usd(self.chars_sent + next_chars)
        if after is not None and after > self.max_cost:
            raise CostCapReached(f"Spending cap ${self.max_cost:.2f} reached (≈ ${self.spent_usd:.2f} spent, "
                                 f"{self.chars_sent:,} characters sent). Progress is saved: raise --max-cost and "
                                 "run the same command again to continue.")

    # ---- synthesis --------------------------------------------------------------------------------
    def job(self, text: str, voice: CloudVoice, seed: int, lang: str = "") -> Job:
        return Job(text=text, lang=lang or self.lang, seed=seed, speaker=voice.speaker,
                   description=voice.style)

    lang = "en"

    def prepare(self, text, voice, seed=0):
        """The whole request happens here (in a worker thread); :meth:`finish` only decodes."""
        import time

        self.gen.check_text(text)
        self.check_budget(len(text))
        with self._lock:  # counted when sent: an in-flight request is already billed
            self.chars_sent += len(text)
            self.requests += 1
        t0 = time.time()
        wav = self.gen.synth(self.job(text, voice, seed))
        return wav, time.time() - t0

    def finish(self, prepared, voice, speed=1.0):
        return decode(prepared, self.sample_rate), 0.0

    def synthesize_audio(self, text, voice, seed, speed):
        wav, t = self.prepare(text, voice, seed)
        return self.finish(wav, voice, speed)[0], t

    # ---- voices -----------------------------------------------------------------------------------
    def speaker_for(self, wanted: str, lang: str | None = None) -> str:
        """A provider voice id from an id or a display name (case-insensitive); unknown ids pass through, so
        voices from the user's own library work."""
        if not wanted:
            return ""
        from folivox.voicegen.cloud import CloudError

        try:
            speakers = self.gen.speakers(lang)
        except CloudError as e:
            if e.kind == "auth":
                raise
            return wanted
        if wanted in speakers:
            return wanted
        names = {n.lower(): i for i, n in getattr(self.gen, "names", {}).items()}
        return names.get(wanted.lower(), wanted)

    def voice_modes(self) -> tuple[str, ...]:
        return voice_modes_of(type(self.gen))

    def make_voice(self, wanted: str = "", style: str | None = None, lang: str = "en", mode: str = "preset",
                   description: str = "", reference=None, remembered: str = "") -> CloudVoice:
        """Resolve the voice for a run. ``mode`` design / localize / clone creates a voice in the provider's
        account (the caller deletes it with :meth:`release`); ``remembered`` is the id made by an earlier,
        interrupted run."""
        self.lang = lang
        if mode not in self.voice_modes():
            raise ProviderError(f"{type(self.gen).label} has no {mode!r} voice mode for the book "
                                f"(available: {', '.join(self.voice_modes())})")
        self.gen.check_lang(lang)
        self.gen.mode = mode
        note = DEFAULT_STYLE.get(self.name, "") if style is None else style.strip()
        if not type(self.gen).style:
            note = ""
        warnings: list[str] = []
        if self.name in DEFAULT_STYLE and lang != "en":
            from folivox import lang as languages

            if self.model in NO_INSTRUCTIONS:
                warnings.append(f"{self.model} cannot be told to avoid an English accent; for "
                                f"{languages.get(lang).name} use gpt-4o-mini-tts")
            else:
                note = f"{ACCENT_NOTE.format(language=languages.get(lang).name)} {note}".strip()
        speaker = self.speaker_for(wanted, lang) if mode in ("preset", "localize") else ""
        if mode == "preset":
            return CloudVoice(self.name, self.model, speaker, note, "preset", warnings=tuple(warnings))
        if remembered:
            return CloudVoice(self.name, self.model, remembered, note, mode, description, warnings=tuple(warnings))
        job = Job(text="", lang=lang, speaker=speaker, description=description, reference=reference)
        made = self.gen.setup_voices([job])
        if not made:
            raise ProviderError(f"{type(self.gen).label} did not create a voice")
        return CloudVoice(self.name, self.model, job.speaker, note, mode, description, warnings=tuple(warnings))

    def release(self, voice: CloudVoice) -> None:
        """Delete a voice made for this run (a failure to delete is not an error: it only costs a slot)."""
        if voice.mode == "preset" or not voice.speaker:
            return
        try:
            self.gen.teardown_voices([voice.speaker])
        except ProviderError:
            pass


def voice_modes_of(cls) -> tuple[str, ...]:
    """Modes usable for a whole book: preset, plus the ones that create a voice in the account."""
    from folivox.voicegen.cloud import CloudGenerator

    can_create = cls.setup_voices is not CloudGenerator.setup_voices
    return tuple(m for m in cls.modes if m == "preset" or can_create)


def decode(wav: bytes, rate: int = 24000) -> np.ndarray:
    import soundfile as sf

    from folivox.voicegen.cloud import to_wav

    audio, sr = sf.read(io.BytesIO(to_wav(wav)), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if sr != rate and len(audio):
        n = int(round(len(audio) * rate / sr))
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def generator_class(provider: str):
    from folivox.voicegen.cloud import cloud_providers

    cls = cloud_providers().get(provider)
    if cls is None:
        raise ProviderError(f"No cloud engine {provider!r}")
    return cls


def make_engine(provider: str):
    def factory(model: str = "auto", **options) -> CloudTTS:
        options.pop("device", None)
        return CloudTTS(provider, model=model, **options)

    factory.__qualname__ = f"engine_{provider}"
    return factory


# One module-level factory per provider, importable as "folivox.tts.cloud:<name>".
elevenlabs, openai, gemini, cartesia = (make_engine(n) for n in ("elevenlabs", "openai", "gemini", "cartesia"))


def register_cloud_engine(name: str, description: str, key_env: str, target: str | None = None) -> None:
    from folivox.tts import ENGINES

    ENGINES.register(name, target or f"folivox.tts.cloud:{name}", description, local=False, needs=key_env)
