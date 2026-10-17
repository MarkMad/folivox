"""Reference voice for zero-shot cloning: a short clean recording plus its transcript."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

MIN_SECONDS, MAX_SECONDS = 3.0, 30.0
GOOD_RANGE = (6.0, 15.0)


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
        out = []
        if not GOOD_RANGE[0] <= self.duration <= GOOD_RANGE[1]:
            out.append(f"The voice sample is {self.duration:.1f} s long; 6–15 s of clean speech works best.")
        return out


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
        raise VoiceError(f"The voice sample is too short ({duration:.1f} s); 6–15 s is needed.")
    if duration > MAX_SECONDS:
        raise VoiceError(f"The voice sample is too long ({duration:.1f} s); trim it to 6–15 s.")

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
