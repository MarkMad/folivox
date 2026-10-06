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
            out.append(f"Образец голоса длится {self.duration:.1f} с; лучше всего работает 6–15 с чистой речи.")
        return out


def audio_duration(path: Path) -> float:
    import soundfile as sf

    info = sf.info(str(path))
    return info.frames / info.samplerate


def load_voice(wav: str | Path, transcript: str | None = None, transcribe=None) -> Voice:
    """``transcript`` may be text, a path to a .txt file, or None (sibling .txt, else ``transcribe(wav)``)."""
    wav = Path(wav).expanduser()
    if not wav.exists():
        raise VoiceError(f"Файл голоса не найден: {wav}")
    try:
        duration = audio_duration(wav)
    except Exception as e:  # noqa: BLE001
        raise VoiceError(f"Не удалось прочитать аудио {wav}: {e}") from e
    if duration < MIN_SECONDS:
        raise VoiceError(f"Образец голоса слишком короткий ({duration:.1f} с), нужно 6–15 с.")
    if duration > MAX_SECONDS:
        raise VoiceError(f"Образец голоса слишком длинный ({duration:.1f} с), обрежьте до 6–15 с.")

    text = None
    if transcript:
        p = Path(transcript).expanduser()
        text = p.read_text(encoding="utf-8") if p.suffix == ".txt" and p.exists() else transcript
    elif wav.with_suffix(".txt").exists():
        text = wav.with_suffix(".txt").read_text(encoding="utf-8")
    elif transcribe is not None:
        text = transcribe(wav)
    if not text or not text.strip():
        raise VoiceError("Нужна расшифровка образца голоса: --voice-text \"…\" или файл рядом с .wav")
    return Voice(wav, " ".join(text.split()), duration)
