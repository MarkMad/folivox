"""Reference voice for zero-shot cloning: a short clean recording plus its transcript."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

MIN_SECONDS, MAX_SECONDS = 3.0, 30.0
# Recommended sample length (s) per engine family. NOT MEASURED: the numbers come from the engines' own documentation
# (CosyVoice 3 prompt audio: 6-15 s is its sweet spot and the frontend asserts <= 30 s; Fish Audio S2 Pro / Drama 3:
# 10-30 s in the fish-speech docs). A clone-quality comparison (CER, by ear) on 10/20/30 s cuts is still to be done;
# change this table, nothing else, when it shows a different optimum. MAX_SECONDS stays the hard limit for all.
GOOD_RANGES = {"default": (6.0, 15.0), "fish": (10.0, 30.0)}
GOOD_RANGE = GOOD_RANGES["default"]


def good_range(engine: str | None = None) -> tuple[float, float]:
    """Recommended sample length in seconds for a TTS engine id (``fish-s2``, ``fish``, ``cosyvoice3``…)."""
    family = (engine or "").split("-")[0]
    return GOOD_RANGES.get(family, GOOD_RANGES["default"])


def _fmt(x: float) -> str:
    return f"{x:g}"


class VoiceError(ValueError):
    pass


@dataclass(frozen=True)
class Voice:
    wav: Path
    transcript: str
    duration: float

    @cached_property
    def id(self) -> str:
        h = hashlib.sha1(self.wav.read_bytes())
        h.update(self.transcript.encode())
        return h.hexdigest()[:16]

    @property
    def warnings(self) -> list[str]:
        return self.warnings_for(None)

    def warnings_for(self, engine: str | None) -> list[str]:
        lo, hi = good_range(engine)
        if lo <= self.duration <= hi:
            return []
        return [f"The voice sample is {self.duration:.1f} s long; {_fmt(lo)}–{_fmt(hi)} s of clean speech works best."]


# Letters per second of ordinary speech; far outside this the text is not what the recording says
# (a transcript of a longer original, a cut-off one, or a recogniser run in the wrong language).
_RATE = {"alpha": (4.0, 22.0), "cjk": (1.2, 11.0)}
_CJK = {"zh", "ja", "ko"}


def _script_of(ch: str) -> str:
    o = ord(ch)
    if 0x0400 <= o <= 0x052F:
        return "cyrillic"
    if 0x3040 <= o <= 0x30FF:
        return "kana"
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
        return "hangul"
    if 0x4E00 <= o <= 0x9FFF:
        return "han"
    if ch.isascii() or 0x00C0 <= o <= 0x024F:
        return "latin"
    return "other"


_EXPECTED = {"ru": {"cyrillic"}, "ja": {"han", "kana"}, "zh": {"han"}, "ko": {"hangul", "han"}}


def transcript_warnings(text: str, duration: float, lang: str) -> list[str]:
    """Hints that the transcript does not belong to the recording or is in another language than ``lang``."""
    letters = [c for c in text if c.isalpha()]
    if not letters or duration <= 0:
        return []
    out = []
    kind = "cjk" if lang in _CJK else "alpha"
    rate = len(letters) / duration
    lo, hi = _RATE[kind]
    if rate > hi:
        out.append(f"The transcript is too long for a {duration:.0f} s recording ({len(letters)} letters): it may be "
                   "the text of a longer original. Clone quality drops when text and audio differ.")
    elif rate < lo:
        out.append(f"The transcript is too short for a {duration:.0f} s recording ({len(letters)} letters): "
                   "part of the speech is not in the text. Clone quality drops when text and audio differ.")
    expected = _EXPECTED.get(lang, {"latin"})
    share = sum(_script_of(c) in expected for c in letters) / len(letters)
    if share < 0.6:
        out.append(f"The transcript does not look like the sample language ({lang}): the speech recogniser may have "
                   "been run in the wrong language. Choose the language of the sample and transcribe again.")
    return out


def audio_duration(path: Path) -> float:
    import soundfile as sf

    info = sf.info(str(path))
    return info.frames / info.samplerate


def load_voice(wav: str | Path, transcript: str | None = None, transcribe=None) -> Voice:
    """``transcript`` may be text, a path to a .txt file, or None (sibling .txt, else ``transcribe(wav)``)."""
    wav = Path(wav).expanduser()
    if not wav.exists():
        raise VoiceError(f"Voice file not found: {wav}")
    try:
        duration = audio_duration(wav)
    except Exception as e:  # noqa: BLE001
        raise VoiceError(f"Cannot read audio {wav}: {e}") from e
    if duration < MIN_SECONDS:
        raise VoiceError(f"The voice sample is too short ({duration:.1f} s); at least {MIN_SECONDS:g} s is needed.")
    if duration > MAX_SECONDS:
        raise VoiceError(f"The voice sample is too long ({duration:.1f} s); at most {MAX_SECONDS:g} s, trim it.")

    text = None
    if transcript:
        p = Path(transcript).expanduser()
        text = p.read_text(encoding="utf-8") if p.suffix == ".txt" and p.exists() else transcript
    elif wav.with_suffix(".txt").exists():
        text = wav.with_suffix(".txt").read_text(encoding="utf-8")
    elif transcribe is not None:
        text = transcribe(wav)
    if not text or not text.strip():
        raise VoiceError("A transcript of the voice sample is needed: --voice-text \"…\" or a .txt next to it")
    return Voice(wav, " ".join(text.split()), duration)
